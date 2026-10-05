"""One process, one model configuration, one safely closed WLK session."""
import asyncio
import logging
import threading
import time
from copy import deepcopy
from pathlib import Path

from app.records import CaptionStore, Journal, _seconds
from app.settings import ROOT
from app.wlk_config import config_values

log = logging.getLogger(__name__)


class SessionControl:
    def __init__(self):
        self.paused = threading.Event()
        self.stopped = threading.Event()
        self.speaker_names = {}
        self._lock = threading.Lock()
        self._settings = None
        self.revision = 0
        self._actions=[]

    def configure(self,settings):
        with self._lock:
            if self._settings is None: self._settings=deepcopy(settings)

    def snapshot(self):
        with self._lock:
            return self.revision,dict(self._settings) if self._settings is not None else None

    def update_languages(self,settings):
        with self._lock:
            if self.stopped.is_set(): return
            self._settings=dict(self._settings)
            for key in ('source_language','target_language','mic_language','mic_target_language'):
                if key in settings: self._settings[key]=settings[key]
            self.revision+=1

    def update_options(self,settings):
        keys=('glossary_enabled','glossary_rules','llm_url','llm_model','llm_api_token',
              'llm_timeout','llm_context_chars','llm_fallback','translation_mode')
        with self._lock:
            if self.stopped.is_set(): return
            self._settings={**self._settings,**{key:deepcopy(settings[key]) for key in keys if key in settings}}
            self.revision+=1

    def enqueue_action(self,action):
        with self._lock: self._actions.append(deepcopy(action))

    def drain_actions(self):
        with self._lock:
            actions,self._actions=self._actions,[]
            return actions

    def resume(self,settings):
        with self._lock:
            if self.stopped.is_set(): return
            self._settings=deepcopy(settings)
            self.revision+=1
            self.paused.clear()

    def request(self, command):
        if command == 'stop':
            self.stopped.set()
        elif command == 'pause' and not self.stopped.is_set():
            if self.paused.is_set():
                self.paused.clear()
            else:
                self.paused.set()


