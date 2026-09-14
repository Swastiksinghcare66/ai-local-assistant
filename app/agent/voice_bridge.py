from __future__ import annotations

import asyncio
import re

from .runtime import SaraAgent


def _clean_tts_text(
    text: str,
) -> str:

    text = str(
        text
        or ""
    ).strip()

    text = (
        text
        .replace(
            "\r",
            " ",
        )
        .replace(
            "\n",
            " ",
        )
    )

    text = re.sub(
        r"\[(?:\d+\s*,?\s*)+\]",
        "",
        text,
    )

    text = (
        text
        .replace(
            "**",
            "",
        )
        .replace(
            "__",
            "",
        )
    )

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text.strip()


def _tts_phrases(
    text: str,
    max_chars: int = 220,
) -> list[str]:

    text = _clean_tts_text(
        text
    )

    if not text:

        return []


    sentences = re.split(
        r"(?<=[.!?])\s+",
        text,
    )


    phrases = []

    current = ""


    for sentence in sentences:

        sentence = (
            sentence.strip()
        )

        if not sentence:
            continue


        if (
            len(sentence)
            >
            max_chars
        ):

            parts = re.split(
                r"(?<=[,;:])\s+",
                sentence,
            )

        else:

            parts = [
                sentence
            ]


        for part in parts:

            part = (
                part.strip()
            )

            if not part:
                continue


            candidate = (
                f"{current} {part}".strip()
                if current
                else part
            )


            if (
                len(candidate)
                <=
                max_chars
            ):

                current = (
                    candidate
                )

            else:

                if current:

                    phrases.append(
                        current
                    )

                current = (
                    part
                )


    if current:

        phrases.append(
            current
        )


    return phrases


async def speak_agent_reply(
    client,
    reply,
    style:
        str = "calm_confident",
):

    text = str(
        reply.text
        or ""
    ).strip()


    if not text:

        return


    print()

    print(
        f"[AGENT "
        f"{reply.state.value.upper()}] "
        f"{text}"
    )


    phrases = (
        _tts_phrases(
            text
        )
    )


    for index, phrase in enumerate(
        phrases,
        start=1,
    ):

        try:

            print(
                f"[AGENT TTS "
                f"{index}/"
                f"{len(phrases)}] "
                f"{phrase}"
            )


            await client.speak(
                phrase,
                style=
                    style,
                flow_steps=
                    5,
            )


        except Exception as exc:

            print(
                "[AGENT TTS ERROR] "
                f"{type(exc).__name__}: "
                f"{exc!s}"
            )


            try:

                await client.close()

            except Exception:

                pass


            try:

                await client.connect()


                await client.speak(
                    phrase,
                    style=
                        None,
                    flow_steps=
                        5,
                )


            except Exception as retry_exc:

                print(
                    "[AGENT TTS RETRY FAILED] "
                    f"{type(retry_exc).__name__}: "
                    f"{retry_exc!s}"
                )

                continue


async def agent_turn(
    *,
    agent:
        SaraAgent,
    client,
    prompt_builder,
    user_text:
        str,
    history:
        list,
    normal_run_turn,
):

    reply = (
        await asyncio.to_thread(
            agent.handle,
            user_text,
        )
    )


    decision = (
        reply.decision
    )


    if (
        decision
        is not None
    ):

        print(
            "[INTENT] "
            f"kind="
            f"{decision.kind.value} "
            f"intent="
            f"{decision.intent} "
            f"confidence="
            f"{decision.confidence:.2f} "
            f"web="
            f"{decision.requires_web}"
        )


    if (
        reply.use_normal_chat
    ):

        return await normal_run_turn(
            client=
                client,
            prompt_builder=
                prompt_builder,
            user_text=
                user_text,
            history=
                history,
        )


    await speak_agent_reply(
        client,
        reply,
    )


    history.append(
        {
            "role":
                "user",
            "content":
                user_text,
        }
    )


    history.append(
        {
            "role":
                "assistant",
            "content":
                reply.text,
        }
    )


    if (
        len(history)
        >
        8
    ):

        del history[:-8]


    return reply.text
