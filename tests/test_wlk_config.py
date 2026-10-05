from dataclasses import fields

import pytest

from app.settings import DEFAULTS
from app.wlk_config import config_values, field_schema, make_config
from whisperlivekit.config import WhisperLiveKitConfig


def test_every_upstream_field_has_a_desktop_entry():
    assert {f.name for f in fields(WhisperLiveKitConfig)} == {f['name'] for f in field_schema()}


def test_advanced_parameters_reach_native_dataclass_without_filtering():
    settings = {**DEFAULTS, 'wlk': {'diarization': True, 'sortformer_max_speakers': 3,
                'lora_path': 'adapter.pt', 'retention_seconds': 920., 'frame_threshold': 14}}
    config = make_config(settings)
    assert config.diarization and config.sortformer_max_speakers == 3
    assert config.lora_path == 'adapter.pt' and config.retention_seconds == 920.
    assert config.frame_threshold == 14 and config.pcm_input


def test_existing_local_model_is_resolved_but_custom_path_survives():
    values = config_values(DEFAULTS)
    assert values['model_dir'].endswith('whisper-medium')
    assert config_values({**DEFAULTS, 'wlk': {'model_dir': 'X:/custom'}})['model_dir'] == 'X:/custom'


def test_unknown_settings_fail_loudly_instead_of_silently_discarding():
    with pytest.raises(ValueError, match='不存在'):
        make_config({**DEFAULTS, 'wlk': {'misspelled_option': 1}})


def test_auto_native_translation_limitation_is_explained():
    with pytest.raises(ValueError, match='自动识别'):
        make_config({**DEFAULTS, 'source_language': 'auto'})
