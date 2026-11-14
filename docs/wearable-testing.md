# Wearable branch: setup, daily workflow and test checklist

Branch: `feature/wearable`. It now includes `main` with the team's roles, Care Team, Alerts and health documents,
and the watch uses them: family get watch alerts on their normal **Alerts** page, providers get watch reports as
**health documents**, and the patient sees both on **Care Team**.

> **Two copies of the project?** Make sure you run the copy you just pulled. Check with `git log --oneline -1`
> (it should show the merge with main) and `git status`. If an older copy's server is still running on 5050,
> stop it (Ctrl+C in its terminal) first, or use `-Port 5051`.

## Quick start (Windows, PowerShell, from the repo root)

```powershell
.\scripts\wearable.ps1 setup     # venv, dependencies, backend/.env with keys + DEMO_MODE/DEV_LOGIN
.\scripts\wearable.ps1 test      # 67 automated tests, ~10 s
.\scripts\wearable.ps1 run       # http://127.0.0.1:5050, opens My Watch as the demo patient
```

If PowerShell blocks scripts: `powershell -ExecutionPolicy Bypass -File .\scripts\wearable.ps1 <command>`.

> **Port 5000 doesn't work on this laptop.** Windows reserves ports 4928–5027 here (`netsh interface ipv4 show
> excludedportrange protocol=tcp`), so `make run` / `python app.py` fail with "access a socket in a way forbidden".
> The helper uses **5050**. Use `-Port` to pick another.

macOS / Linux teammates (from `backend/`):

```bash
python -m wearable.devtool env                         # fill backend/.env for demo testing
DEMO_MODE=1 DEV_LOGIN=1 python -m flask --app app run --port 5050
python -m pytest wearable/tests -q
```

## All helper commands

| Command | What it does |
|---|---|
| `setup` | venv + `pip install -r requirements.txt` + `devtool env` (never overwrites values you already set) |
| `test` | the team's tests + the wearable tests (`pytest tests wearable/tests` in `backend/`) |
| `run [-Port 5050]` | app with `DEMO_MODE=1 DEV_LOGIN=1`, opens `/wearable/dev-login/patient` |
| `sim <scenario> [-Patient N]` | writes a scenario straight to the DB for the demo patient (no browser needed) |
| `send -Token T [-Url U] [-Hr 88]` | one reading exactly like the iPhone Shortcut (good for testing the tunnel) |
| `tunnel` | Cloudflare quick tunnel → HTTPS URL for the phone |
| `status` | shows DEMO_MODE, keys, AI tier, tunnel, ntfy |
| `reset-db` | deletes `backend/instance/attunemind.db` (asks first) |

Scenarios: `baseline`, `exercise`, `stress_spike`, `sustained_distress`, `fall`, `cardiac_warning`, `recovery`.
They are seeded, so the same scenario always produces the same curves and the same result.

## One-click roles (DEV_LOGIN=1)

| URL | Signs you in as | Lands on |
|---|---|---|
| `/wearable/dev-login/patient` | Demo Patient | My Watch |
| `/wearable/dev-login/family` | Demo Family member, on the demo patient's care team | Alerts (`/family`) |
| `/wearable/dev-login/provider` | Demo Health provider (Demo Clinic), on the care team | the patient's health documents |

These are the same demo accounts as the normal **Sign in → demo** buttons, but they skip the consent screen and put
the family member and provider on Demo Patient's Care Team automatically, so alerts and reports reach them straight away.

Sign-ins share a browser, so use a **private/incognito window** (or a second browser) for family/provider while the
patient stays signed in in the normal window.

**Tip:** run `setup` once so `FLASK_SECRET_KEY` is fixed. Without it every restart signs everyone out.

## Staying mergeable (PRD §0A)

```powershell
git fetch origin
git rebase origin/main          # at least every few hours
.\scripts\wearable.ps1 test
git push --force-with-lease     # only after a rebase of your own branch
```

Existing files touched (each in a `# --- wearable ---` block):
`backend/app.py` (4 lines), `backend/requirements.txt`, `frontend/templates/base.html` (1 nav link),
`backend/.env.example` (documented settings). Everything else is new: `backend/wearable/`, `frontend/templates/wearable*.html`,
`frontend/static/{js,css}/wearable.*`, `docs/`, `scripts/wearable.ps1`.

