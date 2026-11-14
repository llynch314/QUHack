# AttuneMind
Ai powered mental health assistant app

## Setup

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
# then edit .env: paste your Gemini key and set a SECRET_KEY
```

## Running

| Command | What it does |
|---|---|
| `python chat_bot.py` | Chat with the Gemini bot in the terminal |
| `python emotional_recognition.py` | Webcam emotion detection demo (press `q` to quit) |
| `python app.py` | Web server + API at http://127.0.0.1:5000 (also serves `frontend/`) |
| `pytest` | Runs the backend tests, including who-can-see-what checks |

The first run of the emotion detection downloads DeepFace model weights (a few hundred MB).

## Accounts and access

There are three kinds of login. Each sees a different part of a patient's data:

| | Chat with bot | Health documents | Urgent alerts | Care team |
|---|---|---|---|---|
| **Patient** (the user) | ✅ own | ✅ own (add, delete) | ✅ own (SOS button) | ✅ adds/removes members |
| **Health provider** | ❌ | ✅ for linked patients (add, delete own) | ❌ | sees linked patients |
| **Family member** | ❌ | ❌ | ✅ for linked patients (acknowledge) | sees linked patients |

Providers and family see nothing until the patient adds them to their care team by email, and lose access as soon as the patient removes them.

**Alerts** are created when the patient taps SOS, or automatically when the chatbot sees signs of a panic attack, meltdown or crisis. Family see only the type of alert and a generic note, never the chat text. Patients can turn automatic alerts off (`PATCH /api/auth/me {"auto_alerts": false}`). Crisis messages also get 988 / Crisis Text Line info added to the bot's reply. The detection is simple keyword matching (`backend/safety.py`), not a clinical tool.

The access rules live in one place: `ACCESS` in `backend/auth.py`.

## API reference (for the frontend)

All endpoints take and return JSON. Errors look like `{"error": "message"}`.
After login, send the token on every request: `Authorization: Bearer <token>`.

```js
const res = await fetch("/api/auth/login", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ email, password, role: "patient" }),  // role = which login page
});
const { token, user } = await res.json();
localStorage.setItem("token", token);

// later
fetch("/api/alerts", { headers: { Authorization: `Bearer ${localStorage.getItem("token")}` } });
```

**Auth**
| Method | Path | Who | Body / notes |
|---|---|---|---|
| POST | `/api/auth/register` | anyone | `{email, name, password (8+ chars), role: "patient"\|"provider"\|"family"}` → `{token, user}` |
| POST | `/api/auth/login` | anyone | `{email, password, role?}` → `{token, user}`. Pass `role` from the login page you're on; a mismatch returns 403 |
| GET | `/api/auth/me` | any | → `{user}` |
| PATCH | `/api/auth/me` | any | `{name?, auto_alerts? (patients)}` |

**Care team**
| Method | Path | Who | Body / notes |
|---|---|---|---|
| GET | `/api/care-team` | any | Patient: their members. Provider/family: patients they're linked to. → `{links: [{id, patient, member}]}` |
| POST | `/api/care-team` | patient | `{email}` of an existing provider/family account |
| DELETE | `/api/care-team/<link_id>` | patient | removes access |

**Health documents**
| Method | Path | Who | Body / notes |
|---|---|---|---|
| GET | `/api/patients/<id>/documents` | patient, linked provider | → `{documents: [...]}` newest first |
| POST | `/api/patients/<id>/documents` | patient, linked provider | `{title, body?, category?}` |
| GET | `/api/documents/<doc_id>` | patient, linked provider | |
| DELETE | `/api/documents/<doc_id>` | patient (any), provider (own) | |

**Alerts**
| Method | Path | Who | Body / notes |
|---|---|---|---|
| GET | `/api/alerts?unacknowledged=1` | patient, family | Family: alerts across all linked patients. Poll this for notifications |
| GET | `/api/patients/<id>/alerts` | patient, linked family | |
| POST | `/api/alerts/sos` | patient | `{kind: "panic_attack"\|"meltdown"\|"crisis"\|"other", note?}` |
| POST | `/api/alerts/<id>/acknowledge` | patient, linked family | marks "I've seen this" |

**Chat and emotion** (patient only)
| Method | Path | Body / notes |
|---|---|---|
| POST | `/api/chat` | `{message, emotion?}` → `{reply, urgent, alert_sent}`. The bot remembers the last 20 messages |
| GET | `/api/chat` | → `{messages: [...]}` history |
| DELETE | `/api/chat` | clears history |
| POST | `/api/detect_emotion` | `{image_data: "data:image/png;base64,..."}` → `{emotion}` (pass it to `/api/chat`) |
