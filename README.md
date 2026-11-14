# AttuneMIND
AI-powered mental well-being companion (healthcare hackathon project).

## Features

- **Chat** with a CBT/DBT-informed companion (Claude Opus 5.5) that builds self-reliance, reads humor and tone, and always surfaces crisis resources (988, 741741, 911) when someone may be at risk.
- **Talk out loud** in real time with Gemini 3.1 Flash Live. (Voice stays on Gemini because Claude has no real-time audio API; it needs its own `GEMINI_API_KEY`.)
- **Calm Toolkit**: guided breathing, 5-4-3-2-1 grounding, a CBT thought record, DBT skill cards and soft background noise, with stress ratings before and after.
- **My Progress**: see which skills lower your stress, and choose to print or share a report with a therapist, doctor or parent.
- **Accessibility** (the **Aa** menu): text size, dyslexia-friendly and low-vision fonts, high contrast, dark mode, reduced motion and read-aloud.
- **Three kinds of account**: patients, health providers and family members, each with their own sign-in and their own view (see below).
- **Sign in with Google**; check-ins are stored in SQLite (or any SQL database via `DATABASE_URL`). Chats are never stored.

## Project layout

| Path | What it is |
|---|---|
| `backend/app.py` | Flask app: pages and JSON API |
| `backend/claude_client.py` | Claude client and model settings |
| `backend/claude_chat.py` | Text chat (Claude) |
| `backend/claude_emotion.py` | Webcam expression check (Claude) |
| `backend/prompts.py` | System prompt and crisis detection, shared by chat and voice |
| `backend/gemini_client.py` | Gemini client for voice mode only |
| `backend/voice.py` | Websocket relay between the browser and Gemini Live |
| `backend/auth.py` | Sign in with Google, the three sign-in doors, and the access rules (`ACCESS`) |
| `backend/care.py` | Care team, health documents and alerts (pages + API) |
| `backend/safety.py` | Spots panic attack / meltdown / crisis language for family alerts |
| `backend/tests/` | Tests for who can see what (`pytest`) |
| `backend/models.py` | Database tables |
| `frontend/templates/`, `frontend/static/` | Pages, CSS and JavaScript |

## Quick start (with make)

From the repo root:

```bash
make setup    # create the venv, install dependencies, create backend/.env
# paste your Claude key into backend/.env as ANTHROPIC_API_KEY (get one at https://platform.claude.com/settings/keys)
# optional: GEMINI_API_KEY too, for voice mode (https://aistudio.google.com/apikey)
make run      # Flask web app at http://127.0.0.1:5000
make chat     # terminal chatbot
make webcam   # webcam emotion demo (press q to quit)
make watch    # live view of saved expression readings from the database (run in a second terminal)
```

For the website you don't need Google sign-in to start: set `DEV_LOGIN=1` in `backend/.env` to get demo accounts (one patient, one provider, one family member).

Run `make` on its own to list all commands. On Windows, install make with `winget install ezwinports.make` if you don't have it.

## Setup (manual)

Requires Python 3.11 or newer (the Gemini library used for voice needs it). On a Mac, install Python 3.12 from python.org and use `python3.12 -m venv .venv`. Run these from the `backend/` folder.

```bash
# 1. Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # macOS / Linux

# 2. Install dependencies
pip install -r requirements.txt
pip install -r requirements-voice.txt   # optional, only for speechtotext.py / tts.py

# 3. Add your Claude API key (and optionally a Gemini key for voice)
copy .env.example .env        # Windows   (macOS/Linux: cp .env.example .env)
# then edit .env and paste your key
```

## Running

| Command | What it does |
|---|---|
| `python chat_bot.py` | Chat with the Claude bot in the terminal |
| `python emotional_recognition.py` | Webcam emotion detection demo (press `q` to quit) |
| `python app.py` | Flask web server at http://127.0.0.1:5000 |

Emotion detection sends the image to Claude, so it uses the same `ANTHROPIC_API_KEY` as the chatbot and needs an internet connection. The webcam demo asks Claude about once every 1.5 seconds to keep costs and rate limits down.

