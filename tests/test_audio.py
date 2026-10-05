import unittest
import threading
import time
from unittest.mock import patch

import numpy as np

from app.audio import AudioCapture, _TimestampBuffer, _mix_chunks, _to_mono_resampled


class FakeStream:
    def __init__(self, channels, frames, callback=None):
        self.channels = channels
        self.frames = frames
        self.callback = callback
        self.closed = False

    def read(self, count, exception_on_overflow=False):
        return np.zeros(count * self.channels, dtype=np.float32).tobytes()

    def stop_stream(self):
        pass

    def start_stream(self):
        pass

    def close(self):
        self.closed = True


class FakePyAudio:
    def __init__(self):
        self.devices = [
            {"index": 0, "name": "Speakers", "hostApi": 0, "maxOutputChannels": 2,
             "maxInputChannels": 0, "defaultSampleRate": 48000, "isLoopbackDevice": False},
            {"index": 1, "name": "Speakers (loopback)", "hostApi": 0, "maxOutputChannels": 0,
             "maxInputChannels": 2, "defaultSampleRate": 48000, "isLoopbackDevice": True},
            {"index": 2, "name": "Microphone", "hostApi": 0, "maxOutputChannels": 0,
             "maxInputChannels": 1, "defaultSampleRate": 44100, "isLoopbackDevice": False},
        ]

    def get_host_api_count(self):
        return 1

    def get_host_api_info_by_index(self, index):
        return {"index": 0, "name": "Windows WASAPI", "defaultOutputDevice": 0, "defaultInputDevice": 2}

    def get_device_count(self):
        return len(self.devices)

    def get_device_info_by_index(self, index):
        return self.devices[index]

    def open(self, channels, frames_per_buffer, **kwargs):
        return FakeStream(channels, frames_per_buffer, callback=kwargs.get("stream_callback"))

    def terminate(self):
        pass


class AudioSignalTests(unittest.TestCase):
    def test_stereo_downmix_averages_channels(self):
        stereo = np.array([[0.2, -0.2], [0.6, 0.2]], dtype=np.float32)
        mono = _to_mono_resampled(stereo, channels=2, input_rate=16000, output_rate=16000)
        np.testing.assert_allclose(mono, [0.0, 0.4], atol=1e-6)

    def test_48khz_audio_is_resampled_to_16khz(self):
        source = np.sin(2 * np.pi * 440 * np.arange(4800) / 48000).astype(np.float32)
        converted = _to_mono_resampled(source, channels=1, input_rate=48000, output_rate=16000)
        self.assertEqual(converted.dtype, np.float32)
        self.assertEqual(len(converted), 1600)
        self.assertGreater(float(np.sqrt(np.mean(converted**2))), 0.6)

    def test_both_streams_mix_and_clip_to_float_audio_range(self):
        mixed = _mix_chunks(np.array([0.8, -0.8]), np.array([0.7, -0.7]))
        np.testing.assert_array_equal(mixed, np.array([1.0, -1.0], dtype=np.float32))

    def test_timestamp_buffer_aligns_samples_and_fills_missing_audio_with_silence(self):
        system = _TimestampBuffer(max_chunks=4)
        mic = _TimestampBuffer(max_chunks=4)
        system.push(10.0, np.full(4, 0.25, dtype=np.float32))
        mic.push(10.000125, np.full(2, 0.5, dtype=np.float32))

        mixed = _mix_chunks(system.pop_window(10.0, 6, 16000), mic.pop_window(10.0, 6, 16000))
        np.testing.assert_array_equal(mixed, [0.25, 0.25, 0.75, 0.75, 0.0, 0.0])


class AudioCaptureValidationTests(unittest.TestCase):
    def test_rejects_unknown_mode(self):
        with self.assertRaisesRegex(ValueError, "mode"):
            AudioCapture("desktop")

    def test_rejects_missing_requested_device_instead_of_falling_back(self):
        capture = AudioCapture("system", output_device="Definitely Missing")
        try:
            with self.assertRaisesRegex(RuntimeError, "Definitely Missing"):
                capture.start()
            self.assertIsNotNone(capture.error)
        finally:
            capture.stop()

    def test_stop_then_start_is_supported(self):
        with patch("app.audio.pyaudio.PyAudio", FakePyAudio):
            capture = AudioCapture("system", chunk_duration=0.01)
            try:
                capture.start()
                capture.stop()
                capture.start()
                self.assertIsNone(capture.error)
            finally:
                capture.stop()

    def test_stop_does_not_wait_for_a_stuck_blocking_read(self):
        read_entered = threading.Event()
        release_read = threading.Event()

        class StuckReadStream(FakeStream):
            def read(self, count, exception_on_overflow=False):
                read_entered.set()
                release_read.wait()
                return super().read(count, exception_on_overflow)

        class StuckReadPA(FakePyAudio):
            def open(self, channels, frames_per_buffer, **kwargs):
                return StuckReadStream(channels, frames_per_buffer, callback=kwargs.get("stream_callback"))

        with patch("app.audio.pyaudio.PyAudio", StuckReadPA):
            capture = AudioCapture("system", chunk_duration=0.01)
            capture.start()
            try:
                self.assertFalse(read_entered.wait(0.1), "capture must use callbacks, not blocking reads")
                stopped = threading.Event()
                stopper = threading.Thread(target=lambda: (capture.stop(), stopped.set()), daemon=True)
                stopper.start()
                self.assertTrue(stopped.wait(1.0), "stop should have a bounded completion time")
            finally:
                release_read.set()
                capture.stop()


