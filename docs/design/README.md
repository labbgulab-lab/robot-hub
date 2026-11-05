# Design reference

The "Robot Hub student app" design canvas, copied here so builders have it next to the code.

- `*.dc.html`: one file per board (design-canvas format: `<x-dc>`, `{{holes}}`, `sc-if`/`sc-for`, a DCLogic class). Read them for exact markup, copy and states.
- `renders/*.png`: each board rendered as a picture.
- `builder/*.py`: the scripts that generated the boards. `builder/build_hub.py` holds the shared CSS (tokens, buttons, cards, pills, sheets); `build_ra.py` adds reachy_app's CSS (`RA_CSS`); `build_pepper.py` adds Pepper's (`P_CSS`). Reuse that CSS rather than inventing new styles.
- `tokens.json`: the LabaLab Robot Hub design-system tokens.
- `canvas.json`: board titles and order.

Board map: hub 1-16 (Install, Main, KeyLater, Hub, RobotPanel, RobotPanel2, Network, Logs, Settings, Files, Setup, Hotspot, CardStates, NoRobots, AppStates, FlowStates); reachy_app 1-9 (RATalk, RATable, RATableLive, RADialogs, RAShow, RATalkStates, RATableStates, RAMoreTable, RAMoreTalk); Pepper 1-3 (PepperDash, PepperStates, PepperSim). "Table" in file names is the Group tab.
