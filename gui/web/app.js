const api = () => window.pywebview.api;
const el = (id) => document.getElementById(id);

async function refresh() {
  const s = await api().get_status();
  const st = el("status");
  const btn = el("reconnect");
  const conn = s.connection || (s.logged_in ? "ok" : "expired");
  if (conn === "ok") {
    st.textContent = "Logged in"; st.className = "status ok";
    btn.style.display = "none";
  } else if (conn === "none") {
    // Fresh install, no account yet — steer to Add account, not the dead-end
    // Reconnect (which can't onboard a brand-new user).
    st.textContent = "No account yet"; st.className = "status bad";
    btn.style.display = "inline-block";
    btn.textContent = "Connect Trace account";
    btn.onclick = connectAccount;
  } else {
    st.textContent = "Session expired"; st.className = "status bad";
    btn.style.display = "inline-block";
    btn.textContent = "Reconnect";
    btn.onclick = reconnectFlow;
  }
  const sd = el("statusDetail");
  if (sd) {
    sd.textContent = (conn !== "ok" && s.login_detail) ? ("Diagnostic: " + s.login_detail) : "";
    st.title = s.login_detail || "";
  }
  el("auto").checked = s.auto;
  if (s.settings) el("quality").value = s.settings.quality;
  if (s.settings) el("combine").checked = s.settings.combine !== false;
  if (s.settings && s.settings.output_dir) {
    el("outDir").textContent = s.settings.output_dir;
    el("outDir").title = s.settings.output_dir;
  }
  el("version").textContent = "TraceDown v" + (s.version || "");
  await renderAccounts();
  const games = await api().list_games();
  renderGames(games);
}

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

function renderGames(games) {
  const box = el("games");
  box.innerHTML = "";
  for (const g of games) {
    const div = document.createElement("div");
    div.className = "game"; div.id = "g-" + g.id;
    div.innerHTML = `
      <div class="thumb"></div>
      <div class="meta">
        <div class="date">${g.date}</div>
        <div class="opp">vs ${g.opponent || g.title}</div>
        <div class="bar" style="display:none"><i></i></div>
        <div class="speed"></div>
      </div>
      <div class="action"></div>`;
    const action = div.querySelector(".action");
    if (g.state === "saved") {
      action.innerHTML = `<span class="saved">✓ Saved</span>`;
    } else {
      setDownloadBtn(action, g.id);
    }
    box.appendChild(div);
    loadThumb(div, g);
  }
}

function loadThumb(div, g) {
  if (!g.team_id) return;
  api().get_thumb(g.team_id, g.id).then((url) => {
    if (url) {
      const t = div.querySelector(".thumb");
      t.style.backgroundImage = `url("${url}")`;
      t.style.backgroundSize = "cover";
      t.style.backgroundPosition = "center";
    }
  }).catch(() => {});
}

function showBar(id) { const g = el("g-" + id); if (g) g.querySelector(".bar").style.display = "block"; }

function setDownloadBtn(action, id) {
  action.innerHTML = "";
  const b = document.createElement("button");
  b.textContent = "Download";
  b.onclick = () => startDownload(id);
  action.appendChild(b);
}
function setCancelBtn(action, id) {
  action.innerHTML = "";
  const b = document.createElement("button");
  b.textContent = "Cancel";
  b.style.background = "#3a2330"; b.style.color = "#f0a0b8";
  b.onclick = () => { b.disabled = true; b.textContent = "Cancelling…"; api().cancel(); };
  action.appendChild(b);
}
function startDownload(id) {
  const g = el("g-" + id);
  if (!g) return;
  showBar(id);
  setCancelBtn(g.querySelector(".action"), id);
  api().download_game(id);
}

