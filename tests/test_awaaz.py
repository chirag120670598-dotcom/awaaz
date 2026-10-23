"""Tests for awaaz.

No TTS engine is required — and none is assumed present. The synthesiser
adapter is tested at the command-construction level, which is pure; the
subprocess call is not exercised in CI.
"""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from awaaz.adapters.tts_adapter import (
    ENGINES,
    TTSError,
    available_engines,
    build_command,
    synthesize,
)
from awaaz.cli import main
from awaaz.core.codeswitch import (
    AMBIGUOUS,
    ENGLISH,
    HINGLISH,
    english_fraction,
    label_word,
    segment_spans,
)
from awaaz.core.numbers import (
    date_to_hinglish,
    expand_numbers,
    money_to_hinglish,
    number_to_hinglish,
    ordinal_to_hinglish,
    phone_to_hinglish,
)
from awaaz.core.script import (
    Cue,
    VoiceScript,
    build_script,
    estimate_duration,
    reading_pace,
)
from awaaz.core.ssml import SSML, build_ssml, strip_ssml
from awaaz.core.transliterate import (
    devanagari_fraction,
    devanagari_to_roman,
    roman_to_devanagari,
)


# --- numbers ----------------------------------------------------------------

class TestNumbers:
    @pytest.mark.parametrize("value,expected", [
        (0, "zero"),
        (1, "ek"),
        (11, "gyarah"),
        (21, "ikkis"),          # Hindi has one word for 21, not "twenty one"
        (34, "chautis"),
        (67, "sathsath"),
        (100, "ek sau"),
        (1000, "ek hazaar"),
        (100000, "ek lakh"),
        (10000000, "ek karod"),
    ])
    def test_basic(self, value, expected):
        assert number_to_hinglish(value) == expected

    def test_indian_grouping_not_western(self):
        """12,34,567 is barah lakh..., not one point two million."""
        assert number_to_hinglish(1234567) == (
            "barah lakh chautis hazaar paanch sau sathsath")

    def test_negative(self):
        assert number_to_hinglish(-5).startswith("minus")

    def test_ordinal(self):
        assert ordinal_to_hinglish(1) == "pehla"
        assert ordinal_to_hinglish(2) == "doosra"
        assert ordinal_to_hinglish(25).endswith("van")

    def test_money_with_paise(self):
        assert money_to_hinglish("1234.50") == (
            "ek hazaar do sau chautis rupaye pachaas paise")

    def test_money_whole(self):
        assert money_to_hinglish(1000) == "ek hazaar rupaye"

    def test_money_usd(self):
        assert money_to_hinglish(5, currency="USD") == "paanch dollar"

    def test_money_zero(self):
        assert money_to_hinglish(0) == "zero rupaye"

    def test_date(self):
        assert date_to_hinglish(15, 8, 2026) == "pandrah august do hazaar chhabbis"

    def test_date_without_year(self):
        assert date_to_hinglish(1, 1) == "ek january"

    def test_bad_month_rejected(self):
        with pytest.raises(ValueError):
            date_to_hinglish(1, 13)

    def test_phone_read_digit_by_digit(self):
        """Reading a phone number as ninety-eight crore is useless for dialling."""
        assert phone_to_hinglish("9876543210") == (
            "nau aath saat chhah paanch chaar teen do ek zero")
        assert "karod" not in phone_to_hinglish("9876543210")


