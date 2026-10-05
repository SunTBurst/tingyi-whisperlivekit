"""Desktop transport for the original WhisperLiveKit WebSocket API."""
import asyncio
import inspect
import json
from urllib.parse import urlencode, urlsplit, urlunsplit

from app.asr import _pcm16le_bytes


def session_url(base, language, target, context='', mode='full'):
    parsed = urlsplit(base.rstrip('/'))
    if parsed.scheme not in ('http','https','ws','wss') or not parsed.hostname:
        raise ValueError('服务器地址应为 http://地址:端口 或 https://地址:端口')
    scheme = 'wss' if parsed.scheme in ('https','wss') else 'ws'
    query = urlencode({'language':language, 'target_language':target or '',
                       'context':context or '', 'mode':mode})
    return urlunsplit((scheme,parsed.netloc,parsed.path.rstrip('/')+'/asr',query,''))


async def stream_native(base, chunks, language, target, on_snapshot,
                        *, context='', token=None, mode='full', drain_timeout=150,
                        on_connected=None):
    from websockets.asyncio.client import connect
    headers = {'Authorization':'Bearer '+token} if token else None
    uri = session_url(base,language,target,context,mode)
    async with connect(uri, additional_headers=headers, max_size=32*1024*1024,
                       open_timeout=30, ping_timeout=60) as socket:
        async def receive():
            async for message in socket:
                payload = json.loads(message)
                if payload.get('type')=='ready_to_stop':
                    return
                if payload.get('type')=='error' or payload.get('status')=='error':
                    raise RuntimeError(payload.get('error') or '原库流式处理失败')
                if payload.get('type')=='config':
                    if not payload.get('useAudioWorklet'):
                        raise RuntimeError('服务器未启用 PCM 输入；请在原库设置启用 pcm_input。')
                    if on_connected:
                        result=on_connected()
                        if inspect.isawaitable(result): await result
                    continue
                result = on_snapshot(payload)
                if inspect.isawaitable(result):
                    await result
            raise RuntimeError('原库连接在最终字幕完成前关闭')

        consumer = asyncio.create_task(receive())
        async def feed():
            async for chunk in chunks:
                pcm=_pcm16le_bytes(chunk)
                if pcm: await socket.send(pcm)
            await socket.send(b'')
        feeder=asyncio.create_task(feed())
        try:
            done,_=await asyncio.wait({consumer,feeder},return_when=asyncio.FIRST_COMPLETED)
            if consumer in done and not feeder.done():
                await consumer
                raise RuntimeError('原库处理在音频结束前停止')
            await feeder
            await asyncio.wait_for(consumer,timeout=drain_timeout)
        finally:
            for task in (consumer,feeder):
                if not task.done(): task.cancel()
            await asyncio.gather(consumer,feeder,return_exceptions=True)
