from __future__ import annotations

import re
from dataclasses import dataclass


CASUAL = "casual"
LOCAL_INFO = "local_info"
KNOWLEDGE_INFO = "knowledge_info"
ACTION = "action"


@dataclass
class KnowledgeDecision:
    kind: str
    reason: str
    current: bool = False


def _clean(text: str) -> str:
    return re.sub(
        r"\s+",
        " ",
        str(text or "").strip().lower(),
    )


def classify_request(text: str) -> KnowledgeDecision:

    q = _clean(text)

    if not q:
        return KnowledgeDecision(
            CASUAL,
            "empty input",
        )


    # ============================================================
    # EXPLICIT BACKGROUND WEB INFORMATION
    # ============================================================

    explicit_web_info = (
        "search the web for",
        "search internet for",
        "search online for",
        "look up online",
        "look this up",
        "find information about",
        "check online",
    )

    if any(x in q for x in explicit_web_info):
        return KnowledgeDecision(
            KNOWLEDGE_INFO,
            "online lookup requested but web search is disabled",
            current=True,
        )


    # ============================================================
    # BROWSER ACTIONS
    # ============================================================

    if re.search(
        r"\b(search|find|look up)\b.+"
        r"\b(in|using|with)\b.+"
        r"\b(edge|chrome|firefox|brave)\b",
        q,
    ):
        return KnowledgeDecision(
            ACTION,
            "explicit browser action",
        )


    # ============================================================
    # LOCAL INFORMATION
    # ============================================================

    local_patterns = (
        r"\bwhat(?:'s| is)?(?: the)? time\b",
        r"\bcurrent time\b",
        r"\btime right now\b",
        r"\bwhat(?:'s| is)?(?: the)? date\b",
        r"\btoday'?s date\b",
        r"\bwhat day is it\b",
        r"\bday today\b",

        r"\bbattery\b",
        r"\bcpu\b",
        r"\bram\b",
        r"\bmemory usage\b",
        r"\bdisk space\b",
        r"\bstorage\b",
        r"\bsystem status\b",
        r"\bpc status\b",
        r"\bcomputer status\b",
        r"\bwindows version\b",
        r"\boperating system\b",
        r"\bgpu usage\b",
        r"\bgpu status\b",
        r"\bnetwork status\b",
        r"\bnetwork interfaces\b",
        r"\brunning processes\b",
        r"\brunning applications\b",
    )

    if any(
        re.search(pattern, q)
        for pattern in local_patterns
    ):
        return KnowledgeDecision(
            LOCAL_INFO,
            "information is available from the local computer",
        )


    # ============================================================
    # ACTION REQUESTS
    # ============================================================

    action_patterns = (

        r"^\s*(?:please\s+)?"
        r"(?:open|launch|start|run)\b",

        r"^\s*(?:please\s+)?"
        r"(?:close|quit|exit)\b",

        r"\bset (?:the )?volume\b",
        r"\bvolume to \d+",

        r"^\s*(?:please\s+)?"
        r"(?:create|make)\b",

        r"^\s*(?:please\s+)?"
        r"(?:delete|remove|recycle)\b",

        r"^\s*(?:please\s+)?"
        r"(?:rename|move|copy)\b",

        r"^\s*(?:please\s+)?"
        r"(?:install|uninstall)\b",

        r"^\s*(?:please\s+)?"
        r"(?:lock|restart|shutdown|shut down)\b",

        r"\bplay\b.+\byoutube\b",

        r"\bplay\b.+\bsong\b",

        r"\bturn on\b",
        r"\bturn off\b",

        r"^\s*(?:please\s+)?"
        r"(?:list|show)\b.+"
        r"\b(files|folders|processes|applications)\b",
    )

    if any(
        re.search(pattern, q)
        for pattern in action_patterns
    ):
        return KnowledgeDecision(
            ACTION,
            "user requested a computer action",
        )


    # ============================================================
    # CASUAL CONVERSATION
    # ============================================================

    casual_patterns = (
        r"^(hi|hello|hey|yo)\b",
        r"\bhow are you\b",
        r"\bhow'?s it going\b",
        r"\bwhat are you doing\b",
        r"\bthank(s| you)\b",
        r"\bgood (morning|afternoon|evening|night)\b",
        r"\btell me a joke\b",
        r"\bi'?m bored\b",
        r"\blet'?s talk\b",
        r"\bchat with me\b",
        r"\bdo you like\b",
        r"\bwhat do you think about me\b",
    )

    if any(
        re.search(pattern, q)
        for pattern in casual_patterns
    ):
        return KnowledgeDecision(
            CASUAL,
            "casual conversation",
        )


    # ============================================================
    # CURRENT / CHANGING INFORMATION
    # ============================================================

    current_terms = (
        "latest",
        "recent",
        "today",
        "yesterday",
        "right now",
        "currently",
        "current ",
        "news",
        "update",
        "updates",
        "new release",
        "new version",
        "price",
        "stock",
        "score",
        "result",
        "election",
        "weather",
        "released",
        "launch date",
    )

    if any(
        term in q
        for term in current_terms
    ):
        return KnowledgeDecision(
            KNOWLEDGE_INFO,
            "current information requires live data unavailable offline",
            current=True,
        )


    # ============================================================
    # GENERAL FACTUAL INFORMATION
    # ============================================================

    factual_patterns = (
        r"^(what|who|where|when|why|how)\b",
        r"^can you explain\b",
        r"^explain\b",
        r"^tell me about\b",
        r"^describe\b",
        r"^define\b",
        r"^give me information\b",
        r"^what does\b",
        r"^what is the difference\b",
        r"^which\b",
    )

    if any(
        re.search(pattern, q)
        for pattern in factual_patterns
    ):
        return KnowledgeDecision(
            KNOWLEDGE_INFO,
            "general factual information should use local knowledge",
            current=False,
        )


    # Plain conversational statements remain local.
    return KnowledgeDecision(
        CASUAL,
        "no factual or action requirement detected",
    )

