"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const PAGE = 50;
const DAY = 86400;
const REGION_LABELS = { US: "US", CA: "Canada", REMOTE: "Remote" };

const state = {
  offset: 0,
  total: 0,
  statuses: ["saved", "applied", "interviewing", "offer", "rejected"],
  tracked: new Map(), // listing id -> tracker item
  companies: [],
  prevVisit: 0,
  lastGroup: null,
};

// ---------- helpers ----------
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function ago(ts) {
  if (!ts) return "";
  const s = Date.now() / 1000 - ts;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < DAY) return `${Math.round(s / 3600)}h ago`;
  if (s < DAY * 60) return `${Math.round(s / DAY)}d ago`;
  return new Date(ts * 1000).toLocaleDateString(undefined, { month: "short", year: "numeric" });
}

function dayGroup(ts) {
  if (!ts) return "Date unknown";
  const start = new Date(); start.setHours(0, 0, 0, 0);
  const today = start.getTime() / 1000;
  if (ts >= today) return "Today";
  if (ts >= today - DAY) return "Yesterday";
  if (ts >= today - 6 * DAY) return "This week";
  if (ts >= today - 30 * DAY) return "This month";
  return "Older";
}

function monogram(name) {
  const words = String(name).replace(/[^\p{L}\p{N} ]/gu, "").split(/\s+/).filter(Boolean);
  return ((words[0]?.[0] ?? "?") + (words.length > 1 ? words[1][0] : words[0]?.[1] ?? "")).toUpperCase();
}

function store(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch {}
}
function load(key, fallback) {
  try { const v = localStorage.getItem(key); return v === null ? fallback : JSON.parse(v); } catch { return fallback; }
}

let toastTimer;
function toast(message) {
  const el = $("#toast");
  el.textContent = message;
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, 5000);
}

async function api(path, options = {}) {
  let res;
  try {
    const json = typeof options.body === "string"; // FormData uploads set their own content type
    res = await fetch(path, { headers: json ? { "Content-Type": "application/json" } : {}, ...options });
  } catch {
    const err = new Error("Couldn't reach Intern Board. Is ./run.sh still running?");
    toast(err.message);
    throw err;
  }
  if (!res.ok) {
    let detail = `${res.status}`;
    try { const body = await res.json(); detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail); } catch {}
    const err = new Error(detail);
    err.status = res.status;
    if (!options.quiet) toast(`Request failed: ${detail}`);
    throw err;
  }
  return res.json();
}

function deadlineInfo(deadline) {
  if (!deadline) return null;
  const days = Math.round((new Date(deadline + "T23:59:59") - Date.now()) / 86400000);
  const label = new Date(deadline + "T12:00:00").toLocaleDateString(undefined, { month: "short", day: "numeric" });
  return { days, label };
}

function deadlineTag(deadline) {
  const d = deadlineInfo(deadline);
  if (!d) return "";
  if (d.days < 0) return `<span class="tag danger">Overdue · ${d.label}</span>`;
  if (d.days <= 3) return `<span class="tag warn">Due ${d.days === 0 ? "today" : d.label}</span>`;
  return `<span class="tag">Due ${d.label}</span>`;
}

// ---------- extension points for features/*.js ----------
// Features register functions here instead of editing this file:
//   IB.hooks.listingMeta.push(listing => "<span>html</span>")    extra tags on a board row
//   IB.hooks.listingActions.push(listing => "<button>…</button>") buttons before Track/Apply
//   IB.hooks.drawer.push((trackerItem, sectionEl) => { … })     a section in the tracker drawer
//   IB.hooks.profile.push((profile, containerEl) => { … })      a panel under the Profile tab
//   IB.hooks.listingsLoaded.push(() => { … })                   after board rows render
const IB = window.IB = {
  hooks: { listingMeta: [], listingActions: [], drawer: [], profile: [], listingsLoaded: [] },
  pages: {},                   // view name -> (sectionEl, URLSearchParams) => void, for full pages
  monogram: name => monogram(name),
  api, esc, toast, ago, deadlineInfo, state,
  profile: null,               // last loaded /api/profile response
  reloadListings: () => loadListings(true),
  reloadTracker: () => loadTracker(),
  loadProfile: () => loadProfile(),
  showView: view => { location.hash = `#${view}`; },
  listing: id => listCache.get(id) ?? state.tracked.get(id),

  // Start an AI job and wait for it. Resolves with the job's result; rejects with an Error
  // whose message is fit to show. onProgress(seconds) is called while it runs.
  async runJob(kind, payload = {}, { onProgress } = {}) {
    const { job_id } = await api("/api/ai/jobs", { method: "POST", body: JSON.stringify({ kind, payload }) });
    const started = Date.now();
    for (;;) {
      await new Promise(r => setTimeout(r, 1500));
      const job = await api(`/api/ai/jobs/${job_id}`);
      onProgress?.(Math.round((Date.now() - started) / 1000), job.status);
      if (job.status === "done") return job.result;
      if (job.status === "error") throw new Error(job.error || "The AI request failed.");
      if (Date.now() - started > 10 * 60 * 1000) throw new Error("This is taking too long. The app may have restarted; try again.");
    }
  },
};

function runHooks(name, ...args) {
  return IB.hooks[name].map(fn => { try { return fn(...args) ?? ""; } catch (err) { console.error(err); return ""; } }).join("");
}

