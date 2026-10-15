<script lang="ts">
  import Logo from "./Logo.svelte";
  import { credits, noCredits, ready } from "../../lib/stores/credits.svelte";
  import { renewText } from "./text";
  let { listing = null, logo = null }: { listing?: { company: string; title: string } | null; logo?: string | null } = $props();

  const text = $derived.by(() => {
    const a = credits.account;
    if (!ready(a)) return "";
    if (a.empty) return `No credits left · ${renewText()}`;
    return `${a.remaining} credits left${a.low ? " · running low" : ""}`;
  });
  const cls = $derived(noCredits() ? "empty" : ready(credits.account) && credits.account.low ? "low" : "");
</script>

<header class="fp-head">
  <h1>Find People</h1>
  <div class="fp-head-right">
    <span class="fp-credits {cls}">{text}</span>
    {#if listing}<span class="fp-job"><Logo company={listing.company} src={logo} size="sm" /><span>{listing.title}</span></span>{/if}
  </div>
</header>
