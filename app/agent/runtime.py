from __future__ import annotations

import re

from .intent import analyse_intent
from .pc_broker import AUTO, BLOCK, CONFIRM, PCCapabilityBroker
from .types import AgentReply, AgentState, IntentKind
class SaraAgent:
    def __init__(self):
        self.pc = PCCapabilityBroker()

    def _reply_from_result(self, decision, result):
        if result.success:
            return AgentReply(
                state=AgentState.SUCCESS,
                text=result.message or "Done.",
                decision=decision,
                result=result,
            )
        return AgentReply(
            state=AgentState.FAILED,
            text=result.error or "I tried, but the action failed.",
            decision=decision,
            result=result,
        )

    def handle(self, user_text: str) -> AgentReply:
        # Deterministic confirmation path comes before LLM routing.
        if self.pc.has_pending():
            if re.match(r"^\s*(confirm|cancel|no|stop|never mind|nevermind)\b", user_text, flags=re.I):
                result = self.pc.confirm_from_text(user_text)
                if result is not None:
                    return self._reply_from_result(None, result)

        decision = analyse_intent(user_text)

        if decision.kind == IntentKind.AMBIGUOUS or decision.ambiguous:
            return AgentReply(
                state=AgentState.NEEDS_CLARIFICATION,
                text=decision.clarification or "Can you clarify what you want me to do?",
                decision=decision,
            )

        if decision.kind == IntentKind.CHAT:
            return AgentReply(
                state=AgentState.CHAT,
                text="",
                decision=decision,
                use_normal_chat=True,
            )

        if decision.kind == IntentKind.QUESTION:
            return AgentReply(
                state=AgentState.CHAT,
                text="",
                decision=decision,
                use_normal_chat=True,
            )

        if decision.kind == IntentKind.ACTION and decision.intent == "web_search":
            return AgentReply(
                state=AgentState.UNSUPPORTED,
                text="Web search is disabled.",
                decision=decision,
            )

        if decision.kind == IntentKind.ACTION:
            prepared = self.pc.prepare(decision.intent, decision.arguments)

            if prepared.policy == BLOCK:
                return AgentReply(
                    state=AgentState.UNSUPPORTED,
                    text=(
                        f"I understood the action {prepared.intent}, but I don't have "
                        "a safe implemented capability for it."
                    ),
                    decision=decision,
                )

            if prepared.policy == CONFIRM:
                code = self.pc.stage(prepared)
                spoken = " ".join(code)
                return AgentReply(
                    state=AgentState.NEEDS_CONSENT,
                    text=(
                        f"This is a major change: {prepared.summary}. "
                        f"Verification code is {spoken}. "
                        f"Say confirm {spoken} within 90 seconds to continue."
                    ),
                    decision=decision,
                )

            if prepared.policy == AUTO:
                return self._reply_from_result(
                    decision,
                    self.pc.execute(prepared),
                )

        return AgentReply(
            state=AgentState.UNSUPPORTED,
            text="I understood the request, but I don't have a safe way to execute it.",
            decision=decision,
        )
