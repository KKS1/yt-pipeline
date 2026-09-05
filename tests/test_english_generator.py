from scripts.english_generator import (
    _clean_challenge_dialogue,
    align_scenes_to_turns,
    build_scene_timeline,
    ensure_english_description_cta,
    ensure_english_quiz_shorts_hashtags,
    ensure_english_vibes_hashtags,
    finalize_english_description,
    inject_scene_timeline,
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
    # DEPRECATED: combine_english_parts removed - replaced by single storytelling prompt
    # This test is no longer applicable
    pass


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


def test_ensure_english_description_cta_preserves_existing_playlist_urls():
    description = """English quiz for beginners: learn the idiom fast.
Practice English vocabulary with Emma and Liam.

Watch playlist here: {playlist_url}
Watch the playlist here: {playlist_url}

#Shorts #EnglishQuiz"""

    cleaned = ensure_english_description_cta(description)

    # Function preserves existing playlist lines (doesn't deduplicate them)
    assert cleaned.count("{playlist_url}") == 2
    # Does NOT add a third playlist line
    assert cleaned.count("📺 Watch the playlist here: {playlist_url}") == 0


def test_ensure_english_description_cta_adds_spaced_icon_block():
    cleaned = ensure_english_description_cta(
        "English listening practice for daily conversation.\nLearn useful phrases today."
    )

    assert "📺 Watch the Everyday English Practice playlist here: {playlist_url}" in cleaned
    assert "💬 Comment below:" in cleaned
    assert "🔔 Subscribe" in cleaned


def test_ensure_english_description_cta_adds_scene_timeline_placeholder():
    cleaned = ensure_english_description_cta(
        "Natural English for real conversations.\nSpeak like a native today.",
        include_timeline=True,
    )

    assert "{scene_timeline}" in cleaned
    assert "0:00 - Start the lesson" not in cleaned


def test_ensure_english_vibes_hashtags():
    cleaned = ensure_english_vibes_hashtags("Learn English today.\n\n#LearnEnglish")
    assert "#EnglishListeningPractice" in cleaned


def test_finalize_english_description_includes_opener_and_hashtag():
    cleaned = finalize_english_description("Practice phrasal verbs today.", is_quiz=True)
    assert "🎯" in cleaned.splitlines()[0]
    assert "#LearnEnglish" in cleaned


def test_build_scene_timeline_formats_timestamps():
    scenes = [
        {"scene_id": 1, "scene_label": "Library Intro", "start_turn": 0, "end_turn": 1},
        {"scene_id": 2, "scene_label": "Cafe Scene", "start_turn": 2, "end_turn": 3},
    ]
    per_turn_times = [(0.0, 5.0), (5.0, 10.0), (10.0, 40.0), (40.0, 65.0)]
    block = build_scene_timeline(scenes, per_turn_times)
    assert "0:00 - Library Intro" in block
    assert "0:10 - Cafe Scene" in block


def test_inject_scene_timeline_replaces_placeholder():
    description = "Intro\n\n{scene_timeline}\n\nMore text"
    block = "📑 Timeline:\n0:00 - Start"
    result = inject_scene_timeline(description, block)
    assert "{scene_timeline}" not in result
    assert "0:00 - Start" in result


def test_align_scenes_to_turns():
    dialogue = [
        {"speaker": "Emma", "text": "Hello"},
        {"speaker": "Liam", "text": "Hi there"},
        {"speaker": "Emma", "text": "Let's begin"},
    ]
    scenes = [
        {
            "scene_id": 1,
            "dialogues": [
                {"character": "Emma", "text": "Hello"},
                {"character": "Liam", "text": "Hi there"},
            ],
        },
        {
            "scene_id": 2,
            "dialogues": [{"character": "Emma", "text": "Let's begin"}],
        },
    ]
    aligned = align_scenes_to_turns(scenes, dialogue)
    assert aligned[0]["start_turn"] == 0
    assert aligned[0]["end_turn"] == 1
    assert aligned[1]["start_turn"] == 2
    assert aligned[1]["end_turn"] == 2


def test_ensure_english_quiz_shorts_hashtags_strips_and_promotes():
    description = """English quiz for beginners.
Practice today's idiom with Emma and Liam.

#Grammar #Shorts #EnglishQuiz

🔔 Subscribe for more lessons.
#LearnEnglish #Vocabulary"""

    cleaned = ensure_english_quiz_shorts_hashtags(description)
    hashtag_lines = [line for line in cleaned.splitlines() if "#" in line]

    # All hashtags stripped from body, single promoted line appended at end
    assert len(hashtag_lines) == 1
    assert "#Shorts" in hashtag_lines[0]
    assert "#EnglishQuiz" in hashtag_lines[0]
    assert "#LearnEnglish" in hashtag_lines[0]
    # Original hashtags (#Grammar, #Vocabulary) are stripped from body
    assert "#Grammar" not in cleaned
    assert "#Vocabulary" not in cleaned


def test_ensure_english_quiz_shorts_hashtags_appends_when_missing():
    cleaned = ensure_english_quiz_shorts_hashtags("English quiz for beginners.")

    last_line = cleaned.splitlines()[-1]
    assert "#Shorts" in last_line
    assert "#EnglishQuiz" in last_line
    assert "#LearnEnglish" in last_line


def test_flatten_dialogue():
    from scripts.english_generator import flatten_dialogue
    nested = [
        {"speaker": "Emma", "text": "Hello"},
        {
            "dialogue": [
                {"speaker": "Liam", "text": "Hi there"},
                {
                    "dialogue_list": [
                        {"speaker": "Emma", "text": "Nested dialogue"}
                    ]
                }
            ]
        },
        {"speaker": "Liam", "text": "Goodbye"}
    ]
    expected = [
        {"speaker": "Emma", "text": "Hello"},
        {"speaker": "Liam", "text": "Hi there"},
        {"speaker": "Emma", "text": "Nested dialogue"},
        {"speaker": "Liam", "text": "Goodbye"}
    ]
    assert flatten_dialogue(nested) == expected


def test_align_scenes_to_turns_normalizes_extensions():
    from scripts.english_generator import align_scenes_to_turns
    scenes = [
        {
            "scene_id": 1,
            "scene_label": "Intro",
            "image_filename": "scene_1_intro.jpg",
            "visual_prompt": "Intro scene",
            "start_turn": 0,
            "end_turn": 1
        },
        {
            "scene_id": 2,
            "scene_label": "Body",
            "image_filename": "scene_2_body.png",
            "visual_prompt": "Body scene",
            "start_turn": 2,
            "end_turn": 3
        }
    ]
    dialogue = [
        {"speaker": "Emma", "text": "Hello 1"},
        {"speaker": "Liam", "text": "Hello 2"},
        {"speaker": "Emma", "text": "Hello 3"},
        {"speaker": "Liam", "text": "Hello 4"}
    ]
    aligned = align_scenes_to_turns(scenes, dialogue)
    assert aligned[0]["image_filename"] == "scene_1_intro.png"
    assert aligned[1]["image_filename"] == "scene_2_body.png"
