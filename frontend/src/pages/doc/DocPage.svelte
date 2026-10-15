<script lang="ts">
  // Printable, editable view of one tailored resume or cover letter (doc.html?id=…).
  import { onMount, tick } from "svelte";
  import * as api from "../../lib/api";
  import { editable } from "./editable";
  import type { DocHeader, FullDocument, LetterContent, ResumeContent } from "../../lib/types";

  const docId = new URLSearchParams(location.search).get("id");
  const PAGE_PX = 10 * 96; // 11in page minus 0.5in margins, in CSS px
  const STEPS: [number, number][] = [[11, 1], [10.75, 0.92], [10.5, 0.85], [10.25, 0.78], [10, 0.72]]; // [pt, spacing]

  let doc = $state.raw<FullDocument | null>(null);
  // The content being edited. Not reactive on purpose: edits change it in place, and the page is
  // redrawn (renders++) only after loading or saving.
  // svelte-ignore non_reactive_update
  let content: ResumeContent | LetterContent | null = null;
  let renders = $state(0);
  let error = $state("");
  let dirty = $state(false);
  let saving = $state(false);
  let msg = $state({ text: "", kind: "" });
  let fitMsg = $state({ text: "", kind: "" });
  let sheet: HTMLElement | undefined = $state();

  const resume = () => content as ResumeContent;
  const letter = () => content as LetterContent;
  function markDirty() {
    if (!dirty) { dirty = true; msg = { text: "Unsaved edits", kind: "busy" }; }
  }
  const ed = (value: string | null | undefined, set: (v: string) => void) => ({ value, set, onEdit: markDirty });
  const field = <T extends object>(obj: T, key: keyof T) => ed(obj[key] as string, v => { (obj as Record<keyof T, unknown>)[key] = v; });
  const item = (list: string[], i: number) => ed(list[i], v => { list[i] = v; });
  const joined = (list: string[], sep: string, joiner: string) =>
    ed(list.join(joiner), v => { list.splice(0, list.length, ...v.split(sep).map(s => s.trim()).filter(Boolean)); });

  // ---------- one-page fit ----------
  async function fit() {
    await tick();
    const page = sheet?.querySelector(".page");
    if (!page || !sheet) return;
    try { await document.fonts.ready; } catch { /* fonts are optional */ }
    for (const [pt, sp] of STEPS) {
      sheet.style.setProperty("--fs", `${pt}pt`);
      sheet.style.setProperty("--sp", String(sp));
      if (page.getBoundingClientRect().height <= PAGE_PX) {
        fitMsg = { text: pt === STEPS[0][0] ? "Fits on one page" : `Fits on one page at ${pt}pt`, kind: "ok" };
        return;
      }
    }
    fitMsg = { text: `Runs past one page even at ${STEPS.at(-1)![0]}pt. Shorten a few lines or remove an entry.`, kind: "error" };
  }

  function render(d: FullDocument) {
    doc = d;
    content = structuredClone($state.snapshot(d.content)) as ResumeContent | LetterContent;
    renders++;
    fit();
  }

  // Drop lines that were emptied while editing.
  function cleaned(c: ResumeContent | LetterContent) {
    const copy = structuredClone(c) as ResumeContent & LetterContent;
    const trim = (arr: string[]) => arr.filter(s => String(s).trim());
    if (copy.paragraphs) copy.paragraphs = trim(copy.paragraphs);
    for (const x of [...(copy.experience || []), ...(copy.projects || [])]) x.bullets = trim(x.bullets);
    for (const e of copy.education || []) e.details = trim(e.details);
    if (copy.header) copy.header.contact = trim(copy.header.contact);
    return copy;
  }

  async function save() {
    if (!doc || !content) return;
    saving = true;
    msg = { text: "Saving…", kind: "busy" };
    try {
      const saved = await api.saveDocument(doc.id, cleaned(content));
      dirty = false;
      render({ ...doc, ...saved } as FullDocument);
      msg = { text: "Saved", kind: "ok" };
    } catch (err) {
      msg = { text: (err as Error).message, kind: "error" };
    } finally {
      saving = false;
    }
  }

  function print() {
    msg = { text: "Choose “Save as PDF” as the destination", kind: "" };
    window.print();
  }

  function back() {
    if (history.length > 1 && document.referrer.startsWith(location.origin)) history.back();
    else location.href = "./#tracker";
  }

  const kind = $derived(doc ? (doc.kind === "resume" ? "Resume" : "Cover letter") : "Document");
  const words = $derived(doc?.kind === "cover_letter" ? doc.content.paragraphs.join(" ").split(/\s+/).filter(Boolean).length : 0);
  const notes = $derived(doc?.content.notes ?? {});
  const lists = $derived(([
    ["Check before sending", notes.checks, "warn"], ["Emphasised", notes.emphasized, ""], ["Draws on", notes.drew_on, ""], ["Gaps in the posting", notes.gaps, ""],
  ] as [string, string[] | undefined, string][]).filter(([, items]) => items?.length));

  onMount(() => {
    const beforeunload = (e: BeforeUnloadEvent) => { if (dirty) { e.preventDefault(); e.returnValue = ""; } };
    window.addEventListener("beforeunload", beforeunload);
    (async () => {
      if (!docId) throw new Error("No document id in the link.");
      const d = await api.document(docId, { quiet: true });
      const name = d.content.header?.name || "";
      document.title = [name, d.kind === "resume" ? "Resume" : "Cover letter", d.listing?.company].filter(Boolean).join(" – ");
      render(d);
    })().catch(err => { error = (err as Error).message; });
    return () => window.removeEventListener("beforeunload", beforeunload);
  });
