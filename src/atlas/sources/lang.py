"""Language detection for comment text via lingua.

The detector is built lazily on first call (model loading is expensive) and
restricted to English plus the languages plausibly seen on HN, so ambiguous
short texts do not scatter across lingua's full set. URLs are stripped before
detection; callers should pass HTML-free text with code blocks already removed
(`htmltext.html_to_text(text, drop_pre=True)`).
"""

from __future__ import annotations

import re

_URL = re.compile(r"https?://\S+")
_MIN_WORDS = 5
_EN_THRESHOLD = 0.2

_detector = None


def _get_detector():
    global _detector
    if _detector is None:
        from lingua import Language, LanguageDetectorBuilder

        _detector = LanguageDetectorBuilder.from_languages(
            Language.ENGLISH,
            Language.GERMAN,
            Language.FRENCH,
            Language.SPANISH,
            Language.PORTUGUESE,
            Language.ITALIAN,
            Language.DUTCH,
            Language.RUSSIAN,
            Language.POLISH,
            Language.CHINESE,
            Language.JAPANESE,
            Language.KOREAN,
            Language.TURKISH,
            Language.SWEDISH,
            Language.UKRAINIAN,
        ).build()
    return _detector


def detect_many(texts: list[str]) -> list[str]:
    """ISO 639-1 code per text; "und" for short or undecidable input.

    A text counts as English when English is the top language or its confidence
    is at least 0.2, which keeps code- and quote-heavy English comments "en".
    """
    from lingua import Language

    cleaned = [_URL.sub(" ", t) if t else "" for t in texts]
    out = ["und"] * len(cleaned)
    idx = [i for i, t in enumerate(cleaned) if len(t.split()) >= _MIN_WORDS]
    if not idx:
        return out
    detector = _get_detector()
    results = detector.compute_language_confidence_values_in_parallel(
        [cleaned[i] for i in idx]
    )
    for i, values in zip(idx, results):
        # All-zero confidences mean the text had no signal (e.g. punctuation or
        # digits); lingua still emits every language in that case.
        if not values or values[0].value == 0.0:
            continue
        top = values[0].language
        en = next((v.value for v in values if v.language == Language.ENGLISH), 0.0)
        if top == Language.ENGLISH or en >= _EN_THRESHOLD:
            out[i] = "en"
        else:
            out[i] = top.iso_code_639_1.name.lower()
    return out
