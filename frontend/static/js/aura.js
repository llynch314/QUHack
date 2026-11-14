// The mood aura: a soft glowing gradient around the edge of the screen (below the top bar)
// whose colors show how the user is feeling. It stays on screen while they scroll.
//
// Where the mood comes from (newest wins, with two exceptions noted below):
//   - the mood picker (the round button in the bottom-right corner), or the dashboard color dots
//   - what they type in chat (the server guesses a mood: /api/chat returns `mood`)
//   - stress check-ins in the Calm Toolkit (0 calm ... 10 very stressed)
//   - the optional camera expression check (it never overrides a mood they picked in the
//     last 15 minutes, and "neutral" never replaces a real feeling)
//
// A session lasts while the tab is open (it resets after 2 hours idle). At the end of a
// session ("See my session aura", or signing out) the aura turns into a timeline of
// every mood felt, running clockwise from the top-left corner, with a short summary.
// The session is kept in this browser tab only (sessionStorage), never sent anywhere.
//
// Any element with data-aura-oval (the big oval on the home page and the dashboard) shows the
// main mood: the current one, or the most-felt one once a session has ended.
//
// Other scripts can call:  Aura.setMood('calm', 'chat'),  Aura.fromStress(7),
//                          Aura.fromCamera('happy'),  Aura.endSession()
(function () {
  'use strict';
  if (window.Aura) return;

  // ---------- The moods ----------
  // family = the dashboard color it belongs to (saved to Mood history for patients).
  // colors = the gradient. pace = seconds per gentle "breath" of the glow. size = glow width in px.
  // Strong feelings glow wider but never faster: the aura breathes slowly to help calm, not to alarm.
  var MOODS = [
    { id: 'peaceful',    label: 'Peaceful',    family: 'Green',  colors: ['#A8D5BA', '#CFE8D5', '#8CC7C0'], pace: 12, size: 34, note: 'Still and at ease.' },
    { id: 'calm',        label: 'Calm',        family: 'Green',  colors: ['#8FB08A', '#7FC8B8', '#B7D8A8'], pace: 10, size: 36, note: 'Steady. Everything feels okay.' },
    { id: 'content',     label: 'Content',     family: 'Green',  colors: ['#9CC58F', '#D8E3A1', '#8FB08A'], pace: 10, size: 36, note: 'Things are good enough right now.' },
    { id: 'grateful',    label: 'Grateful',    family: 'Green',  colors: ['#F2B5A0', '#F7D488', '#9CC58F'], pace: 9,  size: 40, note: 'Thankful for something or someone.' },

    { id: 'happy',       label: 'Happy',       family: 'Yellow', colors: ['#E8C24A', '#F4A259', '#F7E07A'], pace: 8,  size: 44, note: 'Bright and full of energy.' },
    { id: 'excited',     label: 'Excited',     family: 'Yellow', colors: ['#F4A259', '#F06C9B', '#F7E07A'], pace: 7,  size: 48, note: 'Buzzing about something.' },
    { id: 'hopeful',     label: 'Hopeful',     family: 'Yellow', colors: ['#F7D488', '#9FD3E6', '#F2B5A0'], pace: 9,  size: 40, note: 'Things could get better.' },
    { id: 'loved',       label: 'Loved',       family: 'Yellow', colors: ['#F28FB0', '#F7B2C8', '#E8C24A'], pace: 9,  size: 42, note: 'Cared for and supported.' },

    { id: 'neutral',     label: 'Neutral',     family: null,     colors: ['#B4AACB', '#A498C2', '#CBC2DD'], pace: 11, size: 32, note: 'Not much either way.' },
    { id: 'thoughtful',  label: 'Thoughtful',  family: 'Purple', colors: ['#A58BC0', '#C7B3DD', '#7F9FC4'], pace: 11, size: 34, note: 'Your mind is busy with big ideas.' },
    { id: 'confused',    label: 'Confused',    family: 'Purple', colors: ['#B49FD0', '#E0C3E8', '#9AA7C7'], pace: 10, size: 36, note: 'Not sure what to think or do.' },

    { id: 'tired',       label: 'Tired',       family: 'Blue',   colors: ['#9AA7C7', '#B9C2D9', '#7F9FC4'], pace: 13, size: 30, note: 'Low on energy. Rest is okay.' },
    { id: 'sad',         label: 'Sad',         family: 'Blue',   colors: ['#7F9FC4', '#5C7EB0', '#A4B8D8'], pace: 12, size: 40, note: 'Quiet or down. Go gently.' },
    { id: 'lonely',      label: 'Lonely',      family: 'Blue',   colors: ['#6C7BB8', '#8E9BD0', '#4E5D99'], pace: 12, size: 40, note: 'Wishing someone was there.' },
    { id: 'numb',        label: 'Numb',        family: 'Blue',   colors: ['#A9A5B5', '#C8C4D2', '#8C8799'], pace: 14, size: 28, note: 'Hard to feel much at all.' },

    { id: 'anxious',     label: 'Anxious',     family: 'Red',    colors: ['#E8B04A', '#D9905A', '#F2CE7A'], pace: 10, size: 46, note: 'Worried or on edge.' },
    { id: 'stressed',    label: 'Stressed',    family: 'Red',    colors: ['#E08A4F', '#D4705F', '#F2B36B'], pace: 10, size: 48, note: 'Under pressure.' },
    { id: 'frustrated',  label: 'Frustrated',  family: 'Red',    colors: ['#D97B4F', '#C9604D', '#E8A05A'], pace: 10, size: 48, note: 'Blocked or annoyed.' },
    { id: 'overwhelmed', label: 'Overwhelmed', family: 'Red',    colors: ['#C0569A', '#D4705F', '#8E5BB5'], pace: 10, size: 54, note: 'Too much at once.' },
    { id: 'angry',       label: 'Angry',       family: 'Red',    colors: ['#D4705F', '#B8463C', '#E8875F'], pace: 10, size: 54, note: 'Mad about something.' },
    { id: 'scared',      label: 'Scared',      family: 'Red',    colors: ['#8E5BB5', '#C0569A', '#5C4A99'], pace: 10, size: 50, note: 'Afraid something bad will happen.' },
    { id: 'panic',       label: 'Panicking',   family: 'Red',    colors: ['#E0473C', '#FF8A65', '#F06C9B'], pace: 10, size: 60, note: 'Breathe with the glow: in as it grows, out as it fades.' },
    { id: 'hurting',     label: 'Hurting',     family: 'Red',    colors: ['#B8463C', '#8E5BB5', '#C0569A'], pace: 12, size: 56, note: "You don't have to go through this alone." }
  ];
  var BY_ID = {};
  MOODS.forEach(function (m) { BY_ID[m.id] = m; });

  var GROUPS = [
    { title: 'Calm', ids: ['peaceful', 'calm', 'content', 'grateful'] },
    { title: 'Bright', ids: ['happy', 'excited', 'hopeful', 'loved'] },
    { title: 'In between', ids: ['neutral', 'thoughtful', 'confused'] },
    { title: 'Low', ids: ['tired', 'sad', 'lonely', 'numb'] },
    { title: 'Intense', ids: ['anxious', 'stressed', 'frustrated', 'overwhelmed', 'angry', 'scared', 'panic', 'hurting'] }
  ];
  var FAMILY_DEFAULT = { Yellow: 'happy', Green: 'calm', Blue: 'sad', Red: 'stressed', Purple: 'thoughtful' };
  var CAMERA = { angry: 'angry', disgust: 'frustrated', fear: 'scared', happy: 'happy', sad: 'sad', surprise: 'excited', neutral: 'neutral' };
  var SOURCE_TEXT = { picked: 'you picked it', chat: 'from your chat', checkin: 'from your check-in',
                      camera: 'from your camera', start: 'starting point' };

  var KEY = 'attune-aura-session';     // sessionStorage: this tab only
  var HIDE_KEY = 'attune-aura-hidden'; // localStorage: remembered preference
  var IDLE_RESET = 2 * 60 * 60 * 1000;
  var PICK_HOLD = 15 * 60 * 1000;

  // ---------- Session state ----------
  function now() { return Date.now(); }
  function newSession() { var t = now(); return { started: t, last: t, ended: null, entries: [{ m: 'neutral', s: 'start', t: t }] }; }
  function load() {
    try {
      var s = JSON.parse(sessionStorage.getItem(KEY));
      if (s && s.entries && s.entries.length && now() - s.last < IDLE_RESET) return s;
    } catch (e) { /* storage blocked */ }
    return newSession();
  }
  function save() { try { sessionStorage.setItem(KEY, JSON.stringify(session)); } catch (e) { /* storage blocked */ } }
  var session = load();
  function current() { return session.entries[session.entries.length - 1]; }
  function hiddenPref() { try { return localStorage.getItem(HIDE_KEY) === '1'; } catch (e) { return false; } }

  // ---------- Building the page elements ----------
  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === 'text') node.textContent = attrs[k];
      else if (k.slice(0, 2) === 'on') node.addEventListener(k.slice(2), attrs[k]);
      else node.setAttribute(k, attrs[k]);
    });
    (children || []).forEach(function (c) { if (c) node.append(c); });
    return node;
  }
  function swatch(m) {
    var s = el('span', { class: 'aura-swatch', 'aria-hidden': 'true' });
    s.style.background = 'conic-gradient(' + m.colors.concat(m.colors[0]).join(',') + ')';
    return s;
  }

  var frame, live, story, chip, chipLabel, panel, panelStatus, panelNote, liveRegion, summary;

  function build() {
    live = el('div', { class: 'aura-layer aura-live' }, [el('div', { class: 'aura-fill' })]);
    story = el('div', { class: 'aura-layer aura-story' }, [el('div', { class: 'aura-fill' })]);
    frame = el('div', { class: 'aura', 'aria-hidden': 'true' }, [live, story]);

    chipLabel = el('span', { class: 'aura-chip-label' });
    chip = el('button', { type: 'button', class: 'aura-chip', 'aria-haspopup': 'dialog', 'aria-expanded': 'false',
                          'aria-controls': 'auraPanel', onclick: function () { togglePanel(); } },
              [el('span', { class: 'aura-chip-dot', 'aria-hidden': 'true' }), chipLabel]);

    var groups = GROUPS.map(function (g) {
      return el('fieldset', { class: 'aura-group' }, [
        el('legend', { text: g.title }),
        el('div', { class: 'aura-moods' }, g.ids.map(function (id) {
          var m = BY_ID[id];
          return el('button', { type: 'button', class: 'aura-mood', 'data-mood': id, 'aria-pressed': 'false',
                                title: m.note, onclick: function () { pick(id); } }, [swatch(m), el('span', { text: m.label })]);
        }))
      ]);
    });
    panelStatus = el('p', { class: 'aura-status' });
    panelNote = el('p', { class: 'aura-note' });
    var hideBox = el('input', { type: 'checkbox', id: 'auraHide' });
    hideBox.checked = hiddenPref();
    hideBox.addEventListener('change', function () {
      try { localStorage.setItem(HIDE_KEY, hideBox.checked ? '1' : '0'); } catch (e) { /* ignore */ }
      render();
    });
    panel = el('div', { class: 'aura-panel', id: 'auraPanel', role: 'dialog', 'aria-labelledby': 'auraPanelTitle', hidden: '' }, [
      el('div', { class: 'aura-panel-head' }, [
        el('h2', { id: 'auraPanelTitle', text: 'How are you feeling?' }),
        el('button', { type: 'button', class: 'aura-close', 'aria-label': 'Close', onclick: function () { closePanel(true); } }, [document.createTextNode('×')])
      ]),
      panelStatus, panelNote
    ].concat(groups).concat([
      el('div', { class: 'aura-panel-foot' }, [
        el('button', { type: 'button', class: 'btn btn-primary', onclick: function () { closePanel(false); endSession(); } },
           [document.createTextNode('See my session aura')]),
        el('label', { class: 'aura-hide' }, [hideBox, el('span', { text: 'Hide the glow' })])
      ])
    ]));

    liveRegion = el('div', { class: 'sr-only', 'aria-live': 'polite' });
    document.body.append(frame, chip, panel, liveRegion);

    document.addEventListener('keydown', function (e) {
      if (e.key !== 'Escape') return;
      if (summary) closeSummary(); else if (!panel.hidden) closePanel(true);
    });
    document.addEventListener('click', function (e) {
      if (!panel.hidden && !panel.contains(e.target) && !chip.contains(e.target)) closePanel(false);
    });
  }

  // ---------- Keeping the aura just below the top bar ----------
  var bar = null, ticking = false;
  function place() {
    ticking = false;
    var top = bar ? Math.max(0, bar.getBoundingClientRect().bottom) : 0;
    frame.style.top = top + 'px';
  }
  function schedulePlace() { if (!ticking) { ticking = true; requestAnimationFrame(place); } }

  // ---------- Drawing ----------
  function cornerAngle() {
    // Angle of the top-left corner seen from the middle of the aura, so the session timeline starts there.
    var r = frame.getBoundingClientRect();
    return -Math.atan2(r.width / 2, r.height / 2) * 180 / Math.PI;
  }

  function timeline() {
    // Mood segments with how long each lasted (the "starting point" neutral is skipped once a real mood exists).
    var end = session.ended || now();
    var list = session.entries.map(function (e, i) {
      var next = session.entries[i + 1];
      return { m: e.m, s: e.s, ms: Math.max(1000, (next ? next.t : end) - e.t) };
    });
    var real = list.filter(function (x) { return x.s !== 'start'; });
    if (real.length) list = real;
    var merged = [];
    list.forEach(function (x) {
      var last = merged[merged.length - 1];
      if (last && last.m === x.m) last.ms += x.ms; else merged.push({ m: x.m, ms: x.ms });
    });
    return merged;
  }

  function storyGradient(segments, from) {
    var total = segments.reduce(function (s, x) { return s + x.ms; }, 0);
    // Every mood gets at least 4% of the ring so brief feelings still show.
    var parts = segments.map(function (x) { return Math.max(x.ms / total, 0.04); });
    var sum = parts.reduce(function (s, p) { return s + p; }, 0);
    var stops = [], at = 0;
    segments.forEach(function (x, i) {
      var c = BY_ID[x.m].colors, w = parts[i] / sum * 100;
      stops.push(c[0] + ' ' + (at + w * 0.15).toFixed(2) + '%', c[1] + ' ' + (at + w * 0.7).toFixed(2) + '%');
      at += w;
    });
    // Blend the end back into the start so there's no hard seam where the timeline meets itself.
    stops.push(BY_ID[segments[0].m].colors[0] + ' 100%');
    return 'conic-gradient(from ' + from.toFixed(1) + 'deg, ' + stops.join(', ') + ')';
  }

  // ---------- The mood oval(s) ----------
  function readableText(hex) {
    // Dark text on light colors, white on dark ones (simple luminance check).
    var n = parseInt(hex.slice(1), 16), r = n >> 16, g = (n >> 8) & 255, b = n & 255;
    return (0.299 * r + 0.587 * g + 0.114 * b) > 150 ? '#22301E' : '#FFFFFF';
  }
  function mainMood() {
    // The current mood, or the one felt longest once the session has ended.
    if (!session.ended) return current();
    var totals = {};
    timeline().forEach(function (x) { totals[x.m] = (totals[x.m] || 0) + x.ms; });
    var top = Object.keys(totals).sort(function (a, b) { return totals[b] - totals[a]; })[0];
    return { m: top, s: 'session' };
  }
  function renderOvals() {
    var mm = mainMood(), m = BY_ID[mm.m], fresh = mm.s === 'start';
    document.querySelectorAll('[data-aura-oval]').forEach(function (oval) {
      var fill = oval.querySelector('.fill, .aura-oval-fill'), note = oval.querySelector('.meaning, .aura-oval-note');
      if (!fill || !note) {
        // Replace the placeholder (logo) with the mood oval.
        fill = el('div', { class: 'aura-oval-fill' });
        note = el('p', { class: 'aura-oval-note', 'aria-live': 'polite' });
        oval.replaceChildren(fill, el('div', { class: 'aura-oval-bottom' }, [
          note, el('button', { type: 'button', class: 'btn aura-oval-btn',
                               onclick: function (e) { e.stopPropagation(); openPanel(); } }, [document.createTextNode('Change mood')])
        ]));
        oval.classList.add('aura-oval');
      }
      fill.style.background = 'linear-gradient(160deg, ' + m.colors[0] + ', ' + m.colors[2] + ' 55%, ' + m.colors[1] + ')';
      fill.style.color = readableText(m.colors[0]);
      fill.textContent = fresh ? 'How are you?' : (session.ended ? 'Mostly ' + m.label.toLowerCase() : m.label);
      note.textContent = fresh
        ? 'Pick a mood, chat, or do a check-in, and this will match how you feel.'
        : (session.ended ? 'Your main mood this session. Your session aura is around the screen.' : m.note);
    });
    // Dashboard color dots: highlight the color family of the current mood.
    var dots = document.querySelectorAll('.dot[data-name]');
    if (dots.length && !fresh && m.family) {
      dots.forEach(function (d) { d.setAttribute('aria-pressed', String(d.dataset.name === m.family)); });
    }
  }

  function render() {
    var c = current(), m = BY_ID[c.m];
    var hidden = hiddenPref();
    frame.hidden = hidden;
    frame.style.setProperty('--aura-c1', m.colors[0]);
    frame.style.setProperty('--aura-c2', m.colors[1]);
    frame.style.setProperty('--aura-c3', m.colors[2]);
    frame.style.setProperty('--aura-pace', m.pace + 's');
    frame.style.setProperty('--aura-size', m.size + 'px');
    frame.classList.toggle('is-story', !!session.ended);
    if (session.ended) {
      frame.style.setProperty('--aura-size', '52px');
      story.firstChild.style.background = storyGradient(timeline(), cornerAngle());
    }
    chip.querySelector('.aura-chip-dot').style.background = session.ended
      ? storyGradient(timeline(), 0) : 'conic-gradient(' + m.colors.concat(m.colors[0]).join(',') + ')';
    chipLabel.textContent = session.ended ? 'Session aura' : m.label;
    chip.setAttribute('aria-label', (session.ended ? 'Showing your session aura' : 'Your aura: ' + m.label) +
                      (hidden ? ' (glow hidden)' : '') + '. Change how you feel');
    chip.classList.toggle('is-hidden', hidden);
    panel.querySelectorAll('.aura-mood').forEach(function (b) {
      b.setAttribute('aria-pressed', String(!session.ended && b.dataset.mood === c.m && c.s !== 'start'));
    });
    panelStatus.textContent = session.ended
      ? 'Showing your session aura. Pick a mood to start a new session.'
      : (c.s === 'start' ? 'Pick the mood closest to how you feel. Your aura will match it.'
                         : 'Your aura: ' + m.label + ' (' + SOURCE_TEXT[c.s] + ').');
    panelNote.textContent = session.ended ? '' : (c.s === 'start' ? '' : m.note);
    panelNote.classList.toggle('is-urgent', !session.ended && c.m === 'hurting');
    if (!session.ended && c.m === 'hurting') {
      panelNote.textContent = m.note + ' If you are in danger, call or text 988, or call 911.';
    }
    renderOvals();
  }

  // ---------- Changing the mood ----------
  function setMood(id, source) {
    var m = BY_ID[id];
    if (!m) return false;
    source = SOURCE_TEXT[source] && source !== 'start' ? source : 'picked';
    var c = current();
    if (source === 'camera') {
      if (id === 'neutral' && c.m !== 'neutral') return false;                 // neutral face isn't a feeling
      if (c.s === 'picked' && now() - c.t < PICK_HOLD) return false;          // respect what they told us
    }
    if (session.ended) session = newSession();
    session.last = now();
    if (current().m === id && current().s !== 'start') { current().s = source; save(); render(); return true; }
    session.entries.push({ m: id, s: source, t: now() });
    if (session.entries.length > 500) session.entries.splice(1, session.entries.length - 500);
    save();
    render();
    liveRegion.textContent = 'Aura changed to ' + m.label + '.';
    return true;
  }

  // Picked in the aura panel: also save the matching color to Mood history (signed-in patients).
  var clickingDot = false;
  function pick(id) {
    setMood(id, 'picked');
    var family = BY_ID[id].family;
    if (!family) return;
    var dot = document.querySelector('.dot[data-name="' + family + '"]');
    if (dot) { clickingDot = true; dot.click(); clickingDot = false; return; }   // dashboard saves + updates its capsule
    if (window.ATTUNE_ROLE !== 'patient') return;                                  // only patients have a Mood history
    fetch('/api/moods', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                          body: JSON.stringify({ color: family }) }).catch(function () { /* not a patient: fine */ });
  }

  function fromStress(n) {
    n = Number(n);
    if (isNaN(n)) return false;
    var id = n <= 1 ? 'peaceful' : n <= 3 ? 'calm' : n <= 4 ? 'neutral' : n <= 5 ? 'anxious'
           : n <= 7 ? 'stressed' : n <= 9 ? 'overwhelmed' : 'panic';
    return setMood(id, 'checkin');
  }
  function fromCamera(emotion) { return CAMERA[emotion] ? setMood(CAMERA[emotion], 'camera') : false; }

  // ---------- Panel ----------
  function togglePanel() { if (panel.hidden) openPanel(); else closePanel(true); }
  function openPanel() {
    panel.hidden = false;
    chip.setAttribute('aria-expanded', 'true');
    var pressed = panel.querySelector('.aura-mood[aria-pressed="true"]') || panel.querySelector('.aura-mood');
    pressed.focus();
  }
  function closePanel(returnFocus) {
    if (panel.hidden) return;
    panel.hidden = true;
    chip.setAttribute('aria-expanded', 'false');
    if (returnFocus) chip.focus();
  }

  // ---------- End of session ----------
  function minutes(ms) {
    var m = Math.round(ms / 60000);
    return m < 1 ? 'under a minute' : m === 1 ? '1 minute' : m + ' minutes';
  }
  function describe(segments) {
    var real = segments.filter(function (x) { return x.m !== 'neutral'; });
    if (!real.length) return 'Your aura stayed neutral this time. Pick a mood or chat to color it next time.';
    var totals = {}, total = 0;
    segments.forEach(function (x) { totals[x.m] = (totals[x.m] || 0) + x.ms; total += x.ms; });
    var top = Object.keys(totals).sort(function (a, b) { return totals[b] - totals[a]; })[0];
    var text = 'You felt mostly ' + BY_ID[top].label.toLowerCase() + ' (' + Math.round(totals[top] / total * 100) + '% of the time).';
    var first = real[0].m, last = segments[segments.length - 1].m;
    if (first !== last) {
      text += ' You started out ' + BY_ID[first].label.toLowerCase() + ' and ended ' + BY_ID[last].label.toLowerCase() + '.';
      var eased = { Red: 3, Blue: 2, Purple: 1, Yellow: 0, Green: 0 };
      if ((eased[BY_ID[first].family] || 0) > (eased[BY_ID[last].family] || 0)) text += ' That shift took real effort. Nice work.';
    }
    return text;
  }

  function endSession(opts) {
    opts = opts || {};
    if (!session.ended) { session.ended = now(); session.last = now(); save(); }
    render();
    showSummary(opts.signOutForm || null);
  }

  function showSummary(signOutForm) {
    closeSummary();
    var segments = timeline();
    var totals = {}, total = 0;
    segments.forEach(function (x) { totals[x.m] = (totals[x.m] || 0) + x.ms; total += x.ms; });
    var ranked = Object.keys(totals).sort(function (a, b) { return totals[b] - totals[a]; });
    var ring = el('div', { class: 'aura-ring', role: 'img',
                           'aria-label': 'Session aura: ' + ranked.map(function (id) { return BY_ID[id].label; }).join(', ') });
    ring.style.background = storyGradient(segments, 0);
    var rows = ranked.slice(0, 6).map(function (id) {
      var pct = Math.round(totals[id] / total * 100);
      var meter = el('span', { class: 'aura-meter', 'aria-hidden': 'true' }, [el('span', {})]);
      meter.firstChild.style.width = Math.max(pct, 3) + '%';
      meter.firstChild.style.background = 'linear-gradient(90deg,' + BY_ID[id].colors.join(',') + ')';
      return el('li', {}, [swatch(BY_ID[id]), el('span', { class: 'aura-row-label', text: BY_ID[id].label }), meter,
                           el('span', { class: 'aura-row-pct', text: pct + '%' })]);
    });
    var buttons = [];
    if (signOutForm) {
      buttons.push(el('button', { type: 'button', class: 'btn btn-primary', onclick: function () {
        signOutForm.dataset.auraDone = '1';
        try { sessionStorage.removeItem(KEY); } catch (e) { /* ignore */ }
        signOutForm.submit();
      } }, [document.createTextNode('Sign out')]));
      buttons.push(el('button', { type: 'button', class: 'btn', onclick: function () { reopen(); } }, [document.createTextNode('Stay signed in')]));
    } else {
      buttons.push(el('button', { type: 'button', class: 'btn btn-primary', onclick: function () { closeSummary(); } }, [document.createTextNode('Keep this aura')]));
      buttons.push(el('button', { type: 'button', class: 'btn', onclick: function () { session = newSession(); save(); render(); closeSummary(); } },
                      [document.createTextNode('Start a new session')]));
    }
    var dialog = el('div', { class: 'aura-summary', role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': 'auraSumTitle' }, [
      el('h2', { id: 'auraSumTitle', text: 'Your session aura' }),
      el('p', { class: 'aura-sub', text: minutes(total) + (segments.length > 1 ? ', ' + ranked.length + ' moods' : '') +
                ' · the ring goes clockwise from the top, like the glow around your screen' }),
      ring,
      el('p', { text: describe(segments) }),
      el('ul', { class: 'aura-rows' }, rows),
      el('div', { class: 'aura-summary-foot' }, buttons)
    ]);
    summary = el('div', { class: 'aura-backdrop', onclick: function (e) { if (e.target === summary) closeSummary(); } }, [dialog]);
    document.body.append(summary);
    dialog.querySelector('button').focus();
  }
  function reopen() {
    // "Stay signed in": go back to the live aura they had.
    session.ended = null; save(); render(); closeSummary();
  }
  function closeSummary() {
    if (!summary) return;
    summary.remove();
    summary = null;
    chip.focus();
  }

  // ---------- Listening to the rest of the site ----------
  function wire() {
    // Dashboard color dots (patient app): the dot's family sets a matching mood.
    document.addEventListener('click', function (e) {
      var dot = e.target.closest && e.target.closest('.dot[data-name]');
      if (dot && !clickingDot && FAMILY_DEFAULT[dot.dataset.name]) setMood(FAMILY_DEFAULT[dot.dataset.name], 'picked');
    });
    // The dashboard redraws its oval with its 5 basic colors: put the main mood back.
    window.addEventListener('attune:mood', function () { setTimeout(renderOvals, 0); });
    // Signing out ends the session: show the session aura first.
    document.addEventListener('submit', function (e) {
      var form = e.target;
      if (!/\/logout$/.test(form.getAttribute('action') || '') || form.dataset.auraDone) return;
      if (!timeline().some(function (x) { return x.m !== 'neutral'; })) {
        try { sessionStorage.removeItem(KEY); } catch (err) { /* ignore */ }
        return;
      }
      e.preventDefault();
      closePanel(false);
      endSession({ signOutForm: form });
    }, true);
  }

  function init() {
    build();
    bar = document.querySelector('header.bar, body > header');
    place();
    window.addEventListener('scroll', schedulePlace, { passive: true });
    window.addEventListener('resize', function () { schedulePlace(); if (session.ended) render(); });
    if (bar && window.ResizeObserver) new ResizeObserver(schedulePlace).observe(bar);
    wire();
    render();
    setInterval(function () { session.last = now(); save(); }, 60000);   // keep an active tab's session alive
  }

  window.Aura = {
    moods: MOODS,
    setMood: setMood,
    fromStress: fromStress,
    fromCamera: fromCamera,
    endSession: function () { endSession(); },
    current: function () { return current().m; }
  };

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
