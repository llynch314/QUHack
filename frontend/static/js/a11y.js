// Accessibility menu ("Aa" button in the header) and shared helpers (MC.speak, MC.readAloudOn...).
// One copy for every page: the panel is built here and added to the header's .bar-right.
// Settings are saved per browser in localStorage and applied as data-* attributes on <html>
// (a small inline script in each page applies them before paint, so nothing flashes).
(function () {
    const KEY = 'mc-a11y';
    const root = document.documentElement;

    // [setting key, legend, [[value, label, extra button style], ...], optional help text]
    // The first option ('' value) is the default.
    const GROUPS = [
        ['size', 'Text size', [['', 'A'], ['lg', 'A', 'font-size:1.15em'], ['xl', 'A', 'font-size:1.3em'], ['xxl', 'A', 'font-size:1.45em']]],
        ['font', 'Font', [['', 'Default'], ['readable', 'Dyslexia-friendly'], ['hyperlegible', 'Low vision']],
            'Dyslexia-friendly uses Lexend with extra letter, word and line spacing. Low vision uses Atkinson Hyperlegible.'],
        ['guide', 'Reading guide', [['', 'Off'], ['on', 'On']],
            'A soft band follows your pointer so it\'s easier to keep your place while reading.'],
        ['theme', 'Contrast', [['', 'Auto'], ['light', 'Light'], ['dark', 'Dark'], ['contrast', 'High contrast']]],
        ['palette', 'Colors', [['', 'Sage'], ['ocean', 'Ocean'], ['lavender', 'Lavender'], ['sunrise', 'Sunrise'], ['gray', 'Grayscale']],
            'Color themes apply in Light mode.'],
        ['speak', 'Text-to-speech', [['', 'Off'], ['on', 'Read replies aloud']]],
        ['rate', 'Speaking speed', [['slow', 'Slower'], ['', 'Normal'], ['fast', 'Faster']]],
        ['links', 'Links', [['', 'Default'], ['underline', 'Always underline']]],
        ['targets', 'Buttons', [['', 'Default'], ['big', 'Bigger buttons']]],
        ['focus', 'Keyboard focus', [['', 'Default'], ['strong', 'Extra-visible']],
            'Tab moves between buttons and links. Press Alt + A to open this menu, Esc to close it.'],
        ['motion', 'Motion', [['', 'Auto'], ['reduce', 'Reduce motion']]],
    ];

    function load() {
        try { return JSON.parse(localStorage.getItem(KEY) || '{}'); } catch (e) { return {}; }
    }
    function save() {
        try { localStorage.setItem(KEY, JSON.stringify(settings)); } catch (e) { /* private mode */ }
    }
    const settings = load();

    function apply(key, value) {
        if (value) { settings[key] = value; root.dataset[key] = value; }
        else { delete settings[key]; delete root.dataset[key]; }
        save();
        sync();
        if (key === 'guide') guide.update();
    }

    // ---- Build the panel ----
    function el(tag, attrs, text) {
        const node = document.createElement(tag);
        Object.entries(attrs || {}).forEach(([k, v]) => node.setAttribute(k, v));
        if (text) node.textContent = text;
        return node;
    }

    function buildMenu() {
        const details = el('details', { class: 'a11y-menu' });
        const summary = el('summary', { 'aria-label': 'Accessibility settings', title: 'Accessibility (Alt + A)' }, 'Aa');
        const panel = el('div', { class: 'a11y-panel', role: 'group', 'aria-label': 'Accessibility settings' });
        panel.appendChild(el('h2', { class: 'a11y-title' }, 'Accessibility'));

        GROUPS.forEach(([key, legend, options, help]) => {
            const fs = el('fieldset');
            fs.appendChild(el('legend', {}, legend));
            const seg = el('div', { class: 'seg', 'data-setting': key });
            options.forEach(([value, label, style]) => {
                const b = el('button', { type: 'button', 'data-value': value }, label);
                if (style) b.setAttribute('style', style);
                if (key === 'size') b.setAttribute('aria-label', ['Default', 'Large', 'Larger', 'Largest'][options.findIndex(o => o[0] === value)] + ' text');
                seg.appendChild(b);
            });
            fs.appendChild(seg);
            if (help) fs.appendChild(el('p', { class: 'a11y-help' }, help));
            if (key === 'speak') {
                const row = el('div', { class: 'seg', style: 'margin-top:.4rem' });
                const read = el('button', { type: 'button', id: 'a11yReadPage' }, '🔊 Read this page');
                const stop = el('button', { type: 'button', id: 'a11yStopReading' }, 'Stop');
                read.addEventListener('click', readPage);
                stop.addEventListener('click', () => 'speechSynthesis' in window && speechSynthesis.cancel());
                row.append(read, stop);
                fs.appendChild(row);
                fs.appendChild(el('p', { class: 'a11y-help' }, 'Select some text first to hear just that part.'));
            }
            panel.appendChild(fs);
        });

        const reset = el('button', { type: 'button', class: 'a11y-reset' }, 'Reset all');
        reset.addEventListener('click', () => {
            GROUPS.forEach(([key]) => { delete settings[key]; delete root.dataset[key]; });
            save(); sync(); guide.update();
        });
        panel.appendChild(reset);
        details.append(summary, panel);
        return details;
    }

    function sync() {
        document.querySelectorAll('.a11y-panel .seg[data-setting]').forEach(group => {
            const current = settings[group.dataset.setting] || '';
            group.querySelectorAll('button').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.value === current)));
        });
    }

    let menu = document.querySelector('.a11y-menu');
    if (!menu) {
        const slot = document.querySelector('.bar-right') || document.querySelector('.bar');
        if (slot) { menu = buildMenu(); slot.appendChild(menu); }
    }
    if (menu) {
        menu.querySelectorAll('.seg[data-setting]').forEach(group => {
            group.addEventListener('click', e => {
                const btn = e.target.closest('button');
                if (btn) apply(group.dataset.setting, btn.dataset.value);
            });
        });
        sync();
        // Close with Escape or a click outside; open with Alt + A.
        document.addEventListener('keydown', e => {
            if (e.key === 'Escape' && menu.open) { menu.open = false; menu.querySelector('summary').focus(); }
            if (e.altKey && (e.key === 'a' || e.key === 'A')) {
                e.preventDefault();
                menu.open = !menu.open;
                if (menu.open) (menu.querySelector('.a11y-panel button') || menu).focus();
            }
        });
        document.addEventListener('click', e => { if (menu.open && !menu.contains(e.target)) menu.open = false; });
    }

    // ---- Text-to-speech ----
    const RATES = { slow: 0.75, fast: 1.15 };

    function speak(text, opts = {}) {
        if (!('speechSynthesis' in window) || !text) return;
        if (opts.interrupt !== false) speechSynthesis.cancel();
        const u = new SpeechSynthesisUtterance(text);
        u.rate = opts.rate || RATES[root.dataset.rate] || 0.92;   // a little slower than default feels calmer
        speechSynthesis.speak(u);
    }

    function readPage() {
        const selected = String(window.getSelection ? window.getSelection() : '').trim();
        if (selected) return speak(selected);
        const main = document.getElementById('main') || document.body;
        // Only what's visible: skip hidden tabs, scripts and screen-reader-only labels.
        const parts = [];
        const walker = document.createTreeWalker(main, NodeFilter.SHOW_TEXT, {
            acceptNode(node) {
                const p = node.parentElement;
                if (!node.textContent.trim() || !p || p.closest('script, style, .sr-only, [hidden], [aria-hidden="true"]')) return NodeFilter.FILTER_REJECT;
                return p.offsetParent === null && getComputedStyle(p).position !== 'fixed' ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT;
            },
        });
        while (walker.nextNode()) parts.push(walker.currentNode.textContent.trim());
        speak(parts.join('. ').replace(/\.\s*\./g, '.'));
    }

    // ---- Reading guide (dyslexia aid): a soft band that follows the pointer ----
    const guide = (function () {
        let band = null;
        const move = e => { band.style.top = (e.clientY - band.offsetHeight / 2) + 'px'; };
        return {
            update() {
                const on = root.dataset.guide === 'on';
                if (on && !band) {
                    band = el('div', { class: 'reading-guide', 'aria-hidden': 'true' });
                    document.body.appendChild(band);
                    document.addEventListener('mousemove', move);
                } else if (!on && band) {
                    document.removeEventListener('mousemove', move);
                    band.remove();
                    band = null;
                }
            },
        };
    })();
    guide.update();

    // ---- Shared helpers for other scripts ----
    window.MC = window.MC || {};
    window.MC.reduceMotion = () =>
        root.dataset.motion === 'reduce' || window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    window.MC.readAloudOn = () => root.dataset.speak === 'on';
    window.MC.setReadAloud = on => apply('speak', on ? 'on' : '');
    window.MC.speak = speak;
    window.MC.readPage = readPage;
})();
