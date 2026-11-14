# Mind Connect
AI-powered mental well-being companion (healthcare hackathon project).

## Features

- **Chat** with a CBT/DBT-informed companion (Gemini 3.8 Flash) that builds self-reliance, reads humor and tone, and always surfaces crisis resources (988, 741741, 911) when someone may be at risk.
- **Talk out loud** in real time with Gemini 3.8 Live, or Live Extended Thinking for deeper replies.
- **Calm Toolkit**: guided breathing, 5-4-3-2-1 grounding, a CBT thought record, DBT skill cards and soft background noise, with stress ratings before and after.
- **My Progress**: see which skills lower your stress, and choose to print or share a report with a therapist, doctor or parent.
- **Accessibility** (the **Aa** menu): text size, dyslexia-friendly and low-vision fonts, high contrast, dark mode, reduced motion and read-aloud.
- **Sign in with Google**; check-ins are stored in SQLite (or any SQL database via `DATABASE_URL`). Chats are never stored.

## Project layout

| Path | What it is |
|---|---|
| `backend/app.py` | Flask app: pages and JSON API |
| `backend/gemini_client.py` | Gemini client, model names, system prompt, crisis detection |
| `backend/gemini_backend.py` | Text chat |
| `backend/gemini_emotion.py` | Webcam expression check |
| `backend/voice.py` | Websocket relay between the browser and Gemini Live |
| `backend/auth.py` | Sign in with Google |
| `backend/models.py` | Database tables |
| `frontend/templates/`, `frontend/static/` | Pages, CSS and JavaScript |

## Quick start (with make)

From the repo root:

```bash
make setup    # create the venv, install dependencies, create backend/.env
# paste your Gemini key into backend/.env (get one at https://aistudio.google.com/apikey)
make run      # Flask web app at http://127.0.0.1:5000
make chat     # terminal chatbot
make webcam   # webcam emotion demo (press q to quit)
make watch    # live view of saved expression readings from the database (run in a second terminal)
```

For the website you don't need Google sign-in to start: set `DEV_LOGIN=1` in `backend/.env` to get a demo account.

Run `make` on its own to list all commands. On Windows, install make with `winget install ezwinports.make` if you don't have it.

## Setup (manual)

Requires Python 3.10–3.12. Run these from the `backend/` folder.

```bash
# 1. Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # macOS / Linux

# 2. Install dependencies
pip install -r requirements.txt
pip install -r requirements-voice.txt   # optional, only for speechtotext.py / tts.py

# 3. Add your Gemini API key
copy .env.example .env        # Windows   (macOS/Linux: cp .env.example .env)
# then edit .env and paste your key
```

## Running

| Command | What it does |
|---|---|
| `python chat_bot.py` | Chat with the Gemini bot in the terminal |
| `python emotional_recognition.py` | Webcam emotion detection demo (press `q` to quit) |
| `python app.py` | Flask web server at http://127.0.0.1:5000 |

Emotion detection sends the image to Gemini, so it uses the same `GEMINI_API_KEY` as the chatbot and needs an internet connection. The webcam demo asks Gemini about once every 1.5 seconds to stay within the free-tier rate limits.

## Sign in with Google

1. In [Google Cloud Console](https://console.cloud.google.com/apis/credentials), configure the OAuth consent screen, then **Create credentials > OAuth client ID > Web application**.
2. Add the authorized redirect URI `http://127.0.0.1:5000/auth/google/callback`.
3. Put the client ID and secret in `backend/.env` as `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`, and set `FLASK_SECRET_KEY` to a long random string.
4. Open the app at `http://127.0.0.1:5000` (not `localhost`), so the redirect URI matches.

## Privacy and safety notes

- This is a prototype and is **not HIPAA-compliant**. A production version would need a business associate agreement (BAA) with every vendor that touches health data, including the AI provider, plus encryption, access controls and audit logs.
- On Gemini's free tier, Google may use prompts to improve its products. Don't demo with real patient data.
- New accounts must agree on a consent screen before using the app. Saving expression readings is a separate opt-in checkbox that starts unchecked.
- Chats, voice and camera images are never stored. Signed-in users' check-in ratings are stored, and expression words (e.g. "happy") only if they opted in. Readings are saved in the `expression_reading` table, appended to `backend/instance/expression_log.csv` and printed in the `make run` terminal. Users can delete them at any time.
- Reports are only shared when the user chooses to print or save them.
