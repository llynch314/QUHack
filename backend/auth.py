"""Sign in with Google (OpenID Connect via Authlib), plus an optional demo login.

Setup: create an OAuth client ID ("Web application") in Google Cloud Console, add
http://127.0.0.1:5000/auth/google/callback as an authorized redirect URI, and put
GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in backend/.env.
"""
import os
from functools import wraps

from authlib.integrations.flask_client import OAuth
from flask import Blueprint, abort, flash, g, jsonify, redirect, request, session, url_for

from models import User, db

bp = Blueprint('auth', __name__)
oauth = OAuth()


def google_configured():
    return bool(os.getenv('GOOGLE_CLIENT_ID') and os.getenv('GOOGLE_CLIENT_SECRET'))


def dev_login_enabled():
    """Demo login for the hackathon when Google sign-in isn't set up. Never enable in production."""
    return os.getenv('DEV_LOGIN') == '1'


def init_auth(app):
    oauth.init_app(app)
    if google_configured():
        oauth.register(
            name='google',
            client_id=os.getenv('GOOGLE_CLIENT_ID'),
            client_secret=os.getenv('GOOGLE_CLIENT_SECRET'),
            server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
            client_kwargs={'scope': 'openid email profile'},
        )

    @app.before_request
    def load_user():
        user_id = session.get('user_id')
        g.user = db.session.get(User, user_id) if user_id else None

    @app.context_processor
    def auth_context():
        return {'current_user': g.get('user'), 'google_configured': google_configured(),
                'dev_login_enabled': dev_login_enabled()}


def login_required(view):
    """Pages redirect to sign-in; /api/ routes get a 401 JSON error."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.get('user') is None:
            if request.path.startswith('/api/'):
                return jsonify(error='Please sign in first.'), 401
            return redirect(url_for('auth.login', next=request.path))
        return view(*args, **kwargs)
    return wrapped


def _safe_next(url):
    return url if url and url.startswith('/') and not url.startswith('//') else url_for('index')


def _sign_in(user):
    session.clear()
    session['user_id'] = user.id
    session.permanent = True


@bp.route('/login')
def login():
    session['next'] = _safe_next(request.args.get('next'))
    if google_configured():
        return oauth.google.authorize_redirect(url_for('auth.google_callback', _external=True))
    if dev_login_enabled():
        return redirect(url_for('auth.dev_login'))
    flash('Google sign-in is not set up yet. Add GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET to backend/.env.')
    return redirect(url_for('index'))


@bp.route('/auth/google/callback')
def google_callback():
    if not google_configured():
        abort(404)
    next_url = session.get('next')
    token = oauth.google.authorize_access_token()   # also verifies the ID token
    info = token.get('userinfo') or {}
    if not info.get('sub'):
        flash('Google sign-in failed. Please try again.')
        return redirect(url_for('index'))
    user = User.query.filter_by(google_sub=info['sub']).first()
    if user is None:
        user = User(google_sub=info['sub'])
        db.session.add(user)
    user.email = info.get('email')
    user.name = info.get('name') or info.get('given_name')
    db.session.commit()
    _sign_in(user)
    return redirect(_safe_next(next_url))


@bp.route('/login/dev')
def dev_login():
    if not dev_login_enabled():
        abort(404)
    next_url = session.get('next')
    user = User.query.filter_by(google_sub='dev-demo-user').first()
    if user is None:
        user = User(google_sub='dev-demo-user', name='Demo User', email='demo@example.com')
        db.session.add(user)
        db.session.commit()
    _sign_in(user)
    return redirect(_safe_next(next_url))


@bp.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return redirect(url_for('index'))
