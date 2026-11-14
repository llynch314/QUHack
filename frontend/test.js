// attuneMIND patient app: the script behind test.html.
// One page, one tab per #section: #dashboard, #mood-history, #chatbot, #toolkit, #care-team, #settings.
// Served by the Flask app at /test (run `make run`). Opened straight from disk it shows sample data.
(function () {
  "use strict";

  var PREVIEW = !!window.ATTUNE_DEMO;   // set in test.html: from disk, GitHub Pages, or ?demo
  var $ = function (id) { return document.getElementById(id); };

  // ---------- Small helpers ----------

  // Read text aloud with the browser's built-in speech synthesis.
  // Some browsers only allow speech after the user has clicked or tapped the page.
  function speak(text) {
    if (window.MC && MC.speak) return MC.speak(text);
    if (!("speechSynthesis" in window)) return;
    var message = new SpeechSynthesisUtterance();
    message.text = text;
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(message);
  }

  function pref(key, value) {             // per-browser preferences (not account data)
    try {
      if (value === undefined) return localStorage.getItem("attune-" + key);
      localStorage.setItem("attune-" + key, value);
    } catch (e) { return null; }
  }

  function el(tag, attrs, children) {     // tiny DOM builder: el("li", {class: "x"}, ["text", node])
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === "style") node.style.cssText = attrs[k];
      else if (k.indexOf("on") === 0) node.addEventListener(k.slice(2), attrs[k]);
      else node.setAttribute(k, attrs[k]);
    });
    (children || []).forEach(function (c) { if (c != null) node.append(c); });
    return node;
  }

  function when(iso) { return new Date(iso).toLocaleString([], { dateStyle: "medium", timeStyle: "short" }); }
  function label(activity) { return activity.replace(/-/g, " ").replace(/^./, function (c) { return c.toUpperCase(); }); }

  // ---------- Talking to the backend ----------

  function api(method, url, body) {
    if (PREVIEW) return Demo.handle(method, url, body);
    return fetch(url, {
      method: method,
      headers: body === undefined ? {} : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body)
    }).then(function (res) {
      if (res.status === 401) { location.href = "/signin?next=" + encodeURIComponent(location.pathname + location.hash); throw new Error("Please sign in."); }
      if (res.status === 204) return {};
      return res.json().then(function (data) {
        if (!res.ok) throw new Error(data.error || "Something went wrong. Please try again.");
        return data;
      });
    });
  }

  // ---------- Moods (shared by the dashboard and mood history) ----------

  var MOODS = {
    Yellow: { color: "#E8C24A", meaning: "Yellow means you feel happy and full of energy. It feels bright, like the sun." },
    Green:  { color: "#8FB08A", meaning: "Green means you feel calm and steady. Everything feels okay." },
    Blue:   { color: "#7F9FC4", meaning: "Blue means you feel quiet or a little sad. It is okay to slow down and rest." },
    Red:    { color: "#D4705F", meaning: "Red means you have strong feelings, like anger or worry. Try taking a deep breath." },
    Purple: { color: "#A58BC0", meaning: "Purple means you feel dreamy and thoughtful. Your mind is busy with big ideas." }
  };

  var me = null;   // the signed-in user, from /api/me

  // ---------- Dashboard ----------

  var Dashboard = (function () {
    var quotes = [
      "Small steps still move you forward.",
      "You don't have to have it all figured out today.",
      "Progress is progress, no matter how small.",
      "Be kind to yourself as you grow."
    ];
    var dots = document.querySelectorAll(".dot");

    function showMood(name) {
      dots.forEach(function (o) {
        o.setAttribute("aria-pressed", o.dataset.name === name ? "true" : "false");
      });
      $("capsule").style.setProperty("--mood", MOODS[name].color);
      $("moodName").textContent = name;
      $("moodMeaning").textContent = MOODS[name].meaning;
      // Other components (like the React music player) listen for this.
      window.attuneMood = name;
      window.dispatchEvent(new CustomEvent("attune:mood", { detail: { color: name } }));
    }

    function init() {
      $("inspirationalQuote").textContent = "“" + quotes[Math.floor(Math.random() * quotes.length)] + "”";
      dots.forEach(function (d) {
        d.addEventListener("click", function () {
          showMood(d.dataset.name);
          api("POST", "/api/moods", { color: d.dataset.name })
            .then(function () { $("moodHint").textContent = "Saved to your mood history."; })
            .catch(function (e) { $("moodHint").textContent = "Couldn't save your mood: " + e.message; });
        });
      });
    }

    function render() {
      $("userName").textContent = me.name;
      if (me.mood && MOODS[me.mood.color]) showMood(me.mood.color);
      else showMood("Green");
    }

    return { init: init, render: render };
  })();

  // ---------- Mood history ----------

  var MoodHistory = {
    render: function () {
      return Promise.all([api("GET", "/api/moods"), api("GET", "/api/checkins")]).then(function (r) {
        var moods = r[0].moods, checkins = r[1].checkins;

        // Bar chart of how often each color was picked
        var counts = {};
        moods.forEach(function (m) { counts[m.color] = (counts[m.color] || 0) + 1; });
        var max = Math.max.apply(null, [1].concat(Object.values(counts)));
        $("moodBars").replaceChildren.apply($("moodBars"), Object.keys(MOODS).map(function (name) {
          var n = counts[name] || 0;
          return el("div", {}, [
            el("span", { class: "bar-fill", style: "--c:" + MOODS[name].color + ";height:" + (n / max * 90) + "px" }),
            name + " " + n
          ]);
        }));
        var top = Object.keys(counts).sort(function (a, b) { return counts[b] - counts[a]; });
        $("moodSummary").textContent = moods.length
          ? moods.length + " mood" + (moods.length === 1 ? "" : "s") + " saved. Most often: " + top.slice(0, 3).map(function (c) { return c + " (" + counts[c] + ")"; }).join(", ") + "."
          : "No moods yet. Pick a color on your dashboard to start.";

        $("moodList").replaceChildren.apply($("moodList"), moods.slice(-30).reverse().map(function (m) {
          return el("li", {}, [
            el("span", { class: "dot-swatch", style: "--c:" + (m.hex || MOODS[m.color].color), "aria-hidden": "true" }),
            el("span", { class: "grow" }, [el("strong", {}, [m.color]), " ", m.meaning ? el("span", { class: "muted" }, ["· " + m.meaning]) : null]),
            el("time", { class: "muted", datetime: m.created_at }, [when(m.created_at)])
          ]);
        }));

        var rated = checkins.filter(function (c) { return c.stress_before != null && c.stress_after != null; });
        var avg = rated.length ? rated.reduce(function (s, c) { return s + c.stress_after - c.stress_before; }, 0) / rated.length : null;
        $("checkSummary").textContent = checkins.length
          ? checkins.length + " check-ins." + (avg === null ? "" : " Stress changed by " + (avg > 0 ? "+" : "") + avg.toFixed(1) + " on average per exercise (negative means calmer).")
          : "No check-ins yet. Try an exercise in the Calm Toolkit.";
        $("checkRows").replaceChildren.apply($("checkRows"), checkins.slice(-20).reverse().map(function (c) {
          return el("tr", {}, [
            el("td", {}, [when(c.created_at)]), el("td", {}, [label(c.activity)]),
            el("td", {}, [c.stress_before == null ? "-" : String(c.stress_before)]),
            el("td", {}, [c.stress_after == null ? "-" : String(c.stress_after)])
          ]);
        }));
      });
    },
    init: function () {
      $("shareProgress").addEventListener("click", function () {
        api("POST", "/api/documents/progress-report")
          .then(function () { $("shareStatus").textContent = "Saved as a health document. The providers on your care team can now see it."; })
          .catch(function (e) { $("shareStatus").textContent = e.message; });
      });
    }
  };

  // ---------- Chatbot ----------
  // The chat, its toolbar (voice chat, camera, read aloud) and dictation are in static/js/chat.js
  // and static/js/voice.js, shared with the /chat page.
  var Chatbot = {};

  // ---------- Calm Toolkit ----------

  // A before/after stress rating that saves a check-in. Rendered into each [data-checkin] slot.
  function CheckIn(slot) {
    var activity = slot.dataset.checkin;
    function slider(which, text) {
      var id = activity + "-" + which, out = el("output", { for: id }, ["5"]);
      var input = el("input", { type: "range", id: id, min: "0", max: "10", value: "5",
        oninput: function (e) { out.textContent = e.target.value; } });
      return el("div", { class: "rating" }, [
        el("label", { for: id }, [text + " ", out]), input,
        el("div", { class: "scale", "aria-hidden": "true" }, [el("span", {}, ["0 calm"]), el("span", {}, ["10 very stressed"])])
      ]);
    }
    var status = el("p", { class: "status", role: "status" });
    var save = el("button", { type: "button", class: "btn", onclick: function () {
      if (window.Aura) Aura.fromStress(+$(activity + "-after").value);
      api("POST", "/api/checkins", { activity: activity, stress_before: +$(activity + "-before").value, stress_after: +$(activity + "-after").value })
        .then(function () { status.textContent = "Saved. See it in Mood history."; })
        .catch(function (e) { status.textContent = e.message; });
    } }, ["Save check-in"]);
    slot.className = "stack";
    slot.append(el("h3", {}, ["How stressed do you feel?"]), slider("before", "Before:"), slider("after", "After:"), save, status);
  }

  var Toolkit = (function () {
    var timer = null;
    var phases = [["Breathe in", 4, 1.6], ["Hold", 4, 1.6], ["Breathe out", 6, 1]];
    function breathe(i) {
      var p = phases[i % phases.length], circle = $("breathCircle");
      $("breathCue").textContent = p[0];
      circle.textContent = p[0];
      circle.style.transitionDuration = p[1] + "s";
      circle.style.transform = "scale(" + p[2] + ")";
      timer = setTimeout(function () { breathe(i + 1); }, p[1] * 1000);
    }
    function stop() {
      clearTimeout(timer); timer = null;
      $("breathCircle").style.transform = "scale(1)";
      $("breathCircle").textContent = "Ready";
      $("breathCue").textContent = "Nice work. How do you feel?";
      $("breathStart").disabled = false; $("breathStop").disabled = true;
    }

    // 5-4-3-2-1 grounding boxes are built by static/js/grounding.js.

    function init() {
      $("breathStart").addEventListener("click", function () {
        $("breathStart").disabled = true; $("breathStop").disabled = false; breathe(0);
      });
      $("breathStop").addEventListener("click", stop);
      document.querySelectorAll("[data-checkin]").forEach(CheckIn);
    }
    return { init: init, leave: function () { if (timer) stop(); } };
  })();

  // ---------- Care Team ----------

  var CareTeam = {
    render: function () {
      $("autoAlerts").checked = !!me.auto_alerts;
      return Promise.all([
        api("GET", "/api/care-team"),
        api("GET", "/api/patients/" + me.id + "/documents"),
        api("GET", "/api/alerts")
      ]).then(function (r) {
        var links = r[0].links, docs = r[1].documents, alerts = r[2].alerts;

        $("teamList").replaceChildren.apply($("teamList"), links.length ? links.map(function (l) {
          var m = l.member, isProvider = m.role === "provider";
          var details = isProvider ? [m.specialty, m.organization].filter(Boolean).join(", ") : "";
          return el("li", {}, [
            el("div", { class: "grow" }, [
              el("strong", {}, [m.name]), " ",
              el("span", { class: "pill" + (m.verified ? " ok" : "") }, [isProvider ? (m.verified ? "✓ Verified provider" : "Provider (unverified)") : "Family"]),
              el("div", { class: "muted" }, [m.email + (details ? " · " + details : "")]),
              el("div", { class: "muted" }, ["Can see: " + (isProvider ? "health documents" : "urgent alerts")])
            ]),
            el("button", { type: "button", class: "btn btn-ghost", onclick: function () {
              if (!confirm("Remove " + m.name + "? They will lose access right away.")) return;
              api("DELETE", "/api/care-team/" + l.id).then(CareTeam.render);
            } }, ["Remove"])
          ]);
        }) : [el("li", { class: "muted" }, ["No one yet. Add a health provider or family member below."])]);

        $("docList").replaceChildren.apply($("docList"), docs.length ? docs.map(function (d) {
          return el("li", {}, [
            el("details", { class: "grow" }, [
              el("summary", {}, [el("strong", {}, [d.title]), el("span", { class: "muted" }, [" · " + (d.author_name || "Former member") + " · " + when(d.created_at)])]),
              el("p", { style: "white-space:pre-wrap" }, [d.body || ""])
            ]),
            el("button", { type: "button", class: "btn btn-ghost", onclick: function () {
              if (!confirm("Delete “" + d.title + "”?")) return;
              api("DELETE", "/api/documents/" + d.id).then(CareTeam.render);
            } }, ["Delete"])
          ]);
        }) : [el("li", { class: "muted" }, ["No documents yet."])]);

        $("alertList").replaceChildren.apply($("alertList"), alerts.length ? alerts.slice(0, 10).map(function (a) {
          return el("li", {}, [
            el("div", { class: "grow" }, [el("strong", {}, [a.label]), el("span", { class: "muted" }, [" · " + (a.source === "sos" ? "you sent this" : "from chat") + " · " + when(a.created_at)])]),
            el("span", { class: "pill" + (a.acknowledged_at ? " ok" : "") }, [a.acknowledged_at ? "Seen by " + a.acknowledged_by : "Not seen yet"])
          ]);
        }) : [el("li", { class: "muted" }, ["No alerts."])]);
      });
    },
    init: function () {
      document.querySelectorAll(".sos").forEach(function (btn) {
        btn.addEventListener("click", function () {
          api("POST", "/api/alerts/sos", { kind: btn.dataset.kind }).then(function (data) {
            $("sosStatus").textContent = data.family_notified
              ? "Alert sent to " + data.family_notified + " family member(s). Try the Calm Toolkit while you wait."
              : "Alert saved, but no family members are on your care team yet. Add one below.";
            CareTeam.render();
          }).catch(function (e) { $("sosStatus").textContent = e.message; });
        });
      });
      $("addForm").addEventListener("submit", function (e) {
        e.preventDefault();
        api("POST", "/api/care-team", { email: $("memberEmail").value }).then(function () {
          $("memberEmail").value = ""; $("addStatus").textContent = "Added."; CareTeam.render();
        }).catch(function (err) { $("addStatus").textContent = err.message; });
      });
      $("autoAlerts").addEventListener("change", function (e) {
        api("PATCH", "/api/me/settings", { auto_alerts: e.target.checked }).then(function (d) { me.auto_alerts = d.auto_alerts; });
      });
      $("docForm").addEventListener("submit", function (e) {
        e.preventDefault();
        api("POST", "/api/patients/" + me.id + "/documents", { title: $("docTitle").value, body: $("docBody").value })
          .then(function () { $("docTitle").value = ""; $("docBody").value = ""; CareTeam.render(); });
      });
    }
  };

  // ---------- Settings ----------

  var Settings = {
    render: function () {
      $("setName").textContent = me.name;
      $("setEmail").textContent = me.email ? "· " + me.email : "";
      $("setExpressions").checked = !!me.save_expressions;
      $("setGreeting").checked = pref("greeting") === "1";
    },
    init: function () {
      $("setGreeting").addEventListener("change", function (e) { pref("greeting", e.target.checked ? "1" : "0"); });
      $("setExpressions").addEventListener("change", function (e) {
        api("PATCH", "/api/me/settings", { save_expressions: e.target.checked }).then(function (d) { me.save_expressions = d.save_expressions; });
      });
      $("deleteBtn").addEventListener("click", function () {
        if (!confirm("Permanently delete your account and all your data? This cannot be undone.")) return;
        api("POST", "/api/me/delete").then(function () { location.href = "/"; })
          .catch(function () { $("deleteStatus").textContent = "Could not delete your account. Please try again."; });
      });
    }
  };

  // ---------- Tabs (hash router) ----------

  var VIEWS = {
    "dashboard": Dashboard, "mood-history": MoodHistory, "chatbot": Chatbot,
    "toolkit": Toolkit, "care-team": CareTeam, "settings": Settings
  };
  var current = null;

  function show() {
    var name = location.hash.slice(1);
    if (!VIEWS[name]) name = "dashboard";
    if (current && current !== name && VIEWS[current].leave) VIEWS[current].leave();
    current = name;
    Object.keys(VIEWS).forEach(function (v) { $("view-" + v).hidden = v !== name; });
    $("pageLabel").textContent = $("view-" + name).dataset.label;
    document.title = name === "dashboard" ? "attuneMIND" : $("view-" + name).dataset.label + " · attuneMIND";
    document.querySelectorAll("#menu a").forEach(function (a) {
      if (a.getAttribute("href") === "#" + name) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
    });
    setMenu(false);
    if (VIEWS[name].render && me) {
      Promise.resolve(VIEWS[name].render()).catch(function (e) { console.error("Could not load " + name, e); });
    }
  }

  // ---------- Menu (original behaviour) ----------

  var btn = $("menuBtn"), menu = $("menu");
  function setMenu(open) {
    menu.hidden = !open;
    btn.setAttribute("aria-expanded", open ? "true" : "false");
    btn.setAttribute("aria-label", open ? "Close menu" : "Open menu");
  }
  btn.addEventListener("click", function (e) { e.stopPropagation(); setMenu(menu.hidden); });
  document.addEventListener("click", function (e) { if (!menu.hidden && !menu.contains(e.target)) setMenu(false); });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape" && !menu.hidden) { setMenu(false); btn.focus(); } });

  // ---------- Sample data for previews (opened from disk, no server) ----------

  var Demo = (function () {
    var t = Date.now(), H = 3600e3;
    var data = {
      me: { id: 1, name: "Alex Rivera", first_name: "Alex", email: "alex@example.com", role: "patient",
            auto_alerts: true, save_expressions: false, mood: null },
      moods: [["Blue", 50], ["Green", 30], ["Yellow", 26], ["Green", 6], ["Purple", 3]].map(function (m, i) {
        return { id: i + 1, color: m[0], hex: MOODS[m[0]].color, meaning: "", created_at: new Date(t - m[1] * H).toISOString() };
      }),
      checkins: [
        { id: 1, activity: "breathing", stress_before: 7, stress_after: 4, created_at: new Date(t - 30 * H).toISOString() },
        { id: 2, activity: "grounding", stress_before: 6, stress_after: 3, created_at: new Date(t - 6 * H).toISOString() }
      ],
      links: [
        { id: 1, member: { name: "Dr Lee", email: "dr.lee@cityhospital.example", role: "provider", organization: "City General Hospital", specialty: "Psychiatrist", verified: true } },
        { id: 2, member: { name: "Sam Rivera", email: "sam@example.com", role: "family" } }
      ],
      documents: [{ id: 1, title: "Session notes", body: "Practised box breathing. Plan: daily mood check-in.", author_name: "Dr Lee, Psychiatrist, City General Hospital (Health provider)", created_at: new Date(t - 50 * H).toISOString() }],
      alerts: [{ id: 1, label: "Panic attack", source: "sos", created_at: new Date(t - 52 * H).toISOString(), acknowledged_at: new Date(t - 51 * H).toISOString(), acknowledged_by: "Sam Rivera" }]
    };
    data.me.mood = data.moods[data.moods.length - 1];
    function handle(method, url, body) {
      var out = {};
      if (url === "/api/me") out = data.me;
      else if (url === "/api/moods" && method === "GET") out = { moods: data.moods };
      else if (url === "/api/moods") { out = { mood: { color: body.color } }; data.moods.push({ id: 99, color: body.color, hex: MOODS[body.color].color, created_at: new Date().toISOString() }); }
      else if (url === "/api/checkins" && method === "GET") out = { checkins: data.checkins };
      else if (url === "/api/care-team" && method === "GET") out = { links: data.links };
      else if (/documents$/.test(url) && method === "GET") out = { documents: data.documents };
      else if (url === "/api/alerts") out = { alerts: data.alerts };
      else if (url === "/api/chat") out = { reply: "This is a demo, so I can't reply for real. In the full app, an AI companion listens and helps you find your own answers.", crisis: false };
      else if (url === "/api/me/settings") out = body;
      else if (method !== "GET") return Promise.reject(new Error("This is a demo, so changes aren't saved."));
      return Promise.resolve(JSON.parse(JSON.stringify(out)));
    }
    return { handle: handle };
  })();

  // ---------- Start ----------

  $("previewBanner").hidden = !PREVIEW;
  $("bannerLocal").hidden = location.protocol !== "file:";
  $("bannerDemo").hidden = location.protocol === "file:";
  Object.keys(VIEWS).forEach(function (v) { if (VIEWS[v].init) VIEWS[v].init(); });
  window.addEventListener("hashchange", show);
  show();
  api("GET", "/api/me").then(function (user) {
    me = user;
    Dashboard.render();
    show();                                       // render the current tab now that we know the user
    if (pref("greeting") === "1") speak("Hello, " + me.first_name + "!");
  }).catch(function (e) {
    $("userName").textContent = "Unable to load your name";
    console.error("Could not load the signed-in user.", e);
  });
})();
