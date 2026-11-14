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

    // ---- 5-4-3-2-1 grounding ----
    const steps = [
        { n: 5, prompt: 'Name 5 things you can see' },
        { n: 4, prompt: 'Name 4 things you can feel or touch' },
        { n: 3, prompt: 'Name 3 things you can hear' },
        { n: 2, prompt: 'Name 2 things you can smell' },
        { n: 1, prompt: 'Name 1 thing you can taste, or one kind thing about yourself' },
    ];
    let step = 0;
    const gSteps = document.getElementById('groundSteps');
    const gPrompt = document.getElementById('groundPrompt');
    const gInputs = document.getElementById('groundInputs');
    const gProgress = document.getElementById('groundProgress');
    const gNext = document.getElementById('groundNext');
    const gBack = document.getElementById('groundBack');

    function renderStep() {
        const s = steps[step];
        gPrompt.textContent = `${s.prompt} (${step + 1} of ${steps.length})`;
        gInputs.innerHTML = '';
        for (let i = 1; i <= s.n; i++) {
            const id = `ground-${step}-${i}`;
            const wrap = document.createElement('div');
            wrap.innerHTML = `<label for="${id}" class="sr-only">${s.prompt}, item ${i}</label><input type="text" id="${id}" placeholder="${i}." autocomplete="off">`;
            gInputs.appendChild(wrap);
        }
        gProgress.style.width = (step / steps.length * 100) + '%';
        gBack.disabled = step === 0;
        gNext.textContent = step === steps.length - 1 ? 'Finish' : 'Next';
        gPrompt.focus();
        if (MC.readAloudOn()) MC.speak(s.prompt);
    }

    document.getElementById('groundStart').addEventListener('click', () => {
        step = 0;
        gSteps.hidden = false;
        renderStep();
    });
    gBack.addEventListener('click', () => { if (step > 0) { step--; renderStep(); } });
    gNext.addEventListener('click', () => {
        if (step < steps.length - 1) { step++; renderStep(); return; }
        gProgress.style.width = '100%';
        gSteps.hidden = true;
        finishActivity(document.getElementById('grounding'));
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
