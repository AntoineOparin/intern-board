<script lang="ts">
  import { monogram } from "../../lib/format";
  // A company logo from an earlier Prospeo search, or the company's initials.
  let { company, src, size = "" }: { company: string; src?: string | null; size?: "" | "sm" } = $props();
  let failed = $state(false);
</script>

{#if src && !failed}
  <img class="fp-logo {size}" {src} alt="" loading="lazy" onerror={() => (failed = true)} />
{:else}
  <span class="fp-logo fp-mono {size}" aria-hidden="true">{monogram(company)}</span>
{/if}
