"use strict";
// Tracker drawer section: tailored resumes and cover letters for the open listing.

(() => {
  const { api, esc, ago, runJob, hooks } = window.IB;
  const enc = encodeURIComponent;
  const KIND_LABEL = { resume: "Resume", cover_letter: "Cover letter" };
  const SOURCE_LABEL = {
    api: "from the company's job board",
    claude: "read from the posting page",
    pasted: "pasted by you",
  };

  // Jobs keep running when the drawer closes; reopening the drawer reattaches to them.
  // listing id -> { label, seconds, view: current section's update fn | null }
  const running = new Map();
  // listing id -> notes from the last document written this session
  const lastNotes = new Map();

  hooks.drawer.push(Object.assign((item, section) => {
    section.classList.add("docs");
    section.innerHTML = `
      <h3>Documents</h3>
      <div class="docs-desc">
        <span class="docs-desc-status muted">Checking for the job description…</span>
        <button type="button" class="link docs-load" hidden>Load description</button>
      </div>
      <details class="docs-paste">
        <summary>Paste job description</summary>
        <label class="field">
          <span>Job description <em>for postings that can't be loaded</em></span>
          <textarea rows="6" maxlength="50000" placeholder="Paste the full posting text here"></textarea>
        </label>
        <div class="docs-row">
          <button type="button" class="btn btn-quiet docs-paste-save">Save description</button>
        </div>
      </details>
      <div class="docs-row docs-actions">
        <button type="button" class="btn btn-primary docs-resume">Tailor resume</button>
        <span class="docs-letter">
          <button type="button" class="btn btn-quiet docs-letter-btn">Write cover letter</button>
          <select class="docs-tone" aria-label="Cover letter tone">
            <option value="formal">Formal</option>
            <option value="conversational">Conversational</option>
            <option value="enthusiastic">Enthusiastic</option>
          </select>
        </span>
      </div>
      <p class="form-msg docs-msg" aria-live="polite"></p>
      <div class="docs-notes" hidden></div>
      <ul class="docs-list"></ul>`;

    const q = sel => section.querySelector(sel);
    const msgEl = q(".docs-msg");
    const buttons = [q(".docs-resume"), q(".docs-letter-btn"), q(".docs-load"), q(".docs-paste-save")];

    function msg(text, kind = "") {
      msgEl.textContent = text;
      msgEl.className = `form-msg docs-msg ${kind}`;
    }
    function busy(on) { for (const b of buttons) b.disabled = on; }

    // ---------- description status ----------
    async function loadStatus() {
      const statusEl = q(".docs-desc-status");
      try {
        const s = await api(`/api/documents/posting/${enc(item.id)}`, { quiet: true });
        if (!section.isConnected) return;
        if (s.available) {
          statusEl.textContent = `Job description ${SOURCE_LABEL[s.source] || "saved"} · ${s.chars.toLocaleString()} characters`;
          q(".docs-load").hidden = true;
        } else {
          statusEl.textContent = "Job description not loaded yet. Writing a document loads it first.";
          q(".docs-load").hidden = false;
        }
      } catch {
        statusEl.textContent = "Couldn't check the job description.";
      }
    }

    // ---------- documents list ----------
    async function loadList() {
      const listEl = q(".docs-list");
      let items;
      try {
        ({ items } = await api(`/api/documents?listing_id=${enc(item.id)}`, { quiet: true }));
      } catch (err) {
        listEl.innerHTML = `<li class="form-msg error">${esc(err.message)}</li>`;
        return;
      }
      if (!section.isConnected) return;
      listEl.innerHTML = items.length ? items.map(d => `
        <li class="docs-item" data-id="${esc(d.id)}">
          <span class="docs-item-main">
            <strong>${esc(KIND_LABEL[d.kind] || d.kind)}</strong>
            <span class="muted">${esc(ago(d.created_at))}${d.updated_at > d.created_at + 5 ? " · edited" : ""}</span>
            ${d.stale ? `<span class="tag warn" title="Your profile changed after this was written">Older profile</span>` : ""}
            ${d.notes?.description_used === false ? `<span class="tag" title="Written from the title and company only">No description</span>` : ""}
          </span>
          <a class="btn btn-quiet docs-open" href="/doc.html?id=${enc(d.id)}" target="_blank" rel="noopener">Open ↗</a>
          <button type="button" class="btn btn-danger-quiet docs-delete">Delete</button>
        </li>`).join("") : `<li class="muted docs-empty">No documents for this listing yet.</li>`;
    }

    section.addEventListener("click", async e => {
      const del = e.target.closest(".docs-delete");
      if (!del) return;
      const li = del.closest(".docs-item");
      const label = li.querySelector("strong").textContent.toLowerCase();
      if (!confirm(`Delete this ${label}? This can't be undone.`)) return;
      del.disabled = true;
      try {
        await api(`/api/documents/${enc(li.dataset.id)}`, { method: "DELETE" });
        loadList();
      } catch {
        del.disabled = false;
      }
    });

    // ---------- notes after writing ----------
    function showNotes(notes) {
      const box = q(".docs-notes");
      if (!notes) { box.hidden = true; return; }
      const block = (title, items, cls = "") => items?.length
        ? `<p class="docs-notes-title">${esc(title)}</p><ul class="${cls}">${items.map(t => `<li>${esc(t)}</li>`).join("")}</ul>` : "";
      box.innerHTML =
        (notes.description_used === false
          ? `<p class="docs-warn">Written without the job description. Paste it above and write again for a closer fit.</p>` : "") +
        block("Check before sending", notes.checks, "docs-warn") +
        block("Emphasised", notes.emphasized) +
        block("Draws on", notes.drew_on) +
        block("Gaps in the posting", notes.gaps);
      box.hidden = !box.innerHTML;
    }

    // ---------- running jobs ----------
    const ctx = {
      msg, busy, loadList, loadStatus, showNotes,
      openPaste: () => { q(".docs-paste").open = true; },
    };

    function attach(entry) {
      entry.view = () => {
        if (!section.isConnected) return;
        busy(true);
        msg(`${entry.label} ${entry.seconds}s`, "busy");
      };
      entry.view();
    }

    async function start(kind, payload, label, onDone) {
      if (running.has(item.id)) return;
      const entry = { label, seconds: 0, view: null, current: ctx };
      running.set(item.id, entry);
      attach(entry);
      let result, error;
      try {
        result = await runJob(kind, payload, {
          onProgress: s => { entry.seconds = s; entry.view?.(); },
        });
      } catch (err) {
        error = err;
      } finally {
        running.delete(item.id);
      }
      // The drawer may have been closed and reopened: report into whichever section is current.
      // (Updating a closed drawer's detached section is harmless, and keeps lastNotes current.)
      const target = entry.current;
      target.busy(false);
      if (error) { target.msg(error.message, "error"); return; }
      await onDone?.(result, target);
    }

    async function writeDoc(kind, payload, label) {
      await start(kind, { listing_id: item.id, ...payload }, label, async (result, t) => {
        t.loadStatus();
        await t.loadList();
        try {
          const doc = await api(`/api/documents/${enc(result.document_id)}`, { quiet: true });
          lastNotes.set(item.id, doc.content.notes);
          t.showNotes(doc.content.notes);
        } catch {}
        t.msg(`${KIND_LABEL[kind]} ready. Open it to review, edit and download.`, "ok");
      });
    }

    q(".docs-resume").addEventListener("click", () => writeDoc("tailor_resume", {}, "Tailoring resume…"));
    q(".docs-letter-btn").addEventListener("click", () =>
      writeDoc("cover_letter", { tone: q(".docs-tone").value }, "Writing cover letter…"));

    q(".docs-load").addEventListener("click", () =>
      start("fetch_description", { listing_id: item.id }, "Loading job description…", (result, t) => {
        t.loadStatus();
        if (result?.text) t.msg("Job description loaded.", "ok");
        else t.msg("Couldn't load the job description. Paste it below instead.", "error");
        if (!result?.text) t.openPaste();
      }));

    q(".docs-paste-save").addEventListener("click", async () => {
      const text = q(".docs-paste textarea").value.trim();
      if (text.length < 50) { msg("Paste the full job description (at least 50 characters).", "error"); return; }
      busy(true);
      try {
        await api(`/api/listings/${enc(item.id)}/description`, { method: "PUT", body: JSON.stringify({ text }), quiet: true });
        q(".docs-paste").open = false;
        q(".docs-paste textarea").value = "";
        msg("Job description saved. New documents will use it.", "ok");
        loadStatus();
      } catch (err) {
        msg(err.message, "error");
      } finally {
        busy(false);
      }
    });

    // Reattach to a job started before the drawer was last closed.
    const pending = running.get(item.id);
    if (pending) {
      pending.current = ctx;
      attach(pending);
    } else if (lastNotes.has(item.id)) {
      showNotes(lastNotes.get(item.id));
    }

    loadStatus();
    loadList();
  }, { tool: "documents" }));
})();
