const api = () => window.pywebview.api;
const el = (id) => document.getElementById(id);
const icon = (name) => `<svg class="ic" aria-hidden="true"><use href="#i-${name}"/></svg>`;

async function refresh() {
  const s = await api().get_status();
  const st = el("status");
  const btn = el("reconnect");
  const conn = s.connection || (s.logged_in ? "ok" : "expired");
  if (conn === "ok") {
    st.textContent = "Logged in"; st.className = "status ok";
  } else if (conn === "none") {
    // Fresh install, no account yet — steer to Add account, not the dead-end
    // Reconnect (which can't onboard a brand-new user).
    st.textContent = "No account yet"; st.className = "status bad";
    el("bannerText").textContent = "Connect your Trace account to see your games.";
    btn.textContent = "Connect Trace account";
    btn.onclick = connectAccount;
  } else {
    st.textContent = "Session expired"; st.className = "status bad";
    el("bannerText").textContent = "Your Trace login has expired. Reconnect to keep downloading.";
    btn.textContent = "Reconnect";
    btn.onclick = reconnectFlow;
  }
  el("connBanner").hidden = conn === "ok";
  const sd = el("statusDetail");
  if (sd) {
    sd.textContent = (conn !== "ok" && s.login_detail) ? ("Diagnostic: " + s.login_detail) : "";
    st.title = s.login_detail || "";
  }
  el("auto").checked = s.auto;
  el("login").checked = s.login;
  el("loginRow").hidden = !s.auto;
  showAutoOptions(s.auto, s.auto_options);
  showAutoStatus(s.auto, "");
  if (s.welcome) showWelcome();
  if (s.settings) el("quality").value = s.settings.quality;
  if (s.settings) el("combine").checked = s.settings.combine !== false;
  if (s.settings && s.settings.output_dir) {
    el("outDir").textContent = s.settings.output_dir;
    el("outDir").title = s.settings.output_dir;
  }
  el("version").textContent = "TraceDown v" + (s.version || "");
  el("aboutVersion").textContent = "TraceDown version " + (s.version || "");
  analyticsLoaded = false;   // account or login may have changed; reload on next visit
  _analytics = null;
  statsRequest = null;
  await renderAccounts();
  await loadGames();
  // Once the list and thumbnails have had a head start, quietly save the newest
  // games' stats (a no-op until this account's Analytics has been opened once).
  clearTimeout(statsTimer);
  statsTimer = setTimeout(() => { api().save_stats().catch(() => {}); }, 6000);
}
let statsTimer = null;

async function loadGames() {
  const status = el("gamesStatus");
  const retry = el("retryGames");
  retry.hidden = true;
  status.classList.remove("warn");
  status.textContent = "Loading games…";
  renderGames([]);
  el("games").innerHTML = '<div class="skeleton"></div>'.repeat(3);
  try {
    const result = await api().get_games();
    renderGames(result.games);
    status.classList.toggle("warn", result.errors.length > 0);
    status.textContent = result.errors.length
      ? "Some games could not be loaded. " + result.errors.join("\n")
      : result.games.length ? "" : "No available games were found for this account. Check that your current team is connected.";
    retry.hidden = result.games.length > 0 && result.errors.length === 0;
  } catch (error) {
    renderGames([]);
    status.classList.add("warn");
    status.textContent = "Could not load games. " + String(error);
    retry.hidden = false;
  }
}

el("retryGames").onclick = loadGames;

async function renderAccounts() {
  const data = await api().list_accounts();
  const sel = el("account");
  sel.innerHTML = "";
  for (const a of data.accounts) {
    const o = document.createElement("option");
    o.value = a.id; o.textContent = a.label;
    if (a.id === data.active) o.selected = true;
    sel.appendChild(o);
  }
  const add = document.createElement("option");
  add.value = "__add__"; add.textContent = "+ Add account…";
  sel.appendChild(add);
}

// Show the most-recent few; the rest hide behind a button. Cards sit three to a
// row, so six fills two rows.
const VISIBLE_GAMES = { list: 5, cards: 6 };

// "cards" (the default), "list" or "single" (one game at a time) — a per-person
// preference, remembered on this computer.
let layout = "cards";
try {
  const stored = localStorage.getItem("layout");
  if (stored === "list" || stored === "single") layout = stored;
} catch (e) { /* not available */ }
let singleIndex = 0;   // which game the single layout is showing, within the current filter

function applyLayout() {
  el("games").classList.toggle("is-cards", layout === "cards");
  el("games").classList.toggle("is-single", layout === "single");
  el("games-view").classList.toggle("showing-single", layout === "single");
  document.querySelectorAll("#layoutToggle button").forEach((b) =>
    b.classList.toggle("on", b.dataset.layout === layout));
}

const gameState = new Map();   // id -> "new" | "saved", for every game (shown or not)

// "W 5–3" for a score entered on Trace (our team first), or "" when there is none.
function scoreText(score) {
  return score ? `${{ win: "W", loss: "L", draw: "D" }[score.result]} ${score.us}–${score.them}` : "";
}

// Fill a score badge, or hide it when the game has no score.
function showScore(badge, score) {
  badge.hidden = !score;
  badge.classList.remove("win", "loss", "draw");
  if (!score) return;
  const word = { win: "Won", loss: "Lost", draw: "Drew" }[score.result];
  badge.classList.add(score.result);
  badge.textContent = scoreText(score);
  badge.title = `${word} ${score.us}–${score.them} (score entered on Trace)`;
}

function appendGame(box, g) {
  const div = document.createElement("div");
  div.className = "game"; div.id = "g-" + g.id;
  div.innerHTML = `
    <div class="thumb"><span class="thumb-hint"><b>Game Page</b><small>Stats &amp; Details</small></span><span class="thumb-download">${icon("download")}<b>Download Full Game</b><small>Then watch it right here</small></span></div>
    <div class="meta">
      <div class="opp"><span class="opp-name"></span><span class="badge">New</span><span class="score" hidden></span></div>
      <div class="date"></div>
      <div class="err"></div>
      <div class="mini" hidden><i></i></div>
    </div>
    <div class="action"></div>
    <div class="progress" hidden>
      <div class="bar"><i></i></div>
      <div class="speed"></div>
    </div>
    <div class="hl-panel" hidden></div>`;
  const name = "vs " + (g.opponent || g.title);
  div.querySelector(".opp-name").textContent = name;
  div.querySelector(".opp-name").title = name;
  div.querySelector(".date").textContent = g.date_label || g.date;
  showScore(div.querySelector(".score"), g.score);
  // In the list and card layouts, clicking a game (anywhere but its buttons)
  // opens that game's own page.
  div.addEventListener("click", (e) => {
    if (layout === "single" || e.target.closest("button, .hl-panel")) return;
    openSingle(g.id);
  });
  // On the game's own page, the thumbnail of a game that isn't saved yet offers the download.
  div.querySelector(".thumb").addEventListener("click", () => {
    if (layout !== "single" || gameState.get(g.id) === "saved" || div.classList.contains("is-busy")) return;
    startDownload(g.id);                     // waits in line if another download is running
  });
  box.appendChild(div);
  if (gameState.get(g.id) === "saved") setSaved(div, g.id);
  else setIdle(div, g.id);
  loadThumb(div, g);
}

let allGames = [];
let gameFilter = "all";   // "all" | "new" | "saved"

function renderGames(games) {
  allGames = games;
  gameState.clear();
  games.forEach((g) => gameState.set(g.id, g.state));
  partial.clear();
  games.forEach((g) => { if (g.partial != null) partial.set(g.id, g.partial); });
  clipCount.clear();
  games.forEach((g) => { if (g.clips) clipCount.set(g.id, g.clips); });
  el("gameTools").hidden = games.length === 0;
  renderSeasonSummary();
  renderGameList();
}

// Record and goals from the scores entered on Trace, over the games listed.
function renderSeasonSummary() {
  const box = el("seasonSummary");
  box.hidden = !allGames.some((g) => g.score);
  if (!box.hidden) box.replaceChildren(...seasonItems());
}

function matchesFilter(g, query) {
  if (gameFilter !== "all" && gameState.get(g.id) !== gameFilter) return false;
  const text = `${g.opponent || g.title} ${g.date_label || ""} ${g.date}`.toLowerCase();
  return query.split(/\s+/).every((word) => text.includes(word));
}

function filteredGames() {
  const query = el("gameSearch").value.trim().toLowerCase();
  return allGames.filter((g) => matchesFilter(g, query));
}

function renderGameList() {
  if (windowFull) leaveFull();      // the video about to be redrawn is the one filling the screen
  const box = el("games");
  box.innerHTML = "";
  const query = el("gameSearch").value.trim().toLowerCase();
  const narrowed = query !== "" || gameFilter !== "all";
  const games = filteredGames();
  if (narrowed && games.length === 0 && allGames.length > 0) {
    const none = document.createElement("div");
    none.className = "notice";
    none.textContent = "No games match.";
    box.appendChild(none);
    return;
  }
  if (layout === "single") { renderSingle(box, games); return; }
  // Games arrive newest-first, so the first few are the most recent. A search or
  // filter shows every match — hiding results behind a button would defeat it.
  const visible = narrowed ? games.length : VISIBLE_GAMES[layout];
  games.slice(0, visible).forEach((g) => appendGame(box, g));
  const rest = games.slice(visible);
  if (rest.length === 0) return;
  const more = document.createElement("button");
  more.className = "show-more";
  more.textContent = `Show all ${games.length} games`;
  more.onclick = () => {
    more.remove();
    rest.forEach((g) => appendGame(box, g));
  };
  box.appendChild(more);
}

// Single layout: one game's own page — the video (or thumbnail), its buttons and
// its analytics — with arrows (and the arrow keys) to move through the games.
let returnLayout = null;   // the layout to go back to when a game was opened by clicking it

function openSingle(id) {
  const index = filteredGames().findIndex((g) => g.id === id);
  if (index < 0) return;
  if (layout !== "single") returnLayout = layout;
  layout = "single";          // not saved as the preference: this is a visit, not a choice
  singleIndex = index;
  applyLayout();
  renderGameList();
  document.querySelector("main").scrollTo(0, 0);
}

function renderSingle(box, games) {
  if (games.length === 0) return;
  singleIndex = Math.max(0, Math.min(singleIndex, games.length - 1));
  const nav = node("div", "single-nav");
  if (returnLayout) {
    const back = labelButton("prev", "All games", "Back to all games.", () => {
      layout = returnLayout;
      returnLayout = null;
      applyLayout();
      renderGameList();
    });
    back.classList.add("single-back");
    nav.append(back);
  }
  const prev = iconButton("prev", "Newer game (left arrow key)", () => stepSingle(-1));
  const next = iconButton("next", "Older game (right arrow key)", () => stepSingle(1));
  prev.disabled = singleIndex === 0;
  next.disabled = singleIndex === games.length - 1;
  nav.append(prev, node("span", "single-count", `Game ${singleIndex + 1} of ${games.length}`), next);
  box.appendChild(nav);
  const g = games[singleIndex];
  appendGame(box, g);
  const card = el("g-" + g.id);
  // Highlights or recaps play here even without the full game. The timeline is
  // drawn once the player is in place: your bookmarks need to know what is saved.
  attachPlayer(card, g.id).finally(() => attachTimeline(card, g));
  appendGameStats(box, g);
}

function stepSingle(delta) {
  singleIndex += delta;
  renderGameList();
}

document.addEventListener("keydown", (e) => {
  if (layout !== "single" || el("games-view").hidden) return;
  // In the video player the arrow keys scrub, as they should.
  if (e.metaKey || e.ctrlKey || e.altKey || /^(INPUT|SELECT|TEXTAREA|VIDEO)$/.test(e.target.tagName)) return;
  if (e.target.closest && e.target.closest(".player-frame")) return;
  if (e.key === "ArrowLeft") { e.preventDefault(); stepSingle(-1); }
  if (e.key === "ArrowRight") { e.preventDefault(); stepSingle(1); }
});

