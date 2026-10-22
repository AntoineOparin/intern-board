<script lang="ts">
  import Icon from "../../lib/components/Icon.svelte";
  import PeopleHeader from "./PeopleHeader.svelte";
  import SiteLine from "./SiteLine.svelte";
  import FreeLinks from "./FreeLinks.svelte";
  import Person from "./Person.svelte";
  import AddPerson from "./AddPerson.svelte";
  import { people, search, nounFor } from "../../lib/stores/people.svelte";
  import { noCredits } from "../../lib/stores/credits.svelte";
  import { dayDate } from "./text";
  import type { PeopleKind, PeopleSession } from "../../lib/types";

  // Step 3: the people found (or added) for one kind.
  let { session, kind }: { session: PeopleSession; kind: PeopleKind } = $props();
  const list = $derived(session.contacts[kind] || []);
  const lastSearch = $derived(session.searches[kind]);
  const againLabel = $derived(noCredits() ? "No credits left" : "Search again · 1 credit");
  const countryNote = $derived(!!lastSearch && !lastSearch.country_filtered && list.some(p => p.source === "prospeo"));
</script>

<PeopleHeader listing={session.listing} logo={session.site?.logo_url} />
<div class="fp-results-head">
  <a class="fp-back link" href={`#people?listing=${encodeURIComponent(session.listing.id)}`}><Icon name="back" />Back</a>
  <p class="fp-count-line">{list.length} {nounFor(kind, list.length)} at {session.company}</p>
  <button type="button" class="btn btn-quiet fp-again" class:loading={people.searching === kind} title="Run the search again on Prospeo"
    disabled={noCredits() || !session.configured || people.searching === kind} onclick={() => search(kind)}>
    {lastSearch || noCredits() ? againLabel : "Search Prospeo · 1 credit"}</button>
</div>
<p class="form-msg {people.resultsMsg.kind}" role="status" id="fp-results-msg">{people.resultsMsg.text}</p>
{#if lastSearch?.stale}
  <p class="fp-stale">This list is from {dayDate(lastSearch.searched_at)}. People change roles and companies, so search again for a fresh one before reaching out.</p>
{/if}
{#if countryNote}<p class="muted fp-note">No one matched in this job's country, so these are from other locations.</p>{/if}
{#if list.length}
  <div class="fp-people">
    {#each list as c (c.person_id)}<Person {kind} contact={c} />{/each}
  </div>
{:else if lastSearch}
  <section class="fp-panel fp-noone">
    <h2>No one found</h2>
    <p class="muted">Prospeo has no matching people at {session.site?.domain || session.company}. Check the website is right, or search LinkedIn yourself.</p>
    <SiteLine />
    <FreeLinks {session} groups={[kind === "recruiters" ? "recruiters" : "team", "google"]} panel={false} />
  </section>
{/if}
<AddPerson {kind} />
{#if !list.length && !lastSearch}
  <FreeLinks {session} groups={[kind === "recruiters" ? "recruiters" : "team", "google", "alumni"]} />
{/if}