// ---------- views ----------
// Sidebar links -> the section that shows them. "matches" is the board sorted by match;
// the three tools share one page.
const VIEWS = { board: "board", matches: "board", tracker: "tracker", companies: "companies", profile: "profile",
                resume: "tool", cover: "tool", people: "people" };
const SECTIONS = ["board", "tracker", "companies", "profile", "tool", "people"];
let currentView = null;

// "#people?listing=…" -> showView("people", URLSearchParams)
function viewFromHash() {
  const [view, query] = location.hash.slice(1).split("?");
  return [view, new URLSearchParams(query || "")];
}

function showView(view, params = new URLSearchParams()) {
  if (!(view in VIEWS)) view = "board";
  const previous = currentView;
  currentView = view;
  for (const s of SECTIONS) $(`#${s}-view`).hidden = s !== VIEWS[view];
  for (const a of $$(".nav [data-view-link]")) {
    if (a.dataset.viewLink === view) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  }
  closeNav();
  if (view === "matches" && filters().sort !== "match") { setFilter("sort", "match"); if (previous) filtersChanged(); }
  if (view === "board" && previous === "matches" && filters().sort === "match") { setFilter("sort", "posted"); filtersChanged(); }
  if (view === "companies" && !state.companies.length) loadCompanies();
  if (view === "profile") loadProfile();
  if (VIEWS[view] === "tool") renderTool(view);
  if (IB.pages[view]) IB.pages[view]($(`#${VIEWS[view]}-view`), params);
  store("view", view);
}

// ---------- sidebar (mobile) ----------
function openNav() {
  document.body.classList.add("nav-open");
  $("#scrim").hidden = false;
  $("#nav-open").setAttribute("aria-expanded", "true");
}
function closeNav() {
  document.body.classList.remove("nav-open");
  $("#scrim").hidden = true;
  $("#nav-open").setAttribute("aria-expanded", "false");
}
$("#nav-open").addEventListener("click", openNav);
$("#scrim").addEventListener("click", closeNav);
document.addEventListener("keydown", e => { if (e.key === "Escape" && document.body.classList.contains("nav-open")) closeNav(); });

function renderWho(p) {
  const name = p?.data?.name?.trim();
  $("#who-name").textContent = name || "Set up your profile";
  $("#who-avatar").textContent = name ? monogram(name) : "?";
}

// ---------- tool pages ----------
const TOOLS = {
  resume: { title: "Resume tailor", hook: "documents",
            lede: "A one-page resume rewritten for one internship, using only what's in your profile. Edit it, then save as PDF." },
  cover: { title: "Cover letter", hook: "documents",
           lede: "A short cover letter for one internship, in the tone you pick. It draws on real experience from your profile." },
};

function renderTool(view) {
  const tool = TOOLS[view];
  $("#tool-heading").textContent = tool.title;
  $("#tool-lede").textContent = tool.lede;
  const items = [...state.tracked.values()].sort((a, b) =>
    state.statuses.indexOf(a.status) - state.statuses.indexOf(b.status) || a.company.localeCompare(b.company));
  const empty = items.length === 0;
  $("#tool-empty").hidden = !empty;
  $(".tool-picker").hidden = empty;
  $("#tool-body").hidden = empty;
  if (empty) return;

  const select = $("#tool-listing");
  const wanted = select.value || load("toolListing", null);
  select.innerHTML = items.map(i => `<option value="${esc(i.id)}">${esc(i.company)} — ${esc(i.title)} (${esc(i.status)})</option>`).join("");
  select.value = items.some(i => i.id === wanted) ? wanted : items[0].id;
  $("#tool-hint").textContent = "Showing internships from your tracker.";
  renderToolBody(view);
}

function renderToolBody(view = currentView) {
  const item = state.tracked.get($("#tool-listing").value);
  const body = $("#tool-body");
  body.innerHTML = "";
  const hook = IB.hooks.drawer.find(h => h.tool === TOOLS[view].hook);
  if (!item || !hook) return;
  store("toolListing", item.id);
  const section = document.createElement("section");
  section.className = "drawer-section tool-section";
  body.append(section);
  try { hook(item, section); } catch (err) { console.error(err); }
}
$("#tool-listing").addEventListener("change", () => renderToolBody());
window.addEventListener("hashchange", () => showView(...viewFromHash()));

// ---------- filters ----------
const form = $("#filters");

function filters() {
  const f = new FormData(form);
  return {
    q: f.get("q").trim(),
    region: f.get("region"),
    category: f.get("category"),
    term: f.get("term"),
    degree: f.get("degree"),
    source: f.get("source"),
    sort: f.get("sort"),
    new_only: f.get("new_only") === "on",
    hide_tracked: f.get("hide_tracked") === "on",
  };
}

function setFilter(name, value) {
  const el = form.elements[name];
  if (el instanceof RadioNodeList) for (const r of el) r.checked = r.value === value;
  else if (el.type === "checkbox") el.checked = !!value;
  else el.value = value;
}

function restoreFilters() {
  for (const [name, value] of Object.entries(load("filters", {}))) {
    const el = form.elements[name];
    if (!el) continue;
    if (el instanceof RadioNodeList || el.type === "checkbox") setFilter(name, value);
    else { el.dataset.pending = value; el.value = value; }
  }
}

