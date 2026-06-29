"""
Coursework & Lift Tracker - Streamlit MVP (iteration 2)
=======================================================

STUDY (Tab 1):  paste lecture notes or upload a PDF and generate a real
                multiple-choice / short-answer practice test with an LLM
                (OpenAI or Anthropic). The API key is read from the app's
                settings (st.secrets) so you, the owner, set it ONCE and end
                users never type a key. A manual key box appears only if no
                key is configured.

LIFT  (Tab 2):  paste your workout notes the way you keep them. The app reads
                your weights and reps and recommends the next session using
                DOUBLE PROGRESSION (the standard method): add reps inside a
                target range first, then add load once you hit the top of the
                range. Rep ranges and load jumps default by lift type
                (heavy compounds 4-6, isolation 8-12, small delt work 12-15)
                and are fully editable. Nothing auto-progresses if you mark a
                lift as missed.

Rep-range and double-progression defaults follow standard strength guidance
(NSCA): strength compounds <=6 reps, hypertrophy 6-12, isolation/finishers
12+; increase reps within range, then load. See README for sources.

Run it:
    pip install -r requirements.txt
    streamlit run app.py
"""

import io
import os
import re
import json
import sqlite3
from datetime import datetime, timezone

# ======================================================================
#  STUDY: prompt + LLM calls + parsing  (pure/testable)
# ======================================================================

def build_quiz_prompt(source_text, qtype, n):
    if qtype == "Topic study guide":
        shape = ('a JSON array of objects, each: {"question": "the topic name", '
                 '"choices": [], "answer": "a clear 2-4 sentence explanation of '
                 'that topic", "explanation": ""}')
        instruction = (
            f"identify the {n} most important topics and explain each one "
            f"clearly, expanding on the ideas but staying strictly faithful to "
            f"the material (do not invent facts not supported by it)")
    elif qtype == "Multiple choice":
        shape = ('a JSON array of objects, each: {"question": str, '
                 '"choices": [4 strings], "answer": "the exact correct choice", '
                 '"explanation": str}')
        instruction = (f"write {n} multiple choice questions that test "
                       f"understanding of the key concepts")
    else:
        shape = ('a JSON array of objects, each: {"question": str, '
                 '"choices": [], "answer": str, "explanation": str}')
        instruction = (f"write {n} short answer questions that test "
                       f"understanding of the key concepts")
    return (
        f"You are a study assistant. Using ONLY the material below, {instruction}. "
        f"Return {shape}. Return JSON only, no prose.\n\n"
        f"MATERIAL:\n{source_text[:8000]}"
    )


def parse_quiz_json(content):
    if not content:
        return []
    match = re.search(r"\[.*\]", content, re.DOTALL)
    data = json.loads(match.group(0) if match else content)
    out = []
    for q in data:
        out.append({
            "question": str(q.get("question", "")).strip(),
            "choices": [str(c) for c in (q.get("choices") or [])],
            "answer": str(q.get("answer", "")).strip(),
            "explanation": str(q.get("explanation", "")).strip(),
        })
    return out


def call_openai(api_key, prompt, model="gpt-4o-mini"):
    import requests
    r = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={"model": model, "messages": [{"role": "user", "content": prompt}],
              "temperature": 0.4},
        timeout=90)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def call_anthropic(api_key, prompt, model="claude-3-5-sonnet-20241022"):
    import requests
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": api_key, "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
        json={"model": model, "max_tokens": 2000,
              "messages": [{"role": "user", "content": prompt}]},
        timeout=90)
    r.raise_for_status()
    return r.json()["content"][0]["text"]


def generate_quiz(api_key, provider, source_text, qtype, n):
    prompt = build_quiz_prompt(source_text, qtype, n)
    content = (call_anthropic(api_key, prompt) if provider == "Anthropic"
               else call_openai(api_key, prompt))
    return parse_quiz_json(content)


def read_pdf_text(file_bytes):
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(file_bytes))
    return "\n".join((p.extract_text() or "") for p in reader.pages)


# ======================================================================
#  LIFT: parsing + double progression  (pure/testable)
# ======================================================================

