from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .types import ActionResult

from .tools.pc import (
    open_application,
    open_website,
    browser_search,
)


@dataclass(
    frozen=True
)
class Capability:

    name: str

    handler: Callable[..., ActionResult]

    description: str


CAPABILITIES = {

    "open_application":
        Capability(
            name=
                "open_application",
            handler=
                open_application,
            description=
                "Open a Windows application.",
        ),

    "open_website":
        Capability(
            name=
                "open_website",
            handler=
                open_website,
            description=
                "Open a website.",
        ),

    "open_url":
        Capability(
            name=
                "open_url",
            handler=
                open_website,
            description=
                "Open an HTTP or HTTPS URL.",
        ),

    "browser_search":
        Capability(
            name=
                "browser_search",
            handler=
                browser_search,
            description=(
                "Search using a specific "
                "installed browser."
            ),
        ),
}


def get_capability(
    intent: str,
):

    return CAPABILITIES.get(
        intent
    )


def capability_names():

    return sorted(
        CAPABILITIES.keys()
    )
