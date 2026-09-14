from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ActionPolicy:
    risk: int
    always_confirm: bool = False
    confirm_if_ambiguous: bool = True


POLICIES = {
    # Read-only / low consequence
    "web_search": ActionPolicy(risk=0),
    "get_pc_status": ActionPolicy(risk=0),

    # Easy to reverse
    "open_application": ActionPolicy(risk=1),
    "open_website": ActionPolicy(risk=1),
    "open_url": ActionPolicy(risk=1),
    "browser_search": ActionPolicy(risk=1),
    "media_control": ActionPolicy(risk=1),
    "set_volume": ActionPolicy(risk=1),

    # Potential data/work loss
    "close_application": ActionPolicy(
        risk=2,
        always_confirm=True,
    ),

    # Anything unknown should never auto-execute.
    "other_action": ActionPolicy(
        risk=3,
        always_confirm=True,
    ),
}


def policy_for(intent: str) -> ActionPolicy:
    return POLICIES.get(
        intent,
        ActionPolicy(
            risk=3,
            always_confirm=True,
        ),
    )

