<script lang="ts">
  import { onMount, untrack } from "svelte";
  import Select from "../../lib/components/Select.svelte";
  import * as api from "../../lib/api";
  import { ago } from "../../lib/format";
  import { KIND_LABEL, running, messages, lastNotes, versions, openPaste, writeDocument, loadDescription, pasteDescription } from "../../lib/stores/documents.svelte";
  import type { DocumentNotes, DocumentSummary, PostingStatus, TrackerItem } from "../../lib/types";

  // Tailored resumes and cover letters for one listing (tracker side panel and the tool pages).
  let { item, tool = false }: { item: TrackerItem; tool?: boolean } = $props();
  const SOURCE_LABEL: Record<string, string> = {
    api: "from the company's job board", claude: "read from the posting page", pasted: "pasted by you",
  };
  const TONES = [{ value: "formal", label: "Formal" }, { value: "conversational", label: "Conversational" }, { value: "enthusiastic", label: "Enthusiastic" }];

  let status = $state<PostingStatus | null | "error">(null);
  let docs = $state<DocumentSummary[] | null>(null);
  let listError = $state("");
  let tone = $state("formal");
  let pasteOpen = $state(false);
  let pasteText = $state("");
  let pasting = $state(false);
  let deleting = $state<string | null>(null);

  const busy = $derived(running.has(item.id) || pasting);
  const msg = $derived(messages.get(item.id) ?? { text: "", kind: "" });
  const notes = $derived(lastNotes.get(item.id));

  async function loadStatus() {
    try { status = await api.postingStatus(item.id, { quiet: true }); } catch { status = "error"; }
  }
  async function loadList() {
    try { docs = (await api.documents(item.id, { quiet: true })).items; listError = ""; } catch (err) { listError = (err as Error).message; }
  }

  onMount(() => {
    // A message from an earlier visit only stays while its job is still running.
    if (!running.has(item.id)) messages.delete(item.id);
  });
  // Load now, and again whenever a job or a paste changes this listing's documents.
  $effect(() => {
    void versions.get(item.id);
    untrack(() => { loadStatus(); loadList(); });
  });
  $effect(() => {
    if (openPaste.get(item.id)) { pasteOpen = true; openPaste.delete(item.id); }
  });

  async function remove(d: DocumentSummary) {
    if (!confirm(`Delete this ${KIND_LABEL[d.kind].toLowerCase()}? This can't be undone.`)) return;
    deleting = d.id;
    try { await api.deleteDocument(d.id); await loadList(); } catch { /* shown */ } finally { deleting = null; }
  }

  async function savePaste() {
    pasting = true;
    try {
      if (await pasteDescription(item.id, pasteText.trim())) { pasteOpen = false; pasteText = ""; }
    } finally { pasting = false; }
  }

  const block = (n: DocumentNotes | undefined) => !n ? [] : ([
    ["Check before sending", n.checks, "docs-warn"], ["Emphasised", n.emphasized, ""], ["Draws on", n.drew_on, ""], ["Gaps in the posting", n.gaps, ""],
  ] as [string, string[] | undefined, string][]).filter(([, items]) => items?.length);
</script>

<section class="drawer-section docs" class:tool-section={tool}>
  <h3>Documents</h3>
  <div class="docs-desc">
    <span class="docs-desc-status muted">{status === null ? "Checking for the job description…"
      : status === "error" ? "Couldn't check the job description."
      : status.available ? `Job description ${SOURCE_LABEL[status.source ?? ""] || "saved"} · ${status.chars.toLocaleString()} characters`
      : "Job description not loaded yet. Writing a document loads it first."}</span>
    <button type="button" class="link docs-load" hidden={status === null || status === "error" || status.available} disabled={busy}
      onclick={() => loadDescription(item.id)}>Load description</button>
  </div>
  <details class="docs-paste" bind:open={pasteOpen}>
    <summary>Paste job description</summary>
    <label class="field">
      <span>Job description <em>for postings that can't be loaded</em></span>
      <textarea rows="6" maxlength="50000" placeholder="Paste the full posting text here" bind:value={pasteText}></textarea>
    </label>
    <div class="docs-row">
      <button type="button" class="btn btn-quiet docs-paste-save" disabled={busy} onclick={savePaste}>Save description</button>
    </div>
  </details>
  <div class="docs-row docs-actions">
    <button type="button" class="btn btn-primary docs-resume" disabled={busy} onclick={() => writeDocument(item.id, "resume")}>Tailor resume</button>
    <span class="docs-letter">
      <button type="button" class="btn btn-quiet docs-letter-btn" disabled={busy} onclick={() => writeDocument(item.id, "cover_letter", tone)}>Write cover letter</button>
      <Select class="docs-tone" label="Cover letter tone" options={TONES} bind:value={tone} />
    </span>
  </div>
  <p class="form-msg docs-msg {msg.kind}" aria-live="polite">{msg.text}</p>
  <div class="docs-notes" hidden={!notes || running.has(item.id) || (notes.description_used !== false && !block(notes).length)}>
    {#if notes}
      {#if notes.description_used === false}<p class="docs-warn">Written without the job description. Paste it above and write again for a closer fit.</p>{/if}
      {#each block(notes) as [title, items, cls] (title)}
        <p class="docs-notes-title">{title}</p><ul class={cls}>{#each items ?? [] as t, i (i)}<li>{t}</li>{/each}</ul>
      {/each}
    {/if}
  </div>
  <ul class="docs-list">
    {#if listError}
      <li class="form-msg error">{listError}</li>
    {:else if docs}
      {#each docs as d (d.id)}
        <li class="docs-item" data-id={d.id}>
          <span class="docs-item-main">
            <strong>{KIND_LABEL[d.kind] || d.kind}</strong>
            <span class="muted">{ago(d.created_at)}{d.updated_at > d.created_at + 5 ? " · edited" : ""}</span>
            {#if d.stale}<span class="tag warn" title="Your profile changed after this was written">Older profile</span>{/if}
            {#if d.notes?.description_used === false}<span class="tag" title="Written from the title and company only">No description</span>{/if}
          </span>
          <a class="btn btn-quiet docs-open" href={`doc.html?id=${encodeURIComponent(d.id)}`} target="_blank" rel="noopener">Open ↗</a>
          <button type="button" class="btn btn-danger-quiet docs-delete" disabled={deleting === d.id} onclick={() => remove(d)}>Delete</button>
        </li>
      {:else}
        <li class="muted docs-empty">No documents for this listing yet.</li>
      {/each}
    {/if}
  </ul>
</section>
