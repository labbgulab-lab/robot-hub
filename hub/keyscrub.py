"""Keep API keys out of the shared robot-file library.

A built Furhat skill carries its OpenAI key inside (OpenAiSkill's Gradle build
writes it to `furhatchat/openai.properties`), and the library is shared with
the whole lab. So every upload goes through `scrub()`:

  * In an archive (.skill / .jar / .zip), a key-named property in a
    `.properties` or `.env` entry is blanked. That spot is a *key slot*:
    `inject()` can fill it with one of this hub's own keys on download, so the
    person downloading gets a working skill with their key, not the uploader's.
  * Anything that still looks like a key afterwards -- a known pattern, or
    the exact value of a key this laptop holds -- refuses the upload, naming
    where it was found. A refusal is safer than a guess at stripping it.

Blocking (an 85 MB skill takes seconds); call it through a thread.
"""

from __future__ import annotations

import os
import re
import shutil
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

# Keys of the services the lab uses: (literal start, full pattern, what it is).
# The scan finds each literal with bytes.find and only then runs the pattern
# at that spot: one regex over the whole file took 70 s on an 85 MB skill
# (its Arabic segmenter data alone is 43 MB). A key must not continue a word,
# so "task-runner-..." is not an "sk-" key.
_PATTERNS = [
    (b"sk-", rb"sk-(?:proj-|ant-|svcacct-)?[A-Za-z0-9_-]{20,}", "an OpenAI or Anthropic key"),
    (b"AIza", rb"AIza[0-9A-Za-z_-]{35}", "a Google (Gemini) key"),
    (b"xai-", rb"xai-[A-Za-z0-9]{20,}", "an xAI (Grok) key"),
    (b"sk_", rb"sk_[0-9a-f]{40,}", "an ElevenLabs key"),
    *((p, p + rb"[A-Za-z0-9]{30,}", "a GitHub token")
      for p in (b"ghp_", b"gho_", b"ghu_", b"ghs_", b"ghr_")),
    (b"github_pat_", rb"github_pat_[A-Za-z0-9_]{40,}", "a GitHub token"),
]
_COMPILED = [(lit, re.compile(rx), what) for lit, rx, what in _PATTERNS]
_WORD = frozenset(b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789")

# A private key with its body. Checked in text and resources, not in compiled
# classes: bundled libraries carry well-known public test keys there (netty's
# OpenSsl.class in every Furhat skill), and the bare marker too (Furhat's
# TelemetryModule.class strips it off keys it loads).
_PEM_MARK = b"PRIVATE KEY-----"
_PEM_BODY = re.compile(rb"PRIVATE KEY-----(?:\s|\n)*[A-Za-z0-9+/]{40,}")

# A property whose *name* says it holds a secret.
_SECRET_NAME = re.compile(r"(?i)(api[_.-]?key|apikey|secret|token|password|passwd)")
_SLOT_FILES = (".properties", ".env")
ARCHIVES = (".skill", ".jar", ".zip")

# Which hub provider fills a slot, guessed from where the slot is.
_PROVIDER_HINTS = (("openai", "gpt"), ("gpt", "gpt"), ("gemini", "gemini"),
                   ("google", "gemini"), ("eleven", "elevenlabs"), ("qwen", "qwen"))


class KeyFound(ValueError):
    """The file still holds something that looks like a key; str() says where."""


@dataclass
class Slot:
    entry: str            # archive member, e.g. furhatchat/openai.properties
    prop: str             # property name, e.g. apiKey
    provider: str         # hub provider id that fills it, e.g. gpt

    def label(self) -> str:
        return "{}#{}".format(self.entry, self.prop)


@dataclass
class ScrubResult:
    path: Path                       # the file to upload (maybe a new copy)
    removed: list[str] = field(default_factory=list)   # "entry#prop" blanked
    slots: list[Slot] = field(default_factory=list)


def _provider_for(entry: str, prop: str) -> str:
    where = (entry + " " + prop).lower()
    for hint, provider in _PROVIDER_HINTS:
        if hint in where:
            return provider
    return "gpt"


def known_secrets(extra: Iterable[str] = ()) -> list[bytes]:
    """Exact values to refuse: this laptop's own keys. Short values (a robot's
    factory password such as "nao") would match everywhere, so they are left
    to the patterns."""
    values = set(v for v in extra if v)
    for name, value in os.environ.items():
        if _SECRET_NAME.search(name) and value:
            values.add(value)
    return [v.strip().encode() for v in values if len(v.strip()) >= 16]


def _find_key(data: bytes, secrets: list[bytes], compiled: bool = False) -> Optional[str]:
    for lit, rx, what in _COMPILED:
        i = data.find(lit)
        while i != -1:
            if (i == 0 or data[i - 1] not in _WORD) and rx.match(data, i):
                return what
            i = data.find(lit, i + 1)
    if not compiled:
        i = data.find(_PEM_MARK)
        while i != -1:
            if _PEM_BODY.match(data, i):
                return "a private key"
            i = data.find(_PEM_MARK, i + 1)
    for s in secrets:
        if s in data:
            return "one of this laptop's own keys"
    return None


def _looks_secret(name: str, value: str, secrets: list[bytes]) -> bool:
    """A value to blank. A key-shaped name alone is not enough: bundled
    libraries ship error texts named "...Password1" or "...is_token"."""
    value = value.strip()
    if not value:
        return False
    if _find_key(value.encode("utf-8", "replace"), secrets):
        return True
    return bool(_SECRET_NAME.search(name)) and len(value) >= 16 and not re.search(r"\s", value)


def _split_line(line: str) -> Optional[tuple[str, str, str]]:
    """'name = value' / 'name: value' / 'NAME=value' -> (name, separator, value)."""
    stripped = line.strip()
    if not stripped or stripped[0] in "#!":
        return None
    m = re.match(r"^(\s*(?:export\s+)?)([^=:\s]+)(\s*[=:]\s*)(.*)$", line)
    if not m:
        return None
    return m.group(2), m.group(1) + m.group(2) + m.group(3), m.group(4)


def _blank_secrets(text: str, secrets: list[bytes]) -> tuple[str, list[str]]:
    """Return the text with every secret value emptied, and their names."""
    out, names = [], []
    for line in text.splitlines(keepends=True):
        parts = _split_line(line.rstrip("\r\n"))
        if parts and _looks_secret(parts[0], parts[2], secrets):
            ending = line[len(line.rstrip("\r\n")):]
            out.append(parts[1] + ending)
            names.append(parts[0])
        else:
            out.append(line)
    return "".join(out), names


def _empty_slots(text: str) -> list[str]:
    names = []
    for line in text.splitlines():
        parts = _split_line(line)
        if parts and _SECRET_NAME.search(parts[0]) and not parts[2].strip():
            names.append(parts[0])
    return names


def _rewrite(src: Path, dst: Path, replace: dict[str, bytes]) -> None:
    """Copy an archive entry by entry, in order (a jar wants its manifest
    first), swapping the contents of the members in `replace`."""
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w", compresslevel=1) as zout:
        for info in zin.infolist():
            data = replace[info.filename] if info.filename in replace else zin.read(info)
            zout.writestr(info, data, compress_type=info.compress_type)


def scrub(path: Path, workdir: Path, secrets: Iterable[bytes] = ()) -> ScrubResult:
    """Return a keyless version of `path`, or raise KeyFound."""
    secrets = list(secrets)
    if path.suffix.lower() not in ARCHIVES or not zipfile.is_zipfile(path):
        where = _find_key(path.read_bytes(), secrets)
        if where:
            raise KeyFound("{} contains {} -- remove it and upload again".format(
                path.name, where))
        return ScrubResult(path=path)

    result = ScrubResult(path=path)
    replace: dict[str, bytes] = {}
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            data = z.read(info)
            if info.filename.lower().endswith(_SLOT_FILES):
                text = data.decode("utf-8", "replace")
                cleaned, names = _blank_secrets(text, secrets)
                if names:
                    data = cleaned.encode("utf-8")
                    replace[info.filename] = data
                    result.removed += ["{}#{}".format(info.filename, n) for n in names]
                for n in _empty_slots(cleaned if names else text):
                    result.slots.append(Slot(info.filename, n, _provider_for(info.filename, n)))
            where = _find_key(data, secrets, info.filename.endswith(".class"))
            if where:
                raise KeyFound("{} holds {} in {} -- rebuild it without the key "
                               "and upload again".format(path.name, where, info.filename))
    if replace:
        out = workdir / path.name
        _rewrite(path, out, replace)
        result.path = out
    return result


def slots(path: Path) -> list[Slot]:
    """The empty key slots of an archive -- what inject() can fill."""
    if path.suffix.lower() not in ARCHIVES or not zipfile.is_zipfile(path):
        return []
    found = []
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            if info.filename.lower().endswith(_SLOT_FILES):
                text = z.read(info).decode("utf-8", "replace")
                found += [Slot(info.filename, n, _provider_for(info.filename, n))
                          for n in _empty_slots(text)]
    return found


def inject(path: Path, dst: Path, provider: str, key: str) -> int:
    """Write `key` into every empty slot `provider` fills; return how many."""
    targets = [s for s in slots(path) if s.provider == provider]
    if not targets:
        shutil.copyfile(path, dst)
        return 0
    replace: dict[str, bytes] = {}
    with zipfile.ZipFile(path) as z:
        for entry in {s.entry for s in targets}:
            props = {s.prop for s in targets if s.entry == entry}
            lines = []
            for line in z.read(entry).decode("utf-8", "replace").splitlines(keepends=True):
                parts = _split_line(line.rstrip("\r\n"))
                if parts and parts[0] in props and not parts[2].strip():
                    ending = line[len(line.rstrip("\r\n")):]
                    line = parts[1] + key + ending
                lines.append(line)
            replace[entry] = "".join(lines).encode("utf-8")
    _rewrite(path, dst, replace)
    return len(targets)
