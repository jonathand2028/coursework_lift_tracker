"""
Coursework & Lift Tracker - Streamlit MVP
=========================================

One small app, two jobs, one user (you):

  STUDY:  read a syllabus / textbook PDF and generate short quizzes for a
          chosen topic.
  LIFT:   read a workout history (CSV) and compute the exact targets for the
          next session using a simple progressive-overload rule.

The AI that writes quiz questions is kept BEHIND ONE FUNCTION
(`generate_quiz`) so it can be swapped out. If you provide an OpenAI-style
API key it uses a real model; if not, it falls back to a built-in
question generator so the app always works offline.

Run it:
    pip install streamlit pandas pypdf requests
    streamlit run app.py

The progression math and the offline quiz generator are plain Python at the
top of the file with no Streamlit dependency, so they can be unit-tested.
"""

import io
import re
import json
import random
from datetime import datetime


# ======================================================================
#  LIFT:  progressive-overload logic  (pure, testable)
# ======================================================================

def _is_success(reps, sets, target_reps, target_sets):
    """A session 'succeeds' when you hit the target reps on every target set."""
    return reps >= target_reps and sets >= target_sets


def next_targets(rows, target_reps=5, target_sets=5, increment=5.0,
                 deload_factor=0.9, stall_limit=2):
    """Compute the next session per exercise.

    `rows` is a list of dicts: {date, exercise, weight, reps, sets}.
    Returns a list of recommendation dicts, one per exercise.

    Rule:
      - If your most recent session hit the target -> add `increment`.
      - If you missed, that is a 'stall'. After `stall_limit` stalls in a
        row -> deload (multiply weight by `deload_factor`) and reset.
    """
    # group by exercise, keep chronological order
    by_ex = {}
    for r in sorted(rows, key=lambda x: str(x.get("date", ""))):
        by_ex.setdefault(r["exercise"], []).append(r)

    out = []
    for exercise, history in by_ex.items():
        last = history[-1]
        last_weight = float(last["weight"])
        reps = int(last["reps"])
        sets = int(last["sets"])

        # count consecutive stalls ending at the most recent session
        stalls = 0
        for r in reversed(history):
            if _is_success(int(r["reps"]), int(r["sets"]), target_reps, target_sets):
                break
            stalls += 1

        if _is_success(reps, sets, target_reps, target_sets):
            rec_weight = last_weight + increment
            action = "progress"
            note = f"Hit {reps}x{sets}. Add {increment:g} and go again."
        elif stalls >= stall_limit:
            rec_weight = round(last_weight * deload_factor, 1)
            action = "deload"
            note = (f"Stalled {stalls} times. Deload to "
                    f"{rec_weight:g} and rebuild.")
        else:
            rec_weight = last_weight
            action = "repeat"
            note = (f"Missed target ({reps}x{sets}). Repeat "
                    f"{last_weight:g} until you hit {target_reps}x{target_sets}.")

        out.append({
            "exercise": exercise,
            "last_weight": last_weight,
            "last_result": f"{reps} reps x {sets} sets",
            "next_weight": rec_weight,
            "next_scheme": f"{target_sets} x {target_reps}",
            "action": action,
            "note": note,
        })
    return out


def parse_workout_csv(text):
    """Parse a CSV string into row dicts. Expects headers:
    date, exercise, weight, reps, sets (case-insensitive)."""
    import csv
    rows = []
    reader = csv.DictReader(io.StringIO(text))
    norm = {h: h.strip().lower() for h in (reader.fieldnames or [])}
    for raw in reader:
        row = {norm.get(k, k): v for k, v in raw.items()}
        try:
            rows.append({
                "date": row.get("date", ""),
                "exercise": row.get("exercise", "").strip(),
                "weight": float(row.get("weight", 0)),
                "reps": int(float(row.get("reps", 0))),
                "sets": int(float(row.get("sets", 0))),
            })
        except (ValueError, TypeError):
            continue
    return rows


SAMPLE_WORKOUT_CSV = """date,exercise,weight,reps,sets
2026-06-01,Squat,185,5,5
2026-06-01,Bench,135,5,5
2026-06-03,Squat,190,5,5
2026-06-03,Bench,140,4,5
2026-06-05,Squat,195,5,5
2026-06-05,Bench,140,4,5
"""


# ======================================================================
#  STUDY:  quiz generation  (offline fallback is pure + testable)
# ======================================================================

_STOPWORDS = set("""
the a an and or of to in on for with is are was were be been being this that
these those as at by from it its into will shall can may your you we our their
""".split())


def generate_quiz_offline(text, topic="", n=5):
    """Build simple recall questions from source text, no API needed.

    Strategy: find informative sentences (optionally about `topic`), then turn
    each into a fill-in-the-blank by hiding its most distinctive keyword.
    """
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if len(s.strip()) > 40]
    if topic:
        t = topic.lower()
        focused = [s for s in sentences if t in s.lower()]
        sentences = focused or sentences

    random.shuffle(sentences)
    quiz = []
    for s in sentences:
        words = re.findall(r"[A-Za-z][A-Za-z\-]{3,}", s)
        candidates = [w for w in words if w.lower() not in _STOPWORDS]
        if not candidates:
            continue
        # pick the longest word as the "key term" to blank out
        answer = max(candidates, key=len)
        blanked = re.sub(r"\b" + re.escape(answer) + r"\b",
                         "______", s, count=1)
        quiz.append({
            "question": blanked,
            "answer": answer,
            "type": "fill-in-the-blank",
        })
        if len(quiz) >= n:
            break
    return quiz


