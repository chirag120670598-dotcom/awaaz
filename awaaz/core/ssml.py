"""SSML generation.

SSML is the one thing that makes a stock TTS voice tolerable: pauses, rate,
pitch and per-word emphasis. Most Indic TTS setups skip it entirely and then
wonder why the output sounds like a navigation system.

.. warning::
   SSML support varies wildly. Amazon Polly and Azure support most of this;
   ``espeak-ng`` supports almost none of it. :func:`strip_ssml` produces a
   plain-text fallback for engines that will not take markup.

Standard library only (``xml.sax.saxutils`` for escaping).
"""

from __future__ import annotations

from typing import Iterable, List, Optional, Sequence
from xml.sax.saxutils import escape

from .script import Cue, VoiceScript

__all__ = ["SSML", "build_ssml", "strip_ssml"]


class SSML:
    """A tiny SSML builder.

    Tags are escaped on the way in, so transcript text containing ``&`` or
    ``<`` cannot break the document — a real risk, because Indian business
    names are full of them ("Ravi & Sons").
    """

    def __init__(self, *, lang: str = "hi-IN", rate: str = "medium",
                 pitch: str = "medium", volume: str = "medium") -> None:
        self.lang = lang
        self.rate = rate
        self.pitch = pitch
        self.volume = volume
        self._body: List[str] = []

    # -- primitives --------------------------------------------------------

    def say(self, text: str, *, emphasis: Optional[str] = None,
            lang: Optional[str] = None, rate: Optional[str] = None) -> "SSML":
        """A run of text, optionally wrapped in emphasis or a language switch."""
        content = escape(str(text))
        if not content.strip():
            return self
        if emphasis:
            content = f'<emphasis level="{escape(emphasis)}">{content}</emphasis>'
        if lang:
            content = f'<lang xml:lang="{escape(lang)}">{content}</lang>'
        if rate:
            content = f'<prosody rate="{escape(rate)}">{content}</prosody>'
        self._body.append(content)
        return self

    def pause(self, ms: int) -> "SSML":
        """A break. Negative or zero durations are dropped, not clamped —
        a zero-length break is markup for nothing."""
        if ms <= 0:
            return self
        self._body.append(f'<break time="{int(ms)}ms"/>')
        return self

    def break_strength(self, strength: str) -> "SSML":
        if strength not in ("none", "x-weak", "weak", "medium", "strong", "x-strong"):
            raise ValueError(f"unknown break strength: {strength!r}")
        self._body.append(f'<break strength="{strength}"/>')
        return self

    def prosody(self, text: str, *, rate: Optional[str] = None,
                pitch: Optional[str] = None, volume: Optional[str] = None) -> "SSML":
        attrs = []
        if rate:
            attrs.append(f'rate="{escape(rate)}"')
        if pitch:
            attrs.append(f'pitch="{escape(pitch)}"')
        if volume:
            attrs.append(f'volume="{escape(volume)}"')
        if not attrs:
            return self.say(text)
        self._body.append(
            f'<prosody {" ".join(attrs)}>{escape(text)}</prosody>')
        return self

    def emphasise_words(self, text: str, words: Sequence[str],
                        *, level: str = "moderate") -> "SSML":
        """Wrap specific words in ``<emphasis>``, leaving the rest plain."""
        if not words:
            return self.say(text)
        marked = set(w.lower() for w in words)
        out: List[str] = []
        for token in str(text).split():
            bare = token.strip(".,!?\u0964;:\"'()")
            if bare.lower() in marked:
                # keep the punctuation outside the tag so it still renders
                prefix = token[: len(token) - len(token.lstrip(".,!?\u0964;:\"'()"))]
                suffix = token[len(token.rstrip(".,!?\u0964;:\"'()")):]
                out.append(
                    f'{prefix}<emphasis level="{escape(level)}">'
                    f'{escape(bare)}</emphasis>{suffix}')
            else:
                out.append(escape(token))
        self._body.append(" ".join(out))
        return self

    def sub(self, text: str, alias: str) -> "SSML":
        """Pronounce ``text`` as ``alias`` — the escape hatch for names."""
        self._body.append(f'<sub alias="{escape(alias)}">{escape(text)}</sub>')
        return self

    def paragraph(self, text: str) -> "SSML":
        self._body.append(f"<p>{escape(text)}</p>")
        return self

    # -- output ------------------------------------------------------------

    def build(self) -> str:
        """A complete SSML document."""
        body = "\n  ".join(self._body)
        return (
            '<speak version="1.1" xmlns="http://www.w3.org/2001/10/synthesis" '
            f'xml:lang="{escape(self.lang)}">\n'
            f'  <prosody rate="{escape(self.rate)}" pitch="{escape(self.pitch)}" '
            f'volume="{escape(self.volume)}">\n  {body}\n  </prosody>\n</speak>\n'
        )

    def __str__(self) -> str:
        return self.build()


def build_ssml(
    script: VoiceScript,
    *,
    lang: str = "hi-IN",
    rate: str = "medium",
    pitch: str = "medium",
    volume: str = "medium",
    emphasise: bool = True,
) -> str:
    """Render a :class:`~awaaz.core.script.VoiceScript` as SSML.

    Each cue's ``pause_after`` becomes a real ``<break>``, which is what makes
    the output sound like someone speaking rather than something reading.
    """
    ssml = SSML(lang=lang, rate=rate, pitch=pitch, volume=volume)
    for cue in script.cues:
        if emphasise and cue.emphasise:
            ssml.emphasise_words(cue.text, cue.emphasise)
        else:
            ssml.say(cue.text)
        ssml.pause(int(cue.pause_after * 1000))
    return ssml.build()


def strip_ssml(ssml: str) -> str:
    """Plain text from SSML, for engines that cannot take markup.

    Breaks become spaces rather than disappearing, so the words do not run
    together.
    """
    import re
    out = re.sub(r"<break[^>]*/>", " ", ssml)
    out = re.sub(r"<[^>]+>", "", out)
    return re.sub(r"[ \t]+", " ", out).strip()
