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
Pick a provider (OpenAI or Anthropic), paste your API key, then upload a PDF
or paste lecture notes. Choose multiple-choice or short-answer and a question
count, and the app calls the model to generate a practice test with a
flashcard-style reveal for each answer. The key is entered in the UI and is
not stored.

### Lift tab
Paste your workout notes the way you keep them in your Google Doc (the app
ships with your format pre-filled as an example). It reads the working-set
weights and reps, applies linear progressive overload (hit target -> add
weight; miss -> hold), and prints next-session targets you can copy straight
back into your notes. Defaults: +5 lbs upper body, +10 lbs lower body, all
adjustable in the UI. Mark any lifts you missed and those hold their weight.

## Deploy to a dev website (Streamlit Community Cloud)

1. Push this repo to GitHub.
2. Go to https://share.streamlit.io and sign in with GitHub.
3. Click "New app", pick this repo, branch `main`, main file `app.py`.
4. Click "Deploy". The app builds from `requirements.txt` and gets a public
   `*.streamlit.app` URL you can share. (Enter your model API key in the app
   UI at runtime; no secrets configuration required.)
