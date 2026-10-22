<script lang="ts">
  import { onMount } from "svelte";
  import Select from "../../lib/components/Select.svelte";
  import ListingRow from "./ListingRow.svelte";
  import { ago, dayGroup } from "../../lib/format";
  import { board, loadMore, filtersChanged, clearFilters, groupKey, refreshNow } from "../../lib/stores/board.svelte";
  import { filters, anyActive } from "../../lib/stores/filters.svelte";
  import { meta } from "../../lib/stores/meta.svelte";
  import { tracker, dueThisWeek } from "../../lib/stores/tracker.svelte";
  import { ranking } from "../../lib/stores/ranking.svelte";
  import { profile, hasProfileData } from "../../lib/stores/profile.svelte";
  import { navigate } from "../../lib/stores/router.svelte";
  import { companies, loadCompanies } from "../../lib/stores/companies.svelte";
  import type { Count, Listing } from "../../lib/types";

  let { visible }: { visible: boolean } = $props();

  // ---------- options from /api/meta ----------
  const opts = (items: Count<string | null>[] | undefined, all: string) =>
    [{ value: "", label: all }, ...(items ?? []).filter(i => i.value).map(i => ({ value: i.value!, label: `${i.value} · ${i.count.toLocaleString()}` }))];
  const categories = $derived(opts(meta.data?.categories, "All categories"));
  const terms = $derived(opts(meta.data?.terms, "Any term"));
  const degrees = $derived(opts(meta.data?.degrees, "Any degree"));
  const SOURCES = [
    { value: "", label: "All sources" }, { value: "simplify", label: "SimplifyJobs list" }, { value: "board", label: "Company boards" },
    { value: "negarprh", label: "Canadian Tech Internships" }, { value: "michelleokolie", label: "Canada Tech Internships" },
    { value: "frogg", label: "Frogg Canadian Internships" }, { value: "zapply", label: "Zapply" },
  ];
  const SORTS = [
    { value: "posted", label: "Newest posted" }, { value: "added", label: "Recently added here" },
    { value: "company", label: "Company A–Z" }, { value: "match", label: "Best match" },
  ];
  // Sponsorship: what US postings say (or the source list, when the posting doesn't say).
  const sponsorCount = (v: string) => meta.data?.sponsorship?.find(x => x.value === v)?.count ?? 0;
  const sponsorships = $derived([
    { value: "", label: "Any sponsorship" },
    { value: "offers", label: `Offers sponsorship · ${sponsorCount("Offers Sponsorship").toLocaleString()}` },
    { value: "likely", label: `Offers or may sponsor · ${(sponsorCount("Offers Sponsorship")
      + sponsorCount("May Offer Sponsorship")).toLocaleString()}` },
    { value: "open", label: `Not ruled out · ${((meta.data?.active ?? 0) - sponsorCount("Does Not Offer Sponsorship")
      - sponsorCount("U.S. Citizenship is Required")).toLocaleString()}` },
  ]);
  const regionCount = (r: string) => (meta.data?.regions.find(x => x.value === r)?.count ?? 0).toLocaleString();
  const sourceCount = (s: string) => (meta.data?.sources.find(x => x.value === s)?.count ?? 0).toLocaleString();

  // A saved filter whose option no longer exists falls back to "all" once the options arrive.
  $effect(() => {
    if (!meta.data) return;
    for (const [key, list] of [["category", categories], ["term", terms], ["degree", degrees]] as const) {
      if (filters[key] && !list.some(o => o.value === filters[key])) filters[key] = "";
    }
  });

  // ---------- sync status ----------
  const sync = $derived.by(() => {
    if (board.syncOverride) return board.syncOverride;
    const m = meta.data;
    if (!m) return { kind: "", text: "Connecting…" };
    if (m.last_error) return { kind: "error", text: "Last refresh failed" };
    if (m.last_refresh) return { kind: "ok", text: `Updated ${ago(m.last_refresh)}` };
    return { kind: "busy", text: "First import…" };
  });

  // ---------- filters ----------
  let searchTimer: ReturnType<typeof setTimeout> | undefined;
  function onSearch() {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(filtersChanged, 250);
  }
  const changed = () => { clearTimeout(searchTimer); filtersChanged(); };

  let searchInput: HTMLInputElement;
  function onKey(e: KeyboardEvent) {
    const target = e.target as HTMLElement;
    if (e.key === "/" && !target.closest?.("input, textarea, select") && visible) {
      e.preventDefault();
      searchInput.focus();
    }
  }

  function stat(kind: "new" | "CA" | "board" | "due") {
    if (kind === "due") { navigate("#tracker"); return; }
    if (kind === "new") filters.new_only = !filters.new_only;
    if (kind === "CA") filters.region = filters.region === "CA" ? "" : "CA";
    if (kind === "board") filters.source = filters.source === "board" ? "" : "board";
    filtersChanged();
  }

  // ---------- groups ----------
  const groups = $derived.by(() => {
    const out: { key: string; items: Listing[] }[] = [];
    for (const l of board.items) {
      const key = groupKey(l, filters.sort, dayGroup);
      const last = out.at(-1);
      if (last && last.key === key) last.items.push(l);
      else out.push({ key, items: [l] });
    }
    return out;
  });

  // "Best match needs your resume" when sorting by match without a profile.
  const rankNote = $derived.by(() => {
    if (filters.sort !== "match") return false;
    const s = ranking.status;
    if (!s && !profile.data) return false;
    return !(s ? s.has_profile : hasProfileData());
  });

  // ---------- infinite scroll ----------
  let sentinel: HTMLDivElement;
  onMount(() => {
    const observer = new IntersectionObserver(entries => {
      if (entries[0].isIntersecting && visible && !board.loading && board.items.length) loadMore();
    }, { rootMargin: "600px" });
    observer.observe(sentinel);
    return () => observer.disconnect();
  });