class TestExpandNumbers:
    def test_rupee_symbol(self):
        assert expand_numbers("Total \u20b91,234 hai") == (
            "Total ek hazaar do sau chautis rupaye hai")

    def test_rupee_with_paise(self):
        assert "paise" in expand_numbers("\u20b950.50")

    def test_dollar(self):
        assert "dollar" in expand_numbers("$50")

    def test_rs_suffix(self):
        assert "rupaye" in expand_numbers("500 rs")

    def test_date(self):
        assert "august" in expand_numbers("Date: 15/08/2026")

    def test_percentage(self):
        assert "percent" in expand_numbers("50% growth")

    def test_phone_digits(self):
        assert "nau aath" in expand_numbers("call 9876543210")

    def test_abbreviation_upi(self):
        assert expand_numbers("UPI se pay karo") == "yu pi ai se pay karo"

    def test_plain_integer(self):
        assert expand_numbers("Mera bill 1200 hai") == (
            "Mera bill ek hazaar do sau hai")

    def test_decimal_read_digitwise(self):
        assert "point" in expand_numbers("value 3.14 hai")

    def test_empty_is_safe(self):
        assert expand_numbers("") == ""

    def test_no_numbers_unchanged(self):
        assert expand_numbers("namaste dosto") == "namaste dosto"

    def test_abbreviations_do_not_cascade(self):
        """'UPI' -> 'yu pi ai', and the 'ai' entry must not re-expand its own output."""
        assert expand_numbers("UPI") == "yu pi ai"
        assert expand_numbers("UPI se pay karo") == "yu pi ai se pay karo"

    def test_percent_sign_consumed(self):
        """A word boundary after '%' can never match, so it must not be used."""
        assert expand_numbers("50% growth") == "pachaas percent growth"
        assert "%" not in expand_numbers("50%")

    def test_words_are_not_eaten(self):
        """'k' means thousand after a digit only — not inside a word."""
        assert expand_numbers("kaam karo") == "kaam karo"


# --- code switching ---------------------------------------------------------

class TestCodeSwitch:
    @pytest.mark.parametrize("word,expected", [
        ("namaste", HINGLISH), ("kya", HINGLISH), ("rupaye", HINGLISH),
        ("software", ENGLISH), ("developer", ENGLISH), ("database", ENGLISH),
    ])
    def test_known_words(self, word, expected):
        assert label_word(word) == expected

    def test_devanagari_is_hindi(self):
        assert label_word("\u0928\u092e\u0938\u094d\u0924\u0947") == HINGLISH

    def test_aspirated_pattern_is_hindi(self):
        """kh/gh/chh/dh do not occur in English words."""
        assert label_word("khaana") == HINGLISH
        assert label_word("ghar") == HINGLISH

    def test_tion_ending_is_english(self):
        assert label_word("integration") == ENGLISH

    def test_punctuation_stripped(self):
        assert label_word("kya?") == HINGLISH

    def test_empty_is_ambiguous(self):
        assert label_word("") == AMBIGUOUS
        assert label_word("!!!") == AMBIGUOUS

    def test_spans_split_correctly(self):
        """'episode' really is an English word, so it joins the English run."""
        spans = segment_spans("Aaj ka episode AI tools ke baare mein hai")
        assert [(s.language, s.text) for s in spans] == [
            (HINGLISH, "Aaj ka"),
            (ENGLISH, "episode AI tools"),
            (HINGLISH, "ke baare mein hai"),
        ]

    def test_collisions_resolve_from_context(self):
        """'the' and 'to' are both languages — neighbours decide, not a default."""
        hindi_side = segment_spans("namaste kya the tum")
        assert hindi_side[0].language == HINGLISH
        english_side = segment_spans("the software developer deployed the app")
        assert all(span.language == ENGLISH for span in english_side)

    def test_collisions_are_ambiguous_in_isolation(self):
        assert label_word("the") == AMBIGUOUS
        assert label_word("to") == AMBIGUOUS

    def test_pure_hinglish_is_one_span(self):
        spans = segment_spans("namaste dosto aaj hum baat karenge")
        assert len(spans) == 1
        assert spans[0].language == HINGLISH

    def test_word_indices_are_contiguous(self):
        """No gaps and no double counting — every word belongs to one span."""
        text = "Aaj ka episode AI tools ke baare mein hai"
        spans = segment_spans(text)
        indices = [w for s in spans for w in range(s.start_word, s.end_word)]
        assert indices == list(range(len(text.split())))

    def test_span_text_covers_input(self):
        text = "namaste dosto aaj software ki baat hai"
        rebuilt = " ".join(s.text for s in segment_spans(text))
        assert rebuilt == text

    def test_empty_text(self):
        assert segment_spans("") == []

    def test_english_fraction(self):
        """episode + AI + tools out of 8 words."""
        # episode + AI + tools, out of 9 words
        assert english_fraction("Aaj ka episode AI tools ke baare mein hai") == 3 / 9

    def test_english_fraction_pure_hindi(self):
        assert english_fraction("namaste dosto aaj hum") == 0.0

    def test_english_fraction_empty(self):
        assert english_fraction("") == 0.0

    def test_span_to_dict(self):
        assert {"language", "text", "start_word"} <= set(
            segment_spans("namaste software")[0].to_dict())


