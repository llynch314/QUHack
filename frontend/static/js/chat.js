// Text chat with Gemini, browser dictation, and the optional webcam expression check.
(function () {
    const log = document.getElementById('chatLog');
    const form = document.getElementById('chatForm');
    const input = document.getElementById('chatInput');
    const sendBtn = document.getElementById('sendBtn');
    const status = document.getElementById('chatStatus');
    const crisisPanel = document.getElementById('crisisPanel');

    // Conversation history lives only in this page (not stored on the server).
    const history = [];
    let emotion = null;

    function addBubble(role, text, { speakButton = true } = {}) {
        const div = document.createElement('div');
        div.className = 'bubble ' + role;
        div.textContent = text;
        if (role === 'model' && speakButton && 'speechSynthesis' in window) {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'btn speak-btn';
            btn.textContent = '🔊 Read aloud';
            btn.addEventListener('click', () => MC.speak(text));
            div.appendChild(document.createElement('br'));
            div.appendChild(btn);
        }
        log.appendChild(div);
        log.scrollTop = log.scrollHeight;
        return div;
    }

    function showCrisis() {
        if (crisisPanel.hidden) {
            crisisPanel.hidden = false;
            crisisPanel.scrollIntoView({ behavior: MC.reduceMotion() ? 'auto' : 'smooth', block: 'nearest' });
        }
    }

    async function send(text) {
        history.push({ role: 'user', text });
        addBubble('user', text);
        sendBtn.disabled = true;
        status.textContent = 'Mind Connect is thinking...';
        try {
            const res = await fetch('/api/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ messages: history, emotion }),
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.error || 'Something went wrong.');
            history.push({ role: 'model', text: data.reply });
            addBubble('model', data.reply);
            if (data.crisis) showCrisis();
            if (MC.readAloudOn()) MC.speak(data.reply);
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

    // Let voice.js add its transcripts to the same log.
    window.MC.chat = { addBubble, showCrisis, history };

    // ---- Dictation (browser speech recognition, Chrome/Edge/Safari) ----
    const dictateBtn = document.getElementById('dictateBtn');
    const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!Recognition) {
        dictateBtn.hidden = true;
    } else {
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

    // ---- Optional webcam expression check (opt-in, once a minute) ----
    const SNAPSHOT_INTERVAL_MS = 60000;
    const camToggle = document.getElementById('camToggle');
    const video = document.getElementById('webcam');
    const camStatus = document.getElementById('camStatus');
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
    // voice.js uses this to stream frames to Gemini Live.
    window.MC.camera = { grabFrame };

    async function snapshot() {
        const frame = grabFrame();
        if (!frame) return;
        try {
            const res = await fetch('/api/emotion', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ image_data: frame, source: window.MC.voiceActive ? 'voice' : 'chat' }),
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
            camStatus.textContent = emotion
                ? 'Your expression looks: ' + emotion + (data.saved ? ' (saved to My Progress)' : '')
                : 'No face found.';
        } catch (err) {
            camStatus.textContent = err.message || 'Expression check failed.';
        }
    }

    camToggle.addEventListener('change', async () => {
        if (camToggle.checked) {
            try {
                stream = await navigator.mediaDevices.getUserMedia({ video: true });
                video.srcObject = stream;
                video.hidden = false;
                camStatus.textContent = 'Camera on.';
                // Each snapshot is one Gemini request, so check once a minute
                // (plus one shortly after turning on) to stay within the quota.
                setTimeout(snapshot, 1500);
                timer = setInterval(snapshot, SNAPSHOT_INTERVAL_MS);
            } catch (err) {
                camToggle.checked = false;
                camStatus.textContent = 'Camera unavailable: ' + err.message;
            }
        } else {
            clearInterval(timer);
            if (stream) stream.getTracks().forEach(t => t.stop());
            stream = null;
            video.hidden = true;
            emotion = null;
            camStatus.textContent = 'Camera off.';
        }
    });
})();
