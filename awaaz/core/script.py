"""Voiceover scripting.

Turns written text into something a voice can actually read: sentences split
where a breath belongs, pauses marked where the listener needs a beat,
emphasis placed on the words that carry the meaning, and a duration estimate
so you know whether the script fits the slot before you record.

Pure standard library.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

__all__ = [
    "Cue",
    "VoiceScript",
    "build_script",
    "estimate_duration",
    "reading_pace",
    "WORD_CHARS",
]

#: Hindi speech is syllable-timed and runs slightly faster than English in
#: words per minute, so one pace does not fit both.
DEFAULT_WPM = {"hi": 145.0, "en": 155.0, "?": 150.0}

#: Pauses in seconds, by trigger.
PAUSE = {
    "comma": 0.25,
    "sentence": 0.55,
    "paragraph": 1.10,
    "em_dash": 0.45,
    "ellipsis": 0.70,
    "colon": 0.35,
}

WORD_CHARS = re.compile(r"[\w\u0900-\u097f'-]+")

_SENTENCE_END = re.compile(r"(?<=[.!?\u0964])\s+")
_CLAUSE_SPLIT = re.compile(r"(?<=[,\u0964;:])\s+")


def reading_pace(language: str = "hi", *, wpm: Optional[float] = None) -> float:
    """Words per minute for a language."""
    if wpm is not None:
        if wpm <= 0:
            raise ValueError("wpm must be positive")
        return float(wpm)
    return DEFAULT_WPM.get(language, 150.0)


def estimate_duration(text: str, *, language: str = "hi",
                      wpm: Optional[float] = None,
                      extra_pause: float = 0.0) -> float:
    """Seconds to read ``text`` aloud, including the pauses in it.

    Word count over words-per-minute is crude but honest — it is accurate to
    within a couple of seconds for a paragraph, which is what you need to
    know whether a 60-second short is going to run long.

    >>> round(estimate_duration("ek do teen chaar paanch", wpm=60), 1)
    5.0
    """
    pace = reading_pace(language, wpm=wpm)
    words = len(WORD_CHARS.findall(text))
    speech = (words / pace) * 60.0

    pauses = 0.0
    pauses += text.count(",") * PAUSE["comma"]
    pauses += len(_SENTENCE_END.findall(text)) * PAUSE["sentence"]
    pauses += text.count("\n\n") * PAUSE["paragraph"]
    pauses += text.count("\u2014") * PAUSE["em_dash"]
    pauses += text.count("...") * PAUSE["ellipsis"]
    return round(speech + pauses + extra_pause, 2)


@dataclass(frozen=True)
class Cue:
    """One readable unit: a sentence or clause, with its pause after."""

    text: str
    pause_after: float = 0.0
    emphasise: Tuple[str, ...] = ()
    language: str = "hi"

    @property
    def word_count(self) -> int:
        return len(WORD_CHARS.findall(self.text))

    @property
    def duration(self) -> float:
        return estimate_duration(self.text, language=self.language,
                                 extra_pause=self.pause_after)

    def to_dict(self) -> dict:
        return {"text": self.text, "pause_after": self.pause_after,
                "emphasise": list(self.emphasise), "language": self.language,
                "word_count": self.word_count, "duration": self.duration}


@dataclass
class VoiceScript:
    """A complete, timed voiceover script."""

    cues: List[Cue] = field(default_factory=list)
    language: str = "hi"

    @property
    def text(self) -> str:
        return " ".join(cue.text for cue in self.cues)

    @property
    def word_count(self) -> int:
        return sum(cue.word_count for cue in self.cues)

    @property
    def duration(self) -> float:
        return round(sum(cue.duration for cue in self.cues), 2)

    @property
    def mmss(self) -> str:
        total = int(round(self.duration))
        return f"{total // 60:02d}:{total % 60:02d}"

    def fits(self, seconds: float) -> bool:
        """Whether the script fits a target slot, with a little slack."""
        return self.duration <= seconds

    def trim_to(self, seconds: float) -> "VoiceScript":
        """Drop trailing cues until the script fits.

        Dropping from the end rather than the middle keeps the script coherent
        — cutting the middle leaves a hole the listener notices.
        """
        if seconds <= 0:
            raise ValueError("seconds must be positive")
        kept: List[Cue] = []
        running = 0.0
        for cue in self.cues:
            if running + cue.duration > seconds and kept:
                break
            kept.append(cue)
            running += cue.duration
        return VoiceScript(cues=kept, language=self.language)

    def to_dict(self) -> dict:
        return {"language": self.language, "word_count": self.word_count,
                "duration": self.duration, "mmss": self.mmss,
                "cues": [c.to_dict() for c in self.cues]}

    def as_text(self) -> str:
        """Readable script with pause markers, for a human reading aloud."""
        out = []
        for cue in self.cues:
            line = cue.text
            if cue.emphasise:
                line += "   [emphasis: " + ", ".join(cue.emphasise) + "]"
            if cue.pause_after >= 0.4:
                line += "   [pause]"
            out.append(line)
        return "\n".join(out)


#: Words that carry meaning in a Hindi/Hinglish voiceover. Marking these makes
#: a flat TTS voice sound considerably less flat.
_EMPHASIS_MARKERS = frozenset("""
sabse zyada kam bilkul zaroori zaroori bilkul nahi haan kabhi hamesha pehli
pehla doosra teesra sirf ek hi bhi toh matlab important biggest best worst
never always everyone nobody first last problem solution secret truth
""".split())


def _emphasise(sentence: str, *, max_marks: int = 2) -> Tuple[str, ...]:
    """Pick the words worth stressing in a sentence."""
    found: List[str] = []
    for word in WORD_CHARS.findall(sentence):
        lowered = word.lower()
        if lowered in _EMPHASIS_MARKERS and lowered not in found:
            found.append(lowered)
        if len(found) >= max_marks:
            break
    # numbers and capitalised names also deserve stress
    if len(found) < max_marks:
        for word in WORD_CHARS.findall(sentence):
            if re.search(r"\d", word) and word.lower() not in found:
                found.append(word.lower())
            if len(found) >= max_marks:
                break
    return tuple(found)


def build_script(
    text: str,
    *,
    language: str = "hi",
    max_words_per_cue: int = 18,
    mark_emphasis: bool = True,
    wpm: Optional[float] = None,
) -> VoiceScript:
    """Split prose into readable, timed cues.

    Sentences are split first. Any sentence longer than ``max_words_per_cue``
    is then split on commas, because a TTS voice that runs 30 words without a
    breath sounds like it is rushing — and a human reading it will be.

    >>> script = build_script("Namaste dosto. Aaj hum baat karenge.", language="hi")
    >>> len(script.cues)
    2
    """
    if not text or not text.strip():
        return VoiceScript(language=language)

    # normalise the paragraph breaks so pauses can be measured
    normalised = re.sub(r"\r\n?", "\n", text.strip())
    normalised = re.sub(r"\u2013|\u2014", " \u2014 ", normalised)

    cues: List[Cue] = []
    for paragraph in re.split(r"\n{2,}", normalised):
        paragraph = paragraph.strip()
        if not paragraph:
            continue

        sentences = [s.strip() for s in _SENTENCE_END.split(paragraph) if s.strip()]
        for index, sentence in enumerate(sentences):
            chunks = [sentence]
            if len(WORD_CHARS.findall(sentence)) > max_words_per_cue:
                chunks = [c.strip() for c in _CLAUSE_SPLIT.split(sentence) if c.strip()]

            for chunk_index, chunk in enumerate(chunks):
                is_last_chunk = chunk_index == len(chunks) - 1
                if not is_last_chunk:
                    pause = PAUSE["comma"]
                elif index == len(sentences) - 1:
                    pause = PAUSE["paragraph"]
                else:
                    pause = PAUSE["sentence"]
                if "\u2014" in chunk:
                    pause = max(pause, PAUSE["em_dash"])
                if chunk.rstrip().endswith("..."):
                    pause = max(pause, PAUSE["ellipsis"])

                cues.append(Cue(
                    text=chunk, pause_after=pause,
                    emphasise=_emphasise(chunk) if mark_emphasis else (),
                    language=language))

    return VoiceScript(cues=cues, language=language)
