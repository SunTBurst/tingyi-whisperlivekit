import asyncio
from unittest.mock import patch

import numpy as np

from app.session import SessionControl, run_session
from app.settings import DEFAULTS


async def _capture(settings, emit, control, audio_file=None, realtime=True, **kwargs):
    source = settings.get('source_mode', 'main')
    emit({'type': 'level', 'value': 0.25 if source == 'system' else 0.75})
    yield np.full(1600, 0.1 if source == 'system' else 0.2, dtype=np.float32)
    control.request('stop')


async def _native(base, chunks, language, target, on_snapshot, **kwargs):
    samples = []
    if kwargs.get('on_connected'):
        kwargs['on_connected']()
    async for chunk in chunks:
        samples.append(float(chunk[0]))
    if samples:
        source_text = 'system words' if samples[0] < 0.15 else 'mic words'
        on_snapshot({'lines': [{'text': source_text, 'start': 0, 'end': 0.1,
                                'speaker': 1, 'tokens': [{'text': source_text,
                                                          'start': 0, 'end': 0.1}]}],
                     'buffer_transcription': source_text + ' draft'})


def test_dual_source_events_keep_levels_rows_and_pipeline_snapshots_separate():
    events = []
    settings = {**DEFAULTS, 'source_mode': 'both', 'separate_sources': True,
                'server_url': 'http://fake', 'translation_mode': 'off',
                'save_records': False}
    with patch('app.session.capture_chunks', _capture), \
         patch('app.native_client.stream_native', _native):
        asyncio.run(run_session(settings, events.append, SessionControl()))

    levels = [event for event in events if event.get('type') == 'level' and event.get('value')]
    assert {event.get('source') for event in levels} == {'system', 'mic'}
    applied = [event for event in events if event.get('type') == 'settings_applied']
    assert {event.get('source') for event in applied} == {'system', 'mic'}

    pipeline_updates = [event for event in events if event.get('type') == 'pipeline']
    assert {event.get('source') for event in pipeline_updates} == {'system', 'mic'}
    assert pipeline_updates[-1]['pipelines'].keys() >= {'system', 'mic'}
    assert pipeline_updates[-1]['pipeline_source'] == pipeline_updates[-1]['source']
    assert pipeline_updates[-1]['pipelines']['system']['buffer_transcription'] == 'system words draft'
    assert pipeline_updates[-1]['pipelines']['mic']['buffer_transcription'] == 'mic words draft'

    caption_events = [event for event in events if event.get('type') == 'captions' and event.get('delta')]
    rows = [row for event in caption_events for row in event['rows']]
    assert {row['audio_source'] for row in rows} == {'system', 'mic'}
    for event in caption_events:
        row_sources = {row['audio_source'] for row in event['rows']}
        if len(row_sources) == 1:
            source = next(iter(row_sources))
            assert event['source'] == source
            assert event['pipeline_source'] == source
            assert event['pipeline'] == event['pipelines'][source]
    assert all(row['native']['tokens'][0]['text'] == row['source_original'] for row in rows)
    assert all(row['native_local']['tokens'][0]['start'] == 0 for row in rows)


def test_file_input_is_tagged_main_without_claiming_system_source():
    events = []
    settings = {**DEFAULTS, 'source_mode': 'system', 'server_url': 'http://fake',
                'translation_mode': 'off', 'save_records': False}
    with patch('app.session.capture_chunks', _capture), \
         patch('app.native_client.stream_native', _native):
        asyncio.run(run_session(settings, events.append, SessionControl(), audio_file='meeting.wav'))

    levels = [event for event in events if event.get('type') == 'level' and event.get('value')]
    assert levels and all(event.get('source') == 'main' for event in levels)
    caption_events = [event for event in events if event.get('type') == 'captions' and event.get('delta')]
    rows = [row for event in caption_events for row in event['rows']]
    assert rows and {row['audio_source'] for row in rows} == {'main'}
    assert all(event.get('source') == 'main' for event in caption_events if event.get('rows'))
    pipeline_updates = [event for event in events if event.get('type') == 'pipeline']
    assert pipeline_updates and all(event.get('source') == 'main' for event in pipeline_updates)

