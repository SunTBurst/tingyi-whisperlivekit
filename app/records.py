"""Stable captions, native WhisperLiveKit snapshots, and portable records."""
import copy
import json
import os
import uuid
from datetime import datetime
from pathlib import Path


def _seconds(value, default=0.0):
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return default
    if ':' in text:
        try:
            total = 0.0
            for piece in text.replace(chr(44), chr(46)).split(':'):
                total = total * 60 + float(piece)
            return total
        except ValueError:
            return default
    try:
        return float(text)
    except ValueError:
        return default


def _plain(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if hasattr(value, '__dict__'):
        return {k: _plain(v) for k, v in vars(value).items() if not k.startswith('_')}
    return str(value)


def _translation_text(value):
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ('text', 'translation', 'translated_text'):
            if value.get(key):
                return _translation_text(value[key])
        return ''.join(filter(None, (_translation_text(item) for item in value.values())))
    if isinstance(value, (list, tuple)):
        return ''.join(filter(None, (_translation_text(item) for item in value))).strip()
    if hasattr(value, 'text'):
        return _translation_text(getattr(value, 'text'))
    return ''


def _speaker_key(speaker):
    return str(speaker) if speaker is not None else None


def _is_known_speaker(speaker):
    return speaker not in (None, -1, 0, -2, '-1', '0', '-2')


class CaptionStore:
    def __init__(self):
        self._rows = {}
        self._speaker_names = {}
        self.snapshot = {}
        self._native_lines = []
        self._active_ids = set()
        self._pruned_ordinals = {}
        self.last_removed = []

    def _identity_for(self, line, ordinal=0):
        start = max(0.0, _seconds(line.get('start')))
        stamp=f'{start:.3f}'
        return f"{stamp}:{ordinal+self._pruned_ordinals.get(stamp,0)}", start

    def _upsert(self, line, ordinal=0):
        native = _plain(line)
        text = str(native.get('text') or '').strip()
        speaker = native.get('speaker')
        if not text or speaker in (-2, '-2'):
            return None, False
        row_id, start = self._identity_for(native, ordinal)
        end = max(start + .01, _seconds(native.get('end'), start))
        previous = self._rows.get(row_id)
        native_translation = _translation_text(native.get('translation'))
        if not native_translation and native.get('translations'):
            native_translation = _translation_text(native.get('translations'))
        translation = native_translation
        if previous:
            if text == previous['source'] and not native_translation:
                translation = previous.get('translation', '')
            elif text != previous['source'] and not native_translation:
                translation = ''
        language = native.get('detected_language') or (previous or {}).get('language')
        row = {
            'id': row_id, 'source': text, 'translation': translation,
            'start': start, 'end': end, 'language': language,
            'speaker': speaker, 'speaker_name': self._speaker_names.get(_speaker_key(speaker)),
            'native': native, 'raw': copy.deepcopy(native),
        }
        changed = previous is None or any(previous.get(k) != row.get(k) for k in ('source', 'speaker', 'end', 'translation'))
        self._rows[row_id] = row
        return row, changed

    def ingest(self, lines):
        changed = []
        same_start_counts = {}
        for line in lines:
            stamp = f"{max(0.0, _seconds(line.get('start'))):.3f}"
            ordinal = same_start_counts.get(stamp, 0)
            same_start_counts[stamp] = ordinal + 1
            row, did_change = self._upsert(line, ordinal)
            if row is not None and did_change:
                changed.append(copy.deepcopy(row))
        return changed

    def ingest_snapshot(self, payload: dict):
        """Apply the native full snapshot or append/prune diff message.

        Upstream emits a snapshot with all lines, then diffs containing
        lines_pruned, new_lines, n_lines and the current buffer/status fields.
        Explicit lines_added/updated/removed keys are accepted as adapters too.
        """
        if not isinstance(payload, dict):
            raise TypeError('payload must be a dict')
        payload = _plain(payload)
        kind = payload.get('type')
        # Rows are replaced by _upsert. Keep references for only the live
        # protocol window rather than deep-copying the entire meeting.
        before = {key:self._rows[key] for key in self._active_ids if key in self._rows}
        self.last_removed=[]
        if kind == 'snapshot' or ('lines' in payload and kind not in ('diff', 'update')):
            self.snapshot = {k: copy.deepcopy(v) for k, v in payload.items() if k not in ('type', 'seq')}
            self._native_lines = copy.deepcopy(payload.get('lines') or [])
        else:
            protocol_fields = {'type', 'seq', 'n_lines', 'lines_pruned', 'new_lines',
                               'lines_added', 'lines_updated', 'lines_removed'}
            for key, value in payload.items():
                if key != 'lines' and key not in protocol_fields:
                    self.snapshot[key] = copy.deepcopy(value)
            remove_count = max(0, int(payload.get('lines_pruned') or 0))
            if remove_count:
                # Server retention removes protocol lines, including silence.
                # Already displayed speech remains in the desktop archive.
                pruned = self._native_lines[:remove_count]
                stamps = {}
                for line in pruned:
                    stamp=f"{max(0.,_seconds(line.get('start'))):.3f}"
                    ordinal=stamps.get(stamp,0)
                    stamps[stamp]=ordinal+1
                    self._active_ids.discard(self._identity_for(line,ordinal)[0])
                for stamp,count in stamps.items():
                    self._pruned_ordinals[stamp]=self._pruned_ordinals.get(stamp,0)+count
                self._native_lines = self._native_lines[remove_count:]
            for item in payload.get('lines_removed') or []:
                row_id = item.get('id') if isinstance(item, dict) else item
                if self._rows.pop(row_id, None) is not None: self.last_removed.append(row_id)
            for item in payload.get('lines_updated') or []:
                if isinstance(item, dict):
                    self._upsert(item)
            added = list(payload.get('new_lines') or payload.get('lines_added') or [])
            if 'n_lines' in payload:
                keep = max(0,int(payload['n_lines'])-len(added))
                self._native_lines = self._native_lines[:keep]+added
            else:
                self._native_lines.extend(added)
        current_ids=set()
        stamps={}
        for line in self._native_lines:
            stamp=f"{max(0.,_seconds(line.get('start'))):.3f}"
            ordinal=stamps.get(stamp,0)
            stamps[stamp]=ordinal+1
            row,_ = self._upsert(line,ordinal)
            if row is not None: current_ids.add(row['id'])
        for row_id in self._active_ids-current_ids:
            self._rows.pop(row_id,None)
            self.last_removed.append(row_id)
        self._active_ids=current_ids
        self.snapshot['lines']=copy.deepcopy(self._native_lines)
        return [copy.deepcopy(self._rows[key]) for key in current_ids if before.get(key) != self._rows[key]]

    def apply_translation(self, row_id, expected_source, translated):
        row = self._rows.get(row_id)
        if row is None or row['source'] != expected_source:
            return False
        row['translation'] = translated
        return True

    def rename_speaker(self, speaker, name):
        key = _speaker_key(speaker)
        if key is None:
            return False
        if name is None or not str(name).strip():
            self._speaker_names.pop(key, None)
            display = None
        else:
            display = str(name).strip()
            self._speaker_names[key] = display
        for row in self._rows.values():
            if _speaker_key(row.get('speaker')) == key:
                row['speaker_name'] = display
        return True

    def rows(self):
        return [copy.deepcopy(row) for row in sorted(self._rows.values(), key=lambda r: (r['start'], r['id']))]


def srt_time(seconds):
    milliseconds = max(0, round(float(seconds) * 1000))
    hours, remainder = divmod(milliseconds, 3600000)
    minutes, remainder = divmod(remainder, 60000)
    secs, ms = divmod(remainder, 1000)
    return f'{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}'


def _speaker_label(row):
    speaker = row.get('speaker')
    if not _is_known_speaker(speaker):
        return None
    if row.get('speaker_name'):
        return str(row['speaker_name'])
    return f'Speaker {speaker}'


def _source_line(row):
    label = _speaker_label(row)
    return f'{label}: {row["source"]}' if label else row['source']


def _native_rows(rows):
    result = []
    for row in rows:
        native = row.get('native') or row.get('raw')
        if native:
            result.append(copy.deepcopy(native))
        else:
            native = {'start': row.get('start', 0), 'end': row.get('end', 0),
                      'text': row.get('source', ''), 'speaker': row.get('speaker', -1)}
            if row.get('translation'):
                native['translation'] = row['translation']
            result.append(native)
    return result


def _translation_status(row):
    if row.get('translation_error'):
        return 'error'
    if row.get('translation_pending'):
        return 'pending'
    if row.get('translation_stale'):
        return 'stale'
    return 'ready' if row.get('translation') else 'none'


def _translation_binding(row):
    return {key: row.get(key) for key in (
        'translation_source_text', 'translation_source_revision', 'translation_text_revision',
        'translation_provider', 'translation_model', 'translation_error') if key in row}


def _verbose_json(rows, source_mode='corrected'):
    words, segments, texts, languages = [], [], [], []
    for index, row in enumerate(rows):
        source = row.get('source', '')
        if source:
            texts.append(source)
        if row.get('language') and row['language'] not in languages:
            languages.append(row['language'])
        label = _speaker_label(row)
        segment = {'id': index, 'start': row['start'], 'end': row['end'], 'text': source}
        segment.update(source_mode=source_mode, translation_status=_translation_status(row),
                       translation_stale=bool(row.get('translation_stale', False)),
                       translation_pending=bool(row.get('translation_pending', False)),
                       **_translation_binding(row))
        if row.get('source_original') is not None:
            segment.update(source_original=row['source_original'],source_corrected=row.get('source_corrected',source),
                           glossary_revision=row.get('glossary_revision'),participant_id=row.get('participant_id'))
        if label:
            segment['speaker'] = label
        if row.get('translation'):
            segment['translation'] = row['translation']
        segments.append(segment)
        native = row.get('native') or row.get('raw') or {}
        for word in native.get('words') or native.get('tokens') or []:
            if not isinstance(word, dict):
                word = _plain(word)
            text = word.get('word') or word.get('text') or word.get('token')
            if text and word.get('start') is not None and word.get('end') is not None:
                words.append({'word': str(text).strip(), 'start': _seconds(word['start']), 'end': _seconds(word['end'])})
    return {'task': 'transcribe', 'source_mode':source_mode,
            'words_source':'original_asr','language': languages[0] if languages else 'unknown',
            'text': ' '.join(texts).strip(), 'words': words, 'segments': segments}


def _native_document(rows, snapshot=None):
    if snapshot:
        doc = copy.deepcopy(snapshot)
        doc['lines'] = _native_rows(rows)
        return doc
    return {'status': '', 'lines': _native_rows(rows), 'buffer_transcription': '',
            'buffer_diarization': '', 'buffer_translation': '',
            'remaining_time_transcription': 0, 'remaining_time_transcription_processing': 0,
            'remaining_time_transcription_policy': 0, 'remaining_time_diarization': 0,
            'translation_error': ''}


def export_rows(rows, path, format='txt', snapshot=None, *, source_mode='corrected'):
    target = Path(path)
    normalized = format.lower().lstrip('.')
    if source_mode not in ('corrected', 'original'):
        raise ValueError('source_mode must be corrected or original')
    if source_mode=='original' and normalized not in ('json','native_json','original_json','whisperlivekit_json'):
        original_rows=[]
        for row in rows:
            original=row.get('source_original',row['source'])
            if row.get('source_original') is not None:
                native_translation=_translation_text((row.get('native') or {}).get('translation',''))
                original_rows.append({**row,'source':original,'translation':native_translation,
                                      'translation_source_text':original,'translation_pending':False,
                                      'translation_source_revision':None,'translation_text_revision':None,
                                      'translation_provider':'native','translation_stale':False,
                                      'translation_error':''})
            else:
                original_rows.append({**row,'source':original})
        rows=original_rows
    aliases = {'json': 'native_json', 'original_json': 'native_json',
               'whisperlivekit_json': 'native_json', 'verbose-json': 'verbose_json'}
    normalized = aliases.get(normalized, normalized)
    if normalized == 'native_json':
        contents = json.dumps(_native_document(rows, snapshot), ensure_ascii=False, indent=2) + '\n'
    elif normalized == 'diarized_json':
        segments=[]
        for r in rows:
            segments.append({'id':r['id'],'start':r['start'],'end':r['end'],'text':r['source'],
                             'source_mode':source_mode,
                             'source_original':r.get('source_original'),
                             'source_corrected':r.get('source_corrected'),
                             'glossary_revision':r.get('glossary_revision'),
                             'speaker':r.get('speaker'),'speaker_name':r.get('speaker_name'),
                             'participant_id':r.get('participant_id'),'speaker_namespace':r.get('speaker_namespace'),
                             'participant_pending':r.get('participant_pending',False),
                             'translation':r.get('translation',''),
                             'translation_status':_translation_status(r),
                             'translation_stale':bool(r.get('translation_stale',False)),
                             'translation_pending':bool(r.get('translation_pending',False)),
                             **_translation_binding(r)})
        contents=json.dumps({'task':'transcribe','source_mode':source_mode,'segments':segments},ensure_ascii=False,indent=2)+'\n'
    elif normalized == 'verbose_json':
        contents = json.dumps(_verbose_json(rows,source_mode), ensure_ascii=False, indent=2) + '\n'
    elif normalized in ('txt', 'srt', 'vtt'):
        blocks = []
        for index, row in enumerate(rows, 1):
            start, end = _seconds(row.get('start')), _seconds(row.get('end'))
            if normalized == 'srt':
                blocks.extend([str(index), f'{srt_time(start)} --> {srt_time(end)}'])
            elif normalized == 'vtt':
                blocks.append(f'{srt_time(start).replace(chr(44), chr(46))} --> {srt_time(end).replace(chr(44), chr(46))}')
            else:
                blocks.append(f'[{srt_time(start).replace(chr(44), chr(46))}]')
            source_mode_label='原始听写' if source_mode=='original' else '纠错后文本'
            blocks.append(source_mode_label+'：'+_source_line(row))
            translation_status=_translation_status(row)
            if row.get('translation') or translation_status in ('error','pending','stale'):
                label = _speaker_label(row)
                translated = str(row.get('translation') or '')
                if translation_status in ('pending','stale'):
                    translated='译文待更新'+('：'+translated if translated else '')
                elif translation_status=='error':
                    detail=str(row.get('translation_error') or '').strip()
                    translated='译文未完成'+(('（'+detail+'）') if detail else '')+('：'+translated if translated else '')
                blocks.append(f'{label}: {translated}' if label else translated)
            blocks.append('')
        contents = ('WEBVTT\n\n' if normalized == 'vtt' else '') + '\n'.join(blocks)
        if blocks:
            contents += '\n'
    else:
        raise ValueError('不支持的导出格式')
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(contents, encoding='utf-8')



class Journal:
    def __init__(self, folder, settings, *, path=None):
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        self.path = Path(path) if path else folder / (datetime.now().strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:6] + '.json')
        from app.settings import redact_settings
        self.metadata = {'created_at': datetime.now().isoformat(timespec='seconds'), 'settings': redact_settings(settings)}
        self.native_snapshot = None
        self.store=None
        if path:
            document=read_record(path)
            _backup_invalid_manifest(self.path)
            self.metadata={key:value for key,value in document.items() if key not in ('rows','native_snapshot','events')}
            self.native_snapshot=document.get('native_snapshot')
        if settings.get('long_meeting_mode',False):
            from app.meeting_store import MeetingStore
            self.store=MeetingStore(self.path,self.metadata)
            if path:
                self.store.upsert(document.get('rows',[]))
                for event in document.get('events',[]): self.store.event(event)
                self.store.metadata.update(self.metadata)

    def save(self, rows, snapshot=None, native_snapshot=None):
        if self.store:
            self.save_changes(rows,snapshot=snapshot if native_snapshot is None else native_snapshot)
            return
        temporary = self.path.with_suffix('.tmp')
        document = {**self.metadata, 'rows': rows}
        selected = native_snapshot if native_snapshot is not None else snapshot
        if selected is not None:
            document['native_snapshot'] = selected
            self.native_snapshot = copy.deepcopy(selected)
        temporary.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(temporary, self.path)

    def save_changes(self,rows,*,snapshot=None,removed=(),extra=None):
        if not self.store:
            raise RuntimeError('增量保存需要开启长会议模式')
        self.store.upsert(rows,removed=removed)
        if snapshot is not None: self.native_snapshot=snapshot
        self.metadata.update(extra or {})
        self.store.checkpoint({**self.metadata,'native_snapshot':self.native_snapshot})

    def close(self):
        if self.store: self.store.close()


