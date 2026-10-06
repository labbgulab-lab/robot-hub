"""Detectors. Three mechanisms cover four robots (PLAN.md 2.1).

Every detector is *type*-based: it knows what a Furhat looks like, never what
*this lab's* Furhat looks like. Identity is learned at discovery time and used
as the card key thereafter (12).

The contract `manager.DiscoveryManager` must satisfy:

    mgr = DiscoveryManager(config, bus, on_found, on_lost, on_network)
    await mgr.start()          # returns once detectors are running
    await mgr.stop()           # idempotent; cancels every task cleanly
    mgr.snapshot() -> dict[str, Found]

    on_found(found: Found)     # called on first sight AND on address change
    on_lost(type_id, key)      # called after discovery.lost_after_s of silence
    on_network(info: dict)     # {"on_robot_subnet": bool, "interfaces": [...]}

Callbacks are plain sync functions -- they must not block. They are invoked
from the event loop thread; anything slow belongs on a task.
"""
