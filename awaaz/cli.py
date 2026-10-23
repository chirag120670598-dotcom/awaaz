"""``awaaz`` command line.

Every command runs offline. Nothing is synthesised unless you ask for it and
a TTS engine is actually installed — and :func:`awaaz.adapters.tts_adapter.available_engines`
is what tells you whether one is.

Usage::

    awaaz doctor
    awaaz normalize "Mera bill ₹1,234 hai, 15/08/2026 ko"
    awaaz script script.txt
    awaaz script script.txt --ssml
    awaaz langs "Aaj ka episode AI tools ke baare mein hai"
    awaaz translit "namaste dosto aaj hum baat karenge"
    awaaz number 1234567
    awaaz speak script.txt --out voice.wav

Standard library only.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Sequence

from .adapters.tts_adapter import (
    ENGINES,
    TTSError,
    available_engines,
    synthesize,
)
from .core.codeswitch import (
    AMBIGUOUS,
    ENGLISH,
    HINGLISH,
    english_fraction,
    label_word,
    segment_spans,
)
from .core.numbers import (
    date_to_hinglish,
    expand_numbers,
    money_to_hinglish,
    number_to_hinglish,
    phone_to_hinglish,
)
from .core.script import build_script, estimate_duration, reading_pace
from .core.ssml import build_ssml, strip_ssml
from .core.transliterate import (
    devanagari_fraction,
    devanagari_to_roman,
    roman_to_devanagari,
)

__all__ = ["main", "build_parser"]

_LANG_NAMES = {HINGLISH: "Hinglish", ENGLISH: "English", AMBIGUOUS: "ambiguous"}


def _read(text: Optional[str], path: Optional[str]) -> str:
    if text:
        return text
    if path:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"no such file: {path}")
        return p.read_text(encoding="utf-8")
    raise ValueError("pass text as an argument, or --file path")


# --- subcommands ------------------------------------------------------------

def cmd_doctor(args, out) -> int:
    """What can this machine actually do?"""
    print("awaaz doctor\n", file=out)
    engines = available_engines()
    if engines:
        print("TTS engines installed:", file=out)
        for engine in engines:
            marks = "SSML" if engine.ssml else "plain text only"
            print(f"  \u2713 {engine.name:<12} ({marks})", file=out)
            if engine.notes:
                print(f"      {engine.notes}", file=out)
    else:
        print("No TTS engine found on PATH.", file=out)
        print("\nInstall one:", file=out)
        print("  Debian/Ubuntu: sudo apt-get install espeak-ng", file=out)
        print("  macOS:         brew install espeak-ng", file=out)
        print("  Piper (best):  https://github.com/rhasspy/piper", file=out)
    print("\nSupported but not installed:", file=out)
    for engine in ENGINES.values():
        if engine not in engines:
            print(f"  \u2013 {engine.name}", file=out)
    print("\nEverything else in awaaz works without a TTS engine: "
          "normalise, script, code-switch, transliterate, SSML.", file=out)
    return 0


def cmd_normalize(args, out) -> int:
    text = _read(args.text, args.file)
    result = expand_numbers(text)
    print(result, file=out)
    return 0


def cmd_number(args, out) -> int:
    if args.phone:
        print(phone_to_hinglish(args.value), file=out)
    elif args.money:
        print(money_to_hinglish(args.value, currency=args.currency), file=out)
    else:
        print(number_to_hinglish(args.value), file=out)
    return 0


def cmd_date(args, out) -> int:
    print(date_to_hinglish(args.day, args.month, args.year), file=out)
    return 0


def cmd_script(args, out) -> int:
    text = expand_numbers(_read(args.text, args.file)) if args.numbers \
        else _read(args.text, args.file)
    script = build_script(text, language=args.lang, wpm=args.wpm)

    if args.ssml:
        print(build_ssml(script, lang=args.ssml_lang, rate=args.rate), file=out)
        return 0

    if args.json:
        print(json.dumps(script.to_dict(), ensure_ascii=False, indent=2), file=out)
        return 0

    if args.fit:
        trimmed = script.trim_to(args.fit)
        print(f"target {args.fit}s, script is {script.duration}s "
              f"({script.mmss}) — trimmed to {trimmed.duration}s\n", file=out)
        script = trimmed

    print(script.as_text(), file=out)
    print(f"\n---\n{script.word_count} words, "
          f"{script.duration}s ({script.mmss}) at "
          f"{reading_pace(args.lang, wpm=args.wpm):g} wpm", file=out)
    return 0


def cmd_langs(args, out) -> int:
    text = _read(args.text, args.file)
    spans = segment_spans(text)

    if args.json:
        print(json.dumps(
            {"spans": [s.to_dict() for s in spans],
             "english_fraction": round(english_fraction(text), 3)},
            ensure_ascii=False, indent=2), file=out)
        return 0

    print(f"English share: {english_fraction(text):.0%}\n", file=out)
    for span in spans:
        label = _LANG_NAMES.get(span.language, span.language)
        print(f"[{label:<9}] {span.text}", file=out)
    return 0


def cmd_words(args, out) -> int:
    for word in args.text.split():
        label = label_word(word)
        print(f"{word:<24} {_LANG_NAMES.get(label, label)}", file=out)
    return 0


def cmd_translit(args, out) -> int:
    text = _read(args.text, args.file)
    if args.to_roman:
        print(devanagari_to_roman(text), file=out)
        return 0

    result = roman_to_devanagari(text)
    print(result.text, file=out)
    if not args.quiet:
        print(f"\n---\nconfidence {result.confidence:.0%} "
              f"({result.dictionary_hits} dictionary, "
              f"{result.rule_applied} rule-based)", file=out)
        if result.confidence < 0.9:
            print("Low confidence: roman-to-Devanagari is ambiguous. "
                  "Check the output before synthesising.", file=out)
    return 0


def cmd_ssml(args, out) -> int:
    text = _read(args.text, args.file)
    script = build_script(expand_numbers(text) if args.numbers else text,
                          language=args.lang)
    if args.strip:
        print(strip_ssml(build_ssml(script)), file=out)
        return 0
    print(build_ssml(script, lang=args.ssml_lang, rate=args.rate), file=out)
    return 0


def cmd_speak(args, out) -> int:
    engines = available_engines()
    if not engines:
        print("No TTS engine installed. Run: awaaz doctor", file=sys.stderr)
        return 2

    text = expand_numbers(_read(args.text, args.file)) if args.numbers \
        else _read(args.text, args.file)
    script = build_script(text, language=args.lang)

    payload = build_ssml(script, lang=args.ssml_lang) if args.ssml else script.text
    try:
        engine, cmd = synthesize(
            payload, args.out, engine_name=args.engine,
            voice=args.voice, rate=args.wpm)
    except TTSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"{engine} wrote {args.out} ({script.duration}s of audio expected)",
          file=out)
    if args.verbose:
        print(" ".join(cmd), file=out)
    return 0


# --- wiring -----------------------------------------------------------------

def _add_source(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("text", nargs="?", default="", help="the text")
    parser.add_argument("--file", default="", help="read from a file instead")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="awaaz",
        description="Hinglish voice pipeline: text normalisation, code-switch "
                    "routing, voiceover scripting and SSML. Offline, zero "
                    "dependencies.",
    )
    parser.add_argument("--version", action="version", version="awaaz 0.1.0")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("doctor", help="what TTS engines are installed")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("normalize", help="numbers, currency, dates and units as words")
    _add_source(p)
    p.add_argument("--numbers", action="store_true", default=True)
    p.set_defaults(func=cmd_normalize)

    p = sub.add_parser("number", help="one number as Hinglish words")
    p.add_argument("value")
    p.add_argument("--money", action="store_true")
    p.add_argument("--phone", action="store_true")
    p.add_argument("--currency", default="INR")
    p.set_defaults(func=cmd_number)

    p = sub.add_parser("date", help="a date as Hinglish words")
    p.add_argument("day", type=int)
    p.add_argument("month", type=int)
    p.add_argument("year", type=int, nargs="?", default=None)
    p.set_defaults(func=cmd_date)

    p = sub.add_parser("script", help="voiceover script with cues and timing")
    _add_source(p)
    p.add_argument("--lang", default="hi")
    p.add_argument("--wpm", type=float, default=None)
    p.add_argument("--numbers", action="store_true",
                   help="expand numbers to words first")
    p.add_argument("--ssml", action="store_true")
    p.add_argument("--ssml-lang", default="hi-IN")
    p.add_argument("--rate", default="medium")
    p.add_argument("--json", action="store_true")
    p.add_argument("--fit", type=float, default=None,
                   help="trim the script to fit N seconds")
    p.set_defaults(func=cmd_script)

    p = sub.add_parser("langs", help="split text into Hindi and English spans")
    _add_source(p)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_langs)

    p = sub.add_parser("words", help="language label for each word")
    p.add_argument("text")
    p.set_defaults(func=cmd_words)

    p = sub.add_parser("translit", help="roman Hinglish <-> Devanagari")
    _add_source(p)
    p.add_argument("--to-roman", action="store_true")
    p.add_argument("--quiet", action="store_true")
    p.set_defaults(func=cmd_translit)

    p = sub.add_parser("ssml", help="render text as SSML")
    _add_source(p)
    p.add_argument("--lang", default="hi")
    p.add_argument("--ssml-lang", default="hi-IN")
    p.add_argument("--rate", default="medium")
    p.add_argument("--numbers", action="store_true")
    p.add_argument("--strip", action="store_true",
                   help="print plain text with the tags removed")
    p.set_defaults(func=cmd_ssml)

    p = sub.add_parser("speak", help="synthesise audio (needs a TTS engine)")
    _add_source(p)
    p.add_argument("--out", default="awaaz.wav")
    p.add_argument("--engine", default="")
    p.add_argument("--voice", default="")
    p.add_argument("--lang", default="hi")
    p.add_argument("--ssml-lang", default="hi-IN")
    p.add_argument("--wpm", type=int, default=None)
    p.add_argument("--ssml", action="store_true")
    p.add_argument("--numbers", action="store_true")
    p.add_argument("--verbose", action="store_true")
    p.set_defaults(func=cmd_speak)

    return parser


def _force_utf8_stdio() -> None:
    """Force UTF-8 on stdout/stderr.

    Windows consoles default to a legacy code page (cp1252 or cp850) that
    cannot encode the rupee sign, so a CLI that prints Indian currency
    crashes with ``UnicodeEncodeError`` before it prints anything useful.
    Reconfiguring is the fix; the guards are for streams that are already
    UTF-8 or that do not support reconfiguration (pytest's capture objects,
    pipes closed early).
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


def main(argv: Optional[Sequence[str]] = None) -> int:
    _force_utf8_stdio()
    args = build_parser().parse_args(argv)
    try:
        return args.func(args, sys.stdout)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except TTSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except BrokenPipeError:  # pragma: no cover
        return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
