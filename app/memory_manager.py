"""
Memory Manager
--------------

Controls whether conversation history is:

1. Sent back to the LLM.
2. Stored for future turns.

Memory can be enabled or disabled at runtime without restarting
the assistant.
"""

from app.config import (
    MEMORY_ENABLED_DEFAULT,
    MEMORY_SAVE_WHEN_DISABLED,
    MAX_CONTEXT_MESSAGES,
    ALLOW_UNLIMITED_CONTEXT,
)


class MemoryManager:
    """
    Runtime conversation-memory controller.

    Memory ON:
        previous conversation + current request -> LLM

    Memory OFF:
        current request only -> LLM

    By default, new turns are not stored while memory is disabled.
    """

    def __init__(self):
        self.enabled = MEMORY_ENABLED_DEFAULT
        self.save_when_disabled = MEMORY_SAVE_WHEN_DISABLED

    # ========================================================
    # STATE
    # ========================================================

    def enable(self):
        self.enabled = True
        return True

    def disable(self):
        self.enabled = False
        return False

    def set_enabled(self, enabled: bool):
        self.enabled = bool(enabled)
        return self.enabled

    def toggle(self):
        self.enabled = not self.enabled
        return self.enabled

    def is_enabled(self) -> bool:
        return self.enabled

    def status(self) -> str:
        return "ON" if self.enabled else "OFF"

    # ========================================================
    # STORAGE POLICY
    # ========================================================

    def should_store(self) -> bool:
        """
        Decide whether new conversation turns should be saved.
        """

        if self.enabled:
            return True

        return self.save_when_disabled

    # ========================================================
    # CONTEXT
    # ========================================================

    def build_context(
        self,
        stored_messages: list,
        current_user_message: str,
    ) -> list:
        """
        Build exactly the conversation context sent to the LLM.

        The current user message is ALWAYS included.

        When memory is OFF, previous messages are omitted.
        """

        current_message = {
            "role": "user",
            "content": current_user_message,
        }

        if not self.enabled:
            return [current_message]

        history = list(stored_messages)

        if ALLOW_UNLIMITED_CONTEXT:
            return [
                *history,
                current_message,
            ]

        # Reserve one context slot for the current user message.
        history_limit = max(
            MAX_CONTEXT_MESSAGES - 1,
            0,
        )

        if history_limit > 0:
            history = history[-history_limit:]
        else:
            history = []

        return [
            *history,
            current_message,
        ]

    # ========================================================
    # TURN STORAGE
    # ========================================================

    def store_turn(
        self,
        conversation,
        user_message: str,
        assistant_message: str,
    ) -> bool:
        """
        Store a completed user/assistant turn if policy allows it.

        Returns True if saved, otherwise False.
        """

        if not self.should_store():
            return False

        conversation.add_user(user_message)
        conversation.add_assistant(assistant_message)

        return True

    # ========================================================
    # CLEAR MEMORY
    # ========================================================

    def clear(self, conversation):
        conversation.clear()