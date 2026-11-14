# Apple Watch → AttuneMind: the "AttuneMind Sync" Shortcut

The watch syncs to Apple Health on your iPhone. A Shortcut reads the latest samples and POSTs them over HTTPS
(Cloudflare Tunnel) to `/api/wearable/ingest`. No native app is needed.

```
Apple Watch ──(Apple encrypted sync)──> iPhone Health ──Shortcut, HTTPS──> Cloudflare Tunnel ──> Flask on the laptop
```

## 1. On the laptop

```powershell
.\scripts\wearable.ps1 run        # app on http://127.0.0.1:5050 (DEMO_MODE + DEV_LOGIN on)
.\scripts\wearable.ps1 tunnel     # in a 2nd terminal: prints https://<random>.trycloudflare.com
```

- No `cloudflared`? Install it: `winget install --id Cloudflare.cloudflared`, then open a new terminal.
- Backup: `ngrok http 5050`.
- Put the tunnel URL in `backend/.env` as `PUBLIC_BASE_URL=https://<random>.trycloudflare.com`, then restart `run`.
  The quick-tunnel URL changes every time you restart `tunnel`, so update the Shortcut and `.env` when it does.

## 2. Create a device token

1. Open **My Watch** (`/wearable`) as the patient and accept the consent.
2. **Connect a device** → **Create device token**. The token is shown **once**. Copy it (or scan the QR code with the
   iPhone camera and copy the text). The server stores only a SHA-256 hash.
3. Lost it? Revoke the device and create a new one.

## 3. Build the Shortcut on the iPhone (simple "flat" format)

Open **Shortcuts** → **+** → name it **AttuneMind Sync**. Add these actions:

| # | Action | Settings |
|---|---|---|
| 1 | **Find Health Samples** | Type **Heart Rate**, Start Date *is in the last* **1 hour**, Sort by **Start Date**, Order **Latest First**, Limit **1** |
| 2 | **Get Details of Health Sample** | **Value** → Set Variable `HR` |
| 3 | **Get Details of Health Sample** (of step 1) | **Start Date** → **Format Date**: ISO 8601, include time → Set Variable `HRTime` |
| 4 | **Find Health Samples** | Type **Heart Rate Variability**, last **24 hours**, Latest First, Limit 1 → **Get Details: Value** → Set Variable `HRV` |
| 5 | **Find Health Samples** | Type **Resting Heart Rate**, last **7 days**, Latest First, Limit 1 → **Get Details: Value** → Set Variable `RHR` |
| 6 | **Find Health Samples** *(optional)* | Type **Steps**, last **5 minutes** → **Calculate Statistics: Sum** → Set Variable `Steps` |
| 7 | **Current Date** → **Format Date** | ISO 8601, include time → Set Variable `SentAt` |
| 8 | **Get Contents of URL** | URL `https://<tunnel>/api/wearable/ingest` · Method **POST** · Headers: `X-Device-Token` = *your token*, `Content-Type` = `application/json` · Request Body **JSON** with fields: `sent_at` (Text) = `SentAt`, `ts` (Text) = `HRTime`, `heart_rate` (Number) = `HR`, `hrv_sdnn` (Number) = `HRV`, `resting_hr` (Number) = `RHR`, `steps` (Number) = `Steps` |
| 9 | **Get Dictionary Value** | Key `state.state` from Contents of URL → **Show Notification** "AttuneMind: *Dictionary Value*" |

The JSON body looks like this (the server also accepts the full `samples[]` format from the PRD):

```json
{ "sent_at": "2026-11-14T10:02:11-05:00", "ts": "2026-11-14T10:01:00-05:00",
  "heart_rate": 72, "hrv_sdnn": 41, "resting_hr": 63, "steps": 12 }
```

Notes:
- Health values sometimes arrive as text like `72 count/min`. The server keeps the number.
- `sent_at` must be within 10 minutes of the laptop's clock (replay protection), so build it fresh each run.
- Using the heart-rate sample's own time as `ts` means re-running without a new sample is a harmless duplicate.
- To send a fall or symptom, add `"events": [{"type": "fall_detected"}]` (the event time defaults to `sent_at`).

## 4. Running it

- **Tap it** (Home Screen icon, widget, Back Tap, or "Hey Siri, AttuneMind Sync").
- **Automations:** Shortcuts → Automation → **Time of Day**. iOS has no "every 5 minutes" trigger, so add several
  times, or use **When Apple Watch workout starts/ends**. Set each to **Run Immediately**.
- During the demo, start a **Workout** on the watch: heart rate is sampled much more often.
- First run asks for Health permission per data type. Allow all of them.

Check it worked: **My Watch** shows "last heart-rate sample *x* s ago from apple watch" under Live state, and the
device card shows "last sync *x* ago".

## 5. Make the watch buzz (nudges)

Easiest: **ntfy** (free).
1. Install the **ntfy** app on the iPhone, subscribe to a long random topic, e.g. `attunemind-7f3k2q9x`.
2. In `backend/.env`: `NTFY_TOPIC=attunemind-7f3k2q9x` (restart the app).
3. iPhone notifications mirror to the Apple Watch when the phone is locked. Tier 1–3 nudges now buzz the watch.
   Only the generic nudge text is sent ("Your body seems tense..."), never vitals or names.

Also: open My Watch on the phone (via the tunnel URL, add it to the Home Screen) and tap
**Enable notifications on this device** for browser notifications while it's open.

## Test without the phone

```powershell
.\scripts\wearable.ps1 send -Token <token> -Hr 88                      # same request the Shortcut makes
.\scripts\wearable.ps1 send -Url https://<tunnel> -Token <token>        # through the tunnel (HTTPS)
```
