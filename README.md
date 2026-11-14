# mind-connect2.0
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
# then edit .env and paste your key
```

## Running

| Command | What it does |
|---|---|
| `python chat_bot.py` | Chat with the Gemini bot in the terminal |
| `python emotional_recognition.py` | Webcam emotion detection demo (press `q` to quit) |
| `python app.py` | Flask web server at http://127.0.0.1:5000 |

The first run of the emotion detection downloads DeepFace model weights (a few hundred MB).
