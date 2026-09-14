"""
Tool Registry
-------------

Central registry for functions that the LLM is allowed to call.

The LLM never directly executes Python functions.

Flow:

    LLM
     ↓
    structured tool request
     ↓
    ToolRegistry
     ↓
    registered Python function
     ↓
    structured result
"""

from dataclasses import dataclass
from typing import Any, Callable, Dict, List


# ============================================================
# TOOL DEFINITION
# ============================================================

@dataclass
class ToolDefinition:

    name: str

    description: str

    parameters: dict

    handler: Callable[..., Any]


# ============================================================
# TOOL REGISTRY
# ============================================================

class ToolRegistry:

    def __init__(self):

        self._tools: Dict[str, ToolDefinition] = {}


    # ========================================================
    # REGISTER
    # ========================================================

    def register(
        self,
        name: str,
        description: str,
        parameters: dict,
        handler: Callable[..., Any],
    ):

        if not name:
            raise ValueError(
                "Tool name cannot be empty."
            )

        if not callable(handler):
            raise TypeError(
                f"Handler for tool '{name}' must be callable."
            )

        if name in self._tools:
            raise ValueError(
                f"Tool '{name}' is already registered."
            )

        self._tools[name] = ToolDefinition(
            name=name,
            description=description,
            parameters=parameters,
            handler=handler,
        )


    # ========================================================
    # CHECK TOOL
    # ========================================================

    def has_tool(
        self,
        name: str,
    ) -> bool:

        return name in self._tools


    # ========================================================
    # EXECUTE
    # ========================================================

    def execute(
        self,
        name: str,
        arguments: dict | None = None,
    ) -> dict:

        arguments = arguments or {}

        tool = self._tools.get(name)

        if tool is None:

            return {
                "success": False,
                "tool": name,
                "error": (
                    f"Tool '{name}' is not registered."
                ),
            }

        try:

            result = tool.handler(
                **arguments
            )

            return {
                "success": True,
                "tool": name,
                "result": result,
            }

        except TypeError as exc:

            return {
                "success": False,
                "tool": name,
                "error": (
                    f"Invalid arguments: {exc}"
                ),
            }

        except Exception as exc:

            return {
                "success": False,
                "tool": name,
                "error": str(exc),
            }


    # ========================================================
    # OLLAMA TOOL SCHEMAS
    # ========================================================

    def get_schemas(
        self,
    ) -> List[dict]:
        """
        Convert registered tools into the schema format expected
        by tool-capable chat models.
        """

        schemas = []

        for tool in self._tools.values():

            schemas.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters,
                    },
                }
            )

        return schemas


    # ========================================================
    # TOOL NAMES
    # ========================================================

    def names(
        self,
    ) -> List[str]:

        return list(
            self._tools.keys()
        )


    # ========================================================
    # COUNT
    # ========================================================

    def count(
        self,
    ) -> int:

        return len(
            self._tools
        )