"""TTS backends — deliberately the thinnest layer in the project.

Everything interesting happens in :mod:`awaaz.core`. This module only shells
out to a synthesiser that is actually installed on the machine.

.. warning::
   **No TTS engine is installed in this repository's CI**, and none can be
   assumed present. :func:`available_engines` is the honest entry point: it
   probes for what is actually on the machine before you try to use it.

   ``synthesize()`` builds the correct command line for each engine and is
   unit-tested at the *command construction* level (:func:`build_command`,
   which is pure), but the subprocess call itself is **not** verified against
   a live engine here.

Standard library only (``shutil``, ``subprocess``).
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

__all__ = [
    "ENGINES",
    "Engine",
    "TTSError",
    "available_engines",
    "build_command",
    "synthesize",
]


class TTSError(RuntimeError):
    """Raised when no engine is available or a synthesis call fails."""


@dataclass(frozen=True)
class Engine:
    """How to invoke one TTS backend."""

    name: str
    binary: str
    args: Tuple[str, ...]
    ssml: bool                     # whether it accepts SSML
    output_flag: str               # e.g. "-w" for a file
    voice_flag: Optional[str] = None
    rate_flag: Optional[str] = None
    language_flag: Optional[str] = None
    default_voice: Optional[str] = None
    notes: str = ""


#: Backends worth supporting, best quality first.
ENGINES: Dict[str, Engine] = {
    "piper": Engine(
        name="piper", binary="piper",
        args=(),
        ssml=False,
        output_flag="--output_file",
        voice_flag="--model",
        notes="fast neural TTS, runs offline on a Raspberry Pi. Best quality "
              "here, but needs a downloaded .onnx voice model."),
    "espeak-ng": Engine(
        name="espeak-ng", binary="espeak-ng",
        args=(),
        ssml=True,          # accepts a subset of SSML
        output_flag="-w",
        voice_flag="-v",
        rate_flag="-s",
        default_voice="hi",
        notes="robotic but genuinely offline and tiny. Supports Hindi (`hi`). "
              "The practical floor, not the ceiling."),
    "espeak": Engine(
        name="espeak", binary="espeak",
        args=(),
        ssml=True,
        output_flag="-w",
        voice_flag="-v",
        rate_flag="-s",
        default_voice="hi",
        notes="the older espeak. Same caveats as espeak-ng."),
    "flite": Engine(
        name="flite", binary="flite",
        args=(),
        ssml=False,
        output_flag="-o",
        voice_flag="-voice",
        notes="English only. Useful as a fallback for the English spans of a "
              "code-switched sentence, not for Hindi."),
    "say": Engine(
        name="say", binary="say",
        args=(),
        ssml=False,
        output_flag="-o",
        voice_flag="-v",
        rate_flag="-r",
        notes="macOS only. No Hindi voice ships with it."),
}


def available_engines() -> List[Engine]:
    """Engines actually present on this machine, in preference order.

    This is the function to call before promising a user audio. Returning the
    whole :data:`ENGINES` table would be a lie on any machine that has not
    installed them.
    """
    return [engine for engine in ENGINES.values()
            if shutil.which(engine.binary)]


def build_command(
    engine: Engine,
    *,
    text_file: Path,
    output_file: Path,
    voice: Optional[str] = None,
    rate: Optional[int] = None,
) -> List[str]:
    """The argv for one synthesis call. Pure — no subprocess, fully testable.

    Text is passed as a *file*, never on the command line. A Hinglish script
    with quotes, ampersands and Devanagari in it will break shell quoting, and
    argv has a length limit that a long script can hit.

    >>> build_command(ENGINES["espeak-ng"],
    ...               text_file=Path("in.txt"), output_file=Path("out.wav"),
    ...               voice="hi", rate=150)
    ['espeak-ng', '-v', 'hi', '-s', '150', '-w', 'out.wav', '-f', 'in.txt']
    """
    cmd = [engine.binary, *engine.args]

    chosen_voice = voice or engine.default_voice
    if engine.voice_flag and chosen_voice:
        cmd += [engine.voice_flag, chosen_voice]
    if engine.rate_flag and rate:
        cmd += [engine.rate_flag, str(int(rate))]

    cmd += [engine.output_flag, str(output_file)]

    if engine.name == "espeak-ng" or engine.name == "espeak":
        cmd += ["-f", str(text_file)]
    elif engine.name == "piper":
        cmd += ["-f", str(text_file)]
    else:
        cmd += ["-f", str(text_file)]
    return cmd


def synthesize(
    text: str,
    output_file,
    *,
    engine_name: Optional[str] = None,
    voice: Optional[str] = None,
    rate: Optional[int] = None,
    timeout: float = 120.0,
) -> Tuple[str, List[str]]:
    """Speak ``text`` to a file. Returns the engine used and the argv.

    Raises:
        TTSError: if no engine is installed, or the engine exits non-zero.
    """
    engines = available_engines()
    if not engines:
        raise TTSError(
            "no TTS engine found on PATH. Install one of: "
            + ", ".join(sorted(ENGINES))
            + "\n\n  Debian/Ubuntu: sudo apt-get install espeak-ng\n"
            "  macOS:           brew install espeak-ng\n"
            "  Piper:           https://github.com/rhasspy/piper")

    engine = next((e for e in engines if e.name == engine_name), None) \
        if engine_name else engines[0]
    if engine is None:
        raise TTSError(
            f"engine {engine_name!r} is not installed. Available: "
            + ", ".join(e.name for e in engines))

    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # write the text to a temp file rather than passing it on the command line
    text_path = output_path.with_suffix(output_path.suffix + ".txt")
    text_path.write_text(text, encoding="utf-8")

    cmd = build_command(engine, text_file=text_path, output_file=output_path,
                        voice=voice, rate=rate)
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise TTSError(f"{engine.name} timed out after {timeout}s") from exc
    finally:
        text_path.unlink(missing_ok=True)

    if result.returncode != 0:
        raise TTSError(
            f"{engine.name} failed (exit {result.returncode}): "
            f"{result.stderr.strip()[:400]}")
    if not output_path.exists() or output_path.stat().st_size == 0:
        raise TTSError(f"{engine.name} produced no audio at {output_path}")
    return engine.name, cmd
