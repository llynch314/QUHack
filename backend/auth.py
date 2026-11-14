"""Sign in with Google (OpenID Connect via Authlib), plus an optional demo login.

There are three sign-in doors, one per role: /login?role=patient|provider|family.
A Google account gets its role the first time it signs in and keeps it; using the
wrong door later shows a message instead of signing in. Access rules for each role
are in ACCESS below; every route that touches a patient's data calls require_access().

Setup: create an OAuth client ID ("Web application") in Google Cloud Console, add
http://127.0.0.1:5000/auth/google/callback as an authorized redirect URI, and put
GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in backend/.env.
"""
import os
from datetime import datetime, timezone
from functools import wraps

from authlib.integrations.flask_client import OAuth
from flask import (Blueprint, abort, flash, g, jsonify, redirect, render_template, request,
                   session, url_for)
from werkzeug.exceptions import HTTPException

from models import ROLE_LABELS, ROLES, CareLink, User, db

# What each role may see. Patients see only their own data; providers and family
# see a patient only after that patient adds them to their care team.
ACCESS = {
    'patient': {'documents', 'alerts', 'checkins', 'care_team'},
    'provider': {'documents'},
    'family': {'alerts'},
}

# Where each role lands after signing in.
HOME = {'patient': 'index', 'provider': 'care.provider_home', 'family': 'care.family_home'}

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
        # A new account must agree on the consent screen before using anything else.
        if g.user and g.user.terms_accepted_at is None and request.endpoint not in CONSENT_EXEMPT:
            if request.path.startswith('/api/') or request.path.startswith('/ws/'):
                return jsonify(error='Please finish signing up first.'), 403
            return redirect(url_for('auth.consent'))

    @app.context_processor
    def auth_context():
        return {'current_user': g.get('user'), 'google_configured': google_configured(),
                'dev_login_enabled': dev_login_enabled(), 'role_labels': ROLE_LABELS}

    @app.errorhandler(HTTPException)
    def api_errors_as_json(e):
        """API routes return {"error": ...} instead of an HTML error page."""
        if request.path.startswith('/api/'):
            return jsonify(error=e.description), e.code
        return e


def home_url(user):
    return url_for(HOME.get(user.role, 'index'))


# Pages a signed-in user can reach before agreeing on the consent screen.
CONSENT_EXEMPT = {'auth.consent', 'auth.logout', 'static', 'privacy'}


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


def roles_required(*roles):
    """Signed in AND one of these roles. Others get a 403 (API) or a message (pages)."""
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if g.user.role not in roles:
                if request.path.startswith('/api/'):
                    return jsonify(error='Your account type does not have access to this.'), 403
                flash(f"That page isn't available for {ROLE_LABELS[g.user.role].lower()} accounts.")
                return redirect(home_url(g.user))
            return view(*args, **kwargs)
        return wrapped
    return decorator


def is_linked(patient_id, member_id):
    return db.session.query(CareLink.id).filter_by(
        patient_id=patient_id, member_id=member_id).first() is not None


def can_access(user, patient_id, resource):
    if user is None or resource not in ACCESS.get(user.role, set()):
        return False
    if user.role == 'patient':
        return user.id == patient_id
    return is_linked(patient_id, user.id)


def require_access(patient_id, resource):
    if not can_access(g.get('user'), patient_id, resource):
        abort(403, "You don't have access to this.")


def _safe_next(url):
    return url if url and url.startswith('/') and not url.startswith('//') else url_for('index')


def _sign_in(user, next_url):
    session.clear()
    session['user_id'] = user.id
    session.permanent = True
    if user.terms_accepted_at is None:
        session['next'] = _safe_next(next_url)
        return redirect(url_for('auth.consent'))
    return redirect(_safe_next(next_url))


def _finish_sign_in(user, wanted_role, next_url):
    """Sign in if the account's role matches the door used; otherwise explain which door to use."""
    if user.role != wanted_role:
        flash(f'This Google account is registered as a {ROLE_LABELS[user.role].lower()}. '
              f'Please use the {ROLE_LABELS[user.role].lower()} sign-in.')
        return redirect(url_for('auth.signin'))
    # _sign_in sends new accounts to the consent screen first, then on to this page.
    return _sign_in(user, next_url if next_url and next_url != url_for('index') else home_url(user))


