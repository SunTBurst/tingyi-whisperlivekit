"""JSONL control boundary isolates CUDA and model lifetimes from the GUI."""
import asyncio
import json
import logging
import os
import sys
import threading
import time

from app.session import SessionControl, run_session
from app.settings import ROOT, DEFAULTS


def control_messages(stream):
    """Read the GUI pipe without holding a CRT stdin lock during native imports."""
    if os.name != 'nt':
        for line in stream:
            yield json.loads(line)
        return
    import ctypes
    import msvcrt
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    peek = kernel.PeekNamedPipe
    peek.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
                     ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD),
                     ctypes.POINTER(wintypes.DWORD)]
    peek.restype = wintypes.BOOL
    descriptor = stream.fileno()
    handle = msvcrt.get_osfhandle(descriptor)
    buffered = b''
    while True:
        available = wintypes.DWORD()
        if not peek(handle, None, 0, None, ctypes.byref(available), None):
            if ctypes.get_last_error() in (109, 232):
                return
            raise OSError(ctypes.get_last_error(), 'Cannot read GUI control pipe')
        if not available.value:
            time.sleep(.025)
            continue
        buffered += os.read(descriptor, min(available.value, 65536))
        while b'\n' in buffered:
            line, buffered = buffered.split(b'\n', 1)
            if line.strip():
                yield json.loads(line)


def main():
    os.environ['PATH']=str(ROOT/'runtime/ffmpeg')+os.pathsep+os.environ.get('PATH','')
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING, format='%(asctime)s %(name)s %(message)s')
    output = sys.stdout

    def emit(event):
        output.write(json.dumps(event, ensure_ascii=False) + '\n')
        output.flush()

    messages = control_messages(sys.stdin)
    payload = next(messages, None)
    if payload is None:
        return
    settings = {**DEFAULTS, **payload.get('settings', {})}
    control = SessionControl()
    control.configure(settings)

    def receive_commands():
        for message in messages:
            try:
                if message.get('cmd') in ('rename_speaker','rename_participant','set_participants','reprocess_glossary','manual_save'):
                    control.enqueue_action(message)
                elif message.get('cmd')=='update_options':
                    control.update_options(message['settings'])
                elif message.get('cmd')=='update_languages':
                    control.update_languages(message['settings'])
                elif message.get('cmd')=='resume':
                    control.resume(message['settings'])
                else:
                    control.request(message.get('cmd'))
            except ValueError:
                pass
        control.request('stop')

    threading.Thread(target=receive_commands, daemon=True, name='UICommands').start()
    try:
        asyncio.run(run_session(settings, emit, control, audio_file=payload.get('audio_file'), realtime=payload.get('realtime', True)))
        emit({'type':'state', 'state':'stopped'})
    except Exception as exc:
        logging.exception('Session failed')
        def message(error):
            if isinstance(error,BaseExceptionGroup):
                return '；'.join(message(item) for item in error.exceptions)
            return str(error)
        emit({'type':'error', 'message':f'会议未能继续：{message(exc)}'})
        raise SystemExit(1)


if __name__ == '__main__':
    main()