# === SARA CURRENT OFFICE HOLDER ROUTING V1 ===

import re as _office_re


# Preserve the production classifier.
_classify_request_before_office_holder = (
    classify_request
)


def _normalize_office_holder_query(
    text: str,
) -> str:

    q = str(
        text or ""
    ).lower()


    # Normalize apostrophe form:
    #
    # who's the president
    # ->
    # who is the president

    q = q.replace(
        "who's",
        "who is",
    )


    # STT often separates abbreviations:
    #
    # p m
    # c m
    # c e o

    q = _office_re.sub(
        r"\bp\s+m\b",
        "pm",
        q,
    )

    q = _office_re.sub(
        r"\bc\s+m\b",
        "cm",
        q,
    )

    q = _office_re.sub(
        r"\bc\s+e\s+o\b",
        "ceo",
        q,
    )


    q = _office_re.sub(
        r"\s+",
        " ",
        q,
    ).strip()


    return q


def _is_current_office_holder_question(
    text: str,
) -> bool:

    q = _normalize_office_holder_query(
        text
    )


    # --------------------------------------------------------
    # Questions asking WHO CURRENTLY HOLDS an office.
    #
    # Examples:
    #
    # who is pm of india
    # who is the president of usa
    # who is ceo of nvidia
    # who is chief minister of tamil nadu
    #
    # Historical forms such as:
    #
    # who was president in 2010
    #
    # do NOT match.
    # --------------------------------------------------------

    office = (
        r"(?:"
        r"pm"
        r"|prime\s+minister"
        r"|president"
        r"|chief\s+minister"
        r"|cm"
        r"|ceo"
        r"|chairman"
        r"|governor"
        r"|mayor"
        r")"
    )


    who_is_pattern = (
        r"\bwho\s+is\s+"
        r"(?:the\s+)?"
        r"(?:current\s+|present\s+)?"
        +
        office
        +
        r"\b"
    )


    current_pattern = (
        r"\b(?:current|present)\s+"
        +
        office
        +
        r"\b"
    )


    return bool(
        _office_re.search(
            who_is_pattern,
            q,
        )
        or
        _office_re.search(
            current_pattern,
            q,
        )
    )


def classify_request(
    text: str,
):

    # --------------------------------------------------------
    # Office-holder facts are time-sensitive.
    #
    # They must use live/current retrieval rather than the
    # normal evergreen factual-information path.
    # --------------------------------------------------------

    if _is_current_office_holder_question(
        text
    ):

        return KnowledgeDecision(
            kind=KNOWLEDGE_INFO,

            reason=(
                "office-holder information "
                "requires current data unavailable offline"
            ),

            current=True,
        )


    # Everything else keeps the original production behavior.

    return (
        _classify_request_before_office_holder(
            text
        )
    )


# === END SARA CURRENT OFFICE HOLDER ROUTING V1 ===