function filtersChanged() {
  const f = filters();
  store("filters", f);
  for (const sel of $$("select", form)) sel.classList.toggle("set", sel.name !== "sort" && !!sel.value);
  const active = f.q || f.region || f.category || f.term || f.degree || f.source || f.new_only || f.hide_tracked;
  $("#clear-filters").hidden = !active;
  $("#stat-new").closest(".stat").classList.toggle("active", f.new_only);
  $("#stat-ca").closest(".stat").classList.toggle("active", f.region === "CA");
  $("#stat-board").closest(".stat").classList.toggle("active", f.source === "board");
  loadListings(true);
}

function clearFilters() {
  for (const name of ["q", "category", "term", "degree", "source"]) setFilter(name, "");
  setFilter("region", "");
  setFilter("new_only", false);
  setFilter("hide_tracked", false);
  filtersChanged();
}

let searchTimer;
form.addEventListener("input", e => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(filtersChanged, e.target.type === "search" ? 250 : 0);
});
form.addEventListener("submit", e => e.preventDefault());
$("#clear-filters").addEventListener("click", clearFilters);
$("#empty").addEventListener("click", e => { if (e.target.closest("[data-action=clear]")) clearFilters(); });

document.addEventListener("keydown", e => {
  if (e.key === "/" && !e.target.closest("input, textarea, select") && !$("#board-view").hidden) {
    e.preventDefault();
    form.elements.q.focus();
  }
});

$("#stats").addEventListener("click", e => {
  const stat = e.target.closest(".stat");
  if (!stat) return;
  const f = filters();
  switch (stat.dataset.stat) {
    case "new": setFilter("new_only", !f.new_only); break;
    case "CA": setFilter("region", f.region === "CA" ? "" : "CA"); break;
    case "board": setFilter("source", f.source === "board" ? "" : "board"); break;
    case "due": location.hash = "#tracker"; return;
  }
  filtersChanged();
});

// ---------- meta ----------
function fillSelect(select, items, allLabel) {
  const want = select.dataset.pending ?? select.value;
  select.innerHTML = `<option value="">${allLabel}</option>` +
    items.map(i => `<option value="${esc(i.value)}">${esc(i.value)} · ${i.count.toLocaleString()}</option>`).join("");
  select.value = items.some(i => i.value === want) ? want : "";
  select.classList.toggle("set", !!select.value);
  delete select.dataset.pending;
}

function setSync(kind, text) {
  const el = $("#sync-status");
  el.className = `sync-status ${kind}`;
  $(".label", el).textContent = text;
}

async function loadMeta() {
  const meta = await api("/api/meta");
  fillSelect(form.elements.category, meta.categories.filter(c => c.value), "All categories");
  fillSelect(form.elements.term, meta.terms, "Any term");
  const hadTerms = state.terms?.length;
  state.terms = meta.terms.map(t => t.value);
  if (!hadTerms && IB.profile?.preferences && !$("#profile-view").hidden) renderProfile(IB.profile);
  fillSelect(form.elements.degree, meta.degrees, "Any degree");
  const regions = Object.fromEntries(meta.regions.map(r => [r.value, r.count]));
  for (const el of $$("[data-count]", form)) el.textContent = (regions[el.dataset.count] ?? 0).toLocaleString();
  const sources = Object.fromEntries(meta.sources.map(s => [s.value, s.count]));

  $("#open-total").textContent = meta.active.toLocaleString();
  $("#stat-ca").textContent = (regions.CA ?? 0).toLocaleString();
  $("#stat-board").textContent = (sources.board ?? 0).toLocaleString();
  $("#board-count-text").textContent = meta.boards.enabled
    ? `${(meta.boards.hiring ?? 0).toLocaleString()} company job boards`
    : "company job boards";
  $("#companies-count").textContent = meta.boards.enabled ? (meta.boards.enabled).toLocaleString() : "";

  if (meta.last_error) setSync("error", "Last refresh failed");
  else if (meta.last_refresh) setSync("ok", `Updated ${ago(meta.last_refresh)}`);
  else setSync("busy", "First import…");
  $("#sync-status").title = meta.last_error || "";
  return meta;
}

async function updateNewCount() {
  const { total } = await api(`/api/listings?limit=1&since=${state.prevVisit}`);
  $("#stat-new").textContent = total.toLocaleString();
}

// ---------- listings ----------
function listingQuery(offset) {
  const f = filters();
  const p = new URLSearchParams({ offset, limit: PAGE, sort: f.sort });
  for (const k of ["q", "region", "category", "term", "degree", "source"]) if (f[k]) p.set(k, f[k]);
  if (f.new_only) p.set("since", state.prevVisit);
  if (f.hide_tracked) p.set("hide_tracked", "true");
  return `/api/listings?${p}`;
}

function trackButton(l) {
  const tracked = state.tracked.get(l.id);
  return tracked
    ? `<button class="btn btn-quiet track-btn tracked" data-open="${esc(l.id)}" title="Edit in tracker">${esc(tracked.status)}</button>`
    : `<button class="btn btn-quiet track-btn" data-track="${esc(l.id)}">
         <svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>Track</button>`;
}

