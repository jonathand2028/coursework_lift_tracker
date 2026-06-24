"""
Coursework & Lift Tracker - Streamlit MVP (iteration 2)
=======================================================

Two tools, one user (you):

  STUDY (Tab 1):  paste lecture notes or upload a PDF, and generate a real
                  multiple-choice / short-answer practice test using an LLM
                  (OpenAI or Anthropic). Clean flashcard-style review UI.

  LIFT  (Tab 2):  paste your workout notes the way you actually keep them in
                  a Google Doc. The app parses them, applies linear
                  progressive overload (hit target -> add weight; miss ->
                  hold), and prints your exact targets for next session,
                  ready to paste back into your notes.

Run it:
    pip install -r requirements.txt
    streamlit run app.py

The parsing and progression logic at the top of this file is plain Python
with no Streamlit dependency, so it can be unit-tested on its own.
"""

import io
import re
import json

# ======================================================================
#  STUDY: prompt building + LLM calls + response parsing  (pure/testable)
# ======================================================================

def build_quiz_prompt(source_text, qtype, n):
    """Return the instruction sent to the model. Asks for strict JSON."""
    if qtype == "Multiple choice":
        shape = (
            'a JSON array of objects, each: '
            '{"question": str, "choices": [4 strings], '
            '"answer": "the exact correct choice", "explanation": str}'
        )
    else:
        shape = (
            'a JSON array of objects, each: '
            '{"question": str, "choices": [], '
            '"answer": str, "explanation": str}'
        )
    return (
        f"You are a study-quiz generator. Using ONLY the material below, "
        f"write {n} {qtype.lower()} questions that test understanding of the "
        f"key concepts. Return {shape}. Return JSON only, no prose.\n\n"
        f"MATERIAL:\n{source_text[:8000]}"
    )


def parse_quiz_json(content):
    """Pull a clean list of question dicts out of a model's raw reply."""
    if not content:
        return []
    match = re.search(r"\[.*\]", content, re.DOTALL)
    raw = match.group(0) if match else content
    data = json.loads(raw)
    quiz = []
    for q in data:
        quiz.append({
            "question": str(q.get("question", "")).strip(),
            "choices": [str(c) for c in q.get("choices", []) or []],
            "answer": str(q.get("answer", "")).strip(),
            "explanation": str(q.get("explanation", "")).strip(),
        })
    return quiz


def call_openai(api_key, prompt, model="gpt-4o-mini"):
    import requests
    r = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={"model": model,
              "messages": [{"role": "user", "content": prompt}],
              "temperature": 0.4},
        timeout=90,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def call_anthropic(api_key, prompt, model="claude-3-5-sonnet-20241022"):
    import requests
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": api_key,
                 "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
        json={"model": model, "max_tokens": 2000,
              "messages": [{"role": "user", "content": prompt}]},
        timeout=90,
    )
    r.raise_for_status()
    return r.json()["content"][0]["text"]


def generate_quiz(api_key, provider, source_text, qtype, n):
    """One swap point for the 'brain'. Returns list of question dicts."""
    prompt = build_quiz_prompt(source_text, qtype, n)
    content = (call_anthropic(api_key, prompt) if provider == "Anthropic"
               else call_openai(api_key, prompt))
    return parse_quiz_json(content)


def read_pdf_text(file_bytes):
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(file_bytes))
    return "\n".join((p.extract_text() or "") for p in reader.pages)


# ======================================================================
#  LIFT: parse free-text workout notes + progressive overload (pure)
# ======================================================================

LOWER_KEYWORDS = [
    "squat", "deadlift", "lunge", "leg press", "calf", "hip thrust",
    "rdl", "romanian", "leg curl", "leg extension", "hack",
]

# words to strip out of an exercise name so it reads cleanly
FILLER = [
    "to parallel", "full range", "slow down fast lift up", "slow down",
    "fast lift up", "per side", "until slowing or", "reps", "rep",
]

# header lines that name a workout day
DAY_HINTS = ["training", "day", "session"]


def classify_region(name):
    """Lower body (legs/posterior chain) vs upper body, by keyword."""
    n = name.lower()
    return "lower" if any(k in n for k in LOWER_KEYWORDS) else "upper"


def _clean_name(raw):
    name = re.sub(r"\([^)]*\)", " ", raw)              # drop parentheticals
    name = re.sub(r"^\s*\d+[.)]\s*", " ", name)         # leading list marker "1."
    name = re.sub(r"\d+\s*sets?\s*of\s*\d*", " ", name, flags=re.I)  # "4 sets of 4"
    name = re.sub(r"working sets?.*$", " ", name, flags=re.I)
    name = re.sub(r"\b\d+\s*(?:pounds|lbs)\b", " ", name, flags=re.I)
    for f in FILLER:
        name = re.sub(re.escape(f), " ", name, flags=re.I)
    name = re.sub(r"[~\-]", " ", name)
    name = re.sub(r"^\s*\d+\s+", " ", name)            # any stray leading number
    name = re.sub(r"\s+", " ", name).strip(" .,")
    return name.title() if name else "Exercise"