class AudioCapturePendingTailTests(unittest.TestCase):
    @staticmethod
    def pending_capture(chunk_duration=0.01):
        capture = AudioCapture("both", chunk_duration=chunk_duration)
        capture._generation = 1
        capture._running.set()
        capture._buffers = {"system": _TimestampBuffer(), "mic": _TimestampBuffer()}
        return capture

    def test_stop_flushes_real_timestamp_buffers_not_yet_due_to_mixer(self):
        capture = self.pending_capture()
        start = time.perf_counter() - 0.001
        capture._buffers["system"].push(start, np.full(160, 0.25, dtype=np.float32))
        capture._buffers["mic"].push(start, np.full(160, 0.5, dtype=np.float32))
        with patch("app.audio._MIX_LATE_SECONDS", 1.0):
            mixer = threading.Thread(target=capture._mix_loop, args=(capture._generation,), daemon=True)
            capture._thread = mixer
            mixer.start()
            # The ordinary mixer holds this final window for its lateness allowance.
            time.sleep(0.005)
            self.assertTrue(capture.audio_queue.empty())

            capture.stop()

        tail = capture.get_chunk(timeout=0)
        self.assertIsNotNone(tail)
        self.assertEqual(tail.shape, (160,))
        np.testing.assert_array_equal(tail, np.full(160, 0.75, dtype=np.float32))
        self.assertIsNone(capture.get_chunk(timeout=0))

    def test_stop_continues_after_last_emitted_window_and_mixes_partial_overlap(self):
        capture = self.pending_capture()
        start = time.perf_counter() - 0.2
        old_system = np.full(160, 0.1, dtype=np.float32)
        old_mic = np.full(160, 0.1, dtype=np.float32)
        capture._buffers["system"].push(start, old_system)
        capture._buffers["mic"].push(start, old_mic)
        previous = _mix_chunks(
            capture._buffers["system"].pop_window(start, 160, 16000),
            capture._buffers["mic"].pop_window(start, 160, 16000),
        )
        capture.audio_queue.put_nowait(previous)
        next_start = start + 160 / 16000
        capture._mix_timeline = next_start
        capture._buffers["system"].push(next_start, np.full(160, 0.2, dtype=np.float32))
        capture._buffers["mic"].push(next_start + 80 / 16000, np.full(80, 0.3, dtype=np.float32))

        capture.stop()

        actual_previous = capture.get_chunk(timeout=0)
        actual_tail = capture.get_chunk(timeout=0)
        self.assertIsNotNone(actual_previous)
        self.assertIsNotNone(actual_tail)
        np.testing.assert_array_equal(actual_previous, np.full(160, 0.2, dtype=np.float32))
        expected_tail = np.full(160, 0.2, dtype=np.float32)
        expected_tail[80:] = 0.5
        np.testing.assert_array_equal(actual_tail, expected_tail)
        self.assertIsNone(capture.get_chunk(timeout=0))

    def test_restart_discards_prior_generation_buffers_and_callbacks(self):
        with patch("app.audio.pyaudio.PyAudio", FakePyAudio):
            capture = AudioCapture("both", chunk_duration=0.01)
            capture.start()
            old_generation = capture._generation
            old_buffers = capture._buffers
            capture._buffers["system"].push(time.perf_counter(), np.ones(160, dtype=np.float32))
            capture.stop()

            capture.start()
            try:
                self.assertGreater(capture._generation, old_generation)
                self.assertIsNot(capture._buffers, old_buffers)
                self.assertIsNone(capture._buffers["system"].oldest_timestamp())
                before = capture.audio_queue.qsize()
                capture._audio_callback("system", old_generation, np.ones(480, dtype=np.float32).tobytes(),
                                        480, {}, 0)
                self.assertEqual(capture.audio_queue.qsize(), before)
                self.assertIsNone(capture._buffers["system"].oldest_timestamp())
            finally:
                capture.stop()

    def test_stop_tail_follows_full_live_queue_without_dropping_old_audio(self):
        capture = self.pending_capture()
        old_chunks = [np.full(4, index, dtype=np.float32) for index in range(8)]
        for chunk in old_chunks:
            capture.audio_queue.put_nowait(chunk)
        start = time.perf_counter()
        capture._buffers["system"].push(start, np.full(160, 0.25, dtype=np.float32))
        capture._buffers["mic"].push(start, np.full(160, 0.5, dtype=np.float32))

        capture.stop()

        self.assertEqual(capture.audio_queue.maxsize, 8)
        self.assertEqual(capture.audio_queue.qsize(), 8)
        actual = [capture.get_chunk(timeout=0) for _ in range(9)]
        for got, expected in zip(actual[:8], old_chunks):
            np.testing.assert_array_equal(got, expected)
        np.testing.assert_array_equal(actual[8], np.full(160, 0.75, dtype=np.float32))
        self.assertIsNone(capture.get_chunk(timeout=0))

    def test_stop_tail_skips_uncollected_gaps_between_timestamped_blocks(self):
        capture = self.pending_capture()
        start = time.perf_counter()
        late = start + 3600.0
        for buffer, value in ((capture._buffers["system"], 0.25),
                              (capture._buffers["mic"], 0.5)):
            buffer.push(start, np.full(160, value, dtype=np.float32))
            buffer.push(late, np.full(160, value, dtype=np.float32))

        capture.stop()

        chunks = [capture.get_chunk(timeout=0) for _ in range(3)]
        self.assertEqual(len([chunk for chunk in chunks if chunk is not None]), 2)
        np.testing.assert_array_equal(chunks[0], np.full(160, 0.75, dtype=np.float32))
        np.testing.assert_array_equal(chunks[1], np.full(160, 0.75, dtype=np.float32))


if __name__ == "__main__":
    unittest.main()
