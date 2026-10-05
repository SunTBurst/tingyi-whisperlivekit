import json
import os
import queue
import subprocess
import threading
import unittest
from pathlib import Path

import psutil

ROOT=Path(__file__).resolve().parents[1]


class BackendStartupTests(unittest.TestCase):
    def test_native_initialization_does_not_hang_with_open_command_pipe(self):
        env={**os.environ,'PYTHONUTF8':'1','PATH':str(ROOT/'.venv/Lib/site-packages/torch/lib')+os.pathsep+os.environ.get('PATH','')}
        probe = '''
import json, sys, threading
from app.backend import control_messages
messages=control_messages(sys.stdin)
next(messages)
stopped=threading.Event()
def listen():
    for message in messages:
        if message.get('cmd')=='stop': stopped.set(); return
threading.Thread(target=listen,daemon=True).start()
import numpy, scipy.signal, pyaudiowpatch
print(json.dumps({'type':'status'}),flush=True)
assert stopped.wait(10)
'''
        process=subprocess.Popen([str(ROOT/'.venv/Scripts/python.exe'),'-u','-c',probe],cwd=ROOT,
            env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
            text=True,encoding='utf-8')
        events=queue.Queue()
        threading.Thread(target=lambda:events.put(process.stdout.readline()),daemon=True).start()
        try:
            process.stdin.write(json.dumps({'cmd':'start','settings':{'translation_mode':'off','save_records':False}})+'\n')
            process.stdin.flush()
            try:
                response=events.get(timeout=10)
            except queue.Empty:
                self.fail('Native library initialization stalled while command input remained open')
            self.assertEqual(json.loads(response)['type'],'status')
            process.stdin.write(json.dumps({'cmd':'stop'})+'\n')
            process.stdin.flush()
            process.stdin.close()
            self.assertEqual(process.wait(timeout=25),0)
        finally:
            if process.poll() is None:
                for child in psutil.Process(process.pid).children(recursive=True):
                    child.kill()
                process.kill()
                process.wait(timeout=5)


if __name__=='__main__':
    unittest.main()
