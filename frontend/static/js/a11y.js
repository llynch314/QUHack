// Accessibility settings (text size, font, colors, motion, read aloud).
// Saved per browser in localStorage and applied as data-* attributes on <html>.
(function () {
    const KEY = 'mc-a11y';
    const root = document.documentElement;

    function load() {
        try { return JSON.parse(localStorage.getItem(KEY) || '{}'); } catch (e) { return {}; }
    }
    function save(settings) {
        try { localStorage.setItem(KEY, JSON.stringify(settings)); } catch (e) { /* private mode */ }
    }

    const settings = load();

    function sync() {
        document.querySelectorAll('.seg[data-setting]').forEach(group => {
            const current = settings[group.dataset.setting] || '';
            group.querySelectorAll('button').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.value === current)));
        });
    }

    document.querySelectorAll('.seg[data-setting]').forEach(group => {
        group.addEventListener('click', e => {
            const btn = e.target.closest('button');
            if (!btn) return;
            const key = group.dataset.setting;
            if (btn.dataset.value) { settings[key] = btn.dataset.value; root.dataset[key] = btn.dataset.value; }
            else { delete settings[key]; delete root.dataset[key]; }
            save(settings);
            sync();
        });
    });
    sync();

    // Shared helpers for other scripts.
    window.MC = window.MC || {};
    window.MC.reduceMotion = () =>
        root.dataset.motion === 'reduce' || window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    window.MC.readAloudOn = () => root.dataset.speak === 'on';
    window.MC.speak = (text, opts = {}) => {
        if (!('speechSynthesis' in window) || !text) return;
        if (opts.interrupt !== false) speechSynthesis.cancel();
        const u = new SpeechSynthesisUtterance(text);
        u.rate = opts.rate || 0.92;   // a little slower than default feels calmer
        speechSynthesis.speak(u);
    };
})();
