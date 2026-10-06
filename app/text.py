"""Small text helpers shared by the workflow and the fallback."""

from __future__ import annotations

import re

STOPWORDS = set("""a an the is are was were be been of in on for to and or what which who how when where why
do does did i my me am can could should would will you your it its this that there their with from by at as
any have has had about into than then so if not no yes required require need needs minimum maximum
rule rules policy university nsut student students""".split())


def content_words(text: str) -> set[str]:
    """Lower-cased content words cut to 6 letters (a cheap stem: 'attendance' ~ 'attend')."""
    return {w[:6] for w in re.findall(r"[a-z]{3,}", text.lower()) if w not in STOPWORDS}


def overlap(question: str, text: str) -> int:
    return len(content_words(question) & content_words(text))