## Sign in with Google

1. In [Google Cloud Console](https://console.cloud.google.com/apis/credentials), configure the OAuth consent screen, then **Create credentials > OAuth client ID > Web application**.
2. Add the authorized redirect URI `http://127.0.0.1:5000/auth/google/callback`.
3. Put the client ID and secret in `backend/.env` as `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`, and set `FLASK_SECRET_KEY` to a long random string.
4. Open the app at `http://127.0.0.1:5000` (not `localhost`), so the redirect URI matches.

## Privacy and safety notes

- This is a prototype and is **not HIPAA-compliant**. A production version would need a business associate agreement (BAA) with every vendor that touches health data, including the AI provider, plus encryption, access controls and audit logs.
- Text chat and webcam snapshots go to Anthropic's Claude API; voice audio (and camera frames during voice) go to Google's Gemini API. On Gemini's free tier, Google may use prompts to improve its products. Don't demo with real patient data.
- New accounts must agree on a consent screen before using the app. Saving expression readings is a separate opt-in checkbox that starts unchecked.
- Chats, voice and camera images are never stored. Signed-in users' check-in ratings are stored, and expression words (e.g. "happy") only if they opted in. Readings are saved in the `expression_reading` table, appended to `backend/instance/expression_log.csv` and printed in the `make run` terminal. Users can delete them at any time.
- Reports are only shared when the user chooses to print or save them.

## Accounts and access

The sign-in page (`/signin`) has three doors. A Google account gets its type the first time it signs in and keeps it; using a different door later shows a message instead.

| | Chat, toolkit, progress | Health documents | Urgent alerts | Care team |
|---|---|---|---|---|
| **Patient** | ✅ own | ✅ own (add, delete) | ✅ own (alert buttons) | ✅ adds / removes people |
| **Health provider** | ❌ | ✅ for patients who added them (read, add notes, delete own) | ❌ | sees their patients |
| **Family member** | toolkit only | ❌ | ✅ for patients who added them (mark as seen) | sees who added them |

- Providers and family see nothing until the patient adds them by email on the **Care Team** page, and lose access the moment they're removed. They need to sign in once first so their account exists.
- **Health documents**: notes the patient or provider write, plus progress reports the patient chooses to add (a snapshot of their check-ins).
- **Alerts**: the patient's alert buttons ("I'm having a panic attack" etc.), or automatically when a signed-in patient's chat shows signs of a panic attack, meltdown or crisis. Family see only the type of alert, never the chat text. Patients can turn automatic alerts off. The same kind of chat alert isn't repeated within 10 minutes. Voice mode doesn't create alerts yet.
- The family page checks for new alerts every 20 seconds. There are no push notifications or texts yet.
- All rules live in `ACCESS` in `backend/auth.py`; every route that touches a patient's data calls `require_access()`.

| Page | Who |
|---|---|
| `/care-team` | Patient: alert buttons, care team, documents, alert history |
| `/provider` and `/provider/patients/<id>` | Provider: their patients and each patient's documents |
| `/family` | Family: alerts, with an "I'm checking in" button |

**API** (JSON, uses the signed-in session cookie; errors look like `{"error": "..."}`)

| Method | Path | Who |
|---|---|---|
| GET / POST | `/api/care-team` | GET: anyone signed in. POST `{email}`: patient |
| DELETE | `/api/care-team/<link_id>` | patient |
| PATCH | `/api/me/settings` `{auto_alerts}` | patient |
| GET / POST | `/api/patients/<id>/documents` `{title, body, category?}` | patient, linked provider |
| POST | `/api/documents/progress-report` | patient |
| GET / DELETE | `/api/documents/<id>` | patient; provider (delete own only) |
| GET | `/api/alerts?unacknowledged=1` | patient, family |
| POST | `/api/alerts/sos` `{kind: panic_attack \| meltdown \| crisis \| other, note?}` | patient |
| POST | `/api/alerts/<id>/acknowledge` | patient, linked family |
| POST | `/api/chat` | returns `alert_sent: true` when family were alerted |
