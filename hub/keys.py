"""The speaking keys: stored here, on the laptop, and nowhere else.

Keys are added, removed and assigned to a robot here, then *sent* at launch,
never kept on a robot. So this file is the only place a secret lives. The page
only ever sees a key's label and its last four characters (`public()`).

Stored in `<data>/keys.local.json` (git-ignored, like `.env`):

    {"keys":   [{"id": "k1", "provider": "gemini", "label": "Lab Gemini", "key": "...",
                 "status": {"state": "works", "detail": "...", "credit": null,
                            "checked_at": 1730800000.0}}],
     "assign": {"<robot key>": "k1",                          # main slot only
                "<pepper key>": {"main": "k2", "voice": "k3"}}}

A robot has up to two slots (STUDENT-APP-PLAN 3, 5):
  main   the key it talks through (Reachy: Gemini or GPT; Pepper: GPT; Furhat)
  voice  an ElevenLabs key for its voice (Pepper)
An assignment with only a main slot is still written as a plain string, so
an older hub reading the file keeps working. A robot with no assignment uses
the first working key of the provider its type defaults to (Pepper: GPT,
never "the first Gemini key").
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import tempfile
import time
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("hub.keys")

PROVIDERS = ("gemini", "gpt", "elevenlabs", "openrouter", "qwen")
PROVIDER_LABELS = {"gemini": "Gemini", "gpt": "GPT", "elevenlabs": "ElevenLabs",
                   "qwen": "Qwen", "openrouter": "OpenRouter"}
# Names a request may use for a provider.
PROVIDER_ALIASES = {"openai": "gpt", "chatgpt": "gpt", "google": "gemini",
                    "eleven": "elevenlabs", "11labs": "elevenlabs",
                    "dashscope": "qwen"}
DEFAULT_PROVIDER = "gemini"

# The hub's provider name -> reachy_chat's `--provider`. None means the robot
# cannot be *launched* on it: reachy_chat has no Qwen or OpenRouter backend,
# and ElevenLabs is a voice layered over a brain, not a brain (2026-10-05).
SPEECH_BACKEND = {"gemini": "gemini", "gpt": "gpt_live", "elevenlabs": None,
                  "qwen": None, "openrouter": None}
# Which of those hold a conversation on their own today.
SPEAKS_TODAY = {"gemini", "gpt"}
# ElevenLabs is only ever a voice; OpenRouter only drives group conversations.
VOICE_ONLY = {"elevenlabs"}
GROUPS_ONLY = {"openrouter"}

# The environment variable each provider's key travels in at launch. Launch
# exports one key per provider, so every option on a robot's own picker has one.
PROVIDER_ENV = {"gemini": "GEMINI_API_KEY", "gpt": "OPENAI_API_KEY",
                "elevenlabs": "ELEVENLABS_API_KEY", "openrouter": "OPENROUTER_API_KEY"}

# Per robot type: slot -> providers the slot takes (None = any; a key the
# robot cannot launch on is refused at Launch with a sentence, as before), and
# the provider order its default comes from.
SLOTS = ("main", "voice")
ROBOT_SLOTS: dict[str, dict[str, Optional[tuple[str, ...]]]] = {
    "reachy_wireless": {"main": None},
    "pepper": {"main": ("gpt",), "voice": ("elevenlabs",)},
    "furhat": {"main": ("gpt", "gemini", "openrouter")},
}
ANY_ROBOT_SLOTS: dict[str, Optional[tuple[str, ...]]] = {"main": None,
                                                         "voice": ("elevenlabs",)}
DEFAULT_ORDER = {
    ("reachy_wireless", "main"): ("gemini", "gpt"),
    ("pepper", "main"): ("gpt",),
    ("pepper", "voice"): ("elevenlabs",),
    ("furhat", "main"): ("gpt",),
    (None, "main"): ("gemini",),
    (None, "voice"): ("elevenlabs",),
}
# A key in one of these states is passed over when choosing a default.
UNUSABLE = {"bad", "no_credit"}

KEYS_FILE = "keys.local.json"


class KeyError_(ValueError):
    """A key operation the user asked for cannot be done; str() says why and
    `code` is the friendly-error code (BUILD-PLAN API contract)."""

    def __init__(self, message: str, code: str = "BAD_KEY", **extra: Any) -> None:
        super().__init__(message)
        self.code = code
        self.extra = extra


def tail(key: str) -> str:
    return key[-4:] if len(key) >= 4 else "?"


def normalize_provider(provider: Optional[str]) -> str:
    p = (provider or "").strip().lower()
    return PROVIDER_ALIASES.get(p, p)


def unknown_status() -> dict[str, Any]:
    return {"state": "unknown", "detail": "", "credit": None, "checked_at": None}


class KeyStore:
    def __init__(self, path: Path, seed_gemini_file: Optional[Path] = None) -> None:
        self.path = path
        self._keys: list[dict[str, Any]] = []
        self._assign: dict[str, dict[str, str]] = {}
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
        for entry in self._keys:
            entry["provider"] = normalize_provider(entry.get("provider")) or DEFAULT_PROVIDER
            entry.setdefault("label", "{} key".format(
                PROVIDER_LABELS.get(entry["provider"], entry["provider"])))
        self._assign = {}
        for robot, value in (data.get("assign") or {}).items():
            if isinstance(value, str) and value:            # today's files
                self._assign[str(robot)] = {"main": value}
            elif isinstance(value, dict):
                slots = {s: str(v) for s, v in value.items() if s in SLOTS and v}
                if slots:
                    self._assign[str(robot)] = slots

    def _assign_on_disk(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for robot, slots in self._assign.items():
            out[robot] = slots["main"] if set(slots) == {"main"} else dict(slots)
        return out

    def _save(self) -> None:
        # Write-then-rename, so a crash mid-write cannot lose every key.
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"keys": self._keys, "assign": self._assign_on_disk()}
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
        """Import a Gemini key file this laptop already used (tools only;
        the hub itself no longer seeds at start)."""
        try:
            key = path.read_text(encoding="utf-8").strip()
        except OSError:
            return
        if key:
            self.add("gemini", "Lab Gemini", key)
            log.info("imported the existing Gemini key from %s", path.name)

    # ----------------------------------------------------------- queries
    @staticmethod
    def providers_public() -> list[dict[str, Any]]:
        return [{"id": p, "label": PROVIDER_LABELS[p],
                 "can_talk": p in SPEAKS_TODAY, "can_speak": p in SPEAKS_TODAY,
                 "voice_only": p in VOICE_ONLY, "groups_only": p in GROUPS_ONLY}
                for p in PROVIDERS]

    def public(self, used_by: Optional[dict[str, list[str]]] = None) -> dict[str, Any]:
        """Everything the page may see. `used_by`: key id -> robot names."""
        used_by = used_by or {}
        return {
            "keys": [{**self._public(k), "used_by": list(used_by.get(k["id"], []))}
                     for k in self._keys],
            "assign": {r: dict(s) for r, s in self._assign.items()},
            "providers": self.providers_public(),
        }

    @staticmethod
    def _public(entry: dict[str, Any]) -> dict[str, Any]:
        return {"id": entry["id"], "provider": entry["provider"],
                "label": entry["label"], "tail": tail(entry["key"]),
                "status": dict(entry.get("status") or unknown_status()),
                "voice_only": entry["provider"] in VOICE_ONLY,
                "groups_only": entry["provider"] in GROUPS_ONLY}

    def public_entry(self, key_id: str) -> Optional[dict[str, Any]]:
        entry = self.get(key_id)
        return self._public(entry) if entry else None

    def get(self, key_id: Optional[str]) -> Optional[dict[str, Any]]:
        return next((k for k in self._keys if k["id"] == key_id), None)

    def all_secrets(self) -> list[dict[str, Any]]:
        """Every entry, secret included -- for the file library to refuse an
        upload that holds one of them. Never sent to the page."""
        return list(self._keys)

    def assigned(self, robot_key: str, slot: str = "main") -> Optional[str]:
        return (self._assign.get(robot_key) or {}).get(slot)

    @staticmethod
    def slots_for(type_id: Optional[str]) -> dict[str, Optional[tuple[str, ...]]]:
        return ROBOT_SLOTS.get(type_id or "", ANY_ROBOT_SLOTS)

    def _first_usable(self, providers: tuple[str, ...]) -> Optional[dict[str, Any]]:
        """The first key of the first provider that has one, skipping keys
        known to be bad or empty; a bad key only when nothing else exists."""
        for provider in providers:
            for entry in self._keys:
                if (entry["provider"] == provider
                        and (entry.get("status") or {}).get("state") not in UNUSABLE):
                    return entry
        for provider in providers:
            for entry in self._keys:
                if entry["provider"] == provider:
                    return entry
        return None

    def for_robot(self, robot_key: str, type_id: Optional[str] = None,
                  slot: str = "main") -> tuple[Optional[dict[str, Any]], str]:
        """(the key entry, a sentence on how it was chosen). Entry is None when
        the hub has no key for that slot."""
        assigned = self.assigned(robot_key, slot)
        if assigned:
            entry = self.get(assigned)
            if entry is not None:
                return entry, "assigned"
        order = DEFAULT_ORDER.get((type_id, slot)) or DEFAULT_ORDER.get((None, slot), ())
        entry = self._first_usable(order)
        if entry is not None:
            return entry, "no key assigned, using the first {} key".format(
                PROVIDER_LABELS[entry["provider"]])
        return None, "no {} key in the hub".format(
            " or ".join(PROVIDER_LABELS[p] for p in order) or "matching")

    def env_for_robot(self, robot_key: str, type_id: Optional[str] = None) -> dict[str, str]:
        """{ENV_NAME: key} for every provider the robot's app can use: the
        first usable key of each provider, then the robot's own slots on top
        (main in its provider's variable, voice in ELEVENLABS_API_KEY)."""
        out: dict[str, str] = {}
        for provider, env in PROVIDER_ENV.items():
            entry = self._first_usable((provider,))
            if entry is not None:
                out[env] = entry["key"]
        for slot in self.slots_for(type_id):
            entry, _how = self.for_robot(robot_key, type_id, slot)
            if entry is not None and entry["provider"] in PROVIDER_ENV:
                out[PROVIDER_ENV[entry["provider"]]] = entry["key"]
        return out

    def robot_public(self, robot_key: str, type_id: Optional[str] = None,
                     slot: str = "main") -> Optional[dict[str, Any]]:
        entry, how = self.for_robot(robot_key, type_id, slot)
        if entry is None:
            return None
        return {**self._public(entry), "how": how,
                "assigned": self.assigned(robot_key, slot) == entry["id"]}

    def robot_slots_public(self, robot_key: str,
                           type_id: Optional[str]) -> dict[str, Any]:
        """{slot: {key: public|None, assigned: id|None, how, providers}}."""
        out: dict[str, Any] = {}
        for slot, providers in self.slots_for(type_id).items():
            entry, how = self.for_robot(robot_key, type_id, slot)
            out[slot] = {"key": self._public(entry) if entry else None,
                         "assigned": self.assigned(robot_key, slot),
                         "how": how,
                         "providers": list(providers) if providers else list(PROVIDERS)}
        return out

    def find_secret(self, key: str) -> Optional[dict[str, Any]]:
        return next((k for k in self._keys if k["key"] == key), None)

    # ---------------------------------------------------------- mutation
    def add(self, provider: str, label: str, key: str,
            status: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        provider = normalize_provider(provider)
        if provider not in PROVIDERS:
            raise KeyError_("'{}' is not one of {}".format(
                provider, ", ".join(PROVIDER_LABELS.values())), "UNKNOWN_PROVIDER",
                candidates=list(PROVIDERS))
        key = (key or "").strip()
        if len(key) < 8:
            raise KeyError_("that does not look like an API key", "NOT_A_KEY")
        if self.find_secret(key) is not None:
            raise KeyError_("that key is already in the hub", "DUPLICATE")
        label = (label or "").strip() or self._default_label(provider)
        entry: dict[str, Any] = {"id": "k" + secrets.token_hex(4), "provider": provider,
                                 "label": label, "key": key}
        if status:
            entry["status"] = dict(status)
        self._keys.append(entry)
        self._save()
        return self._public(entry)

    def _default_label(self, provider: str) -> str:
        base = "{} key".format(PROVIDER_LABELS[provider])
        taken = {k["label"] for k in self._keys}
        if base not in taken:
            return base
        n = 2
        while "{} {}".format(base, n) in taken:
            n += 1
        return "{} {}".format(base, n)

    def set_status(self, key_id: str, status: dict[str, Any], save: bool = True) -> bool:
        """Record a check result. Returns True when the state changed."""
        entry = self.get(key_id)
        if entry is None:
            return False
        old = entry.get("status") or {}
        entry["status"] = dict(status)
        if save and status.get("state") != "checking":
            try:
                self._save()
            except OSError as exc:
                log.warning("could not save key status: %s", exc)
        return (old.get("state"), old.get("detail"), old.get("credit")) != (
            status.get("state"), status.get("detail"), status.get("credit"))

    def due_for_check(self, max_age_s: float, now: Optional[float] = None) -> list[str]:
        now = time.time() if now is None else now
        out = []
        for entry in self._keys:
            st = entry.get("status") or {}
            when = st.get("checked_at")
            if st.get("state") == "checking":
                continue
            if not when or now - float(when) >= max_age_s or st.get("state") in ("offline", "unknown"):
                out.append(entry["id"])
        return out

    def remove(self, key_id: str) -> None:
        if self.get(key_id) is None:
            raise KeyError_("no key with id {}".format(key_id), "UNKNOWN_KEY")
        self._keys = [k for k in self._keys if k["id"] != key_id]
        # A robot assigned a deleted key falls back to the default.
        cleaned: dict[str, dict[str, str]] = {}
        for robot, slots in self._assign.items():
            kept = {s: k for s, k in slots.items() if k != key_id}
            if kept:
                cleaned[robot] = kept
        self._assign = cleaned
        self._save()

    def assign(self, robot_key: str, key_id: Optional[str], slot: str = "main",
               type_id: Optional[str] = None) -> None:
        slot = (slot or "main").strip().lower()
        allowed = self.slots_for(type_id)
        if slot not in allowed:
            raise KeyError_("this robot has no {} key".format(slot), "BAD_SLOT")
        slots = dict(self._assign.get(robot_key) or {})
        if not key_id:
            slots.pop(slot, None)
        else:
            entry = self.get(key_id)
            if entry is None:
                raise KeyError_("no key with id {}".format(key_id), "UNKNOWN_KEY")
            providers = allowed[slot]
            if providers and entry["provider"] not in providers:
                raise KeyError_("'{}' is a {} key; this slot takes {}".format(
                    entry["label"], PROVIDER_LABELS[entry["provider"]],
                    " or ".join(PROVIDER_LABELS[p] for p in providers)), "WRONG_PROVIDER")
            slots[slot] = key_id
        if slots:
            self._assign[robot_key] = slots
        else:
            self._assign.pop(robot_key, None)
        self._save()
