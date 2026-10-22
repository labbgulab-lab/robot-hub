"""Voice detection on every listening robot's mic, also while a robot talks.

Until 2026-10-21 every mic was closed while a robot spoke, so a person who
started mid-line lost the start of their sentence, and nobody could be heard
over a robot at all. Tomer wants both: in the group mode people talk whenever
they like, and in the interrupt mode the robots talk *over* the person, who
keeps going.

The robots' mics hear the robot that is talking, so "is that a voice?" is not
enough while one plays. What we do know is exactly what each robot plays and
roughly when (the conductor registers every chunk here with `add_reference`).
So, per mic and per speaking robot, Ears learns how loud that robot arrives at
that mic (the *coupling*: mic level / played level, a high percentile over its
lines). While a robot plays, a block counts as a person only when it is a
voice (Silero) AND louder than the robot's predicted echo at that mic by
`barge_db`. With five robots scattered on a table there is always a mic far
from the speaker and close to the person, and that is the one that hears them.

Until a pair has been learned (its first ~2 s of that robot's speech) its
coupling is a deliberately high guess, so an unlearned mic cannot cut a robot
by mistake; it only becomes sensitive once it knows the echo.

`feed` runs on the robot links' reader threads (one per robot): everything
shared sits behind one lock; each robot's VAD is only touched by its own thread.
"""

from __future__ import annotations

import collections
import logging
import math
import threading
import time
from typing import Optional

import numpy as np

log = logging.getLogger("hub.group.ears")

BLOCK = 512
BLOCK_S = BLOCK / 16000
SPEECH_P = 0.5          # Silero probability that counts as a voice
KEEP_P = 0.35           # lower bar for "still talking" once they have the floor
START_FRAMES = 3        # ~96 ms of voice before the people get the floor (room quiet)
DUPLEX_START_FRAMES = 5 # ~160 ms over a talking robot: echo bursts are short
PREROLL = 10            # blocks (~320 ms) kept from before the voice started
END_SILENCE_S = 0.8     # silence that ends the people's turn
MAX_PEOPLE_S = 30.0

# The echo model. A chunk is heard at the mics around its play time, give or
# take the SSH and speaker latency on the way out and the mic stream on the
# way back, so the reference at time t is the loudest played block in
# [t - REF_BEFORE_S, t + REF_AFTER_S].
REF_BEFORE_S = 0.9
REF_AFTER_S = 0.25
REF_KEEP_S = 30.0
REF_ACTIVE = 0.004      # played rms below this is silence
COUPLING_GUESS = 1.5    # mic rms / played rms before a pair is learned (no barge-in)
COUPLING_MIN_SAMPLES = 30
COUPLING_WINDOW = 400   # samples kept per pair (~13 s of that robot's speech)
COUPLING_PCTL = 85
NOISE_FLOOR = 0.002     # mic rms that is never a voice on its own


def rms_blocks(pcm: bytes) -> list[float]:
    """int16 mono -> rms (0..1) per 512-sample block."""
    x = np.frombuffer(pcm[: len(pcm) - len(pcm) % 2], dtype="<i2").astype(np.float32) / 32768.0
    out = []
    for i in range(0, x.size, BLOCK):
        part = x[i:i + BLOCK]
        if part.size:
            out.append(float(np.sqrt(np.mean(part * part))))
    return out


def level_of(rms: float) -> float:
    """The page's meter scale: 0 = -60 dBFS, 1 = 0 dBFS."""
    return min(1.0, max(0.0, (20 * math.log10(rms + 1e-9) + 60) / 60))