SMALL_ISO_KW = ["lateral raise", "rear delt", "fly", "flies", "reverse fly"]
ISO_KW = ["curl", "extension", "pushdown", "raise", "row", "fly", "incline"]
LOWER_KW = ["squat", "deadlift", "lunge", "rdl", "romanian", "leg press", "hip thrust"]

# defaults per category: (rep_low, rep_high, load_increment, rep_step)
# grounded in standard guidance: heavy compounds 4-6, isolation 8-12,
# small delt/lateral work 12-15; add reps first, then load (double progression)
CATEGORY_DEFAULTS = {
    "compound_lower": (4, 6, 10.0, 1),
    "compound_upper": (4, 6, 5.0, 1),
    "isolation":      (8, 12, 5.0, 2),
    "small_iso":      (12, 15, 2.5, 2),
}

FILLER = ["to parallel", "full range", "slow down fast lift up", "slow down",
          "fast lift up", "per side", "until slowing or", "reps", "rep"]
DAY_HINTS = ["training", "day", "session"]


def categorize(name, day=""):
    n, d = name.lower(), day.lower()
    if any(k in n for k in SMALL_ISO_KW):
        return "small_iso"
    if any(k in n for k in LOWER_KW):
        return "compound_lower"
    if ("accessory" in d or "aesthetic" in d or "dumbbell" in n
            or any(k in n for k in ISO_KW)):
        return "isolation"
    return "compound_upper"


def _clean_name(raw):
    name = re.sub(r"\([^)]*\)", " ", raw)
    name = re.sub(r"^\s*\d+[.)]\s*", " ", name)
    name = re.sub(r"\d+\s*sets?\s*of\s*\d*", " ", name, flags=re.I)
    name = re.sub(r"working sets?.*$", " ", name, flags=re.I)
    name = re.sub(r"\b\d+\s*(?:pounds|lbs)\b", " ", name, flags=re.I)
    for f in FILLER:
        name = re.sub(re.escape(f), " ", name, flags=re.I)
    name = re.sub(r"[~\-]", " ", name)
    name = re.sub(r"^\s*\d+\s+", " ", name)
    name = re.sub(r"\s+", " ", name).strip(" .,")
    return name.title() if name else "Exercise"


def _parse_reps(line, default_reps):
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
    m = re.search(r"working sets?\s*~?\s*(\d+(?:\.\d+)?)", line, flags=re.I)
    if m:
        return float(m.group(1))
    m = re.search(r"~?\s*(\d+(?:\.\d+)?)\s*(?:pounds|lbs)", line, flags=re.I)
    if m:
        return float(m.group(1))
    return None


def parse_workout(text, default_reps=5):
    """Parse notes into editable rows seeded with sensible per-lift defaults."""
    rows = []
    day = "Workout"
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if not re.search(r"sets?\s*of", s, flags=re.I):
            if any(h in s.lower() for h in DAY_HINTS) and len(s) < 60:
                day = re.sub(r"[:\-]+$", "", s).strip()
            continue
        weight = _parse_weight(s)
        if weight is None:
            continue
        name = _clean_name(s)
        cat = categorize(name, day)
        low, high, inc, step = CATEGORY_DEFAULTS[cat]
        rows.append({
            "Day": day,
            "Exercise": name,
            "Type": cat,
            "Weight": weight,
            "Rep low": low,
            "Rep high": high,
            "Reps last": _parse_reps(s, default_reps),
            "Hit all sets": True,
            "Add (lbs)": inc,
            "_rep_step": step,
        })
    return rows


def double_progression(weight, low, high, reps_last, hit, increment, rep_step):
    """Standard double progression. Returns (next_weight, next_reps, action, note)."""
    if not hit:
        return weight, max(low, reps_last), "hold", "Missed last time. Repeat the same weight."
    if reps_last >= high:
        return round(weight + increment, 2), low, "add load", (
            f"Hit the top ({high}). Add {increment:g} lb and reset to {low} reps.")
    if reps_last < low:
        return weight, low, "build", f"Below range. Aim for {low} reps at this weight."
    nxt = min(reps_last + rep_step, high)
    if nxt == reps_last:
        return weight, nxt, "hold", "Already at the top. Push for a rep or add load."
    return weight, nxt, "add reps", f"Add {nxt - reps_last} rep(s): aim for {nxt}."


