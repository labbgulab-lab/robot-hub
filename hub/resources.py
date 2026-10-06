"""Audio-device and exclusive-resource arbitration (PLAN.md 7).

The danger is not "two systems want a microphone". It is that NAO_LLM calls
`sd.InputStream(...)` with no `device=`, so it grabs whatever Windows
currently calls default -- which may be the K11 that Reachy is already
listening through. The failure looks exactly like a broken microphone, and
that class of failure has already cost a demo.

So claims are resolved to *concrete device names* at launch time, never to
the string "default". That is what makes the collision visible instead of
silent. On conflict the launch is refused, naming the holder, with an
override the user can press.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Iterable, Optional

from .adapters.base import Claim
from .config import Config
from .events import EventBus
from .ports import PortAllocator

log = logging.getLogger("hub.resources")

DEFAULT_SENTINELS = ("", "default", "Default", "@default", None)


class ConflictError(RuntimeError):
    def __init__(self, message: str, resource: str) -> None:
        super().__init__(message)
        self.resource = resource


@dataclass
class Holding:
    resource: str          # "audio_in:Microphone (USBAudio1.0)"
    owner_key: str
    owner_name: str
    mode: str              # "require" | "require_absent"


def default_input_device_name() -> Optional[str]:
    """The concrete name Windows currently means by 'default input'.

    Resolved here so that NAO's device-less capture becomes a named claim.
    Returns None when sounddevice is unavailable -- a hub on a machine with
    no audio stack must still run (13.6).
    """
    try:
        import sounddevice as sd  # imported lazily: optional dependency
    except Exception as exc:  # noqa: BLE001
        log.info("sounddevice unavailable (%s); audio arbitration is name-only", exc)
        return None
    try:
        index = sd.default.device[0]
        if index is None or index < 0:
            return None
        return str(sd.query_devices(index)["name"])
    except Exception as exc:  # noqa: BLE001
        log.warning("could not resolve the default input device: %s", exc)
        return None


def default_output_device_name() -> Optional[str]:
    try:
        import sounddevice as sd
    except Exception:  # noqa: BLE001
        return None
    try:
        index = sd.default.device[1]
        if index is None or index < 0:
            return None
        return str(sd.query_devices(index)["name"])
    except Exception:  # noqa: BLE001
        return None


class ResourceBroker:
    def __init__(self, bus: EventBus, config: Config) -> None:
        self.bus = bus
        self.config = config
        # The same allocator the adapters fall back to when the hub injects
        # none. Two independent allocators would each believe a port was free
        # and hand out the same one -- a collision with no error anywhere.
        from .supervisor import shared_port_allocator
        self.ports: PortAllocator = shared_port_allocator(config)
        self._held: dict[str, Holding] = {}       # resource -> holding
        self._by_owner: dict[str, list[str]] = {}

    # ------------------------------------------------------------ resolving
    def resolve(self, claim: Claim) -> str:
        kind, value = claim["kind"], claim.get("value", "")
        if kind == "audio_in" and value in DEFAULT_SENTINELS:
            value = default_input_device_name() or "the Windows default input device"
        elif kind == "audio_out" and value in DEFAULT_SENTINELS:
            value = default_output_device_name() or "the Windows default output device"
        return "{}:{}".format(kind, value)

    # ------------------------------------------------------------ acquiring
    def check(self, owner_key: str, claims: Iterable[Claim]) -> list[tuple[str, str]]:
        """Returns (resource, human sentence) per conflict. Empty = clear."""
        problems: list[tuple[str, str]] = []
        for claim in claims:
            resource = self.resolve(claim)
            mode = claim.get("mode", "require")
            holding = self._held.get(resource)
            if holding is None or holding.owner_key == owner_key:
                continue
            problems.append((resource, self._sentence(resource, mode, holding)))
        return problems

    def acquire(self, owner_key: str, owner_name: str,
                claims: Iterable[Claim], override: bool = False) -> None:
        claims = list(claims)
        problems = self.check(owner_key, claims)
        if problems and not override:
            resource, message = problems[0]
            raise ConflictError(message, resource)
        for _, message in problems:
            self.bus.emit_log("warn", "OVERRIDE: {}".format(message))

        for claim in claims:
            resource = self.resolve(claim)
            if claim.get("mode") == "require_absent":
                # Nothing to hold -- this claim asserts an absence. Record it
                # so a later `require` on the same resource is refused too.
                self._record(resource, owner_key, owner_name, "require_absent")
                continue
            self._record(resource, owner_key, owner_name, "require")

    def _record(self, resource: str, key: str, name: str, mode: str) -> None:
        self._held[resource] = Holding(resource, key, name, mode)
        self._by_owner.setdefault(key, [])
        if resource not in self._by_owner[key]:
            self._by_owner[key].append(resource)

    def _sentence(self, resource: str, mode: str, holding: Holding) -> str:
        kind, _, value = resource.partition(":")
        if kind == "exclusive" and mode == "require_absent":
            body = ("{} must not be running, but {} needs it."
                    .format(value, holding.owner_name))
        elif kind == "exclusive":
            body = "{} is claimed by {}.".format(value, holding.owner_name)
        elif kind.startswith("audio"):
            body = ("{} is in use by {}. Stop that first, or override."
                    .format(value, holding.owner_name))
        else:
            body = "{} is held by {}.".format(value, holding.owner_name)
        return "Cannot start: {}".format(body)

    # ------------------------------------------------------------ releasing
    def release_all(self, owner_key: str) -> None:
        for resource in self._by_owner.pop(owner_key, []):
            holding = self._held.get(resource)
            if holding and holding.owner_key == owner_key:
                self._held.pop(resource, None)
        self.ports.release_owner(owner_key)

    def snapshot(self) -> dict[str, Any]:
        return {
            "resources": [
                {"resource": h.resource, "owner": h.owner_name, "mode": h.mode}
                for h in self._held.values()
            ],
            "ports": self.ports.held(),
        }
