"""Code-switch detection.

A Hinglish sentence is not one language. In

    "Aaj ka episode AI tools ke baare mein hai"

``AI tools`` is English and everything else is Hindi. A single voice reading
all of it will mispronounce one half. This module splits the text into
language-labelled spans so a caller can route each span to the right voice.

Detection is **lexical**, not statistical: a word is English if it is in a
known English list or matches English-only spelling patterns, Hindi if it is
in the Hinglish list or matches Devanagari, and ambiguous otherwise. A
transformer would do better; a word list runs offline in microseconds and is
auditable, which for a pronunciation problem is usually worth more.

Pure standard library.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from .transliterate import is_devanagari

__all__ = [
    "ENGLISH_WORDS",
    "HINGLISH_WORDS",
    "Span",
    "AMBIGUOUS_WORDS",
    "label_word",
    "segment_spans",
    "english_fraction",
    "HINGLISH",
    "ENGLISH",
    "AMBIGUOUS",
]

HINGLISH = "hi"
ENGLISH = "en"
AMBIGUOUS = "?"

#: Words that are unambiguously Hindi/Hinglish in roman spelling.
#: Words spelled the same in both languages. Forcing them one way is wrong
#: half the time, so they are labelled ambiguous and resolved from their
#: neighbours by :func:`segment_spans`.
#:
#: ``the`` is the clearest case: it is both English "the" and Hindi थे (the
#: plural past of होना). ``to`` is English "to" and Hindi तो. A default would
#: be wrong constantly; context gets it right.
AMBIGUOUS_WORDS = frozenset("""
the to do hi me par se log kal sab kam haan hai hain
""".split())

HINGLISH_WORDS = frozenset("""
namaste namaskar dhanyavad shukriya kya kyon kyun hain tha thi aur ka
ki ke ko mein bhi ek chaar paanch chhah saat aath nau
das nahi nahin matlab yani accha achha arre yaar paisa paise rupaye kaam
log baat din aaj kuch bahut thoda zyada chai paani khana ghar dost
bhai dukaan bharat kaise kahan kab kitna kitne kitni mera tera humara aapka
tumhara iska uska wala wali wale ne tak sirf bilkul zaroori sahi galat sach
jhoot samajh samjha samjhi batao bata dena liya diya kiya hua hui hue raha
rahi rahe chalo theek thik bohot bahut paisa rupya sasta mehnga sarkar school
college naukri business dukaan shop customer grahak vyapar hisaab kitaab
zindagi zindgi waqt samay mauka koshish mehnat safalta nakaami seekhna sikhna
bolna sunna dekhna padhna likhna chalna aana jaana rehna khana peena sona
jaagna hasna rona gussa pyaar dosti parivaar maa baap beta beti
""".split())

#: Words that are unambiguously English — mostly the loanwords Indian creators
#: actually reach for, which is what makes the detection useful in practice.
ENGLISH_WORDS = frozenset("""
the a an and or but if then than that this these those is are was were be been
being have has had do does did will would can could should may might must shall
about above across after against along among around at before behind below
beneath beside between beyond by down during except for from in inside into like
near of off on onto out outside over past since through throughout till to
toward under until up upon with within without
software hardware code coding developer programming python javascript database
server cloud deploy deployment api database frontend backend stack framework
library runtime compiler debugger github git commit branch merge pipeline
startup product manager design designer user users customer client team meeting
sprint roadmap launch feature release version update upgrade download install
setup login signup password dashboard analytics metrics report email newsletter
marketing sales revenue profit growth strategy planning research testing
machine learning model training data algorithm network security privacy policy
ai tools tool app apps tech website link video videos audio podcast episode
episodes interview guest guests channel subscriber subscribers audience content
creator creators platform feature features idea ideas problem solution time
money work job career skill skills growth scale funding investor funding pitch
demo launch beta alpha sprint agile scrum standup retro review feedback testing
""".split())

# English-only spelling patterns: -tion/-sion/-ment/-ness/-ing endings and
# double vowels that Hindi romanisation does not produce.
_ENGLISH_PATTERNS = (
    re.compile(r"(tion|sion|ment|ness|ity|ous|able|ible|ance|ence)$"),
    re.compile(r"(ing|edly)$"),
    re.compile(r"[aeiou]{3}"),
)

# Hindi-only patterns.
#
# Only digraphs that English genuinely does not use are safe here. An earlier
# version included th/dh/ph/bh and "starts with a vowel" — which made "the"
# Hindi (th + e) and made almost every vowel-initial English word Hindi too.
# Doubled vowels stay, because aa/ee/oo/uu do not occur in ordinary English.
_HINGLISH_PATTERNS = (
    re.compile(r"(kh|gh|chh|jh)[aeiou]"),
    re.compile(r"(aa|ee|oo|uu)"),
)


def label_word(word: str) -> str:
    """``'hi'``, ``'en'`` or ``'?'`` for one word."""
    cleaned = re.sub(r"[^a-zA-Z\u0900-\u097f]", "", word)
    if not cleaned:
        return AMBIGUOUS
    if any(is_devanagari(c) for c in cleaned):
        return HINGLISH

    lowered = cleaned.lower()
    if lowered in AMBIGUOUS_WORDS:
        return AMBIGUOUS
    if lowered in HINGLISH_WORDS:
        return HINGLISH
    if lowered in ENGLISH_WORDS:
        return ENGLISH

    hindi_score = sum(1 for p in _HINGLISH_PATTERNS if p.search(lowered))
    english_score = sum(1 for p in _ENGLISH_PATTERNS if p.search(lowered))

    if hindi_score and not english_score:
        return HINGLISH
    if english_score and not hindi_score:
        return ENGLISH
    if hindi_score > english_score:
        return HINGLISH
    if english_score > hindi_score:
        return ENGLISH
    return AMBIGUOUS


@dataclass(frozen=True)
class Span:
    """A run of consecutive words in the same language."""

    language: str
    text: str
    start_word: int
    end_word: int

    @property
    def word_count(self) -> int:
        return self.end_word - self.start_word

    def to_dict(self) -> dict:
        return {"language": self.language, "text": self.text,
                "start_word": self.start_word, "end_word": self.end_word}


def segment_spans(
    text: str, *, merge_ambiguous_into: str = HINGLISH,
    min_span_words: int = 2,
) -> List[Span]:
    """Split text into language-labelled spans.

    Args:
        merge_ambiguous_into: a single ambiguous word between two Hindi spans
            is Hindi, not its own span. One-word English islands inside a
            Hindi sentence are almost always loanwords the Hindi voice will
            handle, so merging avoids a jarring voice switch. Set to
            ``AMBIGUOUS`` to keep them separate.
        min_span_words: spans shorter than this are absorbed into the
            surrounding language, for the same reason.

    >>> spans = segment_spans("Aaj ka episode AI tools ke baare mein hai")
    >>> [(s.language, s.text) for s in spans]
    [('hi', 'Aaj ka'), ('en', 'episode AI tools'), ('hi', 'ke baare mein hai')]
    """
    words = text.split()
    if not words:
        return []

    labels = [label_word(w) for w in words]

    # 1. resolve ambiguous words from their neighbours.
    #
    # Scan outward for the nearest *labelled* word on each side rather than
    # looking only at the immediate neighbour. Two words in a row can be
    # ambiguous ("the to"), and a sentence-initial "the" has no left
    # neighbour at all — both cases still have evidence, just not adjacent.
    def _nearest(direction: int, start: int) -> Optional[str]:
        position = start + direction
        while 0 <= position < len(labels):
            if labels[position] != AMBIGUOUS:
                return labels[position]
            position += direction
        return None

    for index, label in enumerate(labels):
        if label != AMBIGUOUS:
            continue
        previous = _nearest(-1, index)
        following = _nearest(1, index)
        if previous == following and previous is not None:
            labels[index] = previous
        elif previous is not None and following is None:
            labels[index] = previous
        elif following is not None and previous is None:
            labels[index] = following
        elif previous is not None and following is not None:
            # both sides known but they disagree — prefer the majority side,
            # falling back to the caller's default
            labels[index] = previous
        else:
            labels[index] = merge_ambiguous_into

    # 2. collapse runs of the same label
    spans: List[Span] = []
    start = 0
    for index in range(1, len(labels) + 1):
        if index == len(labels) or labels[index] != labels[start]:
            spans.append(Span(labels[start], " ".join(words[start:index]),
                              start, index))
            start = index

    # 3. absorb short islands into the larger surrounding span
    if min_span_words > 1 and len(spans) > 2:
        merged: List[Span] = []
        for span in spans:
            if (merged and span.word_count < min_span_words
                    and span.word_count < merged[-1].word_count):
                previous = merged[-1]
                merged[-1] = Span(
                    previous.language,
                    f"{previous.text} {span.text}",
                    previous.start_word, span.end_word)
            else:
                merged.append(span)
        spans = merged

    return spans


def english_fraction(text: str) -> float:
    """Share of words labelled English. Useful for picking a default voice.

    >>> round(english_fraction("Aaj ka episode AI tools ke baare mein hai"), 3)
    0.375
    """
    words = [w for w in text.split() if re.search(r"\w", w)]
    if not words:
        return 0.0
    return sum(1 for w in words if label_word(w) == ENGLISH) / len(words)
