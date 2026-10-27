"""Anchor: the on-air interviewer. One short spoken line per guest turn.

The anchor keeps the interview history itself and resends it each turn, rather than chaining
on `previous_response_id`. Measured 2026-10-27 on muse-spark-1.3 with a 4.5 kB brief: a
chained call took ~10 s every time, the same call with the history resent 1.0-2.0 s (the
instructions and earlier turns hit the prompt cache). At `minimal` effort there is little
reasoning to carry over, so nothing is lost.
"""

from __future__ import annotations

from studio.agents.policy import GUARDRAILS
from studio.meta.responses import ResponsesClient

INSTRUCTIONS = (
    """\
You are the anchor of a live IoMarkets.tv interview. The topic is whatever the brief says:
business, science, sport, culture, a guest's own work. You speak, so write only
the words you will say: no lists, no stage directions, no markdown.

Each reply is one or two sentences, under 45 words. React briefly to what the guest just said,
then ask one question. Follow up when an answer is vague or a figure needs context; otherwise
move to the next topic in the brief. Vary how you open; never start two replies the same way.

The guest's words come from live speech recognition and may contain mistakes; read through
them. If the guest interrupted you, take it in your stride.

You work with a Devil's Advocate, a colleague who checks the guest's claims as they talk. Its
notes may follow the guest's words. If a note says a figure is contradicted, raise it politely
in this reply, give the correct figure and its source in plain words, and let the guest
respond. If a note suggests a challenge, put it when it fits the conversation. Never accuse;
the guest may have a newer or narrower number. The brief's PRESSURE POINTS are the Devil's
Advocate's too: work the strongest of them into your questions.

In a cold start you know nothing about the guest in advance. Live research may follow the
guest's words: use it to ask informed follow-ups, and never say you are reading research.

"""
    + GUARDRAILS
    + """
THE BRIEF
"""
)

OPENING = "We are live. Welcome the guest by name in one sentence, then ask your first question."
COLD_OPENING = (
    "We are live, cold: you know nothing about the guest yet. Welcome them warmly in one "
    "sentence and ask them to introduce themselves and what they are working on."
)
COLD_BRIEF = (
    "COLD START: no brief. Everything you learn comes from the guest, from live research and "
    "from the Devil's Advocate as the interview runs."
)


class Anchor:
    def __init__(self, client: ResponsesClient, brief: str, *, cold: bool = False):
        self.client = client
        self.cold = cold
        self.instructions = INSTRUCTIONS + (COLD_BRIEF if cold else brief)
        self.history: list[dict[str, str]] = []

    async def opening(self) -> str:
        return await self._say(COLD_OPENING if self.cold else OPENING)

    async def reply(
        self,
        guest_said: str,
        *,
        interrupted: bool = False,
        notes: list[str] = (),
        research: str = "",
    ) -> str:
        note = " (They interrupted you.)" if interrupted else ""
        checks = "".join(f"\n[Devil's Advocate: {n}]" for n in notes)
        found = f"\n[Live research:\n{research}]" if research else ""
        return await self._say(f"Guest{note}: {guest_said}{checks}{found}")

    async def _say(self, prompt: str) -> str:
        turn = {"role": "user", "content": prompt}
        resp = await self.client.create(
            "anchor", [*self.history, turn], instructions=self.instructions
        )
        # Only a line that was actually produced joins the history; a cancelled one never did.
        self.history += [turn, {"role": "assistant", "content": resp.text}]
        return resp.text
