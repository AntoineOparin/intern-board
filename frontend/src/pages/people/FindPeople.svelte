<script lang="ts">
  import { untrack } from "svelte";
  import PeopleHeader from "./PeopleHeader.svelte";
  import Pick from "./Pick.svelte";
  import Choose from "./Choose.svelte";
  import Results from "./Results.svelte";
  import { route } from "../../lib/stores/router.svelte";
  import { tracker } from "../../lib/stores/tracker.svelte";
  import { people, openListing, showPick, loadCredits } from "../../lib/stores/people.svelte";

  // Runs each time you arrive on (or move within) Find People, like the old IB.pages.people.
  $effect(() => {
    if (route.view !== "people") return;
    const params = route.params;
    const loaded = tracker.loaded;
    untrack(() => {
      loadCredits(); // free; keeps the count and the out-of-credits state current
      const listing = params.get("listing");
      if (!listing) { showPick(); return; }
      if (!loaded) { people.step = "blank"; return; } // tracker still loading
      openListing(listing, params.get("kind"), params.get("add") === "1");
    });
  });
</script>

{#if people.step === "pick"}
  <Pick />
{:else if people.step === "choose" && people.session}
  <Choose session={people.session} />
{:else if people.step === "results" && people.session && people.kind}
  {#key `${people.session.listing.id}|${people.kind}|${people.add}`}
    <Results session={people.session} kind={people.kind} />
  {/key}
{:else}
  <PeopleHeader />
{/if}
