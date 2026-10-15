<script lang="ts">
  import Icon from "../../lib/components/Icon.svelte";
  import DraftBox from "./DraftBox.svelte";
  import { monogram } from "../../lib/format";
  import { noCredits } from "../../lib/stores/credits.svelte";
  import { people, revealEmail, recheck, removePerson, autoRecheck } from "../../lib/stores/people.svelte";
  import { dayDate } from "./text";
  import type { Contact, PeopleKind } from "../../lib/types";

  let { kind, contact: c }: { kind: PeopleKind; contact: Contact } = $props();
  const open = $derived(people.open === c.person_id);

  $effect(() => { if (open) autoRecheck(kind, c); });

  let revealing = $state(false);
  async function reveal() {
    revealing = true;
    try { await revealEmail(kind, c.person_id); } catch { /* shown */ } finally { revealing = false; }
  }
  let checking = $state(false);
  async function check() {
    checking = true;
    try { await recheck(kind, c.person_id); } catch { /* shown */ } finally { checking = false; }
  }
  const linkedinShort = $derived(c.linkedin_url ? decodeURIComponent(c.linkedin_url.replace(/^https?:\/\/(www\.)?/, "").replace(/\/$/, "")) : "");
  const canRecheck = $derived(!!c.email && (c.recheck_free || !noCredits()));
</script>

<article class="fp-person" class:open data-person={c.person_id}>
  <button type="button" class="fp-person-head" aria-expanded={open} onclick={() => (people.open = open ? null : c.person_id)}>
    <span class="fp-avatar">{monogram(c.full_name || "?")}</span>
    <span class="fp-person-text"><strong>{c.full_name}
        {#if c.moved_to}<span class="tag danger">Now at {c.moved_to}</span>{/if}
        {#if c.source === "manual"}<span class="tag">Added by you</span>{/if}
        {#if c.new_in_role}<span class="tag" title="Prospeo saw a job change in the 3 months before this search">New in role</span>{/if}</strong>
      <span class="muted">{[c.title, c.location].filter(Boolean).join(" · ")}</span></span>
    <Icon name="chevron" class="icon fp-caret" />
  </button>
  {#if open}
    <div class="fp-person-body">
      <div class="fp-chips">
        {#if c.email && c.email_status === "NO_LONGER_VERIFIED"}
          <a class="fp-chip fp-chip-warn" href={`mailto:${c.email}`} title="Prospeo no longer verifies this address">
            <Icon name="mail" /><span>{c.email}</span><span class="fp-cost">not verified now</span></a>
        {:else if c.email}
          <a class="fp-chip" href={`mailto:${c.email}`}><Icon name="mail" /><span>{c.email}</span>
            {#if c.email_status === "VERIFIED"}<span class="fp-ok" title={`Verified by Prospeo${c.email_found_at ? ` on ${dayDate(c.email_found_at)}` : ""}`}><Icon name="check" /></span>{/if}</a>
        {:else if c.email_status === "VERIFIED" && noCredits()}
          <span class="fp-chip fp-chip-off" title="A verified email exists; it costs 1 credit to reveal"><Icon name="mail" />
            <span class="muted">Email available · no credits left</span></span>
        {:else if c.email_status === "VERIFIED"}
          <button type="button" class="fp-chip fp-reveal" data-person={c.person_id} disabled={revealing} onclick={reveal}><Icon name="mail" />
            <span>{revealing ? "Finding email…" : "Find email"}</span><span class="muted fp-cost">1 credit</span></button>
        {:else}
          <span class="fp-chip fp-chip-off"><Icon name="mail" /><span class="muted">{c.source === "manual" ? "No email added" : "No verified email"}</span></span>
        {/if}
        {#if c.linkedin_url}
          <a class="fp-chip" href={c.linkedin_url} target="_blank" rel="noopener"><Icon name="linkedin" />
            <span>{linkedinShort}</span><span class="muted">↗</span></a>
        {:else}
          <span class="fp-chip fp-chip-off"><Icon name="linkedin" /><span class="muted">No LinkedIn profile</span></span>
        {/if}
      </div>
      <div class="fp-fresh">
        {#if c.source === "manual"}
          <span class="muted">Added by you {dayDate(c.found_at)}.</span>
          <button type="button" class="link fp-remove" data-person={c.person_id} onclick={() => removePerson(kind, c.person_id)}>Remove</button>
        {:else}
          <span class="muted">{[`Found ${dayDate(c.found_at)}`, ...(c.email_found_at ? [`email checked ${dayDate(c.email_found_at)}`] : [])].join(" · ")}.</span>
          {#if canRecheck}
            <button type="button" class="link fp-recheck" data-person={c.person_id} disabled={checking} onclick={check}
              title="Checks they're still at the company and the email still works">{checking ? "Checking…" : `Re-check${c.recheck_free ? " (free)" : " · 1 credit"}`}</button>
          {/if}
        {/if}
      </div>
      <DraftBox {kind} contact={c} />
    </div>
  {/if}
</article>