# --- transliteration --------------------------------------------------------

class TestTransliterate:
    def test_dictionary_word(self):
        assert roman_to_devanagari("namaste").text == "\u0928\u092e\u0938\u094d\u0924\u0947"

    def test_dictionary_hit_has_full_confidence(self):
        result = roman_to_devanagari("namaste shukriya")
        assert result.confidence == 1.0
        assert result.rule_applied == 0

    def test_unknown_word_lowers_confidence(self):
        """Rule-based transliteration is ambiguous, so it must not claim certainty."""
        result = roman_to_devanagari("namaste zyxwv")
        assert result.confidence < 1.0
        assert result.rule_applied == 1

    def test_mixed_confidence_between(self):
        result = roman_to_devanagari("namaste zyxwv")
        assert 0.0 < result.confidence < 1.0

    def test_empty(self):
        assert roman_to_devanagari("").text == ""
        assert roman_to_devanagari("").confidence == 1.0

    def test_devanagari_input_left_alone(self):
        original = "\u0928\u092e\u0938\u094d\u0924\u0947"
        assert roman_to_devanagari(original).text == original

    def test_punctuation_preserved(self):
        assert roman_to_devanagari("namaste!").text.endswith("!")

    def test_roundtrip_roughly_holds_for_dictionary_words(self):
        """Lossy in general, but dictionary words should survive."""
        assert devanagari_to_roman("\u0928\u092e\u0938\u094d\u0924\u0947") == "namaste"

    def test_devanagari_to_roman_keeps_inherent_schwa(self):
        """A consonant carries an 'a' unless a matra or halant cancels it."""
        assert devanagari_to_roman("\u0928\u092e\u0938\u094d\u0924\u0947") == "namaste"

    def test_devanagari_fraction(self):
        assert devanagari_fraction("namaste") == 0.0
        assert devanagari_fraction("\u0928\u092e\u0938\u094d\u0924\u0947") == 1.0

    def test_devanagari_fraction_mixed(self):
        assert 0.0 < devanagari_fraction("namaste \u0928\u092e\u0938\u094d\u0924\u0947") < 1.0

    def test_devanagari_fraction_no_letters(self):
        assert devanagari_fraction("12345") == 0.0


# --- script -----------------------------------------------------------------

