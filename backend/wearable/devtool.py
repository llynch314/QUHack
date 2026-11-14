"""Developer helper for the wearable branch (cross-platform). Run from backend/:

  python -m wearable.devtool env          Create/complete backend/.env for local demo testing (never overwrites values you set)
  python -m wearable.devtool status       Show the wearable configuration that the app will use
  python -m wearable.devtool send --url http://127.0.0.1:5000 --token TOKEN [--hr 72]
                                          Send one reading exactly like the iPhone Shortcut does (flat format)
  python -m wearable.devtool reset-db     Delete backend/instance/mindconnect.db (fresh start; asks first)
"""
import argparse
import os
import secrets
import shutil
import sys
from datetime import datetime, timezone

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV = os.path.join(BACKEND, '.env')
EXAMPLE = os.path.join(BACKEND, '.env.example')

DEMO_DEFAULTS = {
    'DEMO_MODE': '1',
    'DEV_LOGIN': '1',
    'AI_DATA_TIER': 'free',
    'WEARABLE_REQUIRE_HTTPS': 'allow_localhost',
}


def _read(path):
    with open(path, encoding='utf-8') as f:
        return f.read().splitlines()


def _value(lines, key):
    for line in lines:
        if line.strip().startswith(key + '='):
            return line.split('=', 1)[1].strip()
    return None


def _set(lines, key, value):
    for i, line in enumerate(lines):
        if line.strip().startswith(key + '='):
            lines[i] = f'{key}={value}'
            return
    lines.append(f'{key}={value}')


def cmd_env(args):
    if not os.path.exists(ENV):
        shutil.copy(EXAMPLE, ENV)
        print('Created backend/.env from .env.example')
    lines = _read(ENV)
    changed = []
    if not _value(lines, 'FLASK_SECRET_KEY'):
        _set(lines, 'FLASK_SECRET_KEY', secrets.token_hex(32))
        changed.append('FLASK_SECRET_KEY (random)')
    if not _value(lines, 'WEARABLE_DATA_KEY'):
        from cryptography.fernet import Fernet
        _set(lines, 'WEARABLE_DATA_KEY', Fernet.generate_key().decode())
        changed.append('WEARABLE_DATA_KEY (new Fernet key - keep it, or old wearable data becomes unreadable)')
    if not args.no_demo:
        for k, v in DEMO_DEFAULTS.items():
            cur = _value(lines, k)
            if cur in (None, '', '0') and cur != v:
                _set(lines, k, v)
                changed.append(f'{k}={v}')
    with open(ENV, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    print('Updated: ' + (', '.join(changed) if changed else 'nothing, .env already complete'))
    print('backend/.env is git-ignored. Never commit it.')


def cmd_status(_args):
    from dotenv import dotenv_values
    v = {**dotenv_values(ENV), **{k: os.environ[k] for k in os.environ if k.startswith(('WEARABLE', 'DEMO', 'DEV_', 'AI_', 'NTFY', 'PUBLIC'))}}
    show = lambda k, d='': v.get(k) or d  # noqa: E731
    print(f"backend/.env exists:      {os.path.exists(ENV)}")
    print(f"DEMO_MODE:                {show('DEMO_MODE', '0')}   (1 = Demo Control Panel)")
    print(f"DEV_LOGIN:                {show('DEV_LOGIN', '0')}   (1 = one-click patient/family/provider logins)")
    print(f"WEARABLE_DATA_KEY set:    {bool(show('WEARABLE_DATA_KEY'))}")
    print(f"AI_DATA_TIER:             {show('AI_DATA_TIER', 'free')}")
    print(f"WEARABLE_REQUIRE_HTTPS:   {show('WEARABLE_REQUIRE_HTTPS', 'allow_localhost')}")
    print(f"PUBLIC_BASE_URL:          {show('PUBLIC_BASE_URL', '(not set)')}")
    print(f"NTFY_TOPIC (watch buzz):  {'set' if show('NTFY_TOPIC') else '(not set)'}")
    print(f"GEMINI_API_KEY set:       {bool(show('GEMINI_API_KEY')) and show('GEMINI_API_KEY') != 'your_key_here'}  (not needed for the wearable demo)")
    print(f"cloudflared on PATH:      {shutil.which('cloudflared') is not None}")


def cmd_send(args):
    import requests
    body = {'sent_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), 'heart_rate': args.hr}
    if args.hrv is not None:
        body['hrv_sdnn'] = args.hrv
    if args.steps is not None:
        body['steps'] = args.steps
    r = requests.post(args.url.rstrip('/') + '/api/wearable/ingest', json=body,
                      headers={'X-Device-Token': args.token}, timeout=15)
    print(f'HTTP {r.status_code}')
    print(r.text[:600])
    return 0 if r.ok else 1


def cmd_reset_db(args):
    path = os.path.join(BACKEND, 'instance', 'mindconnect.db')
    if not os.path.exists(path):
        print('No database file to delete.')
        return 0
    if not args.yes and input(f'Delete {path}? All local users, check-ins and wearable data go. [y/N] ').lower() != 'y':
        print('Cancelled.')
        return 1
    os.remove(path)
    print('Deleted. It is recreated the next time the app starts.')
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description='Wearable dev helper')
    sub = p.add_subparsers(dest='cmd', required=True)
    e = sub.add_parser('env')
    e.add_argument('--no-demo', action='store_true', help="don't turn on DEMO_MODE / DEV_LOGIN")
    sub.add_parser('status')
    s = sub.add_parser('send')
    s.add_argument('--url', required=True)
    s.add_argument('--token', required=True)
    s.add_argument('--hr', type=float, default=72)
    s.add_argument('--hrv', type=float)
    s.add_argument('--steps', type=float)
    r = sub.add_parser('reset-db')
    r.add_argument('--yes', action='store_true')
    a = p.parse_args(argv)
    return {'env': cmd_env, 'status': cmd_status, 'send': cmd_send, 'reset-db': cmd_reset_db}[a.cmd](a) or 0


if __name__ == '__main__':
    sys.exit(main())
