import asyncio
from unittest.mock import patch
import numpy as np
from app.settings import DEFAULTS
from app.session import SessionControl,run_session


def test_delta_corrections_keep_original_words_and_translate_corrected_text(tmp_path):
    events=[]
    calls=[]
    control=SessionControl()
    settings={**DEFAULTS,'server_url':'http://fake','save_records':True,'glossary_enabled':True,
              'glossary_rules':[{'original':'transfarmer','replacement':'transformer','language':'en','enabled':True}]}
    async def capture(*a,**k): yield np.zeros(1600,dtype=np.float32)
    async def native(base,chunks,language,target,on_snapshot,**kwargs):
        async for chunk in chunks: pass
        on_snapshot({'lines':[{'text':'The transfarmer needs a test.','start':0,'end':1,'speaker':1,
            'translation':'旧译文','tokens':[{'text':'transfarmer','start':.2,'end':.5}]}]})
    def translate(cfg,text,source,target):
        calls.append(text)
        return {'translation':'变压器需要测试。','model':'NLLB'}
    with patch('app.session.ROOT',tmp_path),patch('app.session.capture_chunks',capture), \
         patch('app.native_client.stream_native',native),patch('app.session_postprocess.native_translate',translate):
        asyncio.run(run_session(settings,events.append,control))
    assert any(event.get('delta') for event in events if event['type']=='captions')
    rows=[e['rows'] for e in events if e['type']=='captions'][-1]
    assert calls==['The transformer needs a test.']
    assert rows[0]['source_original']=='The transfarmer needs a test.'
    assert rows[0]['source']=='The transformer needs a test.'
    assert rows[0]['translation']=='变压器需要测试。'
    assert rows[0]['native']['tokens'][0]['text']=='transfarmer'
    from app.records import read_record
    path=[e['path'] for e in events if e['type']=='record'][-1]
    assert read_record(path)['rows']==rows


def test_participant_rename_action_is_scoped_and_saved(tmp_path):
    events=[]
    control=SessionControl()
    settings={**DEFAULTS,'server_url':'http://fake','save_records':True,'translation_mode':'off'}
    async def capture(*a,**k): yield np.zeros(1600,dtype=np.float32)
    async def native(base,chunks,language,target,on_snapshot,**kwargs):
        async for chunk in chunks: pass
        on_snapshot({'lines':[{'text':'hello','start':0,'end':1,'speaker':1}]})
    def emit(event):
        events.append(event)
        if event.get('delta') and event.get('rows'):
            control.enqueue_action({'cmd':'rename_participant','participant_id':event['rows'][0]['participant_id'],'name':'王工'})
    with patch('app.session.ROOT',tmp_path),patch('app.session.capture_chunks',capture),patch('app.native_client.stream_native',native):
        asyncio.run(run_session(settings,emit,control))
    rows=[e['rows'] for e in events if e['type']=='captions'][-1]
    assert rows[0]['speaker_name']=='王工' and rows[0]['native']['speaker']==1


def test_saturated_text_queue_marks_rejected_rows_in_final_journal(tmp_path):
    events=[]
    settings={**DEFAULTS,'server_url':'http://fake','save_records':True,'glossary_enabled':True,
              'glossary_rules':[{'original':'wrong','replacement':'right','language':'en'}]}
    async def capture(*a,**k): yield np.zeros(1600,dtype=np.float32)
    async def native(base,chunks,language,target,on_snapshot,**kwargs):
        async for chunk in chunks: pass
        on_snapshot({'lines':[{'text':'wrong '+str(i),'start':i,'end':i+.5,'speaker':1} for i in range(105)]})
    def translate(cfg,text,source,target): return {'translation':'译文','model':'NLLB'}
    with patch('app.session.ROOT',tmp_path),patch('app.session.capture_chunks',capture), \
         patch('app.native_client.stream_native',native),patch('app.session_postprocess.native_translate',translate):
        asyncio.run(run_session(settings,events.append,SessionControl()))
    rows=[e['rows'] for e in events if e['type']=='captions'][-1]
    rejected=[r for r in rows if r.get('translation_error')]
    assert len(rejected)==5
    assert all(not r.get('translation_pending') for r in rows)
    from app.records import read_record
    saved=read_record([e['path'] for e in events if e['type']=='record'][-1])
    assert saved['rows']==rows


