"use strict";
// Rank listings against your resume: match badges on the board and a Ranking panel on the Profile tab.
(function () {
  const IB = window.IB;
  const { esc, api, ago } = IB;
  const STRONG = 70, OK = 45; // keep in step with the board's "Best match" grouping
  let status = null;          // last /api/ranking/status
  let running = null;         // { seconds, status } while a Claude ranking runs here

  const tier = score => (score >= STRONG ? "strong" : score >= OK ? "ok" : "weak");
  const tierLabel = { strong: "Strong match", ok: "Possible match", weak: "Weak match" };

  // ---------- board badge ----------
  IB.hooks.listingMeta.push(l => {
    if (l.match_score == null) return "";
    const t = tier(l.match_score);
    const by = l.match_method === "claude" ? "Claude" : "keyword match";
    const tip = `${tierLabel[t]}, ${l.match_score}/100 (${by}): ${l.match_reason || "no reason given"}`;
    return `<button type="button" class="match-badge ${t}" data-match-why aria-expanded="false"
        title="${esc(tip)}" aria-label="${esc(`${tierLabel[t]}, ${l.match_score} out of 100, scored by ${by}. Show why.`)}">
        <span class="num">${l.match_score}</span>${l.match_method === "claude"
          ? '<svg class="match-claude" viewBox="0 0 12 12" aria-hidden="true"><path d="M6 1.2 7.2 4.8 10.8 6 7.2 7.2 6 10.8 4.8 7.2 1.2 6 4.8 4.8Z"/></svg>'
          : ""}</button>`;
  });

  // Click or Enter on a badge shows the reason under the row; a second press hides it.
  document.addEventListener("click", e => {
    const btn = e.target.closest("[data-match-why]");
    if (!btn) return;
    const row = btn.closest(".listing");
    const l = row && IB.listing(row.dataset.id);
    if (!l) return;
    let why = row.querySelector(".match-why");
    const open = btn.getAttribute("aria-expanded") === "true";
    btn.setAttribute("aria-expanded", String(!open));
    if (open) { why?.remove(); return; }
    if (!why) {
      why = document.createElement("p");
      why.className = "match-why";
      row.querySelector(".l-main").append(why);
    }
    why.innerHTML = `${esc(l.match_reason || "No reason given.")}
      <span class="muted">· ${l.match_method === "claude" ? "Claude" : "Keyword match"}, ${l.match_score}/100</span>`;
  });

  // ---------- board note for "Best match" without a profile ----------
  function sortValue() {
    return document.querySelector("#filters [name=sort]")?.value;
  }

  function updateNote() {
    let note = document.getElementById("rank-note");
    const hasProfile = status ? status.has_profile : !!(IB.profile && Object.keys(IB.profile.data || {}).length);
    const show = sortValue() === "match" && (status || IB.profile) && !hasProfile;
    if (!show) { note?.remove(); return; }
    if (!note) {
      note = document.createElement("p");
      note.id = "rank-note";
      note.className = "rank-note";
      note.innerHTML = `Best match needs your resume. <a class="link" href="#profile">Add it on the Profile tab</a>
        and every listing gets a score.`;
      document.getElementById("result-count")?.after(note);
    }
  }

  let filling = false;
  IB.hooks.listingsLoaded.push(() => {
    updateNote();
    // New listings since the last check have no score yet; fill them in once, then redraw.
    if (sortValue() !== "match" || filling || !status?.has_profile) return;
    const rows = [...document.querySelectorAll("#listings .listing[data-id]")];
    if (!rows.some(r => IB.listing(r.dataset.id)?.match_score == null)) return;
    filling = true;
    refreshStatus().then(s => { if (s?.computed) IB.reloadListings(); }).finally(() => { filling = false; });
  });

  async function refreshStatus() {
    try { status = await api("/api/ranking/status", { quiet: true }); } catch { return null; }
    updateNote();
    return status;
  }

  // ---------- Profile tab panel ----------
  let panelEl = null;

  function statusText(s) {
    if (!s.has_profile) return "Add your resume above to score listings.";
    const parts = [`${s.quick.toLocaleString()} listing${s.quick === 1 ? "" : "s"} with a keyword score`];
    parts.push(s.claude ? `${s.claude} ranked by Claude ${ago(s.claude_at)}` : "none ranked by Claude yet");
    let text = parts.join(", ") + ".";
    if (s.quick_at) text += ` Keyword scores updated ${ago(s.quick_at)}.`;
    if (s.unscored > 0) text += ` ${s.unscored.toLocaleString()} not scored yet.`;
    return text;
  }

  function renderPanel() {
    const el = panelEl;
    if (!el || !el.isConnected) return;
    const s = status;
    el.className = "panel rank-panel";
    el.setAttribute("aria-labelledby", "rank-title");
    const busy = !!running;
    el.innerHTML = `
      <h2 class="panel-title" id="rank-title">Ranking</h2>
      <p class="rank-status" role="status">${s ? esc(statusText(s)) : "Loading…"}</p>
      <div class="rank-actions">
        <button type="button" class="btn btn-primary" data-rank-claude ${!s?.has_profile || busy ? "disabled" : ""}>
          Rank top 40 with Claude</button>
        <button type="button" class="btn btn-quiet" data-rank-quick ${!s?.has_profile || busy ? "disabled" : ""}>
          Recompute keyword scores</button>
        <span class="form-msg ${running ? "busy" : ""}" data-rank-msg role="status" aria-live="polite">${running
          ? esc(progressText(running)) : ""}</span>
      </div>
      <dl class="rank-explain">
        <dt>Keyword scores</dt>
        <dd>Every listing gets one instantly from its title, category, terms, locations and degree against your
          skills and preferences. They are rough: a title that doesn't name a skill scores lower.</dd>
        <dt>Claude scores <svg class="match-claude" viewBox="0 0 12 12" aria-hidden="true"><path d="M6 1.2 7.2 4.8 10.8 6 7.2 7.2 6 10.8 4.8 7.2 1.2 6 4.8 4.8Z"/></svg></dt>
        <dd>Claude reads your full profile and rescores the 40 best keyword matches that it hasn't scored yet,
          with a one-sentence reason. It sees titles and details, not full job descriptions. Takes about a minute
          and uses your Claude plan. Run it again to go further down the list.</dd>
      </dl>
      <p class="rank-tiers muted">Badges on the board:
        <span class="match-badge strong static"><span class="num">${STRONG}+</span></span> strong
        <span class="match-badge ok static"><span class="num">${OK}+</span></span> possible
        <span class="match-badge weak static"><span class="num">&lt;${OK}</span></span> weak.
        Choose Sort: Best match to see the best first.</p>`;
  }

  function progressText(r) {
    return r.status === "queued" ? `Waiting to start… ${r.seconds}s` : `Claude is ranking listings… ${r.seconds}s`;
  }

  function setMsg(text, kind = "") {
    const msg = panelEl?.querySelector("[data-rank-msg]");
    if (msg) { msg.className = `form-msg ${kind}`; msg.textContent = text; }
  }

  async function rankWithClaude() {
    if (running) return;
    running = { seconds: 0, status: "queued" };
    renderPanel();
    const payload = { limit: 40 };
    try {
      const r = await IB.runJob("rank_listings", payload, {
        onProgress(seconds, st) { running = { seconds, status: st }; setMsg(progressText(running), "busy"); },
      });
      running = null;
      await refreshStatus();
      renderPanel();
      let text = r.message || `Ranked ${r.ranked} listing${r.ranked === 1 ? "" : "s"} in ${Math.round(r.seconds)}s.`;
      if (r.failed_batches) text += ` ${r.skipped} couldn't be ranked: ${r.error}`;
      setMsg(text, r.failed_batches ? "error" : "ok");
      IB.reloadListings();
    } catch (err) {
      running = null;
      renderPanel();
      setMsg(err.message, "error");
    }
  }

  async function recomputeQuick() {
    setMsg("Scoring…", "busy");
    try {
      const r = await api("/api/ranking/quick", { method: "POST", quiet: true });
      status = r.status;
      renderPanel();
      setMsg(`Scored ${r.computed.toLocaleString()} listings in ${r.seconds}s.`, "ok");
      IB.reloadListings();
    } catch (err) {
      setMsg(err.message, "error");
    }
  }

  IB.hooks.profile.push((p, container) => {
    panelEl = container;
    container.addEventListener("click", e => {
      if (e.target.closest("[data-rank-claude]")) rankWithClaude();
      else if (e.target.closest("[data-rank-quick]")) recomputeQuick();
    });
    renderPanel();
    // The profile may have just changed; the status call fills in scores for the new version.
    const before = status?.profile_version;
    refreshStatus().then(s => {
      renderPanel();
      if (s && (s.computed || s.profile_version !== before)) IB.reloadListings();
    });
  });

  // If this page was closed mid-ranking, show that the job is still going when it comes back.
  refreshStatus().then(async s => {
    if (s?.computed && sortValue() === "match") IB.reloadListings();
    if (!s?.running_job || running) return;
    running = { seconds: 0, status: "running" };
    renderPanel();
    const started = Date.now();
    for (;;) {
      await new Promise(r => setTimeout(r, 2000));
      let job;
      try { job = await api(`/api/ai/jobs/${s.running_job}`, { quiet: true }); } catch { break; }
      running = { seconds: Math.round((Date.now() - started) / 1000), status: job.status };
      setMsg(progressText(running), "busy");
      if (job.status === "done" || job.status === "error") break;
    }
    running = null;
    await refreshStatus();
    renderPanel();
    IB.reloadListings();
  });
})();
