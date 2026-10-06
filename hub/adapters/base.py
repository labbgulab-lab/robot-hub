"""The contract every robot implements.

Nothing robot-specific leaks past this file into the hub core (PLAN.md 5.1).

Three rules the adapters below are built around, each measured on hardware:
  * identity is never an IP (2.2) -- stable_key() returns unit_id / MAC / serial
  * status endpoints lie (2.3)    -- probe() trusts only the signals in the plan
  * nothing blocks the loop (2.4) -- every method is async with its own timeout
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Optional, TypedDict


# --- Launch steps that must not outlive a cancelled Launch -------------------
# Disconnect cancels a Launch in flight (hub/core.py). Cancelling the await is
# not enough on its own: a child process keeps running, and a thread cannot be
# stopped at all. 2026-10-05: a Disconnect killed a half-started robot app.

async def communicate_or_kill(proc: Any, timeout_s: float,
                              stdin: Optional[bytes] = None) -> tuple[bytes, bytes]:
    """proc.communicate(), but the child dies with the Launch.

    On a timeout or a cancel the child is killed before the exception goes
    on; before, only a timeout killed it, so a cancelled reachy_chat sync or
    deploy_nao.py ran on after Disconnect.
    """
    try:
        return await asyncio.wait_for(proc.communicate(stdin), timeout_s)
    except BaseException:
        if proc.returncode is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
        raise


async def thread_finishing_on_cancel(func: Callable[..., Any], *args: Any,
                                     timeout_s: float) -> Any:
    """asyncio.to_thread with a bound, where a cancel waits for the thread.

    A blocking SSH call cannot be interrupted. If the Launch were let go at
    once, Disconnect would clear the robot first and the start command, still
    in its thread, would start the app after it. Waiting (up to `timeout_s`)
    keeps the order: the command lands, then Disconnect clears it.
    """
    future = asyncio.ensure_future(asyncio.to_thread(func, *args))
    try:
        return await asyncio.wait_for(asyncio.shield(future), timeout_s)
    except asyncio.CancelledError:
        await asyncio.wait({future}, timeout=timeout_s)
        raise


class Health(TypedDict):
    online: bool           # green
    degraded: bool         # amber - a leading indicator tripped
    detail: str            # human sentence for the card
    battery: Optional[int]  # percent, None if the robot cannot report one


ClaimKind = Literal["audio_in", "audio_out", "port", "exclusive"]
ClaimMode = Literal["require", "require_absent"]


class Claim(TypedDict):
    kind: ClaimKind
    value: str             # device name, port number, or resource name
    mode: ClaimMode


class Notes(list):
    """An adapter's human sentences. Once the hub attaches a `sink`, each one
    is logged the moment it is written -- "syncing reachy_chat onto the robot"
    used to appear only after the sync had finished (2026-10-05)."""

    sink: Optional[Callable[[str], None]] = None

    def append(self, text: str) -> None:  # type: ignore[override]
        if self.sink is not None:
            self.sink(text)
        else:
            super().append(text)


@dataclass
class Found:
    """What a detector learned about a robot. Everything here is discovered
    at runtime -- no detector is ever pre-loaded with this lab's values."""

    type_id: str                              # "reachy_wireless" | ...
    address: str                              # host or ip; NOT an identity
    port: Optional[int] = None
    meta: dict[str, Any] = field(default_factory=dict)  # mDNS TXT, USB ids, ...

    def txt(self, key: str, default: Any = None) -> Any:
        return self.meta.get(key, default)


class AdapterUnavailable(RuntimeError):
    """Raised when this robot's local prerequisite is missing (SDK, app, path).

    Costs nothing (13.6): the card is disabled with `str(exc)` as the reason,
    the hub keeps running, no traceback reaches the user.
    """


class PostureRefused(RuntimeError):
    """A posture command the robot was never asked to perform -- a joint too
    hot, an unknown name. `str(exc)` is the sentence shown on the card."""


class RobotAdapter(ABC):
    """One instance per discovered robot."""

    type_id: str = ""            # "reachy_lite" | "reachy_wireless" | "furhat" | "naoqi"
    display_name: str = ""
    reports_battery: bool = False  # only NAO; never render an empty gauge (9.3)
    # Named operator postures ("sit", "lie", "stand"); empty = no buttons.
    postures: tuple[str, ...] = ()

    def __init__(self, found: Found, config: Any) -> None:
        self.found = found
        self.config = config
        self.notes: Notes = Notes()  # human sentences surfaced on the card

    # identity ---------------------------------------------------------
    @abstractmethod
    def stable_key(self, found: Found) -> str:
        """unit_id / MAC / USB serial. NEVER an IP (2.2)."""

    # lifecycle --------------------------------------------------------
    @abstractmethod
    async def probe(self, found: Found) -> Health:
        """Cheap, repeated liveness check. Must respect the lies in 2.3."""

    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Must be idempotent -- calling it twice is not an error."""

    @abstractmethod
    async def announce(self, text: str) -> None:
        """Speak out loud. MUST actually produce sound.

        Failure here does not fail the connection (8); it raises, and the
        caller downgrades the card to "connected, but could not speak".
        """

    # its own system ---------------------------------------------------
    @abstractmethod
    def claims(self) -> list[Claim]:
        """Resources this robot's *system* needs when launched (7)."""

    @abstractmethod
    async def ensure_zero_instances(self) -> list[str]:
        """Verify -- do not merely signal -- that nothing of this robot's
        system is already running. Returns human-readable notes."""

    @abstractmethod
    async def launch(self) -> str:
        """Start this robot's own system. Returns the URL to open in a tab."""

    # optional ---------------------------------------------------------
    async def system_status(self) -> dict[str, Any]:
        """Extra detail for the card (daemon version, mic, ...). Never fatal."""
        return {}

    async def posture(self, name: str) -> str:
        """Move to one of `postures`; returns a sentence for the card."""
        raise PostureRefused("{} has no posture controls".format(
            self.display_name or self.type_id))
