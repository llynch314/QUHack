"""Mind Connect backend: a JSON API with three kinds of login (patient, provider, family).

Run:  python app.py   ->  http://127.0.0.1:5000
API docs are in the README.
"""
import os
import secrets
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS
from werkzeug.exceptions import HTTPException

from models import db
from routes import alerts, auth_routes, care_team, chat, documents

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR.parent / "frontend"


def create_app(config=None):
    app = Flask(__name__, instance_path=str(BASE_DIR / "instance"))
    os.makedirs(app.instance_path, exist_ok=True)

    secret = (config or {}).get("SECRET_KEY") or os.getenv("SECRET_KEY")
    if not secret:
        print("WARNING: SECRET_KEY not set in .env; using a random one (everyone is "
              "logged out when the server restarts).")
        secret = secrets.token_hex(32)

    app.config.update(
        SECRET_KEY=secret,
        SQLALCHEMY_DATABASE_URI=os.getenv(
            "DATABASE_URL", f"sqlite:///{Path(app.instance_path) / 'mindconnect.db'}"),
        TOKEN_MAX_AGE=60 * 60 * 24 * 7,  # logins last 7 days
        MAX_CONTENT_LENGTH=10 * 1024 * 1024,  # 10 MB (webcam frames)
    )
    if config:
        app.config.update(config)

    db.init_app(app)
    # Lets the frontend call the API from another port (e.g. VS Code Live Server).
    CORS(app, resources={r"/api/*": {"origins": os.getenv("CORS_ORIGINS", "*")}})

    for module in (auth_routes, care_team, documents, alerts, chat):
        app.register_blueprint(module.bp)

    @app.errorhandler(HTTPException)
    def json_errors(e):
        return jsonify(error=e.description), e.code

    # Serve the frontend folder so the site and API share one address.
    @app.get("/")
    @app.get("/<path:filename>")
    def frontend(filename="index.html"):
        if not (FRONTEND_DIR / filename).is_file() and filename == "index.html":
            filename = "test.html"
        return send_from_directory(FRONTEND_DIR, filename)

    with app.app_context():
        db.create_all()
    return app


if __name__ == "__main__":
    create_app().run(debug=os.getenv("FLASK_DEBUG") == "1")
