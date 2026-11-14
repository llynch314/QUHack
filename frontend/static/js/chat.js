// Text chat with Claude, the toolbar on top of the chat (voice, camera, read aloud), dictation,
// and the optional webcam expression check. Used by templates/chat.html and the patient app
// (test.html). Voice chat itself is in voice.js.
(function () {
    const $ = id => document.getElementById(id);
    const log = $('chatLog');
    const form = $('chatForm');
    const input = $('chatInput');
    const sendBtn = $('sendBtn');
    const status = $('chatStatus');
    const crisisPanel = $('crisisPanel');
    const live = $('chatLive');
    const DEMO = !!window.ATTUNE_DEMO;   // patient app preview without a server

    window.MC = window.MC || {};
    const speakNow = text => (MC.speak ? MC.speak(text) : null);
    const readAloudOn = () => (MC.readAloudOn ? MC.readAloudOn() : false);

    // Conversation history lives only in this page (not stored on the server).
    const history = [];
    let emotion = null;

    function addBubble(role, text, { speakButton = true } = {}) {
        const div = document.createElement('div');
        div.className = 'bubble ' + role;
        div.textContent = text;
        if (role === 'model' && speakButton && text && 'speechSynthesis' in window) {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'btn speak-btn';
            btn.textContent = 'Read aloud';
            btn.addEventListener('click', () => speakNow(text));
            div.appendChild(document.createElement('br'));
            div.appendChild(btn);
        }
        log.appendChild(div);
        log.scrollTop = log.scrollHeight;
        return div;
    }

    function showCrisis() {
        if (crisisPanel && crisisPanel.hidden) {
            crisisPanel.hidden = false;
            crisisPanel.scrollIntoView({ behavior: MC.reduceMotion && MC.reduceMotion() ? 'auto' : 'smooth', block: 'nearest' });
        }
    }

    async function ask(messages) {
        if (DEMO) return { reply: 'This is a demo, so I can\'t reply for real. In the full app, an AI companion listens and helps you find your own answers.', crisis: false };
        const res = await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ messages, emotion }),
        });
        if (res.status === 401) { location.href = '/signin?next=' + encodeURIComponent(location.pathname + location.hash); throw new Error('Please sign in.'); }
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || 'Something went wrong.');
        return data;
    }

    async function send(text) {
        history.push({ role: 'user', text });
        addBubble('user', text);
        sendBtn.disabled = true;
        status.textContent = 'attuneMIND is thinking...';
        try {
            const data = await ask(history);
            history.push({ role: 'model', text: data.reply });
            addBubble('model', data.reply);
            if (data.crisis) showCrisis();
            if (data.mood && window.Aura) Aura.setMood(data.mood, 'chat');
            if (data.alert_sent) addBubble('system', 'The family members on your care team were sent an alert so they can check in with you. They can\'t see what you wrote.');
            if (readAloudOn()) speakNow(data.reply);
            status.textContent = '';
        } catch (err) {
            history.pop();   // let the user resend
            addBubble('system', err.message);
            status.textContent = '';
        } finally {
            sendBtn.disabled = false;
            input.focus();
        }
    }

    form.addEventListener('submit', e => {
        e.preventDefault();
        const text = input.value.trim();
        if (!text || sendBtn.disabled) return;
        input.value = '';
        send(text);
    });
    input.addEventListener('keydown', e => {
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); form.requestSubmit(); }
    });

    // ---- Toolbar helpers ----
    function setPressed(btn, on) { if (btn) btn.setAttribute('aria-pressed', String(on)); }
    function updateLive() {
        if (!live) return;
        const voiceOn = $('voiceToggle') && $('voiceToggle').getAttribute('aria-pressed') === 'true';
        const camOn = $('camToggle') && $('camToggle').getAttribute('aria-pressed') === 'true';
        live.hidden = !(voiceOn || camOn || ($('voiceStatus') && $('voiceStatus').textContent) || ($('camStatus') && $('camStatus').textContent));
        if ($('voicePanel')) $('voicePanel').hidden = !voiceOn && !($('voiceStatus') && $('voiceStatus').textContent);
    }

    // Let voice.js add its transcripts to the same log and update the toolbar.
    MC.chat = { addBubble, showCrisis, history, setPressed, updateLive, demo: DEMO };

    // ---- Read replies aloud (same setting as the Aa menu) ----
    const speakToggle = $('speakToggle');
    if (speakToggle) {
        if (!('speechSynthesis' in window)) speakToggle.hidden = true;
        const syncSpeak = () => setPressed(speakToggle, readAloudOn());
        speakToggle.addEventListener('click', () => {
            const on = !readAloudOn();
            if (MC.setReadAloud) MC.setReadAloud(on);
            else document.documentElement.dataset.speak = on ? 'on' : '';
            syncSpeak();
            if (!on && 'speechSynthesis' in window) speechSynthesis.cancel();
            status.textContent = on ? 'Replies will be read aloud.' : 'Read aloud is off.';
        });
        syncSpeak();
        // The Aa menu can change it too.
        new MutationObserver(syncSpeak).observe(document.documentElement, { attributes: true, attributeFilter: ['data-speak'] });
    }

    // ---- Dictation into the text box (browser speech recognition, Chrome/Edge/Safari) ----
    const dictateBtn = $('dictateBtn');
    const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (dictateBtn && !Recognition) {
        dictateBtn.hidden = true;
    } else if (dictateBtn) {
        dictateBtn.addEventListener('click', () => {
            const rec = new Recognition();
            rec.lang = 'en-US';
            rec.interimResults = false;
            status.textContent = 'Listening...';
            rec.onresult = e => { input.value = (input.value + ' ' + e.results[0][0].transcript).trim(); input.focus(); };
            rec.onerror = e => { status.textContent = 'Dictation error: ' + e.error; };
            rec.onend = () => { if (status.textContent === 'Listening...') status.textContent = ''; };
            rec.start();
        });
    }

    // ---- Camera: optional expression check (opt-in, once a minute in text chat) ----
    const SNAPSHOT_INTERVAL_MS = 60000;
    const camToggle = $('camToggle');
    const video = $('webcam');
    const camStatus = $('camStatus');
    let stream = null, timer = null;

    // Returns a JPEG data URL of the current camera frame, or null if the camera is off.
    function grabFrame(width = 480, quality = 0.8) {
        if (!stream || !video.videoWidth) return null;
        const canvas = document.createElement('canvas');
        canvas.width = width;
        canvas.height = Math.round(width * video.videoHeight / video.videoWidth);
        canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height);
        return canvas.toDataURL('image/jpeg', quality);
    }
    // voice.js uses this to stream frames to the voice model.
    MC.camera = { grabFrame };

    async function snapshot() {
        const frame = grabFrame();
        if (!frame || DEMO) return;
        try {
            const res = await fetch('/api/emotion', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ image_data: frame, source: MC.voiceActive ? 'voice' : 'chat' }),
            });
            const data = await res.json();
            if (res.status === 429) {
                // Out of API quota: stop checking so we don't keep wasting requests.
                clearInterval(timer);
                timer = null;
                camStatus.textContent = 'Expression check paused: ' + data.error;
                return;
            }
            if (!res.ok) throw new Error(data.error);
            emotion = data.emotion;
            if (emotion && window.Aura) Aura.fromCamera(emotion);
            camStatus.textContent = emotion
                ? 'Camera on. Your expression looks: ' + emotion + (data.saved ? ' (saved to your account)' : '')
                : 'Camera on. No face found.';
        } catch (err) {
            camStatus.textContent = err.message || 'Expression check failed.';
        }
    }

    async function cameraOn() {
        try {
            stream = await navigator.mediaDevices.getUserMedia({ video: true });
        } catch (err) {
            camStatus.textContent = 'Camera unavailable: ' + err.message;
            updateLive();
            return;
        }
        video.srcObject = stream;
        video.hidden = false;
        setPressed(camToggle, true);
        camStatus.textContent = DEMO
            ? 'Camera on (demo: nothing is sent).'
            : 'Camera on. A snapshot goes to the AI about once a minute (every second in voice chat) to read your expression. Nothing is saved unless you turned that on.';
        if (!DEMO) {
            setTimeout(snapshot, 1500);
            timer = setInterval(snapshot, SNAPSHOT_INTERVAL_MS);
        }
        updateLive();
    }

    function cameraOff() {
        clearInterval(timer);
        timer = null;
        if (stream) stream.getTracks().forEach(t => t.stop());
        stream = null;
        video.hidden = true;
        emotion = null;
        setPressed(camToggle, false);
        camStatus.textContent = '';
        updateLive();
    }

    if (camToggle) {
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) camToggle.hidden = true;
        camToggle.addEventListener('click', () => (stream ? cameraOff() : cameraOn()));
    }
    window.addEventListener('hashchange', () => { if (stream && log.offsetParent === null) cameraOff(); });
})();
