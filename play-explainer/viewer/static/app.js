/* Play Explainer viewer. Plain JS, no build step, no libraries.
 *
 * Flow: load /api/config -> load /api/plays for the viewer profile -> every
 * 250 ms read the video time and reveal the plays whose video_time has passed.
 * Plays without a video time join the feed (collapsed) once the video passes a
 * later timed play, so the feed always shows the game in order.
 */
(() => {
  "use strict";

  const $ = (sel) => document.querySelector(sel);
  const el = (tag, attrs = {}, ...kids) => {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v === null || v === undefined || v === false) continue;
      if (k === "class") node.className = v;
      else node.setAttribute(k, v === true ? "" : v);
    }
    for (const kid of kids.flat()) {
      if (kid === null || kid === undefined || kid === false) continue;
      node.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
    }
    return node;
  };

  const STATIC = window.PLAY_EXPLAINER_STATIC || null; // only set in the single-file preview
  const PREFS_KEY = "playExplainer.prefs";
  const LOWER_THIRD_MS = 6500;

  const state = {
    config: null,
    plays: [],
    byId: new Map(),
    persona: null,
    language: "en",
    team: null,
    notes: "",
    mode: "video",
    interval: 10,
    player: null,        // video clock: YouTube, mp4 or stand-in
    playerKind: null,
    replayClock: null,
    duration: 0,
    revealedIds: [],
    revealedSig: null,
    latestId: null,
    animateId: null,
    opened: new Set(),
    closed: new Set(),
    fetchSeq: 0,
    lastScore: null,
    ltTimer: null,
  };

  /* ------------------------------------------------------------ data */

  async function getJSON(url, opts = {}, ms = 90000) {
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), ms);
    try {
      const res = await fetch(url, { ...opts, signal: ctl.signal });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.error || `The server answered ${res.status}.`);
      return body;
    } catch (err) {
      if (err.name === "AbortError") throw new Error("The explainer took longer than 90 seconds.");
      throw err;
    } finally {
      clearTimeout(timer);
    }
  }

  const api = STATIC ? staticApi(STATIC) : {
    config: () => getJSON("/api/config"),
    plays: (profile) => getJSON("/api/plays", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(profile),
    }),
  };

  // Mirrors SampleSource in sources.py, for the no-server preview.
  function staticApi({ config, sample }) {
    const have = new Set(sample.personas_in_sample);
    const fields = ["play_id", "order", "quarter", "clock", "situation", "video_time", "score", "who",
      "impact", "impact_team", "wp_change", "pop_note"];
    return {
      config: async () => ({
        ...config,
        source: "sample",
        personas: config.personas.map((p) => ({ ...p, ready: have.has(p.id), selectable: have.has(p.id) })),
        notices: [],
      }),
      plays: async ({ persona, language, notes }) => {
        const fallback = [...have].sort()[0];
        const plays = sample.plays.map((raw) => {
          const exp = raw.explanations[persona] || raw.explanations[fallback] || {};
          const card = Object.fromEntries(fields.map((f) => [f, raw[f] ?? null]));
          return { ...card, ...exp, read_more: raw.read_more || [], source: "sample" };
        });
        const notices = ["Sample plays, not the real game. Real cards replace these once the viewer is connected to the explainer."];
        if (language !== "en") notices.push("Sample cards are English only. The connected explainer writes in the chosen language.");
        if (notes) notices.push("Notes change the wording once the explainer is connected.");
        return { source: "sample", plays, notices };
      },
    };
  }

  function loadPrefs() {
    try { return JSON.parse(localStorage.getItem(PREFS_KEY)) || {}; } catch { return {}; }
  }
  function savePrefs() {
    try {
      localStorage.setItem(PREFS_KEY, JSON.stringify({
        persona: state.persona, language: state.language, team: state.team, notes: state.notes,
      }));
    } catch { /* storage can be unavailable; prefs just won't persist */ }
  }

  /* ------------------------------------------------------------ clocks */

  class Clock {
    constructor(duration) { this.t = 0; this.playing = false; this.duration = duration; this.last = 0; }
    getTime() {
      if (this.playing) {
        const now = performance.now();
        this.t = Math.min(this.duration, this.t + (now - this.last) / 1000);
        this.last = now;
        if (this.t >= this.duration) this.playing = false;
      }
      return this.t;
    }
    getDuration() { return this.duration; }
    play() { if (this.t >= this.duration) this.t = 0; this.last = performance.now(); this.playing = true; }
    pause() { this.getTime(); this.playing = false; }
    seek(t) { this.getTime(); this.t = Math.max(0, Math.min(t, this.duration)); this.last = performance.now(); }
    isPlaying() { return this.playing; }
  }

  function loadYouTube(id, timeoutMs = 8000) {
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error("YouTube didn't load in time.")), timeoutMs);
      const make = () => {
        // eslint-disable-next-line no-undef
        const yt = new YT.Player("yt", {
          videoId: id,
          playerVars: { playsinline: 1, rel: 0 },
          events: {
            onReady: () => { clearTimeout(timer); resolve(yt); },
            onError: (e) => {
              clearTimeout(timer);
              const why = { 2: "bad video ID", 5: "player error", 100: "video not found", 101: "embedding disabled", 150: "embedding disabled" }[e.data] || `error ${e.data}`;
              if (state.playerKind === "youtube") useStandIn(`The video stopped (${why}).`);
              else reject(new Error(`YouTube: ${why}.`));
            },
          },
        });
      };
      if (window.YT && window.YT.Player) return make();
      window.onYouTubeIframeAPIReady = make;
      const s = document.createElement("script");
      s.src = "https://www.youtube.com/iframe_api";
      s.onerror = () => { clearTimeout(timer); reject(new Error("YouTube is blocked on this network.")); };
      document.head.append(s);
    });
  }

  const wrapYouTube = (yt) => ({
    getTime: () => yt.getCurrentTime() || 0,
    getDuration: () => yt.getDuration() || 0,
    play: () => yt.playVideo(),
    pause: () => yt.pauseVideo(),
    seek: (t) => yt.seekTo(t, true),
    isPlaying: () => yt.getPlayerState() === 1,
  });

  const wrapVideo = (v) => ({
    getTime: () => v.currentTime || 0,
    getDuration: () => (Number.isFinite(v.duration) ? v.duration : 0),
    play: () => v.play(),
    pause: () => v.pause(),
    seek: (t) => { v.currentTime = t; },
    isPlaying: () => !v.paused && !v.ended,
  });

  function standInDuration() {
    const times = state.plays.map((p) => p.video_time).filter((t) => t !== null && t !== undefined);
    return (times.length ? Math.max(...times) : 600) + 45;
  }

  function useStandIn(reason) {
    $("#yt").hidden = true;
    state.player = new Clock(standInDuration());
    state.playerKind = "stand-in";
    state.standInReason = `${reason} A stand-in clock is running instead, so cards still appear at the same moments.`;
    refreshStandIn();
    renderMarks();
  }

  async function setupVideo() {
    const video = state.config.video || {};
    if (STATIC) return useStandIn("This preview can't embed YouTube. Run the server to see the video here.");
    if (video.mp4_url) {
      const v = $("#mp4");
      v.src = video.mp4_url;
      v.hidden = false;
      $("#yt").hidden = true;
      state.player = wrapVideo(v);
      state.playerKind = "mp4";
      return;
    }
    if (!video.youtube_id) return useStandIn("No video is set in viewer_config.json.");
    try {
      const yt = await loadYouTube(video.youtube_id);
      state.player = wrapYouTube(yt);
      state.playerKind = "youtube";
    } catch (err) {
      useStandIn(err.message);
    }
  }

  const activeClock = () => (state.mode === "replay" ? state.replayClock : state.player);

  function buildReplayClock(keepCount = 0) {
    const n = state.plays.length;
    state.replayClock = new Clock(n * state.interval + 2);
    if (keepCount > 0) state.replayClock.seek((keepCount - 1) * state.interval + 1.01);
  }

  const replayTime = (index) => index * state.interval + 1;

  /* ------------------------------------------------------------ reveal logic */

  const popWorthy = (p) => state.mode === "replay" || (p.video_time !== null && p.video_time !== undefined);

  function revealedAt(t) {
    if (state.mode === "replay") {
      return state.plays.filter((_, i) => replayTime(i) <= t).map((p) => p.play_id);
    }
    let last = -1;
    state.plays.forEach((p, i) => {
      if (p.video_time !== null && p.video_time !== undefined && p.video_time <= t) last = i;
    });
    return state.plays.slice(0, last + 1).map((p) => p.play_id);
  }

  function markTime(p, i) {
    return state.mode === "replay" ? replayTime(i) : p.video_time;
  }

  function tick() {
    const clk = activeClock();
    if (!clk || !state.plays.length) return;
    const t = clk.getTime();

    const dur = clk.getDuration() || standInDuration();
    if (Math.abs(dur - state.duration) > 0.5) { state.duration = dur; renderMarks(); }
    $("#playhead").style.left = `${Math.min(100, (t / state.duration) * 100)}%`;
    document.querySelectorAll("#marks li").forEach((li) => li.classList.toggle("passed", Number(li.dataset.t) <= t));
    $("#playBtn").textContent = clk.isPlaying() ? "Pause" : "Play";

    const ids = revealedAt(t);
    const sig = ids.join("|");
    if (sig === state.revealedSig) return drawOverlay(t);

    const before = new Set(state.revealedIds);
    const fresh = ids.filter((id) => !before.has(id));
    const movedForward = ids.length > state.revealedIds.length;
    state.revealedIds = ids;
    state.revealedSig = sig;

    const freshPops = fresh.filter((id) => popWorthy(state.byId.get(id)));
    state.animateId = null;
    if (movedForward && freshPops.length) {
      state.latestId = freshPops[freshPops.length - 1];
      state.animateId = state.latestId;
      state.closed.delete(state.latestId);
      showLowerThird(state.byId.get(state.latestId));
    } else if (!ids.includes(state.latestId)) {
      state.latestId = [...ids].reverse().find((id) => popWorthy(state.byId.get(id))) || ids[ids.length - 1] || null;
    }
    renderFeed();
    renderScore();
    drawOverlay(t);
  }

  // Hook for Arav's computer-vision lines. Only works with an .mp4 (a YouTube
  // embed does not expose its frames). Define window.drawOverlay = ({ctx, time,
  // play, width, height}) => {...} in a separate script to draw.
  function drawOverlay(t) {
    if (state.playerKind !== "mp4" || typeof window.drawOverlay !== "function") return;
    const canvas = $("#overlay");
    const { width, height } = canvas.getBoundingClientRect();
    if (canvas.width !== Math.round(width)) { canvas.width = Math.round(width); canvas.height = Math.round(height); }
    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    window.drawOverlay({ ctx, time: t, play: state.byId.get(state.latestId) || null, width: canvas.width, height: canvas.height });
  }

  /* ------------------------------------------------------------ helped / hurt from the viewer's side */

  function teamName(abbr) {
    const g = state.config.game;
    if (abbr === g.away.abbr) return g.away.name;
    if (abbr === g.home.abbr) return g.home.name;
    return abbr;
  }

  function viewOf(card) {
    let impact = card.impact || "neutral";
    let team = card.impact_team || null;
    let wp = typeof card.wp_change === "number" ? card.wp_change : null;
    if (state.team && team && team !== state.team) {
      impact = impact === "helped" ? "hurt" : impact === "hurt" ? "helped" : "neutral";
      wp = wp === null ? null : -wp;
      team = state.team;
    } else if (state.team && !team) {
      team = state.team;
    }
    const name = team ? teamName(team) : null;
    const label = impact === "neutral"
      ? "Neutral"
      : `${impact === "helped" ? "Helped" : "Hurt"} ${name ? `the ${name}` : "your team"}`;
    return { impact, name, wp, label };
  }

  /* ------------------------------------------------------------ rendering */

  const quarterLabel = (q) => (q === null || q === undefined ? null : Number(q) >= 5 ? "OT" : `Q${q}`);

  function whenText(c, withSituation = true) {
    const parts = [[quarterLabel(c.quarter), c.clock].filter(Boolean).join(" ")];
    if (withSituation && c.situation) parts.push(c.situation);
    return parts.filter(Boolean).join(", ");
  }

  const isOpen = (id) => state.opened.has(id) || (id === state.latestId && !state.closed.has(id));

  function toggle(id) {
    if (isOpen(id)) { state.closed.add(id); state.opened.delete(id); }
    else { state.opened.add(id); state.closed.delete(id); }
    state.animateId = null;
    renderFeed();
    const btn = document.querySelector(`.card[data-id="${CSS.escape(id)}"] .card-head`);
    if (btn) btn.focus();
  }

  function wpRow(v) {
    if (v.wp === null || !v.name) return null;
    const pct = Math.round(v.wp * 100);
    const width = Math.min(Math.abs(v.wp), 0.5) * 100; // 50 points fills one side
    const bar = el("i", { class: v.wp >= 0 ? "up" : "down" });
    bar.style.width = `${width}%`;
    if (v.wp < 0) bar.style.left = `${50 - width}%`;
    return el("div", { class: "wp" },
      el("span", {}, `${v.name} win chance ${pct >= 0 ? "+" : ""}${pct}%`),
      el("span", { class: "wp-bar", role: "img", "aria-label": `${v.name} win chance changed by ${pct} percent` }, bar));
  }

  function cardEl(c) {
    const v = viewOf(c);
    const open = isOpen(c.play_id);
    const classes = ["card", open && "open", c.play_id === state.latestId && "latest", c.play_id === state.animateId && "arrive"];
    const bodyId = `body-${c.play_id}`;

    const head = el("button", { class: "card-head", type: "button", "aria-expanded": String(open), "aria-controls": bodyId },
      el("span", { class: "when" }, whenText(c)),
      el("span", { class: "headline" }, c.headline || "Big moment"),
      el("span", { class: `tag ${v.impact}` }, v.label));
    head.addEventListener("click", () => toggle(c.play_id));

    const details = [];
    if (c.who) details.push(el("dt", {}, "Who"), el("dd", {}, c.who));
    if (c.why_it_matters) details.push(el("dt", {}, "Why it matters"), el("dd", {}, c.why_it_matters));

    const links = (c.read_more || []).filter((l) => /^https?:\/\//.test(l.url));
    const body = el("div", { class: "card-body", id: bodyId },
      c.what_happened && el("p", {}, c.what_happened),
      details.length > 0 && el("dl", {}, details),
      wpRow(v),
      c.pop_note && el("p", { class: "pop" }, c.pop_note),
      links.length > 0 && el("ul", { class: "read-more", "aria-label": "Read more" },
        links.map((l) => el("li", {}, el("a", { href: l.url, target: "_blank", rel: "noopener noreferrer" },
          el("span", {}, l.title || l.url), l.source && el("span", { class: "src" }, l.source))))));

    return el("li", { class: classes.filter(Boolean).join(" "), "data-id": c.play_id }, head, body);
  }

  function renderFeed() {
    const ids = [...state.revealedIds].reverse();
    $("#empty").hidden = ids.length > 0;
    $("#cards").replaceChildren(...ids.map((id) => state.byId.get(id)).filter(Boolean).map(cardEl));
  }

  function renderScore() {
    const lastId = state.revealedIds[state.revealedIds.length - 1];
    const last = lastId ? state.byId.get(lastId) : null;
    const score = (last && last.score) || { away: 0, home: 0 };
    const prev = state.lastScore || { away: 0, home: 0 };
    for (const side of ["away", "home"]) {
      const node = $(`#${side}Pts`);
      const val = score[side] ?? 0;
      node.textContent = val;
      if (state.lastScore && val !== prev[side]) {
        node.classList.remove("bump");
        void node.offsetWidth; // restart the animation
        node.classList.add("bump");
      }
    }
    state.lastScore = { away: score.away ?? 0, home: score.home ?? 0 };
    const isFinal = last && lastId === state.plays[state.plays.length - 1].play_id;
    $("#gameClock").textContent = !last ? "Kickoff" : isFinal ? (Number(last.quarter) >= 5 ? "Final, OT" : "Final") : whenText(last, false);
  }

  function renderMarks() {
    const dur = state.duration || standInDuration();
    const marks = state.plays.map((p, i) => [p, markTime(p, i)])
      .filter(([, t]) => t !== null && t !== undefined)
      .map(([p, t]) => {
        const v = viewOf(p);
        const btn = el("button", { type: "button", "aria-label": `${whenText(p, false)}: ${p.headline || "Big moment"}. ${v.label}.`, title: p.headline || "" });
        btn.addEventListener("click", () => seekTo(t + 0.25)); // a hair past, so the card shows even while paused
        const li = el("li", { class: v.impact, "data-t": t }, btn);
        li.style.left = `${Math.min(100, (t / dur) * 100)}%`;
        return li;
      });
    $("#marks").replaceChildren(...marks);
  }

  function showLowerThird(card) {
    if (!card) return;
    const v = viewOf(card);
    $("#ltTag").className = `lt-tag tag ${v.impact}`;
    $("#ltTag").textContent = v.label;
    $("#ltHead").textContent = card.headline || "Big moment";
    const lt = $("#lowerThird");
    lt.classList.add("show");
    clearTimeout(state.ltTimer);
    state.ltTimer = setTimeout(() => lt.classList.remove("show"), LOWER_THIRD_MS);
  }

  function refreshStandIn() {
    const box = $("#standIn");
    if (state.mode === "replay") {
      box.hidden = false;
      $("#standInText").textContent = `Replay without video. A new play arrives every ${state.interval} seconds, the way it would during a live game.`;
    } else if (state.playerKind === "stand-in") {
      box.hidden = false;
      $("#standInText").textContent = state.standInReason;
    } else {
      box.hidden = true;
    }
  }

  function setStatus(text, isError = false) {
    const s = $("#status");
    s.textContent = text;
    s.classList.toggle("error", isError);
  }

  function setBanner(notices) {
    const b = $("#banner");
    const text = [...new Set(notices.filter(Boolean))].join(" ");
    b.textContent = text;
    b.hidden = !text;
  }

  /* ------------------------------------------------------------ controls */

  function seekTo(t) {
    const clk = activeClock();
    if (!clk) return;
    clk.seek(t);
    tick();
  }

  function fillControls() {
    const cfg = state.config;
    document.title = `Play Explainer: ${cfg.game.title}`;
    $("#gameTitle").textContent = `${cfg.game.title}, Week ${cfg.game.week}`;

    for (const side of ["away", "home"]) {
      const t = cfg.game[side];
      const box = $(`#${side}Team`);
      box.style.setProperty("--team-color", t.color);
      box.querySelector(".name").textContent = t.name;
    }

    const personaSel = $("#persona");
    personaSel.replaceChildren(...cfg.personas.map((p) => {
      const suffix = p.selectable ? (p.ready ? "" : " (written live, slower)") : " (not generated yet)";
      return el("option", { value: p.id, disabled: !p.selectable, title: p.blurb || "" }, p.label + suffix);
    }));
    personaSel.value = state.persona;

    $("#language").replaceChildren(...cfg.languages.map((l) => el("option", { value: l.code }, l.label)));
    $("#language").value = state.language;

    const seg = $("#teamSeg");
    const choices = [[cfg.game.away.abbr, cfg.game.away.name], [cfg.game.home.abbr, cfg.game.home.name], ["", "No team"]];
    seg.replaceChildren(...choices.map(([abbr, label]) => {
      const b = el("button", { type: "button", "aria-pressed": String((state.team || "") === abbr) }, label);
      b.addEventListener("click", () => {
        state.team = abbr || null;
        seg.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
        onProfileChange();
      });
      return b;
    }));

    $("#notes").value = state.notes;
  }

  function onProfileChange() {
    savePrefs();
    renderFeed();     // flip helped/hurt right away from the cards we have
    renderMarks();
    loadPlays();      // then fetch wording written for this viewer
  }

  function wireControls() {
    $("#persona").addEventListener("change", (e) => { state.persona = e.target.value; onProfileChange(); });
    $("#language").addEventListener("change", (e) => {
      state.language = e.target.value;
      document.documentElement.lang = state.language;
      onProfileChange();
    });
    $("#notesForm").addEventListener("submit", (e) => {
      e.preventDefault();
      state.notes = $("#notes").value.trim();
      onProfileChange();
    });

    $("#playBtn").addEventListener("click", () => {
      const clk = activeClock();
      if (!clk) return;
      if (clk.isPlaying()) clk.pause(); else clk.play();
      tick();
    });
    $("#restartBtn").addEventListener("click", () => {
      state.opened.clear();
      state.closed.clear();
      seekTo(0);
    });

    document.querySelectorAll(".modes button").forEach((b) => b.addEventListener("click", () => setMode(b.dataset.mode)));

    $("#speed").addEventListener("change", (e) => {
      const count = state.revealedIds.length;
      const wasPlaying = state.replayClock && state.replayClock.isPlaying();
      state.interval = Number(e.target.value);
      buildReplayClock(count);
      if (wasPlaying) state.replayClock.play();
      refreshStandIn();
      renderMarks();
      tick();
    });
  }

  function setMode(mode) {
    if (mode === state.mode) return;
    const prev = activeClock();
    if (prev && prev.isPlaying()) prev.pause();
    state.mode = mode;
    document.querySelectorAll(".modes button").forEach((b) => b.setAttribute("aria-checked", String(b.dataset.mode === mode)));
    $("#speedWrap").hidden = mode !== "replay";
    if (mode === "replay") buildReplayClock(0);
    state.revealedSig = null;
    state.revealedIds = [];
    state.latestId = null;
    state.duration = 0;
    refreshStandIn();
    tick();
    renderMarks();
    if (!state.plays.length) renderFeed();
  }

  async function loadPlays() {
    const seq = ++state.fetchSeq;
    setStatus(state.plays.length ? "Rewriting the cards for this viewer…" : "Loading the cards…");
    try {
      const res = await api.plays({ persona: state.persona, language: state.language, team: state.team, notes: state.notes });
      if (seq !== state.fetchSeq) return; // a newer request replaced this one
      state.plays = [...res.plays].sort((a, b) => (a.order ?? 0) - (b.order ?? 0));
      state.byId = new Map(state.plays.map((p) => [p.play_id, p]));
      setBanner([...(state.config.notices || []), ...(res.notices || [])]);
      const timed = state.plays.filter((p) => p.video_time !== null && p.video_time !== undefined).length;
      setStatus(`${state.plays.length} big moments, ${timed} synced to the video.`);
      if (state.mode === "replay") buildReplayClock(state.revealedIds.length);
      state.revealedSig = null;
      state.duration = 0;
      tick();
      renderMarks();
      if (!state.revealedIds.length) renderFeed();
    } catch (err) {
      if (seq !== state.fetchSeq) return;
      setStatus(`Couldn't load the cards. ${err.message}${state.plays.length ? " Showing the last set." : ""}`, true);
    }
  }

  /* ------------------------------------------------------------ start */

  async function start() {
    wireControls();
    try {
      state.config = await api.config();
    } catch (err) {
      setStatus(`Couldn't reach the viewer server. ${err.message} Start it with: python3 viewer/server.py`, true);
      return;
    }
    const prefs = loadPrefs();
    const selectable = state.config.personas.filter((p) => p.selectable).map((p) => p.id);
    state.persona = selectable.includes(prefs.persona) ? prefs.persona
      : selectable.includes(state.config.default_persona) ? state.config.default_persona : selectable[0];
    state.language = state.config.languages.some((l) => l.code === prefs.language) ? prefs.language : "en";
    const teams = [state.config.game.away.abbr, state.config.game.home.abbr];
    state.team = teams.includes(prefs.team) ? prefs.team : null;
    state.notes = typeof prefs.notes === "string" ? prefs.notes : "";

    fillControls();
    setBanner(state.config.notices || []);
    await loadPlays();
    await setupVideo();
    refreshStandIn();
    renderMarks();
    setInterval(tick, 250);
    window.addEventListener("resize", renderMarks);
  }

  start();
})();
