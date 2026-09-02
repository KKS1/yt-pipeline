import pytest
from scripts.kokoro_tts import clean_text


def test_clean_text_sanitizes_slashes():
    # Options separated by spaces and slash
    assert clean_text("Choose Option A / Option B") == "Choose Option A or Option B"

    # Compound choices without spaces around slash
    assert clean_text("Is it either/or?") == "Is it either or?"
    assert clean_text("he/she") == "he or she"
    assert clean_text("pass/fail") == "pass or fail"

    # Common slash abbreviations
    assert clean_text("Coffee w/ sugar and tea w/o milk.") == "Coffee with sugar and tea without milk."

    # Emojis and visual cues stripped alongside slash replacement
    assert clean_text("💬 Choose option A / option B [VISUAL: coffee] [PAUSE]") == "Choose option A or option B ..."