// Whatever is saved for a game plays right where its thumbnail was — the full
// game, the highlight reel, single clips and player recaps — with the usual
// play, scrub and volume controls and a "Now playing" picker between them.
async function attachPlayer(card, id) {
  if (layout !== "single" || card.querySelector(".player")) return;
  let media = null;
  try { media = await api().game_media(id); } catch (e) { /* keep the thumbnail */ }
  if (!media || el("g-" + id) !== card || card.querySelector(".player")) return;
  const sources = [];
  media.full.forEach((part, i) => sources.push({
    group: "Full game", label: part.label, url: part.url, full: true,
    half: media.full.length > 1 ? i + 1 : 0 }));      // half 0 = both halves in one file
  if (media.reel) sources.push({ group: "Highlights", label: "Team Highlight Reel", url: media.reel });
  media.clips.forEach((c) => sources.push({ group: "Highlights", label: c.label, url: c.url,
    clipHalf: c.half, clipStart: c.start }));
  media.recaps.forEach((r) => sources.push({ group: "Player recaps", label: r.label, url: r.url }));
  if (sources.length === 0) return;

  const thumb = card.querySelector(".thumb");
  const wrap = node("div", "player");
  const video = document.createElement("video");
  video.preload = "metadata";
  video.playsInline = true;
  if (thumbUrls.has(id)) video.poster = thumbUrls.get(id);
  // If the file can't be played (moved, or an unsupported format), go back to the thumbnail.
  video.addEventListener("error", () => { wrap.remove(); thumb.hidden = false; card._player = null; });
  const frame = node("div", "player-frame is-paused");
  frame.tabIndex = 0;
  frame.append(video, videoControls(frame, video));
  wrap.append(frame);

  const bar = node("div", "player-bar");
  const label = node("span", "player-label", "Now playing");
  const picker = document.createElement("select");
  picker.setAttribute("aria-label", "Now playing");
  const addOption = (src, i) => {
    let group = [...picker.querySelectorAll("optgroup")].find((x) => x.label === src.group);
    if (!group) {
      group = document.createElement("optgroup");
      group.label = src.group;
      picker.append(group);
    }
    const option = node("option", null, src.label);
    option.value = String(i);
    group.append(option);
    label.hidden = picker.hidden = sources.length < 2;      // one thing to play needs no picker
  };
  sources.forEach(addOption);
  const tools = node("div", "player-tools");
  tools.append(iconButton("keyboard", "Keyboard shortcuts (?)", () => el("shortcuts").showModal()));
  bar.append(label, picker, node("span", "spacer"), tools);
  const notes = node("div", "player-notes");
  wrap.append(bar, notes);

  const player = { video, sources, current: -1, onShow: [] };
  // Switch what is playing; `then` runs once the new video is ready to seek.
  player.show = (index, then) => {
    if (index === player.current) { if (then) then(); return; }
    player.current = index;
    picker.value = String(index);
    video.src = sources[index].url;
    if (then) video.addEventListener("loadedmetadata", then, { once: true });
    card.classList.toggle("is-watching-full", !!sources[index].full);
    player.onShow.forEach((fn) => fn());
  };
  // Something new to play (a clip just cut); returns its place in the picker.
  player.addSource = (src) => {
    sources.push(src);
    addOption(src, sources.length - 1);
    return sources.length - 1;
  };
  // A line of words and buttons under the player, one per subject; nothing clears it.
  player.note = (slot, ...content) => {
    let line = notes.querySelector(`[data-slot="${slot}"]`);
    if (!content.length || content[0] == null) { if (line) line.remove(); return; }
    if (!line) {
      line = node("div", "player-note");
      line.dataset.slot = slot;
      notes.append(line);
    }
    line.replaceChildren(...content);
  };
  picker.onchange = () => player.show(Number(picker.value), () => video.play().catch(() => {}));
  video.addEventListener("timeupdate", () => movePlayhead(card));
  card._player = player;
  player.show(0);
  let kept = 0;
  video.addEventListener("timeupdate", () => {
    if (Math.abs(video.currentTime - kept) >= 5) { kept = video.currentTime; rememberPosition(id, player); }
    // Once it has played on a little, "Resumed at…" has said its piece.
    if (player.resumedAt != null && video.currentTime > player.resumedAt + 10) {
      player.resumedAt = null;
      player.note("resume", null);
    }
  });
  video.addEventListener("pause", () => rememberPosition(id, player));
  player.onShow.push(() => { player.resumedAt = null; player.note("resume", null); });
  restorePosition(card, id);
  thumb.hidden = true;
  thumb.after(wrap);
}

// The app's own play / scrub / volume bar (for full screen there is Watch Game,
// which opens the video in the computer's own player). The built-in controls
// darken the picture while they are showing; these sit in a small bar instead.
function videoControls(frame, video) {
  const bar = node("div", "vc");
  const play = iconButton("play", "Play or pause (space)", () => (video.paused ? video.play() : video.pause()));
  const time = node("span", "vc-time", "0:00 / 0:00");
  const seek = document.createElement("input");
  seek.type = "range"; seek.className = "vc-seek"; seek.min = "0"; seek.max = "0"; seek.step = "0.1"; seek.value = "0";
  seek.setAttribute("aria-label", "Position in the video");
  const mute = iconButton("volume", "Mute", () => { video.muted = !video.muted; });
  const volume = document.createElement("input");
  volume.type = "range"; volume.className = "vc-volume"; volume.min = "0"; volume.max = "1"; volume.step = "0.05"; volume.value = "1";
  volume.setAttribute("aria-label", "Volume");
  const speed = document.createElement("select");
  speed.className = "vc-speed";
  speed.setAttribute("aria-label", "Playback speed");
  speed.title = "Playback speed (< and > keys)";
  SPEEDS.forEach((rate) => {
    const option = node("option", null, rate + "×");
    option.value = String(rate);
    speed.append(option);
  });
  speed.onchange = () => setSpeed(video, Number(speed.value));
  const full = iconButton("full", "Full screen (F)", () => toggleFull(frame));
  bar.append(play, time, seek, speed, mute, volume, full);

  const length = (secs) => {
    const s = Math.max(0, Math.floor(secs || 0));
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = String(s % 60).padStart(2, "0");
    return h ? `${h}:${String(m).padStart(2, "0")}:${r}` : `${m}:${r}`;
  };
  let dragging = false;
  const show = () => {
    if (!dragging) seek.value = String(video.currentTime || 0);
    time.textContent = `${length(dragging ? Number(seek.value) : video.currentTime)} / ${length(video.duration)}`;
  };
  const showState = () => {
    play.innerHTML = icon(video.paused ? "play" : "pause");
    frame.classList.toggle("is-paused", video.paused);
    mute.innerHTML = icon(video.muted || video.volume === 0 ? "mute" : "volume");
    volume.value = String(video.muted ? 0 : video.volume);
  };
  video.addEventListener("loadedmetadata", () => { seek.max = String(video.duration || 0); show(); });
  video.addEventListener("timeupdate", show);
  for (const name of ["play", "pause", "volumechange", "emptied"]) video.addEventListener(name, showState);
  video.addEventListener("ratechange", () => { speed.value = String(video.playbackRate); });
  setSpeed(video, savedSpeed());
  speed.value = String(video.playbackRate);      // no "ratechange" is sent when it was already this
  seek.addEventListener("input", () => { dragging = true; show(); });
  seek.addEventListener("change", () => { video.currentTime = Number(seek.value); dragging = false; });
  volume.addEventListener("input", () => { video.volume = Number(volume.value); video.muted = Number(volume.value) === 0; });
  video.addEventListener("click", () => (video.paused ? video.play() : video.pause()));

  // With the player focused, the arrow keys step 5 seconds (elsewhere on the page they change game).
  frame.addEventListener("keydown", (e) => {
    if (e.target.tagName === "INPUT") return;
    if (e.key === "ArrowLeft") { e.preventDefault(); e.stopPropagation(); video.currentTime = Math.max(0, video.currentTime - 5); }
    if (e.key === "ArrowRight") { e.preventDefault(); e.stopPropagation(); video.currentTime = Math.min(video.duration || 0, video.currentTime + 5); }
  });
  for (const b of bar.querySelectorAll("button")) b.classList.remove("icon-btn");
  showState();
  return bar;
}

// ---- watching: speed, frame-step, full screen and the keyboard ----
const SPEEDS = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 2];
const FRAME = 1 / 30;       // saved games are 30 frames a second

function savedSpeed() {
  try {
    const rate = Number(localStorage.getItem("speed"));
    return SPEEDS.includes(rate) ? rate : 1;
  } catch (e) { return 1; }
}

// The speed is yours, not the game's: it is kept for every video from now on.
function setSpeed(video, rate) {
  video.defaultPlaybackRate = rate;      // so it survives switching to another video
  video.playbackRate = rate;
  try { localStorage.setItem("speed", String(rate)); } catch (e) { /* not kept */ }
}

function stepSpeed(video, dir) {
  const at = SPEEDS.indexOf(video.playbackRate);
  setSpeed(video, SPEEDS[Math.max(0, Math.min(SPEEDS.length - 1, (at < 0 ? SPEEDS.indexOf(1) : at) + dir))]);
}

function seekBy(video, secs) {
  video.currentTime = Math.max(0, Math.min(video.duration || 0, video.currentTime + secs));
}

function stepFrame(video, dir) {
  video.pause();
  seekBy(video, dir * FRAME);
}

// A word over the picture for a moment, for changes made from the keyboard.
function flash(frame, text) {
  frame.querySelectorAll(".player-flash").forEach((n) => n.remove());
  const tip = node("div", "player-flash", text);
  frame.append(tip);
  setTimeout(() => tip.remove(), 1000);
}

// Full screen is two things: the video fills the app's window, and the window
// fills the screen. The second is asked of the app and may not be possible.
let windowFull = false;
function setWindowFull(on) {
  if (windowFull === on) return;
  windowFull = on;
  try { api().toggle_fullscreen(); } catch (e) { /* the video still fills the window */ }
}
function toggleFull(frame) {
  const on = !frame.classList.contains("is-full");
  document.querySelectorAll(".player-frame.is-full").forEach((f) => f.classList.remove("is-full"));
  frame.classList.toggle("is-full", on);
  setWindowFull(on);
}
function leaveFull() {
  document.querySelectorAll(".player-frame.is-full").forEach((f) => f.classList.remove("is-full"));
  setWindowFull(false);
}

// The game whose page is showing and has something to play, else null.
function activePlayer() {
  if (layout !== "single" || el("games-view").hidden) return null;
  const card = document.querySelector("#games .game");
  if (!card || !card._player) return null;
  return { card, id: card.id.slice(2), player: card._player, video: card._player.video,
    frame: card.querySelector(".player-frame") };
}

const playPause = ({ video }) => (video.paused ? video.play().catch(() => {}) : video.pause());
// What each key does on a game's page. Later sections add theirs.
const PLAYER_KEYS = {
  " ": playPause,
  k: playPause,
  j: ({ video }) => seekBy(video, -10),
  l: ({ video }) => seekBy(video, 10),
  ",": ({ video }) => stepFrame(video, -1),
  ".": ({ video }) => stepFrame(video, 1),
  "<": ({ video, frame }) => { stepSpeed(video, -1); flash(frame, video.playbackRate + "×"); },
  ">": ({ video, frame }) => { stepSpeed(video, 1); flash(frame, video.playbackRate + "×"); },
  m: ({ video, frame }) => { video.muted = !video.muted; flash(frame, video.muted ? "Muted" : "Sound on"); },
  f: ({ frame }) => toggleFull(frame),
  "?": () => el("shortcuts").showModal(),
};

document.addEventListener("keydown", (e) => {
  if (e.metaKey || e.ctrlKey || e.altKey || document.querySelector("dialog[open]")) return;
  const tag = e.target.tagName;
  // Typing is typing: a note with a "k" in it must not pause the video.
  if (tag === "TEXTAREA" || tag === "SELECT" || (tag === "INPUT" && e.target.type !== "range")) return;
  const active = activePlayer();
  if (!active) return;
  if (e.key === "Escape") { if (windowFull) { e.preventDefault(); leaveFull(); } return; }
  const key = e.key.length === 1 ? e.key.toLowerCase() : e.key;
  if (key === " " && tag === "BUTTON") return;      // space presses the focused button, as everywhere
  const action = PLAYER_KEYS[key];
  if (!action) return;
  e.preventDefault();
  action(active);
});
el("shortcutsClose").onclick = () => el("shortcuts").close();

// ---- where you stopped: kept per game on this computer ----
// Only the full game is remembered, as which file was playing (0 = the game in
// one file, 1 or 2 = a half) and how far into it.
const KEEP_POSITIONS = 200;

function positions() {
  try { return JSON.parse(localStorage.getItem("positions")) || {}; } catch (e) { return {}; }
}

function storePositions(all) {
  const ids = Object.keys(all);
  if (ids.length > KEEP_POSITIONS) {
    ids.sort((a, b) => (all[a].at || 0) - (all[b].at || 0))
      .slice(0, ids.length - KEEP_POSITIONS).forEach((id) => delete all[id]);
  }
  try { localStorage.setItem("positions", JSON.stringify(all)); } catch (e) { /* not kept */ }
}

function forgetPosition(id) {
  const all = positions();
  if (!(id in all)) return;
  delete all[id];
  storePositions(all);
}