def test_dropped_capture_packets_preserve_timeline_and_emit_exact_gap():
    from app.session import capture_chunks
    control=SessionControl()
    events=[]
    packets=[(np.ones(8000,dtype=np.float32),16000)]
    class Capture:
        error=None
        def start(self): pass
        def stop(self): pass
        def get_packet(self,timeout):
            if packets: return packets.pop(0)
            control.request('stop')
            return None
    async def consume():
        return [chunk async for chunk in capture_chunks(DEFAULTS,events.append,control,pause_as_eof=True)]
    with patch('app.audio.AudioCapture',return_value=Capture()):
        chunks=asyncio.run(consume())
    audio=np.concatenate(chunks)
    assert len(audio)==24000
    assert np.all(audio[:16000]==0) and np.all(audio[16000:]==1)
    gaps=[e for e in events if e['type']=='audio_gap']
    assert len(gaps)==1 and gaps[0]['start_sample']==0 and gaps[0]['samples']==16000


def test_interrupted_session_marks_unprocessed_audio_and_resumes_without_id_collision(tmp_path):
    import pytest
    from app.records import read_record
    events=[]
    cfg={**DEFAULTS,'server_url':'http://fake','translation_mode':'off','save_records':True}
    async def capture(*a,**k): yield np.zeros(320000,dtype=np.float32)
    async def interrupted(base,chunks,language,target,on_snapshot,**kwargs):
        async for _ in chunks: pass
        on_snapshot({'lines':[{'text':'confirmed before failure','start':0,'end':1,'speaker':1}]})
        raise RuntimeError('connection lost')
    with patch('app.session.ROOT',tmp_path),patch('app.session.capture_chunks',capture),patch('app.native_client.stream_native',interrupted):
        with pytest.raises(ExceptionGroup): asyncio.run(run_session(cfg,events.append,SessionControl()))
    path=[e['path'] for e in events if e['type']=='record'][-1]
    document=read_record(path)
    assert document['audio_clock']==20 and document['committed_audio_clock']==1
    old=document['rows'][0]
    resumed=[]
    async def short_capture(*a,**k): yield np.zeros(1600,dtype=np.float32)
    async def new_native(base,chunks,language,target,on_snapshot,**kwargs):
        async for _ in chunks: pass
        on_snapshot({'lines':[{'text':'new segment','start':0,'end':.1,'speaker':1}]})
    with patch('app.session.ROOT',tmp_path),patch('app.session.capture_chunks',short_capture),patch('app.native_client.stream_native',new_native):
        asyncio.run(run_session({**cfg,'resume_record':path},resumed.append,SessionControl()))
    restored=read_record(path)
    assert len(restored['rows'])==2 and len({r['id'] for r in restored['rows']})==2
    assert restored['rows'][0]==old
    assert restored['rows'][1]['participant_id']!=old['participant_id']
    gap=next(e for e in restored['events'] if e['type']=='recovery_gap')
    assert gap['start']==1 and gap['captured_until']==20 and gap['duration']>=19


def test_manual_checkpoint_with_autosave_off_recovers_but_clean_end_saves_no_tail(tmp_path):
    from app.records import read_record
    events=[]
    control=SessionControl()
    cfg={**DEFAULTS,'server_url':'http://fake','translation_mode':'off','save_records':False}
    async def capture(*a,**k): yield np.zeros(1600,dtype=np.float32)
    async def native(base,chunks,language,target,on_snapshot,**kwargs):
        async for _ in chunks: pass
        on_snapshot({'lines':[{'text':'checkpoint','start':0,'end':1,'speaker':1}]})
        control.enqueue_action({'cmd':'manual_save'})
        await asyncio.sleep(.15)
        on_snapshot({'type':'diff','n_lines':2,'new_lines':[{'text':'unsaved tail','start':1,'end':2,'speaker':1}]})
    with patch('app.session.ROOT',tmp_path),patch('app.session.capture_chunks',capture),patch('app.native_client.stream_native',native):
        asyncio.run(run_session(cfg,events.append,control))
    doc=read_record([e['path'] for e in events if e['type']=='record'][-1])
    assert [r['source'] for r in doc['rows']]==['checkpoint']
    assert doc['manual_checkpoint'] is True and doc['status']=='stopped'
