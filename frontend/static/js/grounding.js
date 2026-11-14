// 5-4-3-2-1 grounding: a box for each sense where the user types what they notice.
// Renders into every [data-grounding] element. Nothing typed here is saved or sent anywhere.
// When the user finishes, the mount fires a "grounding:done" event (the toolkit then asks
// how they feel afterwards).
(function () {
    const SENSES = [
        { n: 5, icon: '👀', title: 'things I can see', hint: 'e.g. a blue mug' },
        { n: 4, icon: '✋', title: 'things I can feel or touch', hint: 'e.g. my feet on the floor' },
        { n: 3, icon: '👂', title: 'things I can hear', hint: 'e.g. a fan humming' },
        { n: 2, icon: '👃', title: 'things I can smell', hint: 'e.g. coffee' },
        { n: 1, icon: '👅', title: 'thing I can taste (or one kind thing about myself)', hint: 'e.g. mint, or "I\'m trying"' },
    ];
    const TOTAL = SENSES.reduce((sum, s) => sum + s.n, 0);
    let counter = 0;

    function speak(text) { if (window.MC && MC.readAloudOn && MC.readAloudOn()) MC.speak(text); }

    function render(mount) {
        const uid = 'g' + (++counter);
        mount.classList.add('stack');
        mount.innerHTML = '';

        const intro = document.createElement('p');
        intro.className = 'muted';
        intro.textContent = 'Slow down and notice what\'s around you, one sense at a time. Type as much or as little as you like. ' +
            'What you type stays on this screen and isn\'t saved.';

        const senses = document.createElement('div');
        senses.className = 'ground-senses';
        const groups = SENSES.map((sense, si) => {
            const fs = document.createElement('fieldset');
            fs.className = 'ground-sense';
            const legend = document.createElement('legend');
            legend.innerHTML = `<span aria-hidden="true">${sense.icon}</span> ${sense.n} ${sense.title}<span class="ground-count"></span>`;
            const inputs = document.createElement('div');
            inputs.className = 'ground-inputs';
            for (let i = 1; i <= sense.n; i++) {
                const id = `${uid}-${si}-${i}`;
                const label = document.createElement('label');
                label.className = 'sr-only';
                label.htmlFor = id;
                label.textContent = `${sense.title}, ${i} of ${sense.n}`;
                const input = document.createElement('input');
                input.type = 'text';
                input.id = id;
                input.autocomplete = 'off';
                input.maxLength = 120;
                input.placeholder = i === 1 ? sense.hint : `${i}.`;
                inputs.append(label, input);
            }
            // Read the prompt aloud the first time someone moves into this sense (if read-aloud is on).
            fs.addEventListener('focusin', e => { if (!fs.contains(e.relatedTarget)) speak(`${sense.n} ${sense.title}`); });
            fs.append(legend, inputs);
            senses.appendChild(fs);
            return { fs, sense, count: legend.querySelector('.ground-count') };
        });

        const progressWrap = document.createElement('div');
        progressWrap.className = 'progress';
        progressWrap.setAttribute('aria-hidden', 'true');
        const bar = document.createElement('span');
        progressWrap.appendChild(bar);
        const status = document.createElement('p');
        status.className = 'status';
        status.setAttribute('role', 'status');

        const row = document.createElement('div');
        row.className = 'row';
        const done = document.createElement('button');
        done.type = 'button';
        done.className = 'btn btn-primary';
        done.textContent = "I'm done";
        const clear = document.createElement('button');
        clear.type = 'button';
        clear.className = 'btn';
        clear.textContent = 'Clear and start again';
        row.append(done, clear);

        function update() {
            let filled = 0;
            groups.forEach(({ fs, sense, count }) => {
                const n = [...fs.querySelectorAll('input')].filter(i => i.value.trim()).length;
                filled += n;
                count.textContent = `(${n} of ${sense.n})`;
                fs.classList.toggle('done', n === sense.n);
            });
            bar.style.width = (filled / TOTAL * 100) + '%';
            return filled;
        }

        senses.addEventListener('input', update);
        done.addEventListener('click', () => {
            const filled = update();
            const msg = filled === 0
                ? 'Even just reading through the senses can help. Take one slow breath.'
                : `You noticed ${filled} thing${filled === 1 ? '' : 's'}. Take a slow breath and notice how your body feels now.`;
            status.textContent = msg;
            speak(msg);
            mount.dispatchEvent(new CustomEvent('grounding:done', { bubbles: true, detail: { filled } }));
        });
        clear.addEventListener('click', () => {
            senses.querySelectorAll('input').forEach(i => { i.value = ''; });
            status.textContent = '';
            update();
            senses.querySelector('input').focus();
        });

        mount.append(intro, progressWrap, senses, row, status);
        update();
    }

    function init() { document.querySelectorAll('[data-grounding]').forEach(render); }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})();
