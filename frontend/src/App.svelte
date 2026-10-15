<script lang="ts">
  import { onMount } from "svelte";
  import Icon from "./lib/components/Icon.svelte";
  import Sidebar from "./lib/components/Sidebar.svelte";
  import Toast from "./lib/components/Toast.svelte";
  import Placeholder from "./pages/Placeholder.svelte";
  import FindPeople from "./pages/people/FindPeople.svelte";
  import Integrations from "./pages/profile/Integrations.svelte";
  import { route, startRouter, VIEWS, type View } from "./lib/stores/router.svelte";
  import { loadMeta } from "./lib/stores/meta.svelte";
  import { loadTracker } from "./lib/stores/tracker.svelte";
  import { profile, loadProfile } from "./lib/stores/profile.svelte";

  const TITLES: Record<View, string> = {
    board: "Internship board", matches: "Best matches", tracker: "Applications", companies: "Company watchlist",
    profile: "Your profile", resume: "Resume tailor", cover: "Cover letter", people: "Find People",
  };
  const section = $derived(VIEWS[route.view]);

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
    const stop = startRouter();
    let timer: ReturnType<typeof setInterval> | undefined;
    (async () => {
      let m = await loadMeta();
      // On the very first run the server is still importing; wait for it.
      while (!m.last_refresh && !m.last_error) {
        await new Promise(r => setTimeout(r, 2000));
        m = await loadMeta();
      }
      await loadTracker();
      loadProfile().catch(() => {});
      timer = setInterval(() => loadMeta().catch(() => {}), 60 * 1000);
    })().catch(() => {});
    return () => { stop(); clearInterval(timer); };
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
  <section id="board-view" class="view" aria-label="Internship board" hidden={section !== "board"}>
    <Placeholder title={TITLES[route.view === "matches" ? "matches" : "board"]} view={route.view === "matches" ? "matches" : "board"} />
  </section>
  <section id="tracker-view" class="view" aria-label="Tracker" hidden={section !== "tracker"}>
    <Placeholder title={TITLES.tracker} view="tracker" />
  </section>
  <section id="companies-view" class="view" aria-label="Companies" hidden={section !== "companies"}>
    <Placeholder title={TITLES.companies} view="companies" />
  </section>
  <section id="tool-view" class="view" aria-label="Internship tools" hidden={section !== "tool"}>
    <Placeholder title={TITLES[route.view === "cover" ? "cover" : "resume"]} view={route.view === "cover" ? "cover" : "resume"} />
  </section>
  <section id="people-view" class="view" aria-label="Find people" hidden={section !== "people"}>
    <FindPeople />
  </section>
  <section id="profile-view" class="view" aria-label="Your profile" hidden={section !== "profile"}>
    <Placeholder title={TITLES.profile} view="profile" />
    {#if section === "profile"}<div id="profile-extras"><Integrations /></div>{/if}
  </section>
</main>

<Toast />
