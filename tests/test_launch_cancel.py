"""A Launch cancelled by Disconnect must not leave work running behind it.

2026-10-05: Disconnect during a Launch killed a half-started robot app. The
hub now cancels the Launch task, and these two helpers make the cancel reach
what the task had started: a child process, and a blocking SSH thread.
"""

from __future__ import annotations

import asyncio
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hub.adapters.base import (communicate_or_kill,  # noqa: E402
                               thread_finishing_on_cancel)


def test_a_cancelled_child_is_killed():
    async def scenario():
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-c", "import time; time.sleep(60)",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        step = asyncio.create_task(communicate_or_kill(proc, 120))
        await asyncio.sleep(0.5)
        step.cancel()
        try:
            await step
        except asyncio.CancelledError:
            pass
        await asyncio.wait_for(proc.communicate(), 10)    # drains + closes the pipes
        return proc.returncode

    returncode = asyncio.run(scenario())
    assert returncode is not None          # it died; before, it ran on


def test_a_timed_out_child_is_killed_and_the_timeout_still_raised():
    async def scenario():
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-c", "import time; time.sleep(60)",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            await communicate_or_kill(proc, 0.5)
        except asyncio.TimeoutError:
            await asyncio.wait_for(proc.communicate(), 10)
            return proc.returncode
        raise AssertionError("no timeout")

    assert asyncio.run(scenario()) is not None


def test_a_cancel_waits_for_the_ssh_step_already_on_the_wire():
    # The order is the whole point: the start command lands first, then
    # Disconnect's cleanup runs -- never the other way round.
    order: list[str] = []
    entered = threading.Event()

    def start_command() -> str:
        entered.set()
        time.sleep(0.5)
        order.append("app started on the robot")
        return "started"

    async def scenario():
        step = asyncio.create_task(
            thread_finishing_on_cancel(start_command, timeout_s=10))
        while not entered.is_set():
            await asyncio.sleep(0.01)
        step.cancel()
        try:
            await step
        except asyncio.CancelledError:
            order.append("launch cancelled")
        order.append("disconnect clears the robot")

    asyncio.run(scenario())
    assert order == ["app started on the robot", "launch cancelled",
                     "disconnect clears the robot"]


def test_the_thread_helper_returns_and_times_out_like_wait_for():
    async def scenario():
        assert await thread_finishing_on_cancel(lambda: 7, timeout_s=5) == 7
        try:
            await thread_finishing_on_cancel(time.sleep, 2, timeout_s=0.2)
        except asyncio.TimeoutError:
            return True
        return False

    assert asyncio.run(scenario())