class TestScript:
    def test_splits_sentences(self):
        script = build_script("Namaste dosto. Aaj hum baat karenge.")
        assert len(script.cues) == 2

    def test_long_sentence_split_on_commas(self):
        long_text = ("Yeh ek bahut lamba sentence hai jo comma pe tootna chahiye, "
                     "kyunki ek saans mein itna bolna mushkil hai, aur sunne wale "
                     "ko bhi pause chahiye hota hai.")
        assert len(build_script(long_text).cues) > 1

    def test_empty_text(self):
        assert build_script("").cues == []
        assert build_script("   ").cues == []

    def test_cues_reassemble_to_input(self):
        text = "Pehla sentence. Doosra sentence."
        script = build_script(text)
        assert script.text == text

    def test_duration_positive(self):
        assert build_script("Namaste dosto aaj hum baat karenge").duration > 0

    def test_mmss_format(self):
        script = build_script("Namaste. " * 50)
        assert ":" in script.mmss

    def test_estimate_duration_words(self):
        assert estimate_duration("ek do teen chaar paanch", wpm=60) == 5.0

    def test_estimate_duration_includes_pauses(self):
        with_pause = estimate_duration("ek do teen, chaar paanch", wpm=60)
        without = estimate_duration("ek do teen chaar paanch", wpm=60)
        assert with_pause > without

    def test_estimate_duration_empty(self):
        assert estimate_duration("") == 0.0

    def test_reading_pace_defaults(self):
        assert reading_pace("hi") == 145.0
        assert reading_pace("en") == 155.0
        assert reading_pace("xx") == 150.0

    def test_reading_pace_override(self):
        assert reading_pace("hi", wpm=100) == 100.0

    def test_reading_pace_rejects_zero(self):
        with pytest.raises(ValueError):
            reading_pace("hi", wpm=0)

    def test_fits(self):
        script = build_script("Namaste dosto.")
        assert script.fits(60)
        assert not script.fits(0.1)

    def test_trim_to(self):
        script = build_script(" ".join(f"Sentence number {i}." for i in range(30)))
        trimmed = script.trim_to(5)
        assert trimmed.duration <= 5 or len(trimmed.cues) == 1

    def test_trim_keeps_at_least_one_cue(self):
        """Trimming to nothing would produce silence, which is not a script."""
        script = build_script("Ek bahut lamba sentence yahan hai.")
        assert len(script.trim_to(0.5).cues) == 1

    def test_trim_rejects_zero(self):
        with pytest.raises(ValueError):
            build_script("Namaste.").trim_to(0)

    def test_trim_is_prefix(self):
        """Cutting the middle leaves a hole the listener notices."""
        script = build_script(" ".join(f"Sentence {i}." for i in range(10)))
        trimmed = script.trim_to(script.duration / 2)
        assert script.cues[:len(trimmed.cues)] == trimmed.cues

    def test_emphasis_marked(self):
        script = build_script("Yeh sabse zaroori baat hai.")
        assert any(c.emphasise for c in script.cues)

    def test_emphasis_can_be_disabled(self):
        script = build_script("Yeh sabse zaroori baat hai.", mark_emphasis=False)
        assert all(not c.emphasise for c in script.cues)

    def test_as_text_readable(self):
        assert "Namaste" in build_script("Namaste dosto.").as_text()

    def test_cue_duration_and_word_count(self):
        cue = Cue("ek do teen", pause_after=0.5)
        assert cue.word_count == 3
        assert cue.duration > 0

    def test_script_to_dict(self):
        d = build_script("Namaste dosto.").to_dict()
        assert {"language", "word_count", "duration", "cues"} <= set(d)


# --- SSML -------------------------------------------------------------------

class TestSSML:
    def test_valid_document(self):
        out = build_ssml(build_script("Namaste dosto."))
        assert out.startswith("<speak")
        assert out.strip().endswith("</speak>")

    def test_breaks_from_pauses(self):
        script = build_script("Pehla. Doosra.")
        assert "<break time=" in build_ssml(script)

    def test_escaping(self):
        """Indian business names are full of ampersands — this must not break XML."""
        out = SSML().say("Ravi & Sons <Pvt Ltd>").build()
        assert "&amp;" in out
        assert "&lt;" in out
        assert "<Pvt" not in out

    def test_emphasis_applied(self):
        out = SSML().emphasise_words("Yeh sabse zaroori hai", ["zaroori"]).build()
        assert "<emphasis" in out
        assert "zaroori" in out

    def test_emphasis_keeps_punctuation_outside(self):
        out = SSML().emphasise_words("zaroori.", ["zaroori"]).build()
        assert "</emphasis>." in out

    def test_emphasis_without_words_is_plain(self):
        out = SSML().emphasise_words("plain text", []).build()
        assert "<emphasis" not in out

    def test_pause_zero_dropped(self):
        assert "<break" not in SSML().pause(0).build()

    def test_pause_negative_dropped(self):
        assert "<break" not in SSML().pause(-100).build()

    def test_bad_break_strength_rejected(self):
        with pytest.raises(ValueError):
            SSML().break_strength("sideways")

    def test_lang_switch(self):
        out = SSML().say("AI tools", lang="en-US").build()
        assert 'xml:lang="en-US"' in out

    def test_sub_alias(self):
        out = SSML().sub("GST", "ji es ti").build()
        assert 'alias="ji es ti"' in out

    def test_empty_say_ignored(self):
        assert "<emphasis" not in SSML().say("   ").build()

    def test_strip_ssml(self):
        text = strip_ssml(build_ssml(build_script("Namaste dosto.")))
        assert "<" not in text
        assert "Namaste" in text

    def test_strip_keeps_words_separated(self):
        """Breaks become spaces, so words do not run together."""
        assert strip_ssml("<speak>a<break time='500ms'/>b</speak>") == "a b"

    def test_full_script_roundtrip(self):
        script = build_script("Namaste dosto. Aaj hum baat karenge.")
        text = strip_ssml(build_ssml(script))
        assert "Namaste" in text and "baat" in text


