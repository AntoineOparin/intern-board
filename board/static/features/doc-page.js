"use strict";
// Printable, editable view of one tailored resume or cover letter (doc.html?id=…).
// All user and AI text is set with textContent.

(() => {
  const $ = sel => document.querySelector(sel);
  const sheet = $("#sheet");
  const saveBtn = $("#doc-save");
  const docId = new URLSearchParams(location.search).get("id");
  const PAGE_PX = 10 * 96;      // 11in page minus 0.5in margins, in CSS px
  const STEPS = [[11, 1], [10.75, 0.92], [10.5, 0.85], [10.25, 0.78], [10, 0.72]]; // [pt, spacing]
  let doc = null;
  let dirty = false;

  // ---------- helpers ----------
  function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  function msg(id, text, kind = "") {
    const node = $(id);
    node.textContent = text;
    node.className = `form-msg ${kind}`;
  }

  async function api(path, options = {}) {
    let res;
    try {
      res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
    } catch {
      throw new Error("Couldn't reach Intern Board. Is it still running?");
    }
    if (!res.ok) {
      let detail = `Request failed (${res.status})`;
      try { const body = await res.json(); if (typeof body.detail === "string") detail = body.detail; } catch {}
      throw new Error(detail);
    }
    return res.json();
  }

  function markDirty() {
    if (!dirty) { dirty = true; saveBtn.disabled = false; msg("#doc-msg", "Unsaved edits", "busy"); }
  }

  // Make `node` editable in place; `set` stores the edited text back into the content object.
  function editable(node, value, set) {
    node.textContent = value ?? "";
    try { node.contentEditable = "plaintext-only"; } catch { node.contentEditable = "true"; }
    node.spellcheck = true;
    node.addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); node.blur(); } });
    node.addEventListener("input", () => { set(node.textContent.replace(/\s+/g, " ").trim()); markDirty(); });
    return node;
  }

  const edit = (tag, cls, obj, key) => editable(el(tag, cls), obj[key], v => { obj[key] = v; });

  function editableList(tag, cls, list, sep, joiner) {
    return editable(el(tag, cls), list.join(joiner), v => {
      list.splice(0, list.length, ...v.split(sep).map(s => s.trim()).filter(Boolean));
    });
  }

  function row(left, right) {
    const r = el("div", "r-row");
    const l = el("div");
    l.append(...left);
    r.append(l, right);
    return r;
  }

  function bullets(list) {
    const ul = el("ul");
    list.forEach((_, i) => ul.append(editable(el("li"), list[i], v => { list[i] = v; })));
    return ul;
  }

  function section(title, ...children) {
    const s = el("section", "r-section");
    s.append(el("h2", null, title), ...children);
    return s;
  }

  function header(h, cls = "") {
    const box = el("header", cls);
    box.append(edit("h1", "r-name", h, "name"));
    const line = el("p", "r-contact");
    const parts = [
      ...h.contact.map((_, i) => editable(el("span"), h.contact[i], v => { h.contact[i] = v; })),
      ...h.links.map(link => edit("span", "", link, "url")),
    ];
    parts.forEach((p, i) => { if (i) line.append(el("span", "sep", "|")); line.append(p); });
    box.append(line);
    return box;
  }

  // ---------- resume ----------
  function renderResume(c) {
    const page = el("div", "page");
    page.append(header(c.header));

    if (c.education?.length) {
      page.append(section("Education", ...c.education.map((e, idx) => {
        const entry = el("div", "r-entry");
        entry.append(
          row([edit("strong", "", e, "school")], edit("span", "", e, "location")),
          row([edit("em", "", e, "degree")], edit("span", "", e, "dates")),
          ...e.details.map((_, i) => editable(el("p", "r-detail"), e.details[i], v => { e.details[i] = v; })));
        if (idx === 0 && c.awards?.length) {
          const p = el("p", "r-detail");
          p.append(el("b", null, "Awards: "), editableList("span", "", c.awards, ";", "; "));
          entry.append(p);
        }
        return entry;
      })));
    }

    if (c.experience?.length) {
      page.append(section("Experience", ...c.experience.map(x => {
        const entry = el("div", "r-entry");
        entry.append(
          row([edit("strong", "", x, "organization")], edit("span", "", x, "location")),
          row([edit("em", "", x, "role")], edit("span", "", x, "dates")),
          bullets(x.bullets));
        return entry;
      })));
    }

    if (c.projects?.length) {
      page.append(section("Projects", ...c.projects.map(p => {
        const entry = el("div", "r-entry");
        const left = [edit("strong", "", p, "name")];
        if (p.tech) left.push(el("span", null, " | "), edit("span", "r-tech", p, "tech"));
        if (p.link) left.push(el("span", null, " | "), edit("span", "", p, "link"));
        entry.append(row(left, edit("span", "", p, "dates")), bullets(p.bullets));
        return entry;
      })));
    }

    if (c.skills?.length) {
      const box = el("div", "r-skills");
      for (const g of c.skills) {
        const p = el("p");
        const label = edit("b", "", g, "label");
        p.append(label, el("b", null, ": "), editableList("span", "", g.items, ",", ", "));
        box.append(p);
      }
      page.append(section("Skills", box));
    }
    return page;
  }

  // ---------- cover letter ----------
  function renderLetter(c) {
    const page = el("div", "page");
    page.append(header(c.header, "doc-l-head"));
    const meta = el("div", "doc-l-meta");
    meta.append(edit("p", "", c, "date"), edit("p", "", c, "recipient"));
    const body = el("div", "doc-l-body");
    body.append(edit("p", "doc-l-greeting", c, "greeting"));
    c.paragraphs.forEach((_, i) => body.append(editable(el("p"), c.paragraphs[i], v => { c.paragraphs[i] = v; })));
    body.append(edit("p", "doc-l-closing", c, "closing"), edit("p", "doc-l-signature", c, "signature"));
    page.append(meta, body);
    return page;
  }

  // ---------- notes (screen only) ----------
  function list(title, items, cls = "") {
    if (!items?.length) return [];
    const ul = el("ul", cls);
    items.forEach(t => ul.append(el("li", null, t)));
    return [el("h3", null, title), ul];
  }

  function renderNotes() {
    const n = doc.content.notes || {};
    const box = $("#doc-notes");
    box.replaceChildren(el("h2", null, doc.kind === "resume" ? "Tailoring notes" : "Letter notes"));
    if (doc.stale) box.append(el("p", "warn", "Your profile has changed since this was written."));
    if (n.description_used === false) {
      box.append(el("p", "warn", "Written without the job description, from the title and company only."));
    }
    if (doc.kind === "cover_letter") {
      const words = doc.content.paragraphs.join(" ").split(/\s+/).filter(Boolean).length;
      box.append(el("p", null, `${doc.content.tone ? doc.content.tone[0].toUpperCase() + doc.content.tone.slice(1) + " tone · " : ""}${words} words`));
    }
    box.append(
      ...list("Check before sending", n.checks, "warn"),
      ...list("Emphasised", n.emphasized),
      ...list("Draws on", n.drew_on),
      ...list("Gaps in the posting", n.gaps));
    box.hidden = false;
  }

  // ---------- one-page fit ----------
  async function fit() {
    const page = sheet.querySelector(".page");
    if (!page) return;
    try { await document.fonts.ready; } catch {}
    for (const [pt, sp] of STEPS) {
      sheet.style.setProperty("--fs", `${pt}pt`);
      sheet.style.setProperty("--sp", sp);
      if (page.getBoundingClientRect().height <= PAGE_PX) {
        msg("#doc-fit", pt === STEPS[0][0] ? "Fits on one page" : `Fits on one page at ${pt}pt`, "ok");
        return;
      }
    }
    msg("#doc-fit", `Runs past one page even at ${STEPS.at(-1)[0]}pt. Shorten a few lines or remove an entry.`, "error");
  }

  function render() {
    const c = doc.content;
    sheet.replaceChildren(doc.kind === "resume" ? renderResume(c) : renderLetter(c));
    renderNotes();
    fit();
  }

  // Drop lines that were emptied while editing.
  function cleaned(c) {
    const copy = structuredClone(c);
    const trim = arr => arr.filter(s => String(s).trim());
    if (copy.paragraphs) copy.paragraphs = trim(copy.paragraphs);
    for (const x of [...(copy.experience || []), ...(copy.projects || [])]) x.bullets = trim(x.bullets);
    for (const e of copy.education || []) e.details = trim(e.details);
    if (copy.header) copy.header.contact = trim(copy.header.contact);
    return copy;
  }

  // ---------- toolbar ----------
  saveBtn.addEventListener("click", async () => {
    saveBtn.disabled = true;
    msg("#doc-msg", "Saving…", "busy");
    try {
      const saved = await api(`/api/documents/${encodeURIComponent(docId)}`,
        { method: "PUT", body: JSON.stringify({ content: cleaned(doc.content) }) });
      doc = { ...doc, ...saved };
      dirty = false;
      render();
      msg("#doc-msg", "Saved", "ok");
    } catch (err) {
      saveBtn.disabled = false;
      msg("#doc-msg", err.message, "error");
    }
  });

  $("#doc-print").addEventListener("click", () => {
    msg("#doc-msg", "Choose “Save as PDF” as the destination", "");
    window.print();
  });

  $("#doc-back").addEventListener("click", () => {
    if (history.length > 1 && document.referrer.startsWith(location.origin)) history.back();
    else location.href = "/#tracker";
  });

  sheet.addEventListener("focusout", () => { if (dirty) fit(); });
  window.addEventListener("beforeunload", e => { if (dirty) { e.preventDefault(); e.returnValue = ""; } });

  // ---------- load ----------
  async function load() {
    if (!docId) throw new Error("No document id in the link.");
    doc = await api(`/api/documents/${encodeURIComponent(docId)}`);
    const kind = doc.kind === "resume" ? "Resume" : "Cover letter";
    $("#doc-kind").textContent = kind;
    $("#doc-for").textContent = doc.listing ? `${doc.listing.title} · ${doc.listing.company}` : "";
    const name = doc.content.header?.name || "";
    document.title = [name, kind, doc.listing?.company].filter(Boolean).join(" – ");
    render();
  }

  load().catch(err => {
    $("#doc-save").hidden = $("#doc-print").hidden = true;
    $("#doc-hint").hidden = true;
    const box = el("div", "doc-error");
    box.append(el("p", null, err.message), el("p", "muted", "Open documents from a listing in your tracker."));
    sheet.replaceWith(box);
  });
})();
