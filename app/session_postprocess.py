"""Bounded optional text work, independent from live ASR capture and decoding."""
import asyncio
from collections import OrderedDict
import hashlib
import json
import re
import threading

from app.glossary import Glossary


def source_revision(row,settings):
    values=[row.get('source'),row.get('target_language'),row.get('glossary_revision'),
            row.get('language'),row.get('configured_language'),settings.get('translation_provider','nllb'),
            settings.get('llm_model',''),settings.get('llm_url',''),
            (settings.get('wlk') or {}).get('nllb_size','600M'),(settings.get('wlk') or {}).get('nllb_backend','ctranslate2')]
    return hashlib.sha256(json.dumps(values,ensure_ascii=False).encode()).hexdigest()[:20]


def native_translate(settings,text,source,target):
    import requests
    base=str(settings.get('server_url') or '').rstrip('/')
    if base.startswith('ws://'): base='http://'+base[5:]
    elif base.startswith('wss://'): base='https://'+base[6:]
    if not base: raise RuntimeError('本地翻译服务尚未连接')
    token=(settings.get('wlk') or {}).get('api_token')
    headers={'Authorization':'Bearer '+token} if token else {}
    rules=settings.get('glossary_rules',[]) if settings.get('glossary_enabled') else []
    response=requests.post(base+'/desktop/translate',json={'text':text,'source':source,'target':target,'glossary_rules':rules},
                           headers=headers,timeout=(3,20))
    if response.status_code==404:
        raise RuntimeError('该远程原库服务没有文字纠错翻译扩展，请使用本机服务或 LM Studio')
    if not response.ok: raise RuntimeError('本地文字翻译失败（HTTP '+str(response.status_code)+'）')
    result=response.json()
    if not result.get('translation'): raise RuntimeError('本地翻译没有返回译文')
    return result


async def translate_row(row,settings,cancel):
    from app.llm_client import LLMCancelledError
    if cancel is not None and cancel.is_set(): raise LLMCancelledError('文字翻译已取消')
    source=row.get('language') or row.get('configured_language') or 'auto'
    target=row.get('target_language') or settings.get('target_language')
    text=row.get('source','')
    provider=settings.get('translation_provider','nllb')
    result={}
    required_terms=[]
    if provider=='lmstudio':
        from app.llm_client import LMStudioClient
        client=LMStudioClient(settings)
        terms=[]
        if settings.get('glossary_enabled'):
            for rule in Glossary(settings.get('glossary_rules',[])).rules:
                if not rule['enabled'] or not rule['fixed_translation']: continue
                if rule['language'] and not Glossary._applies(rule['language'],source): continue
                if rule['target_language'] and not Glossary._applies(rule['target_language'],target): continue
                pattern=re.escape(rule['replacement'])
                if rule['match_mode'].startswith('whole_word'): pattern=r'(?<!\w)'+pattern+r'(?!\w)'
                flags=0 if rule['match_mode'].endswith('case_sensitive') else re.IGNORECASE
                if re.search(pattern,text,flags):
                    terms.append(rule['replacement']+' = '+rule['fixed_translation'])
                    required_terms.append(rule)
        prompt=f'Translate from {source} to {target}. Return only the translation. Preserve all meaning and names.'
        if terms: prompt+=' Use these exact target terms: '+ '; '.join(terms)+'.'
        messages=[{'role':'user','content':prompt+'\n\n'+text}]
        def generate():
            output=''.join(client.stream_chat(messages,cancel)).strip()
            if not output: raise RuntimeError('LM Studio 未产生译文')
            return output
        try:
            translated=await asyncio.to_thread(generate)
            result={'translation':translated,'translation_model':client.model,'translation_provider':'lmstudio'}
        except Exception as exc:
            if isinstance(exc,LLMCancelledError) or (cancel is not None and cancel.is_set()): raise
            if not settings.get('llm_fallback'): raise
            native=await asyncio.to_thread(native_translate,settings,text,source,target)
            result={**native,'translation_model':native.get('model','NLLB'),'translation_provider':'nllb',
                    'translation_fallback':True,'translation_fallback_reason':str(exc)}
    else:
        native=await asyncio.to_thread(native_translate,settings,text,source,target)
        result={**native,'translation_model':native.get('model','NLLB'),'translation_provider':'nllb'}
    glossary=Glossary(settings.get('glossary_rules',[]),enabled=settings.get('glossary_enabled',False))
    result['translation']=glossary.apply_fixed_translations(result['translation'],target)
    if cancel is not None and cancel.is_set(): raise LLMCancelledError('文字翻译已取消')
    if result.get('translation_provider')=='lmstudio':
        result['fixed_terms_unapplied']=[{'replacement':rule['replacement'],'fixed_translation':rule['fixed_translation']}
            for rule in required_terms if rule['fixed_translation'] not in result['translation']]
    result.update(translation_source_text=text,translation_source_revision=row.get('glossary_revision'),
                  translation_text_revision=row.get('source_revision'),translation_stale=False,
                  translation_pending=False,translation_error='')
    return result


