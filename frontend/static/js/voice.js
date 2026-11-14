// Voice mode: streams the microphone to /ws/voice (relayed to Gemini Live) and plays the reply.
(function () {
    const startBtn = document.getElementById('voiceStart');
    const stopBtn = document.getElementById('voiceStop');
    const modelSel = document.getElementById('voiceModel');
    const thinkingRow = document.getElementById('thinkingRow');
    const thinkingSel = document.getElementById('thinkingLevel');
    const status = document.getElementById('voiceStatus');
    const level = document.getElementById('voiceLevel');

    modelSel.addEventListener('change', () => { thinkingRow.hidden = modelSel.value !== 'extended'; });

    let ws = null, micStream = null, recordCtx = null, playCtx = null, frameTimer = null;
    let playTime = 0, playing = [];
    let current = null;   // transcript bubble being filled: { who, el, text }

    function setStatus(text) { status.textContent = text; }

    // ---- Playback of 24 kHz PCM from Gemini ----
    function playPcm(arrayBuffer) {
        const int16 = new Int16Array(arrayBuffer);
        if (!int16.length) return;
        const buffer = playCtx.createBuffer(1, int16.length, 24000);
        const data = buffer.getChannelData(0);
        for (let i = 0; i < int16.length; i++) data[i] = int16[i] / 0x8000;
        const src = playCtx.createBufferSource();
        src.buffer = buffer;
        src.connect(playCtx.destination);
        playTime = Math.max(playTime, playCtx.currentTime + 0.05);
        src.start(playTime);
        playTime += buffer.duration;
        playing.push(src);
        src.onended = () => { playing = playing.filter(s => s !== src); };
    }

    function stopPlayback() {
        playing.forEach(s => { try { s.stop(); } catch (e) {} });
        playing = [];
        playTime = 0;
    }

    // ---- Transcripts into the shared chat log ----
    function transcript(who, text) {
        const chat = window.MC.chat;
        if (!chat) return;
        if (!current || current.who !== who) {
            finishBubble();
            current = { who, text: '', el: chat.addBubble(who === 'user' ? 'user' : 'model', '', { speakButton: false }) };
        }
        current.text += text;
        current.el.textContent = current.text;
        current.el.parentElement.scrollTop = current.el.parentElement.scrollHeight;
    }

    function finishBubble() {
        if (current && current.text.trim() && window.MC.chat) {
            window.MC.chat.history.push({ role: current.who === 'user' ? 'user' : 'model', text: current.text.trim() });
        }
        current = null;
    }

    // ---- Start / stop ----
    async function start() {
        startBtn.disabled = true;
        setStatus('Asking for microphone access...');
        try {
            micStream = await navigator.mediaDevices.getUserMedia({
                audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
            });
        } catch (err) {
            setStatus('Microphone unavailable: ' + err.message);
            startBtn.disabled = false;
            return;
        }

        playCtx = new AudioContext();
        recordCtx = new AudioContext();
        await recordCtx.audioWorklet.addModule('/static/js/pcm-recorder-worklet.js');
        const source = recordCtx.createMediaStreamSource(micStream);
        const recorder = new AudioWorkletNode(recordCtx, 'pcm-recorder');
        source.connect(recorder);

        const params = new URLSearchParams({ mode: modelSel.value, thinking: thinkingSel.value });
        const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
        ws = new WebSocket(`${proto}//${location.host}/ws/voice?${params}`);
        ws.binaryType = 'arraybuffer';
        setStatus('Connecting to Gemini...');

        recorder.port.onmessage = e => {
            if (e.data.level !== undefined) level.style.width = Math.min(100, e.data.level * 400) + '%';
            if (e.data.pcm && ws && ws.readyState === WebSocket.OPEN) ws.send(e.data.pcm);
        };

        ws.onmessage = e => {
            if (typeof e.data !== 'string') { playPcm(e.data); return; }
            const msg = JSON.parse(e.data);
            if (msg.type === 'ready') {
                window.MC.voiceActive = true;
                setStatus('Listening - go ahead and talk.');
                stopBtn.disabled = false;
                // While the camera is on, Gemini Live sees ~1 frame per second to read your expression.
                frameTimer = setInterval(() => {
                    const frame = window.MC.camera && window.MC.camera.grabFrame(320, 0.7);
                    if (frame && ws && ws.readyState === WebSocket.OPEN) {
                        ws.send(JSON.stringify({ type: 'frame', data: frame.split(',')[1] }));
                    }
                }, 1000);
            }
            else if (msg.type === 'transcript') transcript(msg.who, msg.text);
            else if (msg.type === 'turn_complete') { finishBubble(); setStatus('Listening...'); }
            else if (msg.type === 'interrupted') { stopPlayback(); finishBubble(); }
            else if (msg.type === 'crisis') window.MC.chat && window.MC.chat.showCrisis();
            else if (msg.type === 'error') setStatus('Voice error: ' + msg.message);
        };
        ws.onclose = () => { cleanup(); if (!status.textContent.startsWith('Voice error')) setStatus('Voice chat ended.'); };
        ws.onerror = () => setStatus('Voice error: could not connect to the server.');
    }

    function cleanup() {
        clearInterval(frameTimer);
        frameTimer = null;
        window.MC.voiceActive = false;
        finishBubble();
        stopPlayback();
        if (micStream) micStream.getTracks().forEach(t => t.stop());
        if (recordCtx) recordCtx.close();
        if (playCtx) playCtx.close();
        micStream = recordCtx = playCtx = null;
        level.style.width = '0';
        startBtn.disabled = false;
        stopBtn.disabled = true;
    }

    function stop() {
        if (ws && ws.readyState === WebSocket.OPEN) { ws.send(JSON.stringify({ type: 'stop' })); ws.close(); }
        cleanup();
    }

    startBtn.addEventListener('click', () => start().catch(err => { setStatus('Voice error: ' + err.message); cleanup(); }));
    stopBtn.addEventListener('click', stop);
    window.addEventListener('beforeunload', stop);
})();
