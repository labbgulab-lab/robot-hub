"""ElevenLabs ears and voice for engine B ("ElevenLabs ears + voice, GPT brain").

Ears -- Scribe v2 Realtime (elevenlabs.io/docs, read 2026-10-07):
    wss://api.elevenlabs.io/v1/speech-to-text/realtime
        ?model_id=scribe_v2_realtime&audio_format=pcm_24000&commit_strategy=vad
         &vad_silence_threshold_secs=..&include_language_detection=true
    header xi-api-key
    -> {"message_type": "input_audio_chunk", "audio_base_64", "commit": false, "sample_rate"}
    <- session_started / partial_transcript {text} / committed_transcript {text}
    Hebrew and English are both in its 90+ languages; the language is detected
    per sentence, which is the point: visitors answer in Hebrew or in English.

Voice -- Eleven v4 Turbo over the Text to Dialogue WebSocket, exactly as
reachy_chat/providers/elevenlabs_voice.py uses it on Reachy (working there
since 2026-10-05):
    wss://api.elevenlabs.io/v1/text-to-dialogue/stream-input
        ?model_id=eleven_v4_turbo&output_format=pcm_24000
    -> {"voices": [voice_id]} -> {"inputs": [{"text", "voice_id"}]} ...
    -> {"flush": true}, {"close_socket": true}
    <- {"audio": base64, "is_final": bool}

On Reachy, ElevenLabs re-voiced the transcript of a speech-to-speech model
that was itself still speaking, and the two raced (GPT + ElevenLabs stuttered,
not fixed). Here the brain produces text only, so nothing races.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import time
from typing import Awaitable, Callable, Optional
from urllib.parse import urlencode

log = logging.getLogger("pepper.eleven")

API = "https://api.elevenlabs.io"
STT_URL = "wss://api.elevenlabs.io/v1/speech-to-text/realtime"
TTS_URL = "wss://api.elevenlabs.io/v1/text-to-dialogue/stream-input"
STT_MODEL = "scribe_v2_realtime"
TTS_MODEL = "eleven_v4_turbo"
RATE = 24000
# Turn-based: people pause to think before an answer is finished, so the
# silence that ends a turn is longer than a chat app would use.
SILENCE_ENDS_TURN_S = 0.9
CONNECT_TIMEOUT_S = 6.0
# The mic is gated while Pepper speaks, so Scribe can go many seconds without
# audio; on 2026-10-12 its session ended mid-conversation. Keep it fed with
# silence, and reconnect by itself if it ends anyway.
KEEPALIVE_S = 3.0
RECONNECTS = 3
FINISH_TIMEOUT_S = 25.0


async def list_voices(key: str) -> list[dict]:
    """The account's voices: [{id, name, language}]."""
    import httpx
    async with httpx.AsyncClient(timeout=8.0) as client:
        r = await client.get(API + "/v1/voices", headers={"xi-api-key": key})
    r.raise_for_status()
    out = []
    for v in r.json().get("voices") or []:
        labels = v.get("labels") or {}
        if v.get("voice_id"):
            out.append({"id": v["voice_id"], "name": v.get("name", ""),
                        "language": labels.get("language", "") or labels.get("accent", "")})
    return out


