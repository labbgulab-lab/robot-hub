#!/usr/bin/env python3
"""Render the Reachy announcement sentences to WAV (PLAN.md 8).

Furhat and NAO can be handed text: both have their own speech engine. Neither
Reachy can -- the Pollen daemon exposes no TTS endpoint anywhere in its 98
paths -- so their "I am connected and ready to run" is a real audio file that
the hub uploads to the robot. This script is what produces it.

Run it after changing `announce` in config.toml. The filename is derived from
a hash of the exact sentence (`hub/announce.py`), so an edited sentence
becomes a new file and the daemon's idempotent upload check cannot silently
reuse the previous recording.

This is a tool, not a hub dependency: nothing under `hub/` imports it, and it
is the only place a text-to-speech engine is ever required.

    python tools/make_announcement_wavs.py            # render what is missing
    python tools/make_announcement_wavs.py --force    # re-render everything
    python tools/make_announcement_wavs.py --list     # just show the plan
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Callable, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from hub.adapters import DISPLAY_NAMES                     # noqa: E402
from hub.announce import announcements_dir, wav_filename   # noqa: E402
from hub.config import load_config                         # noqa: E402

# The two robots whose daemon cannot speak for itself.
NEEDS_WAV = ("reachy_wireless", "reachy_lite")

NO_ENGINE = """\
No text-to-speech engine is available on this machine, so the recordings
cannot be generated here. Either:

  1. Install one and re-run this script:
         {python} -m pip install pyttsx3

  2. Or record each sentence yourself -- any recorder, any voice -- and save
     it under the exact filename listed above in:
         {folder}

The filename is what matters, not how the audio was made. A plain 16-bit PCM
WAV is the safe format; the daemon's accepted sample rates were never captured
on hardware."""


def _pyttsx3_renderer() -> Optional[Callable[[str, Path], None]]:
    try:
        import pyttsx3
    except Exception:  # noqa: BLE001
        return None

    def render(text: str, path: Path) -> None:
        engine = pyttsx3.init()
        engine.save_to_file(text, str(path))
        engine.runAndWait()
        engine.stop()

    return render


def _sapi_renderer() -> Optional[Callable[[str, Path], None]]:
    """Windows' own speech synthesiser, driven out of process.

    System.Speech is always present on Windows, so this is the path that needs
    no install at all. It runs in PowerShell rather than in-process because
    the hub's Python has no binding to it.

    The sentence and the destination travel in the environment rather than on
    the command line. `powershell -Command` does not populate `$args`, and a
    sentence quoted into a one-liner is at the mercy of PowerShell's parser --
    an apostrophe in an announcement would be enough to break it.
    """
    if sys.platform != "win32":
        return None

    script = (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        "$s.SetOutputToWaveFile($env:HUB_WAV_PATH); "
        "$s.Speak($env:HUB_WAV_TEXT); "
        "$s.Dispose()"
    )

    def render(text: str, path: Path) -> None:
        env = dict(os.environ, HUB_WAV_PATH=str(path), HUB_WAV_TEXT=text)
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=120, env=env)
        if result.returncode != 0 or not path.is_file():
            raise RuntimeError(
                (result.stderr or "PowerShell produced no file").strip())

    return render


def pick_renderer() -> tuple[Optional[Callable[[str, Path], None]], str]:
    renderer = _pyttsx3_renderer()
    if renderer is not None:
        return renderer, "pyttsx3"
    renderer = _sapi_renderer()
    if renderer is not None:
        return renderer, "Windows System.Speech"
    return None, ""


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true",
                        help="re-render even when the file already exists")
    parser.add_argument("--list", action="store_true",
                        help="print what would be rendered and stop")
    args = parser.parse_args(argv)

    config = load_config()
    folder = announcements_dir(config)
    folder.mkdir(parents=True, exist_ok=True)

    plan: list[tuple[str, str, Path]] = []
    for type_id in NEEDS_WAV:
        robot = config.robot(type_id)
        if not robot.enabled:
            continue
        names = [robot.display_name or DISPLAY_NAMES.get(type_id, type_id)]
        names += [u.display_name for u in robot.units.values() if u.display_name]
        for name in names:
            text = robot.announcement(name)
            plan.append((name, text, folder / wav_filename(text)))

    if not plan:
        print("No Reachy is enabled in config.toml, so there is nothing to "
              "render.")
        return 0

    for name, text, path in plan:
        state = "exists" if path.is_file() else "missing"
        print("{:<18} {:<8} {}".format(name, state, path.name))
        print("{:<18} {!r}".format("", text))
    if args.list:
        return 0

    todo = [item for item in plan if args.force or not item[2].is_file()]
    if not todo:
        print("\nEverything is already rendered. Use --force to redo it.")
        return 0

    renderer, engine = pick_renderer()
    if renderer is None:
        print("\n" + NO_ENGINE.format(python=sys.executable, folder=folder))
        return 1

    print("\nRendering {} file(s) with {}...".format(len(todo), engine))
    failures = 0
    for name, text, path in todo:
        try:
            renderer(text, path)
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print("  {}: FAILED - {}".format(name, exc))
            continue
        size = path.stat().st_size if path.is_file() else 0
        if size == 0:
            failures += 1
            print("  {}: FAILED - the engine wrote an empty file".format(name))
        else:
            print("  {}: {} ({:,} bytes)".format(name, path.name, size))

    if failures:
        print("\n{} recording(s) failed. Until they exist, those robots will "
              "connect but report 'could not speak'.".format(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
