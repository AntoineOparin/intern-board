<script lang="ts">
  // Printable, editable view of one tailored resume or cover letter (doc.html?id=…), with a
  // formatting toolbar, undo, and Word and PDF downloads.
  import { onMount, tick } from "svelte";
  import * as api from "../../lib/api";
  import Icon from "../../lib/components/Icon.svelte";
  import { swapOptions } from "../../lib/points";
  import { hex, pageOf, plain, pruned, rangeAt, shiftKeys, SIZE_LIMITS, textOffsets, withoutFormatting } from "../../lib/richtext";
  import { editable } from "./editable";
  import FormatBar, { type FormatActions, type FormatTarget } from "./FormatBar.svelte";
  import type {
    Align, BulletRef, DocFormat, DocHeader, FullDocument, HeadingKey, LetterContent, Line, LineStyle, PageFormat, ProfileData, ResumeContent, ResumeEntry,
  } from "../../lib/types";

  const docId = new URLSearchParams(location.search).get("id");
  const STEPS: [number, number][] = [[11, 1], [10.75, 0.92], [10.5, 0.85], [10.25, 0.78], [10, 0.72]]; // [pt, spacing]
  const HISTORY = 100;
  const HEADINGS: Record<HeadingKey, string> = { education: "Education", experience: "Experience", projects: "Projects", skills: "Skills" };
  const FONT_STACKS: Record<string, string> = {
    "Source Serif 4": "",
    Georgia: "Georgia, serif",
    "Times New Roman": '"Times New Roman", Times, serif',
    Arial: "Arial, Helvetica, sans-serif",
    Helvetica: "Helvetica, Arial, sans-serif",
  };

  let doc = $state.raw<FullDocument | null>(null);
  // The content being edited. Not reactive on purpose: edits change it in place, and the page is
  // redrawn (renders++) only after loading, saving, undo or a swap. Formatting changes bump `formats`.
  // svelte-ignore non_reactive_update
  let content: ResumeContent | LetterContent | null = null;
  let renders = $state(0);
  let formats = $state(0);
  let error = $state("");
  let dirty = $state(false);
  let saving = $state(false);
  let msg = $state({ text: "", kind: "" });
  let fitMsg = $state({ text: "", kind: "" });
  let overflows = $state(false);
  let fitted = { fs: 11, sp: 1 }; // the size the page fits at, for the Word file
  let sheet: HTMLElement | undefined = $state();
  // The current profile, so a resume bullet can be swapped for another phrasing of its point.
  let pool = $state.raw<ProfileData | null>(null);
  let open = $state<string | null>(null); // key of the open swap menu
  let menuEl: HTMLElement | undefined = $state();

  // The formatting toolbar acts on the last field focused, and on the selection saved in it.
  let target = $state<(FormatTarget & { key: string; blockKey: string | null }) | null>(null);
  let marks = $state({ b: false, i: false, u: false });
  let colour = $state("#000000");
  let savedRange: Range | null = null;
  // Undo: snapshots of the content. Typing in a field is one step, from its first keystroke.
  let past = $state.raw<string[]>([]);
  let future = $state.raw<string[]>([]);
  let typing = false;
  let commanding = false;

  const resume = () => content as ResumeContent;
  const letter = () => content as LetterContent;
  function markDirty() {
    if (!dirty) { dirty = true; msg = { text: "Unsaved edits", kind: "busy" }; }
  }
  const ed = (value: Line | null | undefined, set: (v: Line) => void, key: string, rich = true) => ({ value, set, onEdit: markDirty, key, rich });
  const field = <T extends object>(obj: T, k: keyof T, key: string) => ed(obj[k] as Line, v => { (obj as Record<keyof T, unknown>)[k] = v; }, key);
  const item = (list: Line[], i: number, key: string) => ed(list[i], v => { list[i] = v; }, key);
  const joined = (list: string[], sep: string, joiner: string, key: string) =>
    ed(list.join(joiner), v => { list.splice(0, list.length, ...plain(v).split(sep).map(s => s.trim()).filter(Boolean)); }, key, false);
  const heading = (section: HeadingKey) =>
    ed(resume().headings?.[section] ?? HEADINGS[section], v => { (resume().headings ??= {})[section] = v; }, `heading.${section}`);

  // ---------- formatting ----------
  const format = (): DocFormat => (content!.format ??= {});
  const styles = (): Record<string, LineStyle> => (format().styles ??= {});
  const styleOf = (key: string | null | undefined): LineStyle => (key && content?.format?.styles?.[key]) || {};
  function setStyle(key: string, update: Partial<LineStyle>) {
    const next = pruned({ ...styles()[key], ...update });
    if (next) styles()[key] = next;
    else delete styles()[key];
  }
  const fieldEl = () => (target ? sheet?.querySelector<HTMLElement>(`[data-key="${target.key}"]`) : null) ?? null;
  const blockEl = () => (target?.blockKey ? sheet?.querySelector<HTMLElement>(`[data-block="${target.blockKey}"]`) : null) ?? null;

  /** Puts the stored formatting on the page: margins, font, line spacing and each field's style. */
  function applyStyles() {
    if (!sheet || !content) return;
    const st = content.format?.styles ?? {};
    const page = pageOf(content.format);
    const m = page.margins;
    sheet.style.padding = `${m.top}in ${m.right}in ${m.bottom}in ${m.left}in`;
    sheet.style.setProperty("--lh", String(page.lineHeight));
    sheet.style.fontFamily = FONT_STACKS[page.font] ?? "";
    for (const el of sheet.querySelectorAll<HTMLElement>("[data-key]")) {
      const s = st[el.dataset.key!];
      el.style.fontSize = s?.size ? `calc(var(--fs) * ${s.size})` : "";
    }
    for (const el of sheet.querySelectorAll<HTMLElement>("[data-block]")) {
      const s = st[el.dataset.block!];
      el.style.textAlign = s?.align ?? "";
      el.style.paddingTop = s?.before ? `calc(var(--line) * ${s.before})` : "";
      el.style.paddingBottom = s?.after ? `calc(var(--line) * ${s.after})` : "";
    }
    let rule = document.getElementById("doc-page-rule");
    if (!rule) {
      rule = document.createElement("style");
      rule.id = "doc-page-rule";
      document.head.append(rule);
    }
    rule.textContent = `@page { size: letter; margin: ${m.top}in ${m.right}in ${m.bottom}in ${m.left}in; }`;
  }

  // ---------- one-page fit ----------
  async function fit() {
    await tick();
    applyStyles();
    const page = sheet?.querySelector(".page");
    if (!page || !sheet || !content) return;
    try { await document.fonts.ready; } catch { /* fonts are optional */ }
    const p = pageOf(content.format);
    const limit = (11 - p.margins.top - p.margins.bottom) * 96;
    const size = (pt: number, sp: number) => {
      sheet!.style.setProperty("--fs", `${pt}pt`);
      sheet!.style.setProperty("--sp", String(sp));
      fitted = { fs: pt, sp };
    };
    const fits = () => page.getBoundingClientRect().height <= limit;
    if (p.size !== "auto") {
      size(p.size, 1);
      overflows = !fits();
      fitMsg = overflows
        ? { text: `Runs onto a second page at ${p.size}pt. Pick a smaller size, narrower margins, or Auto.`, kind: "error" }
        : { text: "Fits on one page", kind: "ok" };
    } else {
      overflows = true;
      for (const [pt, sp] of STEPS) {
        size(pt, sp);
        if (fits()) {
          overflows = false;
          fitMsg = { text: pt === STEPS[0][0] ? "Fits on one page" : `Fits on one page at ${pt}pt`, kind: "ok" };
          break;
        }
      }
      if (overflows) fitMsg = { text: `Runs past one page even at ${STEPS.at(-1)![0]}pt. Shorten a few lines or remove an entry.`, kind: "error" };
    }
    formats++; // sizes shown in the toolbar depend on the base size
  }

  function render(d: FullDocument) {
    doc = d;
    content = structuredClone($state.snapshot(d.content)) as ResumeContent | LetterContent;
    renders++;
    return fit();
  }

  // Drop lines that were emptied while editing (a bullet's ref and style go with it).
  function cleaned(c: ResumeContent | LetterContent) {
    const copy = structuredClone(c) as ResumeContent & LetterContent;
    let st = { ...(copy.format?.styles ?? {}) };
    const keepOf = (arr: Line[]) => arr.map(s => !!plain(s).trim());
    const trim = (arr: Line[], prefix: string) => {
      const keep = keepOf(arr);
      st = shiftKeys(st, prefix, keep);
      return arr.filter((_, i) => keep[i]);
    };
    if (copy.paragraphs) copy.paragraphs = trim(copy.paragraphs, "paragraphs");
    for (const section of ["experience", "projects"] as const) {
      (copy[section] || []).forEach((x, n) => {
        const keep = keepOf(x.bullets);
        if (x.refs) x.refs = x.refs.filter((_, i) => keep[i]);
        x.bullets = trim(x.bullets, `${section}.${n}.bullets`);
      });
    }
    (copy.education || []).forEach((e, n) => { e.details = trim(e.details, `education.${n}.details`); });
    if (copy.header) copy.header.contact = trim(copy.header.contact, "header.contact");
    if (copy.headings) {
      for (const k of Object.keys(copy.headings) as HeadingKey[]) if (!plain(copy.headings[k]).trim()) delete copy.headings[k];
      if (!Object.keys(copy.headings).length) delete copy.headings;
    }
    if (copy.format) {
      if (Object.keys(st).length) copy.format.styles = st;
      else delete copy.format.styles;
      if (!copy.format.page) delete copy.format.page;
      if (!Object.keys(copy.format).length) delete copy.format;
    }
    return copy;
  }

  // ---------- undo ----------
  const snapshot = () => JSON.stringify(content);
  function remember() {
    if (!content) return;
    past = [...past.slice(1 - HISTORY), snapshot()];
    future = [];
  }
  async function restore(json: string) {
    const key = target?.key;
    content = JSON.parse(json);
    typing = false;
    renders++;
    markDirty();
    await fit();
    const el = key ? sheet?.querySelector<HTMLElement>(`[data-key="${key}"]`) : null;
    if (el) {
      el.focus({ preventScroll: true });
      const n = el.textContent?.length ?? 0;
      select(el, n, n);
    }
  }
  function undo() {
    if (!past.length || !content) return;
    future = [...future, snapshot()];
    const last = past.at(-1)!;
    past = past.slice(0, -1);
    restore(last);
  }
  function redo() {
    if (!future.length || !content) return;
    past = [...past, snapshot()];
    const next = future.at(-1)!;
    future = future.slice(0, -1);
    restore(next);
  }

  // ---------- the field and selection the toolbar acts on ----------
  const LABELS: Record<string, string> = {
    school: "School", degree: "Degree", location: "Location", dates: "Dates", organization: "Employer", role: "Role",
    name: "Project name", tech: "Technologies", link: "Link", label: "Skill group", items: "Skills", awards: "Awards",
    date: "Date", recipient: "Recipient", greeting: "Greeting", closing: "Closing", signature: "Signature",
  };
  function describe(key: string): string {
    const parts = key.split(".");
    const prev = parts.at(-2);
    if (key === "header.name") return "Name";
    if (parts[0] === "header") return "Contact line";
    if (parts[0] === "heading") return "Section title";
    if (prev === "bullets") return "Bullet";
    if (prev === "details") return "Education detail";
    if (prev === "paragraphs") return `Paragraph ${Number(parts.at(-1)) + 1}`;
    return LABELS[parts.at(-1)!] ?? "Text";
  }

  function onfocusin(e: FocusEvent) {
    const el = (e.target as Element).closest?.<HTMLElement>("[data-key]");
    if (!el) return;
    typing = false;
    const block = el.closest<HTMLElement>("[data-block]");
    target = {
      key: el.dataset.key!, blockKey: block?.dataset.block ?? null, label: describe(el.dataset.key!),
      rich: !("plain" in el.dataset), alignable: !!block && !("noalign" in block.dataset), block: !!block,
    };
  }

  const query = (cmd: string) => { try { return document.queryCommandState(cmd); } catch { return false; } };
  function onselectionchange() {
    const sel = getSelection();
    if (!sel?.rangeCount || !sheet) return;
    const node = sel.anchorNode;
    const el = (node instanceof Element ? node : node?.parentElement)?.closest<HTMLElement>("[data-key]");
    if (!el || !sheet.contains(el)) return;
    savedRange = sel.getRangeAt(0).cloneRange();
    marks = { b: query("bold"), i: query("italic"), u: query("underline") };
    let value = "";
    try { value = document.queryCommandValue("foreColor"); } catch { /* not supported */ }
    colour = hex(value) ?? "#000000";
  }

  function select(el: HTMLElement, start: number, end: number) {
    const sel = getSelection();
    if (!sel) return;
    const r = rangeAt(el, start, end);
    sel.removeAllRanges();
    sel.addRange(r);
    savedRange = r.cloneRange();
  }

  function changed() {
    markDirty();
    formats++;
    fit();
  }

  /** Bold, italic, underline or colour on the selection, or on the whole field when nothing is selected. */
  function mark(cmd: "bold" | "italic" | "underline" | "foreColor", value?: string) {
    const el = fieldEl();
    if (!el || !target?.rich) return;
    remember();
    // A keyboard user stays on the toolbar button; the command needs focus in the field meanwhile.
    const from = document.activeElement?.closest(".fmt-bar") ? (document.activeElement as HTMLElement) : null;
    // The live selection when it's in the field (a shortcut), else the one saved before a toolbar click.
    const live = getSelection();
    const current = live?.rangeCount && el.contains(live.getRangeAt(0).commonAncestorContainer) ? live.getRangeAt(0).cloneRange() : null;
    el.focus({ preventScroll: true });
    const range = current ?? (savedRange && el.contains(savedRange.commonAncestorContainer) ? savedRange : null);
    const caret = range ? textOffsets(el, range) : null;
    const whole = !range || range.collapsed;
    const sel = getSelection()!;
    const r = whole ? document.createRange() : range!;
    if (whole) r.selectNodeContents(el);
    sel.removeAllRanges();
    sel.addRange(r);
    commanding = true;
    try {
      document.execCommand("styleWithCSS", false, "false");
      document.execCommand(cmd, false, value);
    } finally {
      commanding = false;
    }
    typing = false;
    // The field stored the new line on input; redraw it from that so the markup stays simple.
    const after = whole ? caret : textOffsets(el, sel.getRangeAt(0));
    el.dispatchEvent(new Event("doc:refresh"));
    if (after) select(el, after[0], after[1]);
    onselectionchange();
    from?.focus();
    changed();
  }

  const act: FormatActions = {
    undo,
    redo,
    mark: cmd => mark(cmd),
    colour: value => mark("foreColor", value),
    size(step) {
      const el = fieldEl();
      if (!el || !target) return;
      remember();
      const now = Math.round(parseFloat(getComputedStyle(el).fontSize) * 0.75 * 2) / 2; // px -> pt, to 0.5
      const k = (now + step * 0.5) / fitted.fs;
      setStyle(target.key, { size: Math.min(SIZE_LIMITS.max, Math.max(SIZE_LIMITS.min, k)) });
      changed();
    },
    align(value: Align) {
      if (!target?.blockKey || !target.alignable) return;
      remember();
      setStyle(target.blockKey, { align: value });
      changed();
    },
    spacing(which, lines) {
      if (!target?.blockKey) return;
      remember();
      setStyle(target.blockKey, { [which]: lines });
      changed();
    },
    blankLine() {
      if (!target?.blockKey) return;
      remember();
      setStyle(target.blockKey, { after: Math.min(4, (styleOf(target.blockKey).after ?? 0) + 1) });
      changed();
    },
    clear() {
      const el = fieldEl();
      if (!el || !target || !content) return;
      remember();
      el.dispatchEvent(new Event("doc:clear"));
      delete styles()[target.key];
      onselectionchange();
      changed();
    },
    page(update: Partial<PageFormat>) {
      if (!content) return;
      remember();
      format().page = { ...format().page, ...update };
      changed();
    },
    resetPage() {
      if (!content?.format?.page) return;
      remember();
      delete format().page;
      changed();
    },
    async clearAll() {
      if (!content) return;
      remember();
      const { format: _dropped, ...rest } = content;
      content = withoutFormatting(rest) as ResumeContent | LetterContent;
      renders++;
      markDirty();
      await fit();
    },
  };

  // The toolbar's view of the current field.
  const style = $derived.by(() => {
    void formats; void renders;
    const own = target ? fieldEl() : null;
    const block = blockEl();
    const s = styleOf(target?.blockKey);
    const ta = target?.alignable && block ? getComputedStyle(block).textAlign : "";
    const align: Align | null = !ta ? null : ta === "center" ? "center" : ta === "right" || ta === "end" ? "right" : ta === "justify" ? "justify" : "left";
    return {
      align, before: s.before ?? 0, after: s.after ?? 0,
      sizePt: own ? Math.round(parseFloat(getComputedStyle(own).fontSize) * 0.75 * 2) / 2 : null,
    };
  });
  const page = $derived.by(() => { void formats; void renders; return pageOf(content?.format); });

  function onbeforeinput(e: InputEvent) {
    if (e.inputType === "historyUndo" || e.inputType === "historyRedo") {
      e.preventDefault();
      if (e.inputType === "historyUndo") undo(); else redo();
      return;
    }
    if (e.defaultPrevented || commanding || typing) return;
    remember();
    typing = true;
  }

  function onkeydown(e: KeyboardEvent) {
    if (!(e.metaKey || e.ctrlKey) || e.altKey || !content) return;
    const t = e.target as HTMLElement;
    if (t.closest?.("input, textarea, select")) return;
    const k = e.key.toLowerCase();
    if (k === "z") { e.preventDefault(); if (e.shiftKey) redo(); else undo(); }
    else if (k === "y" && e.ctrlKey) { e.preventDefault(); redo(); }
    else if ((k === "b" || k === "i" || k === "u") && !e.shiftKey && t.closest?.("[data-key]")) {
      e.preventDefault();
      if (target?.rich) mark(({ b: "bold", i: "italic", u: "underline" } as const)[k]);
    }
  }

  // ---------- swapping a bullet for another phrasing ----------
  const swapButton = (key: string) => sheet?.querySelector(`[data-swap="${key}"]`) as HTMLElement | null;
  async function toggleSwap(key: string) {
    open = open === key ? null : key;
    if (open) { await tick(); menuEl?.querySelector("button")?.focus(); }
  }
  function closeSwap(key: string) {
    open = null;
    swapButton(key)?.focus();
  }
  async function swap(x: ResumeEntry, i: number, text: string, ref: BulletRef, key: string) {
    remember();
    x.bullets[i] = text;
    (x.refs ??= [])[i] = ref;
    markDirty();
    open = null;
    renders++;
    await fit();
    swapButton(key)?.focus();
  }
  // While a menu is open: a click elsewhere closes it, Escape closes it and returns focus.
  $effect(() => {
    const key = open;
    if (!key) return;
    const onDown = (e: PointerEvent) => { if (!(e.target as Element).closest?.(".r-swap, .r-swap-menu")) open = null; };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") { e.preventDefault(); closeSwap(key); } };
    window.addEventListener("pointerdown", onDown);
    window.addEventListener("keydown", onKey);
    return () => { window.removeEventListener("pointerdown", onDown); window.removeEventListener("keydown", onKey); };
  });

  async function save() {
    if (!doc || !content) return;
    saving = true;
    msg = { text: "Saving…", kind: "busy" };
    try {
      const saved = await api.saveDocument(doc.id, cleaned(content));
      dirty = false;
      await render({ ...doc, ...saved } as FullDocument);
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

  // The Word file is built by the server from the saved document, so unsaved edits are saved first.
  async function downloadWord() {
    if (!doc) return;
    const hadEdits = dirty;
    if (dirty) {
      await save();
      if (dirty) return;
    }
    msg = { text: "Making the Word file…", kind: "busy" };
    try {
      const { blob, name } = await api.documentDocx(doc.id, fitted.fs, fitted.sp);
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = name;
      document.body.append(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 10_000);
      msg = { text: hadEdits ? "Saved your edits and downloaded the Word file" : "Downloaded the Word file", kind: "ok" };
    } catch (err) {
      msg = { text: `Couldn't make the Word file: ${(err as Error).message}`, kind: "error" };
    }
  }

  function back() {
    if (history.length > 1 && document.referrer.startsWith(location.origin)) history.back();
    else location.href = "./#tracker";
  }

  const kind = $derived(doc ? (doc.kind === "resume" ? "Resume" : "Cover letter") : "Document");
  const words = $derived(doc?.kind === "cover_letter" ? doc.content.paragraphs.map(plain).join(" ").split(/\s+/).filter(Boolean).length : 0);
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
      const name = plain(d.content.header?.name);
      document.title = [name, d.kind === "resume" ? "Resume" : "Cover letter", d.listing?.company].filter(Boolean).join(" – ");
      render(d);
      if (d.kind === "resume") api.profile({ quiet: true }).then(p => { pool = p.data; }).catch(() => { /* no swapping, nothing else lost */ });
    })().catch(err => { error = (err as Error).message; });
    return () => window.removeEventListener("beforeunload", beforeunload);
  });
