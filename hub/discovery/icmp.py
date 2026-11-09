"""One ICMP echo without starting a process, for the network sweep.

On Windows the sweep used to start `ping.exe` for every address: on HOT-WiFi
(nine /24s, ~2,300 addresses a round, a round every 5 s) that was ~100
process starts a second. asyncio starts a process *on the event loop thread*
(Popen -> CreateProcess), so each one blocks the whole hub for a moment, and
on 2026-11-09 one CreateProcess never returned: two ping.exe hung in the
network stack, the hub stopped answering, and it could not even be killed.

Here an echo is one IcmpSendEcho call (iphlpapi, no admin rights needed) on
a small pool of daemon threads. A call that hangs in Windows holds one worker
thread, never the event loop, and daemon threads never stop the hub from
quitting. Elsewhere `available()` is False and netscan keeps using `ping`.
"""

from __future__ import annotations

import asyncio
import logging
import queue
import socket
import struct
import sys
import threading
from typing import Any, Callable, Optional

log = logging.getLogger("hub.discovery.icmp")

IP_SUCCESS = 0
_REPLY_SIZE = 256      # ICMP_ECHO_REPLY (28 bytes on 32-bit, 40 on 64-bit) + data + 8
_PAYLOAD = b"robothub"

_api: Any = None
_api_error: Optional[str] = None
_local = threading.local()


def _load() -> Any:
    """The iphlpapi functions, loaded once; None when unavailable."""
    global _api, _api_error
    if _api is not None or _api_error is not None:
        return _api
    if sys.platform != "win32":
        _api_error = "not Windows"
        return None
    try:
        import ctypes
        from ctypes import wintypes
        lib = ctypes.WinDLL("iphlpapi", use_last_error=True)
        create = lib.IcmpCreateFile
        create.restype = wintypes.HANDLE
        create.argtypes = []
        send = lib.IcmpSendEcho
        send.restype = wintypes.DWORD
        send.argtypes = [wintypes.HANDLE, ctypes.c_uint32, ctypes.c_void_p, wintypes.WORD,
                         ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD]
        _api = (ctypes, create, send)
    except Exception as exc:  # noqa: BLE001
        _api_error = str(exc)
        log.info("ICMP API not available, sweep uses ping.exe: %s", exc)
    return _api


def available() -> bool:
    return _load() is not None


def echo(ip: str, timeout_ms: int = 700) -> bool:
    """True when `ip` itself answered an echo within `timeout_ms`.

    Blocking: call it from a worker thread. A router's "destination host
    unreachable" is not an answer (Status != IP_SUCCESS, or the reply comes
    from another address)."""
    api = _load()
    if api is None:
        return False
    ctypes, create, send = api
    handle = getattr(_local, "handle", None)
    if handle is None:
        handle = create()
        if not handle or handle == ctypes.c_void_p(-1).value:
            return False
        _local.handle = handle
    try:
        dest = struct.unpack("=I", socket.inet_aton(ip))[0]
    except OSError:
        return False
    data = ctypes.create_string_buffer(_PAYLOAD, len(_PAYLOAD))
    reply = ctypes.create_string_buffer(_REPLY_SIZE)
    count = send(handle, dest, data, len(_PAYLOAD), None, reply, _REPLY_SIZE, int(timeout_ms))
    if not count:
        return False
    address, status = struct.unpack_from("=II", reply.raw, 0)
    return status == IP_SUCCESS and address == dest


class DaemonPool:
    """N daemon threads running blocking calls for the event loop.

    Not concurrent.futures.ThreadPoolExecutor: its workers are joined when
    the interpreter exits, so one call stuck in Windows would keep the hub
    from quitting. A daemon thread is simply dropped."""

    def __init__(self, workers: int, name: str = "icmp") -> None:
        self._jobs: "queue.SimpleQueue[Any]" = queue.SimpleQueue()
        self._workers = workers
        self._name = name
        self._started = False
        self._lock = threading.Lock()

    def _start(self) -> None:
        with self._lock:
            if self._started:
                return
            for n in range(self._workers):
                threading.Thread(target=self._work, name="{}-{}".format(self._name, n),
                                 daemon=True).start()
            self._started = True

    def _work(self) -> None:
        while True:
            fn, args, loop, fut = self._jobs.get()
            if fut.cancelled():
                continue
            try:
                result, error = fn(*args), None
            except BaseException as exc:  # noqa: BLE001
                result, error = None, exc
            try:
                loop.call_soon_threadsafe(_settle, fut, result, error)
            except RuntimeError:       # the loop is closed: the hub is quitting
                pass

    def submit(self, fn: Callable[..., Any], *args: Any) -> "asyncio.Future[Any]":
        """A future for fn(*args), run on a pool thread."""
        self._start()
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        self._jobs.put((fn, args, loop, fut))
        return fut


def _settle(fut: "asyncio.Future[Any]", result: Any, error: Optional[BaseException]) -> None:
    if fut.done():
        return
    if error is not None:
        fut.set_exception(error)
    else:
        fut.set_result(result)
