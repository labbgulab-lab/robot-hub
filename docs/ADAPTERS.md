# Adding a robot

Everything robot-specific lives behind one interface. Nothing else in the hub
needs to change.

## 1. Write the adapter

Create `hub/adapters/<robot>.py` with a class implementing
`hub.adapters.base.RobotAdapter`, then register it in
`hub/adapters/__init__.py`:

```python
_MODULES["my_robot"] = ("my_robot", "MyRobotAdapter")
KNOWN_TYPES = (..., "my_robot")
DISPLAY_NAMES["my_robot"] = "My Robot"
```

The import is guarded, so a broken or dependency-missing adapter disables one
card and leaves the hub running.

### The methods

| Method | Contract |
|---|---|
| `stable_key(found)` | `unit_id` / MAC / USB serial. **Never an IP.** |
| `probe(found)` | Cheap, repeated, ≤ a few seconds. Returns `Health`. |
| `connect()` / `disconnect()` | Session lifecycle. `disconnect` is idempotent. |
| `announce(text)` | Speak out loud. Must *actually* make sound. |
| `claims()` | What this robot's system takes when launched. |
| `ensure_zero_instances()` | **Verify** nothing is already running. Returns notes. |
| `launch()` | Start the system, return the URL to open. |
| `system_status()` | Optional extras for the card. Never fatal. |

### Four rules that are not style preferences

1. **Never block the event loop.** Robot latency here is jittery — 8 ms to
   457 ms on the same robot, same session. Everything is `async` with a
   timeout; blocking SDK work goes to a thread or a subprocess.
2. **Identity is never an IP.** Two different robots held `172.20.10.10`
   within one hour of each other.
3. **Assume status endpoints lie until you have measured them.** One robot
   here returns `{"status": "ok"}` while unplugged.
4. **A robot nobody owns must cost nothing.** Import optional dependencies
   lazily; raise `AdapterUnavailable("install X")` rather than a traceback.

## 2. Add a detector, if it needs one

`hub/discovery/` holds three, and they are *type*-based — they know what a
class of robot looks like, never what this lab's particular robot looks like.
Identity is learned at discovery time.

If your robot advertises mDNS, add its service type to `mdns.py`. If it needs
something else, write a module that calls `on_found(Found(...))` and
`on_lost(type_id, key)` and register it in `manager.py`.

## 3. Declare what it fights over

`claims()` is how robots avoid each other.

```python
Claim(kind="audio_in",  value="", mode="require")          # "" = resolve the
                                                           # current default
Claim(kind="exclusive", value="some_app", mode="require_absent")
```

Leave `value` empty for audio to have the broker resolve the concrete device
name at launch time. That resolution is the whole point: a claim on the string
`"default"` collides silently, a claim on
`"Microphone (USBAudio1.0)"` collides visibly.

## 4. Tell `doctor.py` what to check for

Add a check to `hub/doctor.py` for each local prerequisite, with the **exact**
remedy. Someone cloning this repo with only your robot should be able to run
`python -m hub.doctor` and be told precisely what to install.

## 5. Write the profile

Measure it, do not assume it. Put what you find in `docs/profiles/<robot>.md`,
especially anything that surprised you — that file is what stops the next
person re-learning it.
