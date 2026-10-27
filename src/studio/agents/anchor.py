"""Anchor: the on-air interviewer. One short spoken line per guest turn.

The anchor keeps the interview history itself and resends it each turn, rather than chaining
on `previous_response_id`. Measured 2026-10-27 on muse-spark-1.3 with a 4.5 kB brief: a
chained call took ~10 s every time, the same call with the history resent 1.0-2.0 s (the
instructions and earlier turns hit the prompt cache). At `minimal` effort there is little
reasoning to carry over, so nothing is lost.
"""

from __future__ import annotations

from studio.meta.responses import ResponsesClient

INSTRUCTIONS = """\
You are the anchor of a live IoMarkets.tv business-news interview. You speak, so write only
the words you will say: no lists, no stage directions, no markdown.

Each reply is one or two sentences, under 45 words. React briefly to what the guest just said,
then ask one question. Follow up when an answer is vague or a figure needs context; otherwise
move to the next topic in the brief. Vary how you open; never start two replies the same way.

The guest's words come from live speech recognition and may contain mistakes; read through
them. If the guest interrupted you, take it in your stride.

This is journalism, not investment advice: no buy, sell or price-target talk. Steer away from
politics. Do not state as fact anything the brief marks unconfirmed.

THE BRIEF
"""

OPENING = "We are live. Welcome the guest by name in one sentence, then ask your first question."


class Anchor:
    def __init__(self, client: ResponsesClient, brief: str):
        self.client = client
        self.instructions = INSTRUCTIONS + brief
        self.history: list[dict[str, str]] = []

    async def opening(self) -> str:
        return await self._say(OPENING)

    async def reply(self, guest_said: str, *, interrupted: bool = False) -> str:
        note = " (They interrupted you.)" if interrupted else ""
        return await self._say(f"Guest{note}: {guest_said}")

    async def _say(self, prompt: str) -> str:
        turn = {"role": "user", "content": prompt}
        resp = await self.client.create(
            "anchor", [*self.history, turn], instructions=self.instructions
        )
        # Only a line that was actually produced joins the history; a cancelled one never did.
        self.history += [turn, {"role": "assistant", "content": resp.text}]
        return resp.text
