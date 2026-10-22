"""Silent dry run of the group conversation: no robots, no speaker, no mic.

    .venv\\Scripts\\python.exe tools\\group_dryrun.py [--robots 5] [--plan full]

Written 2026-10-21 for a night with no robots and someone asleep in the next
room. Everything real runs (the conductor, ears with Silero, the director,
STT, TTS, interjections) except the robots, which are FakeLinks in a virtual
room:

* each fake robot "plays" its audio into the room on a real-time clock;
* each fake mic hears every robot at a per-pair coupling (its own robot loud,
  far robots quiet), plus the virtual person at a per-mic gain, plus noise,
  delivered in 32 ms blocks like the SSH mic stream;
* the virtual person speaks pre-voiced sentences on a script, some of them
  over a robot (barge-in), some in the gaps, one asking what a robot sees
  (a still picture stands in for the camera).

It prints the transcript as it happens and a summary: latencies, cut-offs,
interruptions, false barge-ins.
"""

from __future__ import annotations

import argparse
import collections
import asyncio
import json
import logging
import os
import sys
import threading
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hub.group import robots as robots_mod  # noqa: E402
from hub.group.conductor import GroupManager  # noqa: E402
from hub.group.services import openai_speech  # noqa: E402

SR = 16000
ROOM_S = 900
NOISE = 0.002
CACHE = ROOT / "cache" / "dryrun"


class Room:
    """Every sound in the virtual room on one sample clock."""

    def __init__(self) -> None:
        self.t0 = time.monotonic()
        self.tracks: dict[str, np.ndarray] = {}
        self.lock = threading.Lock()

    def n(self, t: float) -> int:
        return int((t - self.t0) * SR)

    def track(self, name: str) -> np.ndarray:
        with self.lock:
            if name not in self.tracks:
                self.tracks[name] = np.zeros(SR * ROOM_S, dtype=np.float32)
            return self.tracks[name]

    def put(self, name: str, start_t: float, samples: np.ndarray) -> None:
        tr = self.track(name)
        a = max(0, self.n(start_t))
        b = min(tr.size, a + samples.size)
        if b > a:
            tr[a:b] += samples[: b - a]

    def silence(self, name: str, from_t: float) -> None:
        tr = self.track(name)
        a = max(0, self.n(from_t))
        tr[a:] = 0.0

    def active(self, name: str, t: float, window: float = 0.2) -> bool:
        tr = self.tracks.get(name)
        if tr is None:
            return False
        a = max(0, self.n(t - window))
        return bool(np.any(np.abs(tr[a:self.n(t)]) > 0.01))


ROOM: Room
COUPLING: dict[tuple[str, str], float] = {}
PERSON_GAIN: dict[str, float] = {}
MOTIONS: list[tuple[float, str, dict]] = []
VERBOSE = os.environ.get("DRYRUN_VERBOSE") == "1"
T0 = time.monotonic()


class FakeLink(robots_mod._Link):
    """RobotLink's interface over the virtual room."""

    LAT = 0.35

    def __init__(self, key: str, name: str, host: str = "", user: str = "",
                 password: str = "", *, listen: bool = True) -> None:
        super().__init__(key, name, listen)
        self._open = False
        self._thread = None
        self.mic_source = "fake"

    @property
    def connected(self) -> bool:
        return self._open

    def _latency_s(self) -> float:
        return self.LAT

    async def open(self) -> None:
        await asyncio.sleep(0.3)
        self._open = True
        if self.listen:
            self._thread = threading.Thread(target=self._mic, daemon=True)
            self._thread.start()

    def _mic(self) -> None:
        n = ROOM.n(time.monotonic())
        rng = np.random.default_rng(abs(hash(self.key)) % 2**32)
        while self._open:
            now_n = ROOM.n(time.monotonic() - 0.06)       # the stream's own lag
            while n + 512 <= now_n:
                block = rng.normal(0, NOISE, 512).astype(np.float32)
                for name, tr in list(ROOM.tracks.items()):
                    g = PERSON_GAIN.get(self.key, 0.2) if name == "person" else COUPLING.get(
                        (self.key, name), 0.05)
                    block += g * tr[n:n + 512]
                pcm = np.clip(block * 32768, -32768, 32767).astype(np.int16)
                self._deliver_mic(pcm)
                n += 512
            time.sleep(0.01)

    async def close(self) -> None:
        self._open = False
        self._reset_clock()

    async def play(self, pcm: bytes) -> None:
        samples = self._samples(pcm)
        if samples.size == 0 or not self._open:
            return
        now = time.monotonic()
        start = max(now, self._play_until) + self.LAT
        ROOM.put(self.key, start, samples.astype(np.float32) / 32768.0)
        self._account(int(samples.size))

    async def end_line(self) -> None:
        self._carry = b""

    async def stop_audio(self) -> None:
        ROOM.silence(self.key, time.monotonic() + 0.1)
        self._reset_clock()

    async def motion(self, cmd: dict) -> None:
        MOTIONS.append((time.monotonic(), self.name, cmd))

    async def snapshot(self):
        path = os.environ.get("HUB_GROUP_TEST_IMAGE", "")
        return Path(path).read_bytes() if path and Path(path).is_file() else None


