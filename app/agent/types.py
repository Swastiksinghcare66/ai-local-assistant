from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class IntentKind(str, Enum):
    CHAT = "chat"
    QUESTION = "question"
    ACTION = "action"
    AMBIGUOUS = "ambiguous"


class AgentState(str, Enum):
    CHAT = "chat"
    ANSWERED = "answered"
    EXECUTING = "executing"
    SUCCESS = "success"
    FAILED = "failed"
    UNSUPPORTED = "unsupported"
    NEEDS_CONSENT = "needs_consent"
    NEEDS_CLARIFICATION = "needs_clarification"


@dataclass
class IntentDecision:
    kind: IntentKind
    intent: str
    confidence: float = 0.0
    arguments: dict[str, Any] = field(default_factory=dict)

    requires_web: bool = False
    search_query: str | None = None

    ambiguous: bool = False
    clarification: str | None = None

    reason: str | None = None


@dataclass
class ActionResult:
    success: bool
    action: str
    message: str = ""
    error: str | None = None
    verified: bool = False
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentReply:
    state: AgentState
    text: str
    decision: IntentDecision | None = None
    result: ActionResult | None = None

    # If True, the caller should use Sara's existing normal
    # conversational STT -> LLM -> TTS path unchanged.
    use_normal_chat: bool = False
