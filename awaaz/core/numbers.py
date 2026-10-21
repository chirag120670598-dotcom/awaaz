"""Numbers, currency, dates and units spoken in Hinglish.

A TTS engine handed ``₹12,34,567`` will read it as gibberish. Handed
``barah lakh chautis hazaar paanch sau sath rupaye`` it reads it correctly.
This module does the translation, using **Indian grouping** — lakh and crore,
not million and billion, because that is how the listener counts.

Pure standard library.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import List, Optional, Tuple

__all__ = [
    "number_to_hinglish",
    "ordinal_to_hinglish",
    "money_to_hinglish",
    "date_to_hinglish",
    "phone_to_hinglish",
    "expand_numbers",
]

# Hindi has a distinct word for every number from 1 to 99 — it does not
# compose them the way English does. 34 is "chautis", not "tees chaar".
# Composing them would produce something no Hindi speaker says.
_ONES_TO_NINETYNINE = [
    "", "ek", "do", "teen", "chaar", "paanch", "chhah", "saat", "aath", "nau",
    "das", "gyarah", "barah", "terah", "chaudah", "pandrah", "solah",
    "satrah", "atharah", "unnis",
    "bees", "ikkis", "bais", "tees", "chaud", "pachchis", "chhabbis",
    "sattaais", "attais", "untees",
    "tees", "iktees", "batees", "taintees", "chautis", "painted", "chattees",
    "saintees", "atees", "untalis",
    "chalees", "iktalis", "bayalis", "taintalis", "chautalis", "paintedalis",
    "chhayalis", "saintalis", "athtalis", "unachas",
    "pachaas", "ikyaavan", "baavan", "taipan", "chaupan", "pachpan",
    "chhappan", "sattaavan", "atthavan", "unsath",
    "saath", "iksath", "baasath", "taisath", "chaunsath", "painsath",
    "chhiyasath", "sathsath", "athsath", "unhattar",
    "sattar", "iktahattar", "bahattar", "tihattar", "chauhattar", "pachhattar",
    "chhihattar", "satahattar", "athhattar", "unasi",
    "assi", "ikyasi", "bayasi", "tirasi", "chaursi", "pachasi", "chhayasi",
    "sataasi", "athasi", "navasi",
    "nabbe", "ikyanve", "bayanve", "tiranve", "chaunve", "pachanve",
    "chhiyanve", "sattanve", "athanve", "ninyanve",
]

# Kept for the handful of places that build words from parts (hundreds).
_ONES = [
    "", "ek", "do", "teen", "chaar", "paanch", "chhah", "saat", "aath", "nau",
    "das", "gyarah", "barah", "terah", "chaudah", "pandrah", "solah",
    "satrah", "atharah", "unnis",
]

#: Spoken digit by digit — phone numbers, PINs, OTPs.
_DIGITS = ["zero", "ek", "do", "teen", "chaar", "paanch", "chhah", "saat",
           "aath", "nau"]

_SCALE = _SCALE = ((10_000_000, "karod"), (100_000, "lakh"), (1_000, "hazaar"))


def _two_digits(n: int) -> str:
    """1-99 as a single Hindi word. Hindi has no "twenty four"."""
    if not 0 <= n <= 99:
        raise ValueError(f"_two_digits takes 0-99, got {n}")
    return _ONES_TO_NINETYNINE[n]


def _three_digits(n: int) -> str:
    hundred, rest = divmod(n, 100)
    head = f"{_ONES[hundred]} sau" if hundred else ""
    tail = _two_digits(rest) if rest else ""
    return f"{head} {tail}".strip()


def number_to_hinglish(value) -> str:
    """An integer spoken in Hinglish, using lakh and crore.

    >>> number_to_hinglish(1234567)
    'barah lakh chautis hazaar paanch sau sath'
    >>> number_to_hinglish(1000)
    'ek hazaar'
    >>> number_to_hinglish(100)
    'ek sau'
    """
    n = int(value)
    if n == 0:
        return "zero"
    negative = n < 0
    n = abs(n)

    parts: List[str] = []
    for divisor, label in _SCALE:
        amount, n = divmod(n, divisor)
        if amount:
            chunk = _two_digits(amount) if amount < 100 else _three_digits(amount)
            parts.append(f"{chunk} {label}")
    if n:
        parts.append(_two_digits(n) if n < 100 else _three_digits(n))

    out = " ".join(parts)
    return f"minus {out}" if negative else out


def ordinal_to_hinglish(value) -> str:
    """``1`` → ``pehla``. Only the common small ordinals are special-cased;
    the rest fall back to ``number + van``, which is how they are said."""
    n = int(value)
    special = {1: "pehla", 2: "doosra", 3: "teesra", 4: "chautha", 5: "paanchvan",
               6: "chhata", 7: "saatvan", 8: "aathvan", 9: "nauvan", 10: "dasvan"}
    if n in special:
        return special[n]
    return f"{number_to_hinglish(n)}van"


def money_to_hinglish(value, *, currency: str = "INR") -> str:
    """An amount spoken with the right currency word and paise.

    >>> money_to_hinglish("1234.50")
    'ek hazaar do sau chautis rupaye pachas paise'
    >>> money_to_hinglish(1000)
    'ek hazaar rupaye'
    >>> money_to_hinglish(5, currency="USD")
    'paanch dollar'
    """
    words = {
        "INR": ("rupaye", "paise"),
        "USD": ("dollar", "cent"),
        "EUR": ("euro", "cent"),
        "GBP": ("pound", "penny"),
        "AED": ("dirham", "fils"),
    }
    major, minor = words.get(currency.upper(), ("rupaye", "paise"))
    amount = Decimal(str(value))
    whole = int(amount)
    paise = int(round((amount - whole) * 100))

    out = f"{number_to_hinglish(whole)} {major}" if whole else ""
    if paise:
        out = f"{out} {number_to_hinglish(paise)} {minor}".strip()
    return out or f"zero {major}"


_MONTHS = {
    1: "january", 2: "february", 3: "march", 4: "april", 5: "may", 6: "june",
    7: "july", 8: "august", 9: "september", 10: "october", 11: "november",
    12: "december",
}


def date_to_hinglish(day: int, month: int, year: Optional[int] = None) -> str:
    """``(15, 8, 2026)`` → ``pandrah august do hazaar chhabbis``.

    >>> date_to_hinglish(15, 8, 2026)
    'pandrah august do hazaar chhabbis'
    """
    if not 1 <= month <= 12:
        raise ValueError(f"month must be 1-12, got {month}")
    out = f"{number_to_hinglish(day)} {_MONTHS[month]}"
    if year is not None:
        out += f" {number_to_hinglish(year)}"
    return out


def phone_to_hinglish(digits: str) -> str:
    """A phone number read digit by digit, the way it is actually said.

    ``number_to_hinglish`` would read ``9876543210`` as ninety-eight crore
    …, which is useless for dialling.

    >>> phone_to_hinglish("9876543210")
    'nau aath saat chhah paanch chaar teen do ek zero'
    """
    spoken = " ".join(_DIGITS[int(ch)] for ch in str(digits) if ch.isdigit())
    if not spoken:
        raise ValueError("phone_to_hinglish needs at least one digit")
    return spoken


# --- text-level expansion ---------------------------------------------------

_CURRENCY_SYMBOLS = {"\u20b9": "INR", "$": "USD", "\u20ac": "EUR", "\u00a3": "GBP"}

_UNIT_WORDS = {
    "km": "kilometer", "kms": "kilometer", "kg": "kilo", "kgs": "kilo",
    "g": "gram", "mg": "milligram", "l": "liter", "ml": "milliliter",
    "m": "meter", "cm": "centimeter", "mm": "millimeter", "ft": "feet",
    "in": "inch", "sqft": "square feet", "acre": "acre",
    "hr": "ghanta", "hrs": "ghante", "min": "minute", "sec": "second",
    "k": "hazaar", "cr": "karod", "l": "lakh", "mn": "million",
    "am": "a.m.", "pm": "p.m.", "ist": "Indian Standard Time",
    "utc": "UTC", "gmt": "GMT",
}

_ABBREVIATIONS = {
    "gst": "ji es ti", "gstn": "ji es ti en", "pan": "pi e en",
    "aadhaar": "aadhaar", "ifsc": "ai ef es si", "vpa": "vi pi e",
    "upi": "yu pi ai", "atm": "e ti em", "emi": "i em ai",
    "ceo": "si i o", "cto": "si ti o", "hr": "eich aar",
    "api": "e pi ai", "ai": "e ai", "ml": "em el",
    "ok": "theek", "pls": "please", "plz": "please", "btw": "by the way",
    "approx": "lagbhag", "approx.": "lagbhag", "etc": "vagairah",
    "etc.": "vagairah", "vs": "versus", "vs.": "versus",
    "govt": "sarkar", "govt.": "sarkar", "pvt": "private",
    "ltd": "limited", "co": "company", "no.": "number",
}


def expand_numbers(text: str) -> str:
    """Rewrite numbers, currency, dates and units in a string as words.

    Order matters: currency and dates are matched before bare numbers, or
    ``₹1200`` becomes "symbol one thousand two hundred".

    >>> expand_numbers("Mera bill 1200 rupaye hai")
    'Mera bill ek hazaar do sau rupaye hai'
    >>> expand_numbers("Total ₹12,34,567 hai")
    'Total barah lakh chautis hazaar paanch sau sath rupaye hai'
    """
    if not text:
        return text
    out = text

    # 1. currency: ₹1,234.56 / $50 / 500rs
    def _currency(match: re.Match) -> str:
        symbol, amount = match.group(1), match.group(2)
        currency = _CURRENCY_SYMBOLS.get(symbol, "INR")
        return money_to_hinglish(amount.replace(",", ""), currency=currency)

    out = re.sub(r"([\u20b9$\u20ac\u00a3])\s*([\d,]+(?:\.\d+)?)", _currency, out)
    out = re.sub(
        r"\b([\d,]+(?:\.\d+)?)\s*(?:rs\.?|rupees?|rupaye)\b",
        lambda m: money_to_hinglish(m.group(1).replace(",", ""), currency="INR"),
        out, flags=re.IGNORECASE)

    # 2. dates: 15/08/2026 and 15-08-2026
    def _date(match: re.Match) -> str:
        day, month, year = int(match.group(1)), int(match.group(2)), match.group(3)
        try:
            return date_to_hinglish(day, month, int(year) if year else None)
        except ValueError:
            return match.group(0)

    out = re.sub(r"\b(\d{1,2})[/\-](\d{1,2})(?:[/\-](\d{2,4}))?\b", _date, out)

    # 3. phone numbers: 10+ consecutive digits, read digit by digit
    out = re.sub(
        r"(?<!\d)(?:\+?91[\s\-]?)?([6-9]\d{9})(?!\d)",
        lambda m: phone_to_hinglish(m.group(1)), out)

    # 4. percentages
    # no \b after the percent sign: % is a non-word character, so a word
    # boundary there would require a letter immediately after it and the rule
    # would never fire on "50% growth".
    out = re.sub(
        r"\b(\d+(?:\.\d+)?)\s*(?:%|percent)(?!\w)",
        lambda m: f"{number_to_hinglish(Decimal(m.group(1)))} percent", out)

    # 5. abbreviations, in ONE pass.
    #
    # A loop of re.sub() calls cannot be used here: "UPI" expands to "yu pi
    # ai", and the later "ai" entry then re-expands that output into "yu pi
    # e ai". One alternation with longest-first ordering avoids the cascade,
    # because each match is consumed exactly once.
    abbrev_pattern = "|".join(
        re.escape(a) for a in sorted(_ABBREVIATIONS, key=len, reverse=True))
    out = re.sub(
        rf"\b({abbrev_pattern})\b",
        lambda m: _ABBREVIATIONS[m.group(1).lower()], out, flags=re.IGNORECASE)

    # 6. units
    for unit, spoken in sorted(_UNIT_WORDS.items(), key=lambda kv: -len(kv[0])):
        out = re.sub(rf"(?<=\d)\s*{re.escape(unit)}\b", f" {spoken}", out,
                     flags=re.IGNORECASE)

    # 7. plain integers and decimals last
    def _plain(match: re.Match) -> str:
        raw = match.group(0)
        if "." in raw:
            whole, _, frac = raw.partition(".")
            return (f"{number_to_hinglish(int(whole))} point "
                    f"{' '.join(_ONES[int(c)] for c in frac)}").strip()
        return number_to_hinglish(int(raw))

    out = re.sub(r"(?<![\w.])\d[\d,]*(?:\.\d+)?(?![\w.])", _plain, out)
    return out