def _parse_reps(line, default_reps):
    """Target reps from 'sets of 4' or '(until slowing or 6 reps)'."""
    paren = re.search(r"sets?\s*of\s*\(([^)]*)\)", line, flags=re.I)
    if paren:
        nums = re.findall(r"(\d+)\s*reps?", paren.group(1), flags=re.I)
        if nums:
            return int(nums[-1])
    plain = re.search(r"sets?\s*of\s*(\d+)", line, flags=re.I)
    if plain:
        return int(plain.group(1))
    return default_reps


def _parse_weight(line):
    """Working-set weight: number after 'working sets', else first lb value."""
    m = re.search(r"working sets?\s*~?\s*(\d+(?:\.\d+)?)", line, flags=re.I)
    if m:
        return float(m.group(1))
    m = re.search(r"~?\s*(\d+(?:\.\d+)?)\s*(?:pounds|lbs)", line, flags=re.I)
    if m:
        return float(m.group(1))
    return None


def parse_workout(text, default_reps=4):
    """Parse free-text notes into a list of exercise dicts."""
    exercises = []
    day = "Workout"
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        has_set = re.search(r"sets?\s*of", s, flags=re.I)
        # day header: text line, no "sets of", mentions training/day
        if not has_set:
            if any(h in s.lower() for h in DAY_HINTS) and len(s) < 60:
                day = re.sub(r"[:\-]+$", "", s).strip()
            continue
        weight = _parse_weight(s)
        if weight is None:
            continue  # warm-up-only or unparseable line
        name = _clean_name(s)
        exercises.append({
            "day": day,
            "name": name,
            "reps": _parse_reps(s, default_reps),
            "weight": weight,
            "each": "each" in s.lower() or "per side" in s.lower(),
            "region": classify_region(name),
        })
    return exercises


def next_weight(weight, region, hit, upper_inc, lower_inc):
    """Linear progressive overload: add on success, hold on a miss."""
    if not hit:
        return weight
    return weight + (lower_inc if region == "lower" else upper_inc)


def build_next_session(exercises, missed_names, upper_inc=5.0, lower_inc=10.0):
    """Return per-exercise recommendations for the next session."""
    missed = set(missed_names or [])
    out = []
    for ex in exercises:
        hit = ex["name"] not in missed
        nxt = next_weight(ex["weight"], ex["region"], hit, upper_inc, lower_inc)
        out.append({
            **ex,
            "hit": hit,
            "next_weight": nxt,
            "delta": round(nxt - ex["weight"], 1),
        })
    return out


def format_session_text(recs):
    """A clean block the user can paste back into their Google Doc."""
    lines, day = [], None
    for r in recs:
        if r["day"] != day:
            day = r["day"]
            lines.append(f"\n{day}")
        each = " each" if r["each"] else ""
        change = (f"(+{r['delta']:g})" if r["delta"] > 0 else "(hold)")
        lines.append(
            f"- {r['name']}: 4 sets of {r['reps']}, "
            f"working set {r['next_weight']:g} lbs{each} {change}"
        )
    return "\n".join(lines).strip()


SAMPLE_NOTES = """Strength Training
1. 4 sets of 4 to parallel back squats (1st and 2nd set lighter weight, working sets 325 pounds)
2. 4 sets of 4 full range bench press (1st and 2nd set lighter weight, working sets 175 pounds)
3. 4 sets of 4 full range deadlifts (1st set and 2nd lighter weight, working sets 335 pounds)
4. 4 sets of 4 full range wide grip pull ups (1st and 2nd set lighter weight, working sets 90 pounds)

Power Training
1. 4 sets of (until slowing or 6 reps) to parallel back squats (working sets 235 pounds)
2. 4 sets of (until slowing or 4 reps) full range bench press (working sets 145 pounds)
3. 4 sets of (until slowing or 6 reps) full range deadlifts (working sets 275 pounds)
4. 4 sets of (until slowing or 6 reps) full range wide grip pull ups (working sets 35 pounds)

Accessory / Aesthetic Day (Dumbbells)
1. 4 sets of 9 incline dumbbell press (working sets ~60 lbs each)
2. 4 sets of 9 one-arm dumbbell row per side (working sets ~70 lbs)
3. 4 sets of 12 lateral raises (working sets ~22.5 lbs each)
4. 4 sets of 12 dumbbell biceps curls (working sets ~35 lbs each)
5. 4 sets of 15 rear delt flies (working sets ~15 lbs each)
"""


