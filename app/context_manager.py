"""
Context Window Manager
----------------------
Selects which conversation messages
should be sent to the LLM.
"""

from app.config import (
    MAX_CONTEXT_MESSAGES,
    ALLOW_UNLIMITED_CONTEXT,
)


class ContextManager:

    def get_context(self, messages):

        if ALLOW_UNLIMITED_CONTEXT:
            return messages

        return messages[-MAX_CONTEXT_MESSAGES:]