"""Live terminal watch feed for the demo (no Apple Watch needed). Run from backend/ while the app is running:

  python -m wearable.live [--url http://127.0.0.1:5050] [--every 5] [--mode calm]

It signs in as the DEV_LOGIN demo patient, accepts the wearable consent, creates its own device token and then
POSTs a reading to /api/wearable/ingest every few seconds - the exact same endpoint and auth the iPhone Shortcut uses.
Type commands while it runs (type `help`). Samples are tagged source "demo_feed", so the UI says where they came from.
"""
import argparse
import json
import os
import random
import sys
import threading
import time
from datetime import datetime, timezone

from . import simulator

MODES = {   # command -> simulator scenario used for the history backfill and the live values
    'calm': 'baseline',
    'stress': 'stress_spike',
    'distress': 'sustained_distress',
    'exercise': 'exercise',
    'recovery': 'recovery',
    'cardiac': 'cardiac_warning',
    'fall': 'fall',
}
SOURCE = 'demo_feed'
LABEL = 'Terminal demo feed'

HELP = """
Commands (type and press Enter):
  calm | stress | distress | exercise | recovery | cardiac | fall
                    switch scenario: clears the demo data, backfills ~16 min of history so the state
                    changes immediately, then keeps streaming live readings in that mode
  hr 110            pin the live heart rate (hr off = back to the mode's values)
  hrv 20            pin the live HRV (hrv off)
  {"heart_rate": 95, "hrv_sdnn": 22}
                    send any JSON body as-is (one line). sent_at is filled in for you.
                    Flat format keys: heart_rate hrv_sdnn resting_hr steps active_energy workout_active events
  file path.json    send a JSON file
  pause | resume    stop / restart the automatic readings
  once              send one reading now
  reset             delete the demo patient's wearable data (keeps consent + device)
  status            show the current mode and last result
  quit              exit (Ctrl+C works too)
"""

C = {'calm': '32', 'elevated': '33', 'exercising': '36', 'recovering': '36', 'stressed': '33;1',
     'distressed': '31;1', 'emergency': '41;97;1'}


def _paint(text, code):
    return f'\x1b[{code}m{text}\x1b[0m' if code else text


def _now_iso():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


