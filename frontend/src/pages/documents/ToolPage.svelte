<script lang="ts">
  import Select from "../../lib/components/Select.svelte";
  import DocsSection from "./DocsSection.svelte";
  import { tracker } from "../../lib/stores/tracker.svelte";
  import { load, store } from "../../lib/storage";

  // Resume tailor and Cover letter: the Documents section for one tracked internship.
  let { view }: { view: "resume" | "cover" } = $props();
  const TOOLS = {
    resume: { title: "Resume tailor", lede: "A one-page resume rewritten for one internship, using only what's in your profile. Edit it, then save as PDF." },
    cover: { title: "Cover letter", lede: "A short cover letter for one internship, in the tone you pick. It draws on real experience from your profile." },
  };
  const tool = $derived(TOOLS[view]);
  const items = $derived([...tracker.items].sort((a, b) =>
    tracker.statuses.indexOf(a.status) - tracker.statuses.indexOf(b.status) || a.company.localeCompare(b.company)));
  const options = $derived(items.map(i => ({ value: i.id, label: `${i.company} — ${i.title} (${i.status})` })));

  // The picked internship is remembered under `toolListing`.
  let wanted = $state(load<string | null>("toolListing", null));
  const selected = $derived(items.find(i => i.id === wanted) ?? items[0]);
  $effect(() => { if (selected) store("toolListing", selected.id); });
  const empty = $derived(tracker.loaded && items.length === 0);
</script>

<div class="intro intro-compact">
  <div>
    <h1 id="tool-heading">{tool.title}</h1>
    <p class="lede" id="tool-lede">{tool.lede}</p>
  </div>
</div>
<div class="tool-picker panel" hidden={empty || !selected}>
  {#if selected}
    <label class="field"><span>Internship</span>
      <Select id="tool-listing" label="Internship" {options} value={selected.id} onchange={v => (wanted = v)} /></label>
  {/if}
  <p class="muted tool-hint" id="tool-hint">Showing internships from your tracker.</p>
</div>
<div id="tool-empty" class="empty empty-panel" hidden={!empty}>
  <p class="empty-title">Track an internship first</p>
  <p>These tools work on internships in your tracker. Press <strong>Track</strong> on any listing, then come back.</p>
  <a class="btn btn-primary" href="#board">Browse internships</a>
</div>
<div id="tool-body" class="panel tool-body" hidden={empty || !selected}>
  {#if selected}
    {#key selected.id}<DocsSection item={selected} tool />{/key}
  {/if}
</div>
