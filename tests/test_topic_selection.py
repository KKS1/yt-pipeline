"""Topic dedup and the post-selection confirmation loop.

Covers the regression where english-quiz and english-shorts never checked
recently published topics: the check only ran for manually supplied --topic,
and the Groq-failure fallback picked blindly from a hardcoded seed list.
"""
import builtins

import pytest

from scripts import english_generator as eg


HISTORY = {
    "quiz": [
        "Only 10% Pass This Borrow vs Lend Test",
        "You Sound RUDE When You Say 'No Problem'",
        "Only 10% Pass This Affect vs Effect Test",
    ],
    "shorts": [
        "Native Speakers NEVER Say 'Make' vs 'Do' – English in 60 Sec",
        "The Actually Secret Nobody Teaches – Speak Like a Native",
    ],
    "podcast": [
        "Master the 'Would You Mind' Mistake – English Practice",
    ],
}


@pytest.fixture
def fake_history(monkeypatch):
    """Serve a fixed ledger so tests never touch the real published-topics file."""
    monkeypatch.setattr(eg, "get_published_topics", lambda: {k: list(v) for k, v in HISTORY.items()})
    return HISTORY


@pytest.fixture
def scripted_generation(monkeypatch):
    """Replace Groq topic generation with a queue of canned topics."""
    queue = []

    def _fake(is_challenge=False, topic_type="podcast", rejected=None):
        calls.append({"topic_type": topic_type, "rejected": list(rejected or [])})
        return queue.pop(0) if queue else f"Auto Topic {len(calls)}"

    calls = []
    monkeypatch.setattr(eg, "generate_dynamic_topic", _fake)
    return queue, calls


@pytest.fixture
def answers(monkeypatch):
    """Feed scripted answers to the confirm prompt, with a TTY faked open."""
    scripted = []

    def _fake_input(prompt=""):
        if not scripted:
            raise AssertionError(f"unexpected prompt: {prompt!r}")
        return scripted.pop(0)

    monkeypatch.setattr(builtins, "input", _fake_input)
    monkeypatch.setattr(eg, "_can_prompt", lambda: True)
    return scripted


# ── dedup detection ─────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "topic, topic_type",
    [
        ("Only 10% Pass This Borrow vs Lend Test", "quiz"),
        # Same subject wearing a different CTR formula.
        ("Borrow vs Lend: One Makes You Look Dumb", "quiz"),
        ("STOP Using 'No Problem' — Here's Why", "quiz"),
        ("Native Speakers NEVER Say Make vs Do", "shorts"),
        ("Master the Would You Mind Mistake", "podcast"),
    ],
)
def test_detects_duplicates_despite_different_wording(fake_history, topic, topic_type):
    assert eg.is_already_published(topic, topic_type) is True


@pytest.mark.parametrize(
    "topic, topic_type",
    [
        ("Only 10% Pass This Want vs Wish Test", "quiz"),
        # Distinct comparison pairs must not be conflated.
        ("Only 10% Pass This SAY vs TELL Test", "quiz"),
        ("The ELI5 Secret Nobody Teaches", "shorts"),
        ("Only 10% Pass This Preposition Trap Test", "quiz"),
        ("How to Ask For a Raise Without Sorry", "podcast"),
        ("Lost in Customs Because of One Word", "shorts"),
    ],
)
def test_allows_genuinely_fresh_topics(fake_history, topic, topic_type):
    assert eg.is_already_published(topic, topic_type) is False


def test_short_topics_do_not_match_everything(fake_history):
    """The old bidirectional substring check flagged 'Could' against nearly every entry."""
    assert eg.is_already_published("Could", "quiz") is False
    assert eg.is_already_published("English", "shorts") is False


def test_empty_history_matches_nothing(monkeypatch):
    monkeypatch.setattr(eg, "get_published_topics", lambda: {"quiz": []})
    assert eg.is_already_published("Any Topic At All", "quiz") is False


def test_seeds_are_filtered_against_history(monkeypatch):
    """The Groq-failure fallback must not hand back an already-published title."""
    monkeypatch.setattr(eg, "get_published_topics", lambda: {"quiz": list(HISTORY["quiz"])})
    for _ in range(25):
        assert eg._pick_seed_topic("quiz") not in HISTORY["quiz"]