async def capture_chunks(settings, emit, control, audio_file=None, realtime=True,
                         *, pause_as_eof=False, media_state=None):
    import numpy as np
    from app.audio import AudioCapture, _to_mono_resampled
    capture = None
    expected_sample=0
    async def captured_packet(timeout):
        nonlocal expected_sample
        if hasattr(capture,'get_packet'):
            packet=await asyncio.to_thread(capture.get_packet,timeout)
            if packet is None: return None,0
            samples,start=packet
        else:
            samples=await asyncio.to_thread(capture.get_chunk,timeout)
            if samples is None: return None,0
            start=expected_sample
        gap=max(0,int(start)-expected_sample)
        if gap:
            emit({'type':'audio_gap','start_sample':expected_sample,'samples':gap,'seconds':round(gap/16000,3),
                  'message':f'采集缓冲溢出，约 {gap/16000:.2f} 秒声音缺失，记录已标记'})
        expected_sample=int(start)+len(samples)
        return samples,gap

    def gap_chunks(samples):
        # Silence carries elapsed sample positions only, never invented words.
        for offset in range(0,samples,8000):
            yield np.zeros(min(8000,samples-offset),dtype=np.float32)
    async def chunks():
        nonlocal capture,expected_sample
        started = time.monotonic()
        active_duration = 0.0
        last_tick = started
        tick_sent = -1
        audio = None
        offset = (media_state or {}).get('offset',0)
        is_open = False
        paused_reported = False
        if audio_file:
            from whisperlivekit.test_harness import load_audio_pcm
            audio=(media_state or {}).get('audio')
            if audio is None:
                pcm = await asyncio.to_thread(load_audio_pcm,str(audio_file))
                audio = np.frombuffer(pcm,dtype='<i2').astype(np.float32)/32768.
                if media_state is not None: media_state['audio']=audio
        else:
            capture = AudioCapture(settings['source_mode'], settings.get('output_device'), settings.get('mic_device'))
        try:
            while not control.stopped.is_set():
                now = time.monotonic()
                if not control.paused.is_set():
                    active_duration += now - last_tick
                last_tick = now
                if control.paused.is_set():
                    if is_open:
                        if capture:
                            await asyncio.to_thread(capture.stop)
                            # Preserve samples captured before pause, including a
                            # phrase tail that would otherwise be cleared on resume.
                            while True:
                                tail,gap = await captured_packet(0)
                                if tail is None:
                                    break
                                for silence in gap_chunks(gap): yield silence
                                yield tail
                        is_open = False
                    if pause_as_eof:
                        return
                    if not paused_reported:
                        emit({'type':'state', 'state':'paused'})
                        emit({'type':'level', 'value':0})
                        paused_reported = True
                    await asyncio.sleep(.05)
                    continue
                if not is_open:
                    if capture:
                        await asyncio.to_thread(capture.start)
                        expected_sample=0
                    is_open = True
                    paused_reported = False
                    if not pause_as_eof: emit({'type':'state', 'state':'running'})
                if audio is not None:
                    if offset >= len(audio):
                        break
                    chunk = audio[offset:offset+8000]
                    offset += len(chunk)
                    if media_state is not None: media_state['offset']=offset
                    if realtime:
                        await asyncio.sleep(len(chunk) / 16000)
                else:
                    chunk,gap = await captured_packet(.2)
                    if capture.error:
                        raise RuntimeError(f'音频设备异常：{capture.error}')
                    if chunk is None:
                        # A heartbeat allows language changes to close a quiet
                        # stream without waiting for the next spoken sample.
                        if pause_as_eof: yield np.empty(0,dtype=np.float32)
                        continue
                    for silence in gap_chunks(gap): yield silence
                emit({'type':'level', 'value':min(1.0, float(np.sqrt(np.mean(chunk ** 2))) * 5)})
                if not pause_as_eof and int(active_duration) != tick_sent:
                    tick_sent = int(active_duration)
                    emit({'type':'elapsed', 'seconds':tick_sent})
                yield chunk
            if capture and is_open:
                await asyncio.to_thread(capture.stop)
                is_open = False
                # Drain audio already captured before the stop command.
                while True:
                    tail,gap = await captured_packet(0)
                    if tail is None:
                        break
                    for silence in gap_chunks(gap): yield silence
                    yield tail
        finally:
            if capture:
                await asyncio.to_thread(capture.stop)

    async for chunk in chunks():
        yield chunk