@bp.route('/signin')
def signin():
    """Page with the three sign-in options."""
    if g.get('user'):
        return redirect(home_url(g.user))
    return render_template('signin.html', next=_safe_next(request.args.get('next')))


@bp.route('/login')
def login():
    role = request.args.get('role')
    if role not in ROLES:
        return redirect(url_for('auth.signin', next=request.args.get('next')))
    session['next'] = _safe_next(request.args.get('next'))
    session['login_role'] = role
    if google_configured():
        return oauth.google.authorize_redirect(url_for('auth.google_callback', _external=True))
    if dev_login_enabled():
        return redirect(url_for('auth.dev_login'))
    flash('Google sign-in is not set up yet. Add GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET to backend/.env, '
          'or set DEV_LOGIN=1 to use demo accounts.')
    return redirect(url_for('auth.signin'))


@bp.route('/auth/google/callback')
def google_callback():
    if not google_configured():
        abort(404)
    next_url = session.get('next')
    role = session.get('login_role', 'patient')
    token = oauth.google.authorize_access_token()   # also verifies the ID token
    info = token.get('userinfo') or {}
    if not info.get('sub'):
        flash('Google sign-in failed. Please try again.')
        return redirect(url_for('index'))
    user = User.query.filter_by(google_sub=info['sub']).first()
    if user is None:
        user = User(google_sub=info['sub'], role=role)   # first sign-in picks the role
        db.session.add(user)
    user.email = info.get('email')
    user.name = info.get('name') or info.get('given_name')
    db.session.commit()
    return _finish_sign_in(user, role, _safe_next(next_url))


@bp.route('/login/dev')
def dev_login():
    if not dev_login_enabled():
        abort(404)
    next_url = session.get('next')
    role = session.get('login_role', 'patient')
    # One demo account per role, so all three views can be shown without Google.
    sub = f'dev-demo-{role}'
    user = User.query.filter_by(google_sub=sub).first()
    if user is None:
        user = User(google_sub=sub, role=role, name=f'Demo {ROLE_LABELS[role]}',
                    email=f'demo-{role}@example.com')
        db.session.add(user)
        db.session.commit()
    return _finish_sign_in(user, role, _safe_next(next_url))


@bp.route('/welcome', methods=['GET', 'POST'])
def consent():
    """Consent screen shown when an account is created. Agreeing is required; saving
    expression readings is a separate opt-in that starts unchecked."""
    if g.user is None:
        return redirect(url_for('auth.login'))
    error = None
    if request.method == 'POST':
        if request.form.get('agree') != 'yes':
            error = 'Please tick the box to agree before continuing.'
        else:
            now = datetime.now(timezone.utc)
            g.user.terms_accepted_at = now
            g.user.save_expressions = request.form.get('save_expressions') == 'yes'
            g.user.expressions_consent_at = now
            db.session.commit()
            next_url = _safe_next(session.pop('next', None))
            if g.user.needs_profile:   # providers say where they work before seeing patients
                return redirect(url_for('auth.account', next=next_url))
            return redirect(next_url)
    return render_template('consent.html', error=error), (400 if error else 200)


PROFILE_FIELDS = {'organization': 200, 'specialty': 120, 'license_number': 60}   # field: max length


@bp.route('/account', methods=['GET', 'POST'])
@login_required
def account():
    """Account details for every role: provider profile (providers only) and account deletion."""
    error = None
    next_url = request.args.get('next')
    if request.method == 'POST':
        if g.user.role != 'provider':
            abort(403)
        values = {f: (request.form.get(f) or '').strip()[:n] or None for f, n in PROFILE_FIELDS.items()}
        if not values['organization']:
            error = 'Please add the hospital, clinic or practice you work at.'
        else:
            for field, value in values.items():
                setattr(g.user, field, value)
            db.session.commit()
            flash('Your provider profile is saved.')
            return redirect(_safe_next(next_url) if next_url else url_for('auth.account'))
    return render_template('account.html', error=error, next=next_url), (400 if error else 200)


@bp.route('/settings/expressions', methods=['POST'])
@login_required
def set_expression_saving():
    """Turn saving expression readings on or off later (from My Progress)."""
    g.user.save_expressions = request.form.get('save_expressions') == 'yes'
    g.user.expressions_consent_at = datetime.now(timezone.utc)
    db.session.commit()
    flash('Expression saving is now ' + ('on.' if g.user.save_expressions else 'off.'))
    return redirect(url_for('report'))


@bp.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return redirect(url_for('index'))
