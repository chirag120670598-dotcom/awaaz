# awaaz

**आवाज़ — the Hinglish voice pipeline.** Numbers, dates and currency spoken as
words. Hindi and English routed to different voices. Voiceover scripts with
real pauses and timing. SSML for the engines that accept it.

Zero dependencies. Runs offline. 138 tests.

```bash
$ awaaz normalize "Aapka bill ₹1,234.50 hai, 15/08/2026 tak. Call 9876543210. 50% off!"
Aapka bill ek hazaar do sau chautis rupaye pachaas paise hai, pandrah august
do hazaar chhabbis tak. Call nau aath saat chhah paanch chaar teen do ek zero.
pachaas percent off!
```

## Why

A TTS engine reading raw Hinglish text produces something no Indian would
tolerate. Four things go wrong, and all four are fixable without a GPU:

**1. Numbers are read in the wrong system.** `12,34,567` comes out "one point
two million" instead of *barah lakh chautis hazaar paanch sau sathsath*. Hindi
groups in lakhs and crores. Worse, Hindi has a **distinct word for every
number from 1 to 99** — 34 is *chautis*, not "tees chaar". Composing them the
way English does produces something nobody says.

**2. Phone numbers are read as quantities.** `9876543210` becomes "nine
hundred eighty seven crore…" — useless for dialling. Phone numbers, PINs and
OTPs must be read digit by digit.

**3. One voice reads two languages.** In *"Aaj ka episode AI tools ke baare
mein hai"*, `AI tools` is English and the rest is Hindi. A Hindi voice
mangles the English; an English voice mangles everything else.

**4. No pauses, no emphasis.** Stock TTS output sounds like a navigation
system because nothing tells it where to breathe.

## Quickstart

```bash
git clone https://github.com/chirag120670598-dotcom/awaaz
cd awaaz
export PYTHONPATH=.

python -m awaaz.cli doctor                    # what can this machine do?
python -m awaaz.cli normalize --file script.txt
python -m awaaz.cli langs "Aaj ka episode AI tools ke baare mein hai"
python -m awaaz.cli script --file script.txt --numbers --fit 60
python -m awaaz.cli ssml --file script.txt
python -m awaaz.cli speak --file script.txt --out voice.wav
```

Or `pip install .` and use the `awaaz` entry point.

## The four layers

### 1. Normalisation — `core/numbers.py`

| Input | Output |
|---|---|
| `₹1,234.50` | ek hazaar do sau chautis rupaye pachaas paise |
| `$50` | pachaas dollar |
| `15/08/2026` | pandrah august do hazaar chhabbis |
| `9876543210` | nau aath saat chhah paanch chaar teen do ek zero |
| `50%` | pachaas percent |
| `5km` | paanch kilometer |
| `UPI` | yu pi ai |
| `3.14` | teen point ek chaar |

Rules are applied in a deliberate order — currency before dates before phone
numbers before plain numbers — because `₹1200` matched as a plain number
first becomes "symbol one thousand two hundred".

### 2. Code-switch routing — `core/codeswitch.py`

```
$ awaaz langs --file examples/hinglish_script.txt
English share: 15%

[Hinglish ] Aaj ka
[English  ] episode AI tools
[Hinglish ] ke baare mein hai. Maine 5
```

Detection is **lexical, not statistical**: a word is Hindi if it is in the
Hinglish list or matches Hindi-only spelling patterns, English if it is in the
English list or matches English-only ones. A transformer would beat this. A
word list runs offline in microseconds and is *auditable* — you can open the
file and see why a word was routed where it was, which for a pronunciation
problem is usually worth more.

**Words that are genuinely both languages are not forced either way.** `the`
is English *the* and Hindi थे. `to` is English *to* and Hindi तो. These are
labelled ambiguous and resolved from their nearest labelled neighbour, so a
sentence-initial "the" followed by English reads as English:

```python
>>> segment_spans("the software developer deployed the app")
[Span(language='en', text='the software developer deployed the app', ...)]
```

### 3. Voiceover scripting — `core/script.py`

Splits prose into *cues* — a sentence or clause, with a pause after it and the
words worth stressing. Then times the whole thing:

```
$ awaaz script --file examples/voiceover.txt --numbers --fit 60
target 60.0s, script is 52.4s (00:52) — trimmed to 52.4s

Namaste dosto!   [pause]
Aaj hum baat karenge ek aise topic par jo har creator ke liye zaroori hai.
                                    [emphasis: ek, zaroori]   [pause]
...
---
97 words, 52.4s (00:52) at 145 wpm
```

Hindi runs faster than English (145 vs 155 wpm), so the pace is per-language.
`--fit 60` trims from the **end**, not the middle — cutting the middle leaves a
hole the listener notices.

### 4. SSML — `core/ssml.py`

```xml
<speak version="1.1" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="hi-IN">
  <prosody rate="medium" pitch="medium" volume="medium">
  Aaj ka episode AI tools ke baare mein hai.
  <break time="550ms"/>
  <emphasis level="moderate">Sabse</emphasis> accha result Claude ne diya.
  <break time="1100ms"/>
  </prosody>
</speak>
```

Every cue's pause becomes a real `<break>`, which is what makes output sound
like someone speaking rather than something reading. Text is escaped on the
way in — Indian business names are full of ampersands ("Ravi & Sons"), and
unescaped that produces a malformed document.

