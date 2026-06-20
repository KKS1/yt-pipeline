from scripts.english_generator import (
    _clean_challenge_dialogue,
    combine_english_parts,
    ensure_english_description_cta,
    ensure_english_quiz_shorts_hashtags,
    is_outro_line,
    sanitize_dialogue_part,
)


def test_is_outro_line_detects_cta():
    assert is_outro_line("Thanks for listening, and don't forget to subscribe!")
    assert is_outro_line("See you next time on EnglishVibesHub!")
    assert is_outro_line("Let's take a quick break before the next section.")
    assert is_outro_line("Stay tuned for the next episode, where we'll explore travel idioms.")
    assert is_outro_line("Looking forward to it!")
    assert not is_outro_line("Welcome to EnglishVibesHub, today we talk about travel.")


def test_sanitize_strips_mid_part_signoffs():
    dialogue = [
        {"speaker": "Emma", "text": "Let's look at this phrasal verb."},
        {"speaker": "Liam", "text": "Thanks for watching, subscribe for more!"},
        {"speaker": "Emma", "text": "Next episode we will be exploring airport English."},
        {"speaker": "Liam", "text": "Stay tuned for the next lesson."},
        {"speaker": "Emma", "text": "Another teaching point here."},
    ]
    cleaned = sanitize_dialogue_part(dialogue, max_outro_turns_at_end=0)
    assert len(cleaned) == 2
    assert cleaned[0]["text"].startswith("Let's look")


def test_sanitize_keeps_outro_only_at_end_of_part3():
    dialogue = [
        {"speaker": "Emma", "text": "One more idiom before we close."},
        {"speaker": "Liam", "text": "Like and subscribe to EnglishVibesHub!"},
        {"speaker": "Emma", "text": "Thanks for listening, see you next time!"},
    ]
    cleaned = sanitize_dialogue_part(dialogue, max_outro_turns_at_end=2)
    assert len(cleaned) == 3
    assert is_outro_line(cleaned[-1]["text"])
    assert is_outro_line(cleaned[-2]["text"])


def test_combine_english_parts_sanitizes_each_segment():
    script = combine_english_parts(
        {
            "title": "Test",
            "dialogue": [
                {"speaker": "Emma", "text": "Welcome to EnglishVibesHub!"},
                {"speaker": "Liam", "text": "Subscribe for more lessons!"},
            ],
        },
        {"dialogue": [{"speaker": "Emma", "text": "Deep dive content."}]},
        {
            "dialogue": [
                {"speaker": "Liam", "text": "Wrap-up lesson here."},
                {"speaker": "Emma", "text": "Hit the like button and subscribe!"},
                {"speaker": "Liam", "text": "Thanks for listening, tune in next time!"},
            ]
        },
        "Travel",
    )
    assert len(script["dialogue"]) == 5
    assert script["dialogue"][0]["text"].startswith("Welcome")
    assert not any(is_outro_line(t["text"]) for t in script["dialogue"][:3])
    assert is_outro_line(script["dialogue"][-1]["text"])


def test_clean_challenge_dialogue_strips_midweek_outros():
    script = {
        "dialogue": [
            {"speaker": "Emma", "text": "Welcome to Day 2 of the challenge."},
            {"speaker": "Liam", "text": "Subscribe and hit the bell!"},
            {"speaker": "Emma", "text": "Now practice this sentence out loud."},
        ]
    }
    cleaned = _clean_challenge_dialogue(script, day_number=2)
    assert len(cleaned["dialogue"]) == 2
    assert not any(is_outro_line(t["text"]) for t in cleaned["dialogue"])


def test_clean_challenge_dialogue_keeps_day_7_final_outro():
    script = {
        "dialogue": [
            {"speaker": "Emma", "text": "Welcome to the recap."},
            {"speaker": "Liam", "text": "Here is question one."},
            {"speaker": "Emma", "text": "Thanks for listening, see you next time!"},
        ]
    }
    cleaned = _clean_challenge_dialogue(script, day_number=7)
    assert is_outro_line(cleaned["dialogue"][-1]["text"])


def test_ensure_english_description_cta_dedupes_playlist_variants():
    description = """English quiz for beginners: learn the idiom fast.
Practice English vocabulary with Emma and Liam.

Watch playlist here: {playlist_url}
Watch the playlist here: {playlist_url}

#Shorts #EnglishQuiz"""

    cleaned = ensure_english_description_cta(description)

    assert cleaned.count("{playlist_url}") == 1
    assert cleaned.count("📺 Watch the playlist here: {playlist_url}") == 1
    assert "Watch playlist here:" not in cleaned


def test_ensure_english_description_cta_adds_spaced_icon_block():
    cleaned = ensure_english_description_cta(
        "English listening practice for daily conversation.\nLearn useful phrases today."
    )

    assert "\n\n📺 Watch the playlist here: {playlist_url}\n\n🔔 Subscribe" in cleaned
    assert "\n\n💬 Comment below:" in cleaned


def test_ensure_english_quiz_shorts_hashtags_promotes_required_line():
    description = """English quiz for beginners.
Practice today's idiom with Emma and Liam.

#Grammar #Shorts #EnglishQuiz

🔔 Subscribe for more lessons.
#LearnEnglish #Vocabulary"""

    cleaned = ensure_english_quiz_shorts_hashtags(description)
    hashtag_lines = [line for line in cleaned.splitlines() if "#" in line]

    assert hashtag_lines[0] == "#Shorts #EnglishQuiz #LearnEnglish"
    assert "#Grammar" in hashtag_lines[1]
    assert "#Vocabulary" in hashtag_lines[2]
    assert cleaned.count("#Shorts") == 1
    assert cleaned.count("#EnglishQuiz") == 1
    assert cleaned.count("#LearnEnglish") == 1


def test_ensure_english_quiz_shorts_hashtags_appends_when_missing():
    cleaned = ensure_english_quiz_shorts_hashtags("English quiz for beginners.")

    assert cleaned.splitlines()[-1] == "#Shorts #EnglishQuiz #LearnEnglish"