def read_record(path):
    """Load both prior rows-only journals and extended native records."""
    from app.meeting_store import load_meeting
    return load_meeting(path)


def _backup_invalid_manifest(path):
    """Preserve broken manifest bytes before an intentional repair/write."""
    path=Path(path)
    try: json.loads(path.read_text(encoding='utf-8-sig'))
    except (ValueError,UnicodeError):
        backup=path.with_name(path.name+'.corrupt-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6]+'.bak')
        backup.write_bytes(path.read_bytes())


def update_record(path,*,rows=None,participant_state=None,snapshot=None):
    """Persist deliberate edits to a closed meeting, preserving native data."""
    path=Path(path)
    document=read_record(path)
    _backup_invalid_manifest(path)
    if participant_state is not None: document['participant_state']=participant_state
    if snapshot is not None: document['native_snapshot']=snapshot
    if rows is not None: document['rows']=rows
    if document.get('storage',{}).get('type')=='sqlite':
        from app.meeting_store import MeetingStore
        store=MeetingStore(path,create=False)
        try:
            if rows is not None: store.upsert(rows)
            store.checkpoint({key:value for key,value in document.items() if key not in ('rows','events')})
        finally: store.close()
    else:
        temporary=path.with_suffix('.tmp')
        temporary.write_text(json.dumps(document,ensure_ascii=False,indent=2),encoding='utf-8')
        os.replace(temporary,path)
