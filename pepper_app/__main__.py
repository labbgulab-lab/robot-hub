"""Pepper's operator dashboard.

    python -m pepper_app <pepper-ip>            # what the hub's Launch runs
    python -m pepper_app --robot ""             # no robot: the page only, for testing

Needs OPENAI_API_KEY in the environment (the hub passes its GPT key).

The dashboard listens on 127.0.0.1 only. The laptop connects OUT to the agent
on Pepper (robot port 8790), and Pepper's chest tablet loads its page from the
agent (robot port 8791), so Windows never asks about the firewall. Only when
that connect fails does Pepper connect back to port 8782 (the old way).
"""

from __future__ import annotations

import argparse
import os
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", category=DeprecationWarning, message=".*audioop.*")

DEFAULT_PORT = 8780


def default_data() -> Path:
    """The student app keeps data outside the code (ROBOT_HUB_DATA); a lab checkout keeps it here."""
    root = os.environ.get("ROBOT_HUB_DATA", "").strip()
    if root:
        return Path(root) / "pepper"
    return Path(__file__).resolve().parent / "data"


def main() -> None:
    from .robot import AGENT_PORT, BACK_PORT, TABLET_PORT

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("robot", nargs="?", default=None, help="Pepper's IP address")
    ap.add_argument("--robot", dest="robot_opt", default=None, help="same, as an option")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--host", default="127.0.0.1", help="the dashboard's address (default: this laptop only)")
    ap.add_argument("--agent-port", type=int, default=AGENT_PORT, help="the agent listens here on Pepper")
    ap.add_argument("--tablet-port", type=int, default=TABLET_PORT, help="Pepper serves the tablet page here")
    ap.add_argument("--back-port", type=int, default=BACK_PORT, help="fallback: Pepper connects back here")
    ap.add_argument("--data", default=str(default_data()))
    args = ap.parse_args()
    robot = args.robot_opt if args.robot_opt is not None else (args.robot or "")

    import uvicorn

    from .server import create_app
    app = create_app(robot.strip(), args.port, args.agent_port, Path(args.data),
                     back_port=args.back_port, tablet_port=args.tablet_port)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning", access_log=False)


if __name__ == "__main__":
    main()
