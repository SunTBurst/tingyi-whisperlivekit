import threading
import time
import unittest
from unittest.mock import patch

import numpy as np

from app.audio import AudioCapture


class _FakeStream:
    def start_stream(self):
        pass

    def stop_stream(self):
        pass

    def close(self):
        pass


class _FakePyAudio:
    def __init__(self):
        self.devices = [
            {"index": 0, "name": "Speakers", "hostApi": 0, "maxOutputChannels": 2,
             "maxInputChannels": 0, "defaultSampleRate": 48000, "isLoopbackDevice": False},
            {"index": 1, "name": "Speakers (loopback)", "hostApi": 0, "maxOutputChannels": 0,
             "maxInputChannels": 2, "defaultSampleRate": 48000, "isLoopbackDevice": True},
        ]

    def get_host_api_count(self):
        return 1

    def get_host_api_info_by_index(self, index):
        return {"index": 0, "name": "Windows WASAPI", "defaultOutputDevice": 0}

    def get_device_count(self):
        return len(self.devices)

    def get_device_info_by_index(self, index):
        return self.devices[index]

    def open(self, **kwargs):
        return _FakeStream()

    def terminate(self):
        pass


class AudioPacketTelemetryTests(unittest.TestCase):
    def setUp(self):
        self.capture = AudioCapture("system", sample_rate=16000, chunk_duration=0.01)

    def test_enqueued_packets_get_contiguous_sample_offsets(self):
        first = np.arange(4, dtype=np.float32)
        second = np.arange(3, dtype=np.float32)
        self.capture._enqueue(first)
        self.capture._enqueue(second)
        packet1 = self.capture.get_packet(timeout=0)
        packet2 = self.capture.get_packet(timeout=0)
        self.assertEqual(packet1[1], 0)
        self.assertEqual(packet2[1], 4)
        np.testing.assert_array_equal(packet1[0], first)
        np.testing.assert_array_equal(packet2[0], second)

    def test_full_queue_drops_oldest_with_exact_gap_and_counters(self):
        chunks = [np.full(4, index, dtype=np.float32) for index in range(10)]
        for chunk in chunks:
            self.capture._enqueue(chunk)
        self.assertEqual(self.capture.total_dropped_chunks, 2)
        self.assertEqual(self.capture.total_dropped_samples, 8)
        packet = self.capture.get_packet(timeout=0)
        self.assertEqual(packet[1], 8)
        np.testing.assert_array_equal(packet[0], chunks[2])
        self.assertEqual(self.capture.get_chunk(timeout=0).tolist(), chunks[3].tolist())
        packet = self.capture.get_packet(timeout=0)
        self.assertEqual(packet[1], 16)

    def test_stop_tail_follows_live_fifo_and_keeps_sample_offsets(self):
        live = [np.full(2, index, dtype=np.float32) for index in range(3)]
        for chunk in live:
            self.capture._enqueue(chunk)
        tail = np.full(5, 9, dtype=np.float32)
        self.capture._enqueue_stop_tail(tail)
        packets = [self.capture.get_packet(timeout=0) for _ in range(4)]
        self.assertEqual([start for _, start in packets], [0, 2, 4, 6])
        for packet, expected in zip(packets, [*live, tail]):
            np.testing.assert_array_equal(packet[0], expected)

    def test_new_generation_resets_offsets_and_drop_statistics(self):
        with patch("app.audio.pyaudio.PyAudio", _FakePyAudio):
            self.capture._enqueue(np.ones(4, dtype=np.float32))
            self.capture._enqueue(np.ones(4, dtype=np.float32))
            # Force the old queue full without producing audio or opening real devices.
            for _ in range(7):
                self.capture._enqueue(np.ones(4, dtype=np.float32))
            self.capture._enqueue(np.ones(4, dtype=np.float32))
            self.assertGreater(self.capture.total_dropped_chunks, 0)
            self.capture.start()
            self.capture.stop()
            self.capture.start()
            try:
                self.assertEqual(self.capture.total_dropped_chunks, 0)
                self.assertEqual(self.capture.total_dropped_samples, 0)
                self.capture._enqueue(np.ones(3, dtype=np.float32))
                self.assertEqual(self.capture.get_packet(timeout=0)[1], 0)
            finally:
                self.capture.stop()

    def test_waiting_consumer_does_not_block_packet_producer(self):
        ready = threading.Event()
        result = []
        def consume():
            ready.set()
            result.append(self.capture.get_packet(timeout=0.5))
        consumer = threading.Thread(target=consume, daemon=True)
        consumer.start()
        self.assertTrue(ready.wait(0.1))
        started = time.perf_counter()
        self.capture._enqueue(np.arange(6, dtype=np.float32))
        self.assertLess(time.perf_counter() - started, 0.1)
        consumer.join(0.2)
        self.assertFalse(consumer.is_alive())
        self.assertEqual(result[0][1], 0)
        np.testing.assert_array_equal(result[0][0], np.arange(6, dtype=np.float32))


if __name__ == "__main__":
    unittest.main()
