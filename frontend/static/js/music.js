// "Music for your mood": a React component on the dashboard (frontend/test.html).
// It listens for the mood color picked on the dashboard (the "attune:mood" event from test.js)
// and shows calm Spotify playlists for it, from the backend's /api/music.
//
// React is loaded from a CDN in test.html, so there's no build step. JSX isn't available
// without one, so elements are written with React.createElement (aliased to h).
// Privacy: Spotify's player is only loaded when the user presses Play.
(function () {
  "use strict";
  var root = document.getElementById("musicRoot");
  if (!root || !window.React || !window.ReactDOM) return;

  var h = React.createElement;
  var useState = React.useState, useEffect = React.useEffect;
  var PREVIEW = location.protocol === "file:";
  var QUERIES = {   // same as backend/spotify.py, for previews opened from disk
    Yellow: "happy acoustic morning", Green: "calm acoustic chill", Blue: "comforting gentle piano",
    Red: "calming meditation breathing", Purple: "dreamy ambient focus"
  };

  function loadMusic(mood) {
    if (PREVIEW) {
      return Promise.resolve({ mood: mood, query: QUERIES[mood], configured: false, playlists: [],
        search_url: "https://open.spotify.com/search/" + encodeURIComponent(QUERIES[mood]) });
    }
    return fetch("/api/music?mood=" + encodeURIComponent(mood)).then(function (res) {
      if (!res.ok) throw new Error("Couldn't load music right now.");
      return res.json();
    });
  }

  function PlaylistTile(props) {
    var p = props.playlist;
    return h("li", { className: "music-tile" },
      p.image ? h("img", { src: p.image, alt: "", loading: "lazy", width: 64, height: 64 }) : h("span", { className: "music-art", "aria-hidden": "true" }, "♪"),
      h("div", { className: "grow" },
        h("strong", null, p.name),
        p.owner ? h("div", { className: "muted" }, "by " + p.owner) : null),
      h("button", { type: "button", className: "btn" + (props.playing ? " btn-primary" : ""),
        "aria-pressed": props.playing ? "true" : "false", onClick: props.onPlay },
        props.playing ? "Playing" : "Play"));
  }

  function MusicCard() {
    var _m = useState(window.attuneMood || "Green"), mood = _m[0], setMood = _m[1];
    var _d = useState(null), data = _d[0], setData = _d[1];
    var _e = useState(null), error = _e[0], setError = _e[1];
    var _p = useState(null), playing = _p[0], setPlaying = _p[1];

    // Follow the mood picked on the dashboard
    useEffect(function () {
      function onMood(e) { setMood(e.detail.color); }
      window.addEventListener("attune:mood", onMood);
      return function () { window.removeEventListener("attune:mood", onMood); };
    }, []);

    // Load playlists for the mood (waits a moment, so trying out colors doesn't spam Spotify)
    useEffect(function () {
      var cancelled = false;
      setError(null);
      var t = setTimeout(function () {
        loadMusic(mood).then(function (d) {
          if (cancelled) return;
          setData(d);
          setPlaying(null);
        }).catch(function (e) { if (!cancelled) setError(e.message); });
      }, 400);
      return function () { cancelled = true; clearTimeout(t); };
    }, [mood]);

    var playlists = (data && data.playlists) || [];
    var current = playlists.filter(function (p) { return p.id === playing; })[0];

    return h("section", { className: "card stack music-card", "aria-labelledby": "musicH" },
      h("div", { className: "row", style: { justifyContent: "space-between" } },
        h("h2", { id: "musicH" }, "Music for ", h("span", { className: "music-mood", style: { "--c": moodColor(mood) } }, mood)),
        h("span", { className: "pill" }, "Spotify")),
      h("p", { className: "muted" }, "Calm playlists to match how you feel. Change your color and the music changes too."),
      error ? h("p", { className: "status", role: "status" }, error) : null,
      !data && !error ? h("p", { className: "status" }, "Finding music…") : null,
      current ? h("iframe", {
        key: current.id, title: "Spotify player: " + current.name, src: current.embed_url + "?utm_source=generator",
        width: "100%", height: 152, loading: "lazy", style: { border: 0, borderRadius: 14 },
        allow: "autoplay; clipboard-write; encrypted-media; fullscreen; picture-in-picture"
      }) : null,
      playlists.length ? h("ul", { className: "list music-list" }, playlists.map(function (p) {
        return h(PlaylistTile, { key: p.id, playlist: p, playing: p.id === playing,
          onPlay: function () { setPlaying(p.id === playing ? null : p.id); } });
      })) : null,
      data ? h("p", null,
        h("a", { href: data.search_url, target: "_blank", rel: "noopener" },
          playlists.length ? "More on Spotify" : "Find “" + data.query + "” on Spotify"),
        h("span", { className: "muted" }, playlists.length ? " · Spotify loads only when you press Play." : " (opens Spotify)")) : null
    );
  }

  function moodColor(name) {
    return { Yellow: "#E8C24A", Green: "#8FB08A", Blue: "#7F9FC4", Red: "#D4705F", Purple: "#A58BC0" }[name] || "#8FB08A";
  }

  ReactDOM.createRoot(root).render(h(MusicCard));
})();
