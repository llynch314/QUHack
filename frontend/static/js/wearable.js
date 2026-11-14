// attuneMIND "My Watch" page: live state, nudges, emergency overlay, timeline, demo panel,
// device pairing, settings and the privacy panel. Plain JS + fetch, polls every 5 s.
(function () {
    const PID = window.W_PATIENT_ID;
    const $ = id => document.getElementById(id);
    let lastActive = Date.now();
    ['pointerdown', 'keydown', 'scroll', 'touchstart'].forEach(ev =>
        window.addEventListener(ev, () => { lastActive = Date.now(); }, { passive: true }));

    // ---------- fetch helper ----------
    async function api(path, { method = 'GET', body, poll = false } = {}) {
        const headers = { 'Content-Type': 'application/json' };
        if (poll) {
            headers['X-Wearable-Poll'] = '1';
            if (Date.now() - lastActive < 60000) headers['X-User-Active'] = '1';
        }
        const res = await fetch(path, { method, headers, body: body ? JSON.stringify(body) : undefined });
        let data = {};
        try { data = await res.json(); } catch (e) { /* non-JSON */ }
        if (res.status === 401 && data.reauth) {
            alert(data.error);
            location.href = '/login?next=/wearable';
            throw new Error('signed out');
        }
        if (!res.ok) {
            const err = new Error(data.error || ('HTTP ' + res.status));
            err.data = data; err.status = res.status;
            throw err;
        }
        return data;
    }

    const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    const ago = iso => {
        if (!iso) return 'never';
        const s = Math.round((Date.now() - new Date(iso)) / 1000);
        if (s < 60) return s + ' s ago';
        if (s < 3600) return Math.round(s / 60) + ' min ago';
        if (s < 86400) return Math.round(s / 3600) + ' h ago';
        return new Date(iso).toLocaleString();
    };
    function log(msg) {
        const el = $('demoLog');
        if (!el) return;
        el.textContent = `[${new Date().toLocaleTimeString()}] ${msg}\n` + el.textContent;
    }

    // ---------- live state ----------
    let shownNudge = null, emergencyKey = null, countdownTimer = null, familyCount = 0;

    function renderState(d) {
        const st = d.state;
        const ring = $('ring');
        ring.className = 'ring' + (st ? ' state-' + st.state : '');
        $('stateName').textContent = st ? st.state : 'no data';
        $('stateConf').textContent = st ? `confidence ${Math.round(st.confidence * 100)}%` : '';
        const L = d.latest || {};
        $('hr').textContent = L.heart_rate ? Math.round(L.heart_rate.value) : '-';
        $('hrv').textContent = L.hrv_sdnn ? Math.round(L.hrv_sdnn.value) : '-';
        $('rest').textContent = L.resting_hr ? Math.round(L.resting_hr.value) : '-';
        $('explain').textContent = st ? st.explanation : 'Waiting for your first sync. Connect a device below, or use the Demo Control Panel.';
        $('why').innerHTML = st ? st.reasons.map(r => `<li>${esc(r)}</li>`).join('') : '';
        const src = L.heart_rate ? ` · last heart-rate sample ${ago(L.heart_rate.ts)} from ${L.heart_rate.source.replace('_', ' ')}` : '';
        $('updated').textContent = st ? `State updated ${ago(st.ts)}${src}` : '';

        // plan
        if (d.plan) {
            $('planBody').innerHTML = `<ol class="stack">${d.plan.steps.map(s => `<li>${s.link ? `<a href="${esc(s.link)}">${esc(s.text)}</a>` : esc(s.text)}</li>`).join('')}</ol>
                <p class="small muted">Most people feel steadier in about ${d.plan.projected_minutes} minutes (based on ${esc(d.plan.based_on)}).</p>`;
        } else {
            $('planBody').innerHTML = '<p class="muted">Nothing to work through right now. When your body seems tense, a short step-by-step plan shows up here.</p>';
        }

        // nudge banner (+ browser notification)
        const n = d.nudge;
        if (n && n.tier < 3) {
            $('nudge').hidden = false;
            $('nudge').className = 'nudge' + (n.tier >= 2 ? ' t2' : '');
            $('nudgeText').textContent = n.message;
            $('nudgeLink').href = n.link || '/toolkit';
            $('nudgeLink').textContent = n.link && n.link.includes('plan') ? 'See my plan' : 'Take 2 minutes';
            if (shownNudge !== n.id) {
                shownNudge = n.id;
                if ('Notification' in window && Notification.permission === 'granted') {
                    try { new Notification('attuneMIND', { body: n.message }); } catch (e) { /* ignore */ }
                }
                if (navigator.vibrate) navigator.vibrate([200, 100, 200]);
            }
        } else {
            $('nudge').hidden = true;
        }

        familyCount = d.family_count || 0;
        if ($('familyNote')) $('familyNote').textContent = familyCount ? `${familyCount} family member(s) on your care team will get alerts.`
            : 'No family member is on your care team yet, so nobody receives alerts. Add one on the Care Team page.';

        // emergency overlay
        const isEm = st && st.state === 'emergency';
        const pending = d.pending_alert;
        const key = isEm ? st.kind + st.ts.slice(0, 16) : null;
        if (isEm) {
            $('emergency').hidden = false;
            $('emTitle').textContent = st.kind === 'fall' ? 'Possible fall detected' : 'Warning signs detected';
            $('emText').textContent = st.explanation;
            if (emergencyKey !== key) { emergencyKey = key; $('emCallNote').hidden = true; $('emCall').focus(); }
            clearInterval(countdownTimer);
            const tick = () => {
                if (!familyCount && st.kind) {
                    $('emCount').textContent = 'No family member is on your care team, so nobody will be alerted. Call 911 if you need help.';
                } else if (pending && pending.send_at) {
                    const left = Math.max(0, Math.round((new Date(pending.send_at) - Date.now()) / 1000));
                    $('emCount').textContent = left > 0 ? `If you don't tap "I'm OK", your family will be alerted in ${left} s.`
                        : 'Your family is being alerted.';
                } else if (d.last_family_alert && ['open', 'acknowledged'].includes(d.last_family_alert.status)
                           && d.last_family_alert.kind === st.kind) {
                    $('emCount').textContent = d.last_family_alert.status === 'acknowledged'
                        ? 'Your family has seen the alert.' : 'Your family has been alerted.';
                } else {
                    $('emCount').textContent = '';
                }
            };
            tick();
            countdownTimer = setInterval(tick, 1000);
        } else {
            $('emergency').hidden = true;
            clearInterval(countdownTimer);
        }
    }

    async function refreshState(poll = true) {
        try {
            renderState(await api(`/api/patients/${PID}/state`, { poll }));
        } catch (e) { if (e.message !== 'signed out') console.warn(e); }
    }

    // ---------- timeline chart ----------
    const STATE_COLORS = { stressed: '#ef6c00', distressed: '#c62828', emergency: '#c62828', exercising: '#1565c0' };
    async function refreshChart(poll = true) {
        let d;
        try { d = await api(`/api/patients/${PID}/vitals?range=${$('range').value}`, { poll }); } catch (e) { return; }
        const svg = $('chart'), W = 800, H = 180, P = 22;
        const hr = d.series.heart_rate, hrv = d.series.hrv_sdnn;
        const all = hr.concat(hrv, d.states);
        if (!hr.length && !hrv.length) {
            svg.innerHTML = `<text x="${W / 2}" y="${H / 2}" text-anchor="middle">No data in this range yet</text>`;
            return;
        }
        const times = all.map(p => +new Date(p.ts));
        const t0 = Math.min(...times), t1 = Math.max(...times, t0 + 60000);
        const x = t => P + (W - 2 * P) * ((+new Date(t) - t0) / (t1 - t0));
        const yv = (v, lo, hi) => H - P - (H - 2 * P) * ((v - lo) / (hi - lo || 1));
        let out = '';
        // state bands
        d.states.forEach((s, i) => {
            const c = STATE_COLORS[s.state];
            if (!c) return;
            const next = d.states[i + 1];
            const x1 = x(s.ts), x2 = next ? x(next.ts) : W - P;
            out += `<rect x="${x1}" y="${P / 2}" width="${Math.max(2, x2 - x1)}" height="${H - P}" fill="${c}" opacity="0.15"/>`;
        });
        const line = (pts, lo, hi, color) => pts.length ? `<polyline fill="none" stroke="${color}" stroke-width="2" points="${pts.map(p => `${x(p.ts).toFixed(1)},${yv(p.value, lo, hi).toFixed(1)}`).join(' ')}"/>` : '';
        out += line(hr, 30, 180, 'var(--primary)') + line(hrv, 0, 100, '#00897b');
        [60, 100, 140].forEach(v => { out += `<text x="2" y="${yv(v, 30, 180) + 4}">${v}</text>`; });
        out += `<text x="${P}" y="${H - 4}">${new Date(t0).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</text>`;
        out += `<text x="${W - P}" y="${H - 4}" text-anchor="end">${new Date(t1).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</text>`;
        svg.innerHTML = out;
    }

    // ---------- patient actions ----------
    async function act(path, body, label) {
        try {
            const r = await api(path, { method: 'POST', body });
            log(`${label} -> state=${r.state ? r.state.state : '?'}${r.alert ? ` family alert=${r.alert.kind}/${r.alert.status}` : ''}${r.cancelled_alerts ? ' (family alert cancelled)' : ''}`);
            await refreshState(false);
            refreshChart(false);
        } catch (e) { alert(e.message); }
    }
    $('btnExercising').onclick = () => act('/api/wearable/feedback', { correction: 'exercising' }, "I'm exercising");
    $('btnNotOkay').onclick = () => act('/api/wearable/feedback', { correction: 'not_okay' }, "I'm not okay");
    $('emOk').onclick = () => act('/api/wearable/feedback', { correction: 'im_ok' }, "I'm OK");

    // Call 911: on a real phone the tel: link dials. In DEMO_MODE, or on a computer (which can't
    // place calls), we never dial and say so instead. Either way family are alerted right away.
    const isPhone = /Android|iPhone|iPad|iPod/i.test(navigator.userAgent);
    document.querySelectorAll('.call911').forEach(a => a.addEventListener('click', async ev => {
        const dials = isPhone && !window.W_DEMO;
        if (!dials) ev.preventDefault();
        let r = null;
        try { r = await api('/api/wearable/emergency/call', { method: 'POST' }); } catch (e) { /* still show the note */ }
        const fam = !r ? '' : r.family_alerted ? ' Your family has been alerted now.'
            : r.family_count ? '' : ' No family member is on your care team, so nobody was alerted.';
        const msg = window.W_DEMO ? 'Demo mode: no real call was placed. On a phone this button dials 911.' + fam
            : dials ? 'Calling 911...' + fam : "This computer can't place calls: call 911 from your phone now." + fam;
        log('Call 911 tapped' + (dials ? ' (dialing)' : ' (not dialed)') + (r && r.family_alerted ? ', family alerted now' : ''));
        const note = $('emCallNote');
        if (!$('emergency').hidden) { note.textContent = msg; note.hidden = false; } else { alert(msg); }
        refreshState(false);
    }));
    document.querySelectorAll('[data-symptom]').forEach(b => {
        b.onclick = () => act('/api/wearable/self-report', { symptom: b.dataset.symptom }, 'Self-report ' + b.dataset.symptom);
    });
    $('nudgeDismiss').onclick = async () => {
        if (!shownNudge) return;
        try { await api(`/api/wearable/nudges/${shownNudge}/seen`, { method: 'POST' }); } catch (e) { /* ignore */ }
        $('nudge').hidden = true;
    };
    $('nudgeLink').addEventListener('click', () => { if (shownNudge) api(`/api/wearable/nudges/${shownNudge}/seen`, { method: 'POST' }).catch(() => {}); });

    // The demo controls live on their own page (/demo), not in the patient's app.
    if ($('makeReport')) $('makeReport').onclick = async () => {
        const r = await api(`/api/patients/${PID}/wearable-report`, { method: 'POST' });
        log('Report created: ' + r.report.title);
        loadReports(r.report.id);
    };

    // ---------- consent ----------
    $('consentBtn').onclick = async () => {
        await api('/api/wearable/consent', { method: 'POST', body: { accept: true } });
        $('consent').hidden = true;
        loadPrivacy();
    };

    // ---------- devices ----------
    let lastIngestUrl = '';
    async function loadDevices(poll = false) {
        const { devices } = await api('/api/wearable/devices', { poll });
        const active = devices.filter(d => !d.revoked);
        $('deviceList').innerHTML = devices.length ? devices.map(d => `<li class="card small">
            <strong>${esc(d.label)}</strong> ${d.revoked ? '<span class="tag denied">revoked</span>' : '<span class="tag">active</span>'}<br>
            Encrypted connection (TLS) · last sync ${esc(ago(d.last_seen_at))}
            ${d.revoked ? '' : `<button type="button" class="btn btn-ghost" data-revoke="${d.id}" style="min-height:32px;padding:2px 10px;margin-left:6px">Revoke</button>`}</li>`).join('')
            : '<li class="muted small">No devices yet.</li>';
        $('deviceList').querySelectorAll('[data-revoke]').forEach(b => b.onclick = async () => {
            if (!confirm('Revoke this device? It will stop syncing immediately.')) return;
            await api(`/api/wearable/devices/${b.dataset.revoke}`, { method: 'DELETE' });
            loadDevices();
        });
        const seen = active.map(d => d.last_seen_at).filter(Boolean).sort().pop();
        $('syncChip').textContent = active.length ? `${active.length} device(s) · last sync ${ago(seen)}` : 'No device yet';
    }
    $('devCreate').onclick = async () => {
        try {
            const r = await api('/api/wearable/devices', { method: 'POST', body: { label: $('devLabel').value } });
            $('newToken').hidden = false;
            $('tokenText').textContent = r.token;
            $('tokenQr').src = r.qr;
            $('ingestUrl').textContent = lastIngestUrl = r.ingest_url;
            loadDevices();
        } catch (e) {
            alert(e.message);
            if (e.data && e.data.consent_required) $('consent').scrollIntoView();
        }
    };
    $('copyToken').onclick = () => navigator.clipboard.writeText($('tokenText').textContent);
    $('copyUrl').onclick = () => navigator.clipboard.writeText(lastIngestUrl);

    // ---------- settings ----------
    const TOGGLES = ['emergency_alerts', 'family_tier2_alerts', 'ai_explanations'];
    TOGGLES.forEach(k => $(k).onchange = async () => {
        try {
            await api('/api/wearable/profile', { method: 'POST', body: { [k]: $(k).checked } });
            $('settingsStatus').textContent = k === 'family_tier2_alerts'
                ? ($(k).checked ? 'Saved. Family will get a generic message after a sustained stress episode.' : 'Saved. Family will no longer hear about stress, only emergencies (if that is on).')
                : 'Saved.';
            loadPrivacy();
        } catch (e) { alert(e.message); }
    });

    // ---------- privacy ----------
    async function loadPrivacy() {
        const p = await api('/api/wearable/privacy');
        $('consent').hidden = p.profile.consent_current;
        TOGGLES.forEach(k => { $(k).checked = !!p.profile[k]; });
        const e = p.encryption;
        $('privEnc').innerHTML = [
            `In transit: ${esc(e.in_transit)}${location.protocol === 'https:' ? ' (this page is on HTTPS now)' : ' (you are on local http; the phone must use the tunnel URL)'}`,
            `At rest: ${esc(e.at_rest)}${e.key_source === 'dev-generated' ? ' <span class="tag denied">dev key: demo only</span>' : ''}`,
            'Device tokens: stored only as a SHA-256 hash, write-only, revocable',
            'Auto sign-out after inactivity on this page',
            'Every view of your data is in the audit log below',
        ].map(x => `<li>${x}</li>`).join('');
        const a = p.ai;
        const trained = a.tier === 'free' ? 'AI features off to protect your data (free tier)' : 'Used to train AI: <strong>No</strong>';
        $('privAi').innerHTML = [
            `Provider: ${esc(a.provider)} (${esc(a.model)})`,
            `Data tier: <strong>${esc(a.tier)}</strong>`,
            trained,
            `Wearable AI explanations: ${a.enabled_for_wearable ? 'on' : 'off'}`,
            `Sent when on: ${a.fields_sent.map(esc).join(', ')}. Never your name, email, IDs, timestamps or raw vitals.`,
            `AI calls this week: ${a.calls_this_week}`,
            'The state reader itself is rule-based and runs on our server, not in the AI.',
        ].map(x => `<li>${x}</li>`).join('');
        $('auditRows').innerHTML = p.audit.map(r => `<tr><td>${esc(new Date(r.ts).toLocaleString())}</td>
            <td>${esc(r.actor_role)}${r.actor_id ? ' #' + r.actor_id : ''}</td><td>${esc(r.action)}</td>
            <td><span class="tag ${r.outcome === 'denied' ? 'denied' : ''}">${esc(r.outcome)}</span></td></tr>`).join('');
        $('connChip').textContent = location.protocol === 'https:' ? 'Encrypted connection (TLS)' : 'Local http (dev only)';
        $('connChip').className = 'chip ' + (location.protocol === 'https:' ? 'ok' : 'warn');
    }
    $('deleteBtn').onclick = async () => {
        const typed = prompt('This permanently deletes your wearable samples, states, events, alerts, reports and devices. The audit log keeps a record of the deletion.\n\nType DELETE to confirm.');
        if (typed !== 'DELETE') return;
        await api('/api/wearable/delete', { method: 'POST', body: { confirm: 'DELETE' } });
        alert('Your wearable data was deleted.');
        location.reload();
    };

    // ---------- reports ----------
    async function loadReports(openId) {
        const { reports } = await api('/api/wearable/reports');
        $('reportList').innerHTML = reports.length ? reports.map(r => `<li><a href="#reports" data-report="${r.id}">${esc(r.title)}</a></li>`).join('')
            : '<li class="muted">No reports yet.</li>';
        $('reportList').querySelectorAll('[data-report]').forEach(a => a.onclick = () => showReport(a.dataset.report));
        if (openId) showReport(openId);
    }
    async function showReport(id) {
        const { report } = await api(`/api/wearable/reports/${id}`);
        $('reportBody').hidden = false;
        $('reportBody').textContent = report.body;
    }

    // ---------- start ----------
    if ('Notification' in window && Notification.permission === 'default') {
        const b = document.createElement('button');
        b.className = 'btn btn-ghost'; b.textContent = 'Enable notifications on this device';
        b.onclick = () => Notification.requestPermission().then(() => b.remove());
        $('settings').appendChild(b);
    }
    $('range').onchange = () => refreshChart(false);
    refreshState(false); refreshChart(false); loadDevices(); loadPrivacy(); loadReports();
    setInterval(refreshState, 5000);
    setInterval(refreshChart, 30000);
    setInterval(() => { loadDevices(true).catch(() => {}); }, 30000);
    setInterval(() => { loadReports().catch(() => {}); }, 15000);
})();
