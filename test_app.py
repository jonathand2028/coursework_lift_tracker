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


def test_database_save_and_load_roundtrip():
    conn = app.get_connection(":memory:")
    app.init_db(conn)
    assert app.load_latest_rows(conn) == []

    rows = app.parse_workout(app.SAMPLE_NOTES)
    app.save_session(conn, rows, ts="2026-06-20T10:00:00")
    loaded = app.load_latest_rows(conn)
    # same lift can repeat across days, so all rows are preserved by (day, lift)
    assert len(loaded) == len(rows)
    by = {(r["Day"], r["Exercise"]): r for r in loaded}
    strength_squat = by[("Strength Training", "Back Squats")]
    assert strength_squat["Weight"] == 325
    assert strength_squat["Rep low"] == 4

    # a newer session for that lift should win in load_latest_rows
    app.save_session(conn, [{**strength_squat, "Weight": 335}],
                     ts="2026-06-23T10:00:00")
    again = {(r["Day"], r["Exercise"]): r for r in app.load_latest_rows(conn)}
    assert again[("Strength Training", "Back Squats")]["Weight"] == 335
    assert len(app.session_dates(conn)) == 2


def test_exercise_progress_and_body_metrics():
    conn = app.get_connection(":memory:")
    app.init_db(conn)
    app.save_session(conn, [{"Day": "S", "Exercise": "Bench", "Type": "compound_upper",
                             "Weight": 175, "Rep low": 4, "Rep high": 6,
                             "Reps last": 4, "Add (lbs)": 5, "_rep_step": 1}],
                     ts="2026-06-01T00:00:00")
    app.save_session(conn, [{"Day": "S", "Exercise": "Bench", "Type": "compound_upper",
                             "Weight": 180, "Rep low": 4, "Rep high": 6,
                             "Reps last": 6, "Add (lbs)": 5, "_rep_step": 1}],
                     ts="2026-06-08T00:00:00")
    prog = app.exercise_progress(conn, "S", "Bench")
    assert [w for _, w in prog] == [175, 180]

    app.save_body_metric(conn, 185.0, 14.0, ts="2026-06-01T00:00:00")
    app.save_body_metric(conn, 183.5, 13.5, ts="2026-06-08T00:00:00")
    metrics = app.load_body_metrics(conn)
    assert len(metrics) == 2
    assert metrics[0]["bodyweight"] == 185.0


def test_summarize_recs():
    recs = [{"action": "add load"}, {"action": "add reps"}, {"action": "hold"}]
    s = app.summarize_recs(recs)
    assert "moving up" in s and "adding reps" in s and "holding" in s


def test_study_guide_prompt():
    p = app.build_quiz_prompt("cells and mitochondria", "Topic study guide", 4)
    assert "cells and mitochondria" in p
    assert "important topics" in p


def test_new_study_modes_prompts():
    cm = app.build_quiz_prompt("photosynthesis", "Common mistakes", 3)
    assert "photosynthesis" in cm and "often get wrong" in cm
    ex = app.build_quiz_prompt("photosynthesis", "Exam-style questions", 3)
    assert "exam-style questions" in ex


def test_estimate_1rm():
    assert app.estimate_1rm(100, 1) == 100
    # Epley: 200 * (1 + 5/30) = 233.3 -> nearest 5 = 235
    assert app.estimate_1rm(200, 5) == 235
    assert app.estimate_1rm(135, 10) == 180


def test_answer_matches_lenient():
    assert app.answer_matches("Paris", "paris")
    assert app.answer_matches("B) Mitochondria", "Mitochondria")
    assert app.answer_matches("the cell wall", "Cell Wall")
    assert not app.answer_matches("Nucleus", "Ribosome")
    assert not app.answer_matches(None, "Anything")


def test_grade_mc_scores_correctly():
    quiz = [
        {"question": "Capital of France?", "choices": ["Paris", "Rome"], "answer": "Paris"},
        {"question": "2+2?", "choices": ["3", "4"], "answer": "4"},
        {"question": "Sky color?", "choices": ["Blue", "Green"], "answer": "Blue"},
    ]
    answers = {1: "Paris", 2: "3", 3: None}
    score, results = app.grade_mc(quiz, answers)
    assert score == 1
    assert results[0]["correct"] and not results[1]["correct"]
    assert results[2]["selected"] is None


def test_build_coach_prompt_includes_lifts():
    recs = [{"Exercise": "Back Squats", "Type": "compound_lower",
             "action": "add load", "next_weight": 335, "next_reps": 4}]
    p = app.build_coach_prompt(recs, metrics=[{"bodyweight": 185}])
    assert "Back Squats" in p
    assert "strength coach" in p
    assert "185" in p