function rememberPosition(id, player) {
  const src = player.sources[player.current];
  const video = player.video;
  if (!src || !src.full || !video.duration || video.currentTime < 10) return;
  if (video.duration - video.currentTime < 30) { forgetPosition(id); return; }      // watched to the end
  const all = positions();
  all[id] = { half: src.half, t: Math.round(video.currentTime), at: Date.now() };
  storePositions(all);
}

// Put the full game back where it was left, paused, and say so.
function restorePosition(card, id) {
  const player = card._player;
  const saved = positions()[id];
  if (!player || !saved) return;
  const index = player.sources.findIndex((s) => s.full && s.half === saved.half);
  if (index < 0) return;
  const video = player.video;
  const apply = () => {
    if (saved.t < 10 || saved.t > video.duration - 30) return;
    video.currentTime = saved.t;
    player.resumedAt = saved.t;
    const where = saved.half ? ` in the ${saved.half === 2 ? "2nd" : "1st"} half` : "";
    player.note("resume", node("span", null, `Resumed at ${clock(saved.t)}${where}`),
      labelButton("retry", "Start over", "Play this game from the beginning.", () => {
        video.currentTime = 0;
        player.resumedAt = null;
        forgetPosition(id);
        player.note("resume", null);
      }));
  };
  if (index !== player.current) player.show(index, apply);
  else if (video.readyState >= 1) apply();
  else video.addEventListener("loadedmetadata", apply, { once: true });
}

// ---- match timeline: when the shots and box entries happened; click to jump there ----
const MOMENT_WORDS = { "shot": "Shot", "opp-shot": "Opponent shot", "box-entry": "Box entry",
  "opp-box-entry": "Opponent box entry" };