def recommend(rows):
    out = []
    for r in rows:
        nw, nr, action, note = double_progression(
            float(r["Weight"]), int(r["Rep low"]), int(r["Rep high"]),
            int(r["Reps last"]), bool(r["Hit all sets"]),
            float(r["Add (lbs)"]), int(r.get("_rep_step", 1)))
        out.append({**r, "next_weight": nw, "next_reps": nr,
                    "action": action, "note": note})
    return out


def format_session_text(recs):
    lines, day = [], None
    for r in recs:
        if r["Day"] != day:
            day = r["Day"]
            lines.append(f"\n{day}")
        lines.append(f"- {r['Exercise']}: {r['next_weight']:g} lb x "
                     f"{r['next_reps']} reps  ({r['action']})")
    return "\n".join(lines).strip()


SAMPLE_NOTES = """Strength Training
1. 4 sets of 4 to parallel back squats (working sets 325 pounds)
2. 4 sets of 4 full range bench press (working sets 175 pounds)
3. 4 sets of 4 full range deadlifts (working sets 335 pounds)
4. 4 sets of 4 full range wide grip pull ups (working sets 90 pounds)

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
#  DATABASE: workout history persistence  (stdlib sqlite3, testable)
# ======================================================================
#
# This uses Python's built-in SQLite, so it works with zero extra packages
# and persists to a local file. To upgrade to a hosted database later
# (e.g. Supabase Postgres so the LIVE app remembers data across restarts),
# only get_connection() changes; the SQL below is standard. See README.

COLS = ["Day", "Exercise", "Type", "Weight", "Rep low", "Rep high",
        "Reps last", "Hit all sets", "Add (lbs)", "_rep_step"]


def get_connection(db_path="tracker.db"):
    """Return a SQLite connection. Pass ':memory:' in tests."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            day TEXT, exercise TEXT, type TEXT,
            weight REAL, rep_low INTEGER, rep_high INTEGER,
            reps_last INTEGER, increment REAL, rep_step INTEGER
        )""")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS body_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            bodyweight REAL, bodyfat REAL, note TEXT
        )""")
    conn.commit()


def save_session(conn, rows, ts=None):
    """Persist one workout session (a list of exercise row dicts)."""
    ts = ts or datetime.now(timezone.utc).isoformat()
    for r in rows:
        conn.execute(
            "INSERT INTO sessions (ts, day, exercise, type, weight, rep_low, "
            "rep_high, reps_last, increment, rep_step) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (ts, r.get("Day"), r.get("Exercise"), r.get("Type"),
             float(r.get("Weight", 0)), int(r.get("Rep low", 0)),
             int(r.get("Rep high", 0)), int(r.get("Reps last", 0)),
             float(r.get("Add (lbs)", 0)), int(r.get("_rep_step", 1))))
    conn.commit()
    return ts


def load_latest_rows(conn):
    """Reconstruct editor rows from each exercise's most recent saved entry."""
    cur = conn.execute("SELECT * FROM sessions ORDER BY ts DESC, id DESC")
    seen, rows = set(), []
    for r in cur.fetchall():
        key = (r["day"], r["exercise"])  # same lift can appear on different days
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "Day": r["day"], "Exercise": r["exercise"], "Type": r["type"],
            "Weight": r["weight"], "Rep low": r["rep_low"],
            "Rep high": r["rep_high"], "Reps last": r["reps_last"],
            "Hit all sets": True, "Add (lbs)": r["increment"],
            "_rep_step": r["rep_step"],
        })
    return rows


def session_dates(conn, limit=10):
    """Distinct saved session timestamps, newest first."""
    cur = conn.execute(
        "SELECT ts, COUNT(*) n FROM sessions GROUP BY ts ORDER BY ts DESC LIMIT ?",
        (limit,))
    return [(r["ts"], r["n"]) for r in cur.fetchall()]