// Where a listing came from. Zapply's reuse terms ask for credit and a link to their repository.
const SOURCE_LABELS = {
  negarprh: ["Canadian Tech Internships", "https://github.com/negarprh/Canadian-Tech-Internships-2027"],
  michelleokolie: ["Canada Tech Internships", "https://github.com/michelleokolie/canada-tech-internships-summer-2027"],
  zapply: ["Zapply", "https://github.com/zapplyjobs/Internships-2027"],
};

function sourceTag(l) {
  if (l.source === "board") return '<span class="tag direct" title="Found on the company\'s own job board">Direct</span>';
  const label = SOURCE_LABELS[l.source];
  return label ? `<a class="via" href="${label[1]}" target="_blank" rel="noopener">via ${esc(label[0])}</a>` : "";
}

function listingHTML(l) {
  const isNew = state.prevVisit && l.first_seen > state.prevVisit;
  const locs = l.locations.split(" / ");
  const locText = locs.length > 2 ? `${locs.slice(0, 2).join(" · ")} +${locs.length - 2}` : locs.join(" · ");
  const spons = l.sponsorship && l.sponsorship !== "Other" ? `<span class="tag warn">${esc(l.sponsorship)}</span>` : "";
  return `
    <article class="listing" data-id="${esc(l.id)}">
      <div class="monogram" aria-hidden="true">${esc(monogram(l.company))}</div>
      <div class="l-main">
        <div class="l-company">${esc(l.company)}
          ${isNew ? '<span class="tag new">New</span>' : ""}
          ${sourceTag(l)}
        </div>
        <a class="l-title" href="${esc(l.url)}" target="_blank" rel="noopener">${esc(l.title)}</a>
        <div class="l-meta">
          <span class="loc" title="${esc(locs.join("\n"))}">${esc(locText)}</span>
          ${l.category ? `<span class="tag">${esc(l.category)}</span>` : ""}
          ${l.terms.map(t => `<span class="tag">${esc(t)}</span>`).join("")}
          ${spons}
          <span class="age">${ago(l.date_posted)}</span>
          ${runHooks("listingMeta", l)}
        </div>
      </div>
      <div class="l-actions">
        ${runHooks("listingActions", l)}
        <span class="track-slot">${trackButton(l)}</span>
        <a class="btn btn-quiet" href="${esc(l.url)}" target="_blank" rel="noopener">Apply ↗</a>
      </div>
    </article>`;
}

function groupKey(l) {
  const sort = filters().sort;
  if (sort === "posted") return dayGroup(l.date_posted);
  if (sort === "added") return dayGroup(l.first_seen);
  if (sort === "match") return l.match_score == null ? "Not scored" : l.match_score >= 70 ? "Strong match" : l.match_score >= 45 ? "Possible match" : "Weak match";
  return (l.company[0] || "#").toUpperCase().replace(/[^A-Z]/, "#");
}

function appendListings(items) {
  const root = $("#listings");
  for (const l of items) {
    const key = groupKey(l);
    let group = root.lastElementChild;
    if (state.lastGroup !== key || !group) {
      root.insertAdjacentHTML("beforeend",
        `<section class="group-wrap"><h2 class="group-label">${esc(key)}</h2><div class="group"></div></section>`);
      group = root.lastElementChild;
      state.lastGroup = key;
    }
    $(".group", group).insertAdjacentHTML("beforeend", listingHTML(l));
  }
}

function showSkeleton() {
  const row = `<div class="listing skeleton"><div class="monogram"></div>
    <div class="l-main"><span class="bar" style="width:22%"></span><span class="bar" style="width:58%;margin-top:9px;height:13px"></span><span class="bar" style="width:40%;margin-top:9px"></span></div>
    <div class="l-actions"><span class="bar" style="width:150px;height:30px"></span></div></div>`;
  $("#listings").innerHTML = `<section class="group-wrap"><div class="group">${row.repeat(7)}</div></section>`;
}

const listCache = new Map();
let listToken = 0;
let loadingMore = false;

async function loadListings(reset) {
  const token = ++listToken;
  if (reset) { state.offset = 0; showSkeleton(); }
  let data;
  try {
    data = await api(listingQuery(state.offset));
  } catch {
    if (reset) $("#listings").innerHTML = "";
    return;
  }
  if (token !== listToken) return; // a newer filter change won
  if (reset) { $("#listings").innerHTML = ""; listCache.clear(); state.lastGroup = null; }
  for (const l of data.items) listCache.set(l.id, l);
  appendListings(data.items);
  state.total = data.total;
  state.offset += data.items.length;
  $("#result-count").textContent = `${data.total.toLocaleString()} internship${data.total === 1 ? "" : "s"}`;
  $("#more-btn").hidden = state.offset >= data.total;
  $("#empty").hidden = data.total > 0;
  runHooks("listingsLoaded");
}

async function loadMore() {
  if (loadingMore || state.offset >= state.total) return;
  loadingMore = true;
  try { await loadListings(false); } finally { loadingMore = false; }
}
$("#more-btn").addEventListener("click", loadMore);
new IntersectionObserver(entries => {
  if (entries[0].isIntersecting && !$("#board-view").hidden && state.offset) loadMore();
}, { rootMargin: "600px" }).observe($("#sentinel"));

