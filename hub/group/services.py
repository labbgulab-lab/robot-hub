"""The three cloud calls of a group conversation: director, ears, voice.

Measured from the lab laptop on 2026-10-19 (Hebrew):
  director  gpt-5.4-mini, reasoning off, JSON      ~1.4-2.0 s
  STT       gpt-transcribe                          ~1.6 s for 5 s of speech
  voice     ElevenLabs eleven_v4_turbo, HTTP stream  first audio ~0.6 s,
            4.7 s of speech complete in ~1.0 s
The ElevenLabs text-to-dialogue *WebSocket* reachy_chat uses was slower than
real time from here (first audio 4.7-6.4 s), so this uses the plain
text-to-speech stream endpoint instead.

One httpx client for the whole session: keep-alive saves a TLS handshake on
every line.
"""

from __future__ import annotations

import asyncio
import io
import time
import json
import logging
import re
import wave
from typing import Any, AsyncIterator, Optional

import httpx

log = logging.getLogger("hub.group.services")

OPENAI = "https://api.openai.com/v1"
ELEVEN = "https://api.elevenlabs.io"
# The writer, through OpenRouter (2026-10-21, Tomer's demo key). Benchmarked
# that morning on the real group prompt in Hebrew, median of 5:
#   google/gemini-3.5-flash     2.5 s  $0.0036/line  most natural, funniest Hebrew
#   openai/gpt-oss-120b         1.0-1.7 s (Cerebras)  $0.0006  fastest, odd Hebrew
#   openai/gpt-5.4-mini         2.3-3.2 s  $0.0012  good
#   gemini-3.5-flash-lite       1.6 s direct / 2.4 s OpenRouter  sometimes garbled
#   claude-haiku-5.5            5 s;  deepseek-v4.1-flash 8-16 s;  grok-4.3 11 s
# A slow answer is raced by the fast model after HEDGE_DIRECTOR_S (conductor).
DIRECTOR_MODEL = "google/gemini-3.5-flash"
FAST_MODEL = "openai/gpt-oss-120b"
OPENROUTER = "https://openrouter.ai/api/v1"
# OpenRouter's voice: verbatim Hebrew and English, first audio ~1.4 s.
OR_TTS_MODEL = "openai/gpt-audio-mini"
OR_STT_MODEL = "google/gemini-3.5-flash-lite"   # gpt-audio-mini / voxtral translate Hebrew
# Measured from home 2026-10-21, a short JSON reply: gpt-4.1-mini 0.92 s
# steady, gpt-5.4-mini 0.8-2.8 s, gpt-5.4-nano 1.3-1.8 s. The page can switch.
DIRECTOR_MODELS = ("google/gemini-3.5-flash", "openai/gpt-oss-120b", "openai/gpt-5.4-mini",
                   "gpt-4.1-mini", "gpt-5.4-mini", "gemini-3.5-flash-lite")
# Gemini, the fallback when OpenAI refuses (on 2026-10-21 the lab key ran out
# of credits mid-test). Measured from home that night: director 0.8-1.0 s,
# transcription 1.5 s, voice first audio 0.9 s (streaming).
GEMINI = "https://generativelanguage.googleapis.com/v1beta/models/"
GEMINI_DIRECTOR = "gemini-3.5-flash-lite"
GEMINI_STT = "gemini-3.5-flash-lite"
GEMINI_TTS = "gemini-3.8-flash-lite-tts"
# Gemini's voice models each have their own DAILY cap per key (2026-10-21:
# 100 a day on the lab key, 10 on the free one; it resets at midnight
# Pacific = 10:00 in Israel), so a session walks through all of them.
# First audio measured that night: 3.1 0.86 s, 3.8-lite 0.91 s, 3.8 1.14 s,
# 2.5 5.5 s (last resort).
GEMINI_TTS_MODELS = ("gemini-3.1-flash-tts-preview", "gemini-3.8-flash-lite-tts",
                     "gemini-3.8-flash-tts", "gemini-2.5-flash-preview-tts")
DIRECTOR_TIMEOUT_S = 8.0
STT_MODEL = "gpt-transcribe"
HEARING_MODEL = "gpt-audio-mini"
OPENAI_TTS_MODEL = "gpt-4o-mini-tts"
TTS_MODEL = "eleven_v4_turbo"
# Requests ElevenLabs runs at once: Starter 3, Creator 5 (the plan, not the
# credits; topping up does not raise it).
ELEVEN_SLOTS = 3
# A "too many concurrent requests" refusal is waited out this many times.
ELEVEN_BUSY_WAITS = (0.3, 0.6, 1.0)


