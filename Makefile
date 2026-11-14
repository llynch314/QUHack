# Run `make` (or `make help`) from the repo root to see the commands.
# Works on Windows, macOS and Linux. Uses backend/.venv directly, so there is
# no need to activate the virtual environment first.

ifeq ($(OS),Windows_NT)
  # Always use cmd.exe so commands behave the same whether make is started
  # from PowerShell, cmd or Git Bash.
  SHELL       := cmd.exe
  SYS_PY      := python
  VENV_PY     := .venv\Scripts\python.exe
  VENV_MARKER := backend/.venv/Scripts/python.exe
else
  SYS_PY      := python3
  VENV_PY     := .venv/bin/python
  VENV_MARKER := backend/.venv/bin/python
endif

# Fails with a clear message if backend/.env has no real Claude (Anthropic) key.
CHECK_KEY := $(VENV_PY) -c "import sys; from dotenv import dotenv_values; k = (dotenv_values('.env').get('ANTHROPIC_API_KEY') or '').strip(); sys.exit(0 if k and k != 'your_key_here' else 'ANTHROPIC_API_KEY is not set. Run make env, then paste your key into backend/.env')"

.DEFAULT_GOAL := help
.PHONY: help setup install install-voice env check-key run chat webcam expressions watch

help:
	@echo Commands:
	@echo   make setup          Create the venv, install dependencies and create backend/.env
	@echo   make run            Start the web app, then open the dashboard at http://127.0.0.1:5000/dashboard
	@echo   make chat           Chat with the Claude bot in the terminal
	@echo   make webcam         Webcam emotion detection demo, press q to quit
	@echo   make expressions    Show the latest saved expression readings from the database
	@echo   make watch          Live view of expression readings as they are saved (for demos)
	@echo   make install-voice  Install the optional voice dependencies

setup: install env

$(VENV_MARKER):
	cd backend && $(SYS_PY) -m venv .venv

install: $(VENV_MARKER)
	cd backend && $(VENV_PY) -m pip install -r requirements.txt

install-voice: $(VENV_MARKER)
	cd backend && $(VENV_PY) -m pip install -r requirements-voice.txt

# Copies .env.example to .env, but never overwrites an existing .env.
env: $(VENV_MARKER)
	cd backend && $(VENV_PY) -c "import os, shutil; print('backend/.env already exists, leaving it alone') if os.path.exists('.env') else (shutil.copy('.env.example', '.env'), print('Created backend/.env - paste your ANTHROPIC_API_KEY into it'))"

check-key:
	@cd backend && $(CHECK_KEY)

run: check-key
	cd backend && $(VENV_PY) app.py

chat: check-key
	cd backend && $(VENV_PY) chat_bot.py

webcam: check-key
	cd backend && $(VENV_PY) emotional_recognition.py

expressions: $(VENV_MARKER)
	cd backend && $(VENV_PY) show_expressions.py

watch: $(VENV_MARKER)
	cd backend && $(VENV_PY) show_expressions.py --follow
