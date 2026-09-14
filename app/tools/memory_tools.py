"""
Memory Tools
------------

Exposes the real runtime MemoryManager state as callable tools.

These tools do NOT ask the LLM to remember whether memory is on.
They read and modify the actual Session.memory object.

Examples:

    "Is memory enabled?"
        -> get_memory_status()

    "Turn memory off."
        -> disable_memory()

    "Enable memory."
        -> enable_memory()

    "Clear conversation memory."
        -> clear_memory()
"""


def register_memory_tools(
    registry,
    session,
):
    """
    Register all memory-related tools.

    The handlers close over the active Session object, so every
    tool call reads or modifies the real runtime memory state.
    """

    # ========================================================
    # GET MEMORY STATUS
    # ========================================================

    def get_memory_status():

        enabled = session.memory.is_enabled()

        return {
            "enabled": enabled,
            "status": (
                "ON"
                if enabled
                else "OFF"
            ),
            "stored_messages": (
                session.conversation.message_count()
            ),
        }


    registry.register(
        name="get_memory_status",
        description=(
            "Check the assistant's actual current conversation "
            "memory state. Use this whenever the user asks whether "
            "memory is on, off, enabled, disabled, active, or inactive."
        ),
        parameters={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        handler=get_memory_status,
    )


    # ========================================================
    # ENABLE MEMORY
    # ========================================================

    def enable_memory():

        session.memory.enable()

        return {
            "enabled": True,
            "status": "ON",
            "message": "Conversation memory is now enabled.",
        }


    registry.register(
        name="enable_memory",
        description=(
            "Enable conversation memory. Use when the user asks "
            "to turn on, enable, activate, or start memory."
        ),
        parameters={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        handler=enable_memory,
    )


    # ========================================================
    # DISABLE MEMORY
    # ========================================================

    def disable_memory():

        session.memory.disable()

        return {
            "enabled": False,
            "status": "OFF",
            "message": "Conversation memory is now disabled.",
        }


    registry.register(
        name="disable_memory",
        description=(
            "Disable conversation memory. Use when the user asks "
            "to turn off, disable, deactivate, or stop memory."
        ),
        parameters={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        handler=disable_memory,
    )


    # ========================================================
    # CLEAR MEMORY
    # ========================================================

    def clear_memory():

        previous_message_count = (
            session.conversation.message_count()
        )

        session.memory.clear(
            session.conversation
        )

        return {
            "success": True,
            "cleared_messages": previous_message_count,
            "memory_status": session.memory.status(),
            "message": "Stored conversation memory has been cleared.",
        }


    registry.register(
        name="clear_memory",
        description=(
            "Permanently clear stored conversation history. "
            "Use only when the user explicitly asks to clear, "
            "erase, delete, forget, or reset conversation memory."
        ),
        parameters={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        handler=clear_memory,
    )