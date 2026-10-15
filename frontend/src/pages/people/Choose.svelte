<script lang="ts">
  import Icon, { type IconName } from "../../lib/components/Icon.svelte";
  import PeopleHeader from "./PeopleHeader.svelte";
  import SiteLine from "./SiteLine.svelte";
  import FreeLinks from "./FreeLinks.svelte";
  import { people, choose } from "../../lib/stores/people.svelte";
  import { credits, noCredits, ready } from "../../lib/stores/credits.svelte";
  import { ago } from "../../lib/format";
  import { renewText, shortDate } from "./text";
  import type { PeopleKind, PeopleSession } from "../../lib/types";

  // Step 2: recruiters or coffee chats.
  let { session }: { session: PeopleSession } = $props();
  const l = $derived(session.listing);
  const renews = $derived(ready(credits.account) ? credits.account.renews : null);

  type Card = { kind: PeopleKind; icon: IconName; title: string; text: string };
  const cards = $derived<Card[]>([
    { kind: "recruiters", icon: "badge", title: "Recruiters", text: "University and technical recruiters who hire interns." },
    { kind: "team", icon: "coffee", title: "Coffee chats", text: `${session.team_label} on the team you're applying to.` },
  ]);

  function card(kind: PeopleKind) {
    const done = session.searches[kind], saved = session.contacts[kind].length;
    const usable = !!(saved || done || (session.configured && !noCredits()));
    const foot = done ? `${saved} saved · searched ${ago(done.searched_at)}${done.stale ? " · may be out of date" : ""}`
      : saved ? `${saved} added by you`
      : noCredits() ? `No credits left · ${renewText()}` : "Uses 1 Prospeo credit";
    return { usable, foot, warn: !!done?.stale || (!usable && noCredits()) };
  }
</script>

<PeopleHeader listing={l} logo={session.site?.logo_url} />
<a class="fp-back link" href="#people"><Icon name="back" />All tracked jobs</a>
<section class="fp-center">
  <h2>Who are you looking for at {session.company}?</h2>
  <p class="muted">Pick one before each search.</p>
  {#if !session.configured}
    <p class="form-msg error">Add your Prospeo API key under <a class="link" href="#profile">My profile → Integrations</a> to search.</p>
  {:else if noCredits()}
    <p class="fp-out">You're out of Prospeo credits {renews ? `until ${shortDate(renews)}` : "until they renew"}. People you've already found still work. Use the free searches below, then add who you find.</p>
  {/if}
  <div class="fp-choices">
    {#each cards as c (c.kind)}
      {@const info = card(c.kind)}
      <div class="fp-choice-wrap">
        <button type="button" class="fp-choice" class:loading={people.searching === c.kind} data-kind={c.kind}
          disabled={!info.usable || people.searching === c.kind} onclick={() => choose(c.kind)}>
          <span class="fp-choice-icon"><Icon name={c.icon} /></span>
          <strong>{c.title}</strong>
          <span class="fp-choice-text">{c.text}</span>
          <span class="fp-choice-foot {info.warn ? 'warn' : 'muted'}">{info.foot}</span>
        </button>
        <a class="link fp-add-link" href={`#people?listing=${encodeURIComponent(l.id)}&kind=${c.kind}&add=1`}>or add someone yourself</a>
      </div>
    {/each}
  </div>
  <SiteLine />
  <p class="form-msg {people.chooseMsg.kind}" role="status" id="fp-choose-msg">{people.chooseMsg.text}</p>
</section>
{#if !session.configured || noCredits()}
  <FreeLinks {session} groups={["recruiters", "team", "google"]} />
{/if}