window.onPy = (event, p) => {
  const g = el("g-" + p.id);
  if (!g) return;
  if (event === "progress") {
    showBar(p.id);
    g.querySelector(".bar > i").style.width = p.percent + "%";
    g.querySelector(".speed").textContent = `Half ${p.half} · ${p.speed} MB/s`;
    const action = g.querySelector(".action");
    const btn = action.querySelector("button");
    if (!btn || btn.textContent === "Download") setCancelBtn(action, p.id);
  } else if (event === "cancelled") {
    g.querySelector(".bar").style.display = "none";
    g.querySelector(".bar > i").style.width = "0%";
    g.querySelector(".speed").textContent = "";
    setDownloadBtn(g.querySelector(".action"), p.id);
  } else if (event === "saved") {
    g.querySelector(".bar").style.display = "none";
    g.querySelector(".speed").textContent = "";
    g.querySelector(".action").innerHTML = `<span class="saved">✓ Saved</span>`;
  } else if (event === "unavailable") {
    g.querySelector(".bar").style.display = "none";
    g.querySelector(".speed").textContent = "";
    g.querySelector(".action").innerHTML = `<span style="color:#8aa0b4">No video</span>`;
  } else if (event === "error") {
    g.querySelector(".bar").style.display = "none";
    g.querySelector(".speed").textContent = "";
    g.querySelector(".action").innerHTML = `<span style="color:#e0a33e" title="${(p.message||'').replace(/"/g,'')}">Failed</span>`;
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

el("downloadAll").onclick = () => api().download_new();
el("openFolder").onclick = () => api().open_folder();
el("settingsBtn").onclick = () => el("settings").showModal();
el("closeSettings").onclick = () => el("settings").close();

// ---- team analytics dialog: lazy-loaded (fetched fresh each time it opens) ----
async function loadAnalytics() {
  const tbody = document.querySelector("#analytics-table tbody");
  const tfoot = document.querySelector("#analytics-table tfoot");
  const map = el("season-map");
  const empty = el("analytics-empty");
  try {
    const data = await api().get_analytics();
    map.innerHTML = data.season_territory_svg || "";
    tbody.innerHTML = "";
    empty.hidden = data.games.length > 0;
    data.games.forEach((g) => {
      const tr = document.createElement("tr");
      const ctrl = (g.poss_secs_us / 60).toFixed(1)
        + (g.poss_pct_us == null ? "" : ` (${g.poss_pct_us}%)`);
      const cells = [g.date, g.opponent, ctrl,
        g.passes_us, g.shots_us, g.shots_them, g.box_us, g.att_third_us,
        g.packing_us];
      cells.forEach((val) => {
        const td = document.createElement("td");
        td.textContent = val;
        td.title = val;              // full value on hover (opponent may be truncated)
        tr.appendChild(td);
      });
      tr.addEventListener("click", () => { map.innerHTML = g.territory_svg; });
      tbody.appendChild(tr);
    });
    const s = data.season;
    const sCtrl = (s.poss_secs_us / 60).toFixed(1)
      + (s.poss_pct_us == null ? "" : ` (${s.poss_pct_us}%)`);
    tfoot.innerHTML = data.games.length
      ? `<tr><td>Season</td><td>${s.games} games</td><td>${sCtrl}</td>`
        + `<td>${s.passes_us}</td><td>${s.shots_us}</td><td>${s.shots_them}</td>`
        + `<td>${s.box_us}</td><td>${s.att_third_us}</td><td>${s.packing_us}</td></tr>`
      : "";
  } catch (e) {
    tbody.innerHTML = "";
    tfoot.innerHTML = "";
    empty.hidden = false;
    empty.textContent = "Couldn't load analytics — check your connection and try again.";
  }
}
el("analyticsBtn").onclick = async () => {
  el("analytics").showModal();
  await loadAnalytics();
};
el("closeAnalytics").onclick = () => el("analytics").close();
el("export-csv").onclick = () => api().export_analytics("csv");
el("export-html").onclick = () => api().export_analytics("html");
el("auto").onchange = (e) => api().set_auto(e.target.checked);
el("removeAccount").onclick = async () => {
  const sel = el("account");
  const label = sel.options[sel.selectedIndex] ? sel.options[sel.selectedIndex].text : "this account";
  if (confirm(`Log out and remove "${label}"? Its saved login and history will be deleted.`)) {
    await api().remove_account(sel.value);
    el("settings").close();
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
el("combine").onchange = (e) => api().save_settings({ combine: e.target.checked });
// Run on first ready, and also if the API is already present (e.g. after a
// page reload from the setup screen, where pywebviewready won't fire again).
window.addEventListener("pywebviewready", refresh);
if (window.pywebview && window.pywebview.api) refresh();