`strip_ssml()` produces a plain-text fallback, because SSML support varies
wildly and `espeak-ng` accepts almost none of it.

## Transliteration (and why it is not promised to work)

```
$ awaaz translit "namaste shukriya dosto"
नमस्ते शुक्रिया द्स्तो

---
confidence 67% (2 dictionary, 1 rule-based)
Low confidence: roman-to-Devanagari is ambiguous. Check the output before
synthesising.
```

**Roman-to-Devanagari is inherently ambiguous.** `dosto` came out `द्स्तो` —
wrong. `kya` could be क्या or क्य. Schwa deletion is context-dependent and no
rule set gets it right every time.

So it is offered as a **best effort with a confidence score**: dictionary hits
score 1.0, and the score drops as more words fall through to the syllable
rules. That is the honest contract — the tool tells you when to check, rather
than quietly producing wrong Devanagari.

Devanagari→roman is more reliable, because a consonant carries an inherent
`a` unless a matra or halant cancels it (so नमस्ते → `namaste`, not `nmste`).

## TTS engines

`awaaz` does not bundle a synthesiser. `adapters/tts_adapter.py` shells out to
whatever is installed, and `awaaz doctor` tells you the truth about what that
is:

| Engine | Quality | SSML | Notes |
|---|---|---|---|
| Piper | best | no | neural, offline, runs on a Pi. Needs a `.onnx` voice model |
| espeak-ng | robotic | subset | genuinely tiny and offline. Has Hindi (`hi`) |
| flite | ok | no | English only — useful for English spans |
| say | ok | no | macOS only, no Hindi voice |

```
$ awaaz doctor
awaaz doctor

No TTS engine found on PATH.

Install one:
  Debian/Ubuntu: sudo apt-get install espeak-ng
  macOS:         brew install espeak-ng
  Piper (best):  https://github.com/rhasspy/piper

Everything else in awaaz works without a TTS engine: normalise, script,
code-switch, transliterate, SSML.
```

**Only the text-processing layers are verified in CI.** `build_command()` is
pure and tested; the `subprocess` call is not exercised here because no engine
is installed in this environment.

## What this is not

Stated plainly, because a tool that overstates itself wastes your afternoon:

- **No TTS engine is bundled or verified.** Text in, markup out. Synthesis
  needs `espeak-ng` or Piper installed, and `awaaz doctor` is what tells you
  whether one is.
- **No Hindi TTS model is included.** For genuinely good Hindi speech you want
  [AI4Bharat Indic-TTS](https://github.com/AI4Bharat/Indic-TTS) (IIT Madras) or
  Piper with a Hindi voice. This repo prepares the text for them; it does not
  replace them.
- **Roman→Devanagari will be wrong sometimes.** It says so, with a number.
- **Code-switch detection is a word list, not a model.** Unseen English words
  get missed. Extend `ENGLISH_WORDS`.
- **No voice cloning, no voice conversion, no emotion modelling.**
- **The 145/155 wpm figures are estimates**, not measurements. Calibrate with
  `--wpm` for your own voice.
- **No streaming.** Whole scripts only.

## Architecture

```
awaaz/
├── core/                    # pure stdlib, no I/O, no subprocess
│   ├── numbers.py           #   number/date/currency/phone/unit expansion
│   ├── codeswitch.py        #   Hindi/English span detection
│   ├── transliterate.py     #   roman <-> Devanagari, with confidence
│   ├── script.py            #   cues, pauses, emphasis, timing
│   └── ssml.py              #   SSML generation + stripping
├── adapters/
│   └── tts_adapter.py       #   engine discovery + subprocess (the only I/O)
├── cli.py                   #   argparse
└── tests/test_awaaz.py      #   138 tests
```

`core/` imports nothing outside the standard library, and **CI enforces it** by
AST-parsing every file under `core/` and failing on a third-party import. So
the pipeline stays usable on a machine with no package manager access, which
is most machines in India.

## Tests

```
$ pytest tests/ -q
138 passed in 0.39s
```

Locked down by tests:

- 34 is *chautis*, never "tees chaar"
- phone numbers read digit by digit, never as a quantity
- `%` is consumed (`\b` after `%` can never match — a real bug this caught)
- abbreviations expand in one pass, so `UPI` → "yu pi ai" and the `ai` entry
  never re-expands its own output
- `the` and `to` resolve from context, not from a default
- every word belongs to exactly one span, with no gaps
- XML escaping survives "Ravi & Sons"
- zero-length breaks are dropped, not clamped
- `trim_to()` cuts from the end and always keeps at least one cue
- नमस्ते → `namaste`, never `nmste`

## Related

- [AI4Bharat Indic-TTS](https://github.com/AI4Bharat/Indic-TTS) — the actual
  Hindi TTS models. Point this at them.
- [Piper](https://github.com/rhasspy/piper) — fast offline neural TTS
- [bolkhabar](https://github.com/chirag120670598-dotcom/bolkhabar) — turn a
  podcast transcript into content. Its output feeds nicely into `awaaz script`.

## Contributing

Issues and PRs welcome. The most useful contribution right now is a bigger
`ENGLISH_WORDS` / `HINGLISH_WORDS` list — see
[CONTRIBUTING](CODE_OF_CONDUCT.md) for the code of conduct.

Please add a test with any new rule. Every bug fixed so far in this repo was
found by a test that asserted the behaviour a Hindi speaker would expect.

## License

MIT — see [LICENSE](LICENSE).
