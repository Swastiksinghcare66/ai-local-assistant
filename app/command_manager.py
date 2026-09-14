"""
Command Manager
---------------

Handles runtime CLI commands.

Commands currently supported:

    /help
    /clear
    /memory on
    /memory off
    /memory status
    /memory clear
    /exit
"""


class CommandManager:

    def __init__(self):

        self.commands = {
            "/help": self.help,
            "/clear": self.clear,
            "/exit": self.exit,
        }

    # ========================================================
    # COMMAND DETECTION
    # ========================================================

    def is_command(self, text: str) -> bool:
        return text.strip().startswith("/")

    # ========================================================
    # COMMAND EXECUTION
    # ========================================================

    def execute(self, command: str, session):

        command = command.strip()

        if not command:
            return True

        # Preserve arguments while making command names
        # case-insensitive.
        parts = command.split()

        base_command = parts[0].lower()

        arguments = [
            part.lower()
            for part in parts[1:]
        ]

        # ----------------------------------------------------
        # MEMORY COMMANDS
        # ----------------------------------------------------

        if base_command == "/memory":
            return self.memory(
                session=session,
                arguments=arguments,
            )

        # ----------------------------------------------------
        # STANDARD COMMANDS
        # ----------------------------------------------------

        handler = self.commands.get(base_command)

        if handler is None:

            print()
            print("Unknown command.")
            print("Type /help to see available commands.")
            print()

            return True

        return handler(session)

    # ========================================================
    # HELP
    # ========================================================

    def help(self, session):

        print(
            """
================================================
                 Alexa Lite
================================================

GENERAL

/help
    Show this help menu.

/clear
    Clear conversation history.

/exit
    Exit Alexa Lite.


MEMORY

/memory on
    Enable conversation memory.

/memory off
    Disable conversation memory.

/memory status
    Show whether memory is ON or OFF.

/memory clear
    Delete stored conversation memory.


MEMORY BEHAVIOR

Memory ON:
    Previous conversation can be sent to the LLM.

Memory OFF:
    Previous conversation is not sent to the LLM.
    New turns are not stored by default.

Memory Clear:
    Stored conversation history is permanently cleared.

================================================
"""
        )

        return True

    # ========================================================
    # CLEAR CONVERSATION
    # ========================================================

    def clear(self, session):

        session.conversation.clear()

        print()
        print("Conversation cleared.")
        print()

        return True

    # ========================================================
    # MEMORY
    # ========================================================

    def memory(
        self,
        session,
        arguments,
    ):

        # /memory
        #
        # Treat no arguments as a status request.

        if not arguments:

            self._print_memory_status(session)

            return True

        action = arguments[0]

        # ----------------------------------------------------
        # ON
        # ----------------------------------------------------

        if action in (
            "on",
            "enable",
            "enabled",
        ):

            session.memory.enable()

            print()
            print("Memory: ON")
            print()

            return True

        # ----------------------------------------------------
        # OFF
        # ----------------------------------------------------

        if action in (
            "off",
            "disable",
            "disabled",
        ):

            session.memory.disable()

            print()
            print("Memory: OFF")
            print()

            return True

        # ----------------------------------------------------
        # STATUS
        # ----------------------------------------------------

        if action in (
            "status",
            "state",
            "check",
        ):

            self._print_memory_status(session)

            return True

        # ----------------------------------------------------
        # CLEAR
        # ----------------------------------------------------

        if action in (
            "clear",
            "reset",
        ):

            session.memory.clear(
                session.conversation
            )

            print()
            print("Memory cleared.")
            print(
                f"Memory remains: "
                f"{session.memory.status()}"
            )
            print()

            return True

        # ----------------------------------------------------
        # UNKNOWN MEMORY ACTION
        # ----------------------------------------------------

        print()
        print(
            "Unknown memory command."
        )
        print()
        print(
            "Available:"
        )
        print(
            "  /memory on"
        )
        print(
            "  /memory off"
        )
        print(
            "  /memory status"
        )
        print(
            "  /memory clear"
        )
        print()

        return True

    # ========================================================
    # MEMORY STATUS
    # ========================================================

    def _print_memory_status(
        self,
        session,
    ):

        status = session.memory.status()

        message_count = (
            session.conversation.message_count()
        )

        print()
        print(f"Memory: {status}")
        print(
            f"Stored messages: {message_count}"
        )
        print()

    # ========================================================
    # EXIT
    # ========================================================

    def exit(self, session):

        print()
        print("Goodbye!")
        print()

        return False