async def run_session(settings, emit, control, audio_file=None, realtime=True):
    from app.native_client import stream_native
    from app.settings import redact_settings
    from app.participants import ParticipantRegistry
    from app.glossary import Glossary
    from app.records import read_record
    from app.session_postprocess import TextJobs,source_revision
    from datetime import datetime,timezone
    import re

    control.configure(settings)
    document=read_record(settings['resume_record']) if settings.get('resume_record') else {}
    registry=ParticipantRegistry(state=document.get('participant_state'))
    all_rows={row['id']:dict(row) for row in document.get('rows',[])}
    row_settings={}
    journal_enabled=bool(settings.get('save_records',True))
    journal_long=bool(settings.get('long_meeting_mode'))
    journal=Journal(ROOT/'records',redact_settings(settings),path=settings['resume_record']) if journal_enabled and settings.get('resume_record') else (
        Journal(ROOT/'records',redact_settings(settings)) if journal_enabled else None)
    stores={}
    headers=dict(document.get('native_snapshot',{}).get('streams',{}))
    metadata={}
    pending={}
    removed_pending=set()
    last_save=0.
    latest_pipeline={}
    latest_pipelines={}
    latest_pipeline_source='main'
    timeline=max([float(document.get('audio_clock') or 0),*[float(r.get('end') or 0) for r in all_rows.values()]])
    committed_audio_clock=float(document.get('committed_audio_clock') or max([0.,*[float(r.get('end') or 0) for r in all_rows.values()]]))
    processed_clocks={}
    generation=max([int(m.group(1)) for key in headers for m in [re.search(r':g(\d+):',key)] if m]+[-1])+1
    media_state={}
    events=list(document.get('events',[]))
    pending_events=[]
    translations_to_submit=[]
    last_audio_at=document.get('last_audio_at')
    failed=False
    status='active'
    if document:
        before=last_audio_at or document.get('updated_at')
        gap=None
        try:
            date=datetime.fromisoformat(before)
            if date.tzinfo: gap=max(0.,(datetime.now(timezone.utc)-date).total_seconds())
        except (TypeError,ValueError): pass
        gap_event={'type':'recovery_gap','start':committed_audio_clock,'captured_until':timeline,
                   'duration':(timeline-committed_audio_clock+gap) if gap is not None else None,
                   'note':'从最后已保存的稳定处理位置新建采集段；后续可能含未处理音频或静音，中断期间声音无法重建'}
        events.append(gap_event); pending_events.append(gap_event)
        if gap is not None: timeline+=gap
        all_rows={key:registry.decorate(row) for key,row in all_rows.items()}

    def rows():
        return sorted(all_rows.values(),key=lambda row:(row.get('start',0),row['id']))

    def snapshot(full=False):
        streams={key:dict(value) for key,value in headers.items()}
        if full:
            for value in streams.values(): value['lines']=[]
            for row in rows():
                key=row.get('speaker_namespace','legacy')
                streams.setdefault(key,{'lines':[]})['lines'].append(row.get('native_local') or row.get('native') or {})
        return {**latest_pipeline,'pipeline_source':latest_pipeline_source,
                'pipelines':deepcopy(latest_pipelines),'streams':streams,
                'participant_state':registry.to_dict()}

    def save(force=False):
        nonlocal last_save
        if not journal or not journal_enabled: return
        if not force and not pending and not removed_pending and not pending_events: return
        if not force and time.monotonic()-last_save<1: return
        extra={'status':status,'participant_state':registry.to_dict(),'meeting_id':registry.meeting_id,
               'audio_clock':timeline,'last_audio_at':last_audio_at,'events':events[-1000:]}
        extra['committed_audio_clock']=committed_audio_clock
        try:
            if getattr(journal,'store',None):
                for event in pending_events: journal.store.event(event)
                journal.save_changes(list(pending.values()),removed=tuple(removed_pending),snapshot=snapshot(),extra=extra)
            else:
                if hasattr(journal,'metadata'): journal.metadata.update(extra)
                journal.save(rows(),snapshot=snapshot(full=True))
            pending.clear(); removed_pending.clear(); pending_events.clear()
            last_save=time.monotonic()
            emit({'type':'save_status','saved_at':datetime.now(timezone.utc).isoformat(timespec='seconds'),'rows':len(all_rows)})
        except Exception as exc:
            emit({'type':'warning','message':'记录写入失败，内存中字幕仍保留：'+str(exc)})
            last_save=time.monotonic()

    def emit_delta(changed,removed=(),source=None,pipeline_event=True):
        for row in changed: pending[row['id']]=row
        removed_pending.update(removed)
        row_sources={row.get('audio_source') for row in changed if row.get('audio_source')}
        event_source=source or (next(iter(row_sources)) if len(row_sources)==1 else None)
        if not changed and not removed:
            if pipeline_event:
                emit({'type':'pipeline','source':latest_pipeline_source,
                      'pipeline_source':latest_pipeline_source,'pipeline':latest_pipeline,
                      'pipelines':deepcopy(latest_pipelines)})
            return
        compact_headers={key:{field:value for field,value in header.items() if field in
            ('timeline_offset','language','target_language','asr_model')} for key,header in headers.items()}
        event={'type':'captions','delta':True,'rows':changed,'removed_ids':list(removed),
              'draft':latest_pipeline.get('buffer_transcription',''),'pipeline':latest_pipeline,
              'pipeline_source':latest_pipeline_source,'pipelines':deepcopy(latest_pipelines),
              'sources':sorted(row_sources or ({source} if source else set())),
              'native_snapshot':{'streams':compact_headers},'participant_state':registry.to_dict()}
        if event_source: event['source']=event_source
        emit(event)
        save()
        # Queue only after rows are installed and emitted. A full queue may
        # return an error synchronously, which must replace the pending row.
        submissions=translations_to_submit[:]
        translations_to_submit.clear()
        for row,cfg in submissions: jobs.submit(row,cfg)

    def result_ready(candidate,result):
        current=all_rows.get(candidate['id'])
        if not current or current.get('source_revision')!=candidate.get('source_revision'): return
        row={**current,**result}
        all_rows[row['id']]=row
        emit_delta([row])
        if result.get('translation_error'):
            emit({'type':'warning','message':'文字翻译未完成，听写继续：'+result['translation_error']})
        if result.get('fixed_terms_unapplied'):
            emit({'type':'warning','message':'部分固定译名未命中，已在记录中标明，请核对译文'})
        if result.get('translation_fallback'):
            emit({'type':'warning','message':'LM Studio 无法完成翻译，本段已明确回退到 NLLB'})

    jobs=TextJobs(result_ready,emit)
    engines={}
    def decorate(row,cfg,previous=None):
        rules=cfg.get('glossary_rules',())
        token=(cfg.get('glossary_enabled',False),id(rules))
        if token not in engines:
            engines[token]=Glossary(rules,enabled=cfg.get('glossary_enabled',False))
            engines[token]._source_rules=rules
        glossary=engines[token]
        row=glossary.decorate(registry.decorate(row))
        row['source_revision']=source_revision(row,cfg)
        needs=bool(row.get('target_language')) and (cfg.get('translation_provider')=='lmstudio' or row['source']!=row['source_original'])
        if needs:
            if previous and previous.get('source_revision')==row['source_revision']:
                row.update({key:value for key,value in previous.items() if key=='translation' or key.startswith('translation_')})
            else:
                row.update(translation_pending=True,translation_stale=bool(row.get('translation')))
                translations_to_submit.append((row,cfg))
        else:
            row.update(translation_pending=False,translation_stale=False,
                       translation_source_text=row['source'],translation_source_revision=glossary.revision,
                       translation_provider='native',translation_model='NLLB '+str((cfg.get('wlk') or {}).get('nllb_size','600M')))
            row['translation']=glossary.apply_fixed_translations(row.get('translation',''),row.get('target_language'))
        return row

    def process_actions():
        nonlocal journal,registry
        for action in control.drain_actions():
            command=action.get('cmd')
            try:
                if command in ('rename_participant','rename_speaker'):
                    pid=action.get('participant_id')
                    if not pid:
                        pid=next((row.get('participant_id') for row in reversed(list(all_rows.values())) if row.get('speaker')==action.get('speaker')),None)
                    registry.rename(pid,action['name'])
                elif command=='set_participants': registry=ParticipantRegistry(state=action['state'])
                elif command=='manual_save':
                    if journal is None: journal=Journal(ROOT/'records',{**redact_settings(settings),'long_meeting_mode':True})
                    pending.update(all_rows)
                    if getattr(journal,'store',None):
                        for event in pending_events: journal.store.event(event)
                        journal.save_changes(rows(),snapshot=snapshot(),extra={'status':'paused' if control.paused.is_set() else 'active',
                            'participant_state':registry.to_dict(),'meeting_id':registry.meeting_id,'audio_clock':timeline,
                            'committed_audio_clock':committed_audio_clock,'last_audio_at':last_audio_at,'manual_checkpoint':True})
                    else: journal.save(rows(),snapshot=snapshot(full=True))
                    emit({'type':'record','path':str(journal.path)})
                    continue
                elif command=='reprocess_glossary':
                    _,current=control.snapshot()
                    cfg={**current,**{key:action[key] for key in ('glossary_rules','glossary_enabled') if key in action}}
                    selected=set(action.get('row_ids') or all_rows)
                    changed=[]
                    for key in selected:
                        if key in all_rows:
                            old=all_rows[key]
                            raw={**old,'source':old.get('source_original',old['source']),'translation':old.get('native',{}).get('translation','')}
                            row=decorate(raw,cfg)
                            all_rows[key]=row; row_settings[key]=cfg; changed.append(row)
                    emit_delta(changed)
                    continue
                else: continue
                changed=[]
                for key,row in tuple(all_rows.items()):
                    updated=registry.decorate(row)
                    if updated!=row: all_rows[key]=updated; changed.append(updated)
                if changed: emit_delta(changed)
            except (ValueError,KeyError) as exc:
                emit({'type':'warning','message':str(exc)})

    async def actions_loop():
        while True:
            process_actions()
            save()
            await asyncio.sleep(.1)
    action_task=asyncio.create_task(actions_loop())

    def parameters(cfg,source):
        language=cfg.get('mic_language',cfg['source_language']) if source=='mic' else cfg['source_language']
        target=cfg.get('mic_target_language',cfg.get('target_language','')) if source=='mic' else cfg.get('target_language','')
        if cfg.get('translation_mode')=='off' or (cfg.get('wlk') or {}).get('direct_english_translation'): target=''
        return language,target,cfg.get('context',''),cfg.get('server_url','')

    def global_native(line,offset):
        line=deepcopy(line)
        for name in ('start','end'):
            if name in line:
                value=_seconds(line[name])+offset
                whole=int(value); line[name]=f'{whole//3600}:{whole//60%60:02d}:{value%60:05.2f}'
        for word in line.get('tokens',line.get('words',[])) or []:
            for name in ('start','end'):
                if name in word: word[name]=round(_seconds(word[name])+offset,6)
        return line

    def publish(key,payload):
        nonlocal latest_pipeline,latest_pipeline_source,committed_audio_clock
        store=stores[key]
        changed_native=store.ingest_snapshot(payload)
        info=metadata[key]
        latest_pipeline={field:value for field,value in store.snapshot.items() if field!='lines'}
        latest_pipeline_source=info['source']
        latest_pipelines[info['source']]=deepcopy(latest_pipeline)
        emit({'type':'pipeline','source':info['source'],'pipeline_source':info['source'],
              'pipeline':latest_pipeline,'pipelines':deepcopy(latest_pipelines)})
        stable_end=max([info['offset'],*[info['offset']+_seconds(line.get('end')) for line in store.snapshot.get('lines',[])]])
        processed_clocks[info['source']]=max(processed_clocks.get(info['source'],info['offset']),stable_end)
        committed_audio_clock=max(committed_audio_clock,min(processed_clocks.values()))
        if key not in headers:
            headers[key]={'timeline_offset':info['offset'],'language':info['language'],
                          'target_language':info['target'],'asr_model':info['model'],'configuration':redact_settings(info['configuration'])}
        changed=[]
        for item in changed_native:
            row={**item,'id':key+':'+item['id'],'audio_source':info['source'],
                 'start':round(item['start']+info['offset'],6),'end':round(item['end']+info['offset'],6),
                 'native_local':item['native'],'native':global_native(item['native'],info['offset']),
                 'asr_model':info['model'],'target_language':info['target'],
                 'configured_language':info['language'],'language':item.get('language') or info['language'],
                 'speaker_namespace':key,'source_original':item['source']}
            row['raw']=row['native']
            old=all_rows.get(row['id'])
            _,current=control.snapshot()
            cfg=row_settings.get(row['id'],current) if old and old.get('source_original')==row['source_original'] else current
            row_settings[row['id']]=cfg
            row=decorate(row,cfg,old)
            all_rows[row['id']]=row
            changed.append(row)
        removed=[key+':'+rid for rid in store.last_removed]
        for rid in removed: all_rows.pop(rid,None); row_settings.pop(rid,None)
        emit_delta(changed,removed,source=info['source'],pipeline_event=False)
        if latest_pipeline.get('translation_error'): emit({'type':'warning','message':latest_pipeline['translation_error']})

    def configure_journal(cfg):
        nonlocal journal,journal_enabled,journal_long
        enabled=bool(cfg.get('save_records',True))
        if enabled and cfg.get('long_meeting_mode') and not journal_long and journal is not None:
            old=journal
            path=old.path if Path(old.path).exists() else None
            journal=Journal(ROOT/'records',redact_settings(cfg),path=path)
            journal.metadata.update(getattr(old,'metadata',{}))
            pending.update(all_rows)
            if hasattr(old,'close'): old.close()
            journal_long=True
        if enabled and not journal_enabled:
            if journal is None:
                journal=Journal(ROOT/'records',redact_settings(cfg))
                journal_long=bool(cfg.get('long_meeting_mode'))
            pending.update(all_rows)
        journal_enabled=enabled
        if enabled: save(force=True)

    async def run_channel(source,cfg,base_time,phase):
        nonlocal last_audio_at,committed_audio_clock
        processed_clocks.setdefault(source,base_time)
        queue=asyncio.Queue(maxsize=100)
        clock=base_time
        local={**cfg,'source_mode':source} if source!='main' else cfg
        def capture_emit(event):
            event={**event,'source':source}
            if event.get('type')=='audio_gap':
                event={**event,'start':base_time+event.get('start_sample',0)/16000}
                events.append(event)
                pending_events.append(event)
            emit(event)
        async def produce():
            nonlocal clock,last_audio_at,timeline
            previous=parameters(cfg,source)
            previous_tick=-1
            try:
                async for chunk in capture_chunks(local,capture_emit,control,audio_file,realtime,pause_as_eof=True,media_state=media_state):
                    revision,current=control.snapshot()
                    selected=parameters(current,source)
                    if selected!=previous:
                        await queue.put(('switch',dict(current),clock,revision)); previous=selected
                        emit({'type':'status','message':'语言切换已排队，正在完成已采集的声音'})
                    if not len(chunk): continue
                    await queue.put(('audio',chunk))
                    clock=round(clock+len(chunk)/16000.,6)
                    timeline=max(timeline,clock)
                    last_audio_at=datetime.now(timezone.utc).isoformat()
                    if int(clock)!=previous_tick:
                        previous_tick=int(clock); emit({'type':'elapsed','seconds':previous_tick})
                    if queue.qsize()>70: emit({'type':'audio_backlog','chunks':queue.qsize(),'seconds':round(queue.qsize()*len(chunk)/16000,2)})
            finally:
                if not asyncio.current_task().cancelling(): await queue.put(('eof',))
        producer=asyncio.create_task(produce())
        current,offset,epoch=cfg,base_time,0
        try:
            while True:
                key=f'{source}:g{phase}:e{epoch}'
                stores[key]=CaptionStore()
                language,target,context,base=parameters(current,source)
                if not base: raise ValueError('未连接 WhisperLiveKit 服务')
                metadata[key]={'source':source,'offset':offset,'language':language,'target':target,'model':current['asr_model'],'configuration':current}
                values=config_values(current)
                boundary=None
                async def chunks():
                    nonlocal boundary
                    while True:
                        item=await queue.get()
                        if item[0]!='audio': boundary=item; return
                        yield item[1]
                def connected():
                    if not control.paused.is_set(): emit({'type':'state','state':'running'})
                    emit({'type':'settings_applied','source':source,'language':language,'target_language':target,'asr_model':current['asr_model']})
                native_target='' if current.get('translation_provider')=='lmstudio' else target
                await stream_native(base,chunks(),language,native_target,lambda payload:publish(key,payload),context=context,
                                    token=values.get('api_token'),mode='diff' if current.get('long_meeting_mode') else current.get('stream_mode','full'),
                                    drain_timeout=max(150,float(values.get('rest_timeout') or 0)),on_connected=connected)
                processed_clocks[source]=boundary[2] if boundary and boundary[0]=='switch' else clock
                committed_audio_clock=max(committed_audio_clock,min(processed_clocks.values()))
                save(force=True)
                if boundary is None or boundary[0]=='eof': break
                current,offset=boundary[1],boundary[2]; epoch+=1
            await producer
            return clock
        finally:
            if not producer.done(): producer.cancel()
            await asyncio.gather(producer,return_exceptions=True)

    try:
        if all_rows:
            initial_sources={row.get('audio_source') for row in all_rows.values() if row.get('audio_source')}
            initial_event={'type':'captions','rows':rows(),'pipeline':latest_pipeline,
                           'pipeline_source':latest_pipeline_source,'pipelines':deepcopy(latest_pipelines),
                           'sources':sorted(initial_sources),'native_snapshot':snapshot(full=True),
                           'participant_state':registry.to_dict()}
            if len(initial_sources)==1: initial_event['source']=next(iter(initial_sources))
            emit(initial_event)
        channels=['main']
        while not control.stopped.is_set():
            _,cfg=control.snapshot()
            status='active'; configure_journal(cfg)
            channels=['system','mic'] if not audio_file and cfg['source_mode']=='both' and cfg.get('separate_sources',True) else ['main']
            async with asyncio.TaskGroup() as group:
                tasks=[group.create_task(run_channel(source,cfg,timeline,generation)) for source in channels]
            timeline=max([timeline,*[task.result() for task in tasks]])
            process_actions()
            await jobs.drain(min(120,max(30,float(cfg.get('llm_timeout') or 30))))
            save(force=True)
            if not control.paused.is_set() or control.stopped.is_set(): break
            status='paused'; save(force=True)
            emit({'type':'state','state':'paused'})
            for source in channels: emit({'type':'level','value':0,'source':source})
            while control.paused.is_set() and not control.stopped.is_set(): await asyncio.sleep(.05)
            generation+=1
        emit({'type':'status','message':'原库已完成字幕与翻译'})
    except BaseException:
        failed=True
        failure_event={'type':'interruption','at':datetime.now(timezone.utc).isoformat(),'note':'识别或采集异常，已保存内容可恢复'}
        events.append(failure_event); pending_events.append(failure_event)
        raise
    finally:
        action_task.cancel()
        try: await action_task
        except asyncio.CancelledError: pass
        process_actions()
        await jobs.close()
        status='interrupted' if failed else 'stopped'
        save(force=True)
        final_sources={row.get('audio_source') for row in all_rows.values() if row.get('audio_source')}
        final_event={'type':'captions','rows':rows(),'pipeline':latest_pipeline,
                     'pipeline_source':latest_pipeline_source,'pipelines':deepcopy(latest_pipelines),
                     'sources':sorted(final_sources),
                     'native_snapshot':snapshot(full=True),'participant_state':registry.to_dict()}
        if len(final_sources)==1: final_event['source']=next(iter(final_sources))
        emit(final_event)
        if journal:
            if not journal_enabled and Path(journal.path).exists():
                # Closing an existing checkpoint changes only its lifecycle
                # marker, never writes the unsaved tail after autosave was off.
                if getattr(journal,'store',None): journal.store.checkpoint({'status':status})
                elif hasattr(journal,'metadata'):
                    document=read_record(journal.path)
                    document['status']=status
                    temporary=Path(journal.path).with_suffix('.tmp')
                    import json,os
                    temporary.write_text(json.dumps(document,ensure_ascii=False),encoding='utf-8')
                    os.replace(temporary,journal.path)
            if journal_enabled or Path(journal.path).exists(): emit({'type':'record','path':str(journal.path)})
            if hasattr(journal,'close'): journal.close()
        for source in channels: emit({'type':'level','value':0,'source':source})