$("#listings").addEventListener("click", async e => {
  const trackBtn = e.target.closest("[data-track]");
  const openBtn = e.target.closest("[data-open]");
  if (trackBtn) {
    trackBtn.disabled = true;
    try {
      await api(`/api/tracker/${encodeURIComponent(trackBtn.dataset.track)}`, {
        method: "PUT", body: JSON.stringify({ status: "saved", position: Date.now() / 1000 }),
      });
      await loadTracker();
    } finally {
      rerenderTrack(trackBtn.dataset.track);
    }
  } else if (openBtn) {
    openDrawer(openBtn.dataset.open);
  }
});

function rerenderTrack(id) {
  const slot = $(`.listing[data-id="${CSS.escape(id)}"] .track-slot`);
  const l = listCache.get(id);
  if (slot && l) slot.innerHTML = trackButton(l);
}

// ---------- tracker ----------
async function loadTracker() {
  const data = await api("/api/tracker");
  state.statuses = data.statuses;
  state.tracked = new Map(data.items.map(i => [i.id, i]));
  $("#tracker-count").textContent = data.items.length || "";
  const due = data.items.filter(i => {
    const d = deadlineInfo(i.deadline);
    return d && d.days >= 0 && d.days <= 7 && !["offer", "rejected"].includes(i.status);
  }).length;
  $("#stat-due").textContent = due;
  renderBoard();
}

function cardHTML(i) {
  return `
    <article class="card" draggable="true" data-id="${esc(i.id)}" tabindex="0" aria-label="${esc(i.company)}: ${esc(i.title)}">
      <div class="c-company">${esc(i.company)}</div>
      <div class="c-title">${esc(i.title)}</div>
      <div class="c-tags">
        ${deadlineTag(i.deadline)}
        ${i.active ? "" : '<span class="tag danger">Posting closed</span>'}
        ${i.regions.map(r => `<span class="tag">${REGION_LABELS[r] ?? esc(r)}</span>`).join("")}
      </div>
      ${i.notes ? `<div class="c-notes">${esc(i.notes)}</div>` : ""}
    </article>`;
}

function renderBoard() {
  $("#tracker-empty").hidden = state.tracked.size > 0;
  $("#kanban").innerHTML = state.statuses.map(s => {
    const cards = [...state.tracked.values()].filter(i => i.status === s).sort((a, b) => a.position - b.position);
    return `
      <section class="column" data-status="${s}" data-stage="${s}" aria-label="${s}">
        <h2><span class="stage-dot"></span>${s}<span class="num">${cards.length}</span></h2>
        ${cards.map(cardHTML).join("") || '<div class="col-empty">Drop cards here</div>'}
      </section>`;
  }).join("");
}

let dragId = null;
const kanban = $("#kanban");
kanban.addEventListener("dragstart", e => {
  const card = e.target.closest(".card");
  if (!card) return;
  dragId = card.dataset.id;
  card.classList.add("dragging");
  e.dataTransfer.effectAllowed = "move";
  e.dataTransfer.setData("text/plain", dragId);
});
kanban.addEventListener("dragend", () => {
  dragId = null;
  $$(".dragging, .drop", kanban).forEach(el => el.classList.remove("dragging", "drop"));
});
kanban.addEventListener("dragover", e => {
  const col = e.target.closest(".column");
  if (!col || !dragId) return;
  e.preventDefault();
  $$(".drop", kanban).forEach(el => el !== col && el.classList.remove("drop"));
  col.classList.add("drop");
});
kanban.addEventListener("drop", async e => {
  const col = e.target.closest(".column");
  if (!col || !dragId) return;
  e.preventDefault();
  const id = dragId;
  // Position the card between its new neighbours, based on where it was dropped.
  const others = $$(".card", col).filter(c => c.dataset.id !== id);
  const after = others.findIndex(c => e.clientY < c.getBoundingClientRect().top + c.offsetHeight / 2);
  const pos = i => state.tracked.get(others[i].dataset.id).position;
  let position;
  if (!others.length) position = 0;
  else if (after === -1) position = pos(others.length - 1) + 1;
  else if (after === 0) position = pos(0) - 1;
  else position = (pos(after - 1) + pos(after)) / 2;

  const item = state.tracked.get(id);
  const before = { status: item.status, position: item.position };
  Object.assign(item, { status: col.dataset.status, position });
  renderBoard();
  try {
    await api(`/api/tracker/${encodeURIComponent(id)}`, { method: "PUT", body: JSON.stringify({ status: item.status, position }) });
  } catch {
    Object.assign(item, before);
    renderBoard();
  }
  rerenderTrack(id);
});
kanban.addEventListener("click", e => {
  const card = e.target.closest(".card");
  if (card) openDrawer(card.dataset.id);
});
kanban.addEventListener("keydown", e => {
  const card = e.target.closest(".card");
  if (card && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); openDrawer(card.dataset.id); }
});

// ---------- drawer ----------
const drawer = $("#drawer");
const cardForm = $("#card-form");
let drawerId = null;

