"""An optional Triton import must not corrupt a native streaming session."""
import sys
import types
import warnings
from unittest.mock import patch

import torch

from app.native_asr import configure_median_fallback


def test_native_median_uses_unchanged_torch_fallback_for_missing_symbol():
    from whisperlivekit.whisper import timing
    values=torch.tensor([[[[1.,4.,2.,9.,3.,8.,2.,7.,6.]]]])
    expected=timing.median_filter(values,7)
    configure_median_fallback()
    # CPython can expose a failed concurrent optional-module import without its
    # symbols. The numerical fallback must behave exactly as it does on CPU.
    missing=types.ModuleType('whisperlivekit.whisper.triton_ops')
    with patch.dict(sys.modules,{'whisperlivekit.whisper.triton_ops':missing}), \
         patch.object(torch.Tensor,'is_cuda',new=property(lambda self:True)), \
         warnings.catch_warnings():
        warnings.simplefilter('ignore')
        actual=timing.median_filter(values,7)
    assert torch.equal(actual,expected)