# ---------------------------------------------------------------- ears
class ScribeEars:
    """A live transcription session. `on_partial(text)` while someone talks,
    `on_final(text, language)` once Scribe decides the sentence is over."""

    def __init__(self, key: str, *, language: str,
                 on_partial: Callable[[str], None],
                 on_final: Callable[[str, str], Awaitable[None]],
                 on_error: Callable[[str], None]) -> None:
        self.key, self.language = key, language
        self.on_partial, self.on_final, self.on_error = on_partial, on_final, on_error
        self.ws = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self._buf = bytearray()
        self._tasks: list[asyncio.Task] = []
        self.running = False
        self._last: tuple[str, float] = ("", 0.0)
        self._last_partial_t: Optional[float] = None
        self.commit_gap_s: Optional[float] = None   # last partial -> committed sentence

    def _url(self) -> str:
        q = {"model_id": STT_MODEL, "audio_format": "pcm_24000", "commit_strategy": "vad",
             "vad_silence_threshold_secs": SILENCE_ENDS_TURN_S,
             "include_language_detection": "true"}
        if self.language in ("he", "en"):
            q["language_code"] = self.language
        return STT_URL + "?" + urlencode(q)

    async def start(self) -> None:
        self.loop = asyncio.get_running_loop()
        await self._connect()
        self.running = True
        self._tasks = [asyncio.create_task(self._reader(), name="scribe-reader"),
                       asyncio.create_task(self._uplink(), name="scribe-uplink")]

    async def _connect(self) -> None:
        from websockets.asyncio.client import connect
        try:
            self.ws = await connect(self._url(), additional_headers={"xi-api-key": self.key},
                                    max_size=None, open_timeout=CONNECT_TIMEOUT_S)
        except Exception as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            raise RuntimeError("ElevenLabs speech-to-text refused the connection{}: {}".format(
                " (401: check the ElevenLabs key)" if status == 401 else "", exc)) from exc

    def push(self, pcm24: bytes) -> None:
        """From any thread: the person's audio, already gated by the router."""
        if self.running and self.loop is not None:
            self.loop.call_soon_threadsafe(self._buf.extend, pcm24)

    def clear(self) -> None:
        self._buf.clear()

    async def stop(self) -> None:
        self.running = False
        for t in self._tasks:
            t.cancel()
        ws, self.ws = self.ws, None
        if ws is not None:
            with contextlib.suppress(Exception):
                await ws.close()

    async def _uplink(self) -> None:
        last_sent = time.monotonic()
        while True:
            await asyncio.sleep(0.1)
            if self.ws is None:
                continue
            if self._buf:
                pcm = bytes(self._buf)
                self._buf.clear()
            elif time.monotonic() - last_sent >= KEEPALIVE_S:
                pcm = bytes(2 * (RATE // 10))          # 0.1 s of silence
            else:
                continue
            last_sent = time.monotonic()
            try:
                await self.ws.send(json.dumps({"message_type": "input_audio_chunk",
                                               "audio_base_64": base64.b64encode(pcm).decode("ascii"),
                                               "commit": False, "sample_rate": RATE}))
            except Exception as exc:  # noqa: BLE001
                if not self.running:
                    return
                log.warning("speech-to-text send failed: %s", exc)   # the reader reconnects

    async def _reader(self) -> None:
        for attempt in range(RECONNECTS + 1):
            why = await self._read_session()
            if not self.running:
                return
            if attempt == RECONNECTS:
                break
            log.warning("speech-to-text: %s; reconnecting", why)
            try:
                self.ws = None
                await self._connect()
                self._buf.clear()
            except Exception as exc:  # noqa: BLE001
                why = str(exc)
                break
        self.on_error("speech-to-text session ended ({})".format(why))

    async def _read_session(self) -> str:
        ws = self.ws
        try:
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except ValueError:
                    continue
                kind = msg.get("message_type", "")
                if kind == "partial_transcript":
                    if (msg.get("text") or "").strip():
                        self._last_partial_t = time.monotonic()
                    self.on_partial(msg.get("text") or "")
                elif kind in ("committed_transcript", "committed_transcript_with_timestamps"):
                    # With language detection on, each sentence arrives twice
                    # (plain, then with timestamps): pass it on once.
                    text = (msg.get("text") or "").strip()
                    now = time.monotonic()
                    if not text or (text == self._last[0] and now - self._last[1] < 3.0):
                        continue
                    self._last = (text, now)
                    self.commit_gap_s = now - self._last_partial_t if self._last_partial_t else None
                    self._last_partial_t = None
                    await self.on_final(text, msg.get("language_code") or "")
                elif kind == "session_started":
                    log.info("speech-to-text: Scribe session %s", msg.get("session_id", "?"))
                elif msg.get("error"):
                    self.on_error("speech-to-text: {} {}".format(kind, msg.get("error")))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            return "connection lost: {}".format(exc)
        return "closed by ElevenLabs (code {}, {})".format(
            getattr(ws, "close_code", None), getattr(ws, "close_reason", None) or "no reason")


# ---------------------------------------------------------------- voice
class VoiceStream:
    """One reply's worth of speech: send text as it arrives, audio comes back
    to `play` as it is made. Open it as early as possible -- the connect
    overlaps the brain's thinking."""

    def __init__(self, key: str, voice_id: str, play: Callable[[bytes], None]) -> None:
        self.key, self.voice_id, self.play = key, voice_id, play
        self.ws = None
        self.failed: Optional[str] = None
        self.sent = 0
        self.audio_bytes = 0
        self.first_audio_t: Optional[float] = None
        self.first_text_t: Optional[float] = None
        self.done = asyncio.Event()
        self._finished = False
        self._connect = asyncio.create_task(self._open(), name="tts-connect")
        self._reader_task: Optional[asyncio.Task] = None
        self._pending: list[str] = []

    async def _open(self) -> None:
        from websockets.asyncio.client import connect
        url = "{}?model_id={}&output_format=pcm_24000".format(TTS_URL, TTS_MODEL)
        try:
            self.ws = await connect(url, additional_headers={"xi-api-key": self.key},
                                    max_size=None, open_timeout=CONNECT_TIMEOUT_S)
            await self.ws.send(json.dumps({"voices": [self.voice_id]}))
        except Exception as exc:  # noqa: BLE001
            self.failed = "could not open the ElevenLabs voice: {}".format(exc)
            self.done.set()
            return
        self._reader_task = asyncio.create_task(self._reader(), name="tts-reader")
        for text in self._pending:
            await self._send(text)
        self._pending = []
        if self._finished:
            await self._finish()

    async def _send(self, text: str) -> None:
        try:
            await self.ws.send(json.dumps({"inputs": [{"text": text, "voice_id": self.voice_id}]}))
            self.sent += len(text)
        except Exception as exc:  # noqa: BLE001
            self.failed = "ElevenLabs send failed: {}".format(exc)
            self.done.set()

    async def text(self, text: str) -> None:
        if not text or self.failed:
            return
        if self.first_text_t is None and text.strip():
            self.first_text_t = time.monotonic()
        if self.ws is None:
            self._pending.append(text)
        else:
            await self._send(text)

    async def finish(self) -> None:
        """No more text. Audio keeps coming until ElevenLabs says it is final."""
        self._finished = True
        if self.ws is not None:
            await self._finish()

    async def _finish(self) -> None:
        if self.sent == 0:
            self.done.set()
            return
        try:
            await self.ws.send(json.dumps({"flush": True}))
            await self.ws.send(json.dumps({"close_socket": True}))
        except Exception as exc:  # noqa: BLE001
            self.failed = "ElevenLabs finish failed: {}".format(exc)
            self.done.set()

    async def _reader(self) -> None:
        carry = b""
        try:
            async for raw in self.ws:
                try:
                    msg = json.loads(raw)
                except ValueError:
                    continue
                if msg.get("error"):
                    self.failed = "ElevenLabs: {}".format(msg["error"])
                    break
                data = msg.get("audio")
                if data:
                    pcm = carry + base64.b64decode(data)
                    cut = len(pcm) & ~1
                    carry = pcm[cut:]
                    if cut:
                        if self.first_audio_t is None:
                            self.first_audio_t = time.monotonic()
                        self.audio_bytes += cut
                        self.play(pcm[:cut])
                if msg.get("is_final") or msg.get("isFinal"):
                    break
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            if not self._finished:
                self.failed = "ElevenLabs voice dropped: {}".format(exc)
        self.done.set()

    async def wait(self, timeout: float = FINISH_TIMEOUT_S) -> bool:
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(self.done.wait(), timeout)
        return self.failed is None and self.audio_bytes > 0

    async def close(self) -> None:
        for t in (self._connect, self._reader_task):
            if t is not None and not t.done():
                t.cancel()
        if self.ws is not None:
            with contextlib.suppress(Exception):
                await self.ws.close()


async def synth(key: str, voice_id: str, text: str) -> bytes:
    """All of `text` as 24 kHz PCM16 (Wizard of Oz, quick phrases)."""
    chunks: list[bytes] = []
    stream = VoiceStream(key, voice_id, chunks.append)
    try:
        await stream.text(text)
        await stream.finish()
        ok = await stream.wait()
    finally:
        await stream.close()
    if not ok:
        raise RuntimeError(stream.failed or "ElevenLabs returned no audio")
    return b"".join(chunks)