function openDrawer(id) {
  const i = state.tracked.get(id);
  if (!i) return;
  drawerId = id;
  $("#drawer-company").textContent = i.company;
  $("#drawer-title").textContent = i.title;
  $("#drawer-sub").textContent = `${i.locations}${i.active ? "" : " · posting closed"}`;
  $("#stage-picker").innerHTML = state.statuses.map(s => `
    <label data-stage="${s}"><input type="radio" name="status" value="${s}" ${s === i.status ? "checked" : ""}>
      <span><span class="stage-dot"></span>${s}</span></label>`).join("");
  cardForm.elements.deadline.value = i.deadline ?? "";
  cardForm.elements.notes.value = i.notes ?? "";
  $("#drawer-link").href = i.url;
  const extras = $("#drawer-extras");
  extras.innerHTML = "";
  for (const hook of IB.hooks.drawer) {
    const section = document.createElement("section");
    section.className = "drawer-section";
    extras.append(section);
    try { hook(i, section); } catch (err) { console.error(err); section.remove(); }
  }
  drawer.showModal();
}

drawer.addEventListener("click", e => { if (e.target === drawer) drawer.close(); }); // backdrop click

cardForm.addEventListener("submit", async e => {
  if (e.submitter?.value !== "save" || !drawerId) return;
  const body = {
    status: cardForm.elements.status.value,
    deadline: cardForm.elements.deadline.value,
    notes: cardForm.elements.notes.value,
  };
  const id = drawerId;
  await api(`/api/tracker/${encodeURIComponent(id)}`, { method: "PUT", body: JSON.stringify(body) });
  await loadTracker();
  rerenderTrack(id);
});

$("#drawer-remove").addEventListener("click", async () => {
  const id = drawerId;
  drawer.close();
  await api(`/api/tracker/${encodeURIComponent(id)}`, { method: "DELETE" });
  await loadTracker();
  rerenderTrack(id);
});

// ---------- companies ----------
async function loadCompanies() {
  const data = await api("/api/companies");
  state.companies = data.items;
  renderCompanies();
}

function companyRow(c) {
  const checked = c.last_checked ? ago(c.last_checked) : "Not yet";
  const status = c.last_status === "not_found" ? '<span class="status-err">Board not found</span>'
    : c.last_status === "error" ? `<span class="status-err" title="${esc(c.last_error)}">Last check failed</span>` : checked;
  return `
    <tr class="${c.enabled ? "" : "off"}">
      <td class="c-name"><a href="${esc(c.board_url)}" target="_blank" rel="noopener">${esc(c.name)}</a>${c.origin === "manual" ? '<span class="manual">added by you</span>' : ""}</td>
      <td class="platform">${esc(c.platform)}</td>
      <td class="r">${c.listings || "–"}</td>
      <td class="r">${c.jobs_total ?? "–"}</td>
      <td class="muted">${status}</td>
      <td class="r"><label class="switch" title="${c.enabled ? "Stop" : "Start"} checking this board">
        <input type="checkbox" data-company="${esc(c.platform)}/${esc(c.token)}" ${c.enabled ? "checked" : ""} aria-label="Watch ${esc(c.name)}"><span></span></label></td>
    </tr>`;
}

function renderCompanies() {
  const q = $("#company-search").value.trim().toLowerCase();
  const show = $('input[name="company-show"]:checked').value;
  const rows = state.companies.filter(c =>
    (show === "all" || (show === "hiring" ? c.enabled && c.listings > 0 : !c.enabled)) &&
    (!q || c.name.toLowerCase().includes(q) || c.token.includes(q)));
  $("#company-rows").innerHTML = rows.map(companyRow).join("") ||
    `<tr><td colspan="6" class="empty">No companies match.</td></tr>`;
  const enabled = state.companies.filter(c => c.enabled).length;
  $("#company-summary").textContent = `Watching ${enabled.toLocaleString()} of ${state.companies.length.toLocaleString()} boards`;
}

$("#company-search").addEventListener("input", renderCompanies);
$$('input[name="company-show"]').forEach(r => r.addEventListener("change", renderCompanies));

$("#company-rows").addEventListener("change", async e => {
  const input = e.target.closest("[data-company]");
  if (!input) return;
  const [platform, token] = input.dataset.company.split("/");
  try {
    await api(`/api/companies/${platform}/${encodeURIComponent(token)}`, {
      method: "PATCH", body: JSON.stringify({ enabled: input.checked }),
    });
    const c = state.companies.find(c => c.platform === platform && c.token === token);
    c.enabled = input.checked ? 1 : 0;
    if (!input.checked) c.listings = 0;
    input.closest("tr").classList.toggle("off", !input.checked);
    loadMeta();
    loadListings(true);
  } catch {
    input.checked = !input.checked;
  }
});

$("#add-company").addEventListener("submit", async e => {
  e.preventDefault();
  const f = e.target;
  const msg = $("#add-company-msg");
  const url = f.elements.url.value.trim();
  f.classList.remove("invalid");
  msg.className = "form-msg";
  if (!url) {
    f.classList.add("invalid");
    msg.classList.add("error");
    msg.textContent = "Paste a link to the company's Greenhouse, Lever or Ashby job board.";
    f.elements.url.focus();
    return;
  }
  const btn = $("button[type=submit]", f);
  btn.disabled = true;
  btn.textContent = "Checking board…";
  try {
    const c = await api("/api/companies", { method: "POST", quiet: true,
      body: JSON.stringify({ url, name: f.elements.name.value.trim() || null }) });
    msg.classList.add("ok");
    msg.textContent = `Added ${c.name}: ${c.kept} matching internship${c.kept === 1 ? "" : "s"} out of ${c.jobs_total} open jobs.`;
    f.reset();
    await Promise.all([loadCompanies(), loadMeta(), loadListings(true)]);
  } catch (err) {
    f.classList.add("invalid");
    msg.classList.add("error");
    msg.textContent = err.message;
  } finally {
    btn.disabled = false;
    btn.textContent = "Add company";
  }
});