function clock(seconds) {
  const s = Math.max(0, Math.round(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

// Where a moment sits in its own half ("2nd half 6:49"), which is how people talk about a game.
function momentText(m, line) {
  const inHalf = m.half === 2 && line.half1 ? m.t - line.half1 : m.t;
  return `${MOMENT_WORDS[m.label] || m.label} · ${m.half === 2 ? "2nd" : "1st"} half ${clock(inHalf)}`;
}

async function attachTimeline(card, g) {
  const data = await loadStatsQuietly();
  if (!card.isConnected || card.querySelector(".timeline")) return;
  const number = Number(g.id.split("-").pop());
  const game = data && data.games.find((x) => x.game_id === number);
  const line = game && game.timeline;
  if (!line || !line.moments.length) return;
  const total = line.duration || (line.moments[line.moments.length - 1].t + 120);
  const block = node("div", "timeline");
  block._line = line;
  block._total = total;
  const head = node("div", "row");
  const legend = node("div", "legend");
  for (const [cls, text] of [["us", "Us"], ["them", "Opponent"]]) {
    const item = node("span");
    item.append(node("i", "tl-key " + cls), text);
    legend.append(item);
  }
  legend.append(node("span", null, "Round = shot, small = box entry"));
  head.append(node("h3", null, "Match timeline"), node("span", "spacer"), legend);
  const track = node("div", "tl-track");
  if (line.half1) {
    const split = node("div", "tl-split");
    split.style.left = (line.half1 / total) * 100 + "%";
    track.append(split, node("span", "tl-half first", "1st half"), node("span", "tl-half second", "2nd half"));
    track.querySelector(".tl-half.second").style.left = (line.half1 / total) * 100 + "%";
  }
  // What a dot is stays out of the way until it is clicked; then it is named here.
  const picked = node("div", "tl-picked");
  picked.append(node("span", "caption", "Click a dot to jump to that moment."));
  line.moments.forEach((m) => {
    const theirs = m.label.startsWith("opp-");
    const kind = m.label.endsWith("shot") ? "shot" : "box";
    const text = momentText(m, line);
    const mark = node("button", `tl-mark ${theirs ? "them" : "us"} ${kind}`);
    mark.style.left = (m.t / total) * 100 + "%";
    mark.title = text;
    mark.setAttribute("aria-label", text);
    mark.onclick = () => {
      track.querySelectorAll(".tl-mark").forEach((x) => x.classList.toggle("on", x === mark));
      const chip = node("span", "tl-chip");
      chip.append(node("i", `tl-key ${theirs ? "them" : "us"}`), text);
      picked.replaceChildren(chip);
      jumpTo(card, g.id, m, line);
    };
    track.append(mark);
  });
  track.append(node("div", "tl-playhead"));
  block.append(head, track, picked);
  card.querySelector(".meta").before(block);
}

// Start the full game a few seconds before the moment. Without the full game,
// play the saved highlight clip that covers the moment instead.
function jumpTo(card, id, m, line) {
  const player = card._player;
  const half = m.half === 2 ? 2 : 1;
  const fullAt = (h) => player ? player.sources.findIndex((s) => s.full && (s.half === 0 || s.half === h)) : -1;
  const index = fullAt(half);
  if (index < 0) {
    const inHalf = half === 2 && line.half1 ? m.t - line.half1 : m.t;
    let clip = -1;
    if (player) {
      player.sources.forEach((s, i) => {
        if (s.clipHalf !== half || s.clipStart > inHalf + 2 || inHalf - s.clipStart > 130) return;
        if (clip < 0 || s.clipStart > player.sources[clip].clipStart) clip = i;
      });
    }
    if (clip < 0) {
      setNote(id, "Download the full game or its highlights to jump to this moment.", true);
      return;
    }
    const at = Math.max(0, inHalf - player.sources[clip].clipStart - 3);
    const go = () => { player.video.currentTime = at; player.video.play().catch(() => {}); };
    if (clip === player.current && player.video.readyState >= 1) go(); else player.show(clip, go);
    card.querySelector(".player").scrollIntoView({ block: "nearest", behavior: "smooth" });
    return;
  }
  const src = player.sources[index];
  const inFile = src.half === 2 && line.half1 ? m.t - line.half1 : m.t;
  player.show(index, () => {
    player.video.currentTime = Math.max(0, inFile - 5);
    player.video.play().catch(() => {});
  });
  if (index === player.current && player.video.readyState >= 1) {
    player.video.currentTime = Math.max(0, inFile - 5);
    player.video.play().catch(() => {});
  }
  card.querySelector(".player").scrollIntoView({ block: "nearest", behavior: "smooth" });
}

// The line on the timeline that follows the full game as it plays.
function movePlayhead(card) {
  const block = card.querySelector(".timeline");
  const player = card._player;
  if (!block || !player) return;
  const head = block.querySelector(".tl-playhead");
  const src = player.sources[player.current];
  head.hidden = !(src && src.full);
  if (head.hidden) return;
  const at = player.video.currentTime + (src.half === 2 && block._line.half1 ? block._line.half1 : 0);
  head.style.left = Math.min(100, (at / block._total) * 100) + "%";
}

// The game's analytics under its card, loaded once and shared with the Analytics page.
let statsRequest = null;
function loadStatsQuietly() {
  if (_analytics) return Promise.resolve(_analytics);
  if (!statsRequest) {
    statsRequest = api().get_analytics().then((data) => { _analytics = data; return data; })
      .catch(() => null).finally(() => { statsRequest = null; });
  }
  return statsRequest;
}

async function appendGameStats(box, g) {
  const section = node("div", "single-stats");
  section.append(node("div", "caption", "Loading this game's analytics…"));
  box.appendChild(section);
  const data = await loadStatsQuietly();
  if (!section.isConnected) return;               // moved on to another game meanwhile
  const number = Number(g.id.split("-").pop());
  const game = data && data.games.find((x) => x.game_id === number);
  if (!game) {
    // The heat map comes from a different file, which Trace keeps for older games too.
    section.replaceChildren(node("div", "caption", data
      ? "No stats for this game. Trace only provides stats for its most recent games."
      : "Couldn't load the stats. Check your connection."), heatCard(g, "whole"));
    return;
  }
  fillGameStats(section, game);
}

// ---- heat map: where our identified outfield players spent the game ----
const heatMaps = new Map();      // game id -> heat map, once loaded
const heatFailed = new Map();    // game id -> why it couldn't be loaded, so it isn't retried on every visit
let heatLoading = false;         // one game's tracking is downloaded at a time

function heatSvg(grid, cols, rows) {
  const W = cols * 10, H = rows * 10;
  // One busy square (players lined up for a kick-off) shouldn't wash out the rest:
  // full strength is the level only the busiest few squares reach.
  const values = grid.flat().filter((v) => v > 0).sort((a, b) => a - b);
  const top = values.length ? values[Math.floor((values.length - 1) * 0.97)] : 1;
  let cells = "";
  grid.forEach((row, r) => row.forEach((v, c) => {
    if (v > 0) cells += `<rect x="${c * 10}" y="${r * 10}" width="10" height="10" opacity="${Math.pow(Math.min(1, v / top), 0.75).toFixed(2)}"/>`;
  }));
  const boxH = H * 0.59, boxW = W * 0.157, y0 = (H - boxH) / 2;
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Heat map of where your players were">`
    + `<defs><filter id="heat-blur" x="-10%" y="-10%" width="120%" height="120%"><feGaussianBlur stdDeviation="7"/></filter>`
    + `<clipPath id="heat-clip"><rect width="${W}" height="${H}" rx="4"/></clipPath></defs>`
    + `<g clip-path="url(#heat-clip)"><rect class="heat-ground" width="${W}" height="${H}"/>`
    + `<g class="heat-cells" filter="url(#heat-blur)">${cells}</g></g>`
    + `<g class="heat-lines"><rect x="1" y="1" width="${W - 2}" height="${H - 2}" rx="4"/>`
    + `<line x1="${W / 2}" y1="1" x2="${W / 2}" y2="${H - 1}"/><circle cx="${W / 2}" cy="${H / 2}" r="${H * 0.135}"/>`
    + `<rect x="1" y="${y0}" width="${boxW}" height="${boxH}"/><rect x="${W - 1 - boxW}" y="${y0}" width="${boxW}" height="${boxH}"/></g>`
    + `</svg>`;
}

// seg: "whole" | "first" | "second", the part of the game the stats above show.
function heatCard(g, seg) {
  const card = node("div", "card heat-card");
  const body = node("div", "heat-body");
  card.append(node("h3", null, "Heat map"), body);
  const show = (heat) => {
    const part = heat[seg] || heat.whole;
    const when = heat[seg] ? { whole: "the game", first: "the 1st half", second: "the 2nd half" }[seg] : "the game";
    const pitch = node("div", "heat-pitch");
    pitch.innerHTML = heatSvg(part.grid, heat.cols, heat.rows);
    const key = node("div", "heat-key");
    key.append("Less", node("i"), "More", node("span", "spacer"), "Your team attacks this way →");
    const n = part.players;
    body.replaceChildren(pitch, key, node("p", "caption",
      `Where the ${n} outfield player${n === 1 ? "" : "s"} Trace identified on your team spent ${when}. `
      + "The goalkeeper is left out, and both halves are turned the same way."
      + (heat[seg] ? "" : " Trace has no tracking for this half, so the whole game is shown.")));
  };
  const load = async () => {
    const bar = node("div", "mini sliding");
    bar.append(node("i"));
    body.replaceChildren(node("p", "caption", "Loading player tracking from Trace. This can take a minute…"), bar);
    heatLoading = true;
    let res;
    try { res = await api().get_heatmap(g.id, true); } catch (e) { res = { ok: false, error: String(e) }; }
    heatLoading = false;
    if (res && res.ok) { heatFailed.delete(g.id); heatMaps.set(g.id, res.heat); show(res.heat); return; }
    heatFailed.set(g.id, (res && res.error) || "Couldn't load the heat map.");
    offer(heatFailed.get(g.id));
  };
  // A game's heat map loads by itself once its page has been open a moment,
  // unless a download is using the connection; then the button is offered.
  const loadSoon = () => {
    body.replaceChildren(node("p", "caption", "Getting ready to load the heat map…"));
    setTimeout(() => {
      if (!card.isConnected) return;                 // moved on to another game
      const busy = heatLoading || autoBusy || jobs.some((j) => j.state === "running" || j.state === "waiting");
      if (busy) offer(""); else load();
    }, 1200);
  };
  const offer = (problem) => {
    const note = node("p", "caption" + (problem ? " warn" : ""), problem
      || "A download is running, so the heat map wasn't loaded automatically. Loading it downloads about 20 to 50 MB once; after that it is kept with the game.");
    body.replaceChildren(note, labelButton(problem ? "retry" : "download", problem ? "Try again" : "Load heat map",
      "Download this game's player tracking from Trace and draw the heat map.", load));
  };
  if (heatMaps.has(g.id)) { show(heatMaps.get(g.id)); return card; }
  body.append(node("p", "caption", "Looking for a saved heat map…"));
  api().get_heatmap(g.id, false).then((res) => {
    if (res && res.ok) { heatMaps.set(g.id, res.heat); show(res.heat); }
    else if (res && !res.missing) offer(res.error);
    else if (heatFailed.has(g.id)) offer(heatFailed.get(g.id));
    else loadSoon();
  }, () => offer(""));
  return card;
}

function fillGameStats(section, game) {
  const st = game[_seg];
  const head = node("div", "row");
  const toggle = node("div", "seg-toggle");
  [["whole", "Whole game"], ["first", "1st half"], ["second", "2nd half"]].forEach(([seg, label]) => {
    const b = node("button", seg === _seg ? "on" : null, label);
    b.onclick = () => { _seg = seg; fillGameStats(section, game); };
    toggle.append(b);
  });
  head.append(node("h2", null, "Game analytics"), node("span", "spacer"), toggle);
  const tiles = node("div", "tiles");
  renderTiles(st, null, tiles);
  const territory = node("div", "card");
  const pitch = node("div", "pitch");
  pitch.innerHTML = st.territory_svg || "";
  const n = st.sequences_us;
  territory.append(node("h3", null, "Territory"), pitch,
    node("p", "caption", `From ${n} tracked sequence${n === 1 ? "" : "s"}${n < 3 ? " — too few to read much into." : "."}`));
  const halves = node("div", "card");
  const table = node("table", "stats-table");
  table.innerHTML = "<thead><tr><th></th><th>1st half</th><th>2nd half</th><th>Whole</th></tr></thead><tbody></tbody>";
  renderHalves(game, table.querySelector("tbody"));
  halves.append(node("h3", null, "By half"), table);
  const grid = node("div", "cards");
  grid.append(territory, halves);
  const players = node("div", "card");
  const list = node("div", "players");
  renderPlayers(st, list);
  players.append(node("h3", null, "Touches by player"), list);
  const listed = gameByNumber(game.game_id);
  section.replaceChildren(...[head, tiles, listed && heatCard(listed, _seg), grid, players].filter(Boolean));
}

el("gameSearch").oninput = () => { singleIndex = 0; renderGameList(); };
document.querySelectorAll("#layoutToggle button").forEach((b) => {
  b.onclick = () => {
    layout = b.dataset.layout;
    returnLayout = null;
    try { localStorage.setItem("layout", layout); } catch (e) { /* not available */ }
    applyLayout();
    renderGameList();
  };
});
applyLayout();
document.querySelectorAll("#gameFilter button").forEach((b) => {
  b.onclick = () => {
    gameFilter = b.dataset.filter;
    singleIndex = 0;
    document.querySelectorAll("#gameFilter button").forEach((x) =>
      x.classList.toggle("on", x === b));
    renderGameList();
  };
});

// Thumbnails are fetched once per game and kept, so re-drawing the list (filter,
// search, layout switch) shows them straight away instead of fetching again.
const thumbUrls = new Map();      // game id -> image URL, once loaded
const thumbRequests = new Map();  // game id -> request in flight

function showThumb(id) {
  const g = el("g-" + id);
  if (g && thumbUrls.has(id)) g.querySelector(".thumb").style.backgroundImage = `url("${thumbUrls.get(id)}")`;
}

function loadThumb(div, g) {
  if (!g.team_id) return;
  if (thumbUrls.has(g.id)) { showThumb(g.id); return; }
  if (thumbRequests.has(g.id)) return;          // already on its way; it will fill this card too
  const request = api().get_thumb(g.team_id, g.id).then((url) => {
    if (url) { thumbUrls.set(g.id, url); showThumb(g.id); }
  }).catch(() => {}).finally(() => thumbRequests.delete(g.id));
  thumbRequests.set(g.id, request);
}

function endProgress(g) {
  g.classList.remove("is-busy");
  g.querySelector(".err").classList.remove("info");
  g.querySelector(".err").textContent = "";
  g.querySelector(".progress").hidden = true;
  g.querySelector(".bar > i").style.width = "0%";
  g.querySelector(".speed").textContent = "";
}

function node(tag, className, text) {
  const n = document.createElement(tag);
  if (className) n.className = className;
  if (text != null) n.textContent = text;
  return n;
}

function iconButton(iconName, label, onclick) {
  const b = document.createElement("button");
  b.className = "icon-btn";
  b.innerHTML = icon(iconName);
  b.title = label;
  b.setAttribute("aria-label", label);
  b.onclick = onclick;
  return b;
}

function labelButton(iconName, text, title, onclick) {
  const b = document.createElement("button");
  b.innerHTML = icon(iconName);
  b.append(text);
  b.title = title;
  b.onclick = onclick;
  return b;
}

function savedLabel(text) {
  const span = node("span", "state saved");
  span.innerHTML = icon("check");
  span.append(text);
  return span;
}

// The thin green line under that note while something is being made for the game:
// a fraction (0–1) fills it that far, null slides it back and forth (no count to
// go on), false hides it.
function setMini(id, fraction) {
  const g = el("g-" + id);
  if (!g) return;
  const mini = g.querySelector(".mini");
  mini.hidden = fraction === false;
  mini.classList.toggle("sliding", fraction === null);
  mini.firstChild.style.width = fraction === null || fraction === false ? "" : Math.max(3, fraction * 100) + "%";
}

// The line under a game's date: grey for progress and results, amber for problems.
function setNote(id, text, info) {
  const g = el("g-" + id);
  if (!g) return;
  const note = g.querySelector(".err");
  note.classList.toggle("info", !!info);
  note.textContent = text || "";
}

// ---- the three things a game offers: Game (video), Highlights, Player Recaps ----
const clipCount = new Map();           // id -> team highlight clips already cut
const highlightsRunning = new Set();   // ids whose team clips are being made right now
const recapsRunning = new Map();       // id -> latest step text while "Download all" runs

function highlightsButton(id) {
  if (highlightsRunning.has(id)) {
    const stop = labelButton("x", "Stop", "Stop making highlights. Nothing half-done is kept.", () => {
      stop.disabled = true;
      api().cancel();
    });
    stop.classList.add("danger");
    return stop;
  }
  if (waiting("highlights:" + id)) return inLineButton("highlights:" + id);
  const count = clipCount.get(id) || 0;
  const saved = gameState.get(id) === "saved";
  const title = count ? `${count} highlight clips saved. Click to show them in the folder.`
    : saved ? "Cut this game's shots and box entries into highlight clips."
    : "Download just this game's shots and box entries from Trace as highlight clips, without the full game.";
  const b = labelButton("film", "Highlights", title, () => runHighlights(id));
  if (count) b.classList.add("done");
  return b;
}

function recapsButton(g, id) {
  // The list needs room, so from the card and list layouts it opens on the
  // game's own page; there, the button shows and hides it.
  return labelButton("user", "Player Recaps", "Choose which players' recaps to download.", () => {
    if (layout === "single") { toggleRecaps(g, id); return; }
    openSingle(id);
    const card = el("g-" + id);
    if (!card) return;
    toggleRecaps(card, id).then(() => card.querySelector(".hl-panel").scrollIntoView({ block: "nearest", behavior: "smooth" }));
  });
}

// Not downloaded (or cancelled): Game, Highlights, Player Recaps.
function setIdle(g, id) {
  endProgress(g);
  g.classList.add("is-new");
  const share = partial.get(id);
  const inLine = waiting("game:" + id);
  const full = inLine ? inLineButton("game:" + id)
    : share != null ? labelButton("download", `Resume (${Math.round(share * 100)}%)`,
      "Carry on downloading the full game from where it stopped.", () => startDownload(id))
    : labelButton("download", "Full Game", "Download the full game video.", () => startDownload(id));
  const folder = labelButton("folder", "Open Folder", "Open this game's folder.", async () => {
    const res = await api().open_game_folder(id);
    if (!(res && res.ok)) setNote(id, (res && res.error) || "Couldn't open the folder.", false);
  });
  const buttons = [full];
  if (share != null && !inLine) {
    buttons.push(labelButton("x", "Discard", "Delete what was downloaded of this game so far.", () => discardDownload(id)));
  }
  g.querySelector(".action").replaceChildren(...buttons, folder, highlightsButton(id), recapsButton(g, id));
}

function setBusy(g) {
  if (g.classList.contains("is-busy")) return;
  g.classList.add("is-busy");
  g.querySelector(".progress").hidden = false;
  const action = g.querySelector(".action");
  action.innerHTML = "";
  const b = document.createElement("button");
  b.className = "danger wide";
  b.innerHTML = icon("x") + "Cancel";
  b.title = "Stop this download. What has been downloaded is kept, so it can carry on later.";
  b.onclick = () => { b.disabled = true; b.textContent = "Cancelling…"; api().cancel(); };
  action.appendChild(b);
}

// Downloaded: watch it, find it, and the same Highlights / Player Recaps buttons.
// A green button means that part is saved.
function setSaved(g, id) {
  endProgress(g);
  g.classList.remove("is-new");
  const run = async (call) => {
    const res = await call(id);
    setNote(id, res && res.ok ? "" : (res && res.error) || "Couldn't open the video.", false);
  };
  const done = (iconName, text, title, onclick) => {
    const b = labelButton(iconName, text, title, onclick);
    b.classList.add("done");
    return b;
  };
  g.querySelector(".action").replaceChildren(
    done("play", "Watch Game", "The game is saved. Click to play it.", () => run((gameId) => api().play_game(gameId))),
    done("folder", "Open Folder", "Show the game video in its folder.", () => run((gameId) => api().reveal_game(gameId))),
    highlightsButton(id), recapsButton(g, id));
  if (highlightsRunning.has(id)) { setNote(id, "Cutting team highlights…", true); setMini(id, null); }
  attachPlayer(g, id);
}

// Redraw a card's buttons after something changed, unless it is mid-download.
function redrawButtons(id) {
  const g = el("g-" + id);
  if (!g || g.classList.contains("is-busy")) return;
  if (gameState.get(id) === "saved") setSaved(g, id); else setIdle(g, id);
}

async function runHighlights(id) {
  if (clipCount.get(id) > 0) {
    const shown = await api().reveal_highlights(id);
    setNote(id, shown && shown.ok ? "" : (shown && shown.error) || "", false);
    return;
  }
  enqueue({
    key: "highlights:" + id, id, kind: "Highlights", redraw: () => redrawButtons(id),
    run: async () => {
      const hadGame = gameState.get(id) === "saved";
      highlightsRunning.add(id);
      redrawButtons(id);
      setNote(id, hadGame ? "Cutting team highlights…" : "Getting highlight clips from Trace…", true);
      setMini(id, null);
      let res;
      try { res = await api().download_highlights(id); } catch (e) { res = { ok: false, error: String(e) }; }
      highlightsRunning.delete(id);
      const ok = !!(res && res.ok);
      if (ok) clipCount.set(id, res.count);
      redrawButtons(id);
      setMini(id, false);
      const text = ok ? `Saved ${res.count} highlight clip${res.count === 1 ? "" : "s"}.`
        : (res && res.error) || "Couldn't save highlights.";
      setNote(id, text, ok);
      return { ok, text, stopped: !ok && /^Stopped/.test(text) };
    },
  });
}

// ---- player recaps panel: Trace's follow-camera recap for each player ----
async function toggleRecaps(g, id) {
  const panel = g.querySelector(".hl-panel");
  if (!panel.hidden) { panel.hidden = true; return; }
  panel.hidden = false;
  if (recapsRunning.has(id) && panel.childElementCount) return;   // keep the live view
  await loadRecaps(panel, id);
}

async function loadRecaps(panel, id, note) {
  panel.replaceChildren(node("div", "caption", "Loading player recaps…"));
  let res;
  try { res = await api().list_highlights(id); } catch (e) { res = { ok: false, error: String(e) }; }
  renderRecaps(panel, id, res, note);
}

// One row: a label, a line of detail, and an action that swaps to "Saved" when done.
// `error` is what went wrong on the last try, if anything.
function recapRow(id, p, error) {
  const none = !p.saved && p.seconds === 0;
  const length = p.seconds ? ` · ${Math.floor(p.seconds / 60)}:${String(p.seconds % 60).padStart(2, "0")}` : "";
  const detail = none ? "No recap for this game." : "Follow-camera recap from Trace" + length;
  const row = node("div", "hl-row" + (none ? " is-off" : ""));
  row.dataset.user = p.user_id;
  const text = node("div", "hl-text");
  const note = node("div", "hl-detail", detail);
  const bar = node("div", "bar");
  bar.hidden = true;
  bar.append(node("i"));
  const who = `${p.number ? "#" + p.number : "No number"} · ${p.name || "Player"}`;
  text.append(node("div", "hl-title", who), note, bar);
  const action = node("div", "action");
  row.append(text, action);
  if (p.saved) { action.append(savedLabel("Saved")); return row; }
  if (none) return row;
  const key = `recap:${id}:${p.user_id}`;
  const job = findJob(key);
  if (job && job.state === "running") {
    const busy = labelButton("download", "Downloading…", "", () => {});
    busy.disabled = true;
    action.append(busy);
    return row;
  }
  if (job) { action.append(inLineButton(key)); return row; }
  if (error) { note.classList.add("warn"); note.textContent = error; }
  const redraw = (problem) => {
    const card = el("g-" + id);          // the list may have been redrawn meanwhile
    const old = card && card.querySelector(`.hl-row[data-user="${p.user_id}"]`);
    if (old) old.replaceWith(recapRow(id, p, problem));
  };
  action.append(labelButton(error ? "retry" : "download", error ? "Retry" : "Download",
    "Download this player's recap.", () => enqueue({
      key, id, kind: "Player recap · " + who, redraw: () => redraw(),
      run: async () => {
        redraw();
        let res;
        try { res = await api().download_recap(id, p.user_id); } catch (e) { res = { ok: false, error: String(e) }; }
        const ok = !!(res && res.ok);
        const problem = ok ? "" : (res && res.error) || "That didn't work.";
        if (ok) p.saved = true;
        // The row is drawn from the line, and this one is still marked as running.
        setTimeout(() => redraw(problem), 0);
        return { ok, text: ok ? "Saved." : problem, stopped: /stop|cancel/i.test(problem) };
      },
    })));
  return row;
}

function recapsSummary(res) {
  if (!res || !res.ok) return (res && res.error) || "Couldn't download the recaps.";
  const saved = `${res.recaps} player recap${res.recaps === 1 ? "" : "s"}`;
  if (res.cancelled) return `Stopped. Saved ${saved}.`;
  if (!res.recaps && !res.failed) return "Every available recap is already saved.";
  return `Saved ${saved}.` + (res.failed ? ` ${res.failed} failed.` : "");
}

const recapLists = new Map();     // id -> the last player list loaded, to redraw without asking Trace again
function renderRecaps(panel, id, res, note) {
  recapLists.set(id, res);
  const running = recapsRunning.has(id);
  panel.classList.toggle("is-running", running);
  const status = node("span", "hl-detail hl-status", running ? recapsRunning.get(id) : note || "");
  const overall = node("div", "bar hl-overall");
  overall.hidden = !running;
  overall.append(node("i"));
  const head = node("div", "row");
  head.append(node("h3", null, "Player recaps"), status, node("span", "spacer"));
  const todo = res.ok ? res.players.filter((p) => !p.saved && p.seconds).length : 0;
  if (running) {
    const stop = labelButton("x", "Stop", "Stop after the recap being downloaded.", () => {
      stop.disabled = true;
      api().cancel();
    });
    stop.classList.add("danger");
    head.append(stop);
  } else if (waiting("recaps:" + id)) {
    head.append(inLineButton("recaps:" + id));
  } else if (todo > 0) {
    head.append(labelButton("download", `Download all ${todo}`,
      "Download every recap not saved yet (about 100 MB or more each).", () => downloadAllRecaps(id)));
  }
  head.append(iconButton("folder", "Show this game's Player Highlights folder", async () => {
    const shown = await api().reveal_highlights(id, "recaps");
    if (!(shown && shown.ok)) status.textContent = (shown && shown.error) || "";
  }));
  panel.replaceChildren(head, overall);
  if (!res.ok) {
    panel.append(node("div", "hl-detail warn", "Couldn't load the player list. " + (res.error || "")));
    return;
  }
  if (res.players.length === 0) {
    panel.append(node("div", "hl-detail", "Trace has no player recaps for this game."));
    return;
  }
  const grid = node("div", "hl-players");
  res.players.forEach((p) => grid.append(recapRow(id, p)));
  panel.append(grid);
}

function downloadAllRecaps(id) {
  const panelNow = () => { const card = el("g-" + id); return card && card.querySelector(".hl-panel"); };
  enqueue({
    key: "recaps:" + id, id, kind: "All player recaps",
    redraw: () => { if (panelNow() && recapLists.has(id)) renderRecaps(panelNow(), id, recapLists.get(id)); },
    run: async () => {
      recapsRunning.set(id, "Starting…");
      if (panelNow() && recapLists.has(id)) renderRecaps(panelNow(), id, recapLists.get(id));
      let res;
      try { res = await api().download_all_recaps(id); } catch (e) { res = { ok: false, error: String(e) }; }
      recapsRunning.delete(id);
      const text = recapsSummary(res);
      if (panelNow()) loadRecaps(panelNow(), id, text);      // the list may have been redrawn meanwhile
      return { ok: !!(res && res.ok) && !res.cancelled && !res.failed, text, stopped: !!(res && res.cancelled) };
    },
  });
}

function onRecapsEvent(p) {
  if (p.text) recapsRunning.set(p.id, p.text);
  if (p.text) jobProgress("recaps:" + p.id, undefined, p.text);
  const card = el("g-" + p.id);
  if (!card) return;
  const panel = card.querySelector(".hl-panel");
  const status = panel.querySelector(".hl-status");
  if (p.text && status) status.textContent = p.text;
  const row = p.saved_user != null && panel.querySelector(`.hl-row[data-user="${p.saved_user}"]`);
  if (row) {
    row.querySelector(".action").replaceChildren(savedLabel("Saved"));
    row.querySelector(".bar").hidden = true;
  }
}

// A recap is downloading: fill that player's bar, and the overall one for "Download all".
function onRecapProgress(p) {
  jobProgress(`recap:${p.id}:${p.user_id}`, p.percent / 100, `${p.percent}%`);
  if (p.total) jobProgress("recaps:" + p.id, (p.index - 1 + p.percent / 100) / p.total);
  const card = el("g-" + p.id);
  if (!card) return;
  const panel = card.querySelector(".hl-panel");
  const row = panel.querySelector(`.hl-row[data-user="${p.user_id}"]`);
  if (row) {
    const bar = row.querySelector(".bar");
    bar.hidden = p.percent >= 100;
    bar.firstChild.style.width = p.percent + "%";
    const b = row.querySelector(".action button");
    if (b && b.disabled) b.textContent = `Downloading… ${p.percent}%`;
  }
  const overall = panel.querySelector(".hl-overall > i");
  if (overall && p.total) overall.style.width = ((p.index - 1 + p.percent / 100) / p.total) * 100 + "%";
}

// Failed: say why and let the user try again.
function setFailed(g, id, message) {
  setIdle(g, id);
  const b = g.querySelector(".action button");
  if (!partial.has(id)) b.innerHTML = icon("retry") + "Retry";
  setNote(id, "Download failed" + (message ? ": " + message : ""), false);
  g.querySelector(".err").title = message || "";
}

// Finished one way or another: replace the button with a status label.
function setState(g, kind, iconName, text, title) {
  endProgress(g);
  g.classList.toggle("is-new", kind === "warn");
  const span = document.createElement("span");
  span.className = "state " + kind;
  span.innerHTML = iconName ? icon(iconName) : "";
  span.append(text);
  if (title) span.title = title;
  g.querySelector(".action").replaceChildren(span);
}

// "about 6 min left" from a number of seconds; "" when there is nothing to go on yet.
function timeLeft(secs) {
  if (secs == null) return "";
  if (secs < 60) return "less than a minute left";
  const mins = Math.round(secs / 60);
  if (mins < 60) return `about ${mins} min left`;
  return `about ${Math.floor(mins / 60)} h ${mins % 60} min left`;
}

// The line under a full game while it downloads.
function progressText(p) {
  if (p.joining) return `Half ${p.half} · Putting the video together…`;
  return [`${Math.round(p.percent)}%`, `Half ${p.half}`, `${p.speed} MB/s`, timeLeft(p.eta)]
    .filter(Boolean).join(" · ");
}

// ---- the download line ----
// The app downloads one thing at a time. Anything started while another download
// is running waits in line and starts by itself; the Downloads page shows the line.
const jobs = [];           // in the order they were asked for
const partial = new Map();       // game id -> share (0–1) of a full game downloaded before it was cut off
const gamePercent = new Map();   // game id -> last percent reported while its full game downloads
let lineHead = null;             // the "Up next" heading, which also says how long the line will take
let autoBusy = false;      // an automatic download is the one running
let autoText = "";

function findJob(key) { return jobs.find((j) => j.key === key && (j.state === "waiting" || j.state === "running")); }
function waiting(key) { const job = findJob(key); return !!job && job.state === "waiting"; }
function gameTitle(id) {
  const g = allGames.find((x) => x.id === id);
  return g ? "vs " + (g.opponent || g.title) : "Game";
}

// A button standing in for one whose download is waiting its turn.
function inLineButton(key) {
  const b = labelButton("x", "In line", "Waiting for the current download to finish. Click to take it out of the line.",
    () => dequeue(key));
  b.classList.add("queued");
  return b;
}

// job: {key, id, kind, run() -> {ok, text, stopped}, redraw() for when it joins or leaves the line}
function enqueue(job) {
  if (findJob(job.key)) return;
  const old = jobs.findIndex((j) => j.key === job.key);     // a retry replaces the finished row
  if (old >= 0) jobs.splice(old, 1);
  Object.assign(job, { state: "waiting", title: gameTitle(job.id), text: "", percent: null, outcome: null, eta: null });
  jobs.push(job);
  if (job.redraw) job.redraw();
  renderDownloads();
  pump();
}

function dequeue(key) {
  const i = jobs.findIndex((j) => j.key === key && j.state === "waiting");
  if (i < 0) return;
  const [job] = jobs.splice(i, 1);
  if (job.redraw) job.redraw();
  renderDownloads();
}

// Throw away what a cut-off full-game download left on disk.
async function discardDownload(id) {
  let res;
  try { res = await api().discard_download(id); } catch (e) { res = { ok: false, error: String(e) }; }
  const i = jobs.findIndex((j) => j.key === "game:" + id && j.state !== "running" && j.state !== "waiting");
  if (!(res && res.ok)) {
    // Nothing was deleted (the game is downloading, or saved since): leave things as they are and say so.
    const why = (res && res.error) || "Couldn't delete this download.";
    if (i >= 0) jobs[i].text = why;
    setNote(id, why, false);
    renderDownloads();
    return;
  }
  partial.delete(id);
  gamePercent.delete(id);
  if (i >= 0) jobs.splice(i, 1);
  setNote(id, "", false);
  redrawButtons(id);
  renderDownloads();
  showFreeSpace();
}

// Swap a waiting job with the one before (-1) or after (+1) it in the line.
function moveJob(key, step) {
  const line = jobs.filter((j) => j.state === "waiting");
  const at = line.findIndex((j) => j.key === key);
  const other = line[at + step];
  if (at < 0 || !other) return;
  const a = jobs.indexOf(line[at]);
  const b = jobs.indexOf(other);
  [jobs[a], jobs[b]] = [jobs[b], jobs[a]];
  renderDownloads();
}

// "Up next", plus roughly how long the games in line will take: the time left on
// the game that is running, and that game's whole length again for each full game
// waiting. Highlights and recaps in line are short and are not counted.
function showLineTime() {
  if (!lineHead) return;
  const job = jobs.find((j) => j.state === "running" && j.kind === "Full Game");
  const games = jobs.filter((j) => j.state === "waiting" && j.kind === "Full Game").length;
  let text = "Up next";
  if (job && job.eta != null && job.percent > 0 && job.percent < 1 && games) {
    const whole = job.eta / (1 - job.percent);
    text += " · " + timeLeft(job.eta + games * whole).replace(" left", " for the games in line");
  }
  lineHead.textContent = text;
}

async function showFreeSpace() {
  let res;
  try { res = await api().disk_free(); } catch (e) { return; }
  el("dlFree").hidden = !(res && res.ok);
  if (!res || !res.ok) return;
  el("dlFree").textContent = `${res.text} free in the download folder`;
  el("dlFree").classList.toggle("warn", !!res.low);
}

async function pump() {
  if (autoBusy || jobs.some((j) => j.state === "running")) return;
  const job = jobs.find((j) => j.state === "waiting");
  if (!job) return;
  job.state = "running";
  renderDownloads();
  let res;
  try { res = await job.run(job); } catch (e) { res = { ok: false, text: String(e) }; }
  const ok = !!(res && res.ok);
  job.state = ok ? "done" : res && res.stopped ? "stopped" : "failed";
  job.text = (res && res.text) || (ok ? "Saved." : "That didn't work.");
  showFreeSpace();
  renderDownloads();
  pump();
}

// Progress for the job that is running: a fraction (0–1) and/or a line of text.
function jobProgress(key, fraction, text) {
  const job = findJob(key);
  if (!job || job.state !== "running") return;
  if (fraction !== undefined) job.percent = fraction;
  if (text !== undefined) job.text = text;
  if (!job.els) return;
  job.els.bar.classList.toggle("sliding", job.percent === null);
  job.els.bar.firstChild.style.width = job.percent === null ? "" : Math.max(2, job.percent * 100) + "%";
  job.els.detail.textContent = job.text || "Downloading…";
}

function downloadRow(title, detail, state) {
  const row = node("div", "hl-row dl-row is-" + state);
  const text = node("div", "hl-text");
  const note = node("div", "hl-detail" + (state === "failed" ? " warn" : ""), detail);
  const bar = node("div", "bar");
  bar.append(node("i"));
  bar.hidden = state !== "running";
  text.append(node("div", "hl-title", title), note, bar);
  const action = node("div", "action");
  row.append(text, action);
  return { row, note, bar, action };
}

function jobRow(job) {
  const waitingText = "Waiting for its turn.";
  const made = downloadRow(`${job.title} · ${job.kind}`,
    job.state === "waiting" ? waitingText : job.text || "Downloading…", job.state);
  job.els = null;
  if (job.state === "running") {
    job.els = { bar: made.bar, detail: made.note };
    made.bar.classList.toggle("sliding", job.percent === null);
    if (job.percent !== null) made.bar.firstChild.style.width = Math.max(2, job.percent * 100) + "%";
    const stop = labelButton("x", "Stop", job.kind === "Full Game"
      ? "Stop this download. What has been downloaded is kept, so it can carry on later."
      : "Stop this download. Nothing half-done is kept.", () => {
      stop.disabled = true;
      api().cancel();
    });
    stop.classList.add("danger");
    made.action.append(stop);
  } else if (job.state === "waiting") {
    const line = jobs.filter((j) => j.state === "waiting");
    const at = line.indexOf(job);
    const up = iconButton("up", "Move up the line", () => moveJob(job.key, -1));
    up.disabled = at === 0;
    const down = iconButton("down", "Move down the line", () => moveJob(job.key, 1));
    down.disabled = at === line.length - 1;
    made.action.append(up, down, labelButton("x", "Remove", "Take this out of the line.", () => dequeue(job.key)));
  } else if (job.state === "done") {
    made.action.append(savedLabel("Saved"));
  } else if (job.kind === "Full Game" && partial.has(job.id)) {
    made.action.append(
      labelButton("retry", "Resume", "Carry on from what is already downloaded.", () => enqueue(job)),
      labelButton("x", "Discard", "Delete what was downloaded of this game so far.", () => discardDownload(job.id)));
  } else {
    made.action.append(labelButton("retry", "Retry", "Try this download again.", () => enqueue(job)));
  }
  made.action.append(iconButton("games", "Go to this game", () => { showView("games"); openSingle(job.id); }));
  return made.row;
}

function renderDownloads() {
  const running = jobs.filter((j) => j.state === "running");
  const next = jobs.filter((j) => j.state === "waiting");
  const finished = jobs.filter((j) => j.state !== "running" && j.state !== "waiting").reverse();
  const count = running.length + next.length + (autoBusy ? 1 : 0);
  el("dlCount").hidden = count === 0;
  el("dlCount").textContent = count;
  el("clearDone").hidden = finished.length === 0;
  const list = el("dlList");
  list.replaceChildren();
  const group = (title, rows) => {
    if (!rows.length) return null;
    const head = node("h3", "dl-head", title);
    list.append(head, ...rows);
    return head;
  };
  const now = running.map(jobRow);
  if (autoBusy) {
    const auto = downloadRow("Automatic download", autoText || "Saving new games…", "running");
    auto.bar.classList.add("sliding");
    now.push(auto.row);
  }
  group("Downloading now", now);
  lineHead = group("Up next", next.map(jobRow));
  showLineTime();
  group("Finished", finished.map(jobRow));
  el("dlEmpty").hidden = list.childElementCount > 0;
}

function startDownload(id) {
  if (gameState.get(id) === "saved") return;
  enqueue({
    key: "game:" + id, id, kind: "Full Game", redraw: () => redrawButtons(id),
    run: async (job) => {
      const g = el("g-" + id);
      if (g) setBusy(g);
      let res;
      try { res = await api().download_game(id); } catch (e) { res = { ok: false, error: String(e) }; }
      if (job.outcome === "cancelled") return { ok: false, stopped: true, text: "Stopped." };
      if (job.outcome === "unavailable") return { ok: false, text: "Trace has no video for this game yet." };
      const ok = !!(res && res.ok);
      return { ok, text: ok ? "Saved." : "Download failed" + (res && res.error ? ": " + res.error : ".") };
    },
  });
}

window.onPy = (event, p) => {
  if (event === "analytics_progress") { showAnalyticsProgress(p.done, p.total); return; }
  if (event === "update_progress") {
    document.querySelector("#updateBar > i").style.width = p.percent + "%";
    el("updateNote").textContent = `Downloading the update… ${p.percent}%`;
    return;
  }
  if (event === "auto") {
    // An automatic download takes its turn like any other: the line waits for it.
    autoBusy = !!p.running;
    autoText = p.text || "";
    showAutoStatus(autoOn || p.running, p.running ? p.text : "");
    renderDownloads();
    if (!autoBusy) pump();
    return;
  }
  if (event === "recaps") { onRecapsEvent(p); return; }
  if (event === "highlights_progress") {
    if (highlightsRunning.has(p.id)) {
      setNote(p.id, p.done < p.total ? `Downloading highlight ${p.done + 1} of ${p.total} from Trace…`
        : "Joining the clips into the highlight reel…", true);
      setMini(p.id, p.done < p.total ? p.done / p.total : null);
    }
    jobProgress("highlights:" + p.id, p.done < p.total ? p.done / p.total : null,
      p.done < p.total ? `Highlight ${p.done + 1} of ${p.total}` : "Joining the clips into the highlight reel…");
    return;
  }
  if (event === "recap_progress") { onRecapProgress(p); return; }
  if (event === "saved") gameState.set(p.id, "saved");
  const gameJob = findJob("game:" + p.id);
  if (event === "progress") gamePercent.set(p.id, p.percent);
  if (event === "saved") partial.delete(p.id);
  // Stopped or failed partway: what was downloaded is kept, so the card offers Resume.
  if ((event === "cancelled" || event === "error") && gamePercent.get(p.id) > 0) {
    partial.set(p.id, gamePercent.get(p.id) / 100);
  }
  if (gameJob && event === "progress") {
    gameJob.eta = p.joining ? null : p.eta;
    jobProgress(gameJob.key, p.percent / 100, progressText(p));
    showLineTime();
  } else if (gameJob) {
    gameJob.outcome = event;
  }
  const g = el("g-" + p.id);
  if (!g) return;
  if (event === "progress") {
    setBusy(g);
    g.querySelector(".bar > i").style.width = p.percent + "%";
    g.querySelector(".speed").textContent = progressText(p);
  } else if (event === "cancelled") {
    setIdle(g, p.id);
  } else if (event === "saved") {
    setSaved(g, p.id);
  } else if (event === "unavailable") {
    setState(g, "muted", null, "No video");
  } else if (event === "error") {
    setFailed(g, p.id, p.message || "");
  }
};

el("account").onchange = async (e) => {
  const v = e.target.value;
  if (v === "__add__") { await connectAccount(); return; }
  await api().switch_account(v);
  await refresh();
};

// ---- connect-account dialog (replaces fragile alert()/prompt(), which
// WebView2 on Windows ignores) ----
let connectTimer = null;
function stopConnectPoll() { if (connectTimer) { clearInterval(connectTimer); connectTimer = null; } }

async function connectAccount() {
  stopConnectPoll();
  el("connectManual").open = false;
  el("connectUrl").value = "";
  const b = el("connectDetect"); b.disabled = false; b.textContent = "Connect now";
  el("connect").showModal();
  el("connectMsg").textContent = "Opening login window…";
  try {
    await api().add_account_start();
  } catch (err) {
    el("connectMsg").textContent = "Couldn't open the login window: " + String(err);
    return;
  }
  el("connectMsg").textContent = "Waiting for you to log in (email + code)…";
  startConnectPoll();
}

// Poll the login window; the moment the session is live, the backend discovers
// the team and finishes on its own — no need to open the games page or click.
function startConnectPoll() {
  stopConnectPoll();
  connectTimer = setInterval(async () => {
    let res;
    try { res = await api().add_account_poll(); } catch (err) { return; }
    if (!res) return;
    if (res.status === "done") {
      stopConnectPoll(); el("connect").close(); await refresh();
    } else if (res.status === "logged_in_no_team" || res.status === "error") {
      stopConnectPoll();
      el("connectMsg").textContent = (res.detail || "Couldn't finish.")
        + " You can paste your team URL below instead.";
      el("connectManual").open = true;
    }
    // status === "waiting": keep polling, leave the message as-is
  }, 2500);
}

el("connectDetect").onclick = async () => {
  const b = el("connectDetect"); b.disabled = true; b.textContent = "Checking…";
  let res;
  try { res = await api().add_account_finish(); } catch (err) { res = { detail: String(err) }; }
  b.disabled = false; b.textContent = "Connect now";
  if (res && res.ok) { stopConnectPoll(); el("connect").close(); await refresh(); return; }
  el("connectMsg").textContent = (res && res.detail) ? res.detail : "Not connected yet.";
  if (res && res.needs_url) el("connectManual").open = true;
};
el("connectUrlBtn").onclick = async () => {
  const url = el("connectUrl").value.trim();
  if (!url) { el("connectMsg").textContent = "Paste your team page URL first."; return; }
  const b = el("connectUrlBtn"); b.disabled = true; b.textContent = "Connecting…";
  let res;
  try { res = await api().confirm_team_url(url); } catch (err) { res = { detail: String(err) }; }
  b.disabled = false; b.textContent = "Use this URL";
  if (res && res.ok) { stopConnectPoll(); el("connect").close(); await refresh(); return; }
  el("connectMsg").textContent = (res && res.detail) ? res.detail : "That URL didn't work.";
};
el("connectCancel").onclick = async () => {
  stopConnectPoll();
  el("connect").close();
  await api().add_account_cancel();
  await refresh();
};

el("openFolder").onclick = () => api().open_folder();

// ---- sidebar navigation ----
const VIEWS = { games: "games-view", analytics: "analytics", downloads: "downloads", settings: "settings" };
let analyticsLoaded = false;
function showView(name) {
  Object.entries(VIEWS).forEach(([key, id]) => { el(id).hidden = key !== name; });
  document.querySelectorAll("#nav button").forEach((b) =>
    b.classList.toggle("on", b.dataset.view === name));
  if (name === "analytics") renderSeasonTop();
  if (name === "analytics" && !analyticsLoaded) loadAnalytics();
  if (name === "downloads") showFreeSpace();
}
document.querySelectorAll("#nav button").forEach((b) => {
  b.onclick = () => {
    // "Games" always means the whole list: from a single game's page, step back out.
    if (b.dataset.view === "games" && layout === "single") {
      layout = returnLayout && returnLayout !== "single" ? returnLayout : "cards";
      returnLayout = null;
      applyLayout();
      renderGameList();
      document.querySelector("main").scrollTo(0, 0);
    }
    showView(b.dataset.view);
  };
});

// ---- team analytics: loaded the first time the view opens, then on Refresh ----
let _analytics = null;   // last-loaded payload
let _seg = "whole";      // "whole" | "first" | "second"

const METRICS = {
  shots: { label: "Shots", series: [["shots_us", "Us"], ["shots_them", "Opponent"]] },
  control: { label: "Ball-control (min)", series: [["poss_secs_us", "Us"]], scale: 1 / 60, digits: 1 },
  passes: { label: "Passes", series: [["passes_us", "Us"]] },
  box: { label: "Box entries", series: [["box_us", "Us"]] },
  att: { label: "Attacking-third entries", series: [["att_third_us", "Us"]] },
  packing: { label: "Packing", series: [["packing_us", "Us"]] },
};

function ctrlText(st) {
  return (st.poss_secs_us / 60).toFixed(1)
    + (st.poss_pct_us == null ? "" : ` (${st.poss_pct_us}%)`);
}

function shortDate(iso) {
  const d = new Date(iso + "T00:00");
  return isNaN(d) ? iso : d.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

function setMapNote(n) {
  const note = el("map-note");
  const base = `Territory from ${n} tracked sequence${n === 1 ? "" : "s"}`;
  note.textContent = n < 3 ? `${base} — too few to read much into.` : `${base}.`;
  note.classList.toggle("warn", n < 3);
}

function tile(label, value, sub) {
  const div = document.createElement("div");
  div.className = "tile";
  for (const [cls, text] of [["label", label], ["value", value], ["sub", sub]]) {
    if (text == null) continue;
    const part = document.createElement("div");
    part.className = cls;
    part.textContent = text;
    div.appendChild(part);
  }
  return div;
}

// `games` is given for the season: the tiles then add a per-game average.
function renderTiles(st, games, target) {
  const each = (value, unit) => games ? `${(value / games).toFixed(1)}${unit || ""} a game` : null;
  const join = (...parts) => parts.filter(Boolean).join(" · ") || null;
  const minutes = st.poss_secs_us / 60;
  const tiles = [
    tile("Shots", st.shots_us, join(each(st.shots_us), `Opponent ${st.shots_them}`)),
    tile("Ball-control", minutes.toFixed(1) + " min",
      games ? each(minutes, " min") : st.poss_pct_us == null ? null : `${st.poss_pct_us}% of match time`),
    tile("Passes", st.passes_us, each(st.passes_us) || "touches in sequences"),
    tile("Box entries", st.box_us, join(each(st.box_us), st.box_them == null ? null : `Opponent ${st.box_them}`)),
    tile("Attacking-third entries", st.att_third_us, each(st.att_third_us)),
    tile("Packing", st.packing_us, each(st.packing_us) || "opponents bypassed"),
  ];
  if (games != null) tiles.unshift(tile("Games", games, "with stats"));
  (target || el("stat-tiles")).replaceChildren(...tiles);
}

function renderPlayers(st, target) {
  const box = target || el("players");
  const rows = Object.entries(st.touches_by_number || {})
    .sort((a, b) => b[1] - a[1] || Number(a[0]) - Number(b[0])).slice(0, 12);
  box.replaceChildren();
  if (rows.length === 0) {
    const none = document.createElement("div");
    none.className = "caption";
    none.style.gridColumn = "1 / -1";
    none.textContent = "No tracked touches.";
    box.appendChild(none);
    return;
  }
  const peak = rows[0][1];
  for (const [number, count] of rows) {
    const num = document.createElement("div");
    num.className = "num"; num.textContent = "#" + number;
    const track = document.createElement("div");
    track.className = "track";
    const fill = document.createElement("i");
    fill.style.width = (count / peak) * 100 + "%";
    track.appendChild(fill);
    const val = document.createElement("div");
    val.textContent = count;
    box.append(num, track, val);
  }
}

// Bars with rounded tops, anchored to the baseline.
function barPath(x, y, w, base) {
  const r = Math.min(4, w / 2, base - y);
  return `M${x},${base}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${base}Z`;
}

function niceMax(v) {
  if (v <= 4) return 4;
  const step = Math.pow(10, Math.floor(Math.log10(v / 4)));
  const nice = [1, 2, 2.5, 5, 10].map((m) => m * step).find((s) => s * 4 >= v);
  return nice * 4;
}

function renderTrend() {
  const metric = METRICS[el("trend-metric").value];
  const games = _analytics.games.map((g, index) => ({ g, index })).reverse();   // oldest first
  const value = (g, key) => g[_seg][key] * (metric.scale || 1);
  const fmt = (v) => (metric.digits ? v.toFixed(metric.digits) : String(v));
  const legend = el("trend-legend");
  legend.replaceChildren();
  if (metric.series.length > 1) {
    metric.series.forEach(([, name], i) => {
      const item = document.createElement("span");
      const swatch = document.createElement("i");
      swatch.style.background = `var(--series-${i + 1})`;
      item.append(swatch, name);
      legend.appendChild(item);
    });
  }
  const W = 520, H = 210, L = 30, R = 6, T = 8, B = 24;
  const plotW = W - L - R, base = H - B;
  const top = niceMax(Math.max(0, ...games.flatMap(({ g }) => metric.series.map(([k]) => value(g, k)))));
  const y = (v) => base - (v / top) * (base - T);
  const groupW = plotW / Math.max(games.length, 1);
  const n = metric.series.length;
  const barW = Math.max(3, Math.min(20, (groupW - 10) / n - 2));
  const every = Math.ceil(games.length / 8);
  let svg = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${metric.label} per game">`;
  for (let i = 0; i <= 4; i++) {
    const v = (top / 4) * i;
    svg += `<line class="${i ? "grid" : "axis"}" x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}"/>`
      + `<text x="${L - 6}" y="${y(v) + 4}" text-anchor="end">${Number.isInteger(v) ? v : v.toFixed(1)}</text>`;
  }
  games.forEach(({ g, index }, i) => {
    const gx = L + i * groupW;
    const start = gx + (groupW - (n * barW + (n - 1) * 2)) / 2;
    svg += `<rect class="hit" data-game="${index}" x="${gx}" y="${T}" width="${groupW}" height="${base - T}"/>`;
    metric.series.forEach(([key], s) => {
      const v = value(g, key);
      if (v > 0) svg += `<path class="s${s + 1}" pointer-events="none" d="${barPath(start + s * (barW + 2), y(v), barW, base)}"/>`;
    });
    if (i % every === 0) {
      svg += `<text x="${gx + groupW / 2}" y="${H - 7}" text-anchor="middle">${shortDate(g.date)}</text>`;
    }
  });
  el("trend").innerHTML = svg + "</svg>";

  const tip = el("chart-tip");
  el("trend").querySelectorAll(".hit").forEach((hit) => {
    const { g } = games.find((entry) => entry.index === Number(hit.dataset.game));
    hit.onmousemove = (e) => {
      const title = document.createElement("div");
      title.className = "tip-title";
      title.textContent = `vs ${g.opponent} · ${shortDate(g.date)}`;
      tip.replaceChildren(title);
      metric.series.forEach(([key, name], s) => {
        const row = document.createElement("div");
        row.className = "tip-row";
        const swatch = document.createElement("i");
        swatch.style.background = `var(--series-${s + 1})`;
        const val = document.createElement("b");
        val.textContent = fmt(value(g, key));
        row.append(swatch, n > 1 ? name : metric.label, val);
        tip.appendChild(row);
      });
      tip.hidden = false;
      const card = el("trend-card").getBoundingClientRect();
      const left = Math.min(e.clientX - card.left + 12, card.width - tip.offsetWidth - 8);
      tip.style.left = Math.max(8, left) + "px";
      tip.style.top = Math.max(8, e.clientY - card.top - tip.offsetHeight - 10) + "px";
    };
    hit.onmouseleave = () => { tip.hidden = true; };
    hit.onclick = () => { tip.hidden = true; openGamePage(g.game_id); };
  });
}

function renderHalves(game, target) {
  const rows = [
    ["Shots", (st) => st.shots_us], ["Opponent shots", (st) => st.shots_them],
    ["Ball-control (min)", (st) => (st.poss_secs_us / 60).toFixed(1)],
    ["Passes", (st) => st.passes_us], ["Box entries", (st) => st.box_us],
    ["Opponent box entries", (st) => st.box_them],
    ["Attacking-third entries", (st) => st.att_third_us], ["Packing", (st) => st.packing_us],
    ["Tracked sequences", (st) => st.sequences_us],
  ];
  const tbody = target || document.querySelector("#halves-table tbody");
  tbody.replaceChildren();
  for (const [label, pick] of rows) {
    const tr = document.createElement("tr");
    for (const text of [label, pick(game.first), pick(game.second), pick(game.whole)]) {
      const td = document.createElement("td");
      td.textContent = text;
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
  }
}

function renderGamesTable() {
  const data = _analytics;
  const tbody = document.querySelector("#analytics-table tbody");
  const tfoot = document.querySelector("#analytics-table tfoot");
  tbody.replaceChildren();
  data.games.forEach((g, index) => {
    const st = g[_seg];
    const tr = document.createElement("tr");
    const cells = [g.date, g.opponent, scoreText(g.score) || "–", ctrlText(st), st.passes_us, st.shots_us,
      st.shots_them, st.box_us, st.att_third_us, st.packing_us, st.sequences_us];
    cells.forEach((val) => {
      const td = document.createElement("td");
      td.textContent = val;
      td.title = val;              // full value on hover (opponent may be truncated)
      tr.appendChild(td);
    });
    tr.addEventListener("click", () => openGamePage(g.game_id));
    tbody.appendChild(tr);
  });
  const s = data.season[_seg];
  // Record over the games that have a score: wins–draws–losses.
  const tally = (result) => data.games.filter((g) => g.score && g.score.result === result).length;
  const record = data.games.some((g) => g.score) ? `${tally("win")}W ${tally("draw")}D ${tally("loss")}L` : "–";
  tfoot.innerHTML = data.games.length
    ? `<tr><td>Season</td><td>${s.games} games</td><td>${record}</td><td>${ctrlText(s)}</td>`
      + `<td>${s.passes_us}</td><td>${s.shots_us}</td><td>${s.shots_them}</td>`
      + `<td>${s.box_us}</td><td>${s.att_third_us}</td><td>${s.packing_us}</td>`
      + `<td>${s.sequences_us}</td></tr>`
    : "";
}

// A game's own page has its stats, video and timeline: the season page sends you there.
function gameByNumber(number) { return allGames.find((g) => Number(g.id.split("-").pop()) === number); }
function openGamePage(number) {
  const g = gameByNumber(number);
  if (!g) return;
  showView("games");
  openSingle(g.id);
  document.querySelector("main").scrollTo(0, 0);
}

function seasonItems() {
  const scored = allGames.filter((g) => g.score);
  const count = (result) => scored.filter((g) => g.score.result === result).length;
  const sum = (key) => scored.reduce((total, g) => total + g.score[key], 0);
  const item = (label, value, cls) => {
    const wrap = node("div", "sum-item");
    wrap.append(node("div", "sum-value " + (cls || ""), value), node("div", "sum-label", label));
    return wrap;
  };
  const diff = sum("us") - sum("them");
  return [
    item("Record", `${count("win")}W ${count("draw")}D ${count("loss")}L`),
    item("Goals for", sum("us")), item("Goals against", sum("them")),
    item("Goal difference", (diff > 0 ? "+" : "") + diff, diff > 0 ? "win" : diff < 0 ? "loss" : ""),
    item("Games with a score", `${scored.length} of ${allGames.length}`)];
}

// The top of the season page, in the shape of a game page: the record where the
// video sits, then a timeline with one dot per game instead of one per shot.
let seasonPick = null;     // id of the game whose dot is chosen
function renderSeasonTop() {
  const record = el("season-record");
  record.hidden = !allGames.some((g) => g.score);
  if (!record.hidden) record.replaceChildren(...seasonItems());
  const block = el("season-line");
  const games = allGames.slice().sort((a, b) => a.date.localeCompare(b.date));      // oldest first
  block.hidden = games.length === 0;
  if (block.hidden) return;
  const head = node("div", "row");
  const legend = node("div", "legend");
  for (const [cls, text] of [["win", "Win"], ["draw", "Draw"], ["loss", "Loss"], ["none", "No score"]]) {
    const item = node("span");
    item.append(node("i", "tl-key " + cls), text);
    legend.append(item);
  }
  head.append(node("h3", null, "Season timeline"), node("span", "spacer"), legend);
  const track = node("div", "tl-track season-track");
  track.style.setProperty("--n", games.length);       // many games: smaller dots, so they never overlap
  const picked = node("div", "tl-picked");
  const pick = (g, mark) => {
    seasonPick = g.id;
    track.querySelectorAll(".tl-mark").forEach((x) => x.classList.toggle("on", x === mark));
    const name = `vs ${g.opponent || g.title} · ${g.date_label || g.date}`;
    const toPage = () => {
      showView("games");
      openSingle(g.id);
      document.querySelector("main").scrollTo(0, 0);
    };
    const chip = node("button", "tl-chip", name);
    chip.title = "Open this game's page.";
    chip.onclick = toPage;
    const badge = node("span", "score");
    showScore(badge, g.score);
    const stats = _analytics && _analytics.games.find((x) => x.game_id === Number(g.id.split("-").pop()));
    const st = stats && stats.whole;
    const detail = node("span", "caption", st
      ? `Shots ${st.shots_us}–${st.shots_them} · Ball-control ${(st.poss_secs_us / 60).toFixed(1)} min · `
        + `Passes ${st.passes_us} · Box entries ${st.box_us}`
      : _analytics ? "No stats saved for this game." : "");
    const open = labelButton("games", "Open game page", "This game's video, timeline and full stats.", toPage);
    picked.replaceChildren(chip, badge, detail, node("span", "spacer"), open);
  };
  games.forEach((g, i) => {
    const result = g.score ? g.score.result : "none";
    const text = `vs ${g.opponent || g.title} · ${g.date_label || g.date}` + (g.score ? ` · ${scoreText(g.score)}` : "");
    const mark = node("button", "tl-mark shot " + result);
    mark.style.left = ((i + 0.5) / games.length) * 100 + "%";
    mark.title = text;
    mark.setAttribute("aria-label", text);
    mark.onclick = () => pick(g, mark);
    track.append(mark);
    if (g.id === seasonPick) pick(g, mark);
  });
  if (!picked.childElementCount) picked.append(node("span", "caption", "Click a dot to see that game."));
  const ends = node("div", "row tl-ends");
  ends.append(node("span", null, games[0].date_label || games[0].date), node("span", "spacer"),
    node("span", null, games[games.length - 1].date_label || games[games.length - 1].date));
  block.replaceChildren(head, track, ends, picked);
}

function renderAnalytics() {
  const data = _analytics;
  renderSeasonTop();
  if (!data) return;
  const st = data.season[_seg];
  document.querySelectorAll("#seg-toggle button").forEach((b) => b.classList.toggle("on", b.dataset.seg === _seg));
  el("analytics-empty").hidden = data.games.length > 0;
  el("analytics-body").hidden = data.games.length === 0;
  // Trace only serves stats for a plan-limited number of recent games; say so
  // instead of leaving the gap unexplained.
  const coverage = el("analytics-coverage");
  const total = Math.max(allGames.length, data.games.length);
  coverage.hidden = data.games.length >= total;
  coverage.textContent = `Stats from ${data.games.length} of your ${total} games. `
    + "Trace only provides stats for your most recent games on your current plan. "
    + "TraceDown keeps each game's stats once it has loaded them. The record above counts every game with a score.";
  renderTiles(st, st.games);
  el("season-map").innerHTML = st.territory_svg || "";
  setMapNote(st.sequences_us);
  renderPlayers(st);
  renderHalves(data.season);
  renderTrend();
  renderGamesTable();
}

function showAnalyticsProgress(done, total) {
  el("analytics-loading-text").textContent = total
    ? `Loading stats from Trace… game ${Math.min(done + 1, total)} of ${total}`
    : "Loading stats from Trace…";
  document.querySelector("#analytics-loading .bar > i").style.width =
    (total ? Math.round((done / total) * 100) : 0) + "%";
}

function setAnalyticsLoading(on) {
  el("analytics").classList.toggle("is-loading", on);
  el("analytics-loading").hidden = !on;
  for (const id of ["export-csv", "export-html", "analytics-refresh"]) el(id).disabled = on;
}

async function loadAnalytics(refresh) {
  const empty = el("analytics-empty");
  analyticsLoaded = true;
  empty.hidden = true;
  showAnalyticsProgress(0, 0);
  setAnalyticsLoading(true);
  try {
    _analytics = await api().get_analytics(refresh === true);
    setAnalyticsLoading(false);
    empty.textContent = "No stats yet. Trace provides stats for your most recent games.";
    renderAnalytics();
  } catch (e) {
    setAnalyticsLoading(false);
    _analytics = null;
    analyticsLoaded = false;
    el("analytics-body").hidden = true;
    empty.hidden = false;
    empty.textContent = "Couldn't load the stats. Check your connection and try again.";
  }
}

document.querySelectorAll("#seg-toggle button").forEach((b) => {
  b.onclick = () => {
    _seg = b.dataset.seg;
    document.querySelectorAll("#seg-toggle button").forEach((x) =>
      x.classList.toggle("on", x === b));
    renderAnalytics();
  };
});
el("trend-metric").onchange = renderAnalytics;
el("analytics-refresh").onclick = () => loadAnalytics(true);
el("export-csv").onclick = () => api().export_analytics("csv");
el("export-html").onclick = () => api().export_analytics("html");
el("auto").onchange = async (e) => {
  const on = await api().set_auto(e.target.checked);
  el("auto").checked = on;
  el("loginRow").hidden = !on;
  el("autoOptions").hidden = !on;
  el("login").checked = (await api().auto_settings()).login;      // on with automatic downloads, off with them
  showAutoStatus(on, "");
};
el("login").onchange = (e) => api().set_login(e.target.checked);
el("quitApp").onclick = () => api().quit_app();

// The small line in the sidebar: automatic downloads are on, or what they are doing right now.
let autoOn = false;
function showAutoStatus(on, text) {
  autoOn = on;
  el("autoStatus").hidden = !on;
  el("autoStatus").textContent = text || "Automatic downloads on";
}

// The choices under the automatic switch: how often to look, and what to fetch.
function showAutoOptions(on, options) {
  el("autoOptions").hidden = !on;
  if (!options) return;
  const pick = el("interval");
  const hours = String(options.interval);
  // A value set by hand in the config file still shows as what it is.
  if (![...pick.options].some((o) => o.value === hours)) pick.add(new Option(`Every ${hours} hours`, hours));
  pick.value = hours;
  el("autoFull").checked = options.full;
  el("autoHighlights").checked = options.highlights;
  el("autoRecaps").checked = options.recaps;
}

el("interval").onchange = (e) => api().save_settings({ interval: Number(e.target.value) });
["autoFull", "autoHighlights", "autoRecaps"].forEach((id) => {
  el(id).onchange = async () => {
    const res = await api().set_auto_choices({
      full: el("autoFull").checked, highlights: el("autoHighlights").checked, recaps: el("autoRecaps").checked });
    showAutoOptions(true, { ...res, interval: el("interval").value });      // a refused change snaps back
    el("autoNote").hidden = res.ok;
    el("autoNote").textContent = res.ok ? "" : res.error;
  };
});

// ---- first open: appearance and automatic downloads ----
function setTheme(choice) {
  if (choice === "system") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = choice;
  try { localStorage.setItem("theme", choice); } catch (err) { /* not available */ }
  el("theme").value = choice;
}

function showWelcome() {
  const dialog = el("welcome");
  if (dialog.open) return;
  dialog.addEventListener("cancel", (e) => e.preventDefault());      // Esc doesn't skip the choices
  dialog.querySelectorAll("#welcomeTheme button").forEach((b) => {
    b.classList.toggle("on", b.dataset.themeChoice === (document.documentElement.dataset.theme || "system"));
    b.onclick = () => {
      setTheme(b.dataset.themeChoice);
      dialog.querySelectorAll("#welcomeTheme button").forEach((x) => x.classList.toggle("on", x === b));
    };
  });
  el("welcomeAuto").onchange = () => { el("welcomeLoginRow").hidden = !el("welcomeAuto").checked; };
  el("welcomeDone").onclick = async () => {
    el("welcomeDone").disabled = true;
    const auto = el("welcomeAuto").checked;
    await api().finish_welcome(auto, auto && el("welcomeLogin").checked);
    dialog.close();
    el("auto").checked = auto;
    el("login").checked = auto && el("welcomeLogin").checked;
    el("loginRow").hidden = !auto;
    el("autoOptions").hidden = !auto;
    showAutoStatus(auto, "");
  };
  dialog.showModal();
}
el("removeAccount").onclick = async () => {
  const sel = el("account");
  const label = sel.options[sel.selectedIndex] ? sel.options[sel.selectedIndex].text : "this account";
  if (confirm(`Log out and remove "${label}"? Its saved login and history will be deleted.`)) {
    await api().remove_account(sel.value);
    showView("games");
    await refresh();
  }
};
async function reconnectFlow() {
  await api().reconnect_start();
  const b = el("reconnect");
  b.textContent = "I've logged in →";
  b.onclick = async () => {
    b.disabled = true; b.textContent = "Checking…";
    await api().reconnect_finish();
    b.disabled = false; await refresh(); b.textContent = "Reconnect";
  };
}
el("changeDir").onclick = async () => {
  const b = el("changeDir"); b.disabled = true;
  const res = await api().choose_output_dir();
  b.disabled = false;
  if (res && res.ok && res.output_dir) {
    el("outDir").textContent = res.output_dir;
    el("outDir").title = res.output_dir;
  }
};
el("quality").onchange = (e) => api().save_settings({ quality: e.target.value });
// Appearance: light, dark, or whatever the computer is set to. Remembered on this computer.
el("theme").value = document.documentElement.dataset.theme || "system";
el("theme").onchange = (e) => setTheme(e.target.value);
el("combine").onchange = (e) => api().save_settings({ combine: e.target.checked });
// Run on first ready, and also if the API is already present (e.g. after a
// page reload from the setup screen, where pywebviewready won't fire again).
// ---- updates: ask first, install only on "Update now"; say what changed afterwards ----
let foundUpdate = null;      // the newer release, once a check has found one

function showNotes(title, notes) {
  el("whatsNewTitle").textContent = title;
  el("whatsNewList").replaceChildren(...(notes && notes.length ? notes : ["No details were published for this version."])
    .map((line) => node("li", null, line)));
  el("whatsNew").showModal();
}
el("whatsNewClose").onclick = () => el("whatsNew").close();

// Look for a newer version. `asked` is true when the person pressed the button
// (so they are told the result either way); the automatic check stays quiet.
async function checkForUpdate(asked) {
  const result = el("updateResult");
  if (asked) result.textContent = "Checking…";
  let res;
  try { res = await api().check_update(); } catch (e) { res = { ok: false, error: String(e) }; }
  if (!res || !res.ok) {
    if (asked) result.textContent = (res && res.error) || "Couldn't check for updates.";
    return;
  }
  if (!res.available) {
    foundUpdate = null;
    el("updateBanner").hidden = true;
    if (asked) result.textContent = "You have the latest version.";
    return;
  }
  foundUpdate = res;
  result.textContent = `Version ${res.version} is available.`;
  el("updateTitle").textContent = `TraceDown ${res.version} is available.`;
  el("updateNote").textContent = res.can_install ? "Updating closes the app for a moment and reopens it."
    : "Download it from the releases page.";
  el("updateNow").textContent = res.can_install ? "Update now" : "Open download page";
  el("updateBar").hidden = true;
  for (const id of ["updateNow", "updateLater", "updateNotes"]) el(id).disabled = false;
  el("updateBanner").hidden = false;
}

el("checkUpdate").onclick = () => checkForUpdate(true);
el("showNotes").onclick = async () => {
  const mine = await api().version_notes();
  showNotes(`What's new in TraceDown ${mine.version}`, mine.notes);
};
el("updateLater").onclick = () => { el("updateBanner").hidden = true; };
el("updateNotes").onclick = () => showNotes(`What's new in ${foundUpdate.version}`, foundUpdate.notes);
el("updateNow").onclick = async () => {
  const note = el("updateNote");
  const installing = foundUpdate && foundUpdate.can_install;
  if (installing) {
    for (const id of ["updateNow", "updateLater"]) el(id).disabled = true;
    note.textContent = "Downloading the update…";
    el("updateBar").hidden = false;
  }
  let res;
  try { res = await api().install_update(); } catch (e) { res = { ok: false, error: String(e) }; }
  if (res && res.ok && res.restarting) {
    note.textContent = "Installing. TraceDown will close and reopen by itself.";
  } else if (res && res.ok) {
    if (installing) note.textContent = "Couldn't install automatically, so the download is shown in its folder. Open it to update.";
    for (const id of ["updateNow", "updateLater"]) el(id).disabled = false;
    el("updateBar").hidden = true;
  } else {
    note.textContent = (res && res.error) || "The update didn't work.";
    for (const id of ["updateNow", "updateLater"]) el(id).disabled = false;
    el("updateBar").hidden = true;
  }
};

// Once per version, after an update: list what changed.
async function showWhatsNewOnce() {
  let pending = null;
  try { pending = await api().whats_new(); } catch (e) { /* not essential */ }
  if (!pending) return;
  showNotes(`What's new in TraceDown ${pending.version}`, pending.notes);
  api().whats_new_seen();
}

// The splash stays up until the first load has finished (long enough to be seen,
// and never forever if something goes wrong).
const splashSince = Date.now();
function hideSplash() {
  setTimeout(() => el("splash").classList.add("is-done"), Math.max(0, 1100 - (Date.now() - splashSince)));
}
setTimeout(hideSplash, 12000);
const afterFirstLoad = () => {
  hideSplash();
  setTimeout(showWhatsNewOnce, 1300);          // once the splash has cleared
  setTimeout(() => checkForUpdate(false), 4000);
};
const firstLoad = () => refresh().then(afterFirstLoad, afterFirstLoad);
window.addEventListener("pywebviewready", firstLoad);
if (window.pywebview && window.pywebview.api) firstLoad();

el("clearDone").onclick = () => {
  for (let i = jobs.length - 1; i >= 0; i -= 1) {
    if (jobs[i].state !== "running" && jobs[i].state !== "waiting") jobs.splice(i, 1);
  }
  renderDownloads();
};