class Ears:
    def __init__(self, keys: list[str], min_level: float = 0.0, barge_db: float = 10.0,
                 vad_factory=None) -> None:
        if vad_factory is None:
            from .vad import SileroVAD
            vad_factory = SileroVAD
        self.min_level = min_level
        # None = mics closed while a robot plays (the 2026-10-19 behaviour).
        self.barge_db: Optional[float] = barge_db
        self._lock = threading.Lock()
        self._keys = list(keys)
        self._vad = {k: vad_factory() for k in keys}
        self._ring = {k: collections.deque(maxlen=PREROLL) for k in keys}
        self._run = {k: 0 for k in keys}
        self._open = False
        self._buf: dict[str, list[np.ndarray]] = {}
        self._energy: dict[str, float] = {}
        # speaker key -> deque[(t, rms)] of what it played, by play time
        self._ref: dict[str, collections.deque] = {}
        self._coupling: dict[tuple[str, str], collections.deque] = {}
        self._coupling_cache: dict[tuple[str, str], float] = {}
        self.priors: dict[str, float] = {}          # "mic|speaker" -> coupling, saved
        self.levels = {k: 0.0 for k in keys}
        self.excess = {k: -99.0 for k in keys}      # last block, dB over the echo
        # voice-like blocks over a robot, dB over its echo: the 98th
        # percentile is the "echo check" (a person's first frames before a
        # barge-in are too few to move it)
        self.line_peak: dict[str, collections.deque] = {}
        self.capturing = False
        self.during_robot = False                  # this capture began over a robot
        self.started_at = 0.0
        self.last_voice = 0.0
        self.stirred = 0.0
        self.voiced_s = 0.0                        # seconds of voice in this capture
        # The mics that count (None = all). The people's own mic and the
        # robots' mics, kept ready behind it, are all keys here; only the
        # active ones are heard (set_active switches at once, 2026-10-22).
        self.active: Optional[set] = None

    def set_active(self, keys: list[str]) -> None:
        """Hear only these mics from now on; whatever was being captured is
        dropped (it came from the mic being left)."""
        with self._lock:
            self.active = {k for k in keys if k in self._vad}
            self.capturing = False
            self.during_robot = False
            self._buf, self._energy = {}, {}
            for k in self._keys:
                self._run[k] = 0
                self._ring[k].clear()

    # ------------------------------------------------------------ control
    def set_open(self, flag: bool) -> None:
        with self._lock:
            if flag and not self._open:
                for k in self._keys:
                    self._ring[k].clear()
                    self._run[k] = 0
            self._open = flag

    @property
    def is_open(self) -> bool:
        return self._open

    def add_reference(self, speaker: str, start: float, rms: list[float]) -> None:
        """`speaker` plays blocks of these levels from monotonic time `start`."""
        with self._lock:
            dq = self._ref.setdefault(speaker, collections.deque())
            t = start
            for r in rms:
                dq.append((t, r))
                t += BLOCK_S
            cutoff = time.monotonic() - REF_KEEP_S
            while dq and dq[0][0] < cutoff:
                dq.popleft()

    def drop_reference(self, speaker: str, after: float) -> None:
        """A cut line: nothing it queued after `after` will play."""
        with self._lock:
            dq = self._ref.get(speaker)
            if dq:
                self._ref[speaker] = collections.deque((t, r) for t, r in dq if t <= after)

    def robot_playing(self, now: Optional[float] = None, margin: float = 0.0) -> bool:
        now = time.monotonic() if now is None else now
        with self._lock:
            return any(dq and dq[-1][0] + BLOCK_S + margin > now for dq in self._ref.values())

    def coupling(self, mic: str, speaker: str) -> float:
        """Learned, else the loudest robot this mic has learned (a robot is
        never louder at a mic than the loudest one measured there, which is
        usually the mic's own robot), else the saved value from an earlier
        session, else a guess too high to cut anyone. The 2026-10-21 dry run
        showed why the middle steps matter: with only the guess, a person
        talking over a robot that had not spoken yet was not heard at all."""
        got = self._coupling_cache.get((mic, speaker))
        if got is not None:
            return got
        if mic == speaker:
            # A robot's own mic hears it far louder than any other robot
            # (dry run: -9 dB against -16 for the nearest neighbour); nothing
            # borrowed fits, so it stays deaf for the second it takes to learn.
            prior = self.priors.get("{}|{}".format(mic, speaker))
            return prior * 1.4 if prior is not None else COUPLING_GUESS
        known = [c for (m, s), c in self._coupling_cache.items() if m == mic and s != mic]
        if known:
            return max(known) * 2.0
        prior = self.priors.get("{}|{}".format(mic, speaker))
        if prior is not None:
            return prior * 1.4
        return COUPLING_GUESS

    def couplings(self) -> dict[str, float]:
        """The learned pairs, to be saved for the next session."""
        return {"{}|{}".format(m, s): round(c, 5) for (m, s), c in self._coupling_cache.items()}

    # ---------------------------------------------------------- per block
    def _refs_at(self, now: float) -> dict[str, float]:
        lo, hi = now - REF_BEFORE_S, now + REF_AFTER_S
        out = {}
        for spk, dq in self._ref.items():
            if not dq or dq[-1][0] < lo:
                continue
            best = 0.0
            for t, r in reversed(dq):
                if t < lo:
                    break
                if t <= hi and r > best:
                    best = r
            if best >= REF_ACTIVE:
                out[spk] = best
        return out

    def _learn(self, mic: str, spk: str, ratio: float) -> None:
        dq = self._coupling.setdefault((mic, spk), collections.deque(maxlen=COUPLING_WINDOW))
        dq.append(ratio)
        if len(dq) >= COUPLING_MIN_SAMPLES and len(dq) % 10 == 0:
            self._coupling_cache[(mic, spk)] = float(np.percentile(np.array(dq), COUPLING_PCTL))

    def feed(self, key: str, block: np.ndarray) -> None:
        if key not in self._vad or block.size != BLOCK:
            return
        rms = float(np.sqrt(np.mean(np.square(block.astype(np.float32))))) / 32768.0
        level = level_of(rms)
        self.levels[key] = max(level, self.levels.get(key, 0.0))   # shown even when not heard
        active = self.active
        if active is not None and key not in active:
            return
        now = time.monotonic()
        with self._lock:
            refs = self._refs_at(now)
            is_open = self._open
            capturing = self.capturing
        if not is_open:
            return
        if refs and self.barge_db is None:
            # Mics closed while a robot plays; the VAD state starts over after.
            self._vad[key].reset()
            with self._lock:
                self._run[key] = 0
                self._ring[key].clear()
            return
        p = self._vad[key].prob(block)
        loud = level >= self.min_level and rms >= NOISE_FLOOR
        if refs:
            echo = sum(self.coupling(key, s) * r for s, r in refs.items())
            excess = 20 * math.log10((rms + 1e-9) / (echo + NOISE_FLOOR))
            # Learn only from blocks that are the robot alone: one speaker, no
            # person on the floor, and not far over what is already known.
            if len(refs) == 1 and not capturing:
                (spk, r), = refs.items()
                ratio = rms / max(r, 1e-6)
                known = self._coupling_cache.get((key, spk))
                if known is None or ratio < known * 4:
                    self._learn(key, spk, ratio)
            need = self.barge_db or 0.0
            voiced = p >= SPEECH_P and loud and excess >= need
            keep = p >= KEEP_P and excess >= need - 4
            self.excess[key] = excess
            if not capturing and p >= SPEECH_P and len(refs) == 1:
                self.line_peak.setdefault(key, collections.deque(maxlen=3000)).append(excess)
            start_frames = DUPLEX_START_FRAMES
        else:
            voiced = p >= SPEECH_P and loud
            keep = p >= KEEP_P
            self.excess[key] = 99.0 if voiced else -99.0
            start_frames = START_FRAMES
        with self._lock:
            if not self._open:
                return
            if keep and loud:
                self.stirred = now
            self._run[key] = self._run[key] + 1 if voiced else 0
            if self.capturing:
                # A block that is only a robot is kept as silence: what the
                # robots say must not end up in the person's transcript
                # (2026-10-21 dry run: a robot's reply leaked into it).
                self._buf.setdefault(key, []).append(
                    block if (keep or not refs) else np.zeros_like(block))
                if keep:
                    if now - self.last_voice > 0.5:
                        log.debug("voice again at %s after %.1f s (p %.2f, %s)", key[-8:],
                                  now - self.last_voice, p, "robot" if refs else "quiet")
                    self.last_voice = now
                    self._energy[key] = self._energy.get(key, 0.0) + rms * rms
                    self.voiced_s += BLOCK_S / max(1, len(self._vad) if self.active is None
                                                   else len(self.active))
                return
            self._ring[key].append(block)
            if self._run[key] >= start_frames:
                log.info("voice at %s (level %.2f, p %.2f, %s)", key[-8:], level, p,
                         "over a robot" if refs else "room quiet")
                self.capturing = True
                self.during_robot = bool(refs)
                self.started_at = self.last_voice = now
                self.voiced_s = start_frames * BLOCK_S
                heard = [k for k in self._vad if self.active is None or k in self.active]
                self._buf = {k: list(self._ring[k]) for k in heard}
                self._energy = {k: 0.0 for k in heard}
                self._energy[key] = rms * rms * start_frames

    # ------------------------------------------------------------ reading
    def finished(self, end_silence: float = END_SILENCE_S) -> bool:
        now = time.monotonic()
        with self._lock:
            return self.capturing and (now - self.last_voice >= end_silence
                                       or now - self.started_at >= MAX_PEOPLE_S)

    def stirring(self) -> bool:
        return time.monotonic() - self.stirred < 0.25

    def silence(self) -> float:
        with self._lock:
            return time.monotonic() - self.last_voice if self.capturing else 0.0

    def best_key(self) -> Optional[str]:
        with self._lock:
            return max(self._energy, key=self._energy.get) if self._energy else None

    def blocks_of(self, key: str) -> list[np.ndarray]:
        with self._lock:
            return list(self._buf.get(key, []))

    def take(self, keep: bool = False) -> tuple[bytes, Optional[str], float, float]:
        """(pcm of the mic that heard them best, its key, seconds of voice,
        monotonic time the voice ended); resets for the next turn unless `keep`."""
        with self._lock:
            if not self.capturing:
                return b"", None, 0.0, time.monotonic()
            key = max(self._energy, key=self._energy.get) if self._energy else None
            blocks = list(self._buf.get(key, [])) if key else []
            tail = int(max(0.0, time.monotonic() - self.last_voice - 0.25) / BLOCK_S)
            if 0 < tail < len(blocks):
                blocks = blocks[:-tail]
            spoken = self.last_voice - self.started_at
            ended = self.last_voice
            if not keep:
                self.capturing = False
                self.during_robot = False
                self._buf, self._energy = {}, {}
                for k in self._keys:
                    self._run[k] = 0
                    self._ring[k].clear()
        return b"".join(b.astype(np.int16).tobytes() for b in blocks), key, spoken, ended

    def reset_capture(self) -> None:
        self.take()

    def decay(self) -> dict[str, float]:
        out = dict(self.levels)
        for k in self.levels:
            self.levels[k] *= 0.6
        return out

    def echo_report(self) -> dict[str, dict]:
        """Per mic: learned couplings and the loudest voice-over-echo margin
        seen while robots talked with no person on the floor (dB). A margin
        near barge_db means robots could cut themselves off."""
        with self._lock:
            out = {}
            for k in self._keys:
                pairs = {s: round(20 * math.log10(c + 1e-9), 1)
                         for (m, s), c in self._coupling_cache.items() if m == k}
                vals = self.line_peak.get(k)
                peak = float(np.percentile(np.array(vals), 98)) if vals and len(vals) >= 50 else -99.0
                out[k] = {"coupling_db": pairs, "peak_excess_db": round(peak, 1)}
            return out