// ---------- profile ----------
const CATEGORY_CHOICES = ["Software", "AI/ML/Data", "Hardware", "Product", "Quant"];
const REGION_CHOICES = [["US", "US"], ["CA", "Canada"], ["REMOTE", "Remote"]];
const prefsForm = $("#prefs-form");

function chips(container, name, choices, selected) {
  container.innerHTML = choices.map(([value, label]) => `
    <label class="chip"><input type="checkbox" name="${name}" value="${esc(value)}" ${selected.includes(value) ? "checked" : ""}>
      <span>${esc(label)}</span></label>`).join("");
}

function profileSummaryHTML(p) {
  const d = p.data;
  const edu = d.education?.[0];
  const skills = [...(d.skills?.languages ?? []), ...(d.skills?.frameworks ?? [])].slice(0, 14);
  return `
    <div class="ps-head"><strong>${esc(d.name || "Unnamed")}</strong><span class="muted">${esc(p.resume_filename ?? "")}</span></div>
    ${d.summary ? `<p class="ps-summary">${esc(d.summary)}</p>` : ""}
    <dl class="ps-facts">
      ${edu ? `<dt>Education</dt><dd>${esc([edu.degree, edu.field].filter(Boolean).join(", "))} · ${esc(edu.school)} ${edu.end ? `· ${esc(edu.end)}` : ""}</dd>` : ""}
      <dt>Experience</dt><dd>${(d.experience ?? []).map(e => esc(`${e.role}, ${e.organization}`)).join(" · ") || "None listed"}</dd>
      <dt>Projects</dt><dd>${(d.projects ?? []).map(x => esc(x.name)).join(" · ") || "None listed"}</dd>
      <dt>Skills</dt><dd class="ps-skills">${skills.map(x => `<span class="tag">${esc(x)}</span>`).join("")}</dd>
    </dl>`;
}

function renderProfile(p) {
  IB.profile = p;
  $("#profile-dot").hidden = p.has_resume;
  renderWho(p);
  const status = $("#resume-status");
  if (p.extract_job) {
    status.className = "form-msg busy";
    status.textContent = "Claude is reading your resume…";
  } else if (p.has_resume && !Object.keys(p.data).length) {
    status.className = "form-msg error";
    status.textContent = "Your resume was uploaded but not read yet. Upload it again to retry.";
  } else if (p.has_resume) {
    status.className = "form-msg ok";
    status.textContent = `Profile updated ${ago(p.updated_at)}.`;
  } else {
    status.className = "form-msg";
    status.textContent = "";
  }
  const hasData = Object.keys(p.data).length > 0;
  $("#profile-summary").hidden = !hasData;
  $("#raw-edit").hidden = !hasData;
  if (hasData) {
    $("#profile-summary").innerHTML = profileSummaryHTML(p);
    if (!$("#raw-edit").open) $("#profile-json").value = JSON.stringify(p.data, null, 2);
  }

  const pr = p.preferences;
  prefsForm.elements.target_roles.value = pr.target_roles.join(", ");
  for (const k of ["degree_level", "graduation", "work_authorization", "school", "notes"]) prefsForm.elements[k].value = pr[k] ?? "";
  prefsForm.elements.linkedin_premium.checked = !!pr.linkedin_premium;
  chips($("#pref-categories"), "categories", CATEGORY_CHOICES.map(c => [c, c]), pr.categories);
  chips($("#pref-regions"), "regions", REGION_CHOICES, pr.regions);
  const terms = (state.terms ?? []).slice(0, 8);
  chips($("#pref-terms"), "terms", [...new Set([...pr.terms, ...terms])].map(t => [t, t]), pr.terms);

  const extras = $("#profile-extras");
  extras.innerHTML = "";
  for (const hook of IB.hooks.profile) {
    const panel = document.createElement("section");
    extras.append(panel);
    try { hook(p, panel); } catch (err) { console.error(err); panel.remove(); }
  }
}

async function loadProfile() {
  const p = await api("/api/profile");
  renderProfile(p);
  if (p.extract_job) waitForExtraction(p.extract_job);
  return p;
}

async function waitForExtraction(jobId) {
  const status = $("#resume-status");
  for (;;) {
    await new Promise(r => setTimeout(r, 2000));
    const job = await api(`/api/ai/jobs/${jobId}`);
    if (job.status === "error") { status.className = "form-msg error"; status.textContent = job.error; return; }
    if (job.status === "done") { await loadProfile(); return; }
  }
}

async function uploadResume(file) {
  const status = $("#resume-status");
  status.className = "form-msg busy";
  status.textContent = `Uploading ${file.name}…`;
  const body = new FormData();
  body.append("file", file);
  try {
    const r = await api("/api/profile/resume", { method: "POST", body, quiet: true });
    status.textContent = "Claude is reading your resume… (about 20–40 seconds)";
    await waitForExtraction(r.job_id);
  } catch (err) {
    status.className = "form-msg error";
    status.textContent = err.message;
  }
}

