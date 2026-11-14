// Calm Toolkit: breathing, grounding, thought record, before/after check-ins, soft noise.
(function () {
    // ---- Rating sliders show their value ----
    document.querySelectorAll('.rating input[type=range]').forEach(r => {
        const out = document.getElementById(r.id + '-out');
        const update = () => { out.textContent = r.value; r.setAttribute('aria-valuetext', r.value + ' out of 10'); };
        r.addEventListener('input', update);
        update();
    });

    // ---- Before/after check-ins ----
    function finishActivity(section) {
        const after = section.querySelector('.after');
        after.hidden = false;
        after.querySelector('input[type=range]').focus();
    }

    document.querySelectorAll('.tool[data-activity]').forEach(section => {
        const btn = section.querySelector('.save-checkin');
        if (!btn) return;
        btn.addEventListener('click', async () => {
            const activity = section.dataset.activity;
            const before = +document.getElementById(activity + '-before').value;
            const after = +document.getElementById(activity + '-after').value;
            if (window.Aura) Aura.fromStress(after);
            const result = section.querySelector('.result');
            const diff = after - before;
            let msg = diff < 0 ? `Your stress went down by ${-diff}. Nice work.`
                : diff === 0 ? 'About the same. That\'s okay - try another skill, or come back to this one later.'
                : `Your stress went up by ${diff}. That happens - maybe try a different skill, or talk it through in Chat.`;
            if (window.MC_SIGNED_IN) {
                try {
                    const res = await fetch('/api/checkins', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ activity, stress_before: before, stress_after: after }),
                    });
                    if (!res.ok) throw new Error((await res.json()).error);
                    msg += ' Saved to your progress.';
                    btn.disabled = true;
                } catch (err) {
                    msg += ' (Could not save: ' + err.message + ')';
                }
            }
            result.textContent = msg;
        });
    });

    // ---- Guided breathing ----
    const circle = document.getElementById('breathCircle');
    const cue = document.getElementById('breathCue');
    const startBtn = document.getElementById('breathStart');
    const stopBtn = document.getElementById('breathStop');
    const voice = document.getElementById('breathVoice');
    let breathTimer = null, running = false;

    function phase(label, seconds, scale) {
        return new Promise(resolve => {
            if (!running) return resolve();
            if (seconds <= 0) return resolve();
            if (voice.checked) MC.speak(label.split(' ')[0], { rate: 0.85 });
            circle.style.transitionDuration = MC.reduceMotion() ? '0s' : seconds + 's';
            circle.style.transform = `scale(${scale})`;
            let left = seconds;
            cue.textContent = `${label} ${left}`;
            circle.textContent = left;
            breathTimer = setInterval(() => {
                left -= 1;
                if (left <= 0 || !running) { clearInterval(breathTimer); resolve(); return; }
                circle.textContent = left;
            }, 1000);
        });
    }

    async function runBreathing() {
        const [inhale, hold1, exhale, hold2] = document.getElementById('breathPattern').value.split(',').map(Number);
        const rounds = +document.getElementById('breathRounds').value;
        running = true;
        startBtn.disabled = true; stopBtn.disabled = false;
        for (let i = 1; i <= rounds && running; i++) {
            await phase('Breathe in', inhale, 1.8);
            await phase('Hold', hold1, 1.8);
            await phase('Breathe out', exhale, 1);
            await phase('Hold', hold2, 1);
        }
        const completed = running;
        stopBreathing();
        if (completed) {
            cue.textContent = 'Well done. Notice how your body feels now.';
            if (voice.checked) MC.speak('Well done.');
            finishActivity(document.getElementById('breathing'));
        }
    }

    function stopBreathing() {
        running = false;
        clearInterval(breathTimer);
        circle.style.transitionDuration = '0.5s';
        circle.style.transform = 'scale(1)';
        circle.textContent = '';
        cue.textContent = 'Press start when you\'re ready.';
        startBtn.disabled = false; stopBtn.disabled = true;
    }

    startBtn.addEventListener('click', runBreathing);
    stopBtn.addEventListener('click', stopBreathing);

    // ---- 5-4-3-2-1 grounding (the boxes are built by grounding.js) ----
    const grounding = document.getElementById('grounding');
    grounding.addEventListener('grounding:done', () => {
        const after = grounding.querySelector('.after');
        if (after.hidden) finishActivity(grounding);
    });

    // ---- Thought record ----
    document.getElementById('trDone').addEventListener('click', () => finishActivity(document.getElementById('thought-record')));

    // ---- Soft noise (brown noise via Web Audio) ----
    const noiseBtn = document.getElementById('noiseToggle');
    const noiseVol = document.getElementById('noiseVolume');
    let audioCtx = null, gain = null, noiseNode = null;

    function startNoise() {
        audioCtx = new AudioContext();
        const len = audioCtx.sampleRate * 4;
        const buffer = audioCtx.createBuffer(1, len, audioCtx.sampleRate);
        const data = buffer.getChannelData(0);
        let last = 0;
        for (let i = 0; i < len; i++) {           // brown noise: integrated white noise
            last = (last + 0.02 * (Math.random() * 2 - 1)) / 1.02;
            data[i] = last * 3.5;
        }
        noiseNode = audioCtx.createBufferSource();
        noiseNode.buffer = buffer;
        noiseNode.loop = true;
        gain = audioCtx.createGain();
        gain.gain.value = +noiseVol.value;
        noiseNode.connect(gain).connect(audioCtx.destination);
        noiseNode.start();
    }

    noiseBtn.addEventListener('click', () => {
        const on = noiseBtn.getAttribute('aria-pressed') === 'true';
        if (on) { audioCtx.close(); audioCtx = null; }
        else startNoise();
        noiseBtn.setAttribute('aria-pressed', String(!on));
        noiseBtn.textContent = on ? 'Play soft noise' : 'Stop soft noise';
    });
    noiseVol.addEventListener('input', () => { if (gain) gain.gain.value = +noiseVol.value; });
})();
