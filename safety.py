"""Crisis-language detection shared by every chat path.

One list, one normaliser, so the chat route, the AI pipeline and the
offline fallback can never disagree about what counts as a crisis message.
"""
import re
import unicodedata

CRISIS_TERMS = (
    "suicide",
    "suicidal",
    "kill myself",
    "end my life",
    "end it all",
    "self harm",
    "hurt myself",
    "cut myself",
    "hang myself",
    "want to die",
    "better off dead",
    "no reason to live",
    "cant go on",
    "i dont want to live",
    "i want to disappear",
)


def normalize(text: str) -> str:
    """Lowercase, unify unicode, drop apostrophes and collapse punctuation/space.

    "Can't", "can’t" and "cant" all become "cant"; "self-harm" becomes "self harm".
    """
    text = unicodedata.normalize("NFKC", text or "").lower()
    text = re.sub(r"['’`]", "", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return f" {text.strip()} "


def is_crisis_message(text: str) -> bool:
    """True when the message contains any crisis phrase as whole words."""
    padded = normalize(text)
    return any(f" {term} " in padded for term in CRISIS_TERMS)