class TextJobs:
    def __init__(self,on_result,emit,translate=translate_row):
        self.on_result=on_result
        self.emit=emit
        self.translate=translate
        self.pending=OrderedDict()
        self.wake=asyncio.Event()
        self.empty=asyncio.Event()
        self.empty.set()
        self.cancel=threading.Event()
        self.task=None
        self.closed=False
        self.active_row=None
        self.active_cancel=None

    def submit(self,row,settings):
        if self.closed: return
        if (self.active_row and self.active_row['id']==row['id'] and
                self.active_row.get('source_revision')!=row.get('source_revision') and self.active_cancel):
            self.active_cancel.set()
        if len(self.pending)>=100 and row['id'] not in self.pending:
            self.on_result(row,{'translation_error':'文字翻译积压过多，已保存原文，可在会后重新翻译',
                                'translation_pending':False,'translation_stale':True})
            return
        self.pending[row['id']]=(dict(row),dict(settings))
        self.empty.clear()
        self.wake.set()
        if self.task is None: self.task=asyncio.create_task(self._work(),name='optional-text-translation')

    async def _work(self):
        while not self.closed:
            if not self.pending:
                self.empty.set()
                self.wake.clear()
                await self.wake.wait()
                continue
            _,(row,settings)=self.pending.popitem(last=False)
            self.active_row=row
            self.active_cancel=threading.Event()
            self.emit({'type':'text_backlog','count':len(self.pending)+1})
            try:
                result=await self.translate(row,settings,self.active_cancel)
            except asyncio.CancelledError: raise
            except Exception as exc:
                result={'translation_error':str(exc),'translation_pending':False,'translation_stale':True}
            self.on_result(row,result)
            self.active_row=None
            self.active_cancel=None
        self.empty.set()

    async def drain(self,timeout=30):
        try:
            await asyncio.wait_for(self.empty.wait(),timeout)
            return True
        except asyncio.TimeoutError:
            self.emit({'type':'warning','message':'部分文字翻译尚未完成，原文已经保留在记录中'})
            return False

    async def close(self):
        self.closed=True
        self.cancel.set()
        if self.active_cancel: self.active_cancel.set()
        self.wake.set()
        if self.task:
            self.task.cancel()
            try: await self.task
            except asyncio.CancelledError: pass
        if self.active_row:
            self.on_result(self.active_row,{'translation_pending':False,'translation_stale':True,
                'translation_error':'本段文字翻译未完成，可在会后重译'})
            self.active_row=None
        for row,_ in self.pending.values():
            self.on_result(row,{'translation_pending':False,'translation_stale':True,
                                'translation_error':'会议结束时尚未完成翻译，可在会后重新翻译'})
        self.pending.clear()
