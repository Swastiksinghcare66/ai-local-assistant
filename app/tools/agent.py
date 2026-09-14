"""
Tool Agent
----------

Connects the LLM to the ToolRegistry.

Normal conversation:

    User
      ↓
    LLM streaming
      ↓
    response

Tool request:

    User
      ↓
    LLM
      ↓
    structured tool call
      ↓
    ToolRegistry
      ↓
    Python function
      ↓
    tool result
      ↓
    LLM
      ↓
    natural-language response

The important design rule:

The LLM decides WHICH registered tool it wants to call,
but it never executes arbitrary Python itself.
"""

import json
import time
from typing import Generator, Optional

from app.config import (
    LLM_KEEP_ALIVE,
    LLM_THINK,
    MAX_TOOL_CALLS_PER_TURN,
    SHOW_INFERENCE_TIME,
)
from app.llm_client import (
    client,
    get_generation_options,
    get_model_name,
)


# ============================================================
# HELPERS
# ============================================================

def _message_content(message) -> str:
    """
    Support both Ollama Pydantic objects and dictionary responses.
    """

    if message is None:
        return ""

    if isinstance(message, dict):
        return message.get("content", "") or ""

    return getattr(
        message,
        "content",
        "",
    ) or ""


def _message_tool_calls(message) -> list:
    """
    Extract tool calls from either Ollama objects or dictionaries.
    """

    if message is None:
        return []

    if isinstance(message, dict):
        return message.get("tool_calls", []) or []

    return getattr(
        message,
        "tool_calls",
        [],
    ) or []


def _chunk_message(chunk):
    """
    Extract the message object from an Ollama streaming chunk.
    """

    if isinstance(chunk, dict):
        return chunk.get("message")

    return getattr(
        chunk,
        "message",
        None,
    )


def _tool_name(tool_call) -> str:
    """
    Extract function name from a tool call.
    """

    if isinstance(tool_call, dict):

        function = tool_call.get(
            "function",
            {},
        )

        return function.get(
            "name",
            "",
        )

    function = getattr(
        tool_call,
        "function",
        None,
    )

    if function is None:
        return ""

    return getattr(
        function,
        "name",
        "",
    )


def _tool_arguments(tool_call) -> dict:
    """
    Extract function arguments from a tool call.
    """

    if isinstance(tool_call, dict):

        function = tool_call.get(
            "function",
            {},
        )

        arguments = function.get(
            "arguments",
            {},
        )

    else:

        function = getattr(
            tool_call,
            "function",
            None,
        )

        arguments = getattr(
            function,
            "arguments",
            {},
        )

    if arguments is None:
        return {}

    if isinstance(arguments, dict):
        return arguments

    # Defensive fallback in case a model/provider returns
    # arguments as a JSON string.
    if isinstance(arguments, str):

        try:
            parsed = json.loads(arguments)

            if isinstance(parsed, dict):
                return parsed

        except json.JSONDecodeError:
            pass

    return {}


# ============================================================
# TOOL AGENT
# ============================================================