class FakeBus:
    def subscribe(self):
        return asyncio.Queue()

    def unsubscribe(self, q):
        pass

    def emit_log(self, level, text):
        print("   [hub log]", text)


class FakeKeys:
    def all_secrets(self):
        d = json.loads((ROOT / "keys.local.json").read_text(encoding="utf-8"))["keys"]
        return d


class FakeHub:
    def __init__(self):
        self.bus = FakeBus()
        self.keys = FakeKeys()
        self.adapters = {}
        self.registry = None


async def voice_person(http, key: str, text: str) -> np.ndarray:
    CACHE.mkdir(parents=True, exist_ok=True)
    import hashlib
    path = CACHE / (hashlib.sha1(text.encode()).hexdigest()[:16] + ".pcm")
    for attempt in range(3):
        if path.is_file():
            break
        chunks = []
        try:
            async for c in openai_speech(http, key, "onyx", text,
                                         "A man in his thirties talking to a group, natural pace."):
                chunks.append(c)
            path.write_bytes(b"".join(chunks))
        except Exception as exc:  # noqa: BLE001
            print("   (voicing the person failed: {}; retrying)".format(type(exc).__name__))
    return np.frombuffer(path.read_bytes(), dtype=np.int16).astype(np.float32) / 32768.0


def make_test_image() -> str:
    from PIL import Image, ImageDraw
    path = CACHE / "scene.jpg"
    CACHE.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (512, 288), (225, 230, 235))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 200, 512, 288], fill=(140, 100, 60))           # a table
    d.rectangle([180, 120, 250, 205], fill=(210, 30, 30))          # a red mug
    d.ellipse([245, 140, 275, 180], outline=(210, 30, 30), width=8)
    d.rectangle([320, 60, 420, 205], fill=(30, 90, 200))           # a blue book
    d.text((335, 120), "ROBOTS", fill=(255, 255, 255))
    img.save(path, "JPEG")
    return str(path)


def show(entry: dict) -> None:
    k = entry.get("kind")
    t = entry.get("t")
    if k == "note":
        print("  {:>6} . {}".format("" if t is None else t, entry.get("text")))
    elif k == "human":
        print("  {:>6} PEOPLE: {}".format(t, entry.get("text")))
    else:
        extra = []
        if entry.get("latency_ms") is not None:
            extra.append("{} ms".format(entry["latency_ms"]))
        if entry.get("gesture"):
            extra.append("gesture " + entry["gesture"])
        if entry.get("tone"):
            extra.append(entry["tone"])
        if entry.get("cut"):
            extra.append("CUT OFF")
        print("  {:>6} {} ({}) [{}]: {}  <{}>".format(t, entry.get("character"), entry.get("who"),
                                                     entry.get("move"), entry.get("text"),
                                                     "; ".join(extra)))


