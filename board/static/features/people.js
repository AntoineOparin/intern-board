"use strict";
// Find People: pick a tracked job -> recruiters or coffee chats -> people with emails and intro drafts.
// People come from Prospeo (board/contacts.py); drafts from Claude (outreach job in board/people.py).
(() => {
  const { api, esc, toast, ago, runJob } = window.IB;
  const $ = (sel, root = document) => root.querySelector(sel);

  const ICON = {
    search: '<circle cx="11" cy="11" r="6.5"/><path d="m20 20-4.2-4.2"/>',
    pin: '<path d="M12 21s-6.5-5.6-6.5-11a6.5 6.5 0 0 1 13 0c0 5.4-6.5 11-6.5 11z"/><circle cx="12" cy="10" r="2.3"/>',
    people: '<circle cx="9" cy="8.5" r="3.2"/><path d="M3.5 19c.6-3 2.8-4.7 5.5-4.7s4.9 1.7 5.5 4.7M15.5 5.6a3 3 0 0 1 0 5.8M17 14.6c1.8.6 3 2.1 3.5 4.4"/>',
    badge: '<path d="M12 3l2.2 1.6 2.7-.1.8 2.6 2.2 1.6-.9 2.6.9 2.6-2.2 1.6-.8 2.6-2.7-.1L12 21l-2.2-1.6-2.7.1-.8-2.6L4.1 15.3l.9-2.6-.9-2.6 2.2-1.6.8-2.6 2.7.1z"/><path d="m9 12 2 2 4-4"/>',
    coffee: '<path d="M5 9h11v5a5 5 0 0 1-5 5h-1a5 5 0 0 1-5-5z"/><path d="M16 10.5h1.5a2.5 2.5 0 0 1 0 5H16M8 3.5c0 1 1 1.3 1 2.3M11.5 3.5c0 1 1 1.3 1 2.3"/>',
    mail: '<rect x="3.5" y="5.5" width="17" height="13" rx="2"/><path d="m4 7 8 6 8-6"/>',
    linkedin: '<rect x="3.5" y="3.5" width="17" height="17" rx="3"/><path d="M8 10.5V16M8 7.8v.1M11.5 16v-3.3c0-1.3.9-2.2 2-2.2s2 .9 2 2.2V16M11.5 10.5V16"/>',
    check: '<path d="m5 12.5 4.2 4L19 7"/>',
    copy: '<rect x="8.5" y="8.5" width="11" height="11" rx="2"/><path d="M15.5 8.5V6a1.5 1.5 0 0 0-1.5-1.5H6A1.5 1.5 0 0 0 4.5 6v8A1.5 1.5 0 0 0 6 15.5h2.5"/>',
    back: '<path d="M15 6l-6 6 6 6"/>',
    chevron: '<path d="m9 6 6 6-6 6"/>',
  };
  const icon = (name, cls = "icon") => `<svg class="${cls}" viewBox="0 0 24 24" aria-hidden="true">${ICON[name]}</svg>`;
  const initials = name => IB.monogram(name || "?");
  const KIND_TEXT = {
    recruiters: { noun: n => (n === 1 ? "recruiter" : "recruiters") },
    team: { noun: n => (n === 1 ? "person for a coffee chat" : "people for coffee chats") },
  };
  // LinkedIn allows 200-character invitation notes on free accounts and 300 on Premium (Profile setting).
  const noteLimit = () => (IB.profile?.preferences?.linkedin_premium ? 300 : 200);

  // pending: "person|channel" -> Promise of a draft being written, so re-renders don't start another.
  const st = { el: null, session: null, kind: null, open: null, drafts: new Map(), pending: new Map(), account: null,
               busy: false, add: false, rechecked: new Set() };
  const shortDate = iso => iso ? new Date(String(iso).slice(0, 10) + "T12:00:00").toLocaleDateString(undefined, { month: "short", day: "numeric" }) : "";
  const dayDate = ts => ts ? new Date(ts * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" }) : "";
  const noCredits = () => !!st.account?.empty;
  const renewText = () => st.account?.renews ? `renews ${shortDate(st.account.renews)}` : "renews monthly";
  function creditsText() {
    const a = st.account;
    if (!a?.configured || a.error) return "";
    if (a.empty) return `No credits left · ${renewText()}`;
    return `${a.remaining} credits left${a.low ? " · running low" : ""}`;
  }
  const creditsClass = () => noCredits() ? "empty" : st.account?.low ? "low" : "";

  function logoHTML(listing, logo, size = "") {
    return logo
      ? `<img class="fp-logo ${size}" src="${esc(logo)}" alt="" loading="lazy" onerror="this.replaceWith(Object.assign(document.createElement('span'),{className:'fp-logo fp-mono ${size}',textContent:'${esc(initials(listing.company))}'}))">`
      : `<span class="fp-logo fp-mono ${size}" aria-hidden="true">${esc(initials(listing.company))}</span>`;
  }

  async function loadCredits() {
    const wasEmpty = noCredits();
    try { st.account = await api("/api/integrations/prospeo", { quiet: true }); }
    catch { st.account = null; }
    const pill = $(".fp-credits", st.el);
    if (pill) { pill.textContent = creditsText(); pill.className = `fp-credits ${creditsClass()}`; }
    // Running out (or a renewal) changes which buttons work: redraw the current step.
    if (wasEmpty !== noCredits() && st.session) openListing(st.session.listing.id, st.kind, st.add);
  }

  function header(listing, logo) {
    return `
      <header class="fp-head">
        <h1>Find People</h1>
        <div class="fp-head-right">
          <span class="fp-credits ${creditsClass()}">${creditsText()}</span>
          ${listing ? `<span class="fp-job">${logoHTML(listing, logo, "sm")}<span>${esc(listing.title)}</span></span>` : ""}
        </div>
      </header>`;
  }

  // ---------- step 1: pick a tracked job ----------
  async function renderPick() {
    const items = [...IB.state.tracked.values()].sort((a, b) => a.company.localeCompare(b.company));
    st.el.innerHTML = header(null) + `
      <section class="fp-panel">
        <h2>Who do you want to reach?</h2>
        <p class="muted">Pick a company from your tracker.</p>
        ${items.length ? `
          <label class="fp-search">${icon("search")}
            <input type="search" placeholder="Search your tracked jobs" aria-label="Search your tracked jobs"></label>
          <ul class="fp-jobs" role="list"></ul>` : `
          <div class="fp-empty">
            <p>Your tracker is empty. Press <strong>Track</strong> on a listing, then come back to find people there.</p>
            <a class="btn btn-primary" href="#board">Browse internships</a>
          </div>`}
      </section>`;
    if (!items.length) return;
    let logos = {};
    const list = $(".fp-jobs", st.el);
    const draw = q => {
      const shown = items.filter(i => !q || `${i.title} ${i.company} ${i.locations}`.toLowerCase().includes(q));
      list.innerHTML = shown.map(i => `
        <li><a class="fp-job-row" href="#people?listing=${encodeURIComponent(i.id)}" data-id="${esc(i.id)}">
          ${logoHTML(i, logos[i.id])}
          <span class="fp-job-text"><strong>${esc(i.title)}</strong>
            <span class="muted">${esc(i.company)} <span class="fp-loc">${icon("pin")}${esc(i.locations.split(" / ")[0])}</span></span></span>
          <span class="fp-job-icon">${icon("people")}</span>
        </a></li>`).join("") || `<li class="muted fp-none">No tracked jobs match.</li>`;
    };
    draw("");
    $(".fp-search input", st.el).addEventListener("input", e => draw(e.target.value.trim().toLowerCase()));
    list.addEventListener("click", e => {
      const row = e.target.closest(".fp-job-row");
      if (row) row.classList.add("loading");
    });
    try { logos = await api("/api/people/logos", { quiet: true }); draw($(".fp-search input", st.el).value.trim().toLowerCase()); } catch {}
  }

  // ---------- step 2: recruiters or coffee chats ----------
  function renderChoose() {
    const s = st.session, l = s.listing;
    const card = (kind, iconName, title, text) => {
      const done = s.searches[kind], saved = s.contacts[kind].length;
      const foot = done ? `${saved} saved · searched ${ago(done.searched_at)}${done.stale ? " · may be out of date" : ""}`
        : saved ? `${saved} added by you`
        : noCredits() ? `No credits left · ${renewText()}` : "Uses 1 Prospeo credit";
      const usable = saved || done || (s.configured && !noCredits());
      return `
        <div class="fp-choice-wrap">
          <button type="button" class="fp-choice" data-kind="${kind}" ${usable ? "" : "disabled"}>
            <span class="fp-choice-icon">${icon(iconName)}</span>
            <strong>${title}</strong>
            <span class="fp-choice-text">${esc(text)}</span>
            <span class="fp-choice-foot ${done?.stale || (!usable && noCredits()) ? "warn" : "muted"}">${foot}</span>
          </button>
          <a class="link fp-add-link" href="#people?listing=${encodeURIComponent(l.id)}&kind=${kind}&add=1">or add someone yourself</a>
        </div>`;
    };
    st.el.innerHTML = header(l, s.site?.logo_url) + `
      <a class="fp-back link" href="#people">${icon("back")}All tracked jobs</a>
      <section class="fp-center">
        <h2>Who are you looking for at ${esc(s.company)}?</h2>
        <p class="muted">Pick one before each search.</p>
        ${s.configured ? "" : `<p class="form-msg error">Add your Prospeo API key under <a class="link" href="#profile">My profile → Integrations</a> to search.</p>`}
        ${s.configured && noCredits() ? `<p class="fp-out">You're out of Prospeo credits until ${esc(shortDate(st.account.renews))}. People you've already found still work. Use the free searches below, then add who you find.</p>` : ""}
        <div class="fp-choices">
          ${card("recruiters", "badge", "Recruiters", "University and technical recruiters who hire interns.")}
          ${card("team", "coffee", "Coffee chats", `${s.team_label} on the team you're applying to.`)}
        </div>
        <p class="fp-site muted">${siteLine(s)}</p>
        <p class="form-msg" role="status" id="fp-choose-msg"></p>
      </section>
      ${!s.configured || noCredits() ? freeLinksHTML(s, ["recruiters", "team", "google"]) : ""}`;
    bindSite();
    st.el.querySelectorAll(".fp-choice").forEach(b => b.addEventListener("click", () => choose(b.dataset.kind, b)));
  }

  function siteLine(s) {
    const site = s.site;
    return `${site ? `Searching people at <strong>${esc(site.domain)}</strong>${site.prospeo_name ? ` (${esc(site.prospeo_name)})` : ""}.`
                   : "The company's website is looked up on the first search."}
      <button type="button" class="link fp-change">${site ? "Wrong company? Change website" : "Set website"}</button>
      <span class="fp-site-form" hidden><input type="text" placeholder="stripe.com" aria-label="Company website">
        <button type="button" class="btn btn-quiet fp-site-save">Save</button></span>`;
  }

  function bindSite() {
    const change = $(".fp-change", st.el);
    if (!change) return;
    change.addEventListener("click", () => {
      const f = $(".fp-site-form", st.el);
      f.hidden = false;
      $("input", f).value = st.session.site?.domain || "";
      $("input", f).focus();
    });
    $(".fp-site-save", st.el).addEventListener("click", async () => {
      const website = $(".fp-site-form input", st.el).value.trim();
      try {
        await api("/api/people/site", { method: "PUT", body: JSON.stringify({ listing_id: st.session.listing.id, website }) });
        await openListing(st.session.listing.id, st.kind);
        toast("Website saved. Run the search again to find people there.");
      } catch {}
    });
  }

  async function choose(kind, button) {
    const s = st.session;
    if (s.searches[kind] || s.contacts[kind].length) {
      location.hash = `#people?listing=${encodeURIComponent(s.listing.id)}&kind=${kind}`;
      return;
    }
    await search(kind, button);
  }

  function freeLinksHTML(s, groups) {
    const shown = s.links.groups.filter(g => groups.includes(g.id) && g.items.length);
    return `
      <section class="fp-panel fp-free">
        <h2>Free searches</h2>
        <p class="muted">These open LinkedIn or Google in a new tab and cost nothing. Add the people you find with “add someone yourself”.</p>
        ${shown.map(g => `<h3>${esc(g.title)}</h3><ul class="fp-links">${g.items.map(i =>
          `<li><a class="link" href="${esc(i.url)}" target="_blank" rel="noopener">${esc(i.label)} ↗</a> <span class="muted">${esc(i.hint)}</span></li>`).join("")}</ul>`).join("")}
      </section>`;
  }

  async function search(kind, button) {
    if (st.busy) return;
    st.busy = true;
    const msg = $("#fp-choose-msg", st.el) || $("#fp-results-msg", st.el);
    button?.classList.add("loading");
    if (button) button.disabled = true;
    try {
      await runJob("people_search", { listing_id: st.session.listing.id, kind }, {
        onProgress: sec => { if (msg) { msg.className = "form-msg busy"; msg.textContent = `Searching Prospeo… ${sec}s`; } },
      });
      st.busy = false;
      const target = `#people?listing=${encodeURIComponent(st.session.listing.id)}&kind=${kind}`;
      if (location.hash === target) await openListing(st.session.listing.id, kind);
      else location.hash = target;
    } catch (err) {
      if (msg) { msg.className = "form-msg error"; msg.textContent = err.message; }
    } finally {
      st.busy = false;
      button?.classList.remove("loading");
      if (button) button.disabled = false;
      loadCredits();
    }
  }

  // ---------- step 3: people ----------
  function emailChip(c) {
    if (c.email && c.email_status === "NO_LONGER_VERIFIED") {
      return `<a class="fp-chip fp-chip-warn" href="mailto:${esc(c.email)}" title="Prospeo no longer verifies this address">
        ${icon("mail")}<span>${esc(c.email)}</span><span class="fp-cost">not verified now</span></a>`;
    }
    if (c.email) {
      const verified = c.email_status === "VERIFIED";
      return `<a class="fp-chip" href="mailto:${esc(c.email)}">${icon("mail")}<span>${esc(c.email)}</span>
        ${verified ? `<span class="fp-ok" title="Verified by Prospeo${c.email_found_at ? ` on ${dayDate(c.email_found_at)}` : ""}">${icon("check")}</span>` : ""}</a>`;
    }
    if (c.email_status === "VERIFIED" && noCredits()) {
      return `<span class="fp-chip fp-chip-off" title="A verified email exists; it costs 1 credit to reveal">${icon("mail")}
        <span class="muted">Email available · no credits left</span></span>`;
    }
    if (c.email_status === "VERIFIED") {
      return `<button type="button" class="fp-chip fp-reveal" data-person="${esc(c.person_id)}">${icon("mail")}
        <span>Find email</span><span class="muted fp-cost">1 credit</span></button>`;
    }
    return `<span class="fp-chip fp-chip-off">${icon("mail")}<span class="muted">${c.source === "manual" ? "No email added" : "No verified email"}</span></span>`;
  }

  function freshnessHTML(c) {
    if (c.source === "manual") {
      return `<span class="muted">Added by you ${dayDate(c.found_at)}.</span>
        <button type="button" class="link fp-remove" data-person="${esc(c.person_id)}">Remove</button>`;
    }
    const parts = [`Found ${dayDate(c.found_at)}`];
    if (c.email_found_at) parts.push(`email checked ${dayDate(c.email_found_at)}`);
    const canRecheck = c.email && (c.recheck_free || !noCredits());
    return `<span class="muted">${parts.join(" · ")}.</span>
      ${canRecheck ? `<button type="button" class="link fp-recheck" data-person="${esc(c.person_id)}"
        title="Checks they're still at the company and the email still works">Re-check${c.recheck_free ? " (free)" : " · 1 credit"}</button>` : ""}`;
  }

  function linkedinChip(c) {
    if (!c.linkedin_url) return `<span class="fp-chip fp-chip-off">${icon("linkedin")}<span class="muted">No LinkedIn profile</span></span>`;
    const short = c.linkedin_url.replace(/^https?:\/\/(www\.)?/, "").replace(/\/$/, "");
    return `<a class="fp-chip" href="${esc(c.linkedin_url)}" target="_blank" rel="noopener">${icon("linkedin")}
      <span>${esc(decodeURIComponent(short))}</span><span class="muted">↗</span></a>`;
  }

  function personHTML(c) {
    const open = st.open === c.person_id;
    return `
      <article class="fp-person ${open ? "open" : ""}" data-person="${esc(c.person_id)}">
        <button type="button" class="fp-person-head" aria-expanded="${open}">
          <span class="fp-avatar">${esc(initials(c.full_name))}</span>
          <span class="fp-person-text"><strong>${esc(c.full_name)}
              ${c.moved_to ? `<span class="tag danger">Now at ${esc(c.moved_to)}</span>` : ""}
              ${c.source === "manual" ? `<span class="tag">Added by you</span>` : ""}
              ${c.new_in_role ? `<span class="tag" title="Prospeo saw a job change in the 3 months before this search">New in role</span>` : ""}</strong>
            <span class="muted">${esc([c.title, c.location].filter(Boolean).join(" · "))}</span></span>
          ${icon("chevron", "icon fp-caret")}
        </button>
        ${open ? `
          <div class="fp-person-body">
            <div class="fp-chips">${emailChip(c)}${linkedinChip(c)}</div>
            <div class="fp-fresh">${freshnessHTML(c)}</div>
            <div class="fp-draft" data-person="${esc(c.person_id)}">
              <div class="fp-draft-head">
                <span class="fp-draft-label">Intro draft</span>
                <div class="fp-channel" role="radiogroup" aria-label="Message type">
                  <label><input type="radio" name="fp-ch-${esc(c.person_id)}" value="linkedin_note"><span>LinkedIn note</span></label>
                  <label><input type="radio" name="fp-ch-${esc(c.person_id)}" value="email"><span>Email</span></label>
                </div>
                <button type="button" class="btn btn-quiet fp-copy">${icon("copy")}Copy</button>
              </div>
              <div class="fp-draft-empty" hidden>
                <p class="muted"></p>
                <button type="button" class="btn btn-primary fp-write"></button>
              </div>
              <input class="fp-subject" type="text" aria-label="Email subject" hidden>
              <textarea class="fp-body" rows="5" aria-label="Intro draft"></textarea>
              <p class="fp-angle muted" hidden></p>
              <ul class="fp-checks" hidden></ul>
              <div class="fp-draft-foot"><span class="fp-count muted"></span>
                <span class="form-msg fp-draft-msg" role="status"></span>
                <button type="button" class="link fp-rewrite">Rewrite</button></div>
            </div>
          </div>` : ""}
      </article>`;
  }

  async function renderResults(kind) {
    const s = st.session, people = s.contacts[kind] || [], search = s.searches[kind];
    const countryNote = search && !search.country_filtered && people.some(p => p.source === "prospeo")
      ? `<p class="muted fp-note">No one matched in this job's country, so these are from other locations.</p>` : "";
    const staleNote = search?.stale
      ? `<p class="fp-stale">This list is from ${esc(dayDate(search.searched_at))}. People change roles and companies, so search again for a fresh one before reaching out.</p>` : "";
    const againLabel = noCredits() ? "No credits left" : "Search again · 1 credit";
    st.el.innerHTML = header(s.listing, s.site?.logo_url) + `
      <div class="fp-results-head">
        <a class="fp-back link" href="#people?listing=${encodeURIComponent(s.listing.id)}">${icon("back")}Back</a>
        <p class="fp-count-line">${people.length} ${KIND_TEXT[kind].noun(people.length)} at ${esc(s.company)}</p>
        <button type="button" class="btn btn-quiet fp-again" title="Run the search again on Prospeo"
          ${noCredits() || !s.configured ? "disabled" : ""}>${search ? againLabel : noCredits() ? againLabel : "Search Prospeo · 1 credit"}</button>
      </div>
      <p class="form-msg" role="status" id="fp-results-msg"></p>
      ${staleNote}${countryNote}
      ${people.length ? `<div class="fp-people">${people.map(personHTML).join("")}</div>` : search ? noOneHTML(s) : ""}
      ${addFormHTML(kind)}
      ${!people.length && !search ? freeLinksHTML(s, [kind === "recruiters" ? "recruiters" : "team", "google", "alumni"]) : ""}`;
    $(".fp-again", st.el).addEventListener("click", e => search(kind, e.currentTarget));
    bindAddForm(kind);
    if (!people.length) { bindSite(); return; }

    const listEl = $(".fp-people", st.el);
    listEl.addEventListener("click", e => {
      const head = e.target.closest(".fp-person-head");
      if (head) {
        const id = head.closest(".fp-person").dataset.person;
        st.open = st.open === id ? null : id;
        renderResults(kind);
        return;
      }
      const reveal = e.target.closest(".fp-reveal");
      if (reveal) revealEmail(kind, reveal.dataset.person, reveal);
      const recheckBtn = e.target.closest(".fp-recheck");
      if (recheckBtn) recheck(kind, recheckBtn.dataset.person, recheckBtn);
      const remove = e.target.closest(".fp-remove");
      if (remove) removePerson(kind, remove.dataset.person);
    });
    const open = people.find(p => p.person_id === st.open);
    if (open) {
      mountDraft(kind, open);
      // Old email and still inside Prospeo's free window: re-check quietly, once per visit.
      if (open.email_stale && open.recheck_free && !st.rechecked.has(open.person_id)) {
        st.rechecked.add(open.person_id);
        recheck(kind, open.person_id, null, { quiet: true });
      }
    }
  }

  function addFormHTML(kind) {
    return `
      <details class="fp-add" ${st.add ? "open" : ""}>
        <summary>${icon("people")}Add a person yourself</summary>
        <form class="fp-add-form" autocomplete="off" novalidate>
          <label class="field"><span>Name</span><input name="full_name" required maxlength="100"></label>
          <label class="field"><span>Title <em>(optional)</em></span><input name="title" maxlength="150"
            placeholder="${kind === "recruiters" ? "University Recruiter" : "Software Engineer"}"></label>
          <label class="field"><span>LinkedIn <em>(optional)</em></span><input name="linkedin_url" placeholder="linkedin.com/in/their-name"></label>
          <label class="field"><span>Email <em>(optional)</em></span><input name="email" type="email"></label>
          <div class="fp-add-actions"><button class="btn btn-primary">Add</button>
            <span class="form-msg" role="status"></span></div>
        </form>
      </details>`;
  }

  function bindAddForm(kind) {
    const form = $(".fp-add-form", st.el);
    if (!form) return;
    form.addEventListener("submit", async e => {
      e.preventDefault();
      const f = new FormData(form), msg = $(".form-msg", form);
      if (!f.get("full_name").trim()) { msg.className = "form-msg error"; msg.textContent = "Enter their name."; return; }
      try {
        const c = await api("/api/people/contacts", { method: "POST", quiet: true, body: JSON.stringify({
          listing_id: st.session.listing.id, kind, full_name: f.get("full_name"), title: f.get("title"),
          linkedin_url: f.get("linkedin_url"), email: f.get("email") }) });
        st.session.contacts[kind].push(c);
        st.open = c.person_id;
        st.add = false;
        renderResults(kind);
      } catch (err) { msg.className = "form-msg error"; msg.textContent = err.message; }
    });
  }

  async function removePerson(kind, personId) {
    try {
      await api(`/api/people/contacts/one?listing_id=${encodeURIComponent(st.session.listing.id)}&kind=${kind}&person_id=${encodeURIComponent(personId)}`, { method: "DELETE" });
      st.session.contacts[kind] = st.session.contacts[kind].filter(c => c.person_id !== personId);
      renderResults(kind);
    } catch {}
  }

  async function recheck(kind, personId, button, { quiet = false } = {}) {
    if (button) { button.disabled = true; button.textContent = "Checking…"; }
    try {
      const c = await api("/api/people/recheck", { method: "POST", quiet: true,
        body: JSON.stringify({ listing_id: st.session.listing.id, kind, person_id: personId }) });
      const list = st.session.contacts[kind];
      list[list.findIndex(x => x.person_id === personId)] = c;
      if (c.moved_to) toast(`${c.full_name} now appears to work at ${c.moved_to}.`);
      else if (c.email_status === "NO_LONGER_VERIFIED") toast(`Prospeo no longer verifies ${c.full_name}'s email. They may have left.`);
      else if (!quiet) toast(`Still at ${st.session.company}; email still verified.`);
      renderResults(kind);
    } catch (err) {
      if (!quiet) toast(err.message);
      if (button) { button.disabled = false; button.textContent = "Re-check"; }
    }
    loadCredits();
  }

  function noOneHTML(s) {
    const links = s.links.groups.filter(g => g.id === (st.kind === "recruiters" ? "recruiters" : "team") || g.id === "google");
    return `
      <section class="fp-panel fp-noone">
        <h2>No one found</h2>
        <p class="muted">Prospeo has no matching people at ${esc(s.site?.domain || s.company)}. Check the website is right, or search LinkedIn yourself.</p>
        <p class="fp-site muted">${siteLine(s)}</p>
        ${links.map(g => `<h3>${esc(g.title)}</h3><ul class="fp-links">${g.items.map(i =>
          `<li><a class="link" href="${esc(i.url)}" target="_blank" rel="noopener">${esc(i.label)} ↗</a> <span class="muted">${esc(i.hint)}</span></li>`).join("")}</ul>`).join("")}
      </section>`;
  }

  async function revealEmail(kind, personId, button) {
    button.disabled = true;
    $("span", button).textContent = "Finding email…";
    try {
      const c = await api("/api/people/email", { method: "POST", quiet: true,
        body: JSON.stringify({ listing_id: st.session.listing.id, kind, person_id: personId }) });
      const list = st.session.contacts[kind];
      list[list.findIndex(x => x.person_id === personId)] = c;
      if (!c.email) toast("Prospeo has no verified email for this person. No credit was used.");
      renderResults(kind);
    } catch (err) {
      toast(err.message);  // e.g. out of credits, with the renewal date
      button.disabled = false; $("span", button).textContent = "Find email";
    }
    loadCredits();
  }

  // ---------- intro drafts ----------
  async function loadDrafts() {
    st.drafts = new Map();
    try {
      const { items } = await api(`/api/people/drafts?listing_id=${encodeURIComponent(st.session.listing.id)}`, { quiet: true });
      for (const d of items.sort((a, b) => a.created_at - b.created_at)) {
        if (d.person_id) st.drafts.set(`${d.person_id}|${d.channel}`, d);
      }
    } catch {}
  }

  function mountDraft(kind, c) {
    const box = $(`.fp-draft[data-person="${CSS.escape(c.person_id)}"]`, st.el);
    if (!box) return;
    const channel = st.channel?.[c.person_id] || (c.email ? "email" : "linkedin_note");
    box.querySelector(`input[value="${channel}"]`).checked = true;
    const body = $(".fp-body", box), subject = $(".fp-subject", box), count = $(".fp-count", box), msg = $(".fp-draft-msg", box);

    const empty = $(".fp-draft-empty", box), copy = $(".fp-copy", box), rewrite = $(".fp-rewrite", box);
    const label = channel === "email" ? "email" : "LinkedIn note";
    // Nothing is written until you ask: each draft is a Claude request on your plan.
    const show = (d, writing = false) => {
      const hasDraft = !!d || writing;
      empty.hidden = hasDraft;
      body.hidden = !hasDraft;
      subject.hidden = !hasDraft || channel !== "email";
      copy.hidden = !d;
      rewrite.hidden = !d;
      count.hidden = !hasDraft;
      if (!hasDraft) {
        $("p", empty).textContent = `Claude can write a ${label} to ${c.full_name.split(" ")[0]} from your profile. It takes about 20–40 seconds and uses your Claude plan.`;
        $(".fp-write", empty).textContent = `Write ${label}`;
      }
      subject.value = d?.subject || "";
      body.value = d?.body || "";
      body.placeholder = writing ? `Writing a ${label} with Claude…` : "";
      const angle = $(".fp-angle", box), checks = $(".fp-checks", box);
      angle.hidden = !d?.angle;
      angle.textContent = d?.angle ? `Why this message: ${d.angle}` : "";
      checks.hidden = !d?.checks?.length;
      checks.innerHTML = (d?.checks || []).map(c => `<li>${esc(c)}</li>`).join("");
      updateCount();
    };
    const updateCount = () => {
      const n = body.value.length;
      const limit = noteLimit();
      count.textContent = channel === "linkedin_note" ? `${n} / ${limit}` : `${body.value.split(/\s+/).filter(Boolean).length} words`;
      count.classList.toggle("over", channel === "linkedin_note" && n > limit);
    };
    const key = `${c.person_id}|${channel}`;
    const wait = async promise => {
      msg.className = "form-msg busy";
      msg.textContent = "Writing…";
      show(null, true);
      try {
        const d = await promise;
        if (box.isConnected) { msg.className = "form-msg"; msg.textContent = ""; show(d); }
      } catch (err) {
        if (box.isConnected) { show(st.drafts.get(key)); msg.className = "form-msg error"; msg.textContent = err.message; }
      }
    };
    const generate = () => {
      const listingId = st.session.listing.id;
      const previous = st.drafts.get(key);  // "Rewrite" asks for a different angle than this one
      const promise = runJob("outreach", { listing_id: listingId, person_id: c.person_id, channel,
        recipient_type: kind === "recruiters" ? "recruiter" : "engineer", previous_id: previous?.id }, {
        onProgress: sec => { const m = $(`.fp-draft[data-person="${CSS.escape(c.person_id)}"] .fp-draft-msg`, st.el);
                             if (m) m.textContent = `Writing… ${sec}s`; } })
        .then(d => { st.drafts.set(key, d); return d; })
        .finally(() => st.pending.delete(key));
      st.pending.set(key, promise);
      wait(promise);
    };

    const existing = st.drafts.get(key);
    show(existing);
    if (st.pending.has(key)) wait(st.pending.get(key));
    $(".fp-write", box).addEventListener("click", generate);

    box.querySelectorAll(".fp-channel input").forEach(r => r.addEventListener("change", () => {
      st.channel = { ...(st.channel || {}), [c.person_id]: r.value };
      renderResults(kind);
    }));
    $(".fp-rewrite", box).addEventListener("click", generate);
    body.addEventListener("input", updateCount);
    const save = async () => {
      const d = st.drafts.get(`${c.person_id}|${channel}`);
      if (!d || (d.body === body.value && (d.subject || "") === subject.value)) return;
      try {
        await api(`/api/people/drafts/${encodeURIComponent(d.id)}`, { method: "PUT",
          body: JSON.stringify({ body: body.value, subject: subject.value }), quiet: true });
        Object.assign(d, { body: body.value, subject: subject.value });
      } catch (err) { msg.className = "form-msg error"; msg.textContent = err.message; }
    };
    body.addEventListener("blur", save);
    subject.addEventListener("blur", save);
    $(".fp-copy", box).addEventListener("click", async () => {
      const text = channel === "email" && subject.value ? `Subject: ${subject.value}\n\n${body.value}` : body.value;
      try { await navigator.clipboard.writeText(text); }
      catch { body.select(); document.execCommand("copy"); }
      toast("Copied.");
    });
  }

  // ---------- routing ----------
  async function openListing(listingId, kind, add = false) {
    try {
      st.session = await api(`/api/people/session?listing_id=${encodeURIComponent(listingId)}`);
    } catch { location.hash = "#people"; return; }
    st.add = !!add;
    const has = k => k && (st.session.searches[k] || st.session.contacts[k]?.length);
    st.kind = (has(kind) || (add && kind in KIND_TEXT)) ? kind : null;
    if (!st.kind) { renderChoose(); return; }
    if (!st.open || !st.session.contacts[st.kind].some(c => c.person_id === st.open)) {
      st.open = st.session.contacts[st.kind][0]?.person_id ?? null;  // first card opens, like InternDock
    }
    await loadDrafts();
    renderResults(st.kind);
  }

  IB.pages.people = (el, params) => {
    st.el = el;
    loadCredits();  // free; keeps the count and the out-of-credits state current
    const listing = params.get("listing");
    if (!listing) { st.session = null; renderPick(); return; }
    if (!IB.state.tracked.size && !st.session) { el.innerHTML = header(null); return; } // tracker still loading
    openListing(listing, params.get("kind"), params.get("add") === "1");
  };

  // ---------- tracker drawer: a shortcut into the page ----------
  IB.hooks.drawer.push(Object.assign((item, section) => {
    section.innerHTML = `
      <h3>People</h3>
      <p class="muted">Find recruiters and people on the team at ${esc(item.company)}, with emails and intro drafts.</p>
      <a class="btn btn-quiet fp-drawer-link" href="#people?listing=${encodeURIComponent(item.id)}">${icon("people")}Find people at ${esc(item.company)}</a>`;
    $(".fp-drawer-link", section).addEventListener("click", () => document.querySelector("#drawer").close());
  }, { tool: "people" }));

  // ---------- Profile → Integrations ----------
  IB.hooks.profile.push((p, container) => {
    container.className = "panel fp-integrations";
    container.innerHTML = `<h2 class="panel-title">Integrations</h2><p class="muted">Loading…</p>`;
    const draw = s => {
      container.innerHTML = `
        <h2 class="panel-title">Integrations</h2>
        <div class="fp-int-row">
          <div><strong>Prospeo</strong> <span class="muted">· finds people and verified emails for Find People</span>
            <p class="muted fp-int-status">${s.configured
              ? (s.error ? `<span class="form-msg error">${esc(s.error)}</span>`
                 : `Key ${esc(s.masked)} · ${esc(s.plan || "")} plan · <strong>${s.remaining}</strong> credits left, renews ${esc((s.renews || "").slice(0, 10))}`)
              : "Not connected. Create a free account at prospeo.io, copy your API key from its API page, and paste it here."}</p></div>
        </div>
        <form class="fp-key-form" autocomplete="off">
          <input type="password" name="key" placeholder="${s.configured ? "Paste a new key to replace it" : "Prospeo API key"}" aria-label="Prospeo API key">
          <button class="btn btn-quiet">${s.configured ? "Replace key" : "Save key"}</button>
          ${s.configured ? `<button type="button" class="btn btn-danger-quiet fp-key-remove">Remove key</button>` : ""}
        </form>
        <p class="muted fp-int-note">The key is saved in the app's <code>.env</code> file on your Mac and only sent to Prospeo.
          People you find are saved locally. <button type="button" class="link fp-forget">Delete saved contacts</button></p>
        <p class="form-msg fp-int-msg" role="status"></p>`;
      const msg = $(".fp-int-msg", container);
      $(".fp-key-form", container).addEventListener("submit", async e => {
        e.preventDefault();
        const key = e.target.elements.key.value.trim();
        if (!key) return;
        try { draw(await api("/api/integrations/prospeo", { method: "PUT", body: JSON.stringify({ key }), quiet: true })); st.account = null; }
        catch (err) { msg.className = "form-msg error fp-int-msg"; msg.textContent = err.message; }
      });
      $(".fp-key-remove", container)?.addEventListener("click", async () => {
        await api("/api/integrations/prospeo", { method: "DELETE" });
        draw({ configured: false });
      });
      $(".fp-forget", container).addEventListener("click", async () => {
        const r = await api("/api/people/contacts", { method: "DELETE" });
        msg.className = "form-msg ok fp-int-msg"; msg.textContent = `Deleted ${r.deleted} saved contact${r.deleted === 1 ? "" : "s"}.`;
      });
    };
    api("/api/integrations/prospeo", { quiet: true }).then(draw).catch(() => draw({ configured: false }));
  });
})();
