"""Body language for the group conversation: what each robot does with its head.

The robots' player (robot_streaming_player.py) plays Pollen's recorded
emotions and dances by name. The catalog is in assets/group_moves.json (61
emotions of at most 7.5 s, a few dances), dumped from the same library the
robots load. In the single-robot chat Gemini picks these itself, in context,
and Tomer found that the best match between words and body (2026-10-21). The
group director does the same: it writes the line and picks the speaker's
gesture and a listener's reaction in the same call, so the move fits what is
said.
"""

from __future__ import annotations

import json
import random
from typing import Optional

from ..config import REPO_ROOT

CATALOG_FILE = REPO_ROOT / "assets" / "group_moves.json"


def _load() -> tuple[dict, dict]:
    try:
        data = json.loads(CATALOG_FILE.read_text(encoding="utf-8"))
        return dict(data.get("emotions") or {}), dict(data.get("dances") or {})
    except (OSError, ValueError):
        return {}, {}


EMOTIONS, DANCES = _load()

# Quiet reactions while someone else talks, by temperament. A character the
# operator renamed falls back to GENERIC.
REACTIONS = {
    "Noa": ["enthusiastic2", "yes1", "amazed1", "cheerful1", "understanding2", "surprised1"],
    "Dor": ["displeased1", "displeased2", "impatient1", "no1", "contempt1", "irritated1"],
    "Maya": ["inquiring1", "thoughtful1", "inquiring2", "uncertain1", "reprimand3", "thoughtful2"],
    "Eli": ["laughing2", "laughing1", "oops2", "indifferent1", "surprised2", "cheerful1"],
    "Tamar": ["attentive1", "understanding1", "calming1", "welcoming2", "attentive2", "loving1"],
}
GENERIC = ["attentive1", "understanding1", "inquiring2", "surprised1", "thoughtful2",
           "displeased2", "laughing2"]
# While a person talks in the interrupt mode, the stance the robots react with.
STANCE_REACTIONS = {
    "oppose": ["displeased1", "displeased2", "no1", "impatient1", "irritated1", "contempt1",
               "no_excited1", "reprimand1", "frustrated1"],
    "approve": ["yes1", "enthusiastic1", "enthusiastic2", "success2", "proud2", "understanding2",
                "cheerful1"],
    "mock": ["laughing1", "laughing2", "contempt1", "indifferent1", "reprimand3", "oops2"],
    "correct": ["inquiring1", "reprimand3", "thoughtful1", "no1", "inquiring3"],
    "cut": ["impatient1", "impatient2", "inquiring3", "irritated1"],
    "defend": ["calming1", "reprimand1", "welcoming2", "attentive1"],
}


# The menu by feeling, names only. The full descriptions were ~4,000
# characters of every director prompt (2026-10-21: the whole prompt took
# 3-3.5 s on Gemini direct; see docs/GROUP-CONVERSATION.md).
GROUPS = (
    ("happy, excited", ("enthusiastic1", "enthusiastic2", "cheerful1", "success1", "success2",
                        "proud1", "proud2", "proud3", "dance1", "yeah_nod", "headbanger_combo")),
    ("laughing", ("laughing1", "laughing2", "chicken_peck")),
    ("agreeing, nodding", ("yes1", "understanding1", "understanding2", "uh_huh_tilt",
                           "grateful1")),
    ("disagreeing, annoyed", ("no1", "no_excited1", "displeased1", "displeased2", "irritated1",
                              "irritated2", "impatient1", "impatient2", "contempt1",
                              "reprimand1", "reprimand3", "frustrated1")),
    ("furious (rare)", ("furious1", "rage1")),
    ("surprised, shocked", ("surprised1", "surprised2", "amazed1", "fear1", "neck_recoil",
                            "oops1", "oops2")),
    ("thinking, asking", ("thoughtful1", "thoughtful2", "inquiring1", "inquiring2", "inquiring3",
                          "incomprehensible2", "uncertain1", "side_glance_flick")),
    ("warm, welcoming", ("welcoming1", "welcoming2", "loving1", "calming1", "helpful1", "helpful2",
                         "come1", "attentive1", "attentive2")),
    ("sad, resigned, meh", ("downcast1", "sad2", "resigned1", "indifferent1", "yes_sad1",
                            "uncomfortable1", "relief1", "relief2", "serenity1", "disgusted1")),
)


def menu() -> str:
    """The gesture list for a director prompt, grouped by feeling."""
    known = set(EMOTIONS) | set(DANCES)
    lines = []
    for label, names in GROUPS:
        names = [n for n in names if n in known]
        if names:
            lines.append("{}: {}".format(label, ", ".join(names)))
    return "\n".join(lines)


def command(name: Optional[str]) -> Optional[tuple[dict, float]]:
    """(player motion command, seconds it keeps the head busy) or None."""
    n = str(name or "").strip()
    if n in EMOTIONS:
        return {"type": "emotion", "name": n}, float(EMOTIONS[n].get("dur") or 3.0)
    if n in DANCES:
        return {"type": "dance", "name": n}, float(DANCES[n].get("dur") or 3.0)
    return None


def reaction_for(character: str, stance: str = "", avoid: str = "") -> Optional[str]:
    pool = list(STANCE_REACTIONS.get(stance) or REACTIONS.get(character) or GENERIC)
    pool = [m for m in pool if m in EMOTIONS and m != avoid] or [m for m in GENERIC if m in EMOTIONS]
    return random.choice(pool) if pool else None


# Small moves a listener makes on its own (keep_heads in conductor.py), so a
# robot that is not talking never sits still. Short and quiet on purpose.
IDLE_LISTENING = ("attentive1", "attentive2", "understanding1", "understanding2", "inquiring2",
                  "thoughtful2", "side_glance_flick", "uh_huh_tilt", "yes1")
IDLE_WAITING = ("thoughtful2", "side_glance_flick", "attentive1", "serenity1", "inquiring2",
                "attentive2")


def similar(name: str) -> Optional[str]:
    """Another move of the same feeling as `name` (a long line's second gesture)."""
    for _label, names in GROUPS:
        if name in names:
            pool = [n for n in names if n != name and (n in EMOTIONS or n in DANCES)]
            return random.choice(pool) if pool else None
    return None
