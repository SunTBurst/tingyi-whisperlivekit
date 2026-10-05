import asyncio
from app.settings import DEFAULTS


def test_latest_source_revision_replaces_queued_work_and_results_are_bound():
    from app.session_postprocess import TextJobs
    completed=[]
    async def translate(row,cfg,cancel):
        await asyncio.sleep(.001)
        return {'translation':row['source']+' translated','translation_model':'fake'}
    async def run():
        jobs=TextJobs(lambda row,result:completed.append((row,result)),lambda e:None,translate)
        jobs.submit({'id':'1','source':'old','source_revision':'a'},DEFAULTS)
        jobs.submit({'id':'1','source':'new','source_revision':'b'},DEFAULTS)
        assert await jobs.drain(1)
        await jobs.close()
    asyncio.run(run())
    assert len(completed)==1 and completed[0][0]['source_revision']=='b'
    assert completed[0][1]['translation']=='new translated'


def test_optional_translation_failure_is_returned_without_stopping_session():
    from app.session_postprocess import TextJobs
    completed=[]
    async def translate(row,cfg,cancel): raise RuntimeError('offline')
    async def run():
        jobs=TextJobs(lambda row,result:completed.append(result),lambda e:None,translate)
        jobs.submit({'id':'1','source':'word','source_revision':'a'},DEFAULTS)
        assert await jobs.drain(1)
        await jobs.close()
    asyncio.run(run())
    assert completed[0]['translation_error']=='offline'


def test_translate_corrected_source_uses_actual_text_and_fallback_is_explicit(monkeypatch):
    from app.session_postprocess import translate_row
    from app.llm_client import LMStudioClient
    calls=[]
    def unavailable(self,*args,**kwargs): raise RuntimeError('LM unavailable')
    monkeypatch.setattr(LMStudioClient,'stream_chat',unavailable)
    def native(cfg,text,source,target):
        calls.append(text)
        return {'translation':'corrected译文','model':'NLLB 600M'}
    monkeypatch.setattr('app.session_postprocess.native_translate',native)
    row={'id':'1','source':'corrected','source_original':'wrong','language':'en','target_language':'zh'}
    result=asyncio.run(translate_row(row,{**DEFAULTS,'translation_provider':'lmstudio','llm_fallback':True},None))
    assert calls==['corrected'] and result['translation_fallback'] is True
    assert result['translation_model']=='NLLB 600M'


def test_source_revision_binds_source_language_and_native_translation_model():
    from app.session_postprocess import source_revision
    row={'source':'same','target_language':'zh','language':'en'}
    before=source_revision(row,DEFAULTS)
    assert source_revision({**row,'language':'fr'},DEFAULTS)!=before
    assert source_revision(row,{**DEFAULTS,'wlk':{'nllb_size':'1.3B'}})!=before


def test_cancelled_lm_does_not_start_native_fallback(monkeypatch):
    import threading
    import pytest
    from app.session_postprocess import translate_row
    from app.llm_client import LMStudioClient,LLMCancelledError
    cancel=threading.Event()
    def stopped(self,*args): cancel.set(); raise LLMCancelledError('cancelled')
    monkeypatch.setattr(LMStudioClient,'stream_chat',stopped)
    def forbidden(*args): raise AssertionError('fallback started after cancellation')
    monkeypatch.setattr('app.session_postprocess.native_translate',forbidden)
    with pytest.raises(LLMCancelledError):
        asyncio.run(translate_row({'source':'text','language':'en','target_language':'zh'},
            {**DEFAULTS,'translation_provider':'lmstudio','llm_fallback':True},cancel))


def test_lm_unmatched_fixed_term_is_explicit_and_wrong_source_rules_are_ignored(monkeypatch):
    from app.session_postprocess import translate_row
    from app.llm_client import LMStudioClient
    monkeypatch.setattr(LMStudioClient,'stream_chat',lambda *args:['别的译名'])
    cfg={**DEFAULTS,'translation_provider':'lmstudio','glossary_enabled':True,'glossary_rules':[
        {'original':'Acme','replacement':'Acme','language':'en','fixed_translation':'阿克米','target_language':'zh'},
        {'original':'Acme','replacement':'Acme','language':'fr','fixed_translation':'错误词','target_language':'zh'}]}
    result=asyncio.run(translate_row({'source':'Acme report','language':'en','target_language':'zh'},cfg,None))
    assert result['fixed_terms_unapplied']==[{'replacement':'Acme','fixed_translation':'阿克米'}]


def test_revised_source_cancels_active_request_and_processes_latest_version():
    from app.session_postprocess import TextJobs
    started=asyncio.Event()
    results=[]
    async def translate(row,cfg,cancel):
        if row['source_revision']=='old':
            started.set()
            while not cancel.is_set(): await asyncio.sleep(.001)
            raise RuntimeError('superseded')
        return {'translation':'latest translation'}
    async def run():
        jobs=TextJobs(lambda row,result:results.append((row,result)),lambda e:None,translate)
        jobs.submit({'id':'1','source':'partial','source_revision':'old'},DEFAULTS)
        await started.wait()
        jobs.submit({'id':'1','source':'complete','source_revision':'new'},DEFAULTS)
        assert await jobs.drain(1)
        await jobs.close()
    asyncio.run(run())
    assert results[-1][0]['source_revision']=='new'
    assert results[-1][1]['translation']=='latest translation'