</script>

{#snippet header(h: DocHeader, cls: string)}
  <header class={cls}>
    <!-- svelte-ignore a11y_missing_content (the editable action fills in the name) -->
    <h1 class="r-name" use:editable={field(h, "name")}></h1>
    <p class="r-contact">
      {#each h.contact as _, i (i)}{#if i}<span class="sep">|</span>{/if}<span use:editable={item(h.contact, i)}></span>{/each}{#each h.links as link, i (i)}{#if i || h.contact.length}<span class="sep">|</span>{/if}<span class="" use:editable={field(link, "url")}></span>{/each}
    </p>
  </header>
{/snippet}

<header class="doc-toolbar" aria-label="Document tools">
  <button type="button" id="doc-back" class="btn btn-quiet" onclick={back}>← Back</button>
  <div class="doc-toolbar-title">
    <strong id="doc-kind">{kind}</strong>
    <span id="doc-for" class="muted">{doc?.listing ? `${doc.listing.title} · ${doc.listing.company}` : ""}</span>
  </div>
  <span class="spacer"></span>
  <p id="doc-msg" class="form-msg {msg.kind}" role="status">{msg.text}</p>
  <p id="doc-fit" class="form-msg {fitMsg.kind}" role="status">{fitMsg.text}</p>
  <button type="button" id="doc-save" class="btn btn-quiet" disabled={!dirty || saving} hidden={!!error} onclick={save}>Save edits</button>
  <button type="button" id="doc-print" class="btn btn-primary" hidden={!!error} onclick={print}>Download PDF</button>
</header>
<p id="doc-hint" class="doc-hint muted" hidden={!!error}>Click any text on the page to edit it. To download, choose “Save as PDF” as the destination in the print dialog.</p>

<main class="doc-stage">
  {#if error}
    <div class="doc-error"><p>{error}</p><p class="muted">Open documents from a listing in your tracker.</p></div>
  {:else}
    <article id="sheet" class="sheet" aria-live="polite" bind:this={sheet} onfocusout={() => { if (dirty) fit(); }}>
      {#key renders}
        {#if doc && content}
          {#if doc.kind === "resume"}
            {@const c = resume()}
            <div class="page">
              {@render header(c.header, "")}
              {#if c.education?.length}
                <section class="r-section"><h2>Education</h2>
                  {#each c.education as e, idx (idx)}
                    <div class="r-entry">
                      <div class="r-row"><div><strong use:editable={field(e, "school")}></strong></div><span use:editable={field(e, "location")}></span></div>
                      <div class="r-row"><div><em use:editable={field(e, "degree")}></em></div><span use:editable={field(e, "dates")}></span></div>
                      {#each e.details as _, i (i)}<p class="r-detail" use:editable={item(e.details, i)}></p>{/each}
                      {#if idx === 0 && c.awards?.length}<p class="r-detail"><b>{"Awards: "}</b><span use:editable={joined(c.awards, ";", "; ")}></span></p>{/if}
                    </div>
                  {/each}
                </section>
              {/if}
              {#if c.experience?.length}
                <section class="r-section"><h2>Experience</h2>
                  {#each c.experience as x, idx (idx)}
                    <div class="r-entry">
                      <div class="r-row"><div><strong use:editable={field(x, "organization")}></strong></div><span use:editable={field(x, "location")}></span></div>
                      <div class="r-row"><div><em use:editable={field(x, "role")}></em></div><span use:editable={field(x, "dates")}></span></div>
                      <ul>{#each x.bullets as _, i (i)}<li use:editable={item(x.bullets, i)}></li>{/each}</ul>
                    </div>
                  {/each}
                </section>
              {/if}
              {#if c.projects?.length}
                <section class="r-section"><h2>Projects</h2>
                  {#each c.projects as p, idx (idx)}
                    <div class="r-entry">
                      <div class="r-row"><div><strong use:editable={field(p, "name")}></strong>{#if p.tech}<span>{" | "}</span><span class="r-tech" use:editable={field(p, "tech")}></span>{/if}{#if p.link}<span>{" | "}</span><span use:editable={field(p, "link")}></span>{/if}</div><span use:editable={field(p, "dates")}></span></div>
                      <ul>{#each p.bullets as _, i (i)}<li use:editable={item(p.bullets, i)}></li>{/each}</ul>
                    </div>
                  {/each}
                </section>
              {/if}
              {#if c.skills?.length}
                <section class="r-section"><h2>Skills</h2>
                  <div class="r-skills">
                    {#each c.skills as g, idx (idx)}<p><b use:editable={field(g, "label")}></b><b>{": "}</b><span use:editable={joined(g.items, ",", ", ")}></span></p>{/each}
                  </div>
                </section>
              {/if}
            </div>
          {:else}
            {@const c = letter()}
            <div class="page">
              {@render header(c.header, "doc-l-head")}
              <div class="doc-l-meta"><p use:editable={field(c, "date")}></p><p use:editable={field(c, "recipient")}></p></div>
              <div class="doc-l-body">
                <p class="doc-l-greeting" use:editable={field(c, "greeting")}></p>
                {#each c.paragraphs as _, i (i)}<p use:editable={item(c.paragraphs, i)}></p>{/each}
                <p class="doc-l-closing" use:editable={field(c, "closing")}></p>
                <p class="doc-l-signature" use:editable={field(c, "signature")}></p>
              </div>
            </div>
          {/if}
        {/if}
      {/key}
    </article>
    {#if doc}
      <aside id="doc-notes" class="doc-notes">
        <h2>{doc.kind === "resume" ? "Tailoring notes" : "Letter notes"}</h2>
        {#if doc.stale}<p class="warn">Your profile has changed since this was written.</p>{/if}
        {#if notes.description_used === false}<p class="warn">Written without the job description, from the title and company only.</p>{/if}
        {#if doc.kind === "cover_letter"}
          <p>{doc.content.tone ? `${doc.content.tone[0].toUpperCase()}${doc.content.tone.slice(1)} tone · ` : ""}{words} words</p>
        {/if}
        {#each lists as [title, items, cls] (title)}
          <h3>{title}</h3><ul class={cls}>{#each items ?? [] as t, i (i)}<li>{t}</li>{/each}</ul>
        {/each}
      </aside>
    {/if}
  {/if}
</main>
