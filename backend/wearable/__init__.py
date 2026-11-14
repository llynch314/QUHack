"""AttuneMind wearable integration (PRD §6). Self-contained package; see integrations.py
for the single place that talks to teammates' auth / alerts / documents.

Wire-up in app.py (before db.create_all()):
    from wearable import init_wearable
    init_wearable(app)
"""
import logging
import os

log = logging.getLogger('mindconnect.wearable')


def init_wearable(app):
    from . import models  # noqa: F401  (registers the wearable_* tables before db.create_all)
    from .routes import bp
    from .security import get_fernet

    get_fernet()   # refuses to start without WEARABLE_DATA_KEY (unless DEMO_MODE=1, which uses a dev key)
    if os.getenv('WEARABLE_SECURE_COOKIES') == '1':
        # Turn on when you browse through the HTTPS tunnel. Plain http://127.0.0.1 sign-in stops working.
        app.config['SESSION_COOKIE_SECURE'] = True
    app.register_blueprint(bp)

    @app.context_processor
    def _wearable_ctx():
        return {'wearable_demo_mode': os.getenv('DEMO_MODE') == '1',
                'wearable_dev_login': os.getenv('DEV_LOGIN') == '1'}


__all__ = ['init_wearable']
