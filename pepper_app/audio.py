"""Pepper's voice out, and the person's voice in -- always through Pepper.

Pepper's front microphone and loudspeakers, through the agent on the robot.
There is deliberately no laptop microphone or speaker route (Tomer,
2026-10-07): the people in the demo talk to Pepper, not to a laptop.

Everything is PCM16 mono at 24 kHz, the rate both engines use. Pepper's mic
arrives at 16 kHz and is resampled here.

The mic is half-duplex: while Pepper is speaking (and for a short tail after)
the person's audio is not passed on, or the model would hear Pepper and
answer itself. Barge-in is given up for that, as on Reachy.
"""

from __future__ import annotations

import logging
import time
import warnings
from typing import Callable, Optional

log = logging.getLogger("pepper.audio")

RATE = 24000
TAIL_S = 0.5          # mic stays shut this long after Pepper stops

with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    try:
        import audioop  # deprecated in 3.11, gone in 3.13; the hub runs 3.12
    except ImportError:  # pragma: no cover
        audioop = None


class Resampler:
    """16 kHz -> 24 kHz, continuous across chunks."""

    def __init__(self, src: int, dst: int) -> None:
        self.src, self.dst, self.state = src, dst, None

    def __call__(self, pcm: bytes) -> bytes:
        if self.src == self.dst:
            return pcm
        if audioop is not None:
            out, self.state = audioop.ratecv(pcm, 2, 1, self.src, self.dst, self.state)
            return out
        import array
        a = array.array("h", pcm)
        n = len(a) * self.dst // self.src
        if not a:
            return b""
        out = array.array("h", (a[min(int(i * self.src / self.dst), len(a) - 1)] for i in range(n)))
        return out.tobytes()


def peak(pcm: bytes) -> int:
    if audioop is not None and pcm:
        return audioop.max(pcm, 2)
    return 0


class AudioRouter:
    """Pepper's speaker and mic: the mic gate, and who is listening."""

    def __init__(self, robot) -> None:
        self.robot = robot
        self.listener: Optional[Callable[[bytes], None]] = None   # the brain's ears
        self.mic_on = False
        self._quiet_until = 0.0
        self._up16 = Resampler(16000, RATE)
        self.mic_level = 0
        robot.on_mic = self._from_pepper

    def play(self, pcm24: bytes) -> None:
        self.robot.send_audio(pcm24)
        self._quiet_until = time.monotonic() + len(pcm24) / (RATE * 2) + TAIL_S

    def flush(self) -> None:
        self._quiet_until = time.monotonic() + TAIL_S

    @property
    def speaking(self) -> bool:
        return self.robot.playing or time.monotonic() < self._quiet_until

    async def set_mic(self, on: bool) -> None:
        """Pepper's mic is only streamed while this is on, to keep the hotspot free."""
        self.mic_on = on
        if self.robot.connected:
            try:
                await self.robot.call("mic", on=on)
            except Exception as exc:  # noqa: BLE001
                log.warning("Pepper microphone: %s", exc)

    def _from_pepper(self, pcm16k: bytes) -> None:
        pcm24 = self._up16(pcm16k)
        self.mic_level = peak(pcm24)
        if self.mic_on and self.listener is not None and not self.speaking:
            self.listener(pcm24)
