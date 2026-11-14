"""AttuneMind wearable integration (PRD §6). Self-contained package; see integrations.py
for the single place that talks to the team's roles / care team / alerts / documents.

Wire-up in app.py (after the blueprints, before db.create_all()):
    from wearable import init_wearable
    init_wearable(app)
"""
import logging
import os
import time

log = logging.getLogger('mindconnect.wearable')

PROMOTE_EVERY_S = 2


def init_wearable(app):
    from flask import request
    from sqlalchemy import event

    from models import User

    from . import models  # noqa: F401  (registers the wearable_* tables before db.create_all)
    from .demo import bp as demo_bp
    from .escalation import promote_due_alerts
    from .routes import bp
    from .security import get_fernet

    get_fernet()   # refuses to start without WEARABLE_DATA_KEY (unless DEMO_MODE=1, which uses a dev key)
    if os.getenv('WEARABLE_SECURE_COOKIES') == '1':
        # Turn on when you browse through the HTTPS tunnel. Plain http://127.0.0.1 sign-in stops working.
        app.config['SESSION_COOKIE_SECURE'] = True
    app.register_blueprint(bp)
    app.register_blueprint(demo_bp)   # /demo console: DEMO_MODE + DEV_LOGIN, local requests only

    last = {'t': 0.0}

    @app.before_request
    def _send_due_fall_alerts():
        """Fall countdowns end on time even if the patient closed the page: any request
        (e.g. the family Alerts page polling) sends alerts whose 60 s are up."""
        if request.endpoint == 'static' or time.monotonic() - last['t'] < PROMOTE_EVERY_S:
            return
        last['t'] = time.monotonic()
        try:
            promote_due_alerts()
        except Exception:   # never break the rest of the app over this
            log.exception('wearable: sending due alerts failed')

    @app.after_request
    def _link_demo_accounts(resp):
        """The team's own demo sign-in (/login/dev) creates the demo accounts; link them up so the
        demo family member and provider see Demo Patient no matter which way they signed in."""
        if os.getenv('DEV_LOGIN') == '1' and request.endpoint in ('auth.dev_login', 'auth.consent'):
            try:
                from .integrations import link_demo_team
                link_demo_team()
            except Exception:
                log.exception('wearable: linking demo accounts failed')
        return resp

    @event.listens_for(User, 'before_delete')
    def _delete_wearable_data(mapper, connection, user):
        """Deleting an account (main's delete_user_everywhere) also deletes its wearable data."""
        for table in models.db.metadata.sorted_tables:
            if table.name.startswith('wearable_') and table.name != 'wearable_audit_log' \
                    and 'patient_id' in table.c:
                connection.execute(table.delete().where(table.c.patient_id == user.id))

    @app.context_processor
    def _wearable_ctx():
        return {'wearable_enabled': True, 'wearable_demo_mode': os.getenv('DEMO_MODE') == '1',
                'wearable_dev_login': os.getenv('DEV_LOGIN') == '1'}


__all__ = ['init_wearable']
