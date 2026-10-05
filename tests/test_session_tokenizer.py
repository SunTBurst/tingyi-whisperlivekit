from types import SimpleNamespace
from unittest.mock import patch


def test_simul_session_keeps_its_language_tokenizer_instead_of_shared_source_language():
    from app.native_asr import configure_session_tokenizers
    from whisperlivekit.simul_whisper.backend import SimulStreamingOnlineProcessor
    configure_session_tokenizers()
    decoder=SimpleNamespace(tokenizer='zh-session',state=SimpleNamespace(tokenizer='zh-session'))
    asr=SimpleNamespace(tokenizer='en-shared',_session_cfg=SimpleNamespace(language='zh'))
    with patch.object(SimulStreamingOnlineProcessor,'_create_alignatt',return_value=decoder):
        processor=SimulStreamingOnlineProcessor(asr)
    assert processor.model.tokenizer=='zh-session'
    assert processor.model.state.tokenizer=='zh-session'