def exercise_progress(conn, day, exercise):
    """Return [(ts, weight)] over time for one lift, oldest first."""
    cur = conn.execute(
        "SELECT ts, weight FROM sessions WHERE day=? AND exercise=? ORDER BY ts ASC",
        (day, exercise))
    return [(r["ts"], r["weight"]) for r in cur.fetchall()]


def save_body_metric(conn, bodyweight, bodyfat, note="", ts=None):
    ts = ts or datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO body_metrics (ts, bodyweight, bodyfat, note) VALUES (?,?,?,?)",
        (ts, bodyweight, bodyfat, note))
    conn.commit()
    return ts


def load_body_metrics(conn, limit=60):
    cur = conn.execute(
        "SELECT ts, bodyweight, bodyfat, note FROM body_metrics "
        "ORDER BY ts ASC LIMIT ?", (limit,))
    return [dict(r) for r in cur.fetchall()]


def summarize_recs(recs):
    """Plain-language feedback on a session's recommendations."""
    counts = {}
    for r in recs:
        counts[r["action"]] = counts.get(r["action"], 0) + 1
    parts = []
    if counts.get("add load"):
        parts.append(f"{counts['add load']} lift(s) moving up in weight")
    if counts.get("add reps"):
        parts.append(f"{counts['add reps']} adding reps")
    if counts.get("hold"):
        parts.append(f"{counts['hold']} holding")
    if counts.get("build"):
        parts.append(f"{counts['build']} building into range")
    return "This session: " + ", ".join(parts) + "." if parts else ""


# ======================================================================
#  THEME: custom CSS for a polished, branded look
# ======================================================================

