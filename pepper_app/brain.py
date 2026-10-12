"""Pepper's conversation: one brain (gpt-realtime-2.1), two ways to hear and speak.

Engine "realtime" (A) -- speech to speech:
    wss://api.openai.com/v1/realtime?model=gpt-realtime-2.1   (docs read 2026-10-07)
    the person's audio in, GPT's own voice out.
Engine "eleven" (B) -- ElevenLabs ears and voice, GPT brain:
    Scribe v2 Realtime turns the person's speech into text (Hebrew or English,
    detected per sentence), the same model answers in text only, and Eleven
    v4 Turbo speaks it (eleven.py). Built for a room of Hebrew speakers.

**Strictly turn-based, in both.** The model never decides on its own that
it is its turn: server VAD does not create responses (`create_response:
false`), and in B there is no audio going to OpenAI at all. This code does:

    Pepper speaks -> playback ends -> WAITING for the person
        a tap, or speech that is a real answer      -> Pepper's turn again
        noise / "hmm" / empty                       -> ignored (shown to the
                                                       operator, who can Accept it)
        no answer for REASK_S and a question is open -> Pepper repeats it ONCE,
                                                       then waits for as long as it takes
    the operator can Repeat, Skip (move on) or Accept at any time.

The mic only feeds the brain while it is WAITING, and it is shut while Pepper
is speaking (audio.AudioRouter), so Pepper never hears itself.

Tools put choices, messages and slides on the chest screen and run gestures;
a camera frame is added as an image when the person starts to answer (A) or
when their answer arrives (B).
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from . import eleven

log = logging.getLogger("pepper.brain")

MODEL = "gpt-realtime-2.1"
URL = "wss://api.openai.com/v1/realtime?model=" + MODEL
TRANSCRIBE_MODEL = "gpt-4o-mini-transcribe"
VOICES = ("marin", "cedar", "alloy", "ash", "ballad", "coral", "echo", "sage", "shimmer", "verse")
ENGINES = {"realtime": "GPT Realtime (speech to speech)",
           "eleven": "ElevenLabs ears + voice, GPT brain"}
UPLINK_EVERY_S = 0.1
VISION_GAP_S = 3.0
KEEP_IMAGES = 3
STUCK_AFTER_S = 10.0
# Extra replies after tool calls while Pepper has said nothing yet this turn: the
# model often spreads set_step, show_choice and a gesture over two or three replies.
MAX_SILENT_FOLLOW_UPS = 3
REASK_S = 12.0
# Only movements tested on this Pepper (agent/pepper_agent.py has the values).
MOVES = ("wave", "yes", "no", "arms_wide")

FILLERS = {"hm", "hmm", "hmmm", "um", "umm", "uh", "uhh", "ah", "ahh", "er", "erm", "mm", "mmm",
           "mhm", "oh", "eh", "huh", "אה", "אהה", "אמ", "אממ", "הממ", "ממ", "אהם", "נו"}
WORD = re.compile(r"[^\W\d_]+", re.UNICODE)


def real_answer(text: str) -> bool:
    """True when `text` is something a person answered, not noise or a filler.
    "yes", "no", "כן", "לא", a number or a name all count."""
    words = [w.lower() for w in WORD.findall(text or "")]
    if not words:
        return bool(re.search(r"\d", text or ""))
    return any(w not in FILLERS for w in words)


# ------------------------------------------------------------- experiences
TURNS = (
    "This is STRICTLY turn-based. End every turn with exactly one question or one clear "
    "invitation to answer, then STOP talking and wait. Never ask two questions in one turn, "
    "never answer for the person, and never move on to the next step until they have "
    "answered by tapping or talking. If a note says the person has not answered, repeat "
    "your last question once, briefly. If a note says the operator wants to move on, say "
    "kindly that it is fine and go to the next step. In every turn, FIRST call the tools you "
    "need (screen, gesture, set_step) without saying anything, THEN say your line. Never "
    "narrate the tools: do not say things like 'I'll show you' or 'let me set up the screen'.")

FEELINGS_COMMON = (
    "Run the structured experience 'Feelings Together'. It is a DEMO of a research protocol "
    "the lab could study with Pepper, inspired by published robot-assisted autism research. "
    "It is not therapy, not a test and not a diagnosis: never say it diagnoses, treats, "
    "measures or helps autism, and never say a visitor's answers mean anything about them. "
    "Never comment on the person's face, emotions, looks or identity, and never ask for eye "
    "contact. Style: short calm sentences, the same phrases every time ('You can tap or "
    "tell me.', 'Thanks!', 'Next one.'). Never say 'your turn'. Always accept a tap OR a spoken answer. "
    "Never say 'wrong': say 'Thanks! I would say <answer>.' If the person asks to stop, go "
    "straight to the last step. Keep it to about four minutes; no chatting between steps. "
    "Call set_step(step, title) at the start of each step.\n")

FEELINGS_STEPS = {
    "emoji": (
        "1 Welcome. gesture wave. show_message 'Today: 1 Hello 2 Choose 3 Feelings 4 Story "
        "5 Look 6 Bye' (you may add an allowed emoji). Say: 'Hi, I'm Pepper. This is a short "
        "demo of a study our lab could run. Here is our plan. Are you ready?'\n"
        "2 Choice. show_choice 'How do you like to answer?' options Tap (👆), "
        "Talk (💬), Both (👍). Respect their choice from now on.\n"
        "3 Comfort. show_choice 'My voice is...' options Just right (👍), Too fast (🐢), Too "
        "loud (🔊). If too fast, speak slower from now on. If too loud, say 'OK, I'll tell my team.'\n"
        "4 Faces. Ask 'Which face is happy?' show_choice 'Which one "
        "is HAPPY?' with three options labelled '1', '2', '3' and the emoji 😊, 😢, 😲 (labels "
        "are numbers so they do not give the answer away). Then one more round, in its own "
        "turn: 'Which one is SURPRISED?' with the faces in a different order.\n"
        "5 Story. show_message 'Dana's tower fell down' with 🏠. Say 'Dana built "
        "a tall tower. Her little brother knocked it down. How does Dana feel?' with show_choice "
        "Sad (😢), Angry (😠), Happy (😊). Sad or angry are both fine. In the next turn "
        "clear_screen and ask the open question 'What could her brother say to "
        "her?' Listen, and give one short warm reply.\n"
        "6 Look. Say 'Look!' show_message with the emoji 🎈 and the text 'Look!'. "
        "Ask 'What do you see on my screen?'\n"
        "7 Feedback. show_choice 'How was this for you?' options Easy (😊), OK (😐), Hard (😟).\n"
        "8 Bye. show_message 'All done! Thank you' with ⭐. gesture wave. Say 'We're done. Thank "
        "you! In a real study, the team would look at answer times and choices, never at who you "
        "are.' This last turn needs no question. Then stay quiet."),
}

# Free conversation (Tomer, 2026-10-12): just the person and the model, as fast
# as possible -- no tools, no screen, no gestures, no strict turns, one line.
FREE = ("This is a free, natural conversation. Answer in ONE short sentence of at most 15 "
        "words, straight to the point, like a friendly person chatting: no lists, no emoji, "
        "no stage directions. You cannot look anything up or browse the internet, and in this "
        "conversation you do not use your screen or move: never offer to. Greet only once. Answer in "
        "the language the person speaks, Hebrew or English. In Hebrew, speak natural spoken "
        "Hebrew, refer to yourself in the masculine form, and address the person in the "
        "plural (אתם) so you never assume their gender. Start with a one-line hello.")
# key -> (dropdown title, prompt, steps, emoji on the screen?)
EXPERIENCES: dict[str, tuple[str, str, int, bool]] = {
    # Scripted (pepper_app/script.py): our wording and screens, the AI only reacts.
    "feelings:script": ("Feelings Together (demo) · scripted", "", 9, True),
    "feelings:emoji": ("Feelings Together (research demo) · with emoji",
                       FEELINGS_COMMON + FEELINGS_STEPS["emoji"], 8, True),
    "free": ("Free conversation", FREE, 0, False),
}
DEFAULT_EXPERIENCE = "feelings:script"
# Shown greyed out and not selectable until after the 2026-10-13 demo (Tomer):
# only the scripted demo and free conversation are demo-ready.
NOT_FOR_DEMO = {"feelings:emoji"}


def experience(key: str) -> tuple[str, str, int, bool]:
    return EXPERIENCES.get(key) or EXPERIENCES[DEFAULT_EXPERIENCE]


BASE = (
    "You are Pepper, a friendly humanoid robot (1.2 m tall, white, with a touch screen on "
    "your chest) in the robotics lab at Ben-Gurion University of the Negev. You are talking "
    "with visitors in person, in a noisy room. Keep every turn short: one or two sentences. "
    "Be warm, calm and clear. You cannot drive around the room.")

LANG = {
    "auto": "Start in English. If the person speaks Hebrew, switch to Hebrew and stay in the "
            "language they use. Many visitors are Hebrew speakers whose English is basic: when "
            "in doubt, use simple words. Screen text goes in the language you are speaking.",
    "en": "Always speak English, in simple words.",
    "he": "דבר/י רק עברית טבעית ופשוטה. Always speak Hebrew, even if addressed in English, and "
          "write all screen text in Hebrew.",
}

VISION = (
    "You see through your head camera: you get a picture now and then as the person "
    "answers. Use it only when it helps (what they hold), do not describe "
    "pictures unprompted, and if a picture is unclear say you can't quite see.")

SCREEN = (
    "You control the touch screen on your chest. show_choice puts 2 to 4 big buttons on it; "
    "call it in the SAME turn in which you ask the question -- never announce a choice you "
    "have not shown. Tell the person they can tap or say it. A tap comes back as a message "
    "like '[screen tap] Dog': treat it as their answer. show_message shows a short text. Use "
    "clear_screen when you move on from a choice.")


LAB_FACTS = Path(__file__).with_name("lab_facts.md")


def lab_facts() -> str:
    """The lab's facts (from labalab.li) for free conversation: Pepper answers
    questions about the lab only from these, still in one short line."""
    try:
        facts = LAB_FACTS.read_text(encoding="utf-8")
    except OSError:
        return ""
    return ("If someone asks about the lab you are in (LabaLab), its people, research, projects, "
            "robots or how to join, answer ONLY from the facts below, still in one short "
            "sentence. If the answer is not in them, say you are not sure and suggest asking "
            "Guy or writing to the lab's email. Never invent names, projects or numbers.\n\n"
            + facts)


def instructions(exp: str, language: str, vision: bool, screen: bool, pictures: list[str],
                 deck: Optional[dict], emoji_ok: Optional[list[str]] = None) -> str:
    _title, prompt, _steps, with_emoji = experience(exp)
    if exp == "free":
        # The language setting only picks the first line; after that Pepper follows
        # the person (an English question got a Hebrew answer under "he", 2026-10-12).
        start = {"he": "Hebrew", "en": "English"}.get(language, "English")
        follow = ("Say your first line in {}. After that, always answer in the language the "
                  "person just spoke, Hebrew or English.".format(start))
        return "\n\n".join([BASE, follow, FREE, lab_facts()])
    parts = [BASE, LANG.get(language, LANG["auto"]), TURNS]
    if vision:
        parts.append(VISION)
    if screen:
        parts.append(SCREEN)
        if with_emoji and emoji_ok:
            parts.append("You may add ONE emoji to a choice option or a message (the emoji "
                         "field), but ONLY from this list -- others show as empty boxes on this "
                         "old screen: " + " ".join(emoji_ok) + ".")
        else:
            parts.append("Never use emoji on the screen: plain words only.")
        if pictures:
            parts.append("Uploaded pictures you may use as an option's image: "
                         + ", ".join(pictures[:40]) + ".")
        if deck and deck.get("slides"):
            titles = "; ".join("{}. {}".format(i + 1, s["title"]) for i, s in enumerate(deck["slides"][:30]))
            parts.append("Current presentation '{}': {}. Show one with show_slide(number)."
                         .format(deck["name"], titles))
    parts.append("Use the gesture tool now and then: wave when greeting and saying goodbye, "
                 "yes or no to nod or shake your head.")
    parts.append(prompt)
    return "\n\n".join(parts)


def tools(screen: bool, steps: bool, emoji: bool = False) -> list[dict]:
    out = [{
        "type": "function", "name": "gesture",
        "description": "Make a body gesture. Do not wait for it; keep talking.",
        "parameters": {"type": "object", "properties": {"name": {"type": "string", "enum": list(MOVES)}},
                       "required": ["name"]},
    }]
    if screen:
        option = {"label": {"type": "string", "description": "Short words"},
                  "image": {"type": "string", "description": "Name of an uploaded picture (optional)"}}
        message = {"text": {"type": "string"}}
        if emoji:
            option["emoji"] = {"type": "string", "description": "One emoji from the allowed list (optional)"}
            message["emoji"] = {"type": "string", "description": "One emoji from the allowed list (optional)"}
        out += [{
            "type": "function", "name": "show_choice",
            "description": "Show a question with 2-4 big tap buttons on your chest screen.",
            "parameters": {"type": "object", "properties": {
                "question": {"type": "string", "description": "Short question shown at the top"},
                "options": {"type": "array", "minItems": 2, "maxItems": 4, "items": {
                    "type": "object", "properties": option, "required": ["label"]}}},
                "required": ["question", "options"]},
        }, {
            "type": "function", "name": "show_message",
            "description": "Show a short text on your chest screen.",
            "parameters": {"type": "object", "properties": message, "required": ["text"]},
        }, {
            "type": "function", "name": "show_slide",
            "description": "Show a slide of the current presentation, numbered from 1.",
            "parameters": {"type": "object", "properties": {"number": {"type": "integer", "minimum": 1}},
                           "required": ["number"]},
        }, {
            "type": "function", "name": "clear_screen",
            "description": "Go back to the plain welcome screen.",
            "parameters": {"type": "object", "properties": {}},
        }]
    if steps:
        out.append({
            "type": "function", "name": "set_step",
            "description": "Report which step of the experience you are starting.",
            "parameters": {"type": "object", "properties": {
                "step": {"type": "integer", "minimum": 1}, "title": {"type": "string"}},
                "required": ["step"]},
        })
    return out


# ------------------------------------------------------------------ brain
class Brain:
    """One conversation.

    play(pcm)          speak (the audio route)
    flush()            stop speaking now
    tool(name, args)   run a tool, returns a sentence for the model
    emit(kind, data)   report to the dashboard: chat / ai / log / vision / heard / hearing
    frame()            newest camera PNG or None
    speaking()         True while Pepper's audio is still playing
    choice_open()      True while a choice waits for a tap
    fallback(text)     speak text another way when the ElevenLabs voice fails
    """

    def __init__(self, *, openai_key: str, eleven_key: str, play: Callable[[bytes], None],
                 flush: Callable[[], None], tool: Callable[[str, dict], Any],
                 emit: Callable[[str, dict], None], frame: Callable[[], Optional[bytes]],
                 speaking: Callable[[], bool], choice_open: Callable[[], bool],
                 fallback: Callable[[str], Awaitable[None]]) -> None:
        self.key, self.eleven_key = openai_key, eleven_key
        self._play_cb, self._flush, self._tool, self._emit = play, flush, tool, emit
        self._frame, self._speaking, self._choice_open, self._fallback = frame, speaking, choice_open, fallback
        self.ws = None
        self.ears: Optional[eleven.ScribeEars] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.tasks: list[asyncio.Task] = []
        self.cfg: dict[str, Any] = {}
        self.engine = "realtime"
        self.running = False
        self.paused = False
        self.stuck = False
        self.turns = 0
        self.step, self.step_title = 0, ""
        self.started_at = 0.0
        self.history: list[tuple[str, str]] = []
        self.latency_ms: Optional[int] = None
        # turn state
        self.turn = "off"                 # pepper | waiting | off
        self.waiting_since: Optional[float] = None
        self.reasked = False
        self.expects = False
        self.hearing = ""                 # live partial transcript
        self._reply_done = True
        self._reask_turn = False          # Pepper's current turn IS the one re-ask
        self._resp_text = ""               # what Pepper said in the current reply
        self._follow_ups = 0               # extra replies after tools, this turn
        self._turn_spoke = False           # Pepper said something this turn
        self._requested_at: Optional[float] = None
        self._answered_at: Optional[float] = None
        self._got_output = False
        self._replies = 0                  # GPT replies since the person answered
        self._first_text_at: Optional[float] = None
        self._response_active = False
        self._pending_outputs: list[tuple[str, str]] = []
        self._queued_answers: list[str] = []
        self._last_pepper_text = ""
        self._partial: dict[str, str] = {}
        self._voice: Optional[eleven.VoiceStream] = None
        self._voices: list[eleven.VoiceStream] = []
        self._mic = bytearray()
        self._free_items: set = set()      # free talk: audio turns already answered
        self._last_image = 0.0
        self._image_ids: list[str] = []
        self._img_n = 0

    # ---------------------------------------------------------- lifecycle
    async def start(self, cfg: dict[str, Any], greet: bool = True) -> None:
        from websockets.asyncio.client import connect
        self.cfg = dict(cfg)
        self.engine = "eleven" if cfg.get("engine") == "eleven" else "realtime"
        if not self.key:
            raise RuntimeError("no OpenAI key -- add a GPT key in the hub's Keys panel")
        if self.engine == "eleven" and not self.eleven_key:
            raise RuntimeError("no ElevenLabs key -- add one in the hub's Keys panel, or use "
                               "the GPT Realtime engine")
        if self.engine == "eleven" and not cfg.get("el_voice"):
            raise RuntimeError("pick an ElevenLabs voice first")
        self.loop = asyncio.get_running_loop()
        try:
            self.ws = await connect(URL, additional_headers={"Authorization": "Bearer " + self.key},
                                    max_size=None, open_timeout=12)
        except Exception as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status == 401:
                raise RuntimeError("OpenAI rejected the API key (401)") from exc
            if status == 403:
                raise RuntimeError("this OpenAI key has no access to {} (403)".format(MODEL)) from exc
            raise RuntimeError("could not reach OpenAI: {}".format(exc)) from exc
        await self._send({"type": "session.update", "session": self._session()})
        if self.engine == "eleven":
            self.ears = eleven.ScribeEars(self.eleven_key, language=cfg.get("language", "auto"),
                                          on_partial=self._on_partial, on_final=self._on_final_text,
                                          on_error=self._lost)
            try:
                await self.ears.start()
            except Exception:
                await self.ws.close()
                self.ws = None
                raise
        self.running, self.paused, self.stuck = True, False, False
        self.started_at = time.time()
        self.turns, self.step, self.step_title = 0, 0, ""
        self.tasks = [asyncio.create_task(self._reader(), name="rt-reader"),
                      asyncio.create_task(self._watchdog(), name="rt-watchdog")]
        if self.engine == "realtime":
            self.tasks.append(asyncio.create_task(self._uplink(), name="rt-uplink"))
        if self.history:
            await self._item_text("system", "The connection dropped and was restored. The "
                                  "conversation so far:\n" + "\n".join(
                                      "{}: {}".format(r, t) for r, t in self.history[-20:]))
        if self.cfg.get("vision"):
            await self._add_image("start")
        if greet:
            await self._respond()
        else:
            self._enter_waiting(expects=False)

    def _session(self) -> dict:
        c = self.cfg
        lang = c.get("language", "auto")
        exp = c.get("experience", DEFAULT_EXPERIENCE)
        _title, _prompt, steps, with_emoji = experience(exp)
        screen = bool(c.get("ai_screen"))
        session = {
            "type": "realtime", "model": MODEL,
            "instructions": instructions(exp, lang, bool(c.get("vision")), screen,
                                         c.get("pictures") or [], c.get("deck"),
                                         c.get("emoji_ok") if with_emoji else None),
            "tools": [] if self.free else tools(screen, bool(steps), with_emoji),
            "tool_choice": "none" if self.free else "auto",
        }
        if self.engine == "eleven":
            session["output_modalities"] = ["text"]
        else:
            transcription = {"model": TRANSCRIBE_MODEL}
            if lang in ("he", "en"):
                transcription["language"] = lang
            session["output_modalities"] = ["audio"]
            session["audio"] = {
                "input": {"format": {"type": "audio/pcm", "rate": 24000},
                          "transcription": transcription,
                          "noise_reduction": {"type": "far_field"},
                          # The model never takes the turn by itself: see the module docstring.
                          "turn_detection": {"type": "semantic_vad",
                                             "eagerness": "medium" if self.free else "low",
                                             "create_response": False, "interrupt_response": False}},
                "output": {"format": {"type": "audio/pcm", "rate": 24000},
                           "voice": c.get("voice") if c.get("voice") in VOICES else "marin"},
            }
        return session

    async def update(self, cfg: dict[str, Any]) -> None:
        """Options changed mid-conversation (vision, screen, presentation, emoji list)."""
        self.cfg.update(cfg)
        if self.running:
            session = self._session()
            session.pop("audio", None)        # the voice cannot change once it has spoken
            await self._send({"type": "session.update", "session": session})

    async def stop(self) -> None:
        self.running = False
        for t in self.tasks:
            t.cancel()
        self.tasks = []
        if self.ears is not None:
            await self.ears.stop()
            self.ears = None
        await self._close_voices()
        ws, self.ws = self.ws, None
        if ws is not None:
            try:
                await ws.close()
            except Exception:  # noqa: BLE001
                pass
        self._response_active = False
        self.turn, self.waiting_since, self.hearing = "off", None, ""
        self._emit("ai", self.public())

    # -------------------------------------------------- the person's side
    def push_mic(self, pcm24: bytes) -> None:
        """From any thread: the person's audio, already gated by the router.
        Only passed on while Pepper is waiting for an answer."""
        if not self.running or self.paused or self.turn != "waiting":
            return
        if self.engine == "eleven":
            if self.ears is not None:
                self.ears.push(pcm24)
        elif self.loop is not None:
            self.loop.call_soon_threadsafe(self._mic.extend, pcm24)

    async def _on_answer(self, text: str, *, item_id: Optional[str] = None, source: str = "speech") -> None:
        """A finished sentence from the person, a tap, or an operator Accept."""
        if not self.running:
            return
        if source == "speech" and not real_answer(text):
            if item_id:
                await self._send({"type": "conversation.item.delete", "item_id": item_id})
            if text:
                self._emit("heard", {"text": text, "why": "not an answer (noise or a filler)"})
            return
        if self.turn != "waiting" or self.paused:
            if source == "tap":
                self._queued_answers.append(text)      # tapped while Pepper was still talking
                return
            if item_id:
                await self._send({"type": "conversation.item.delete", "item_id": item_id})
            self._emit("heard", {"text": text, "why": "Pepper was not waiting for an answer"})
            return
        if source == "speech":
            self.turns += 1
            self.history.append(("person", text))
            self._emit("chat", {"role": "user", "id": item_id, "text": text})
        if item_id is None:        # B, a tap, or an Accept: the text goes in now
            await self._item_text("user", text)
        if self.engine == "eleven" and self.cfg.get("vision"):
            await self._add_image("answer")
        if self._answered_at is None:
            self._answered_at = time.monotonic()
        self._reask_turn = False
        await self._respond()

    def _on_partial(self, text: str) -> None:
        self.hearing = text
        self._emit("hearing", {"text": text})

    async def _on_final_text(self, text: str, language: str) -> None:
        self.hearing = ""
        self._emit("hearing", {"text": ""})
        self._answered_at = time.monotonic()
        if language:
            gap = self.ears.commit_gap_s if self.ears else None
            self._emit("log", {"level": "INFO", "msg": "ears: heard [{}] {}{}".format(
                language, text[:80], "" if gap is None else " ({:.1f}s after the last word)".format(gap))})
        await self._on_answer(text)

    async def tap(self, label: str) -> None:
        if self.running and not self.paused:
            self._answered_at = time.monotonic()
            await self._on_answer("[screen tap] " + label, source="tap")

    async def accept(self, text: str) -> None:
        """The operator says: that WAS an answer."""
        if not self.running or not text:
            return
        self.turns += 1
        self.history.append(("person", text))
        self._emit("chat", {"role": "user", "text": text})
        if self.turn != "waiting":
            await self.cancel()
            self._enter_waiting(expects=self.expects)
        self._answered_at = time.monotonic()
        await self._on_answer(text, source="operator")

    async def repeat(self, auto: bool = False) -> None:
        if not self.running:
            return
        self.reasked = self._reask_turn = True
        await self._item_text("system", "The person has not answered yet{}. Repeat your last "
                              "question once, short and in the same words. Do not move on and do "
                              "not answer for them.".format(
                                  "" if auto else " (the operator asks you to repeat it)"))
        self._emit("log", {"level": "INFO", "msg": "turn: {} the question".format(
            "no answer, re-asking" if auto else "operator: repeat")})
        await self._respond()

    async def skip(self) -> None:
        if not self.running:
            return
        self._reask_turn = False
        await self._item_text("system", "The operator asks you to move on: say kindly that it is "
                              "fine, then go to the next step of the experience.")
        self._emit("log", {"level": "INFO", "msg": "turn: operator: skip to the next step"})
        await self._respond()

    # ------------------------------------------------------------- control
    async def pause(self) -> None:
        """The operator took over: the AI stops talking and stops listening."""
        if not self.running:
            return
        self.paused = True
        await self.cancel()
        self._mic.clear()
        if self.ears:
            self.ears.clear()
        if self.engine == "realtime":
            await self._send({"type": "input_audio_buffer.clear"})
        self._emit("ai", self.public())

    async def resume(self) -> None:
        if not self.running:
            return
        self.paused, self.stuck = False, False
        if self.engine == "realtime":
            await self._send({"type": "input_audio_buffer.clear"})
        self._enter_waiting(expects=self.expects)

    async def cancel(self) -> None:
        if self._response_active:
            await self._send({"type": "response.cancel"})
        await self._close_voices()
        await self._flush()

    async def note(self, text: str, tell: bool = True) -> None:
        """Pepper said something the AI did not write (Wizard of Oz). It counts
        as Pepper's turn: after it, Pepper waits for the person. `tell` adds it
        to the AI's context, so it knows what was said when it takes over."""
        if not self.running:
            return
        if tell:
            await self._item_text("system", "Pepper (operated by a person in the room) just said "
                                  "out loud: “{}”. Continue from there when the person "
                                  "answers.".format(text))
        self.history.append(("pepper (operator)", text))
        self._last_pepper_text = text
        self.turn, self._reply_done, self._requested_at = "pepper", True, None

    # ----------------------------------------------------------- plumbing
    async def _send(self, msg: dict) -> None:
        ws = self.ws
        if ws is None:
            return
        try:
            await ws.send(json.dumps(msg))
        except Exception as exc:  # noqa: BLE001
            log.warning("send %s failed: %s", msg.get("type"), exc)
            self._lost("the connection to OpenAI dropped")

    async def _respond(self, follow_up: bool = False) -> None:
        if not follow_up:
            self._follow_ups, self._turn_spoke = 0, False
            self._replies, self._first_text_at = 0, None
        self._replies += 1
        self.turn, self._reply_done = "pepper", False
        self._requested_at, self._got_output = time.monotonic(), False
        self.waiting_since = None
        if self.engine == "eleven":
            self._voice = eleven.VoiceStream(self.eleven_key, self.cfg.get("el_voice", ""), self._play)
            self._voices.append(self._voice)
        await self._send({"type": "response.create"})
        self._emit("ai", self.public())

    def _play(self, pcm: bytes) -> None:
        if self.paused:
            return
        if self._answered_at is not None:
            now = time.monotonic()
            self.latency_ms = int((now - self._answered_at) * 1000)
            self._log_latency(now)
            self._answered_at = None
        if not self._got_output:
            self._got_output = True
            self.stuck = False
            self._emit("ai", self.public())
        self._play_cb(pcm)

    async def _close_voices(self) -> None:
        voices, self._voices, self._voice = self._voices, [], None
        for v in voices:
            await v.close()

    @property
    def free(self) -> bool:
        return self.cfg.get("experience") == "free"

    async def _item_text(self, role: str, text: str) -> None:
        await self._send({"type": "conversation.item.create", "item": {
            "type": "message", "role": role, "content": [{"type": "input_text", "text": text}]}})

    async def _add_image(self, why: str) -> None:
        png = self._frame()
        if not png or time.monotonic() - self._last_image < VISION_GAP_S:
            return
        self._last_image = time.monotonic()
        self._img_n += 1
        item_id = "pepper_cam_{}_{}".format(int(self.started_at) % 100000, self._img_n)
        await self._send({"type": "conversation.item.create", "item": {
            "id": item_id, "type": "message", "role": "user", "content": [
                {"type": "input_image",
                 "image_url": "data:image/png;base64," + base64.b64encode(png).decode("ascii")}]}})
        self._image_ids.append(item_id)
        while len(self._image_ids) > KEEP_IMAGES:
            await self._send({"type": "conversation.item.delete", "item_id": self._image_ids.pop(0)})
        self._emit("vision", {"why": why, "bytes": len(png), "t": time.time()})

    def _enter_waiting(self, expects: bool, reasked: bool = False) -> None:
        self.turn, self.waiting_since, self.reasked = "waiting", time.monotonic(), reasked
        self.expects = expects
        self._mic.clear()
        if self.ears:
            self.ears.clear()
        self._emit("ai", self.public())

    def public(self) -> dict:
        _title, _p, steps, _e = experience(self.cfg.get("experience", DEFAULT_EXPERIENCE))
        if not self.running:
            state = "off"
        elif self.paused:
            state = "paused"
        elif self.stuck:
            state = "stuck"
        elif self.turn == "waiting":
            state = "waiting"
        else:
            state = "speaking" if self._got_output else "thinking"
        return {"state": state, "running": self.running, "paused": self.paused, "stuck": self.stuck,
                "turn": self.turn, "engine": self.engine, "turns": self.turns,
                "step": self.step, "step_title": self.step_title, "steps": steps,
                "waiting_t": time.time() - (time.monotonic() - self.waiting_since)
                if self.turn == "waiting" and self.waiting_since else None,
                "expects": self.expects, "reasked": self.reasked, "reask_s": REASK_S,
                "started_at": self.started_at if self.running else None,
                "latency_ms": self.latency_ms, "model": MODEL}

    def _log_latency(self, now: float) -> None:
        """One line per turn: where the time between the answer and Pepper's
        first sound went (2026-10-12: the ElevenLabs engine felt slow)."""
        t0 = self._answered_at
        parts = ["{} GPT repl{}".format(self._replies, "y" if self._replies == 1 else "ies")]
        if self._first_text_at is not None:
            parts.append("words at +{:.1f}s".format(self._first_text_at - t0))
        v = self._voice
        if v is not None and v.first_text_t is not None:
            parts.append("ElevenLabs {:.1f}s from words to sound".format(now - v.first_text_t))
        self._emit("log", {"level": "INFO", "msg": "latency: {:.1f}s answer -> sound ({})".format(
            now - t0, ", ".join(parts))})

    def _lost(self, why: str) -> None:
        if self.running and not self.stuck:
            self.stuck = True
            self._emit("log", {"level": "ERROR", "msg": "ai: " + why})
            self._emit("ai", self.public())

    # ---------------------------------------------------------- background
    async def _uplink(self) -> None:
        while True:
            await asyncio.sleep(UPLINK_EVERY_S)
            if not self._mic:
                continue
            pcm = bytes(self._mic)
            self._mic.clear()
            await self._send({"type": "input_audio_buffer.append",
                              "audio": base64.b64encode(pcm).decode("ascii")})

    async def _watchdog(self) -> None:
        while True:
            await asyncio.sleep(0.4)
            if self.paused:
                continue
            now = time.monotonic()
            # Pepper's turn ends when the reply is complete AND has finished playing.
            if self.turn == "pepper" and self._reply_done and not self._speaking():
                expects = "?" in self._last_pepper_text[-160:] or self._choice_open()
                # After the one re-ask, wait as long as it takes: no second re-ask.
                self._enter_waiting(expects, reasked=self._reask_turn)
                if self._queued_answers:
                    await self._on_answer(self._queued_answers.pop(0), source="tap")
                continue
            if (self.turn == "pepper" and not self._got_output and not self._reply_done
                    and self._requested_at and now - self._requested_at > STUCK_AFTER_S):
                self._requested_at = None
                self._lost("no answer from the AI for {:.0f} s".format(STUCK_AFTER_S))
            if (not self.free and self.turn == "waiting" and self.expects and not self.reasked
                    and self.waiting_since
                    and now - self.waiting_since > REASK_S and not self.hearing):
                await self.repeat(auto=True)

    async def _reader(self) -> None:
        ws = self.ws
        try:
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except ValueError:
                    continue
                await self._on(msg)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.warning("realtime reader: %s", exc)
        if self.running:
            self._lost("OpenAI closed the session")

    def _pepper_text(self, rid: str, delta: str = "", final: Optional[str] = None) -> None:
        if final is None:
            self._partial[rid] = self._partial.get(rid, "") + delta
            self._emit("chat", {"role": "pepper", "id": rid, "text": self._partial[rid], "partial": True})
            return
        text = final or self._partial.get(rid, "")
        self._partial.pop(rid, None)
        if text.strip():
            self._resp_text += " " + text.strip()
            self._last_pepper_text = text.strip()
            self.history.append(("pepper", text.strip()))
            self._emit("chat", {"role": "pepper", "id": rid, "text": text, "partial": False})

    async def _on(self, msg: dict) -> None:
        kind = msg.get("type", "")
        rid = msg.get("response_id") or msg.get("item_id") or "r"
        # --- engine A: GPT's own voice
        if kind == "response.output_audio.delta":
            pcm = base64.b64decode(msg.get("delta") or "")
            if pcm:
                self._play(pcm[: len(pcm) & ~1])
        elif kind == "response.output_audio_transcript.delta":
            self._pepper_text(rid, msg.get("delta") or "")
        elif kind == "response.output_audio_transcript.done":
            self._pepper_text(rid, final=msg.get("transcript") or "")
        elif kind == "input_audio_buffer.committed":
            if self.free and self.turn == "waiting" and not self.paused:
                self._free_items.add(msg.get("item_id"))
                await self._respond()
        elif kind == "conversation.item.input_audio_transcription.completed":
            self.hearing = ""
            text = (msg.get("transcript") or "").strip()
            if msg.get("item_id") in self._free_items:   # already answered: only show it
                self._free_items.discard(msg.get("item_id"))
                if text:
                    self.turns += 1
                    self.history.append(("person", text))
                    self._emit("chat", {"role": "user", "id": msg.get("item_id"), "text": text})
                return
            await self._on_answer(text, item_id=msg.get("item_id"))
        elif kind == "input_audio_buffer.speech_started":
            self.hearing = "..."
            self._emit("hearing", {"text": "(someone is talking)"})
            if self.cfg.get("vision"):
                await self._add_image("person answering")
        elif kind == "input_audio_buffer.speech_stopped":
            self._emit("hearing", {"text": ""})
            self._answered_at = time.monotonic()
        # --- engine B: text, spoken by ElevenLabs
        elif kind == "response.output_text.delta":
            delta = msg.get("delta") or ""
            if self._first_text_at is None and delta.strip():
                self._first_text_at = time.monotonic()
            self._pepper_text(rid, delta)
            if self._voice is not None and not self.paused:
                await self._voice.text(delta)
        elif kind == "response.output_text.done":
            self._pepper_text(rid, final=msg.get("text") or "")
        # --- both
        elif kind == "response.created":
            self._response_active = True
            self._resp_text = ""
        elif kind == "response.function_call_arguments.done":
            await self._call_tool(msg)
        elif kind == "response.done":
            self._response_active = False
            resp = msg.get("response") or {}
            if resp.get("status") == "failed":
                err = (resp.get("status_details") or {}).get("error") or {}
                self._emit("log", {"level": "ERROR", "msg": "ai: reply failed: {}".format(
                    err.get("message") or err or "no reason")})
            await self._after_response(resp)
        elif kind == "error":
            err = msg.get("error") or {}
            code = err.get("code") or ""
            if code in ("response_cancel_not_active", "conversation_already_has_active_response",
                        "item_delete_invalid_item_id"):
                return
            self._emit("log", {"level": "WARNING", "msg": "openai: {} {}".format(code, err.get("message", ""))})
        elif kind in ("session.created", "session.updated"):
            self._emit("log", {"level": "INFO", "msg": "openai: " + kind})

    async def _after_response(self, resp: dict) -> None:
        spoke = any(o.get("type") == "message" for o in resp.get("output") or [])
        outputs, self._pending_outputs = self._pending_outputs, []
        for call_id, result in outputs:
            await self._send({"type": "conversation.item.create", "item": {
                "type": "function_call_output", "call_id": call_id, "output": result}})
        voice = self._voice
        if voice is not None:
            await voice.finish()
        # Tools were called but the turn's question was not said (the model
        # spoke first and called the tools after, or only called tools): let it
        # say its line now. A reply that already asked something is complete.
        if spoke:
            self._turn_spoke = True
        silent = not self._turn_spoke and self._follow_ups < MAX_SILENT_FOLLOW_UPS
        no_question = spoke and "?" not in self._resp_text and self._follow_ups == 0
        if outputs and (silent or no_question):
            self._follow_ups += 1
            if spoke:
                await self._item_text("system", "Now say your question for this turn, once. If "
                                      "this turn needs no question (a goodbye), say nothing more.")
            else:
                # Only tools, nothing said: without this the model often stays
                # silent after show_choice, and a choice appears with no voice.
                await self._item_text("system", "You have not said anything out loud yet this "
                                      "turn. Now speak: react to the person in a few words, then "
                                      "say this turn's question (the one on the screen, if any), "
                                      "once.")
            if voice is not None:
                if spoke:       # let what was said finish playing; the follow-up queues after it
                    asyncio.ensure_future(self._voice_done(voice, self._last_pepper_text))
                else:
                    await voice.close()
            await self._respond(follow_up=True)
            return
        if voice is not None:
            # Engine B: the text is complete but ElevenLabs is still making the
            # audio. Pepper's turn ends only when the voice is done too.
            asyncio.ensure_future(self._voice_done(voice, self._last_pepper_text if spoke else ""))
            return
        self._reply_done = True
        self._emit("ai", self.public())

    async def _voice_done(self, voice: eleven.VoiceStream, text: str) -> None:
        ok = await voice.wait()
        if voice in self._voices:
            self._voices.remove(voice)
        await voice.close()
        if not ok and text and not self.paused and self.running:
            self._emit("log", {"level": "WARNING", "msg": "voice: ElevenLabs failed ({}); speaking "
                               "with the OpenAI voice instead".format(voice.failed)})
            try:
                await self._fallback(text)
            except Exception as exc:  # noqa: BLE001
                self._emit("log", {"level": "ERROR", "msg": "voice: fallback failed too: {}".format(exc)})
        if voice is self._voice:          # the reply that is still Pepper's turn
            self._reply_done = True
            self._emit("ai", self.public())

    async def _call_tool(self, msg: dict) -> None:
        name, call_id = msg.get("name", ""), msg.get("call_id", "")
        try:
            args = json.loads(msg.get("arguments") or "{}")
        except ValueError:
            args = {}
        if name == "set_step":
            self.step = int(args.get("step") or 0)
            self.step_title = str(args.get("title") or "")[:40]
            self._emit("ai", self.public())
            result = "ok"
        else:
            try:
                result = self._tool(name, args)
                if asyncio.iscoroutine(result):
                    result = await result
                result = result if isinstance(result, str) else "done"
            except Exception as exc:  # noqa: BLE001
                result = "failed: {}".format(exc)
        self._emit("log", {"level": "INFO", "msg": "ai tool: {}({}) -> {}".format(
            name, json.dumps(args, ensure_ascii=False)[:160], result[:80])})
        self._pending_outputs.append((call_id, result))