def generate_quiz(text, topic="", n=5, api_key="", model="gpt-4o-mini",
                  base_url="https://api.openai.com/v1"):
    """Single swap point for the 'brain'.

    With an API key: ask a real model for a richer quiz.
    Without one: fall back to the offline generator above.
    Returns a list of {question, answer, type}.
    """
    if not api_key:
        return generate_quiz_offline(text, topic, n)

    try:
        import requests
        prompt = (
            f"Create a {n}-question short-answer quiz to help a student study "
            f"the topic '{topic or 'this material'}'. Base it ONLY on the text "
            f"below. Return JSON: a list of objects with 'question' and "
            f"'answer'.\n\nTEXT:\n{text[:6000]}"
        )
        resp = requests.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
            },
            timeout=60,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        match = re.search(r"\[.*\]", content, re.DOTALL)
        data = json.loads(match.group(0) if match else content)
        return [{"question": q.get("question", ""),
                 "answer": q.get("answer", ""),
                 "type": "short-answer"} for q in data][:n]
    except Exception:
        # Never let the model break the app - fall back gracefully.
        return generate_quiz_offline(text, topic, n)


def read_pdf_text(file_bytes):
    """Extract text from a syllabus/textbook PDF."""
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(file_bytes))
    return "\n".join((p.extract_text() or "") for p in reader.pages)


# ======================================================================
#  Streamlit UI
# ======================================================================

def main():
    import streamlit as st
    import pandas as pd

    st.set_page_config(page_title="Coursework & Lift Tracker", page_icon="📚",
                       layout="centered")
    st.title("Coursework & Lift Tracker")

    with st.sidebar:
        st.header("Quiz brain (optional)")
        api_key = st.text_input("API key", type="password",
                                help="Leave blank to use the built-in offline "
                                     "quiz generator.")
        st.caption("With a key, quizzes use a real model. Without one, the app "
                   "still works using a simple built-in generator.")

    study_tab, lift_tab = st.tabs(["📚 Study", "🏋️ Lift"])

    # ---------------- STUDY ----------------
    with study_tab:
        st.subheader("Generate a quiz from your course material")
        pdf = st.file_uploader("Syllabus or textbook PDF", type=["pdf"],
                               key="study_pdf")
        pasted = st.text_area("...or paste material here", height=140)
        col1, col2 = st.columns(2)
        topic = col1.text_input("Topic / week (optional)",
                                placeholder="e.g. supply and demand")
        n = col2.number_input("Questions", 1, 15, 5)

        if st.button("Generate quiz", type="primary"):
            text = ""
            if pdf:
                try:
                    text = read_pdf_text(pdf.read())
                except Exception as e:
                    st.error(f"Could not read PDF: {e}")
            if pasted.strip():
                text += "\n" + pasted
            if len(text.strip()) < 40:
                st.warning("Add a PDF or paste more text to quiz from.")
            else:
                quiz = generate_quiz(text, topic, int(n), api_key=api_key)
                if not quiz:
                    st.warning("Could not build questions from this text.")
                for i, q in enumerate(quiz, 1):
                    st.markdown(f"**{i}. {q['question']}**")
                    with st.expander("Show answer"):
                        st.write(q["answer"])

    # ---------------- LIFT ----------------
    with lift_tab:
        st.subheader("Compute your next session")
        st.caption("CSV columns: date, exercise, weight, reps, sets")
        csv_file = st.file_uploader("Workout history CSV", type=["csv"],
                                    key="lift_csv")
        use_sample = st.checkbox("Use sample data", value=not bool(csv_file))

        c1, c2, c3 = st.columns(3)
        target_reps = c1.number_input("Target reps", 1, 20, 5)
        target_sets = c2.number_input("Target sets", 1, 10, 5)
        increment = c3.number_input("Add (lbs)", 1.0, 50.0, 5.0)

        text = None
        if csv_file and not use_sample:
            text = csv_file.read().decode("utf-8", errors="ignore")
        elif use_sample:
            text = SAMPLE_WORKOUT_CSV
            with st.expander("Sample data"):
                st.code(SAMPLE_WORKOUT_CSV)

        if text:
            rows = parse_workout_csv(text)
            if not rows:
                st.warning("No valid rows found. Check the column names.")
            else:
                recs = next_targets(rows, int(target_reps), int(target_sets),
                                    float(increment))
                st.markdown("### Next session")
                badge = {"progress": "🟢", "repeat": "🟡", "deload": "🔵"}
                for r in recs:
                    st.markdown(
                        f"{badge.get(r['action'], '')} **{r['exercise']}**: "
                        f"{r['next_weight']:g} lbs for {r['next_scheme']}"
                    )
                    st.caption(r["note"])
                st.markdown("---")
                st.dataframe(pd.DataFrame(recs)[
                    ["exercise", "last_weight", "last_result",
                     "next_weight", "next_scheme", "action"]
                ], use_container_width=True)


if __name__ == "__main__":
    main()
