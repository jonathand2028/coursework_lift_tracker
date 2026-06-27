# Personal Proposal: Coursework & Lift Tracker

A single-user app that makes study quizzes from my class materials and tells me what to lift at the gym next.

**Owner:** Jonathan Dong
**Last updated:** June 22, 2026

---

## Executive Summary

Two chores cost more effort than they are worth. Quizzing yourself is the best way to remember class material, but making the quizzes by hand is tedious, so it gets skipped. Getting stronger means lifting a little more each session, which requires logging every set and doing the math at the gym. This tool automates both for one user (me). It turns a syllabus and textbook into weekly quizzes, and a workout history into the exact plan for my next session. The scope is small on purpose, so it can ship in a weekend, and the core AI logic gets tested by hand before any code is written.

---

## 1. The Problem

**Studying.** Everything needed to make good practice questions is already in the syllabus and textbook, but turning it into quizzes by hand is slow, so the self-testing that actually helps me remember rarely happens.

**Lifting.** Getting stronger only works if I remember last session's numbers and deliberately push a bit past them. Most fitness apps ask for constant input and still do not just tell me what to do next.

In both cases the tracking takes more effort than the activity. This tool removes that effort.

---

## 2. The Three Features

### Feature 1: Quizzes from my class materials

Read a course syllabus and textbook PDFs, line up the topics with a weekly schedule, and send short quizzes and review questions for the current week. First version: one class, a fixed weekly quiz, no fancy difficulty adjusting.

### Feature 2: Workout progress tracker

For a fixed, consistent routine, store the weight and reps for each exercise and tell me my next session's plan: target weight, sets and reps, and when to take an easier recovery week. First version: a set routine, history read from a spreadsheet file, a clear rule (add a little weight each time, take a recovery week after stalling), and the next targets printed for each exercise. No smartwatch yet.

### Feature 3: How I will build it

A lean setup aimed at a working version in a weekend:

- **Python** for reading files and doing the logic, with standard PDF and spreadsheet tools for input.
- **An open-source AI text tool** to read the materials and write the quiz questions. The AI part is kept separate from the main app logic so I can swap it out easily later.
- **Interface (pick one):** Streamlit for a simple web page, or text messages through Twilio so quizzes and "today's lift" arrive on my phone.
- **Storage:** plain files on my computer. Since I am the only user, no database or login is needed.

---

## 3. Test It Before Building

The riskiest assumption is that the AI can actually do this well with my real materials. I will test that by hand in Claude before writing any code.

1. Get a real syllabus page and a small spreadsheet of my recent workouts.
2. **Quiz test:** give Claude the syllabus and a textbook section, ask for a five-question quiz on this week's topic, and check whether the questions are accurate and worth studying.
3. **Workout test:** give Claude the workout file and the progression rule, ask for the exact weights and reps for my next session, and check the math.
4. Run both in one chat to make sure it can handle the combination.

**How I will know it passed:** if the quizzes are worth studying and the workout targets are correct, the hard part is done and building the app is mostly connecting the pieces. If not, I fix the prompts or inputs before spending a weekend coding.

---

## Running this MVP

```bash
pip install -r requirements.txt
streamlit run app.py
```

Then open the local URL Streamlit prints (usually http://localhost:8501).

### Study tab
Pick a provider (OpenAI or Anthropic), upload a PDF or paste lecture notes,
choose multiple-choice or short-answer and a question count, and the app calls
the model to generate a practice test with a flashcard-style reveal for each
answer.

The API key is read from the app's settings (Streamlit Secrets), so as the
owner you set it once and end users never type a key. To set it: in the
Streamlit Cloud dashboard open your app -> Settings -> Secrets and add
`OPENAI_API_KEY = "sk-..."` (or `ANTHROPIC_API_KEY = "..."`). Running locally,
put the same line in `.streamlit/secrets.toml`. If no key is configured, the
app falls back to a manual key box.

### Lift tab
Paste your workout notes the way you keep them in your Google Doc (the app
ships with your format pre-filled as an example). It reads your weights and
reps into an editable table, then recommends the next session using **double
progression**, the standard method: add reps inside a target range first, then
add load once you hit the top of the range.

Defaults are set by lift type and follow standard strength guidance (NSCA):
heavy compounds 4-6 reps, isolation 8-12, small delt/lateral work 12-15. Load
jumps default to +10 lb lower compounds, +5 lb upper compounds and isolation,
+2.5 lb small isolation. Everything is editable per row. Enter the reps you
actually hit last time; uncheck "Hit all sets" for anything you missed and it
holds the weight. Nothing auto-progresses. The result includes a copy-paste
block for your notes.

Rep-range guidance: NSCA resistance-training standards via
https://www.ptpioneer.com/personal-training/certifications/nsca-cpt/nsca-cpt-chapter-15/
and the double-progression method
https://legionathletics.com/double-progression/

## Deploy to a dev website (Streamlit Community Cloud)

1. Push this repo to GitHub.
2. Go to https://share.streamlit.io and sign in with GitHub.
3. Click "New app", pick this repo, branch `main`, main file `app.py`.
4. Click "Deploy". The app builds from `requirements.txt` and gets a public
   `*.streamlit.app` URL you can share.
5. Open Settings -> Secrets and add your model key, e.g.
   `OPENAI_API_KEY = "sk-..."`, so the Study tab works without anyone typing
   a key.

## Tests & CI

```bash
pip install pytest
pytest -q
```

Unit tests live in `test_app.py` and cover the core logic. GitHub Actions
(`.github/workflows/ci.yml`) runs them automatically on every push and pull
request, so the repo shows a green check when everything passes.

## Database (workout history)

The Lift tab saves your sessions so history survives between visits. After you
enter a session, click "Save this session to history". Next time, choose "My
saved history" to reload your last weights and reps instead of re-pasting notes.

By default this uses **SQLite**, Python's built-in database, written to a local
file (`tracker.db`). No setup and no extra packages. This is durable on your own
machine.

Note on hosting: Streamlit Community Cloud has an ephemeral filesystem, so the
SQLite file resets when the app restarts. For the LIVE app to remember data
permanently, connect a hosted Postgres database (Supabase has a free tier):

1. Create a free project at https://supabase.com and open Project Settings ->
   Database -> Connection string (URI).
2. In the Streamlit app, Settings -> Secrets, add `DATABASE_URL = "postgresql://..."`.
3. Point `get_connection()` at that URL with a Postgres driver
   (`psycopg2-binary`). The table schema is standard SQL and does not change.

Until then, SQLite works out of the box for local use and demos.
