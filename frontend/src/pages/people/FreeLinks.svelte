<script lang="ts">
  import type { LinkGroup, PeopleSession } from "../../lib/types";
  // LinkedIn and Google searches that cost nothing.
  let { session, groups, panel = true }: { session: PeopleSession; groups: LinkGroup["id"][]; panel?: boolean } = $props();
  const shown = $derived(session.links.groups.filter(g => groups.includes(g.id) && g.items.length));
</script>

{#snippet links()}
  {#each shown as g (g.id)}
    <h3>{g.title}</h3>
    <ul class="fp-links">
      {#each g.items as i (i.url)}
        <li><a class="link" href={i.url} target="_blank" rel="noopener">{i.label} ↗</a> <span class="muted">{i.hint}</span></li>
      {/each}
    </ul>
  {/each}
{/snippet}

{#if panel}
  <section class="fp-panel fp-free">
    <h2>Free searches</h2>
    <p class="muted">These open LinkedIn or Google in a new tab and cost nothing. Add the people you find with “add someone yourself”.</p>
    {@render links()}
  </section>
{:else}
  {@render links()}
{/if}
