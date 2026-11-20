from __future__ import annotations

import pytest

from amy.host.barge import looks_like_barge


@pytest.mark.parametrize("text", [
    "Hold on.", "Okay, wait, wait.", "Please, wait a minute.", "Hey, stop.", "Hey Chloe.",
    "Stop.", "Never mind.", "Alright, Chloe.", "Cancel that",
])
def test_interrupt_cues(text):
    assert looks_like_barge(text)


@pytest.mark.parametrize("text", [
    "Hey.", "Hey, look, look, look.", "You're gonna hold.", "Go ahead and hang out with them.",
    "I never said that", "", "You heard that?",
])
def test_room_chatter_does_not_interrupt(text):
    assert not looks_like_barge(text)
