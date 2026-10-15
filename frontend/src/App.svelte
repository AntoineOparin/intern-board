<script lang="ts">
  import { onMount, untrack } from "svelte";
  import Icon from "./lib/components/Icon.svelte";
  import Sidebar from "./lib/components/Sidebar.svelte";
  import Toast from "./lib/components/Toast.svelte";
  import FindPeople from "./pages/people/FindPeople.svelte";
  import Profile from "./pages/profile/Profile.svelte";
  import Companies from "./pages/companies/Companies.svelte";
  import { companies, loadCompanies } from "./lib/stores/companies.svelte";
  import Board from "./pages/board/Board.svelte";
  import Drawer from "./lib/components/Drawer.svelte";
  import Tracker from "./pages/tracker/Tracker.svelte";
  import ToolPage from "./pages/documents/ToolPage.svelte";
  import { board, filtersChanged, loadListings, updateNewCount } from "./lib/stores/board.svelte";
  import { filters, restoreFilters } from "./lib/stores/filters.svelte";
  import { refreshStatus, followRunningJob } from "./lib/stores/ranking.svelte";
  import { visitBaseline, trackActivity } from "./lib/visits";
  import { route, startRouter, VIEWS } from "./lib/stores/router.svelte";
  import { loadMeta } from "./lib/stores/meta.svelte";
  import { loadTracker } from "./lib/stores/tracker.svelte";
  import { profile, loadProfile } from "./lib/stores/profile.svelte";

  // Before anything renders: the "new since last visit" baseline, saved filters, then the route.
  board.prevVisit = visitBaseline();
  restoreFilters();
  const stopRouter = startRouter();
  const section = $derived(VIEWS[route.view]);

  // "Best matches" is the board sorted by match; going back to the board restores newest first.
  $effect(() => {
    const view = route.view, previous = route.previous;
    untrack(() => {
      if (view === "matches" && filters.sort !== "match") { filters.sort = "match"; if (previous) filtersChanged(); }
      if (view === "board" && previous === "matches" && filters.sort === "match") { filters.sort = "posted"; filtersChanged(); }
    });
  });

  $effect(() => { if (route.view === "companies" && !untrack(() => companies.loaded)) loadCompanies().catch(() => {}); });

  // ---------- mobile menu ----------
  let navOpen = $state(false);
  $effect(() => { document.body.classList.toggle("nav-open", navOpen); });
  $effect(() => { void route.view; void route.params; navOpen = false; }); // navigating closes it
  const onKey = (e: KeyboardEvent) => { if (e.key === "Escape" && navOpen) navOpen = false; };

  let main: HTMLElement;
  function skip(e: MouseEvent) {
    e.preventDefault(); // keep the hash: it's the router's
    main.focus();
  }

  onMount(() => {
    const stopActivity = trackActivity();
    let timer: ReturnType<typeof setInterval> | undefined;
    // Scores for listings added since the last check are filled in by the status call.
    refreshStatus().then(s => {
      if (s?.computed && filters.sort === "match") loadListings(true);
      if (s?.running_job) followRunningJob(s.running_job); // ranking still going from an earlier visit
    });
    (async () => {
      let m = await loadMeta();
      // On the very first run the server is still importing; wait for it.
      while (!m.last_refresh && !m.last_error) {
        await new Promise(r => setTimeout(r, 2000));
        m = await loadMeta();
      }
      await loadTracker();
      loadProfile().catch(() => {});
      filtersChanged();
      updateNewCount().catch(() => {});
      timer = setInterval(() => loadMeta().catch(() => {}), 60 * 1000);
    })().catch(() => {});
    return () => { stopRouter(); stopActivity(); clearInterval(timer); };
  });
</script>

<svelte:window onkeydown={onKey} />

<a class="skip" href="#main" onclick={skip}>Skip to content</a>

<header class="mobile-bar">
  <button type="button" class="icon-btn" id="nav-open" aria-label="Open menu" aria-controls="sidebar"
    aria-expanded={navOpen} onclick={() => (navOpen = true)}><Icon name="menu" /></button>
  <span class="brand-text">Intern Board</span>
</header>

<Sidebar />
<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions (Escape closes it too) -->
<div class="scrim" id="scrim" hidden={!navOpen} onclick={() => (navOpen = false)}></div>

<main id="main" tabindex="-1" bind:this={main}>
  <section id="board-view" class="view" aria-labelledby="board-heading" hidden={section !== "board"}>
    <Board visible={section === "board"} />
  </section>
  <section id="tracker-view" class="view" aria-labelledby="tracker-heading" hidden={section !== "tracker"}>
    <Tracker />
  </section>
  <section id="companies-view" class="view" aria-labelledby="companies-heading" hidden={section !== "companies"}>
    <Companies />
  </section>
  <section id="tool-view" class="view" aria-labelledby="tool-heading" hidden={section !== "tool"}>
    {#if section === "tool"}<ToolPage view={route.view === "cover" ? "cover" : "resume"} />{/if}
  </section>
  <section id="people-view" class="view" aria-label="Find people" hidden={section !== "people"}>
    <FindPeople />
  </section>
  <section id="profile-view" class="view" aria-labelledby="profile-heading" hidden={section !== "profile"}>
    {#if section === "profile"}<Profile />{/if}
  </section>
</main>

<Drawer />
<Toast />
