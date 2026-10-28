import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from safety import is_crisis_message  # noqa: E402


@pytest.mark.parametrize(
    "message",
    [
        "I want to die",
        "I can't go on anymore",
        "i cant go on",
        "I can’t go on",  # curly apostrophe
        "thinking about SELF-HARM",
        "sometimes I feel suicidal",
        "I don't want to live like this",
        "Everyone would be better off dead without me",
    ],
)
def test_detects_crisis_language(message):
    assert is_crisis_message(message)


@pytest.mark.parametrize(
    "message",
    [
        "",
        "I had a stressful day at work",
        "This exam is killing me",
        "I'm dying to try that new cafe",
        "Tell me a joke",
    ],
)
def test_ignores_everyday_language(message):
    assert not is_crisis_message(message)