</script>

<svelte:document onkeydown={onKey} />

<div class="intro">
  <div>
    <h1 id="board-heading"><span id="open-total" class="num">{meta.data ? meta.data.active.toLocaleString() : "–"}</span> open internships</h1>
    <p class="lede">Software and tech roles in Canada and the US, from SimplifyJobs, four more community lists and <span id="board-count-text">{meta.data?.boards.enabled ? `${(meta.data.boards.hiring ?? 0).toLocaleString()} company job boards` : "company job boards"}</span>. Only listings posted in the last 30 days are shown.</p>
    <div class="board-sync">
      <span id="sync-status" class="sync-status {sync.kind}" title={!board.syncOverride ? meta.data?.last_error || "" : ""}><span class="dot"></span><span class="label">{sync.text}</span></span>
      <button id="refresh-btn" class="btn btn-quiet" class:spinning={board.refreshing} disabled={board.refreshing} onclick={() => refreshNow(companies.loaded ? loadCompanies : undefined)}
        title="Check every source for new internships now (about 1–2 minutes)">
        <svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M20 12a8 8 0 1 1-2.34-5.66M20 4v4.5h-4.5"/></svg>
        <span>{board.refreshing ? "Refreshing…" : "Refresh"}</span>
      </button>
      <span id="refresh-result" class={board.refreshResult.cls} role="status">{board.refreshResult.text}</span>
    </div>
  </div>
  <div class="stats" id="stats">
    <button type="button" class="stat" class:active={filters.new_only} data-stat="new" onclick={() => stat("new")}><span class="stat-label">New since last visit</span><span class="stat-value num" id="stat-new">{board.newCount === null ? "–" : board.newCount.toLocaleString()}</span></button>
    <button type="button" class="stat" class:active={filters.region === "CA"} data-stat="CA" onclick={() => stat("CA")}><span class="stat-label">In Canada</span><span class="stat-value num" id="stat-ca">{meta.data ? regionCount("CA") : "–"}</span></button>
    <button type="button" class="stat" class:active={filters.source === "board"} data-stat="board" onclick={() => stat("board")}><span class="stat-label">Direct from companies</span><span class="stat-value num" id="stat-board">{meta.data ? sourceCount("board") : "–"}</span></button>
    <button type="button" class="stat" data-stat="due" onclick={() => stat("due")}><span class="stat-label">Deadlines this week</span><span class="stat-value num" id="stat-due">{tracker.loaded ? dueThisWeek(tracker.items) : "–"}</span></button>
  </div>
</div>

