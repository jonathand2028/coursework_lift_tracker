"""
Unit tests for the Coursework & Lift Tracker.

Run:  pytest -q
These cover the pure logic (workout parsing, categorization, double
progression, quiz JSON parsing), with no Streamlit or network needed.
"""

import app


def test_parse_workout_counts_and_skips_bodyweight():
    rows = app.parse_workout(app.SAMPLE_NOTES)
    # 4 strength + 4 power + 5 accessory lines with weights = 13
    assert len(rows) == 13
    names = [r["Exercise"] for r in rows]
    assert "Back Squats" in names
    assert "Lateral Raises" in names


def test_categorize():
    assert app.categorize("Back Squats", "Strength Training") == "compound_lower"
    assert app.categorize("Deadlifts") == "compound_lower"
    assert app.categorize("Bench Press", "Strength Training") == "compound_upper"
    assert app.categorize("Dumbbell Biceps Curls", "Accessory") == "isolation"
    assert app.categorize("Lateral Raises") == "small_iso"
    assert app.categorize("Rear Delt Flies") == "small_iso"


def test_defaults_match_category():
    assert app.CATEGORY_DEFAULTS["compound_lower"][:2] == (4, 6)
    assert app.CATEGORY_DEFAULTS["isolation"][:2] == (8, 12)
    assert app.CATEGORY_DEFAULTS["small_iso"][:2] == (12, 15)


def test_double_progression_add_reps_then_load():
    # in-range -> add reps
    w, r, action, _ = app.double_progression(35, 8, 12, 8, True, 5, 2)
    assert (w, r, action) == (35, 10, "add reps")
    # at top -> add load, reset to bottom
    w, r, action, _ = app.double_progression(35, 8, 12, 12, True, 5, 2)
    assert (w, r, action) == (40, 8, "add load")


def test_double_progression_compound_step_one():
    w, r, action, _ = app.double_progression(325, 4, 6, 6, True, 10, 1)
    assert (w, r, action) == (335, 4, "add load")
    w, r, action, _ = app.double_progression(325, 4, 6, 4, True, 10, 1)
    assert (w, r, action) == (325, 5, "add reps")


def test_double_progression_miss_holds():
    w, r, action, _ = app.double_progression(185, 4, 6, 5, False, 5, 1)
    assert w == 185 and action == "hold"


def test_small_iso_increment_is_two_point_five():
    w, _, action, _ = app.double_progression(22.5, 12, 15, 15, True, 2.5, 2)
    assert w == 25.0 and action == "add load"


def test_parse_quiz_json_extracts_list():
    raw = ('Here is your quiz: '
           '[{"question": "Q1?", "choices": ["a","b","c","d"], '
           '"answer": "a", "explanation": "because"}]')
    quiz = app.parse_quiz_json(raw)
    assert len(quiz) == 1
    assert quiz[0]["question"] == "Q1?"
    assert quiz[0]["answer"] == "a"
    assert len(quiz[0]["choices"]) == 4


def test_build_quiz_prompt_includes_material():
    p = app.build_quiz_prompt("photosynthesis basics", "Multiple choice", 5)
    assert "photosynthesis basics" in p
    assert "5 multiple choice" in p
