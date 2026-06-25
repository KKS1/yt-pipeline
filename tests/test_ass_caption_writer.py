from pathlib import Path

from scripts.ass_caption_writer import generate_ass_captions_from_words


def test_pause_guess_freezes_prompt_counts_down_and_gates_reveal(tmp_path: Path):
    output = tmp_path / "pause_guess.ass"
    dialogue = [
        {
            "speaker": "Emma",
            "text": "Can you guess the natural phrase?",
            "idiom_windows": [
                {
                    "idiom": "answer phrase",
                    "definition": "the answer",
                    "start_turn": 0,
                    "end_turn": 2,
                }
            ],
        },
        {"speaker": "Liam", "text": "[PAUSE 3 SECONDS]"},
        {"speaker": "Emma", "text": "The answer phrase is break a leg."},
    ]
    per_turn_times = [(0.0, 2.0), (2.0, 5.0), (5.0, 7.0)]
    words = [
        {"word": "Can", "start": 0.10, "end": 0.25},
        {"word": "you", "start": 0.26, "end": 0.40},
        {"word": "guess", "start": 0.41, "end": 0.70},
        {"word": "The", "start": 4.80, "end": 5.10},
        {"word": "answer", "start": 5.11, "end": 5.45},
        {"word": "phrase", "start": 5.46, "end": 5.80},
    ]

    generate_ass_captions_from_words(
        words=words,
        output_ass=str(output),
        dialogue=dialogue,
        per_turn_times=per_turn_times,
        idiom_phrases=["answer phrase"],
        is_shorts=True,
    )

    ass = output.read_text(encoding="utf-8")

    assert "Style: Countdown" in ass
    assert "Dialogue: 0,0:00:02.00,0:00:05.00,Emma" in ass
    assert "Can you guess the natural phrase?" in ass
    assert "Dialogue: 2,0:00:02.00,0:00:03.00,Countdown" in ass
    assert "Dialogue: 2,0:00:03.00,0:00:04.00,Countdown" in ass
    assert "Dialogue: 2,0:00:04.00,0:00:05.00,Countdown" in ass

    answer_lines = [line for line in ass.splitlines() if "answer" in line.lower()]
    assert any("IdiomCard" in line and "0:00:05.00" in line for line in answer_lines)
    assert any("Dialogue: 0,0:00:05.00" in line for line in answer_lines)
    assert not any("Dialogue: 0,0:00:04." in line and "answer" in line.lower() for line in answer_lines)
