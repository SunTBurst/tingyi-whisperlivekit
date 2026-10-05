import importlib.util
import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "setup_native_whisper.py"
SPEC = importlib.util.spec_from_file_location("setup_native_whisper", SCRIPT)
runtime = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runtime)


class NativeWhisperRuntimeTests(unittest.TestCase):
    def test_model_target_is_in_native_whisper_folder(self):
        expected_root = Path("F:/test-root") / "models" / "native-whisper" / "small.pt"
        self.assertEqual(runtime.model_path(Path("F:/test-root")), expected_root)

    def test_checkpoint_validation_uses_expected_sha256(self):
        data = b"tiny test checkpoint"
        digest = hashlib.sha256(data).hexdigest()
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "small.pt"
            target.write_bytes(data)
            self.assertTrue(runtime.validate_checkpoint(target, digest))
            self.assertFalse(runtime.validate_checkpoint(target, "0" * 64))

    def test_whisper_and_translation_run_configs_are_explicit(self):
        path = Path("models/native-whisper/small.pt")
        translated = runtime.streaming_options(path, source="en", target="zh")
        self.assertEqual(translated["backend"], "whisper")
        self.assertEqual(translated["backend_policy"], "simulstreaming")
        self.assertEqual(translated["model_size"], "small")
        self.assertEqual(translated["model_path"], str(path))
        self.assertEqual(translated["lan"], "en")
        self.assertEqual(translated["target_language"], "zh")
        direct = runtime.streaming_options(path, source="zh", direct_english=True)
        self.assertTrue(direct["direct_english_translation"])
        self.assertEqual(direct["target_language"], "")

    def test_bundled_ffmpeg_is_prepended_for_test_harness_audio_loading(self):
        with tempfile.TemporaryDirectory() as folder:
            ffmpeg_dir = Path(folder) / "runtime" / "ffmpeg"
            ffmpeg_dir.mkdir(parents=True)
            executable = ffmpeg_dir / "ffmpeg.exe"
            executable.write_bytes(b"fixture")
            with patch.dict(os.environ, {"PATH": "existing"}):
                self.assertEqual(runtime.ensure_ffmpeg_on_path(Path(folder)), executable)
                self.assertEqual(os.environ["PATH"].split(os.pathsep)[0], str(ffmpeg_dir.resolve()))

    def test_download_publishes_only_sha_verified_model(self):
        data = b"official small checkpoint fixture"
        digest = hashlib.sha256(data).hexdigest()

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self, size=-1):
                nonlocal data
                chunk, data = data[:size], data[size:]
                return chunk

        def fake_open(_url, **_kwargs):
            return Response()

        with tempfile.TemporaryDirectory() as folder:
            path = runtime.download_checkpoint(Path(folder), url=f"https://example.invalid/{digest}/small.pt",
                                               opener=fake_open, expected_sha256=digest)
            self.assertEqual(path.read_bytes(), b"official small checkpoint fixture")
            self.assertTrue(runtime.validate_checkpoint(path, digest))

    def test_bad_download_is_not_published(self):
        class Response:
            def __init__(self):
                self.sent = False

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self, _size=-1):
                if self.sent:
                    return b""
                self.sent = True
                return b"bad checkpoint"

        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(RuntimeError, "SHA256 mismatch"):
                runtime.download_checkpoint(Path(folder), opener=lambda *_args, **_kwargs: Response(),
                                            expected_sha256="0" * 64)
            self.assertFalse(runtime.model_path(Path(folder)).exists())
            self.assertFalse(runtime.model_path(Path(folder)).with_suffix(".pt.download").exists())


if __name__ == "__main__":
    unittest.main()
