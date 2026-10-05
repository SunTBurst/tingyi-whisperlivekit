import asyncio
import json
from unittest.mock import patch

import numpy as np

from app.native_client import session_url, stream_native


def test_session_parameters_are_encoded_and_auth_is_header_only():
    url = session_url('https://localhost:8000', 'en', 'zho_Hans', 'SEC & EPC', 'diff')
    assert url.startswith('wss://localhost:8000/asr?')
    assert 'context=SEC+%26+EPC' in url and 'mode=diff' in url
    assert 'secret' not in url


def test_pcm_eof_waits_for_native_ready_to_stop():
    class Socket:
        def __init__(self): self.sent=[]
        async def send(self, value): self.sent.append(value)
        async def recv(self):
            await asyncio.sleep(0)
            return json.dumps({'type':'ready_to_stop'})
        def __aiter__(self): return self
        async def __anext__(self):
            while not self.sent or self.sent[-1] != b'': await asyncio.sleep(.001)
            if getattr(self,'done',False): raise StopAsyncIteration
            self.done=True
            return json.dumps({'type':'ready_to_stop'})
    sock=Socket()
    class Connection:
        async def __aenter__(self): return sock
        async def __aexit__(self,*args): pass
    async def chunks(): yield np.array([.2,-.2],dtype='float32')
    with patch('websockets.asyncio.client.connect',return_value=Connection()):
        asyncio.run(stream_native('http://localhost:8000',chunks(),'en','zh',lambda s:None))
    assert sock.sent[-1]==b'' and len(sock.sent[0])==4