class ToolAgent:

    def __init__(
        self,
        registry,
    ):

        self.registry = registry


    # ========================================================
    # STREAM
    # ========================================================

    def stream(
        self,
        messages: list,
        model_name: Optional[str] = None,
    ) -> Generator[str, None, None]:
        """
        Run one conversational turn with optional tool calls.

        Normal conversation normally requires one LLM pass.

        A tool request normally requires:

            pass 1
                ↓
            tool call
                ↓
            execute tool
                ↓
            pass 2
                ↓
            final natural-language response
        """

        model = get_model_name(
            model_name
        )

        schemas = (
            self.registry.get_schemas()
        )

        # Work on a copy.
        #
        # We don't want temporary tool-response messages
        # polluting the caller's stored conversation.
        working_messages = list(
            messages
        )

        overall_start = (
            time.perf_counter()
        )

        # MAX_TOOL_CALLS_PER_TURN means actual tool rounds.
        #
        # +1 allows the final response after the last tool call.
        max_rounds = (
            MAX_TOOL_CALLS_PER_TURN
            + 1
        )

        for round_number in range(
            1,
            max_rounds + 1,
        ):

            round_start = (
                time.perf_counter()
            )

            first_event_time = None

            content_parts = []

            tool_calls = []


            # ------------------------------------------------
            # ASK LLM
            # ------------------------------------------------

            try:

                stream = client.chat(
                    model=model,
                    messages=working_messages,
                    tools=schemas,
                    think=LLM_THINK,
                    stream=True,
                    keep_alive=LLM_KEEP_ALIVE,
                    options=get_generation_options(),
                )

            except Exception as exc:

                print(
                    f"\n[AGENT ERROR] {exc}"
                )

                yield (
                    "I'm unable to complete "
                    "that request right now."
                )

                return


            # ------------------------------------------------
            # READ STREAM
            # ------------------------------------------------

            for chunk in stream:

                message = _chunk_message(
                    chunk
                )

                if message is None:
                    continue


                # --------------------------------------------
                # NORMAL TEXT
                # --------------------------------------------

                content = _message_content(
                    message
                )

                if content:

                    now = (
                        time.perf_counter()
                    )

                    if first_event_time is None:

                        first_event_time = now

                        if SHOW_INFERENCE_TIME:

                            latency = (
                                first_event_time
                                - round_start
                            )

                            print(
                                f"\n[AGENT] "
                                f"round={round_number} "
                                f"first_event="
                                f"{latency:.3f}s"
                            )

                    content_parts.append(
                        content
                    )

                    # Preserve low-latency streaming.
                    yield content


                # --------------------------------------------
                # TOOL CALLS
                # --------------------------------------------

                calls = (
                    _message_tool_calls(
                        message
                    )
                )

                if calls:

                    now = (
                        time.perf_counter()
                    )

                    if first_event_time is None:

                        first_event_time = now

                        if SHOW_INFERENCE_TIME:

                            latency = (
                                first_event_time
                                - round_start
                            )

                            print(
                                f"\n[AGENT] "
                                f"round={round_number} "
                                f"first_tool="
                                f"{latency:.3f}s"
                            )

                    tool_calls.extend(
                        calls
                    )


            # ------------------------------------------------
            # ACCUMULATE ASSISTANT MESSAGE
            # ------------------------------------------------

            assistant_content = (
                "".join(
                    content_parts
                )
            )

            assistant_message = {
                "role": "assistant",
                "content": assistant_content,
            }

            if tool_calls:

                assistant_message[
                    "tool_calls"
                ] = tool_calls

            working_messages.append(
                assistant_message
            )


            # ------------------------------------------------
            # NO TOOL CALL
            # ------------------------------------------------

            if not tool_calls:

                total = (
                    time.perf_counter()
                    - overall_start
                )

                if SHOW_INFERENCE_TIME:

                    print()
                    print(
                        f"[AGENT] complete "
                        f"rounds={round_number} "
                        f"total={total:.3f}s"
                    )

                return


            # ------------------------------------------------
            # EXECUTE TOOL CALLS
            # ------------------------------------------------

            for call in tool_calls:

                name = _tool_name(
                    call
                )

                arguments = (
                    _tool_arguments(
                        call
                    )
                )

                if SHOW_INFERENCE_TIME:

                    print()
                    print(
                        f"[TOOL] "
                        f"{name}"
                        f"({arguments})"
                    )


                result = (
                    self.registry.execute(
                        name=name,
                        arguments=arguments,
                    )
                )


                if SHOW_INFERENCE_TIME:

                    print(
                        f"[TOOL RESULT] "
                        f"{result}"
                    )


                # --------------------------------------------
                # FEED RESULT BACK TO LLM
                # --------------------------------------------

                working_messages.append(
                    {
                        "role": "tool",
                        "tool_name": name,
                        "content": json.dumps(
                            result,
                            ensure_ascii=False,
                        ),
                    }
                )


        # ====================================================
        # SAFETY LIMIT
        # ====================================================

        print()
        print(
            "[AGENT] Maximum tool-call "
            "rounds reached."
        )

        yield (
            "I couldn't complete that request "
            "within the allowed number of tool calls."
        )