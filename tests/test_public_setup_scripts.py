from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(name):
    return (ROOT / name).read_text(encoding="utf-8")


def test_setup_pins_upstream_and_targets_managed_python():
    setup = read("Setup.ps1")
    assert "363e4f6d029694d9c81ae548beddd9d3c88a3637" in setup
    assert "uv.Source python install 3.12" in setup
    assert "uv.Source venv --python 3.12" in setup
    assert "requirements-public.txt" in setup
    assert "-e \"$upstreamPath[cpu]\"" in setup


def test_start_has_no_model_weight_precondition():
    start = read("Start.ps1")
    assert "upstream\\whisperlivekit\\__init__.py" in start
    assert "models\\whisper-medium\\model.bin" not in start
    assert "download_nllb.py" not in start


def test_repair_does_not_download_model_weights():
    repair = read("Repair.ps1")
    assert "Setup.ps1" in repair
    assert "download_nllb.py" not in repair
    assert "model.bin" not in repair


def test_nllb_requires_clear_noncommercial_acknowledgement():
    downloader = read("Download-NLLB.ps1")
    assert "CC-BY-NC-4.0" in downloader
    assert "$AcceptNonCommercialLicense" in downloader
    assert "ACCEPT-NONCOMMERCIAL" in downloader
    assert "scripts\\download_nllb.py" in downloader


def test_public_requirements_are_separate_from_cuda_snapshot():
    requirements = read("requirements-public.txt").lower()
    assert "pyqt6==6.11.0" in requirements
    assert "pyaudiowpatch==0.2.12.8" in requirements
    assert "torch==" not in requirements
    assert "+cu126" not in requirements


def test_install_guide_states_scope_and_weight_license():
    guide = read("docs/INSTALL.md")
    assert "363e4f6d029694d9c81ae548beddd9d3c88a3637" in guide
    assert "Windows" in guide and "CPU" in guide
    assert "CC-BY-NC-4.0" in guide
    assert "Download-NLLB.ps1" in guide
    assert "Repair.ps1" in guide