<form id="filters" class="filters" autocomplete="off" role="search" onsubmit={e => e.preventDefault()}>
  <label class="search">
    <svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="6.5"/><path d="m20 20-4.2-4.2"/></svg>
    <input type="search" name="q" placeholder="Search title, company or city" aria-label="Search listings" bind:value={filters.q} bind:this={searchInput} oninput={onSearch}>
    <kbd>/</kbd>
  </label>
  <div class="segmented" role="radiogroup" aria-label="Region">
    <label><input type="radio" name="region" value="" bind:group={filters.region} onchange={changed}><span>All <em data-count="all">{meta.data ? meta.data.active.toLocaleString() : ""}</em></span></label>
    <label><input type="radio" name="region" value="US" bind:group={filters.region} onchange={changed}><span>US <em data-count="US">{regionCount("US")}</em></span></label>
    <label><input type="radio" name="region" value="CA" bind:group={filters.region} onchange={changed}><span>Canada <em data-count="CA">{regionCount("CA")}</em></span></label>
    <label><input type="radio" name="region" value="REMOTE" bind:group={filters.region} onchange={changed}><span>Remote <em data-count="REMOTE">{regionCount("REMOTE")}</em></span></label>
  </div>
  <div class="filter-row">
    <Select name="category" label="Category" options={categories} bind:value={filters.category} class={filters.category ? "set" : ""} onchange={changed} />
    <Select name="term" label="Term" options={terms} bind:value={filters.term} class={filters.term ? "set" : ""} onchange={changed} />
    <Select name="degree" label="Degree" options={degrees} bind:value={filters.degree} class={filters.degree ? "set" : ""} onchange={changed} />
    <Select name="sponsorship" label="Sponsorship" options={sponsorships} bind:value={filters.sponsorship} class={filters.sponsorship ? "set" : ""} onchange={changed} />
    <Select name="source" label="Source" options={SOURCES} bind:value={filters.source} class={filters.source ? "set" : ""} onchange={changed} />
    <Select name="sort" label="Sort" options={SORTS} bind:value={filters.sort} onchange={changed} />
    <label class="toggle"><input type="checkbox" name="new_only" bind:checked={filters.new_only} onchange={changed}><span>New only</span></label>
    <label class="toggle"><input type="checkbox" name="hide_tracked" bind:checked={filters.hide_tracked} onchange={changed}><span>Hide tracked</span></label>
    <button type="button" id="clear-filters" class="link" hidden={!anyActive()} onclick={clearFilters}>Clear filters</button>
  </div>
</form>

<p id="result-count" class="result-count" aria-live="polite">{board.loaded ? `${board.total.toLocaleString()} internship${board.total === 1 ? "" : "s"}` : ""}</p>
{#if filters.sponsorship}
  <p id="sponsorship-note" class="filter-note">{{
    offers: "Listings whose posting, or the SimplifyJobs list, says it sponsors visas.",
    likely: "Also includes Zapply's estimates (“May sponsor”), which aren't statements from the employer. Check the posting before you apply.",
    open: "Hides listings whose posting says it can't sponsor visas or needs US citizenship or a clearance. Most postings don't say either way, so check before you apply.",
  }[filters.sponsorship]}</p>
{/if}
{#if rankNote}
  <p id="rank-note" class="rank-note">Best match needs your resume. <a class="link" href="#profile">Add it on the Profile tab</a>
    and every listing gets a score.</p>
{/if}
<div id="listings" class="listings">
  {#if board.loading || !board.loaded}
    <section class="group-wrap"><div class="group">
      {#each Array(7) as _, i (i)}
        <div class="listing skeleton"><div class="monogram"></div>
          <div class="l-main"><span class="bar" style="width:22%"></span><span class="bar" style="width:58%;margin-top:9px;height:13px"></span><span class="bar" style="width:40%;margin-top:9px"></span></div>
          <div class="l-actions"><span class="bar" style="width:150px;height:30px"></span></div></div>
      {/each}
    </div></section>
  {:else}
    {#each groups as g, i (`${i}:${g.key}`)}
      <section class="group-wrap"><h2 class="group-label">{g.key}</h2><div class="group">
        {#each g.items as l (l.id)}<ListingRow {l} />{/each}
      </div></section>
    {/each}
  {/if}
</div>
<div id="sentinel" aria-hidden="true" bind:this={sentinel}></div>
<button id="more-btn" class="btn btn-quiet wide" hidden={!board.loaded || board.items.length >= board.total} onclick={loadMore}>Show more</button>
<div id="empty" class="empty" hidden={!board.loaded || board.total > 0 || board.loading}>
  <p class="empty-title">No listings match these filters.</p>
  <p>Try a broader search, or <button type="button" class="link" onclick={clearFilters}>clear the filters</button>.</p>
</div>
