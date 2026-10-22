<script lang="ts">
  import Icon, { type IconName } from "./Icon.svelte";
  import { route, type View } from "../stores/router.svelte";
  import { meta } from "../stores/meta.svelte";
  import { tracker } from "../stores/tracker.svelte";
  import { profile } from "../stores/profile.svelte";
  import { monogram } from "../format";

  type Item = { view: View; label: string; icon: IconName; count?: () => string; warn?: () => boolean };
  const groups: [string, Item[]][] = [
    ["Internships", [
      { view: "board", label: "Internship board", icon: "board" },
      { view: "matches", label: "Best matches", icon: "star" },
      { view: "companies", label: "Companies", icon: "companies", count: () => (meta.data?.boards.enabled ? meta.data.boards.enabled.toLocaleString() : "") },
    ]],
    ["Tracker", [
      { view: "tracker", label: "Tracker", icon: "tracker", count: () => (tracker.items.length ? String(tracker.items.length) : "") },
    ]],
    ["Internship tools", [
      { view: "resume", label: "Resume tailor", icon: "resume" },
      { view: "cover", label: "Cover letter", icon: "pen" },
      { view: "people", label: "Find people", icon: "people" },
    ]],
    ["Account", [
      { view: "profile", label: "My profile", icon: "profile", warn: () => !!profile.data && !profile.data.has_resume },
    ]],
  ];
  const countIds: Partial<Record<View, string>> = { companies: "companies-count", tracker: "tracker-count" };
  const name = $derived(profile.data?.data?.name?.trim() || "");
</script>

<aside class="sidebar" id="sidebar" aria-label="Main">
  <a class="brand" href="#board">
    <svg class="mark" viewBox="0 0 32 32" aria-hidden="true"><rect width="32" height="32" rx="8"/><path d="M9 21.5c2 2 4.3 3 7 3s5-1 7-3M16 8v16M12 12h8"/></svg>
    <span class="brand-text">Intern Board</span>
  </a>
  <nav class="nav">
    {#each groups as [title, items] (title)}
      <p class="nav-label">{title}</p>
      {#each items as item (item.view)}
        <a href={`#${item.view}`} aria-current={route.view === item.view ? "page" : undefined}>
          <Icon name={item.icon} /><span>{item.label}</span>
          {#if item.count}<span id={countIds[item.view]} class="count">{item.count()}</span>{/if}
          {#if item.warn}<span id="profile-dot" class="count count-warn" hidden={!item.warn()}>Set up</span>{/if}
        </a>
      {/each}
    {/each}
  </nav>
  <div class="sidebar-foot">
    <div class="who">
      <span class="avatar" id="who-avatar" aria-hidden="true">{name ? monogram(name) : "?"}</span>
      <span class="who-text"><strong id="who-name">{profile.data ? name || "Set up your profile" : "Your profile"}</strong><a class="who-link" href="#profile">My profile</a></span>
    </div>
  </div>
</aside>
