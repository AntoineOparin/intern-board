<script lang="ts">
  import { onMount } from "svelte";
  import Icon from "../../lib/components/Icon.svelte";
  import Logo from "./Logo.svelte";
  import PeopleHeader from "./PeopleHeader.svelte";
  import * as api from "../../lib/api";
  import { tracker } from "../../lib/stores/tracker.svelte";
  import { people } from "../../lib/stores/people.svelte";

  // Step 1: pick a company from the tracker.
  const items = $derived([...tracker.items].sort((a, b) => a.company.localeCompare(b.company)));
  let q = $state("");
  let logos: Record<string, string> = $state({});
  const shown = $derived(items.filter(i => {
    const term = q.trim().toLowerCase();
    return !term || `${i.title} ${i.company} ${i.locations}`.toLowerCase().includes(term);
  }));

  onMount(() => {
    people.loadingRow = null;
    api.peopleLogos({ quiet: true }).then(l => (logos = l)).catch(() => {});
  });
</script>

<PeopleHeader />
<section class="fp-panel">
  <h2>Who do you want to reach?</h2>
  <p class="muted">Pick a company from your tracker.</p>
  {#if items.length}
    <label class="fp-search"><Icon name="search" />
      <input type="search" placeholder="Search your tracked jobs" aria-label="Search your tracked jobs" bind:value={q} /></label>
    <ul class="fp-jobs" role="list">
      {#each shown as i (i.id)}
        <li><a class="fp-job-row" class:loading={people.loadingRow === i.id} href={`#people?listing=${encodeURIComponent(i.id)}`}
            data-id={i.id} onclick={() => (people.loadingRow = i.id)}>
          <Logo company={i.company} src={logos[i.id]} />
          <span class="fp-job-text"><strong>{i.title}</strong>
            <span class="muted">{i.company} <span class="fp-loc"><Icon name="pin" />{i.locations.split(" / ")[0]}</span></span></span>
          <span class="fp-job-icon"><Icon name="people" /></span>
        </a></li>
      {:else}
        <li class="muted fp-none">No tracked jobs match.</li>
      {/each}
    </ul>
  {:else}
    <div class="fp-empty">
      <p>Your tracker is empty. Press <strong>Track</strong> on a listing, then come back to find people there.</p>
      <a class="btn btn-primary" href="#board">Browse internships</a>
    </div>
  {/if}
</section>