$("#resume-file").addEventListener("change", e => { if (e.target.files[0]) uploadResume(e.target.files[0]); e.target.value = ""; });
const dz = $("#dropzone");
dz.addEventListener("dragover", e => { e.preventDefault(); dz.classList.add("over"); });
dz.addEventListener("dragleave", () => dz.classList.remove("over"));
dz.addEventListener("drop", e => { e.preventDefault(); dz.classList.remove("over"); if (e.dataTransfer.files[0]) uploadResume(e.dataTransfer.files[0]); });

prefsForm.addEventListener("submit", async e => {
  e.preventDefault();
  const f = new FormData(prefsForm);
  const preferences = {
    target_roles: f.get("target_roles").split(",").map(x => x.trim()).filter(Boolean),
    categories: f.getAll("categories"), regions: f.getAll("regions"), terms: f.getAll("terms"),
    degree_level: f.get("degree_level"), graduation: f.get("graduation").trim(),
    work_authorization: f.get("work_authorization").trim(), school: f.get("school").trim(), notes: f.get("notes").trim(),
    linkedin_premium: f.get("linkedin_premium") === "on",
  };
  const msg = $("#prefs-msg");
  try {
    renderProfile({ ...IB.profile, ...(await api("/api/profile", { method: "PUT", body: JSON.stringify({ preferences }) })) });
    msg.className = "form-msg ok"; msg.textContent = "Saved.";
  } catch (err) {
    msg.className = "form-msg error"; msg.textContent = err.message;
  }
  setTimeout(() => { msg.textContent = ""; }, 3000);
});

$("#save-json").addEventListener("click", async () => {
  let data;
  try { data = JSON.parse($("#profile-json").value); } catch { toast("That isn't valid JSON. Check for a missing comma or quote."); return; }
  renderProfile({ ...IB.profile, ...(await api("/api/profile", { method: "PUT", body: JSON.stringify({ data }) })) });
  toast("Profile saved.");
});

// ---------- refresh ----------
$("#refresh-btn").addEventListener("click", async () => {
  const btn = $("#refresh-btn"), label = $("span", btn), result = $("#refresh-result");
  btn.disabled = true;
  btn.classList.add("spinning");
  label.textContent = "Refreshing…";
  result.className = "muted";
  result.textContent = "Checking every source, about 30–60 seconds.";
  setSync("busy", "Checking sources…");
  try {
    const r = await api("/api/refresh", { method: "POST" });
    if (r.status === "ok") {
      result.className = r.new ? "ok" : "muted";
      result.textContent = r.new ? `${r.new.toLocaleString()} new internship${r.new === 1 ? "" : "s"}` : "No new internships since the last check.";
    } else if (r.status === "already_running") {
      result.textContent = "A refresh is already running; the board updates when it finishes.";
    } else {
      result.textContent = "";
      toast(`Refresh failed: ${r.error}`);
    }
    await Promise.all([loadMeta(), loadListings(true), updateNewCount(), state.companies.length && loadCompanies()]);
  } catch {
    result.textContent = "";
    await loadMeta().catch(() => {});
  } finally {
    btn.classList.remove("spinning");
    btn.disabled = false;
    label.textContent = "Refresh";
    setTimeout(() => { if (!btn.disabled) result.textContent = ""; }, 20000);
  }
});

// ---------- visits ----------
// "New since last visit" means since the end of your previous session. Reloads and coming back
// within SESSION_GAP stay in the same session, so they don't reset what counts as new.
const SESSION_GAP = 30 * 60;

function visitBaseline() {
  const now = Math.floor(Date.now() / 1000);
  const lastActive = load("lastActive", load("lastVisit", null));
  let baseline = load("baseline", null);
  if (lastActive === null) baseline = now; // first visit ever: nothing is new yet
  else if (baseline === null || now - lastActive > SESSION_GAP) baseline = lastActive;
  store("baseline", baseline);
  try { localStorage.removeItem("lastVisit"); } catch {}
  markActive();
  return baseline;
}

function markActive() {
  if (document.visibilityState === "visible") store("lastActive", Math.floor(Date.now() / 1000));
}
setInterval(markActive, 60 * 1000);
document.addEventListener("visibilitychange", markActive);

// ---------- start ----------
(async function init() {
  state.prevVisit = visitBaseline();
  restoreFilters();
  const [hashView, hashParams] = viewFromHash();
  showView(hashView || load("view", "board"), hashParams);
  showSkeleton();

  let meta = await loadMeta();
  // On the very first run the server is still importing; wait for it.
  while (!meta.last_refresh && !meta.last_error) {
    await new Promise(r => setTimeout(r, 2000));
    meta = await loadMeta();
  }
  await loadTracker();
  if (VIEWS[currentView] === "tool") renderTool(currentView);
  if (IB.pages[currentView]) IB.pages[currentView]($(`#${VIEWS[currentView]}-view`), viewFromHash()[1]);
  api("/api/profile").then(p => { IB.profile = p; $("#profile-dot").hidden = p.has_resume; renderWho(p); }).catch(() => {});
  filtersChanged();
  updateNewCount();
  setInterval(loadMeta, 60 * 1000);
})();
