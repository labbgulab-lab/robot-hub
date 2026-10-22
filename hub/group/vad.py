"""Silero VAD (onnxruntime) for the robots' mic streams.

A compact copy of reachy_chat's vad_onnx.py: same model contract (64 samples
of the previous frame prepended, LSTM state carried, 512-sample frames at
16 kHz). One instance per robot mic, because the state belongs to one stream.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from ..config import REPO_ROOT

MODEL = REPO_ROOT / "assets" / "silero_vad.onnx"
FRAME = 512
_CONTEXT = 64


class SileroVAD:
    def __init__(self, model: Path = MODEL) -> None:
        import onnxruntime

        opts = onnxruntime.SessionOptions()
        # Five of these run side by side; a thread pool each would only fight.
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        opts.log_severity_level = 3
        self.session = onnxruntime.InferenceSession(
            str(model), providers=["CPUExecutionProvider"], sess_options=opts)
        self._sr = np.array(16000, dtype=np.int64)
        self.reset()
        self.prob(np.zeros(FRAME, dtype=np.int16))   # warm-up off the hot path
        self.reset()

    def reset(self) -> None:
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._context = np.zeros(_CONTEXT, dtype=np.float32)

    def prob(self, block: np.ndarray) -> float:
        """Speech probability of one 512-sample int16 block."""
        x = np.concatenate([self._context, block.astype(np.float32) / 32768.0])
        out, self._state = self.session.run(
            None, {"input": x.reshape(1, -1), "state": self._state, "sr": self._sr})
        self._context = x[-_CONTEXT:]
        return float(out.item())