# --- TTS adapter ------------------------------------------------------------

class TestTTSAdapter:
    def test_available_engines_is_a_list(self):
        """May well be empty in CI — the point is that it does not lie."""
        assert isinstance(available_engines(), list)

    def test_available_engines_only_installed(self):
        import shutil
        for engine in available_engines():
            assert shutil.which(engine.binary)

    def test_build_command_espeak(self):
        cmd = build_command(
            ENGINES["espeak-ng"], text_file=Path("in.txt"),
            output_file=Path("out.wav"), voice="hi", rate=150)
        assert cmd[0] == "espeak-ng"
        assert "-v" in cmd and "hi" in cmd
        assert "-w" in cmd and "out.wav" in cmd
        assert "-f" in cmd and "in.txt" in cmd

    def test_build_command_uses_default_voice(self):
        cmd = build_command(ENGINES["espeak-ng"], text_file=Path("i"),
                            output_file=Path("o"))
        assert "hi" in cmd

    def test_build_command_piper(self):
        cmd = build_command(ENGINES["piper"], text_file=Path("i"),
                            output_file=Path("o"))
        assert cmd[0] == "piper"
        assert "--output_file" in cmd

    def test_build_command_no_rate_flag_when_absent(self):
        assert "-s" not in build_command(
            ENGINES["piper"], text_file=Path("i"), output_file=Path("o"))

    def test_synthesize_without_engine_raises(self, monkeypatch):
        monkeypatch.setattr("awaaz.adapters.tts_adapter.available_engines",
                            lambda: [])
        with pytest.raises(TTSError, match="no TTS engine"):
            synthesize("namaste", "out.wav")

    def test_synthesize_unknown_engine_raises(self, monkeypatch):
        monkeypatch.setattr("awaaz.adapters.tts_adapter.available_engines",
                            lambda: [ENGINES["espeak-ng"]])
        with pytest.raises(TTSError, match="not installed"):
            synthesize("namaste", "out.wav", engine_name="telepathy")


# --- CLI --------------------------------------------------------------------

