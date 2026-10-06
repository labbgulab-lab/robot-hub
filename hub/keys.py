"""The speaking keys: stored here, on the laptop, and nowhere else.

Tomer, 2026-09-24: there will be Gemini, GPT and Qwen keys for the robots'
speech, and they are handled from the hub -- added, removed and assigned to a
robot here, then *sent* at launch, never kept on a robot. So this file is the
only place a secret lives. The page only ever sees a key's label and its last
four characters (`public()`), which is enough to tell two keys apart and not
enough to be one.

Stored in `keys.local.json` next to config.toml, which is gitignored for the
same reason `.env` is. Two things are in it:

    {"keys":   [{"id": "k1", "provider": "gemini", "label": "Lab Gemini", "key": "..."}],
     "assign": {"<robot unit_id>": "k1"}}

A robot with no assignment falls back to the first key of the default
provider, and its card says so, rather than refusing to launch at all.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import tempfile
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("hub.keys")

# What the lab has keys for. Only some have a speaking backend in reachy_chat
# today -- see SPEECH_BACKEND.
PROVIDERS = ("gemini", "gpt", "elevenlabs", "qwen")
PROVIDER_LABELS = {"gemini": "Gemini", "gpt": "GPT", "elevenlabs": "ElevenLabs",
                   "qwen": "Qwen"}
DEFAULT_PROVIDER = "gemini"

# The hub's provider name -> reachy_chat's `--provider`. None means the robot
# cannot be *launched* on it: reachy_chat has no Qwen backend, and ElevenLabs
# is a voice layered over a brain, not a brain (2026-10-05).
SPEECH_BACKEND = {"gemini": "gemini", "gpt": "gpt_live", "elevenlabs": None,
                  "qwen": None}
# Which of those actually hold a conversation today.
SPEAKS_TODAY = {"gemini", "gpt"}

# The environment variable reachy_chat reads for each provider when its
# dashboard switches backend mid-session (credentials.resolve, use_hub=False).
# Launch exports one key per provider here, so every option on the robot's
# picker has a key, not only the one the robot was launched on.
PROVIDER_ENV = {"gemini": "GEMINI_API_KEY", "gpt": "OPENAI_API_KEY",
                "elevenlabs": "ELEVENLABS_API_KEY"}

KEYS_FILE = "keys.local.json"


class KeyError_(ValueError):
    """A key operation the user asked for cannot be done; str() says why."""


def tail(key: str) -> str:
    return key[-4:] if len(key) >= 4 else "?"


class KeyStore:
    def __init__(self, path: Path, seed_gemini_file: Optional[Path] = None) -> None:
        self.path = path
        self._keys: list[dict[str, str]] = []
        self._assign: dict[str, str] = {}
        self._load()
        if not self._keys and seed_gemini_file is not None:
            self._seed(seed_gemini_file)

    # ------------------------------------------------------------ storage
    def _load(self) -> None:
        if not self.path.is_file():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            log.warning("could not read %s (%s); starting with no keys",
                        self.path.name, exc)
            return
        self._keys = [k for k in data.get("keys", [])
                      if isinstance(k, dict) and k.get("key") and k.get("id")]
        self._assign = {str(r): str(k) for r, k in (data.get("assign") or {}).items()}

    def _save(self) -> None:
        # Write-then-rename, so a crash mid-write cannot lose every key.
        data = {"keys": self._keys, "assign": self._assign}
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), prefix=".keys-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
            os.replace(tmp, self.path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def _seed(self, path: Path) -> None:
        """First run: import the Gemini key this laptop already used, so
        nothing that worked yesterday stops working today."""
        try:
            key = path.read_text(encoding="utf-8").strip()
        except OSError:
            return
        if key:
            self.add("gemini", "Lab Gemini", key)
            log.info("imported the existing Gemini key from %s", path.name)

    # ----------------------------------------------------------- queries
    def public(self) -> dict[str, Any]:
        """Everything the page may see."""
        return {
            "keys": [self._public(k) for k in self._keys],
            "assign": dict(self._assign),
            "providers": [{"id": p, "label": PROVIDER_LABELS[p],
                           "can_speak": p in SPEAKS_TODAY}
                          for p in PROVIDERS],
        }

    @staticmethod
    def _public(entry: dict[str, str]) -> dict[str, Any]:
        return {"id": entry["id"], "provider": entry["provider"],
                "label": entry["label"], "tail": tail(entry["key"])}

    def get(self, key_id: str) -> Optional[dict[str, str]]:
        return next((k for k in self._keys if k["id"] == key_id), None)

    def all_secrets(self) -> list[dict[str, str]]:
        """Every entry, secret included -- for the file library to refuse an
        upload that holds one of them. Never sent to the page."""
        return list(self._keys)

    def for_robot(self, robot_key: str) -> tuple[Optional[dict[str, str]], str]:
        """(the key entry, a sentence on how it was chosen). Entry is None when
        the hub has no key at all."""
        assigned = self._assign.get(robot_key)
        if assigned:
            entry = self.get(assigned)
            if entry is not None:
                return entry, "assigned"
        entry = next((k for k in self._keys if k["provider"] == DEFAULT_PROVIDER), None)
        if entry is not None:
            return entry, "no key assigned, using the first {} key".format(
                PROVIDER_LABELS[DEFAULT_PROVIDER])
        return None, "no {} key in the hub".format(PROVIDER_LABELS[DEFAULT_PROVIDER])

    def env_for_robot(self, robot_key: str) -> dict[str, str]:
        """{ENV_NAME: key} for every provider the robot's app can use: the
        robot's assigned key for its own provider, the first key of each
        other provider."""
        out: dict[str, str] = {}
        for entry in self._keys:
            env = PROVIDER_ENV.get(entry["provider"])
            if env and env not in out:
                out[env] = entry["key"]
        assigned, _ = self.for_robot(robot_key)
        if assigned is not None and assigned["provider"] in PROVIDER_ENV:
            out[PROVIDER_ENV[assigned["provider"]]] = assigned["key"]
        return out

    def robot_public(self, robot_key: str) -> Optional[dict[str, Any]]:
        entry, how = self.for_robot(robot_key)
        if entry is None:
            return None
        return {**self._public(entry), "how": how,
                "assigned": self._assign.get(robot_key) == entry["id"]}

    # ---------------------------------------------------------- mutation
    def add(self, provider: str, label: str, key: str) -> dict[str, Any]:
        provider = (provider or "").strip().lower()
        if provider not in PROVIDERS:
            raise KeyError_("'{}' is not one of {}".format(
                provider, ", ".join(PROVIDER_LABELS.values())))
        key = (key or "").strip()
        if len(key) < 8:
            raise KeyError_("that does not look like an API key")
        if any(k["key"] == key for k in self._keys):
            raise KeyError_("that key is already in the hub")
        label = (label or "").strip() or "{} key".format(PROVIDER_LABELS[provider])
        entry = {"id": "k" + secrets.token_hex(4), "provider": provider,
                 "label": label, "key": key}
        self._keys.append(entry)
        self._save()
        return self._public(entry)

    def remove(self, key_id: str) -> None:
        if self.get(key_id) is None:
            raise KeyError_("no key with id {}".format(key_id))
        self._keys = [k for k in self._keys if k["id"] != key_id]
        # A robot assigned a deleted key falls back to the default.
        self._assign = {r: k for r, k in self._assign.items() if k != key_id}
        self._save()

    def assign(self, robot_key: str, key_id: Optional[str]) -> None:
        if not key_id:
            self._assign.pop(robot_key, None)
        elif self.get(key_id) is None:
            raise KeyError_("no key with id {}".format(key_id))
        else:
            self._assign[robot_key] = key_id
        self._save()
