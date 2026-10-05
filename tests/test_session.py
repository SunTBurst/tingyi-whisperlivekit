import importlib
import unittest
import asyncio
from collections import deque
from unittest.mock import patch


class SessionTests(unittest.TestCase):
    def _run_save_toggle(self, initial_save, resumed_save):
        import numpy as np
        from app.session import SessionControl, run_session
        from app.settings import DEFAULTS

        control = SessionControl()
        settings = {**DEFAULTS, 'server_url':'http://local', 'save_records':initial_save}
        events = []
        journals = []
        phase = 0

        class FakeJournal:
            def __init__(self, folder, metadata):
                self.path = 'meeting.json'
                self.saves = []
                journals.append(self)
            def save(self, rows, snapshot=None):
                self.saves.append((rows, snapshot))

        async def capture(*args, **kwargs):
            yield np.ones(1600, dtype=np.float32)

        async def native(base, chunks, language, target, on_snapshot, **kwargs):
            nonlocal phase
            async for _ in chunks:
                on_snapshot({'lines':[{'text':f'phase {phase}', 'start':0, 'end':.1,
                                       'speaker':1, 'translation':target}]})
                if phase == 0:
                    control.request('pause')
                else:
                    control.request('stop')
            phase += 1

        def emit(event):
            events.append(event)
            if event.get('type') == 'state' and event.get('state') == 'paused':
                control.resume({**settings, 'save_records':resumed_save})

        with patch('app.session.capture_chunks', capture), \
             patch('app.native_client.stream_native', native), \
             patch('app.session.Journal', FakeJournal):
            asyncio.run(run_session(settings, emit, control))
        return journals, events

    def test_enabling_recording_after_pause_backfills_rows(self):
        journals, _ = self._run_save_toggle(False, True)
        self.assertEqual(len(journals), 1)
        saved_rows = [rows for rows, _ in journals[0].saves]
        self.assertTrue(any(any(row['source'] == 'phase 0' for row in rows)
                            for rows in saved_rows))

    def test_disabling_recording_after_pause_stops_future_saves(self):
        journals, _ = self._run_save_toggle(True, False)
        self.assertEqual(len(journals), 1)
        self.assertGreater(len(journals[0].saves), 0)
        saved_sources = [[row['source'] for row in rows]
                         for rows, _ in journals[0].saves]
        self.assertTrue(all('phase 1' not in sources for sources in saved_sources))

    def test_pause_then_end_preserves_already_captured_tail(self):
        import numpy as np
        from app.session import SessionControl, capture_chunks
        from app.settings import DEFAULTS
        control = SessionControl()
        packets = deque([np.array([.1],dtype=np.float32), np.array([.2],dtype=np.float32), np.array([.3],dtype=np.float32)])
        observed = []
        class Capture:
            error = None
            def start(self):
                pass
            def stop(self):
                pass
            def get_chunk(self, timeout=0):
                if not packets:
                    return None
                result = packets.popleft()
                if len(packets)==2:
                    control.request('pause')
                return result
        async def consume():
            async for packet in capture_chunks({**DEFAULTS,'translation_mode':'off','save_records':False},emit,control):
                observed.append(round(float(packet[0]),1))
        def emit(event):
            if event.get('type')=='state' and event.get('state')=='paused':
                control.request('stop')
        with patch('app.audio.AudioCapture', return_value=Capture()):
            asyncio.run(consume())
        self.assertEqual(observed,[.1,.2,.3])

    def test_pause_toggle_never_resumes_a_stopped_session(self):
        try:
            control = importlib.import_module('app.session').SessionControl()
        except ModuleNotFoundError:
            self.fail('后台会话尚未实现')
        self.assertFalse(control.paused.is_set())
        control.request('pause')
        self.assertTrue(control.paused.is_set())
        control.request('pause')
        self.assertFalse(control.paused.is_set())
        control.request('stop')
        control.request('pause')
        self.assertTrue(control.stopped.is_set())
        self.assertFalse(control.paused.is_set())


if __name__ == '__main__':
    unittest.main()
