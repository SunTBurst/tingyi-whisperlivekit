import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app import model_manager, native_models


class ModelManagerTests(unittest.TestCase):
    def test_catalog_and_local_install_state_include_existing_models(self):
        with tempfile.TemporaryDirectory(prefix="models-fixture-") as directory:
            root = Path(directory)
            for relative in (
                "native-whisper/small.pt",
                "nllb-600m/model.bin",
                "nllb-600m/config.json",
                "nllb-600m/tokenizer.json",
                "nllb-600m/shared_vocabulary.txt",
                "whisper-small/model.bin",
                "whisper-small/config.json",
                "whisper-medium/model.bin",
                "whisper-medium/config.json",
            ):
                placeholder = root / relative
                placeholder.parent.mkdir(parents=True, exist_ok=True)
                placeholder.write_text("test placeholder", encoding="utf-8")
            with patch.object(model_manager, "MODEL_ROOT", root), \
                 patch.object(model_manager, "_hub_repos", return_value={}), \
                 patch("app.model_registry.REGISTRY_PATH", root / "model-registry.json"):
                names = {entry["name"] for entry in model_manager.catalog()}
                self.assertIn("nllb-600m-int8", names)
                self.assertIn("voxtral", names)
                self.assertIn("qwen3-vllm:1.7b", names)
                for size in ("tiny", "tiny.en", "base", "base.en", "small", "small.en", "medium", "medium.en",
                             "large-v1", "large-v2", "large-v3", "large-v3-turbo"):
                    self.assertIn(f"whisper-{size}", names)
                    self.assertIn(f"native-whisper-{size}", names)
                native_small = next(x for x in model_manager.installed_models() if x["name"] == "native-whisper-small")
                self.assertTrue(native_small["installed"])
                turbo = next(x for x in model_manager.catalog() if x["name"] == "whisper-large-v3-turbo")
                self.assertEqual(turbo["repo"], "mobiuslabsgmbh/faster-whisper-large-v3-turbo")
                installed = {entry["name"]: entry["installed"] for entry in model_manager.installed_models()}
                self.assertTrue(installed["nllb-600m-int8"])
                self.assertTrue(installed["whisper-small"])
                self.assertTrue(installed["whisper-medium"])

    def test_unknown_download_name_is_rejected_before_network_access(self):
        with self.assertRaisesRegex(ValueError, "Unknown model"):
            model_manager.download_model("not-a-model")

    def test_remove_model_refuses_any_path_outside_models(self):
        with self.assertRaisesRegex(ValueError, "outside"):
            model_manager.remove_model(model_manager.ROOT / "README.md")

    def test_remove_model_accepts_only_child_paths(self):
        model_manager.MODEL_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="manager-test-", dir=model_manager.MODEL_ROOT) as child:
            marker = Path(child) / "marker"
            marker.write_text("temporary", encoding="utf-8")
            removed = model_manager.remove_model(child)
            self.assertEqual(removed, Path(child).resolve())
            self.assertFalse(Path(child).exists())

    def test_local_translation_hook_does_not_override_transformers_or_other_sizes(self):
        self.assertFalse(native_models.configure_local_models(SimpleNamespace(nllb_backend="transformers", nllb_size="600M")))
        self.assertFalse(native_models.configure_local_models(SimpleNamespace(nllb_backend="ctranslate2", nllb_size="1.3B")))

    def test_windows_marks_mlx_and_vllm_unavailable(self):
        with patch.object(model_manager.platform, "system", return_value="Windows"):
            items = {row["name"]: row for row in model_manager.backend_availability()}
        self.assertTrue(any("unavailable" in message.lower() for message in items["mlx"]["warnings"]))
        self.assertTrue(any("not supported" in message.lower() for message in items["vllm"]["warnings"]))

    def test_huggingface_cache_scan_uses_project_owned_cache(self):
        with patch("huggingface_hub.scan_cache_dir", return_value=SimpleNamespace(repos=[])) as scan:
            self.assertEqual(model_manager._hub_repos(), {})
        scan.assert_called_once_with(cache_dir=model_manager.HUB_CACHE)

    def test_installed_native_whisper_small_is_returned_without_download(self):
        path = model_manager.download_model("native-whisper-small")
        self.assertEqual(path, model_manager.MODEL_ROOT / "native-whisper" / "small.pt")


if __name__ == "__main__":
    unittest.main()