class Feed:
    def __init__(self, url, every, mode):
        import requests
        self.url = url.rstrip('/')
        self.every = every
        self.mode = mode
        self.http = requests.Session()
        self.token = None
        self.paused = False
        self.pin = {}
        self.last_state = None
        self.last_line = ''
        self.lock = threading.Lock()
        self.rng = random.Random()
        self.stop = threading.Event()

    # ---------- setup over HTTP (same as clicking through the UI) ----------

    def connect(self):
        try:
            r = self.http.get(self.url + '/wearable/dev-login/patient', timeout=10)
        except Exception as e:  # noqa: BLE001
            sys.exit(f'Cannot reach {self.url} ({e.__class__.__name__}). Start the app first:  .\\scripts\\wearable.ps1 run')
        if r.status_code == 404:
            sys.exit('DEV_LOGIN is off. Start the app with  .\\scripts\\wearable.ps1 run  (it sets DEV_LOGIN=1, DEMO_MODE=1).')
        self.http.post(self.url + '/api/wearable/consent', json={'accept': True}, timeout=10).raise_for_status()
        devices = self.http.get(self.url + '/api/wearable/devices', timeout=10).json().get('devices', [])
        for d in devices:   # one feed device at a time: revoke the ones from earlier runs
            if d.get('label') == LABEL and not d.get('revoked_at'):
                self.http.delete(f"{self.url}/api/wearable/devices/{d['id']}", timeout=10)
        r = self.http.post(self.url + '/api/wearable/devices', json={'label': LABEL, 'source': 'simulator'}, timeout=10)
        r.raise_for_status()
        self.token = r.json()['token']

    def reset(self):
        r = self.http.post(self.url + '/api/wearable/demo/reset', timeout=10)
        if r.status_code == 404:
            print('reset needs DEMO_MODE=1 (wearable.ps1 run sets it).')
            return False
        return r.ok

    # ---------- sending ----------

    def post(self, body):
        body = dict(body)
        body['sent_at'] = _now_iso()
        body.setdefault('source', SOURCE)
        r = self.http.post(self.url + '/api/wearable/ingest', json=body,
                           headers={'X-Device-Token': self.token}, timeout=15)
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, {'error': r.text[:200]}

    def live_values(self):
        n = simulator.HISTORY_MIN
        v = simulator._profile(MODES[self.mode], n - 1, n, self.rng)   # the scenario's "now" values
        scale = self.every / 60   # steps / energy in the profile are per minute; a tick covers `every` seconds
        out = {'heart_rate': round(v['heart_rate']), 'hrv_sdnn': round(v['hrv_sdnn'], 1),
               'steps': round(v['steps'] * scale), 'active_energy': round(v['active_energy'] * scale, 2),
               'workout_active': v['workout_active']}
        if 'hr' in self.pin:
            out['heart_rate'] = self.pin['hr']
        if 'hrv' in self.pin:
            out['hrv_sdnn'] = self.pin['hrv']
        return out

    def tick(self, label=None):
        body = self.live_values()
        status, res = self.post(body)
        self.report(label or self.mode, status, res, f"HR {body['heart_rate']:>3}  HRV {body['hrv_sdnn']:>4}  steps {body['steps']:>2}")

    def backfill(self, mode):
        payload = simulator.generate(MODES[mode], seed=self.rng.randint(1, 10_000))
        payload['source'] = SOURCE
        payload.pop('sent_at', None)
        status, res = self.post(payload)
        self.report(f'{mode} (history)', status, res, f"{len(payload['samples'])} samples"
                    + (f", events: {', '.join(e['type'] for e in payload['events'])}" if payload['events'] else ''))

    def report(self, label, status, res, what):
        t = datetime.now().strftime('%H:%M:%S')
        if status != 200:
            line = f'[{t}] {label:<10} {what}  ->  HTTP {status}: {res.get("error")}'
            print(_paint(line, '31'))
            self.last_line = line
            return
        st = res.get('state') or {}
        state = st.get('state')
        alert = res.get('alert')
        changed = state != self.last_state
        self.last_state = state
        line = (f'[{t}] {label:<10} {what}  ->  ' + _paint(f'{(state or "?").upper():<10}', C.get(state))
                + f' tier {st.get("tier")}'
                + (f'  ALERT {alert.get("kind")}/{alert.get("status")}' if alert else ''))
        print(line + (_paint('   <- state changed', '1') if changed else ''))
        if changed and st.get('reasons'):
            print('           why: ' + ' '.join(st['reasons']))
        self.last_line = line

    # ---------- loop + commands ----------

    def run_ticks(self):
        while not self.stop.wait(self.every):
            if self.paused:
                continue
            with self.lock:
                try:
                    self.tick()
                except Exception as e:  # noqa: BLE001  keep streaming through a hiccup
                    print(_paint(f'send failed: {e.__class__.__name__}: {e}', '31'))

    def switch(self, mode):
        self.mode = mode
        self.pin.clear()
        self.reset()
        self.backfill(mode)

    def handle(self, line):
        line = line.strip()
        if not line:
            return True
        cmd, _, arg = line.partition(' ')
        cmd = cmd.lower()
        if line.startswith('{'):
            try:
                body = json.loads(line)
            except ValueError as e:
                print(f'Not valid JSON: {e}')
                return True
            status, res = self.post(body)
            self.report('json', status, res, ', '.join(f'{k}={v}' for k, v in body.items() if k != 'events')
                        + (' +events' if body.get('events') else ''))
        elif cmd in MODES:
            self.switch(cmd)
        elif cmd in ('hr', 'hrv'):
            if arg.strip().lower() in ('off', ''):
                self.pin.pop(cmd, None)
                print(f'{cmd} back to the {self.mode} values')
            else:
                try:
                    self.pin[cmd] = float(arg)
                except ValueError:
                    print(f'usage: {cmd} 110   or   {cmd} off')
                    return True
                self.tick()
        elif cmd == 'file':
            try:
                with open(arg.strip().strip('"'), encoding='utf-8') as f:
                    body = json.load(f)
            except (OSError, ValueError) as e:
                print(f'Could not read {arg}: {e}')
                return True
            status, res = self.post(body)
            self.report('file', status, res, os.path.basename(arg.strip()))
        elif cmd == 'pause':
            self.paused = True
            print('paused (type resume)')
        elif cmd == 'resume':
            self.paused = False
            print('resumed')
        elif cmd == 'once':
            self.tick()
        elif cmd == 'reset':
            print('reset' if self.reset() else 'reset failed')
            self.last_state = None
        elif cmd == 'status':
            print(f'mode={self.mode} every={self.every}s paused={self.paused} pinned={self.pin or "-"}\nlast: {self.last_line}')
        elif cmd in ('help', '?'):
            print(HELP)
        elif cmd in ('quit', 'exit', 'q'):
            return False
        else:
            print(f'Unknown command: {cmd}. Type help.')
        return True


def main(argv=None):
    p = argparse.ArgumentParser(description='attuneMIND live terminal watch feed')
    p.add_argument('--url', default='http://127.0.0.1:5050')
    p.add_argument('--every', type=float, default=5, help='seconds between automatic readings (default 5)')
    p.add_argument('--mode', default='calm', choices=list(MODES))
    a = p.parse_args(argv)
    if os.name == 'nt':
        os.system('')   # turn on ANSI colours in the Windows console

    feed = Feed(a.url, a.every, a.mode)
    feed.connect()
    print(_paint(f'Connected to {feed.url} as the demo patient. Device "{LABEL}" created.', '32'))
    print(f'Streaming a reading every {a.every:g}s to /api/wearable/ingest. Type help for commands.\n')
    with feed.lock:
        feed.switch(a.mode)
    threading.Thread(target=feed.run_ticks, daemon=True).start()
    try:
        while True:
            line = input()
            with feed.lock:
                if not feed.handle(line):
                    break
    except (KeyboardInterrupt, EOFError):
        pass
    feed.stop.set()
    print('Feed stopped.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
