from __future__ import annotations

from types import SimpleNamespace

from studio.agents.anchor import ANGLES, INSTRUCTIONS, Anchor


class FakeClient:
    def __init__(self):
        self.prompts: list[str] = []

    async def create(self, role, input, instructions):
        self.prompts.append(input[-1]["content"])
        return SimpleNamespace(text=f"Question {len(self.prompts)}?")


async def test_each_turn_suggests_a_different_angle():
    client = FakeClient()
    anchor = Anchor(client, "GUEST: Jane Doe")
    await anchor.opening()
    for said in ["I run a fund.", "We grew 20%.", "Mostly Europe."]:
        await anchor.reply(said)
    suggested = [p.split("Suggested angle")[1] for p in client.prompts[1:]]
    assert len(set(suggested)) == 3  # three replies, three different shapes of question
    assert ANGLES[0] in suggested[0] and ANGLES[1] in suggested[1]
    assert "Suggested angle" not in client.prompts[0]  # the opening is left to the anchor


def test_instructions_ban_repeats_and_stock_praise():
    assert "Never ask a question you have asked before" in INSTRUCTIONS
    assert "That's fascinating" in INSTRUCTIONS
