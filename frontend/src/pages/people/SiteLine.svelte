<script lang="ts">
  import { people, saveSite } from "../../lib/stores/people.svelte";
  // "Searching people at stripe.com." with a way to correct the company's website.
  const site = $derived(people.session?.site ?? null);
  let editing = $state(false);
  let value = $state("");
  let input: HTMLInputElement | undefined = $state();

  async function edit() {
    editing = true;
    value = site?.domain || "";
    await Promise.resolve();
    input?.focus();
  }
</script>

<p class="fp-site muted">
  {#if site}Searching people at <strong>{site.domain}</strong>{#if site.prospeo_name}{" "}({site.prospeo_name}){/if}.{:else}The company's website is looked up on the first search.{/if}
  <button type="button" class="link fp-change" onclick={edit}>{site ? "Wrong company? Change website" : "Set website"}</button>
  <span class="fp-site-form" hidden={!editing}><input type="text" placeholder="stripe.com" aria-label="Company website" bind:value bind:this={input} />
    <button type="button" class="btn btn-quiet fp-site-save" onclick={async () => { await saveSite(value.trim()); editing = false; }}>Save</button></span>
</p>