# ── confirmation loop ───────────────────────────────────────────────────────

def test_confirm_accepts_first_candidate(fake_history, scripted_generation, answers):
    queue, calls = scripted_generation
    queue.append("Brand New Topic")
    answers.append("")

    assert eg.select_topic_interactive(topic_type="quiz") == "Brand New Topic"
    assert len(calls) == 1


def test_retry_generates_a_different_topic(fake_history, scripted_generation, answers):
    queue, calls = scripted_generation
    queue.extend(["First Topic", "Second Topic"])
    answers.extend(["r", "y"])

    assert eg.select_topic_interactive(topic_type="quiz") == "Second Topic"
    assert len(calls) == 2


def test_rejected_topics_are_fed_back_to_the_generator(fake_history, scripted_generation, answers):
    """A retry must not re-propose the topic the user just turned down."""
    queue, calls = scripted_generation
    queue.extend(["First Topic", "Second Topic"])
    answers.extend(["n", "y"])

    eg.select_topic_interactive(topic_type="quiz")

    assert calls[0]["rejected"] == []
    assert calls[1]["rejected"] == ["First Topic"]


def test_retry_loop_is_capped(fake_history, scripted_generation, answers):
    """An endless 'R' must not spin forever burning Groq calls."""
    _, calls = scripted_generation
    answers.extend(["r"] * 10)

    result = eg.select_topic_interactive(topic_type="quiz", max_attempts=3)

    assert len(calls) == 3
    assert result == "Auto Topic 3"


def test_manual_topic_is_confirmed_not_generated(fake_history, scripted_generation, answers):
    _, calls = scripted_generation
    answers.append("y")

    assert eg.select_topic_interactive("Chosen By Hand", topic_type="quiz") == "Chosen By Hand"
    assert calls == []


def test_rejecting_a_manual_topic_falls_back_to_generation(fake_history, scripted_generation, answers):
    queue, calls = scripted_generation
    queue.append("Generated Instead")
    answers.extend(["n", "y"])

    assert eg.select_topic_interactive("Chosen By Hand", topic_type="quiz") == "Generated Instead"
    assert len(calls) == 1


def test_duplicate_warning_is_shown(fake_history, scripted_generation, answers, capsys):
    answers.append("y")

    eg.select_topic_interactive("Only 10% Pass This Borrow vs Lend Test", topic_type="quiz")

    out = capsys.readouterr().out
    assert "WARNING" in out
    assert "Only 10% Pass This Borrow vs Lend Test" in out


def test_quit_aborts_the_run(fake_history, scripted_generation, answers):
    answers.append("q")

    with pytest.raises(SystemExit):
        eg.select_topic_interactive(topic_type="quiz")


# ── non-interactive safety ──────────────────────────────────────────────────

def test_auto_confirm_skips_the_prompt(fake_history, scripted_generation, monkeypatch):
    queue, calls = scripted_generation
    queue.append("Quiet Topic")
    monkeypatch.setattr(eg, "_can_prompt", lambda: False)

    def _boom(prompt=""):
        raise AssertionError("must not prompt in auto-confirm mode")

    monkeypatch.setattr(builtins, "input", _boom)

    assert eg.select_topic_interactive(topic_type="quiz") == "Quiet Topic"
    assert len(calls) == 1


def test_set_auto_confirm_disables_prompting(fake_history, scripted_generation, monkeypatch):
    monkeypatch.setattr(builtins, "input", lambda prompt="": (_ for _ in ()).throw(AssertionError("prompted")))
    eg.set_auto_confirm_topic(True)
    try:
        assert eg._can_prompt() is False
    finally:
        eg.set_auto_confirm_topic(False)


def test_eof_during_prompt_accepts_the_topic(fake_history, scripted_generation, monkeypatch):
    """A closed stdin must not crash a scheduled run mid-pipeline."""
    queue, _ = scripted_generation
    queue.append("Topic From Scheduled Run")

    def _raise_eof(prompt=""):
        raise EOFError

    monkeypatch.setattr(builtins, "input", _raise_eof)

    assert eg.select_topic_interactive(topic_type="quiz") == "Topic From Scheduled Run"