After the roles branch merges into `main`: rebase, then change **only** `backend/wearable/integrations.py`
(the TODOs are in its docstring).

---

# Test checklist

Tick these off in order. ✅ = what you should see.

## A. Automated (2 min)

- [ ] `.\scripts\wearable.ps1 test` → ✅ `96 passed` (22 team tests + 74 wearable tests)
- [ ] `.\scripts\wearable.ps1 status` → ✅ `WEARABLE_DATA_KEY set: True`, `DEMO_MODE: 1`, `DEV_LOGIN: 1`

## B. Patient page basics (`run`, then the page that opens)

- [ ] Consent card shows first. **I understand and agree** → ✅ card disappears.
- [ ] Nav bar has **My Watch**; the rest of the site (Chat, Calm Toolkit, My Progress, Care Team) still works.
- [ ] **Who gets told what** says "1 family member(s) on your care team will get alerts."
- [ ] Top-right chip says **⚠️ Local http (dev only)** on 127.0.0.1.

## C. Reader: exercise vs. stress (Demo Control Panel)

- [ ] **Reset demo data** → ✅ log says reset.
- [ ] **Exercise** → ✅ ring blue **Exercising**, HR ~140, "no stress alert", log says `no family alert`, **no nudge banner**.
- [ ] **Stress spike** → ✅ orange **Stressed**, reasons "HR ~40% above your resting rate while sitting still", nudge banner
      "Your body seems tense…", **Your plan right now** fills in. **Take 2 minutes** opens `/toolkit#breathing`.
- [ ] Click **Stress spike** again → ✅ still one nudge (15-min de-dup).
- [ ] **I'm exercising** → ✅ state switches to Exercising (holds stress alerts off 20 min).
- [ ] **Reset**, then **Sustained distress** → ✅ red **Distressed** (Tier 2), stronger nudge, **no** family alert (toggle is off).
- [ ] Turn on **Tell family when I'm very stressed**, **Reset**, **Sustained distress** → ✅ log shows `family alert distress open`.
- [ ] **Recovery** → ✅ back to **Calm**.
- [ ] Timeline chart shows the heart-rate line and coloured state bands; range selector works.

## D. Emergencies, 911 and family (needs a private window)

- [ ] Private window (Ctrl+Shift+N) → `http://127.0.0.1:5050/wearable/dev-login/family` → ✅ **Alerts** page,
      "Watching over: **Demo Patient**", "No alerts. All quiet."
- [ ] Patient window: **Fall** → ✅ full-screen red overlay, **Call 911** first, "your family will be alerted in **58–60 s**".
- [ ] Wait 60 s → ✅ patient sees "Your family has been alerted"; family window shows **Possible fall (watch): Demo Patient**
      "from their watch" within 5 s, generic text, no numbers. Works even if you close the patient tab.
- [ ] Family: **I've seen this and I'm checking in** → ✅ patient overlay changes to "Your family has seen the alert."
- [ ] **I'm OK** → ✅ overlay closes.
- [ ] **Reset**, **Fall**, then **Call 911** → ✅ "Demo mode: no real call was placed. On a phone this button dials 911.
      Your family has been alerted now." The family alert arrives **immediately** (no 60 s wait). In DEMO_MODE the button
      never dials, even on a phone.
- [ ] **Reset**, **Fall**, then tap **I'm OK** within 60 s → ✅ overlay closes, family **never** get an alert.
- [ ] **Cardiac warning** → ✅ overlay "Warning signs detected", family alert **Warning signs (watch)** appears immediately.
- [ ] **Something feels physically wrong → Chest pain** → ✅ same cardiac overlay.
- [ ] Turn off **Emergency alerts to family**, **Reset**, **Cardiac warning** → ✅ no family alert.
- [ ] Patient → **Care Team** → ✅ the watch alerts are listed with the SOS / chat alerts; remove the family member → ✅
      My Watch says nobody receives alerts, and the emergency screen says so too.

## E. Provider (doctor)

- [ ] Private window → `/wearable/dev-login/provider` → ✅ "Demo Patient: health documents" with
      **Wearable report … (possible fall)** (or "cardiac warning signs" / "strong stress episode") on top. Open it → ✅
      episodes, falls, "Exercise correctly ignored", trends. Reload after each emergency: a new report appears.
