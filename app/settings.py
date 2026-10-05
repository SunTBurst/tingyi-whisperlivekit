"""Settings and files stay beside the local application."""
import json
import os
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'
DEFAULTS = {
    'appearance_theme':'dark',
    'source_mode':'system', 'source_language':'en', 'target_language':'zh',
    'asr_model':'medium', 'translation_mode':'local',
    'output_device':None, 'mic_device':None, 'font_size':24,
    'opacity':0.96, 'always_on_top':True, 'save_records':True,
    'wlk':{}, 'context':'', 'server_url':'', 'allow_downloads':False,
    'speaker_names':{}, 'separate_sources':True,
    'mic_language':'zh', 'mic_target_language':'en', 'stream_mode':'full',
    'long_meeting_mode':True, 'glossary_enabled':False, 'glossary_rules':[],
    'translation_provider':'nllb', 'llm_url':'http://127.0.0.1:1234/v1',
    'llm_model':'', 'llm_api_token':None, 'llm_timeout':60,
    'llm_context_chars':12000, 'llm_fallback':False,
    'show_original_text':False,
    'overlay_width':680, 'overlay_height':300, 'overlay_x':None, 'overlay_y':None,
    'overlay_follow_theme':True,
    'overlay_background_color':'#20242b', 'overlay_background_opacity':88,
    'overlay_font_family':'Microsoft YaHei UI', 'overlay_font_size':30,
    'overlay_source_color':'#ffffff', 'overlay_translation_color':'#91d9e6',
    'overlay_display_mode':'bilingual', 'overlay_show_speaker':True,
    'overlay_show_draft':True, 'overlay_locked':False, 'overlay_always_on_top':True,
}


def redact_settings(settings):
    secret_keys={'api_token','api_key','llm_api_token','password','_management_token'}
    if isinstance(settings,dict):
        return {key:(None if key in secret_keys else redact_settings(value)) for key,value in settings.items()}
    if isinstance(settings,list): return [redact_settings(value) for value in settings]
    return settings


def load_settings():
    values = deepcopy(DEFAULTS)
    path = DATA / 'settings.json'
    if path.exists():
        try:
            saved = json.loads(path.read_text(encoding='utf-8'))
            values.update({k:v for k,v in saved.items() if k in values})
            # Migrate the old whole-window appearance to the independent subtitle.
            if 'overlay_background_opacity' not in saved:
                values['overlay_background_opacity']=round(float(saved.get('opacity',0.88))*100)
            if 'overlay_always_on_top' not in saved:
                values['overlay_always_on_top']=bool(saved.get('always_on_top',True))
        except (ValueError, TypeError, OSError, AttributeError):
            pass
    return values


def save_settings(values):
    DATA.mkdir(parents=True, exist_ok=True)
    path = DATA / 'settings.json'
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps({k:values.get(k,v) for k,v in DEFAULTS.items()}, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temporary, path)