# ======================================================================
#  Streamlit UI
# ======================================================================

def main():
    import streamlit as st

    st.set_page_config(page_title="Coursework & Lift Tracker", page_icon="📚",
                       layout="centered")
    st.title("Coursework & Lift Tracker")

    study_tab, lift_tab = st.tabs(["📚 Study", "🏋️ Lift"])

    # ----------------------------- STUDY -----------------------------
    with study_tab:
        st.subheader("Generate a practice test from your notes")

        c1, c2 = st.columns(2)
        provider = c1.selectbox("Model provider", ["OpenAI", "Anthropic"])
        api_key = c2.text_input("API key", type="password",
                                placeholder="sk-... or anthropic key")

        pdf = st.file_uploader("Lecture notes / textbook PDF", type=["pdf"])
        pasted = st.text_area("...or paste your notes here", height=160)

        c3, c4 = st.columns(2)
        qtype = c3.radio("Question type",
                         ["Multiple choice", "Short answer"], horizontal=True)
        n = c4.slider("How many questions", 3, 15, 6)

        if st.button("Generate practice test", type="primary"):
            source = ""
            if pdf:
                try:
                    source = read_pdf_text(pdf.read())
                except Exception as e:
                    st.error(f"Could not read PDF: {e}")
            if pasted.strip():
                source += "\n" + pasted

            if len(source.strip()) < 40:
                st.warning("Add a PDF or paste more text to quiz from.")
            elif not api_key:
                st.warning("Enter an API key to generate questions.")
            else:
                with st.spinner("Writing your quiz..."):
                    try:
                        quiz = generate_quiz(api_key, provider, source, qtype, n)
                        st.session_state["quiz"] = quiz
                        st.session_state["quiz_type"] = qtype
                    except Exception as e:
                        st.error(f"Generation failed: {e}")

        quiz = st.session_state.get("quiz")
        if quiz:
            st.markdown("---")
            st.markdown("### Practice Test")
            mc = st.session_state.get("quiz_type") == "Multiple choice"
            for i, q in enumerate(quiz, 1):
                st.markdown(f"**{i}. {q['question']}**")
                if mc and q["choices"]:
                    st.radio("Choose:", q["choices"], key=f"ans_{i}",
                             index=None, label_visibility="collapsed")
                else:
                    st.text_input("Your answer", key=f"ans_{i}",
                                  label_visibility="collapsed")
                with st.expander("Show answer"):
                    st.success(q["answer"])
                    if q["explanation"]:
                        st.caption(q["explanation"])
                st.markdown("")
            if st.button("Clear test"):
                st.session_state.pop("quiz", None)
                st.rerun()

    # ----------------------------- LIFT ------------------------------
    with lift_tab:
        st.subheader("Compute next session from your notes")
        st.caption("Paste your workout notes exactly how you keep them. "
                   "The parser reads the working-set weights and reps.")

        notes = st.text_area("Your workout notes", value=SAMPLE_NOTES,
                             height=240)

        c1, c2, c3 = st.columns(3)
        upper_inc = c1.number_input("Upper-body add (lbs)", 0.0, 50.0, 5.0)
        lower_inc = c2.number_input("Lower-body add (lbs)", 0.0, 50.0, 10.0)
        default_reps = c3.number_input("Default target reps", 1, 20, 4,
                                       help="Used only if a line has no rep "
                                            "number. Your 4-6 range is read "
                                            "per exercise.")

        exercises = parse_workout(notes, int(default_reps)) if notes.strip() else []

        if not exercises:
            st.info("Paste notes with lines like "
                    "'4 sets of 4 bench press (working sets 175 pounds)'.")
        else:
            names = [e["name"] for e in exercises]
            missed = st.multiselect(
                "Mark any lifts you MISSED last time (these hold weight)",
                names, default=[],
                help="Everything not selected is treated as hit -> progress.")

            recs = build_next_session(exercises, missed,
                                      float(upper_inc), float(lower_inc))

            st.markdown("### Next session targets")
            day = None
            for r in recs:
                if r["day"] != day:
                    day = r["day"]
                    st.markdown(f"**{day}**")
                tag = "🟢" if r["delta"] > 0 else "⚪"
                each = " each" if r["each"] else ""
                change = f"  (+{r['delta']:g})" if r["delta"] > 0 else "  (hold)"
                st.write(f"{tag} **{r['name']}** "
                         f"({r['region']}): {r['next_weight']:g} lbs{each} "
                         f"for 4x{r['reps']}{change}")

            st.markdown("---")
            st.markdown("**Copy back into your notes:**")
            st.code(format_session_text(recs), language="text")


if __name__ == "__main__":
    main()