- [ ] Provider gets **no** alerts: Alerts isn't in their menu, and in devtools
      `fetch('/api/alerts').then(r => r.status)` → ✅ `403`; `fetch('/api/patients/1/state').then(r => r.status)` → ✅ `403`.
- [ ] Patient window → **Your privacy → Who viewed my data** → ✅ provider `read_state` (**denied**) row.

## F. Privacy and security (PRD §5A.6)

- [ ] **Your privacy** shows Fernet at rest, TLS in transit, AI tier **free** → "AI features off to protect your data".
- [ ] **Export my data** → ✅ JSON download with samples, states, alerts, reports, audit log.
- [ ] DB is ciphertext: `cd backend; .venv\Scripts\python.exe -c "import sqlite3; print(sqlite3.connect('instance/attunemind.db').execute('select value_enc from wearable_vital_sample limit 2').fetchall())"` → ✅ `gAAAA…` strings, no numbers.
- [ ] Plain HTTP from another machine is refused: with the app started on `--host 0.0.0.0`, phone on the same Wi-Fi → `http://<laptop-ip>:5050/api/wearable/ingest` → ✅ 403. (Also covered by tests.)
- [ ] Revoke a device, then `send` with its token → ✅ `HTTP 401`.
- [ ] Idle logoff: set `WEARABLE_IDLE_MINUTES=1` in `.env`, restart, leave My Watch untouched > 1 min, then click a button → ✅ signed out. Set it back to 15.
- [ ] Watch the `run` terminal during a full scenario run → ✅ only IDs, actions and states; no heart-rate numbers.
- [ ] **Delete my wearable data** (type DELETE) → ✅ everything gone except the audit log (which records the deletion); device stops working (401).

## G. Wearable device (Apple Watch + iPhone) — see `docs/apple-watch-shortcut.md`

- [ ] `winget install --id Cloudflare.cloudflared`, then `.\scripts\wearable.ps1 tunnel` → ✅ `https://….trycloudflare.com` URL.
- [ ] Put it in `.env` as `PUBLIC_BASE_URL`, restart `run`. Open the tunnel URL on the laptop → ✅ chip says **🔒 Encrypted connection (TLS)**.
- [ ] My Watch → **Create device token** → ✅ token + QR + ingest URL shown once; the device list shows only the label.
- [ ] From the laptop, through the tunnel: `.\scripts\wearable.ps1 send -Url https://<tunnel> -Token <token>` → ✅ `HTTP 200`.
- [ ] Same with `http://` instead of `https://` → ✅ 403 or a redirect, never stored.
- [ ] Build the **AttuneMind Sync** Shortcut, run it → ✅ notification with a state; My Watch shows
      "last heart-rate sample … from apple watch" and the device card shows "last sync … ago".
- [ ] Run it twice in a row without a new sample → ✅ second run reports duplicates, nothing new stored.
- [ ] Start a **Workout** on the watch, walk/jog 3–5 min, run the Shortcut → ✅ **Exercising**, no nudge.
- [ ] Sit still after the workout, run again → ✅ **Recovering** or **Calm**.
- [ ] Watch buzz: install **ntfy**, subscribe to your topic, set `NTFY_TOPIC` in `.env`, restart, lock the phone, click **Stress spike** → ✅ the watch buzzes with "Your body seems tense…".
- [ ] Revoke the device on My Watch, run the Shortcut → ✅ 401 in the Shortcut result.

## H. Demo rehearsal (PRD §11, ~4 min)

- [ ] Real watch reading on screen ("That's my actual heart rate").
- [ ] Exercise → Exercising, no alert.
- [ ] Stress spike → Stressed, watch buzzes, do box breathing in the Calm Toolkit, Recovery → Calm.
- [ ] Fall → Call 911 / I'm OK, let the countdown expire, family laptop shows the alert, family acknowledge.
- [ ] Provider opens the wearable report: episodes + fall listed, no alert ever sent to them.
- [ ] Patient opens **Your privacy**: encryption, who viewed, AI card; turns off family Tier 2 alerts and explains.

## Known limits on this branch

- Wearable reports are saved as health documents (plain text like the team's other documents); vitals, events and
  states stay Fernet-encrypted in the `wearable_*` tables.
- Nudges reach the watch through ntfy (or browser notifications). Web Push/PWA isn't built.
- Ambience colours and the sleep wind-down (PRD §10.4) aren't built; that section is shared with teammates' branches.
- Port 5000 is unusable on this laptop (see above).