THEME_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap');
html, body, [class*="css"], .stMarkdown, button, input, textarea { font-family: 'Inter', sans-serif !important; }
.block-container { padding-top: 1.5rem; max-width: 900px; }
.app-hero {
  background: linear-gradient(135deg, #E8590C 0%, #F08C00 100%);
  color: #fff; padding: 22px 28px; border-radius: 16px; margin-bottom: 20px;
  box-shadow: 0 6px 18px rgba(232,89,12,0.25);
}
.app-hero h1 { color:#fff !important; margin:0; font-weight:800; font-size:1.7rem; }
.app-hero p { color:#fff2e8; margin:6px 0 0; font-size:0.95rem; }
.stButton>button { border-radius:10px; font-weight:600; border:none; }
.stButton>button[kind="primary"] { background:#E8590C; }
.stTabs [data-baseweb="tab"] { font-weight:600; }
div[data-testid="stMetric"] { background:#FFF4EC; padding:14px 16px; border-radius:12px; border:1px solid #ffe0cc; }
div[data-testid="stExpander"] { border-radius:12px; }
</style>
"""

HERO_HTML = """
<div class="app-hero">
  <h1>🏋️ Coursework &amp; Lift Tracker</h1>
  <p>AI quizzes from your notes, and your next workout by double progression.</p>
</div>
"""


# ======================================================================
#  Streamlit UI
# ======================================================================

def _resolve_key(provider, ui_key):
    """Prefer a key set in app settings (st.secrets); fall back to UI input."""
    import streamlit as st
    if ui_key:
        return ui_key
    name = "ANTHROPIC_API_KEY" if provider == "Anthropic" else "OPENAI_API_KEY"
    try:
        return st.secrets.get(name, "")
    except Exception:
        return ""


def main():
    import streamlit as st
    import pandas as pd

    st.set_page_config(page_title="Coursework & Lift Tracker", page_icon="🏋️",
                       layout="centered")
    st.markdown(THEME_CSS, unsafe_allow_html=True)
    st.markdown(HERO_HTML, unsafe_allow_html=True)

    # database connection (local SQLite file, or Postgres if configured: see README)
    conn = get_connection(os.environ.get("TRACKER_DB", "tracker.db"))
    init_db(conn)

    study_tab, lift_tab = st.tabs(["📚 Study", "🏋️ Lift"])

    # ----------------------------- STUDY -----------------------------
    with study_tab:
        st.subheader("Make a practice test or study guide from your notes")
        provider = st.selectbox("Model provider", ["OpenAI", "Anthropic"])

        configured = _resolve_key(provider, "")
        if configured:
            st.caption("✓ Using the API key set in this app's settings. "
                       "No key needed.")
            ui_key = ""
        else:
            st.info("This needs an OpenAI or Anthropic API key. Paste one "
                    "below, or set it once in the app's Secrets so you never "
                    "type it again (see README).")
            ui_key = st.text_input(
                "API key", type="password",
                help="Set OPENAI_API_KEY or ANTHROPIC_API_KEY in the app's "
                     "Secrets to skip this box.")

        pdf = st.file_uploader("Lecture notes / textbook PDF", type=["pdf"])
        pasted = st.text_area("...or paste your notes here", height=150)

        qtype = st.radio(
            "Mode", ["Multiple choice", "Short answer", "Topic study guide"],
            horizontal=True)
        # instant feedback the moment a mode is selected
        hints = {
            "Multiple choice": "Questions with four options and a revealed answer.",
            "Short answer": "Open questions you answer, then reveal the model answer.",
            "Topic study guide": "Key topics from your notes, explained and expanded "
                                 "(still grounded in your notes).",
        }
        st.caption(hints[qtype])
        label = "How many topics" if qtype == "Topic study guide" else "How many questions"
        n = st.slider(label, 3, 15, 6)
        btn_label = ("Generate study guide" if qtype == "Topic study guide"
                     else "Generate practice test")

        if st.button(btn_label, type="primary"):
            key = _resolve_key(provider, ui_key)
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
            elif not key:
                st.warning("No API key available. Add one in app settings or above.")
            else:
                with st.spinner("Generating from your notes..."):
                    try:
                        st.session_state["quiz"] = generate_quiz(
                            key, provider, source, qtype, int(n))
                        st.session_state["quiz_type"] = qtype
                    except Exception as e:
                        st.error(f"Generation failed: {e}")

        quiz = st.session_state.get("quiz")
        if quiz:
            qmode = st.session_state.get("quiz_type")
            st.markdown("---")
            if qmode == "Topic study guide":
                st.markdown("### Study Guide")
                for i, q in enumerate(quiz, 1):
                    st.markdown(f"**{i}. {q['question']}**")
                    st.write(q["answer"])
                    st.markdown("")
            else:
                st.markdown("### Practice Test")
                mc = qmode == "Multiple choice"
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
            if st.button("Clear"):
                st.session_state.pop("quiz", None)
                st.rerun()

    # ----------------------------- LIFT ------------------------------
    with lift_tab:
        st.subheader("Next session by double progression")
        st.caption("Paste your notes, set how many reps you actually hit last "
                   "time, and the app tells you whether to add reps or add "
                   "load. Add reps inside the range first, then weight at the top.")

        with st.expander("How the progression works"):
            st.markdown(
                "- **Double progression:** keep the weight and add reps until "
                "you reach the top of the range, then add load and drop back "
                "to the bottom of the range.\n"
                "- **Defaults by lift type** (editable per row): heavy "
                "compounds 4-6 reps, isolation 8-12, small delt/lateral work "
                "12-15. Load jumps: +10 lb lower compounds, +5 lb upper "
                "compounds and isolation, +2.5 lb small isolation.\n"
                "- **Uncheck 'Hit all sets'** for anything you missed and it "
                "holds the weight. Nothing auto-progresses.")

        saved = load_latest_rows(conn)
        if saved:
            source = st.radio(
                "Start from", ["My saved history", "Paste notes"],
                horizontal=True,
                help="Your last saved session is loaded from the database.")
        else:
            source = "Paste notes"
            st.caption("No saved sessions yet. Paste your notes, then click "
                       "Save session to start your history.")

        if source == "My saved history":
            rows = saved
            with st.expander(f"Loaded {len(saved)} lifts from your last session"):
                hist = session_dates(conn)
                st.write("Recent saved sessions:")
                for ts, n in hist:
                    st.caption(f"- {ts[:16].replace('T', ' ')}  ({n} lifts)")
        else:
            notes = st.text_area("Your workout notes", value=SAMPLE_NOTES,
                                 height=200)
            rows = parse_workout(notes) if notes.strip() else []

        if not rows:
            st.info("Paste lines like '4 sets of 4 bench press (working sets 175 pounds)'.")
        else:
            st.caption("Edit 'Reps last' to what you actually hit, and uncheck "
                       "'Hit all sets' if you missed. Weights and rep ranges "
                       "are editable too.")
            df = pd.DataFrame(rows)
            display_cols = ["Day", "Exercise", "Type", "Weight", "Rep low",
                            "Rep high", "Reps last", "Hit all sets", "Add (lbs)"]
            edited = st.data_editor(
                df[display_cols], use_container_width=True, hide_index=True,
                disabled=["Day", "Exercise", "Type"], key="lift_editor")

            # carry the hidden rep-step back in by exercise name
            step_by_name = {r["Exercise"]: r["_rep_step"] for r in rows}
            merged = edited.to_dict("records")
            for m in merged:
                m["_rep_step"] = step_by_name.get(m["Exercise"], 1)

            if st.button("💾 Save this session to history", type="primary"):
                ts = save_session(conn, merged)
                st.success(f"Saved {len(merged)} lifts. Next visit, pick "
                           "'My saved history' to pick up where you left off.")

            recs = recommend(merged)
            st.markdown("### Next session")
            day = None
            icon = {"add load": "🔼", "add reps": "🟢", "build": "🔧", "hold": "⚪"}
            for r in recs:
                if r["Day"] != day:
                    day = r["Day"]
                    st.markdown(f"**{day}**")
                st.write(f"{icon.get(r['action'], '•')} **{r['Exercise']}**: "
                         f"{r['next_weight']:g} lb x {r['next_reps']} reps")
                st.caption(r["note"])

            st.markdown("---")
            st.markdown("**Copy back into your notes:**")
            next_text = format_session_text(recs)
            st.code(next_text, language="text")
            st.download_button("Download next session (.txt)", next_text,
                               file_name="next_session.txt")

            fb = summarize_recs(recs)
            if fb:
                st.info(fb)

        st.markdown("---")
        with st.expander("📈 Progress over time"):
            saved_now = load_latest_rows(conn)
            if not saved_now:
                st.caption("Save a few sessions to see your weight trends here.")
            else:
                opts = [f"{r['Day']} | {r['Exercise']}" for r in saved_now]
                pick = st.selectbox("Lift", opts)
                d, ex = pick.split(" | ", 1)
                series = exercise_progress(conn, d, ex)
                if len(series) < 2:
                    st.caption("Only one session saved for this lift so far.")
                else:
                    dfp = pd.DataFrame(series, columns=["session", "weight"])
                    dfp["session"] = dfp["session"].str[:10]
                    st.line_chart(dfp.set_index("session"))

        with st.expander("⚖️ Body metrics (bodyweight, body fat %)"):
            st.caption("Everyone progresses differently. Log these over time to "
                       "track your own trend.")
            bc1, bc2 = st.columns(2)
            bw = bc1.number_input("Bodyweight (lbs)", 0.0, 600.0, 0.0, step=0.5)
            bf = bc2.number_input("Body fat %", 0.0, 60.0, 0.0, step=0.1)
            if st.button("Save body metrics"):
                if bw > 0 or bf > 0:
                    save_body_metric(conn, bw or None, bf or None)
                    st.success("Saved.")
                else:
                    st.warning("Enter a bodyweight or body fat % first.")
            metrics = load_body_metrics(conn)
            if len(metrics) >= 2:
                dfm = pd.DataFrame(metrics)
                dfm["ts"] = dfm["ts"].str[:10]
                st.line_chart(dfm.set_index("ts")[["bodyweight", "bodyfat"]])
            elif metrics:
                st.caption("Log another entry to see a trend.")


if __name__ == "__main__":
    main()
