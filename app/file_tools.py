"""File and batch actions use upstream's REST route and response formats."""
import json
import uuid
from pathlib import Path


def transcribe_files(base, paths, output_dir, response_format='verbose_json',
                     language='en', context='', token=None, progress=None):
    import requests
    if response_format not in {'json','verbose_json','diarized_json','text','srt','vtt'}:
        raise ValueError('不支持的原库导出格式')
    output=Path(output_dir)
    output.mkdir(parents=True,exist_ok=True)
    written=[]
    paths=list(paths)
    headers={'Authorization':'Bearer '+token} if token else {}
    for index,raw_path in enumerate(paths):
        path=Path(raw_path)
        if progress: progress({'index':index,'total':len(paths),'file':str(path),'state':'processing'})
        data={'response_format':response_format,'prompt':context or ''}
        if language and language!='auto': data['language']=language
        with path.open('rb') as stream:
            response=requests.post(base.rstrip('/')+'/v1/audio/transcriptions',
                                   files={'file':(path.name,stream)},data=data,
                                   headers=headers,timeout=(30,1800))
        if not response.ok:
            try: detail=response.json().get('detail',response.text)
            except ValueError: detail=response.text
            raise RuntimeError(f'{path.name} 转写失败（HTTP {response.status_code}）：{detail}')
        suffix='json' if response_format.endswith('json') or response_format=='json' else ('txt' if response_format=='text' else response_format)
        target=output/(path.stem+'.'+suffix)
        if target.exists(): target=output/(path.stem+'-'+uuid.uuid4().hex[:8]+'.'+suffix)
        text=json.dumps(response.json(),ensure_ascii=False,indent=2) if suffix=='json' else response.text
        temporary=target.with_suffix(target.suffix+'.partial')
        temporary.write_text(text,encoding='utf-8')
        temporary.replace(target)
        written.append(str(target))
        if progress: progress({'index':index+1,'total':len(paths),'file':str(target),'state':'complete'})
    return written