async def main() -> None:
    global ROOM
    ap = argparse.ArgumentParser()
    ap.add_argument("--robots", type=int, default=5)
    ap.add_argument("--plan", default="full", choices=("full", "group", "interrupt", "quiet"))
    ap.add_argument("--level", type=int, default=3)
    ap.add_argument("--lang", default="en")
    ap.add_argument("--model", default="google/gemini-3.5-flash")
    ap.add_argument("--voice", default="auto", choices=("auto", "openai", "gemini", "elevenlabs"))
    args = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if VERBOSE else logging.INFO, format="%(asctime)s %(name)s %(message)s",
                        filename=str(ROOT / "logs" / "group-dryrun.log"), filemode="w")

    ROOM = Room()
    robots_mod.LaptopLink = FakeLink
    keys = [("sim:{}".format(i + 1)) for i in range(args.robots)]
    for i, m in enumerate(keys):
        for j, s in enumerate(keys):
            COUPLING[(m, s)] = 0.45 if i == j else 0.18 / (abs(i - j))
        PERSON_GAIN[m] = 0.2
    PERSON_GAIN[keys[-1]] = 0.7          # the person sits by the last robot
    PERSON_GAIN[keys[-2]] = 0.45

    import hub.group.conductor as cond
    cond.SIM_KEYS = tuple(keys)
    os.environ["HUB_GROUP_TEST_IMAGE"] = make_test_image()

    hub = FakeHub()
    gm = GroupManager(hub)
    gm.cfg["seats"] = []
    gm.cfg["settings"].update({"simulate": True, "language": args.lang, "minutes": 6,
                               "topic": "Should robots be allowed to vote?",
                               "voice_provider": args.voice, "director_model": args.model,
                               "barge_in": "normal", "interrupt_level": args.level,
                               "voice_min_level": 0.2})
    gm._save = lambda: None
    gm.cfg["seats"] = [{**s, "listen": True} for s in gm.seats()]
    q = gm.subscribe()

    async def printer():
        seen = {}
        while True:
            ev = await q.get()
            if ev.get("type") == "group.turn":
                t = ev["turn"]
                sig = json.dumps(t, sort_keys=True, ensure_ascii=False)
                if seen.get(t["id"]) != sig and (t.get("kind") != "robot" or t.get("latency_ms") is not None
                                                 or t.get("cut")):
                    seen[t["id"]] = sig
                    show(t)
            elif ev.get("type") == "group.status" and VERBOSE:
                st = ev["status"]
                print("         [{:6.1f}] phase {} {} {}".format(time.monotonic() - T0, st.get("phase"),
                                                           st.get("speaker") or "", st.get("detail") or ""))
            elif ev.get("type") == "group.people" and ev.get("text"):
                print("         (live) ...{}".format(ev["text"][-90:]))

    pr = asyncio.create_task(printer())
    import httpx
    oa = gm._key("gpt")
    http = httpx.AsyncClient(timeout=60)
    say = {}
    he = args.lang == "he"
    lines = {
        "barge": "Wait, wait, can I say something? I think robots should only vote on robot things.",
        "gap": "What about you, the one on the end, do you agree with that?",
        "eyes": "Hey Tamar, what do you see on the table in front of you?",
        "mono": ("Okay listen, here is what I really think. Robots should vote, because they "
                 "pay attention to facts, they do not get tired, they read every single law "
                 "before voting, and honestly most people do not even read the ballot. So if "
                 "we let robots vote, the decisions would be smarter, faster, and cheaper for "
                 "everybody, and I am sure that in twenty years nobody will even remember "
                 "why we argued about it."),
        "short": "No, no, you are all wrong about this.",
    }
    if he:
        lines.update({
            "barge": "רגע, רגע, אפשר להגיד משהו? אני חושב שרובוטים צריכים להצביע רק על דברים של רובוטים.",
            "gap": "ומה איתך, זה שבסוף, אתה מסכים עם זה?",
            "eyes": "היי תמר, מה את רואה על השולחן מולך?",
            "mono": ("טוב תקשיבו, זה מה שאני באמת חושב. רובוטים צריכים להצביע, כי הם שמים לב "
                     "לעובדות, הם לא מתעייפים, הם קוראים כל חוק לפני שהם מצביעים, ובכנות "
                     "רוב האנשים בכלל לא קוראים את הפתק. אז אם ניתן לרובוטים להצביע, "
                     "ההחלטות יהיו חכמות יותר, מהירות יותר וזולות יותר לכולם."),
            "short": "לא, לא, כולכם טועים בזה.",
        })
    for k, text in lines.items():
        say[k] = await voice_person(http, oa, text)
        if say[k] is None or not len(say[k]):
            raise SystemExit("the virtual person has no voice for {!r} (OpenAI down and no "
                             "cached clip)".format(k))

    def person(k: str) -> float:
        audio = say[k]
        ROOM.put("person", time.monotonic(), audio)
        print("         >>> person says ({:.1f} s): {}".format(audio.size / SR, lines[k]))
        return audio.size / SR

    async def wait_robot_talking(timeout=30):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if gm.status.get("phase") == "speaking":
                await asyncio.sleep(1.2)
                return True
            await asyncio.sleep(0.05)
        return False

    async def wait_phase(phase, timeout=30):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if gm.status.get("phase") == phase:
                return True
            await asyncio.sleep(0.03)
        return False

    t_start = time.monotonic()
    if args.plan in ("full", "group", "quiet"):
        print("=== GROUP TALK ===")
        print(await gm.start("group"))
        await asyncio.sleep(30 if args.plan != "quiet" else 75)
        if args.plan != "quiet":
            await wait_robot_talking()
            await asyncio.sleep(1.0)
            d = person("barge")                     # over a robot
            await asyncio.sleep(d + 14)
            await wait_phase("listening", 40)
            person("gap")
            await asyncio.sleep(16)
            await wait_phase("listening", 40)
            person("eyes")
            await asyncio.sleep(18)
    if args.plan in ("full", "interrupt"):
        print("=== INTERRUPT MODE (level {}) ===".format(args.level))
        t_sw = time.monotonic()
        print(await gm.start("interrupt"))
        print("   switch took {:.2f} s".format(time.monotonic() - t_sw))
        await asyncio.sleep(2)
        await wait_phase("listening", 40)
        person("mono")
        await asyncio.sleep(say["mono"].size / SR + 14)
        await wait_phase("listening", 40)
        person("short")
        await asyncio.sleep(15)
        await wait_phase("listening", 40)
        gm.cfg["settings"]["interrupt_level"] = 5
        for seat in gm.cfg["seats"]:
            seat["interrupt_level"] = 5         # each robot has its own level now
        gm.apply_live()
        print("   (level -> 5)")
        person("mono")
        await asyncio.sleep(say["mono"].size / SR + 14)
    if args.plan == "full":
        print("=== SWITCH BACK TO GROUP ===")
        t_sw = time.monotonic()
        print(await gm.start("group"))
        print("   switch took {:.2f} s".format(time.monotonic() - t_sw))
        await asyncio.sleep(15)
    print("=== STOP ===")
    t_sw = time.monotonic()
    print(await gm.stop(), "stop took {:.2f} s".format(time.monotonic() - t_sw))
    echo = gm.session.ears.echo_report() if gm.session and gm.session.ears else {}
    await gm.disconnect()
    pr.cancel()
    await http.aclose()

    tr = gm.transcript
    robot = [t for t in tr if t["kind"] == "robot" and t.get("latency_ms") is not None]
    cut = [t for t in tr if t.get("cut")]
    after_people = []
    for i, t in enumerate(tr):
        if t["kind"] == "human":
            nxt = next((u for u in tr[i + 1:] if u["kind"] == "robot"), None)
            if nxt and nxt.get("latency_ms") is not None:
                after_people.append(nxt["latency_ms"])
    print("\n=== SUMMARY ({:.0f} s) ===".format(time.monotonic() - t_start))
    print("robot lines:", len(robot), " cut off by people:", len(cut))
    lat = sorted(t["latency_ms"] for t in robot)
    if lat:
        print("gap before a robot line: median {} ms, max {} ms".format(lat[len(lat) // 2], lat[-1]))
    print("robot answer after people (ms):", after_people)
    print("gestures sent:", sum(1 for _, _, c in MOTIONS if c.get("type") in ("emotion", "dance")),
          " head moves:", sum(1 for _, _, c in MOTIONS if c.get("type") == "head"),
          " back to breathing:", sum(1 for _, _, c in MOTIONS if c.get("type") == "stop"))
    per = {}
    for _, name, c in MOTIONS:
        per.setdefault(name, collections.Counter())[c.get("type")] += 1
    print("per robot:", {k: dict(v) for k, v in sorted(per.items())})
    print("echo report:", json.dumps(echo))


if __name__ == "__main__":
    asyncio.run(main())
