"""Pepper's operator dashboard.

    python -m pepper_app <pepper-ip>            # what the hub's Launch runs
    python -m pepper_app --robot ""             # no robot: laptop audio only, for testing

Needs OPENAI_API_KEY in the environment (the hub passes its GPT key).
"""

from __future__ import annotations

import argparse
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", category=DeprecationWarning, message=".*audioop.*")

DEFAULT_PORT = 8780
AGENT_PORT = 8782


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("robot", nargs="?", default=None, help="Pepper's IP address")
    ap.add_argument("--robot", dest="robot_opt", default=None, help="same, as an option")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--agent-port", type=int, default=AGENT_PORT)
    ap.add_argument("--data", default=str(Path(__file__).resolve().parent / "data"))
    args = ap.parse_args()
    robot = args.robot_opt if args.robot_opt is not None else (args.robot or "")

    import uvicorn

    from .server import create_app
    app = create_app(robot.strip(), args.port, args.agent_port, Path(args.data))
    uvicorn.run(app, host="0.0.0.0", port=args.port, log_level="warning", access_log=False)


if __name__ == "__main__":
    main()