class ServiceError(RuntimeError):
    def __init__(self, message: str, status: int = 0, body: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.body = body


def spoken_in(language: str) -> str:
    """The language part of a transcription request. The 2026-10-21 runs,
    asked for "Hebrew or English", got mixed-language junk; a demo in one
    language says so (Tomer, 2026-10-22: the demo is English only)."""
    if language == "en":
        return "in English (the speaker speaks English)"
    if language == "he":
        return "in Hebrew (the speaker speaks Hebrew)"
    return "in the language it is spoken (Hebrew or English)"


def eleven_gone(exc: Exception) -> bool:
    """ElevenLabs refused for good (bad key, no credits, voice not allowed),
    not just for this request: only then do the robots leave it for the
    session. Until 2026-10-22 any refusal did, and one 429 for too many
    requests at once cost the 15:32 run its ElevenLabs voices after 5 s."""
    status = getattr(exc, "status", 0)
    body = getattr(exc, "body", "") or ""
    if status in (401, 402, 403):
        return True
    return status == 429 and "concurrent" not in body or "quota_exceeded" in body


def resample_24k_16k(data: bytes, carry: bytes) -> tuple[bytes, bytes]:
    """int16 24 kHz -> 16 kHz, in groups of 3 samples -> 2 (linear, fine for
    speech). Returns (16 kHz bytes, bytes to carry into the next call)."""
    import numpy as np
    data = carry + data
    usable = (len(data) // 6) * 6
    if not usable:
        return b"", data
    x = np.frombuffer(data[:usable], dtype=np.int16).astype(np.float32).reshape(-1, 3)
    y = np.empty((x.shape[0], 2), dtype=np.float32)
    y[:, 0] = x[:, 0]
    y[:, 1] = (x[:, 1] + x[:, 2]) / 2
    return y.reshape(-1).astype(np.int16).tobytes(), data[usable:]


def decode_to_16k(data: bytes) -> bytes:
    """A compressed clip (Ogg Opus, MP3) -> int16 16 kHz mono."""
    import numpy as np
    import soundfile as sf
    x, rate = sf.read(io.BytesIO(data), dtype="float32", always_2d=True)
    x = x.mean(axis=1)
    if rate != 16000 and x.size:
        n = int(round(x.size * 16000 / rate))
        x = np.interp(np.linspace(0, x.size - 1, n), np.arange(x.size), x)
    return (np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes()


class StreamDecoder:
    """A compressed clip (MP3) arriving in pieces -> int16 16 kHz mono, played
    as it comes. Until 2026-10-22 the whole MP3 was downloaded before the
    first sample left, so a line waited for ElevenLabs to finish all of it.

    Decoding a cut-off MP3 gives exactly the samples of the whole one up to
    the cut (checked with libsndfile 1.2.2), so each time another ~1 KB has
    arrived the bytes so far are decoded again (~1 ms) and what is new is
    sent, minus the last two frames, which may be incomplete."""

    MIN_NEW = 1200          # bytes between decodes (~0.3 s of 32 kbps speech)
    HOLD = 2 * 1152         # samples at the end that may still change

    def __init__(self) -> None:
        self.data = bytearray()
        self.decoded_at = 0
        self.out = 0            # 16 kHz samples sent so far

    def feed(self, chunk: bytes) -> bytes:
        self.data += chunk
        if len(self.data) - self.decoded_at < self.MIN_NEW:
            return b""
        return self._emit(final=False)

    def finish(self) -> bytes:
        return self._emit(final=True)

    def _emit(self, final: bool) -> bytes:
        import numpy as np
        import soundfile as sf
        self.decoded_at = len(self.data)
        if not self.data:
            return b""
        try:
            x, rate = sf.read(io.BytesIO(bytes(self.data)), dtype="float32", always_2d=True)
        except Exception:  # noqa: BLE001
            if final:
                raise
            return b""      # not one whole frame yet
        x = x.mean(axis=1)
        step = rate / 16000.0
        if final:
            last = int(x.size / step)
        else:
            last = int(max(0, x.size - self.HOLD - 1) / step)
        if last <= self.out:
            return b""
        pos = np.arange(self.out, last) * step
        self.out = last
        y = np.interp(pos, np.arange(x.size), x)
        return (np.clip(y, -1, 1) * 32767).astype(np.int16).tobytes()


class ElevenGate:
    """ElevenLabs takes 3 requests at a time on the lab's Starter plan; a
    fourth is refused with 429 (2026-10-21: the interjection warm-up ran twice
    beside the live lines and ElevenLabs was dropped for the whole session).
    Live lines take any free slot; background work (warming interjections)
    starts only when no live line is waiting or running, and always leaves
    one slot free for the next live line."""

    def __init__(self, slots: int = 3) -> None:
        self.slots = slots
        self.busy = 0
        self.live = 0           # live requests running or waiting
        self._waiters: list[asyncio.Future] = []

    def _free(self, background: bool) -> bool:
        if background:
            return self.live == 0 and self.busy < max(1, self.slots - 1)
        return self.busy < self.slots

    def _wake(self) -> None:
        waiters, self._waiters = self._waiters, []
        for f in waiters:
            if not f.done():
                f.set_result(None)

    async def acquire(self, background: bool) -> None:
        if not background:
            self.live += 1
        try:
            while not self._free(background):
                f = asyncio.get_running_loop().create_future()
                self._waiters.append(f)
                await f
        except BaseException:
            if not background:
                self.live -= 1
                self._wake()
            raise
        self.busy += 1

    def release(self, background: bool) -> None:
        """Synchronous, so it is safe in the `finally` of a cancelled stream."""
        self.busy -= 1
        if not background:
            self.live -= 1
        self._wake()


def chunked(pcm: bytes, size: int = 16000) -> list[bytes]:
    """Half-second pieces (16 kHz int16), so playback starts at once."""
    return [pcm[i:i + size] for i in range(0, len(pcm), size)]


# On the lab's phone hotspot (2026-10-21: ~30 KB/s down) raw voice audio
# (32-64 KB/s of speech) arrives slower than it plays: robots hung mid-line.
# Compressed, a 5 s line is ~5-20 KB. Only OpenAI (Opus) and ElevenLabs (MP3)
# offer it; OpenRouter's and Gemini's voices are raw only.
def wav_bytes(pcm: bytes, rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def compressed(pcm: bytes, rate: int = 16000) -> tuple[str, bytes, str]:
    """(filename, bytes, mime) for an upload: Ogg Opus, ~10x smaller than WAV.
    On the lab hotspot (~9 KB/s up) 6 s of speech went 178 KB / 19.9 s as WAV
    and 17 KB / 2.7 s as Opus, with the same transcript. WAV if encoding fails."""
    try:
        import numpy as np
        import soundfile as sf
        buf = io.BytesIO()
        sf.write(buf, np.frombuffer(pcm, dtype=np.int16), rate, format="OGG", subtype="OPUS")
        return "speech.ogg", buf.getvalue(), "audio/ogg"
    except Exception as exc:  # noqa: BLE001
        log.info("Opus encoding failed (%s); sending WAV", exc)
        return "speech.wav", wav_bytes(pcm, rate), "audio/wav"


class Services:
    def __init__(self, openai_key: str, eleven_key: str,
                 director_model: str = DIRECTOR_MODEL, gemini_key: Any = "",
                 openrouter_key: str = "") -> None:
        self.openai_key = openai_key
        self.eleven_key = eleven_key
        self.openrouter_key = openrouter_key
        self.compressed = True          # voices as Opus/MP3 (the "Slow network" switch)
        # Every Gemini key the hub has, in order; one that runs out of quota
        # is skipped (2026-10-21: the free "Lab Gemini" key hit its TTS quota
        # after 11 phrases, the lab account's key went on).
        keys = [gemini_key] if isinstance(gemini_key, str) else list(gemini_key or [])
        self.gemini_keys = [k for k in keys if k]
        self._gemini_bad: dict = {}     # key -> time.monotonic() it may be tried again
        self._gemini_tts_bad: dict = {}  # (key, model) -> same
        self.director_model = director_model if director_model in DIRECTOR_MODELS else DIRECTOR_MODEL
        # httpx drops a connection idle for 5 s by default, so every line that
        # came more than 5 s after the last call to the same service paid a
        # new TLS handshake over the hotspot. Kept 2 minutes now, and
        # keepalive() touches each service every KEEPALIVE_S between them.
        self.http = httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=8.0),
                                      limits=httpx.Limits(max_connections=40,
                                                          max_keepalive_connections=20,
                                                          keepalive_expiry=120.0))
        self.eleven_gate = ElevenGate(ELEVEN_SLOTS)
        # False once OpenAI refuses for billing or the key: Gemini from then on.
        self.openai_ok = bool(openai_key)
        self.on_switch = None           # called with a sentence when that happens

    @property
    def gemini_key(self) -> str:
        now = time.monotonic()
        good = [k for k in self.gemini_keys if self._gemini_bad.get(k, 0) <= now]
        if good:
            return good[0]
        # All resting: the one that comes back first.
        return min(self.gemini_keys, key=lambda k: self._gemini_bad.get(k, 0)) if self.gemini_keys else ""

    def gemini_tts(self) -> tuple[str, str]:
        """(key, voice model) to use now: the first pair not resting."""
        now = time.monotonic()
        pairs = [(k, m) for m in GEMINI_TTS_MODELS for k in self.gemini_keys]
        good = [p for p in pairs if self._gemini_tts_bad.get(p, 0) <= now
                and self._gemini_bad.get(p[0], 0) <= now]
        if good:
            return good[0]
        return min(pairs, key=lambda p: self._gemini_tts_bad.get(p, 0)) if pairs else ("", GEMINI_TTS)

    def gemini_tts_refused(self, key: str, model: str, status: int, body: str = "") -> None:
        if status not in (429, 403, 401):
            return
        daily = "PerDay" in (body or "")
        self._gemini_tts_bad[(key, model)] = time.monotonic() + (6 * 3600.0 if daily or status != 429
                                                                 else 60.0)
        log.warning("Gemini voice %s refused on a key (%s%s); trying the next", model, status,
                    ", daily cap" if daily else "")

    def gemini_refused(self, key: str, status: int) -> None:
        """Gemini's limits are per minute (the voice preview model allows only
        a handful a minute per key): a refused key rests for a minute."""
        if status in (429, 403, 401) and key in self.gemini_keys:
            self._gemini_bad[key] = time.monotonic() + (60.0 if status == 429 else 3600.0)
            log.warning("a Gemini key answered %s; using the next one", status)

    def openai_refused(self, status: int, text: str) -> bool:
        """A refusal that will not go away by retrying: no credits, bad key."""
        t = (text or "").lower()
        dead = status == 401 or (status == 429 and any(
            w in t for w in ("insufficient_quota", "credits", "billing", "quota")))
        if dead and self.openai_ok and (self.gemini_key or self.openrouter_key):
            self.openai_ok = False
            msg = ("OpenAI refused ({}): the robots use OpenRouter and Gemini instead".format(
                "no credits" if status == 429 else "key rejected"))
            log.warning("%s", msg)
            if self.on_switch is not None:
                self.on_switch(msg)
        return dead

    def use_gemini_brain(self, model: str = "") -> bool:
        model = model or self.director_model
        if "/" in model and self.openrouter_key:
            return False
        return bool(self.gemini_key) and (model.startswith("gemini") or not self.openai_ok)

    def brain(self, model: str = "") -> str:
        """Who writes the lines now (with `model`, or the table's writer):
        "openrouter", "openai" or "gemini"."""
        if "/" in (model or self.director_model) and self.openrouter_key:
            return "openrouter"
        return "gemini" if self.use_gemini_brain(model) else "openai"

    async def close(self) -> None:
        await self.http.aclose()

    async def warm(self) -> None:
        """Open the connections before the first line needs them, and find out
        now (one 1-token call) whether OpenAI still has credits: on 2026-10-21
        the first lines tried an empty OpenAI account and hung."""
        if self.openai_key:
            try:
                r = await self.http.post(
                    OPENAI + "/chat/completions", headers={"Authorization": "Bearer " + self.openai_key},
                    json={"model": "gpt-4.1-nano", "max_completion_tokens": 1,
                          "messages": [{"role": "user", "content": "hi"}]})
                if r.status_code != 200:
                    self.openai_refused(r.status_code, r.text)
            except Exception as exc:  # noqa: BLE001
                log.info("OpenAI check failed: %s", exc)
        for url, headers in ((ELEVEN + "/v1/models", {"xi-api-key": self.eleven_key}),
                             (OPENROUTER + "/key", {"Authorization": "Bearer " + self.openrouter_key})):
            try:
                await self.http.get(url, headers=headers)
            except Exception as exc:  # noqa: BLE001
                log.info("warm-up of %s failed: %s", url, exc)

    async def keepalive(self) -> None:
        """Free GETs that keep a warm connection to each service in the pool."""
        gets = []
        if self.eleven_key:
            gets.append((ELEVEN + "/v1/models", {"xi-api-key": self.eleven_key}))
        if self.openrouter_key:
            gets.append((OPENROUTER + "/key", {"Authorization": "Bearer " + self.openrouter_key}))
        if self.gemini_key:
            gets.append((GEMINI.rstrip("/") + "?pageSize=1", {"x-goog-api-key": self.gemini_key}))
        if self.openai_key and self.openai_ok:
            gets.append((OPENAI + "/models", {"Authorization": "Bearer " + self.openai_key}))

        async def get(url: str, headers: dict) -> None:
            try:
                await asyncio.wait_for(self.http.get(url, headers=headers), 10.0)
            except Exception as exc:  # noqa: BLE001
                log.debug("keepalive %s: %s", url, exc)
        await asyncio.gather(*(get(u, h) for u, h in gets))

    async def ping_writer(self, model: str) -> None:
        """One real, tiny request to a writer model (ServiceError if it fails)."""
        await self.director("You answer with a JSON object only.",
                            'Answer exactly {"ok": true}', timeout=15.0, max_tokens=20,
                            model=model)

    async def ping_voice(self, voice_id: str) -> int:
        """One real, tiny ElevenLabs request in that voice; bytes of audio."""
        got = 0
        async for chunk in self.speech(voice_id, "Ready."):
            got += len(chunk)
        if not got:
            raise ServiceError("ElevenLabs sent no audio")
        return got

    async def ping_hearing(self, language: str = "") -> str:
        """The transcription path the conversation uses, on half a second of
        quiet room noise."""
        import numpy as np
        noise = (np.random.default_rng(0).normal(0, 30, 8000)).astype(np.int16).tobytes()
        text, _ = await self.transcribe(noise, language=language)
        return text

    async def director(self, system: str, user: str, image: Optional[bytes] = None,
                       timeout: float = DIRECTOR_TIMEOUT_S, max_tokens: int = 400,
                       model: str = "") -> dict:
        """One JSON reply: OpenRouter (the default), OpenAI, or Gemini direct;
        each falls to the next when it fails."""
        model = model or self.director_model
        if "/" in model and self.openrouter_key:
            try:
                return await self.openrouter_director(model, system, user, image, timeout)
            except ServiceError as exc:
                log.info("OpenRouter writer failed (%s); falling back", exc)
                if self.gemini_key:
                    return await self.gemini_director(system, user, image, timeout)
                raise
        if self.use_gemini_brain(model):
            return await self.gemini_director(system, user, image, timeout)
        try:
            return await self.openai_director(system, user, image, timeout, max_tokens, model)
        except ServiceError:
            if self.use_gemini_brain(model):
                return await self.gemini_director(system, user, image, timeout)
            raise

    async def openrouter_director(self, model: str, system: str, user: str,
                                  image: Optional[bytes], timeout: float) -> dict:
        import base64
        content: Any = user + "\nReply with the JSON object only."
        if image:
            content = [{"type": "text", "text": content},
                       {"type": "image_url", "image_url": {
                           "url": "data:image/jpeg;base64," + base64.b64encode(image).decode()}}]
        body: dict = {"model": model, "temperature": 0.9, "max_tokens": 900,
                      "messages": [{"role": "system", "content": system},
                                   {"role": "user", "content": content}]}
        if "gpt-oss" in model:
            body["reasoning"] = {"effort": "low", "exclude": True}
            body["provider"] = {"order": ["cerebras", "groq"]}
        elif "gpt-5" in model:
            body["reasoning"] = {"effort": "none", "exclude": True}
        elif "gemini" in model:
            body["reasoning"] = {"effort": "minimal", "exclude": True}
        try:
            r = await asyncio.wait_for(self.http.post(
                OPENROUTER + "/chat/completions",
                headers={"Authorization": "Bearer " + self.openrouter_key}, json=body), timeout)
        except asyncio.TimeoutError as exc:
            raise ServiceError("the writer ({}) did not answer within {:.0f} s".format(
                model, timeout)) from exc
        except httpx.HTTPError as exc:
            raise ServiceError("the writer ({}) could not be reached: {}".format(
                model, type(exc).__name__)) from exc
        if r.status_code != 200:
            raise ServiceError("the writer ({}) answered {}: {}".format(
                model, r.status_code, r.text[:200]), r.status_code, r.text)
        try:
            content = r.json()["choices"][0]["message"].get("content") or ""
            match = re.search(r"\{.*\}", content, re.S)
            out = json.loads(match.group(0) if match else content)
            if isinstance(out, list) and out and isinstance(out[0], dict):
                out = out[0]
            return out if isinstance(out, dict) else {}
        except (KeyError, IndexError, ValueError) as exc:
            raise ServiceError("the writer ({}) wrote something that is not JSON".format(
                model)) from exc

    async def openrouter_transcribe(self, pcm: bytes, language: str = "") -> tuple[str, Optional[str]]:
        import base64
        body = {"model": OR_STT_MODEL, "reasoning": {"effort": "minimal", "exclude": True},
                "messages": [{"role": "user", "content": [
                    {"type": "text", "text": "Transcribe only the speech in this clip exactly, "
                                             "{}; never translate. Output only the words, nothing "
                                             "if no speech.".format(spoken_in(language))},
                    {"type": "input_audio", "input_audio": {
                        "data": base64.b64encode(wav_bytes(pcm)).decode(), "format": "wav"}}]}]}
        try:
            r = await asyncio.wait_for(self.http.post(
                OPENROUTER + "/chat/completions",
                headers={"Authorization": "Bearer " + self.openrouter_key}, json=body), 10.0)
        except (asyncio.TimeoutError, httpx.HTTPError) as exc:
            raise ServiceError("transcription (OpenRouter) failed: {}".format(
                type(exc).__name__)) from exc
        if r.status_code != 200:
            raise ServiceError("transcription (OpenRouter) answered {}".format(r.status_code))
        text = (r.json()["choices"][0]["message"].get("content") or "").strip().strip('"')
        return text, ("he" if re.search(r"[\u0590-\u05FF]", text) else ("en" if text else None))

    async def gemini_director(self, system: str, user: str, image: Optional[bytes],
                              timeout: float) -> dict:
        import base64
        parts: list = [{"text": user}]
        if image:
            parts.append({"inlineData": {"mimeType": "image/jpeg",
                                         "data": base64.b64encode(image).decode()}})
        body = {"systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": parts}],
                "generationConfig": {"responseMimeType": "application/json", "temperature": 0.9,
                                     "thinkingConfig": {"thinkingLevel": "minimal"}}}
        key = self.gemini_key
        try:
            r = await asyncio.wait_for(self.http.post(
                GEMINI + GEMINI_DIRECTOR + ":generateContent",
                headers={"x-goog-api-key": key}, json=body), timeout)
        except asyncio.TimeoutError as exc:
            raise ServiceError("the director (Gemini) did not answer within {:.0f} s".format(
                timeout)) from exc
        except httpx.HTTPError as exc:
            raise ServiceError("the director (Gemini) could not be reached: {}".format(
                type(exc).__name__)) from exc
        if r.status_code != 200:
            self.gemini_refused(key, r.status_code)
            raise ServiceError("the director (Gemini) answered {}: {}".format(
                r.status_code, r.text[:200]))
        try:
            content = "".join(p.get("text", "") for p in
                              r.json()["candidates"][0]["content"]["parts"])
            match = re.search(r"\{.*\}", content, re.S)
            out = json.loads(match.group(0) if match else content)
            if isinstance(out, list) and out and isinstance(out[0], dict):
                out = out[0]
            return out if isinstance(out, dict) else {}
        except (KeyError, IndexError, ValueError) as exc:
            raise ServiceError("the director (Gemini) wrote something that is not JSON") from exc

    async def openai_director(self, system: str, user: str, image: Optional[bytes] = None,
                              timeout: float = DIRECTOR_TIMEOUT_S, max_tokens: int = 400,
                              model: str = "") -> dict:
        """One JSON reply. `image` (a JPEG from a robot's camera) goes with the
        user message. A hard `timeout`: on 2026-10-19 a stalled call sat out
        the client's 30 s while the room waited."""
        content: Any = user
        if image:
            import base64
            content = [{"type": "text", "text": user},
                       {"type": "image_url", "image_url": {
                           "url": "data:image/jpeg;base64," + base64.b64encode(image).decode(),
                           "detail": "low"}}]
        model = model or self.director_model
        model = model if model.startswith("gpt") else "gpt-4.1-mini"
        body = {"model": model, "max_completion_tokens": max_tokens,
                "response_format": {"type": "json_object"},
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": content}]}
        if model.startswith("gpt-5"):
            body["reasoning_effort"] = "none"
        else:
            body["temperature"] = 0.9
        try:
            r = await asyncio.wait_for(self.http.post(
                OPENAI + "/chat/completions",
                headers={"Authorization": "Bearer " + self.openai_key}, json=body), timeout)
        except asyncio.TimeoutError as exc:
            raise ServiceError("the director (OpenAI) did not answer within {:.0f} s".format(
                timeout)) from exc
        except httpx.HTTPError as exc:
            raise ServiceError("the director (OpenAI) could not be reached: {}".format(
                type(exc).__name__)) from exc
        if r.status_code != 200:
            self.openai_refused(r.status_code, r.text)
            raise ServiceError("the director (OpenAI) answered {}: {}".format(
                r.status_code, r.text[:200]))
        content = r.json()["choices"][0]["message"]["content"]
        try:
            return json.loads(content)
        except ValueError as exc:
            raise ServiceError("the director wrote something that is not JSON: {}".format(
                content[:120])) from exc

    async def director_heard(self, system: str, user: str, pcm: bytes) -> dict:
        """The director answering people straight from their voice: one call
        returns what they said ("heard") and the reply. ~1.3 s against ~3 s
        for transcribe-then-direct (measured 2026-10-19)."""
        import base64
        r = await self.http.post(
            OPENAI + "/chat/completions",
            headers={"Authorization": "Bearer " + self.openai_key},
            json={"model": HEARING_MODEL, "modalities": ["text"],
                  "messages": [{"role": "system", "content": system},
                               {"role": "user", "content": [
                                   {"type": "text", "text": user},
                                   {"type": "input_audio", "input_audio": {
                                       "data": base64.b64encode(wav_bytes(pcm)).decode(),
                                       "format": "wav"}}]}]})
        if r.status_code != 200:
            raise ServiceError("the listening director (OpenAI) answered {}: {}".format(
                r.status_code, r.text[:200]))
        content = r.json()["choices"][0]["message"]["content"] or ""
        match = re.search(r"\{.*\}", content, re.S)
        try:
            return json.loads(match.group(0) if match else content)
        except ValueError as exc:
            raise ServiceError("the listening director wrote something that is not "
                               "JSON: {}".format(content[:120])) from exc

    async def transcribe(self, pcm: bytes, prompt: str = "",
                         language: str = "") -> tuple[str, Optional[str]]:
        if self.openai_ok:
            try:
                return await self.openai_transcribe(pcm, prompt, language)
            except ServiceError:
                if not (self.gemini_key or self.openrouter_key) or self.openai_ok:
                    raise
        return await self.backup_transcribe(pcm, prompt, language)

    async def backup_transcribe(self, pcm: bytes, prompt: str = "",
                                language: str = "") -> tuple[str, Optional[str]]:
        """Gemini direct (~1.5 s), raced by OpenRouter's Gemini after 2.5 s
        (one direct call took 48 s in the 2026-10-21 tests)."""
        tasks = []
        if self.gemini_key:
            tasks.append(asyncio.ensure_future(self.gemini_transcribe(pcm, prompt, language)))
        if self.openrouter_key:
            if tasks:
                done, _ = await asyncio.wait(tasks, timeout=2.5)
                if done and tasks[0].exception() is None:
                    return tasks[0].result()
            tasks.append(asyncio.ensure_future(self.openrouter_transcribe(pcm, language)))
        if not tasks:
            raise ServiceError("no service left to transcribe with")
        try:
            pending = set(tasks)
            last: Optional[BaseException] = None
            while pending:
                done, pending = await asyncio.wait(pending, timeout=12.0,
                                                   return_when=asyncio.FIRST_COMPLETED)
                if not done:
                    break
                for t in done:
                    if t.exception() is None:
                        return t.result()
                    last = t.exception()
            raise ServiceError("transcription failed: {}".format(last or "timed out"))
        finally:
            for t in tasks:
                if not t.done():
                    t.cancel()

    async def gemini_transcribe(self, pcm: bytes, prompt: str = "",
                                language: str = "") -> tuple[str, Optional[str]]:
        import base64
        _name, data, mime = compressed(pcm)
        # No earlier text as a hint: given one, Gemini wrote it out again in
        # front of every piece and the transcript snowballed (dry run 2026-10-21).
        ask = ("Transcribe only the speech in this audio clip, exactly, {}. Output only those "
               "words, nothing else; output nothing if there is no speech. Never repeat words "
               "that are not in the clip.".format(spoken_in(language)))
        body = {"contents": [{"parts": [{"text": ask}, {"inlineData": {
                    "mimeType": mime, "data": base64.b64encode(data).decode()}}]}],
                "generationConfig": {"temperature": 0, "thinkingConfig": {"thinkingLevel": "minimal"}}}
        key = self.gemini_key
        try:
            r = await asyncio.wait_for(self.http.post(
                GEMINI + GEMINI_STT + ":generateContent",
                headers={"x-goog-api-key": key}, json=body), 12.0)
        except (asyncio.TimeoutError, httpx.HTTPError) as exc:
            raise ServiceError("transcription (Gemini) failed: {}".format(type(exc).__name__)) from exc
        if r.status_code != 200:
            self.gemini_refused(key, r.status_code)
            raise ServiceError("transcription (Gemini) answered {}: {}".format(
                r.status_code, r.text[:200]))
        try:
            text = "".join(p.get("text", "") for p in r.json()["candidates"][0]["content"]["parts"])
        except (KeyError, IndexError, ValueError):
            text = ""
        text = text.strip().strip('"')
        # A clip of n seconds holds at most ~4 words a second; more is a loop.
        words = text.split()
        limit = int(len(pcm) / 32000 * 4) + 4
        if len(words) > limit:
            log.info("Gemini transcript too long for the clip (%d words); cut", len(words))
            text = " ".join(words[:limit])
        if text.lower().strip("[]().") in ("no speech", "silence", "none", "empty"):
            text = ""
        return text, ("he" if re.search(r"[\u0590-\u05FF]", text) else ("en" if text else None))

    async def openai_transcribe(self, pcm: bytes, prompt: str = "",
                                language: str = "") -> tuple[str, Optional[str]]:
        """(text, language code or None) for 16 kHz int16 mono speech.
        `prompt` is the text just before this piece (streaming segments)."""
        data = {"model": STT_MODEL}
        if prompt:
            data["prompt"] = prompt[-400:]
        if language in ("he", "en"):
            data["language"] = language
        r = await self.http.post(
            OPENAI + "/audio/transcriptions",
            headers={"Authorization": "Bearer " + self.openai_key},
            files={"file": compressed(pcm)},
            data=data)
        if r.status_code != 200:
            self.openai_refused(r.status_code, r.text)
            raise ServiceError("transcription (OpenAI) answered {}: {}".format(
                r.status_code, r.text[:200]))
        j = r.json()
        langs = j.get("languages") or []
        return (j.get("text") or "").strip(), (langs[0].get("code") if langs else None)

    async def speech(self, voice_id: str, text: str,
                     background: bool = False) -> AsyncIterator[bytes]:
        """int16 16 kHz mono chunks as ElevenLabs produces them (or, on a slow
        network, a 32 kbps MP3 decoded here as it arrives). `background`:
        warming interjections, which waits for the live lines (ElevenGate).
        A "too many concurrent requests" or a server error is waited out and
        tried again before it is raised."""
        fmt = "mp3_22050_32" if self.compressed else "pcm_16000"
        url = "{}/v1/text-to-speech/{}/stream?output_format={}".format(ELEVEN, voice_id, fmt)
        # A little less stability than the default: livelier, more acted.
        body = {"text": text, "model_id": TTS_MODEL,
                "voice_settings": {"stability": 0.35, "similarity_boost": 0.75,
                                   "style": 0.45, "use_speaker_boost": True}}
        await self.eleven_gate.acquire(background)
        try:
            for wait in ELEVEN_BUSY_WAITS + (None,):
                async with self.http.stream("POST", url, headers={"xi-api-key": self.eleven_key},
                                            json=body) as r:
                    if r.status_code != 200:
                        raw = (await r.aread()).decode("utf-8", "replace")
                        busy = (r.status_code == 429 and "concurrent" in raw) or r.status_code >= 500
                        if busy and wait is not None:
                            log.info("ElevenLabs busy (%d); trying again in %.1f s",
                                     r.status_code, wait)
                            await asyncio.sleep(wait)
                            continue
                        raise ServiceError("ElevenLabs answered {}: {}".format(
                            r.status_code, raw[:200]), r.status_code, raw)
                    if self.compressed:
                        dec = StreamDecoder()
                        async for chunk in r.aiter_bytes():
                            pcm = dec.feed(chunk)
                            if pcm:
                                yield pcm
                        pcm = dec.finish()
                        if pcm:
                            yield pcm
                        return
                    carry = b""
                    async for chunk in r.aiter_bytes():
                        chunk = carry + chunk
                        if len(chunk) % 2:
                            carry, chunk = chunk[-1:], chunk[:-1]
                        else:
                            carry = b""
                        if chunk:
                            yield chunk
                    return
        finally:
            self.eleven_gate.release(background)


async def openai_speech(http: httpx.AsyncClient, key: str, voice: str, text: str,
                        style: str = "", compressed: bool = False) -> AsyncIterator[bytes]:
    """OpenAI TTS as the robots' second voice (ElevenLabs out of credits or
    down). It only gives 24 kHz PCM, so this resamples to the robots' 16 kHz
    in blocks of 3 input samples -> 2 output samples (linear, no filter: fine
    for speech). First audio ~2.7 s on the lab hotspot, hidden by the
    conductor preparing each line while the previous one plays."""
    import numpy as np
    body = {"model": OPENAI_TTS_MODEL, "voice": voice, "input": text,
            "response_format": "opus" if compressed else "pcm",
            "instructions": style or "Natural, lively, conversational speech."}
    if compressed:
        r = await http.post(OPENAI + "/audio/speech",
                            headers={"Authorization": "Bearer " + key}, json=body)
        if r.status_code != 200:
            raise ServiceError("OpenAI voice answered {}: {}".format(r.status_code, r.text[:200]),
                               r.status_code, r.text)
        for piece in chunked(decode_to_16k(r.content)):
            yield piece
        return
    async with http.stream("POST", OPENAI + "/audio/speech",
                           headers={"Authorization": "Bearer " + key}, json=body) as r:
        if r.status_code != 200:
            raw = (await r.aread()).decode("utf-8", "replace")
            raise ServiceError("OpenAI voice answered {}: {}".format(r.status_code, raw[:200]),
                               r.status_code, raw)
        carry = b""
        async for chunk in r.aiter_bytes():
            data = carry + chunk
            usable = (len(data) // 6) * 6          # whole groups of 3 int16 samples
            carry = data[usable:]
            if not usable:
                continue
            x = np.frombuffer(data[:usable], dtype=np.int16).astype(np.float32)
            x = x.reshape(-1, 3)
            # Output samples sit at input positions 0 and 1.5 of each group.
            y = np.empty((x.shape[0], 2), dtype=np.float32)
            y[:, 0] = x[:, 0]
            y[:, 1] = (x[:, 1] + x[:, 2]) / 2
            yield y.reshape(-1).astype(np.int16).tobytes()


async def list_voices(eleven_key: str) -> list[dict]:
    async with httpx.AsyncClient(timeout=10) as http:
        r = await http.get(ELEVEN + "/v1/voices", headers={"xi-api-key": eleven_key})
        r.raise_for_status()
    return [{"voice_id": v["voice_id"], "name": v.get("name", v["voice_id"]),
             "gender": str((v.get("labels") or {}).get("gender") or "").lower()}
            for v in r.json().get("voices", []) if v.get("voice_id")]


def male(label: str) -> bool:
    """A voice list's description says male ("male", "male, deep")."""
    return label.lower().startswith("male")


async def eleven_credits(eleven_key: str) -> Optional[int]:
    """Characters left on the ElevenLabs plan, None if it could not be asked."""
    try:
        async with httpx.AsyncClient(timeout=8) as http:
            r = await http.get(ELEVEN + "/v1/user/subscription", headers={"xi-api-key": eleven_key})
        if r.status_code != 200:
            return None
        j = r.json()
        return int(j.get("character_limit", 0)) - int(j.get("character_count", 0))
    except Exception as exc:  # noqa: BLE001
        log.info("could not read ElevenLabs credits: %s", exc)
        return None


# Gemini's prebuilt voices for the five characters, matched by gender and feel.
GEMINI_VOICES = {"Noa": "Zephyr", "Dor": "Charon", "Maya": "Kore", "Eli": "Puck",
                 "Tamar": "Sulafat"}
GEMINI_SPARE = ("Aoede", "Fenrir", "Leda", "Orus", "Callirrhoe")

# The voices each provider offers, for the page's per-robot voice picker
# (2026-10-21: Tomer picks each robot's voice from the provider it uses).
# OpenRouter's gpt-audio-mini takes OpenAI's realtime voices only (no fable,
# nova or onyx).
OPENAI_VOICE_LIST = (("alloy", "neutral"), ("ash", "male"), ("ballad", "male"),
                     ("cedar", "male"), ("coral", "female"), ("echo", "male"),
                     ("fable", "male, British"), ("marin", "female"), ("nova", "female"),
                     ("onyx", "male, deep"), ("sage", "female"), ("shimmer", "female"),
                     ("verse", "male"))
OPENROUTER_VOICES = ("alloy", "ash", "ballad", "cedar", "coral", "echo", "marin", "sage",
                     "shimmer", "verse")
GEMINI_VOICE_LIST = (("Achernar", "female, soft"), ("Achird", "male, friendly"),
                     ("Algenib", "male, gravelly"), ("Algieba", "male, smooth"),
                     ("Alnilam", "male, firm"), ("Aoede", "female, breezy"),
                     ("Autonoe", "female, bright"), ("Callirrhoe", "female, easy-going"),
                     ("Charon", "male, informative"), ("Despina", "female, smooth"),
                     ("Enceladus", "male, breathy"), ("Erinome", "female, clear"),
                     ("Fenrir", "male, excitable"), ("Gacrux", "female, mature"),
                     ("Iapetus", "male, clear"), ("Kore", "female, firm"),
                     ("Laomedeia", "female, upbeat"), ("Leda", "female, youthful"),
                     ("Orus", "male, firm"), ("Puck", "male, upbeat"),
                     ("Pulcherrima", "female, forward"), ("Rasalgethi", "male, informative"),
                     ("Sadachbia", "male, lively"), ("Sadaltager", "male, knowledgeable"),
                     ("Schedar", "male, even"), ("Sulafat", "female, warm"),
                     ("Umbriel", "male, easy-going"), ("Vindemiatrix", "female, gentle"),
                     ("Zephyr", "female, bright"), ("Zubenelgenubi", "male, casual"))


async def gemini_speech(http: httpx.AsyncClient, key: str, voice: str, text: str,
                        tone: str = "", model: str = GEMINI_TTS) -> AsyncIterator[bytes]:
    """Gemini TTS, streamed (SSE, 24 kHz PCM, resampled to 16 kHz). The way of
    speaking goes in front of the words, as Gemini's TTS expects
    ("Say excitedly: ...")."""
    import base64
    spoken = "Say this {}: {}".format(tone, text) if tone else text
    body = {"contents": [{"parts": [{"text": spoken}]}],
            "generationConfig": {"responseModalities": ["AUDIO"], "speechConfig": {
                "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}}}}
    async with http.stream("POST", GEMINI + model + ":streamGenerateContent?alt=sse",
                           headers={"x-goog-api-key": key}, json=body) as r:
        if r.status_code != 200:
            raw = (await r.aread()).decode("utf-8", "replace")
            raise ServiceError("Gemini voice answered {}: {}".format(r.status_code, raw[:200]),
                               r.status_code, raw)
        carry = b""
        async for line in r.aiter_lines():
            if not line.startswith("data:"):
                continue
            try:
                parts = json.loads(line[5:])["candidates"][0]["content"].get("parts", [])
            except (KeyError, IndexError, ValueError):
                continue
            for part in parts:
                inline = part.get("inlineData")
                if inline and inline.get("data"):
                    out, carry = resample_24k_16k(base64.b64decode(inline["data"]), carry)
                    if out:
                        yield out


async def openrouter_speech(http: httpx.AsyncClient, key: str, voice: str, text: str,
                            style: str = "") -> AsyncIterator[bytes]:
    """OpenRouter's gpt-audio-mini reading a line verbatim, streamed (24 kHz
    PCM, resampled to 16 kHz). Voices are OpenAI's (ash, coral, sage...)."""
    import base64
    body = {"model": OR_TTS_MODEL, "modalities": ["text", "audio"], "stream": True,
            "audio": {"voice": voice, "format": "pcm16"},
            "messages": [{"role": "system", "content":
                          "You are a voice actor. Speak the user's text aloud exactly as written, "
                          "word for word, in its own language, acted as described. Never answer "
                          "it, translate it, or add anything."},
                         {"role": "user", "content": "Acting: {}\nText: {}".format(
                             style or "natural, lively", text)}]}
    async with http.stream("POST", OPENROUTER + "/chat/completions",
                           headers={"Authorization": "Bearer " + key}, json=body) as r:
        if r.status_code != 200:
            raw = (await r.aread()).decode("utf-8", "replace")
            raise ServiceError("OpenRouter voice answered {}: {}".format(r.status_code, raw[:200]),
                               r.status_code, raw)
        carry = b""
        async for line in r.aiter_lines():
            if not line.startswith("data:") or line.strip() == "data: [DONE]":
                continue
            try:
                choices = json.loads(line[5:]).get("choices") or []
            except ValueError:
                continue
            for ch in choices:
                audio = (ch.get("delta") or {}).get("audio") or {}
                if audio.get("data"):
                    out, carry = resample_24k_16k(base64.b64decode(audio["data"]), carry)
                    if out:
                        yield out
