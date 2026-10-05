"""WASAPI audio capture for system playback, microphone, or both."""

from __future__ import annotations

import math
import queue
import threading
import time
from collections import deque
from typing import Optional

import numpy as np
from scipy.signal import resample_poly

try:
    import pyaudiowpatch as pyaudio
except ImportError:  # Keep signal helpers importable on non-Windows systems.
    pyaudio = None


_QUEUE_LIMIT = 8
_MIX_BUFFER_LIMIT = 16
_MIX_LATE_SECONDS = 0.03


def _wasapi_api(pa):
    for i in range(pa.get_host_api_count()):
        info = pa.get_host_api_info_by_index(i)
        if "WASAPI" in info.get("name", "").upper():
            return info
    raise RuntimeError("WASAPI host API not found")


def _devices_for_api(pa, api, direction):
    channel_key = "maxOutputChannels" if direction == "output" else "maxInputChannels"
    found = []
    for index in range(pa.get_device_count()):
        device = pa.get_device_info_by_index(index)
        if device.get("hostApi") != api["index"] or not device.get(channel_key, 0):
            continue
        if direction == "output" and device.get("isLoopbackDevice", False):
            continue
        if direction == "input" and device.get("isLoopbackDevice", False):
            continue
        found.append(device)
    return found


def list_devices() -> dict[str, list[str]]:
    """List usable WASAPI playback and microphone device names."""
    if pyaudio is None:
        raise RuntimeError("pyaudiowpatch is required for WASAPI capture")
    pa = pyaudio.PyAudio()
    try:
        api = _wasapi_api(pa)
        return {
            "output": [d["name"] for d in _devices_for_api(pa, api, "output")],
            "input": [d["name"] for d in _devices_for_api(pa, api, "input")],
        }
    finally:
        pa.terminate()


