"""hub/discovery/icmp.py: echoes without ping.exe, on threads that cannot
freeze the event loop or keep the hub from quitting (2026-11-09 hang)."""

from __future__ import annotations

import asyncio
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hub.discovery import icmp  # noqa: E402
from hub.discovery import netscan  # noqa: E402

windows = pytest.mark.skipif(sys.platform != "win32", reason="IcmpSendEcho is Windows only")


@windows
def test_echo_answers_for_this_laptop_and_not_for_a_silent_address():
    assert icmp.available()
    assert icmp.echo("127.0.0.1", 700) is True
    # TEST-NET-1 (RFC 5737): never routed, never answers.
    t = time.monotonic()
    assert icmp.echo("192.0.2.1", 300) is False
    assert time.monotonic() - t < 2.0
    assert icmp.echo("not an address") is False


def test_a_stuck_call_never_blocks_the_loop():
    release = threading.Event()

    def stuck():
        release.wait(5)
        return True

    async def main():
        pool = icmp.DaemonPool(1, name="test-stuck")
        t = time.monotonic()
        lag = []

        async def tick():
            for _ in range(10):
                s = time.monotonic()
                await asyncio.sleep(0.01)
                lag.append(time.monotonic() - s)
        ticker = asyncio.create_task(tick())
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(pool.submit(stuck), 0.2)
        # The single worker is still stuck; a job queued behind it times out too.
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(pool.submit(lambda: True), 0.1)
        await ticker
        release.set()
        return time.monotonic() - t, max(lag)

    took, worst_lag = asyncio.run(main())
    assert took < 1.0
    assert worst_lag < 0.2


def test_results_and_errors_come_back():
    async def main():
        pool = icmp.DaemonPool(2, name="test-ok")
        ok = await pool.submit(lambda a, b: a + b, 2, 3)
        with pytest.raises(ValueError):
            await pool.submit(lambda: (_ for _ in ()).throw(ValueError("x")))
        return ok
    assert asyncio.run(main()) == 5


def test_a_stuck_worker_does_not_stop_python_from_exiting(tmp_path):
    script = tmp_path / "quit.py"
    script.write_text(textwrap.dedent("""
        import asyncio, sys, threading
        sys.path.insert(0, {root!r})
        from hub.discovery import icmp
        async def main():
            pool = icmp.DaemonPool(1)
            try:
                await asyncio.wait_for(pool.submit(threading.Event().wait), 0.1)
            except asyncio.TimeoutError:
                pass
        asyncio.run(main())
        print("bye")
    """).format(root=str(Path(__file__).resolve().parents[1])))
    done = subprocess.run([sys.executable, str(script)], capture_output=True,
                          text=True, timeout=20)
    assert done.returncode == 0 and "bye" in done.stdout


@windows
def test_netscan_ping_uses_icmp_not_a_process(monkeypatch):
    def no_process(*a, **k):
        raise AssertionError("ping.exe was started")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", no_process)
    det = netscan.NetscanDetector.__new__(netscan.NetscanDetector)

    async def main():
        det._sem = asyncio.Semaphore(4)
        return await det._ping("127.0.0.1"), await det._ping("192.0.2.1")
    assert asyncio.run(main()) == (True, False)