class TestCLI:
    def run(self, argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(argv)
        return code, buf.getvalue()

    def test_doctor(self):
        code, out = self.run(["doctor"])
        assert code == 0
        assert "awaaz doctor" in out

    def test_doctor_lists_uninstalled(self):
        _, out = self.run(["doctor"])
        assert "espeak-ng" in out or "No TTS engine" in out

    def test_normalize(self):
        code, out = self.run(["normalize", "Mera bill \u20b91,234 hai"])
        assert code == 0
        assert "ek hazaar do sau chautis" in out

    def test_number(self):
        code, out = self.run(["number", "1234567"])
        assert code == 0
        assert "barah lakh" in out

    def test_number_money(self):
        code, out = self.run(["number", "1234.50", "--money"])
        assert code == 0
        assert "rupaye" in out

    def test_number_phone(self):
        code, out = self.run(["number", "9876543210", "--phone"])
        assert code == 0
        assert "nau aath" in out

    def test_date(self):
        code, out = self.run(["date", "15", "8", "2026"])
        assert code == 0
        assert "august" in out

    def test_script(self):
        code, out = self.run(["script", "Namaste dosto. Aaj hum baat karenge."])
        assert code == 0
        assert "wpm" in out

    def test_script_json(self):
        code, out = self.run(["script", "Namaste dosto.", "--json"])
        assert code == 0
        assert "cues" in json.loads(out)

    def test_script_ssml(self):
        code, out = self.run(["script", "Namaste dosto.", "--ssml"])
        assert code == 0
        assert out.startswith("<speak")

    def test_script_fit(self):
        code, out = self.run(["script", "Namaste dosto. Aaj baat karenge.",
                              "--fit", "30"])
        assert code == 0

    def test_script_from_file(self, tmp_path):
        path = tmp_path / "s.txt"
        path.write_text("Namaste dosto. Aaj hum baat karenge.", encoding="utf-8")
        code, out = self.run(["script", "--file", str(path)])
        assert code == 0
        assert "Namaste" in out

    def test_script_missing_file(self):
        assert self.run(["script", "--file", "nope.txt"])[0] == 2

    def test_langs(self):
        code, out = self.run(["langs", "Aaj ka episode AI tools ke baare mein hai"])
        assert code == 0
        assert "English" in out and "Hinglish" in out

    def test_langs_json(self):
        code, out = self.run(["langs", "namaste software", "--json"])
        assert code == 0
        assert "spans" in json.loads(out)

    def test_words(self):
        code, out = self.run(["words", "namaste software"])
        assert code == 0
        assert "Hinglish" in out and "English" in out

    def test_translit(self):
        code, out = self.run(["translit", "namaste"])
        assert code == 0
        assert "\u0928\u092e\u0938\u094d\u0924\u0947" in out

    def test_translit_confidence_shown(self):
        _, out = self.run(["translit", "namaste zyxwv"])
        assert "confidence" in out

    def test_translit_quiet(self):
        _, out = self.run(["translit", "namaste", "--quiet"])
        assert "confidence" not in out

    def test_translit_to_roman(self):
        code, out = self.run(["translit", "\u0928\u092e\u0938\u094d\u0924\u0947",
                              "--to-roman"])
        assert code == 0
        assert "namaste" in out

    def test_ssml(self):
        code, out = self.run(["ssml", "Namaste dosto."])
        assert code == 0
        assert out.startswith("<speak")

    def test_ssml_strip(self):
        code, out = self.run(["ssml", "Namaste dosto.", "--strip"])
        assert code == 0
        assert "<" not in out

    def test_speak_without_engine(self, monkeypatch):
        monkeypatch.setattr("awaaz.adapters.tts_adapter.available_engines",
                            lambda: [])
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(["speak", "Namaste", "--out", "x.wav"])
        assert code == 2


class TestWindowsConsoleEncoding:
    """Windows consoles default to cp1252, which cannot encode \u20b9 or \u2192.

    This crashed the CLI smoke test on windows-latest in CI, and would crash
    for any Windows user running the same command.
    """

    def test_force_utf8_stdio_does_not_raise(self):
        """pytest's capture objects lack reconfigure(); the guard must cope."""
        from awaaz.cli import _force_utf8_stdio
        _force_utf8_stdio()

    def test_guard_fixes_a_cp1252_stream(self):
        import io
        import sys
        from awaaz.cli import _force_utf8_stdio

        # the failure mode is real: cp1252 cannot encode a rupee sign
        broken = io.TextIOWrapper(open(2, "wb", closefd=False),
                                  encoding="cp1252", newline="")
        with pytest.raises(UnicodeEncodeError):
            broken.write("\u20b9")
            broken.flush()

        guarded = io.TextIOWrapper(open(2, "wb", closefd=False),
                                   encoding="cp1252", newline="")
        original = sys.stdout
        sys.stdout = guarded
        try:
            _force_utf8_stdio()
            sys.stdout.write("TOTAL \u20b96165.00 \u2192 paid")
            sys.stdout.flush()
        finally:
            sys.stdout = original