</script>

<svelte:window {onkeydown} />
<svelte:document {onselectionchange} />

{#snippet bullets(x: ResumeEntry, prefix: string)}
  <ul>
    {#each x.bullets as _, i (i)}
      {@const key = `${prefix}-${i}`}
      {@const path = `${prefix}.bullets.${i}`}
      {@const options = swapOptions(x, i, pool)}
      <li class="r-li">
        <div class="r-bullet" data-block={path} use:editable={item(x.bullets, i, path)}></div>
        {#if options}
          <button type="button" class="r-swap" data-swap={key} aria-label="Swap this bullet for another phrasing" aria-expanded={open === key}
            title="Swap for another phrasing" onclick={() => toggleSwap(key)}><Icon name="swap" /></button>
          {#if open === key}
            <div class="r-swap-menu" role="group" aria-label="Other phrasings" bind:this={menuEl}>
              {#if options.phrasings.length}
                <h4>Other phrasings of this point</h4>
                <ul>{#each options.phrasings as o (o.phrasing)}<li><button type="button" onclick={() => swap(x, i, o.text, { point_id: x.refs![i]!.point_id, phrasing: o.phrasing }, key)}>{o.text}</button></li>{/each}</ul>
              {/if}
              {#if options.points.length}
                <h4>Other points from this entry</h4>
                <ul>{#each options.points as o (o.point_id)}<li><button type="button" onclick={() => swap(x, i, o.text, { point_id: o.point_id, phrasing: 0 }, key)}>{o.text}</button></li>{/each}</ul>
              {/if}
            </div>
          {/if}
        {/if}
      </li>
    {/each}
  </ul>
{/snippet}

{#snippet header(h: DocHeader, cls: string)}
  <header class={cls}>
    <!-- svelte-ignore a11y_missing_content (the editable action fills in the name) -->
    <h1 class="r-name" data-block="header.name" use:editable={field(h, "name", "header.name")}></h1>
    <p class="r-contact" data-block="header.contact">
      {#each h.contact as _, i (i)}{#if i}<span class="sep">|</span>{/if}<span use:editable={item(h.contact, i, `header.contact.${i}`)}></span>{/each}{#each h.links as link, i (i)}{#if i || h.contact.length}<span class="sep">|</span>{/if}<span class="" use:editable={field(link, "url", `header.links.${i}.url`)}></span>{/each}
    </p>
  </header>
{/snippet}

{#snippet sectionTitle(section: HeadingKey)}
  <!-- svelte-ignore a11y_missing_content (the editable action fills in the title) -->
  <h2 data-block="heading.{section}" use:editable={heading(section)}></h2>
{/snippet}

<div class="doc-top">
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
    <button type="button" id="doc-word" class="btn btn-quiet" disabled={saving || !doc} hidden={!!error} onclick={downloadWord}>Download Word</button>
    <button type="button" id="doc-print" class="btn btn-primary" hidden={!!error} onclick={print}>Download PDF</button>
  </header>
  {#if doc && !error}
    <FormatBar {target} canUndo={past.length > 0} canRedo={future.length > 0} {marks} {colour} {style} {page} {act} />
  {/if}
</div>
<p id="doc-hint" class="doc-hint muted" hidden={!!error}>
  Click any text on the page to edit it. Select words to make them bold, italic, underlined or coloured, and use Shift+Enter for a new line. Page sets the margins, font and text size. To download a PDF, choose “Save as PDF” as the destination in the print dialog.
</p>

<main class="doc-stage">
  {#if error}
    <div class="doc-error"><p>{error}</p><p class="muted">Open documents from a listing in your tracker.</p></div>
  {:else}
    <article id="sheet" class="sheet" class:is-letter={doc?.kind === "cover_letter"} class:overflows aria-live="polite" bind:this={sheet}
      {onfocusin} {onbeforeinput} onfocusout={() => { if (dirty) fit(); }}>
      {#key renders}
        {#if doc && content}
          {#if doc.kind === "resume"}
            {@const c = resume()}
            <div class="page">
              {@render header(c.header, "")}
              {#if c.education?.length}
                <section class="r-section">{@render sectionTitle("education")}
                  {#each c.education as e, idx (idx)}
                    {@const p = `education.${idx}`}
                    <div class="r-entry" data-block={p} data-noalign>
                      <div class="r-row"><div><strong use:editable={field(e, "school", `${p}.school`)}></strong></div><span use:editable={field(e, "location", `${p}.location`)}></span></div>
                      <div class="r-row"><div><em use:editable={field(e, "degree", `${p}.degree`)}></em></div><span use:editable={field(e, "dates", `${p}.dates`)}></span></div>
                      {#each e.details as _, i (i)}<p class="r-detail" data-block="{p}.details.{i}" use:editable={item(e.details, i, `${p}.details.${i}`)}></p>{/each}
                      {#if idx === 0 && c.awards?.length}<p class="r-detail" data-block="awards"><b>{"Awards: "}</b><span use:editable={joined(c.awards, ";", "; ", "awards")}></span></p>{/if}
                    </div>
                  {/each}
                </section>
              {/if}
              {#if c.experience?.length}
                <section class="r-section">{@render sectionTitle("experience")}
                  {#each c.experience as x, idx (idx)}
                    {@const p = `experience.${idx}`}
                    <div class="r-entry" data-block={p} data-noalign>
                      <div class="r-row"><div><strong use:editable={field(x, "organization", `${p}.organization`)}></strong></div><span use:editable={field(x, "location", `${p}.location`)}></span></div>
                      <div class="r-row"><div><em use:editable={field(x, "role", `${p}.role`)}></em></div><span use:editable={field(x, "dates", `${p}.dates`)}></span></div>
                      {@render bullets(x, p)}
                    </div>
                  {/each}
                </section>
              {/if}
              {#if c.projects?.length}
                <section class="r-section">{@render sectionTitle("projects")}
                  {#each c.projects as x, idx (idx)}
                    {@const p = `projects.${idx}`}
                    <div class="r-entry" data-block={p} data-noalign>
                      <div class="r-row"><div><strong use:editable={field(x, "name", `${p}.name`)}></strong>{#if plain(x.tech)}<span>{" | "}</span><span class="r-tech" use:editable={field(x, "tech", `${p}.tech`)}></span>{/if}{#if plain(x.link)}<span>{" | "}</span><span use:editable={field(x, "link", `${p}.link`)}></span>{/if}</div><span use:editable={field(x, "dates", `${p}.dates`)}></span></div>
                      {@render bullets(x, p)}
                    </div>
                  {/each}
                </section>
              {/if}
              {#if c.skills?.length}
                <section class="r-section">{@render sectionTitle("skills")}
                  <div class="r-skills">
                    {#each c.skills as g, idx (idx)}<p data-block="skills.{idx}"><b use:editable={field(g, "label", `skills.${idx}.label`)}></b><b>{": "}</b><span use:editable={joined(g.items, ",", ", ", `skills.${idx}.items`)}></span></p>{/each}
                  </div>
                </section>
              {/if}
            </div>
          {:else}
            {@const c = letter()}
            <div class="page">
              {@render header(c.header, "doc-l-head")}
              <div class="doc-l-meta"><p data-block="date" use:editable={field(c, "date", "date")}></p><p data-block="recipient" use:editable={field(c, "recipient", "recipient")}></p></div>
              <div class="doc-l-body">
                <p class="doc-l-greeting" data-block="greeting" use:editable={field(c, "greeting", "greeting")}></p>
                {#each c.paragraphs as _, i (i)}<p data-block="paragraphs.{i}" use:editable={item(c.paragraphs, i, `paragraphs.${i}`)}></p>{/each}
                <p class="doc-l-closing" data-block="closing" use:editable={field(c, "closing", "closing")}></p>
                <p class="doc-l-signature" data-block="signature" use:editable={field(c, "signature", "signature")}></p>
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
        {#if doc.kind === "resume" && pool}<p class="muted">Hover a bullet and use the swap button to pick another phrasing from your profile.</p>{/if}
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
