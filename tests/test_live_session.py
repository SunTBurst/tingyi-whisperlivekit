import asyncio
from unittest.mock import patch
import numpy as np

from app.session import SessionControl, run_session
from app.settings import DEFAULTS


def test_live_language_switch_then_paused_model_change_preserves_audio_and_rows():
    control=SessionControl()
    events=[]
    calls=[]
    capture_round=0
    settings={**DEFAULTS,'server_url':'http://local','save_records':False,'asr_model':'small'}
    async def capture(*args,**kwargs):
        nonlocal capture_round
        capture_round+=1
        if capture_round==1:
            yield np.full(1600,.1,dtype=np.float32)
            control.update_languages({'source_language':'zh','target_language':'en'})
            yield np.full(1600,.2,dtype=np.float32)
            control.request('pause')
            yield np.full(1600,.3,dtype=np.float32)  # Tail captured before pause.
        else:
            yield np.full(1600,.4,dtype=np.float32)
    async def native(base,chunks,language,target,on_snapshot,**kwargs):
        seen=[]
        if kwargs.get('on_connected'): kwargs['on_connected']()
        async for packet in chunks: seen.append(round(float(packet[0]),1))
        calls.append((language,target,seen))
        if seen:
            on_snapshot({'lines':[{'text':str(seen),'start':0,'end':len(seen)*.1,
                                  'speaker':1,'translation':target}]})
    def emit(event):
        events.append(event)
        if event.get('type')=='state' and event.get('state')=='paused':
            control.resume({**settings,'source_language':'zh','target_language':'en','asr_model':'medium'})
    with patch('app.session.capture_chunks',capture),patch('app.native_client.stream_native',native):
        asyncio.run(run_session(settings,emit,control))
    assert calls==[('en','zh',[.1]),('zh','en',[.2,.3]),('zh','en',[.4])]
    rows=[e for e in events if e.get('type')=='captions'][-1]['rows']
    assert len(rows)==3
    assert [r['start'] for r in rows]==[0.,.1,.3]
    assert [r['asr_model'] for r in rows]==['small','small','medium']
    assert [r['target_language'] for r in rows]==['zh','en','en']


def test_stop_is_irreversible_even_if_late_resume_config_arrives():
    control=SessionControl()
    control.request('stop')
    control.resume(DEFAULTS)
    assert control.stopped.is_set()
    assert not control.paused.is_set()
