import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.native_cli import _option_value, build_bench_arguments
from app.settings import ROOT


def _config(**updates):
    values = {
        "backend": "faster-whisper",
        "model_size": "medium",
        "lan": "en",
        "model_dir": r"C:\demo\tingyi\models\whisper-medium",
        "model_path": None,
        "api_token": "secret",
        "min_chunk_size": 0.5,
    }
    values.update(updates)
    return SimpleNamespace(**values)


class NativeCliBenchTests(unittest.TestCase):
    def test_explicit_model_with_separate_value_uses_matching_local_model_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            local_model = root / "models" / "whisper-small"
            local_model.mkdir(parents=True)
            (local_model / "model.bin").write_bytes(b"fixture")
            (local_model / "config.json").write_text("{}", encoding="utf-8")
            config_path = Path(directory) / "engine-options.json"
            with patch("app.native_cli.ROOT", root):
                args = build_bench_arguments(["--model", "small"], _config(), config_file=config_path)
            self.assertEqual(args[args.index("--model") + 1], "small")
            options = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(Path(options["model_dir"]), local_model)
            self.assertNotIn("model_path", options)
            self.assertEqual(options["min_chunk_size"], 0.5)
            for reserved in ("backend", "model_size", "lan", "api_token"):
                self.assertNotIn(reserved, options)

    def test_explicit_model_with_equals_syntax_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            local_model = root / "models" / "whisper-small"
            local_model.mkdir(parents=True)
            (local_model / "model.bin").write_bytes(b"fixture")
            (local_model / "config.json").write_text("{}", encoding="utf-8")
            config_path = Path(directory) / "options.json"
            with patch("app.native_cli.ROOT", root):
                args = build_bench_arguments(["--model=small"], _config(), config_file=config_path)
            self.assertIn("--model=small", args)
            self.assertNotIn("--model", args)
            options = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(Path(options["model_dir"]), local_model)

    def test_language_aliases_and_equals_syntax_are_not_overridden(self):
        cases = [(["--languages", "fr"], "fr"), (["--lan", "zh"], "zh"), (["--languages=ar"], "ar"), (["--lan=ja"], "ja")]
        for supplied, expected in cases:
            with self.subTest(supplied=supplied), tempfile.TemporaryDirectory() as directory:
                args = build_bench_arguments(supplied, _config(), config_file=Path(directory) / "options.json")
                language_flags = [item for item in args if item in ("--languages", "--lan") or item.startswith(("--languages=", "--lan="))]
                self.assertEqual(len(language_flags), 1)
                self.assertEqual(args[args.index("--model") + 1], "medium")
                parsed_language = None
                for index, item in enumerate(args):
                    if item in ("--languages", "--lan"):
                        parsed_language = args[index + 1]
                    elif item.startswith(("--languages=", "--lan=")):
                        parsed_language = item.split("=", 1)[1]
                self.assertEqual(parsed_language, expected)

    def test_defaults_are_added_only_when_no_model_language_or_backend_option_exists(self):
        with tempfile.TemporaryDirectory() as directory:
            args = build_bench_arguments([], _config(), config_file=Path(directory) / "options.json")
        self.assertEqual(args[args.index("--model") + 1], "medium")
        self.assertEqual(args[args.index("--backend") + 1], "faster-whisper")
        self.assertEqual(args[args.index("--languages") + 1], "en")

    def test_supplied_config_file_merges_additional_options_but_reserved_keys_are_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            user_config = directory / "custom.json"
            user_config.write_text(json.dumps({"nllb_size": "1.3B", "model_size": "wrong", "api_token": "leak"}), encoding="utf-8")
            destination = directory / "built.json"
            args = build_bench_arguments(["--config", str(user_config)], _config(), config_file=destination)
            self.assertEqual(Path(args[args.index("--config") + 1]), destination)
            result = json.loads(destination.read_text(encoding="utf-8"))
            self.assertEqual(result["nllb_size"], "1.3B")
            self.assertEqual(result["min_chunk_size"], 0.5)
            for reserved in ("backend", "model_size", "lan", "api_token"):
                self.assertNotIn(reserved, result)

    def test_supplied_inline_json_is_normalized_to_a_path(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "built.json"
            args = build_bench_arguments(["--config={\"custom_flag\":true}"], _config(), config_file=destination)
            self.assertEqual(Path(_option_value(args, "--config")), destination)
            options = json.loads(destination.read_text(encoding="utf-8"))
            self.assertTrue(options["custom_flag"])
            self.assertEqual(options["min_chunk_size"], 0.5)

    def test_speaker_runtime_imports_vendored_upstream_through_native_cli(self):
        interpreter = ROOT / "runtime" / "speaker" / "Scripts" / "python.exe"
        if not interpreter.is_file():
            self.skipTest("isolated speaker runtime has not been installed")
        result = subprocess.run(
            [str(interpreter), "-c", "import app.native_cli; import whisperlivekit.config; print(whisperlivekit.config.__file__)"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        self.assertTrue(Path(result.stdout.strip()).is_relative_to(ROOT / "upstream"))


if __name__ == "__main__":
    unittest.main()
