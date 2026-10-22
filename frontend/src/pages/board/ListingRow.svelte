<script lang="ts">
  import { ago, monogram } from "../../lib/format";
  import { board, why } from "../../lib/stores/board.svelte";
  import { tier, TIER_LABEL } from "../../lib/stores/ranking.svelte";
  import { tracker, loadTracker } from "../../lib/stores/tracker.svelte";
  import { openDrawer } from "../../lib/stores/drawer.svelte";
  import * as api from "../../lib/api";
  import type { Listing } from "../../lib/types";

  let { l }: { l: Listing } = $props();

  // Where a listing came from. Zapply's reuse terms ask for credit and a link to their repository.
  const SOURCE_LABELS: Record<string, [string, string]> = {
    negarprh: ["Canadian Tech Internships", "https://github.com/negarprh/Canadian-Tech-Internships-2027"],
    michelleokolie: ["Canada Tech Internships", "https://github.com/michelleokolie/canada-tech-internships-summer-2027"],
    frogg: ["Frogg Canadian Internships", "https://github.com/seun-ipaye/frogg-canadian-internships"],
    zapply: ["Zapply", "https://github.com/zapplyjobs/Internships-2027"],
  };

  const isNew = $derived(!!board.prevVisit && l.first_seen > board.prevVisit);
  const locs = $derived(l.locations.split(" / "));
  const locText = $derived(locs.length > 2 ? `${locs.slice(0, 2).join(" · ")} +${locs.length - 2}` : locs.join(" · "));
  const tracked = $derived(tracker.items.find(i => i.id === l.id));
  const source = $derived(SOURCE_LABELS[l.source]);
  const t = $derived(l.match_score == null ? null : tier(l.match_score));
  const by = $derived(l.match_method === "claude" ? "Claude" : "keyword match");
  const whyOpen = $derived(why.has(l.id));
  // Sponsorship, in plain words; the tooltip says where it came from.
  const VISA: Record<string, { text: string; cls: string }> = {
    "Offers Sponsorship": { text: "Offers sponsorship", cls: "ok" },
    "May Offer Sponsorship": { text: "May sponsor", cls: "maybe" },
    "Does Not Offer Sponsorship": { text: "No sponsorship", cls: "warn" },
    "U.S. Citizenship is Required": { text: "US citizens only", cls: "warn" },
  };
  const visa = $derived(l.sponsorship ? VISA[l.sponsorship] : undefined);

  let tracking = $state(false);
  async function track() {
    tracking = true;
    try {
      await api.track(l.id, { status: "saved", position: Date.now() / 1000 });
      await loadTracker();
    } catch { /* the request showed a toast */ } finally {
      tracking = false;
    }
  }

  function toggleWhy() {
    if (whyOpen) why.delete(l.id);
    else why.add(l.id);
  }
</script>

<article class="listing" data-id={l.id}>
  <div class="monogram" aria-hidden="true">{monogram(l.company)}</div>
  <div class="l-main">
    <div class="l-company">{l.company}
      {#if isNew}<span class="tag new">New</span>{/if}
      {#if l.source === "board"}<span class="tag direct" title="Found on the company's own job board">Direct</span>
      {:else if source}<a class="via" href={source[1]} target="_blank" rel="noopener">via {source[0]}</a>{/if}
    </div>
    <a class="l-title" href={l.url} target="_blank" rel="noopener">{l.title}</a>
    <div class="l-meta">
      <span class="loc" title={locs.join("\n")}>{locText}</span>
      {#if l.category}<span class="tag">{l.category}</span>{/if}
      {#each l.terms as term (term)}<span class="tag">{term}</span>{/each}
      {#if visa}<span class="tag {visa.cls}" title={l.sponsorship_note ?? undefined}>{visa.text}</span>{/if}
      <span class="age">{ago(l.date_posted)}</span>
      {#if t && l.match_score != null}
        <button type="button" class="match-badge {t}" data-match-why aria-expanded={whyOpen} onclick={toggleWhy}
          title={`${TIER_LABEL[t]}, ${l.match_score}/100 (${by}): ${l.match_reason || "no reason given"}`}
          aria-label={`${TIER_LABEL[t]}, ${l.match_score} out of 100, scored by ${by}. Show why.`}>
          <span class="num">{l.match_score}</span>{#if l.match_method === "claude"}<svg class="match-claude" viewBox="0 0 12 12" aria-hidden="true"><path d="M6 1.2 7.2 4.8 10.8 6 7.2 7.2 6 10.8 4.8 7.2 1.2 6 4.8 4.8Z"/></svg>{/if}</button>
      {/if}
    </div>
    {#if whyOpen}
      <p class="match-why">{l.match_reason || "No reason given."}
        <span class="muted">· {l.match_method === "claude" ? "Claude" : "Keyword match"}, {l.match_score}/100</span></p>
    {/if}
  </div>
  <div class="l-actions">
    <span class="track-slot">
      {#if tracked}
        <button class="btn btn-quiet track-btn tracked" title="Edit in tracker" onclick={() => openDrawer(l.id)}>{tracked.status}</button>
      {:else}
        <button class="btn btn-quiet track-btn" disabled={tracking} onclick={track}>
          <svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>Track</button>
      {/if}
    </span>
    <a class="btn btn-quiet" href={l.url} target="_blank" rel="noopener">Apply ↗</a>
  </div>
</article>
