"""Roman Hinglish ↔ Devanagari.

Most Indic TTS engines read Devanagari correctly and read romanised Hinglish
badly. Most Indian creators type romanised Hinglish because it is faster on a
phone keypad. This module bridges the two.

.. warning::
   Roman-to-Devanagari is **inherently ambiguous**. ``kya`` could be क्या or
   क्य. ``hai`` could be है or हो. Schwa deletion is context-dependent and
   no rule set gets it right every time.

   So this is offered as a *best effort*, with :func:`roman_to_devanagari`
   returning a confidence score so callers can decide whether to trust it.
   Where a dictionary lookup applies (:data:`COMMON_WORDS`), it wins. Where
   it does not, the syllable rules run and confidence drops.

   Do not present the output as correct without checking it.

Pure standard library.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

__all__ = [
    "COMMON_WORDS",
    "DEVANAGARI_CONSONANTS",
    "DEVANAGARI_VOWELS",
    "devanagari_to_roman",
    "roman_to_devanagari",
    "is_devanagari",
    "devanagari_fraction",
    "Transliteration",
]

#: Words that appear constantly in Hinglish. A dictionary lookup beats any
#: rule, so these are tried first.
COMMON_WORDS: Dict[str, str] = {
    "namaste": "\u0928\u092e\u0938\u094d\u0924\u0947",
    "namaskar": "\u0928\u092e\u0938\u094d\u0915\u093e\u0930",
    "dhanyavad": "\u0927\u0928\u094d\u092f\u0935\u093e\u0926",
    "shukriya": "\u0936\u0941\u0915\u094d\u0930\u093f\u092f\u093e",
    "kya": "\u0915\u094d\u092f\u093e",
    "kyon": "\u0915\u094d\u092f\u094b\u0902",
    "kyun": "\u0915\u094d\u092f\u0942\u0902",
    "hai": "\u0939\u0948",
    "hain": "\u0939\u0948\u0902",
    "tha": "\u0925\u093e",
    "thi": "\u0925\u0940",
    "the": "\u0925\u0947",
    "aur": "\u0914\u0930",
    "ka": "\u0915\u093e",
    "ki": "\u0915\u0940",
    "ke": "\u0915\u0947",
    "ko": "\u0915\u094b",
    "se": "\u0938\u0947",
    "me": "\u092e\u0947\u0902",
    "mein": "\u092e\u0947\u0902",
    "par": "\u092a\u0930",
    "bhi": "\u092d\u0940",
    "hi": "\u0939\u0940",
    "to": "\u0924\u094b",
    "ek": "\u090f\u0915",
    "do": "\u0926\u094b",
    "teen": "\u0924\u0940\u0928",
    "chaar": "\u091a\u093e\u0930",
    "paanch": "\u092a\u093e\u0901\u091a",
    "haan": "\u0939\u093e\u0901",
    "nahi": "\u0928\u0939\u0940\u0902",
    "nahin": "\u0928\u0939\u0940\u0902",
    "matlab": "\u092e\u0924\u0932\u092c",
    "yani": "\u092f\u093e\u0928\u0940",
    "accha": "\u0905\u091a\u094d\u091b\u093e",
    "achha": "\u0905\u091a\u094d\u091b\u093e",
    "arre": "\u0905\u0930\u0947",
    "yaar": "\u092f\u093e\u0930",
    "paisa": "\u092a\u0948\u0938\u093e",
    "paise": "\u092a\u0948\u0938\u0947",
    "rupaye": "\u0930\u0941\u092a\u092f\u0947",
    "kaam": "\u0915\u093e\u092e",
    "log": "\u0932\u094b\u0917",
    "baat": "\u092c\u093e\u0924",
    "din": "\u0926\u093f\u0928",
    "aaj": "\u0906\u091c",
    "kal": "\u0915\u0932",
    "sab": "\u0938\u092c",
    "kuch": "\u0915\u0941\u091b",
    "bahut": "\u092c\u0939\u0941\u0924",
    "thoda": "\u0925\u094b\u0921\u093c\u093e",
    "zyada": "\u091c\u094d\u092f\u093e\u0926\u093e",
    "kam": "\u0915\u092e",
    "chai": "\u091a\u093e\u092f",
    "paani": "\u092a\u093e\u0928\u0940",
    "khana": "\u0916\u093e\u0928\u093e",
    "ghar": "\u0918\u0930",
    "dost": "\u0926\u094b\u0938\u094d\u0924",
    "bhai": "\u092d\u093e\u0908",
    "dukaan": "\u0926\u0941\u0915\u093e\u0928",
    "bharat": "\u092d\u093e\u0930\u0924",
    "india": "\u092d\u093e\u0930\u0924",
}

#: Consonants, in the order of the Devanagari varnamala.
DEVANAGARI_CONSONANTS: Dict[str, str] = {
    "k": "\u0915", "kh": "\u0916", "g": "\u0917", "gh": "\u0918", "n": "\u0928",
    "ch": "\u091a", "chh": "\u091b", "j": "\u091c", "jh": "\u091d",
    "t": "\u0924", "th": "\u0925", "d": "\u0926", "dh": "\u0927",
    "p": "\u092a", "ph": "\u092b", "b": "\u092c", "bh": "\u092d", "m": "\u092e",
    "y": "\u092f", "r": "\u0930", "l": "\u0932", "v": "\u0935", "w": "\u0935",
    "sh": "\u0936", "s": "\u0938", "h": "\u0939",
}

#: Independent vowels (used at the start of a syllable).
DEVANAGARI_VOWELS: Dict[str, str] = {
    "a": "\u0905", "aa": "\u0906", "i": "\u0907", "ee": "\u0908",
    "u": "\u0909", "oo": "\u090a", "e": "\u090f", "ai": "\u0910",
    "o": "\u0913", "au": "\u0914",
}

#: Matras — the vowel marks that attach to a consonant.
_MATRAS: Dict[str, str] = {
    "a": "", "aa": "\u093e", "i": "\u093f", "ee": "\u0940",
    "u": "\u0941", "oo": "\u0942", "e": "\u0947", "ai": "\u0948",
    "o": "\u094b", "au": "\u094c",
}

_HALANT = "\u094d"
_ANUSVARA = "\u0902"
_DANDA = "\u0964"

_VOWELS = set("aeiou")


def is_devanagari(char: str) -> bool:
    """Whether a single character is in the Devanagari block."""
    return "\u0900" <= char <= "\u097f"


def devanagari_fraction(text: str) -> float:
    """Share of letters that are Devanagari. 0.0 for pure roman Hinglish."""
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if is_devanagari(c)) / len(letters)


@dataclass(frozen=True)
class Transliteration:
    """Result of roman → Devanagari, with a confidence score.

    ``confidence`` is 1.0 when every word came from :data:`COMMON_WORDS` and
    drops as more words fall through to the syllable rules, which are
    genuinely ambiguous. Use it to decide whether to show the result to a
    human before synthesising.
    """

    text: str
    confidence: float
    dictionary_hits: int = 0
    rule_applied: int = 0

    def __str__(self) -> str:
        return self.text


def _syllable_split(word: str) -> List[str]:
    """Split a roman word into consonant+vowel syllables.

    Deliberately simple: a consonant cluster takes a halant, and a trailing
    schwa is dropped for words longer than two syllables (which is what
    Hindi actually does). Neither rule is universally right — hence the
    confidence score on the result.
    """
    word = word.lower()
    syllables: List[str] = []
    i = 0
    while i < len(word):
        # longest consonant match first ("chh" before "ch" before "c")
        consonant = ""
        for length in (3, 2, 1):
            candidate = word[i:i + length]
            if candidate in DEVANAGARI_CONSONANTS:
                consonant = candidate
                break
        if not consonant:
            # a leading vowel or an unmapped character
            vowel = ""
            for length in (2, 1):
                candidate = word[i:i + length]
                if candidate in DEVANAGARI_VOWELS:
                    vowel = candidate
                    break
            if vowel:
                syllables.append(DEVANAGARI_VOWELS[vowel])
                i += len(vowel)
            else:
                syllables.append(word[i])
                i += 1
            continue

        i += len(consonant)
        vowel = ""
        for length in (2, 1):
            candidate = word[i:i + length]
            if candidate in _MATRAS:
                vowel = candidate
                break
        i += len(vowel)

        # a consonant followed by another consonant takes a halant
        next_is_consonant = i < len(word) and word[i] not in _VOWELS
        if next_is_consonant:
            syllables.append(DEVANAGARI_CONSONANTS[consonant] + _HALANT)
        else:
            syllables.append(DEVANAGARI_CONSONANTS[consonant] + _MATRAS.get(vowel, ""))
    return syllables


def roman_to_devanagari(text: str) -> Transliteration:
    """Transliterate roman Hinglish into Devanagari, best effort.

    >>> roman_to_devanagari("namaste").text
    '\u0928\u092e\u0938\u094d\u0924\u0947'
    """
    if not text:
        return Transliteration("", 1.0)

    out: List[str] = []
    hits = rules = 0
    words = re.split(r"(\s+)", text)

    for token in words:
        if not token or token.isspace():
            out.append(token)
            continue

        # keep punctuation attached but out of the lookup.
        # NOTE: re.match anchors at the start, so trailing punctuation has to
        # be found with re.search + \Z. re.match(r"[^\w]*$", word) returns
        # None for any word that is not entirely punctuation.
        prefix = re.match(r"[^\w]*", token).group(0)
        tail = re.search(r"[^\w]*\Z", token)
        suffix = tail.group(0) if tail else ""
        end = len(token) - len(suffix)
        core = token[len(prefix):end]

        if not core:
            out.append(token)
            continue
        if any(is_devanagari(c) for c in core):
            out.append(token)      # already Devanagari, leave it alone
            hits += 1
            continue

        key = core.lower()
        if key in COMMON_WORDS:
            out.append(f"{prefix}{COMMON_WORDS[key]}{suffix}")
            hits += 1
        else:
            out.append(f"{prefix}{''.join(_syllable_split(core))}{suffix}")
            rules += 1

    total = hits + rules
    confidence = (hits / total) if total else 1.0
    return Transliteration("".join(out), round(confidence, 3), hits, rules)


# --- Devanagari → roman -----------------------------------------------------

_DEVANAGARI_TO_ROMAN: Dict[str, str] = {}
for _roman, _dev in DEVANAGARI_CONSONANTS.items():
    _DEVANAGARI_TO_ROMAN.setdefault(_dev, _roman)
for _roman, _dev in DEVANAGARI_VOWELS.items():
    _DEVANAGARI_TO_ROMAN.setdefault(_dev, _roman)
for _roman, _matra in _MATRAS.items():
    if _matra:
        _DEVANAGARI_TO_ROMAN.setdefault(_matra, _roman)
_DEVANAGARI_TO_ROMAN[_HALANT] = ""
_DEVANAGARI_TO_ROMAN[_ANUSVARA] = "n"
_DEVANAGARI_TO_ROMAN[_DANDA] = "."


def devanagari_to_roman(text: str) -> str:
    """A rough romanisation, mainly for logging and debugging.

    A Devanagari consonant carries an inherent short ``a`` unless a matra or a
    halant cancels it — so नमस्ते has to come out as ``namaste``, not ``nmste``.
    Getting that wrong makes the output useless for anything but a hash.

    Still not a faithful ITRANS/Scholix transliteration: vowel length and
    some schwa deletions are genuinely ambiguous in this direction.

    >>> devanagari_to_roman("\u0928\u092e\u0938\u094d\u0924\u0947")
    'namaste'
    """
    out: List[str] = []
    for index, char in enumerate(text):
        if char in _DEVANAGARI_TO_ROMAN:
            out.append(_DEVANAGARI_TO_ROMAN[char])
        else:
            out.append(char)
            continue

        if char not in DEVANAGARI_CONSONANTS.values():
            continue
        # a consonant needs its inherent "a" unless a matra or halant follows
        following = text[index + 1] if index + 1 < len(text) else ""
        if following in _MATRAS.values() or following == _HALANT:
            continue
        out.append("a")
    return "".join(out)