def _to_mono_resampled(samples, channels: int, input_rate: int, output_rate: int) -> np.ndarray:
    """Convert interleaved or frame-shaped audio to float32 mono at output_rate."""
    data = np.asarray(samples, dtype=np.float32)
    if channels < 1 or input_rate < 1 or output_rate < 1:
        raise ValueError("channels and sample rates must be positive")
    if channels > 1:
        if data.ndim == 1:
            usable = data.size - data.size % channels
            data = data[:usable].reshape(-1, channels)
        elif data.ndim != 2 or data.shape[1] != channels:
            raise ValueError("audio shape does not match channel count")
        data = data.mean(axis=1)
    else:
        data = data.reshape(-1)
    if input_rate != output_rate and data.size:
        divisor = math.gcd(int(input_rate), int(output_rate))
        data = resample_poly(data, output_rate // divisor, input_rate // divisor)
    return np.asarray(data, dtype=np.float32)


def _mix_chunks(system_audio: np.ndarray, mic_audio: np.ndarray) -> np.ndarray:
    """Mix corresponding mono samples, aligning to their shared duration."""
    count = min(len(system_audio), len(mic_audio))
    if count == 0:
        return np.empty(0, dtype=np.float32)
    return np.clip(system_audio[:count] + mic_audio[:count], -1.0, 1.0).astype(np.float32)


class _TimestampBuffer:
    """Bounded FIFO of mono blocks addressed on a shared monotonic timeline."""

    def __init__(self, max_chunks: int = _MIX_BUFFER_LIMIT):
        self._chunks = deque(maxlen=max_chunks)
        self._lock = threading.Lock()

    def push(self, timestamp: float, samples: np.ndarray) -> None:
        samples = np.asarray(samples, dtype=np.float32).reshape(-1)
        if not samples.size:
            return
        with self._lock:
            self._chunks.append([float(timestamp), samples.copy()])

    def oldest_timestamp(self) -> Optional[float]:
        with self._lock:
            return self._chunks[0][0] if self._chunks else None

    def latest_end_timestamp(self, sample_rate: int) -> Optional[float]:
        with self._lock:
            if not self._chunks:
                return None
            return max(timestamp + len(samples) / sample_rate for timestamp, samples in self._chunks)

    def next_data_timestamp(self, start: float, sample_rate: int) -> Optional[float]:
        with self._lock:
            for timestamp, samples in self._chunks:
                end = timestamp + len(samples) / sample_rate
                if end > start:
                    return max(start, timestamp)
            return None

    def has_data_in_window(self, start: float, end: float, sample_rate: int) -> bool:
        with self._lock:
            return any(timestamp < end and timestamp + len(samples) / sample_rate > start
                       for timestamp, samples in self._chunks)

    def pop_window(self, start: float, frames: int, sample_rate: int) -> np.ndarray:
        """Return samples for [start, start+frames/rate), zero-filling gaps."""
        result = np.zeros(frames, dtype=np.float32)
        end = start + frames / sample_rate
        with self._lock:
            while self._chunks:
                timestamp, data = self._chunks[0]
                if timestamp + len(data) / sample_rate <= start:
                    self._chunks.popleft()
                    continue
                if timestamp >= end:
                    break
                if timestamp < start:
                    trim = min(len(data), max(0, int(round((start - timestamp) * sample_rate))))
                    timestamp += trim / sample_rate
                    data = data[trim:]
                    self._chunks[0] = [timestamp, data]
                    if not len(data):
                        self._chunks.popleft()
                        continue
                offset = max(0, int(round((timestamp - start) * sample_rate)))
                if offset >= frames:
                    break
                count = min(len(data), frames - offset)
                result[offset:offset + count] = data[:count]
                if count == len(data):
                    self._chunks.popleft()
                else:
                    self._chunks[0] = [timestamp + count / sample_rate, data[count:]]
        return result


class AudioCapture:
    """Capture WASAPI loopback, microphone, or a clipped mono mix of both.

    Calling stop() releases the streams and PortAudio instance. The same object
    can then be started again. Capture callbacks map blocks to a shared
    monotonic timeline; bounded FIFOs align the two sources and zero-fill gaps.
    Callback and mixer failures are stored in ``error``.
    """

    def __init__(self, mode: str, output_device: Optional[str] = None,
                 mic_device: Optional[str] = None, sample_rate: int = 16000,
                 chunk_duration: float = 0.1):
        if mode not in ("system", "mic", "both"):
            raise ValueError("mode must be 'system', 'mic', or 'both'")
        if sample_rate <= 0 or chunk_duration <= 0:
            raise ValueError("sample_rate and chunk_duration must be positive")
        self.mode = mode
        self.output_device = output_device
        self.mic_device = mic_device
        self.sample_rate = int(sample_rate)
        self.chunk_duration = float(chunk_duration)
        self.audio_queue: queue.Queue[tuple[np.ndarray, int] | np.ndarray] = queue.Queue(maxsize=_QUEUE_LIMIT)
        # Tail frames are drained only after the live queue. They are bounded
        # by the timestamp buffers and never enlarge the live backpressure queue.
        self._stop_tail = deque()
        self.error: Optional[str] = None
        self._pa = None
        self._streams = []
        self._running = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._mix_timeline: Optional[float] = None
        self._lock = threading.RLock()
        self._generation = 0
        self._data_event = threading.Event()
        self._packet_event = threading.Event()
        self._packet_lock = threading.Lock()
        self._sample_cursor = 0
        self._dropped_chunks = 0
        self._dropped_samples = 0
        self._buffers = {"system": _TimestampBuffer(), "mic": _TimestampBuffer()}

    @property
    def total_dropped_chunks(self) -> int:
        return self._dropped_chunks

    @property
    def total_dropped_samples(self) -> int:
        return self._dropped_samples

    @property
    def dropped_chunks(self) -> int:
        return self._dropped_chunks

    @property
    def dropped_samples(self) -> int:
        return self._dropped_samples

    @property
    def drop_statistics(self) -> dict[str, int]:
        return {"dropped_chunks": self._dropped_chunks, "dropped_samples": self._dropped_samples}

    def _select_output(self, pa, api):
        outputs = _devices_for_api(pa, api, "output")
        if not outputs:
            raise RuntimeError("No WASAPI output device found")
        if self.output_device is None:
            output = next((d for d in outputs if d["index"] == api.get("defaultOutputDevice")), None)
            if output is None:
                raise RuntimeError("Default WASAPI output device is unavailable")
        else:
            output = next((d for d in outputs if d["name"] == self.output_device), None)
            if output is None:
                raise RuntimeError(f"WASAPI output device not found: {self.output_device}")
        loops = []
        for i in range(pa.get_device_count()):
            device = pa.get_device_info_by_index(i)
            if device.get("hostApi") == api["index"] and device.get("isLoopbackDevice", False):
                loops.append(device)
        # PortAudioWPatch names each loopback as its output name plus this suffix.
        def loopback_parent(name):
            lowered = name.casefold()
            for suffix in (" (loopback)", " [loopback]"):
                if lowered.endswith(suffix):
                    return name[:-len(suffix)]
            return None

        loopback = next((d for d in loops if loopback_parent(d["name"]) == output["name"]), None)
        if loopback is None:
            raise RuntimeError(f"WASAPI loopback device not found for output: {output['name']}")
        return loopback

    def _select_mic(self, pa, api):
        inputs = _devices_for_api(pa, api, "input")
        if not inputs:
            raise RuntimeError("No WASAPI input device found")
        if self.mic_device is None:
            mic = next((d for d in inputs if d["index"] == api.get("defaultInputDevice")), None)
            if mic is None:
                raise RuntimeError("Default WASAPI input device is unavailable")
            return mic
        mic = next((d for d in inputs if d["name"] == self.mic_device), None)
        if mic is None:
            raise RuntimeError(f"WASAPI input device not found: {self.mic_device}")
        return mic

    def _open(self, pa, device, source, generation):
        channels = int(device["maxInputChannels"])
        rate = int(device["defaultSampleRate"])
        frames = max(1, int(round(rate * self.chunk_duration)))
        callback = lambda in_data, frame_count, time_info, status: self._audio_callback(
            source, generation, in_data, frame_count, time_info, status
        )
        stream = pa.open(format=pyaudio.paFloat32, channels=channels, rate=rate,
                         input=True, input_device_index=device["index"],
                         frames_per_buffer=frames, stream_callback=callback, start=False)
        return {"stream": stream, "channels": channels, "rate": rate, "frames": frames,
                "source": source}

    def _audio_callback(self, source, generation, in_data, frame_count, time_info, status_flags):
        if generation != self._generation or not self._running.is_set():
            return (None, getattr(pyaudio, "paComplete", 1))
        try:
            descriptor = self._streams_by_source[source]
            converted = _to_mono_resampled(
                np.frombuffer(in_data, dtype=np.float32), descriptor["channels"],
                descriptor["rate"], self.sample_rate,
            )
            now = time.perf_counter()
            info = time_info or {}
            adc_time = info.get("input_buffer_adc_time")
            current_time = info.get("current_time")
            if adc_time is not None and current_time is not None:
                timestamp = now + float(adc_time) - float(current_time)
            else:
                timestamp = now - len(converted) / self.sample_rate
            if self.mode == "both":
                self._buffers[source].push(timestamp, converted)
                self._data_event.set()
            else:
                self._enqueue(converted, generation=generation)
        except Exception as exc:
            self.error = f"{source} capture callback failed: {exc}"
            self._running.clear()
            self._data_event.set()
            return (None, getattr(pyaudio, "paAbort", 2))
        return (None, getattr(pyaudio, "paContinue", 0))

    def start(self):
        with self._lock:
            if self._running.is_set():
                return self
            self.error = None
            self._generation += 1
            generation = self._generation
            self._buffers = {"system": _TimestampBuffer(), "mic": _TimestampBuffer()}
            self._mix_timeline = None
            self._data_event.clear()
            self._packet_event.clear()
            with self._packet_lock:
                self._sample_cursor = 0
                self._dropped_chunks = 0
                self._dropped_samples = 0
                while not self.audio_queue.empty():
                    try:
                        self.audio_queue.get_nowait()
                    except queue.Empty:
                        break
                self._stop_tail.clear()
            if pyaudio is None:
                self.error = "pyaudiowpatch is required for WASAPI capture"
                raise RuntimeError(self.error)
            try:
                self._pa = pyaudio.PyAudio()
                api = _wasapi_api(self._pa)
                self._streams_by_source = {}
                if self.mode in ("system", "both"):
                    descriptor = self._open(
                        self._pa, self._select_output(self._pa, api), "system", generation
                    )
                    self._streams.append(descriptor)
                    self._streams_by_source["system"] = descriptor
                if self.mode in ("mic", "both"):
                    descriptor = self._open(
                        self._pa, self._select_mic(self._pa, api), "mic", generation
                    )
                    self._streams.append(descriptor)
                    self._streams_by_source["mic"] = descriptor
                self._running.set()
                if self.mode == "both":
                    self._thread = threading.Thread(
                        target=self._mix_loop, args=(generation,), name="AudioCaptureMixer", daemon=True
                    )
                    self._thread.start()
                for descriptor in self._streams:
                    descriptor["stream"].start_stream()
                return self
            except Exception as exc:
                self.error = str(exc)
                self._cleanup()
                raise

    def _enqueue(self, chunk, generation=None):
        chunk = np.asarray(chunk, dtype=np.float32).reshape(-1)
        if chunk.size == 0:
            return
        with self._packet_lock:
            if generation is not None and generation != self._generation:
                return
            start_sample = self._sample_cursor
            self._sample_cursor += int(chunk.size)
            packet = (chunk, start_sample)
            try:
                self.audio_queue.put_nowait(packet)
            except queue.Full:
                try:
                    dropped = self.audio_queue.get_nowait()
                    if isinstance(dropped, tuple) and len(dropped) == 2:
                        dropped_samples = int(np.asarray(dropped[0]).size)
                    else:
                        dropped_samples = int(np.asarray(dropped).size)
                    self._dropped_chunks += 1
                    self._dropped_samples += dropped_samples
                except queue.Empty:
                    pass
                try:
                    self.audio_queue.put_nowait(packet)
                except queue.Full:
                    # A concurrent consumer cannot make the queue fuller; this
                    # branch protects against an externally replaced queue.
                    self._dropped_chunks += 1
                    self._dropped_samples += int(chunk.size)
                    return
        self._packet_event.set()

    def _pop_packet(self):
        with self._packet_lock:
            try:
                packet = self.audio_queue.get_nowait()
            except queue.Empty:
                packet = None
            if packet is not None:
                if isinstance(packet, tuple) and len(packet) == 2:
                    return packet
                return packet, self._sample_cursor
            if self._stop_tail:
                return self._stop_tail.popleft()
            return None

    def _mix_loop(self, generation):
        frames = max(1, int(round(self.sample_rate * self.chunk_duration)))
        duration = frames / self.sample_rate
        timeline = None
        try:
            while self._running.is_set() and generation == self._generation:
                if timeline is None:
                    system_time = self._buffers["system"].oldest_timestamp()
                    mic_time = self._buffers["mic"].oldest_timestamp()
                    if system_time is None or mic_time is None:
                        self._data_event.wait(timeout=0.05)
                        self._data_event.clear()
                        continue
                    timeline = min(system_time, mic_time)
                    self._mix_timeline = timeline
                due = timeline + duration + _MIX_LATE_SECONDS
                delay = due - time.perf_counter()
                if delay > 0:
                    self._data_event.wait(timeout=min(delay, 0.05))
                    self._data_event.clear()
                    continue
                system_audio = self._buffers["system"].pop_window(timeline, frames, self.sample_rate)
                mic_audio = self._buffers["mic"].pop_window(timeline, frames, self.sample_rate)
                self._enqueue(_mix_chunks(system_audio, mic_audio), generation=generation)
                timeline += duration
                self._mix_timeline = timeline
        except Exception as exc:
            if generation == self._generation:
                self.error = f"audio mixer failed: {exc}"
                self._running.clear()
                self._data_event.set()

    def get_packet(self, timeout: float = 0.2) -> Optional[tuple[np.ndarray, int]]:
        """Return one output block and its start sample on this generation's timeline."""
        deadline = time.monotonic() + max(0.0, float(timeout))
        while True:
            self._packet_event.clear()
            packet = self._pop_packet()
            if packet is not None:
                samples, start_sample = packet
                return np.asarray(samples, dtype=np.float32), int(start_sample)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            self._packet_event.wait(remaining)

    def get_chunk(self, timeout: float = 0.2) -> Optional[np.ndarray]:
        """Legacy audio-only API, consuming the same FIFO as ``get_packet``."""
        packet = self.get_packet(timeout=timeout)
        return packet[0] if packet is not None else None

    def _enqueue_stop_tail(self, chunk):
        """Stage shutdown audio after queued live chunks without dropping either."""
        chunk = np.asarray(chunk, dtype=np.float32).reshape(-1)
        if chunk.size:
            with self._packet_lock:
                start_sample = self._sample_cursor
                self._sample_cursor += int(chunk.size)
                self._stop_tail.append((chunk, start_sample))
            self._packet_event.set()

    def _flush_mixed_tail(self):
        """Synchronously mix only captured, not-yet-emitted timestamped audio."""
        rate = self.sample_rate
        window_frames = max(1, int(round(rate * self.chunk_duration)))
        oldest = [buffer.oldest_timestamp() for buffer in self._buffers.values()]
        oldest = [timestamp for timestamp in oldest if timestamp is not None]
        ends = [buffer.latest_end_timestamp(rate) for buffer in self._buffers.values()]
        ends = [timestamp for timestamp in ends if timestamp is not None]
        if not oldest or not ends:
            return

        timeline = self._mix_timeline
        if timeline is None:
            timeline = min(oldest)
        latest_end = max(ends)
        while timeline < latest_end:
            next_starts = [buffer.next_data_timestamp(timeline, rate)
                           for buffer in self._buffers.values()]
            next_starts = [timestamp for timestamp in next_starts if timestamp is not None]
            if not next_starts:
                break
            next_start = min(next_starts)
            if next_start > timeline:
                # Keep the common frame grid while jumping over uncaptured gaps.
                steps = int(math.floor((next_start - timeline) / (window_frames / rate)))
                timeline += max(0, steps) * (window_frames / rate)
            remaining = max(1, int(math.ceil((latest_end - timeline) * rate - 1e-6)))
            frames = min(window_frames, remaining)
            end = timeline + frames / rate
            system = self._buffers["system"]
            mic = self._buffers["mic"]
            has_audio = (
                system.has_data_in_window(timeline, end, rate)
                or mic.has_data_in_window(timeline, end, rate)
            )
            if has_audio:
                system_audio = system.pop_window(timeline, frames, rate)
                mic_audio = mic.pop_window(timeline, frames, rate)
                self._enqueue_stop_tail(_mix_chunks(system_audio, mic_audio))
            timeline = end
        self._mix_timeline = timeline

    def _cleanup(self, *, flush_tail=False):
        self._running.clear()
        self._generation += 1
        self._data_event.set()
        self._packet_event.set()
        worker = self._thread
        if worker and worker is not threading.current_thread():
            worker.join(timeout=1.0)
        self._thread = None
        for descriptor in self._streams:
            stream = descriptor["stream"]
            try:
                stream.stop_stream()
            except Exception:
                pass
        for descriptor in self._streams:
            try:
                descriptor["stream"].close()
            except Exception:
                pass
        self._streams.clear()
        if self._pa is not None:
            try:
                self._pa.terminate()
            finally:
                self._pa = None
        if flush_tail and self.mode == "both":
            self._flush_mixed_tail()

    def stop(self):
        with self._lock:
            self._cleanup(flush_tail=True)
