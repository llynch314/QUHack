# AttuneMind wearable: HIPAA safeguards map

**Say "built to HIPAA safeguards", not "HIPAA compliant".** There is no HIPAA certification, and real compliance also
needs signed BAAs, a risk analysis, workforce policies and training. This prototype uses synthetic data, except
Roberto's own watch data with his consent.

## Technical safeguards (built, in `backend/wearable/`)

| Security Rule safeguard | Implementation | Where |
|---|---|---|
| Unique user identification | Every person has their own login (Google / DEV_LOGIN). Shared logins aren't allowed. | `auth.py` (main) |
| Access control / minimum necessary | Patient: own vitals. Family: alerts only, generic text. Provider: reports only, never live alerts. Enforced server-side. | `integrations.can_view_vitals`, `routes.py` |
| Automatic logoff | Vitals pages sign out after 15 min without user activity. Background polling doesn't count as activity. | `security.check_idle` |
| Audit controls | Every read/write of wearable data → `wearable_audit_log` (who, role, action, patient, IP, time, allowed/denied). Shown to the patient as "Who viewed my data". Identical reads within 60 s are coalesced. | `security.audit` |
| Integrity | Fernet HMAC detects tampering with stored values. Strict ingest schema + plausible ranges. Audit log is append-only (no update/delete route). | `security.py`, `service.validate_payload` |
| Person / entity authentication | User login + device tokens (32 random bytes, shown once, stored as SHA-256, write-only, revocable). | `security.new_device_token` |
| Transmission security | HTTPS via Cloudflare Tunnel; non-HTTPS rejected (403); HSTS; forwarded-proto trusted only from the local tunnel. | `security.transport_allowed` |
| Encryption at rest | `value_enc`, `meta_enc`, `reasons_enc`, `body_enc` encrypted with Fernet (AES-128-CBC + HMAC-SHA256). Key in `.env` (`WEARABLE_DATA_KEY`). App refuses to start without it unless `DEMO_MODE=1`. | `security.EncryptedText` |
| Replay / abuse | `sent_at` must be within 10 min; dedupe on (patient, type, ts); 60 req/min per device; 256 KB payload cap. | `routes.ingest`, `service.py` |
| No PHI in logs | Logs hold IDs and event types only (tested). | `test_security.py` |
| Patient rights | Versioned consent before first sync; export JSON; delete wearable data; revoke devices; per-alert-type toggles. | `routes.py` |
| AI data use | `AI_DATA_TIER=free` turns off every AI call that would receive wearable-derived data. Reader is rule-based. Optional explanation sends only derived numbers. `wearable_ai_usage_log` stores metadata only. | `ai_explain.py` |

## Risk analysis (short)

| Threat | Likelihood / impact | Mitigation |
|---|---|---|
| Lost or stolen phone | Medium / Medium | Device token is write-only (can't read data). Patient revokes it in one click. Phone passcode + Face ID. |
| Leaked device token | Low / Medium | Write-only, scoped to one patient, rate-limited, revocable; only the hash is stored server-side. |
| Stolen laptop or copied DB file | Low / High | Sensitive columns are ciphertext; key lives in `.env`, not in the DB. Full-disk encryption (BitLocker) on the laptop. Production: managed key (Cloud KMS). |
| Network eavesdropping | Low / High | TLS end-to-end through the tunnel; plain HTTP rejected; no inbound ports opened. |
| AI vendor training on data | Medium / High | Free tier blocked; only de-identified derived numbers on paid tier; production needs Vertex AI under Google's BAA. |
| Family member sees too much | Medium / Medium | Family get alerts only, generic text, no vitals; Tier 2 sharing is opt-in; patient can revoke links. |
| Provider over-alerted / liability | Low / Medium | Providers never get live alerts, only reports. |
| Insider misuse | Low / High | Audit log visible to the patient; denied attempts recorded. |
| False reassurance in an emergency | Low / High | Call 911 always shown first; app never claims to diagnose; family alerts are in addition to 911. |

## BAAs needed for production

- **AI vendor:** the app now uses Anthropic Claude (main's `claude_client.py`). Before sending wearable-derived data, get Anthropic's BAA / zero-data-retention terms in place; until then keep `AI_DATA_TIER=free`.
- **Hosting:** a HIPAA-eligible cloud (e.g. Google Cloud, AWS, Azure) with a signed BAA.
- **Push / SMS provider:** e.g. Twilio (BAA available). ntfy.sh is for the demo only and receives only generic text.
- **Tunnel/CDN:** Cloudflare (enterprise BAA) or replace the tunnel with hosting behind a managed load balancer.

## Breach response plan

1. **Contain:** revoke all device tokens for affected patients; disable demo endpoints; rotate `FLASK_SECRET_KEY` (signs everyone out).
2. **Rotate `WEARABLE_DATA_KEY`:** decrypt with the old key and re-encrypt with a new one (`MultiFernet`), then destroy the old key.
3. **Investigate:** review `wearable_audit_log` for unusual actors, denied attempts, IPs and times.
4. **Notify:** affected individuals without unreasonable delay and no later than **60 days** after discovery; HHS
   (within 60 days if 500+ people, otherwise in the annual log); media if 500+ in one state. Document everything.
5. **Fix and review:** patch the root cause, update this risk analysis, re-train the team.

## Workforce and physical safeguards

- No real patient data in development. Synthetic/simulator data only (plus a team member's own data, with consent).
- No shared logins; each teammate signs in as themselves. DEV_LOGIN only on local demo machines.
- `.env` is never committed; keys are shared out-of-band, never in chat or git.
- Laptop: full-disk encryption (BitLocker / FileVault), screen lock, OS updates.
- Production: hosting in a HIPAA-eligible data center; access reviews; backups encrypted.
