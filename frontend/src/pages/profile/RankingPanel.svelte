<script lang="ts">
  import { onMount } from "svelte";
  import { ago } from "../../lib/format";
  import { ranking, refreshStatus, rankRun, rankWithClaude, recomputeQuick, STRONG, OK } from "../../lib/stores/ranking.svelte";
  import { loadListings } from "../../lib/stores/board.svelte";
  import type { RankingStatus } from "../../lib/types";

  const s = $derived(ranking.status);
  const busy = $derived(!!rankRun.running);

  function statusText(s: RankingStatus) {
    if (!s.has_profile) return "Add your resume above to score listings.";
    const parts = [`${s.quick.toLocaleString()} listing${s.quick === 1 ? "" : "s"} with a keyword score`];
    parts.push(s.claude ? `${s.claude} ranked by Claude ${ago(s.claude_at)}` : "none ranked by Claude yet");
    let text = parts.join(", ") + ".";
    if (s.quick_at) text += ` Keyword scores updated ${ago(s.quick_at)}.`;
    if (s.unscored > 0) text += ` ${s.unscored.toLocaleString()} not scored yet.`;
    return text;
  }

  // The profile may have just changed; the status call fills in scores for the new version.
  onMount(() => {
    const before = ranking.status?.profile_version;
    refreshStatus().then(st => { if (st && (st.computed || st.profile_version !== before)) loadListings(true); });
  });
</script>

<section class="panel rank-panel" aria-labelledby="rank-title">
  <h2 class="panel-title" id="rank-title">Ranking</h2>
  <p class="rank-status" role="status">{s ? statusText(s) : "Loading…"}</p>
  <div class="rank-actions">
    <button type="button" class="btn btn-primary" data-rank-claude disabled={!s?.has_profile || busy} onclick={rankWithClaude}>
      Rank top 40 with Claude</button>
    <button type="button" class="btn btn-quiet" data-rank-quick disabled={!s?.has_profile || busy} onclick={recomputeQuick}>
      Recompute keyword scores</button>
    <span class="form-msg {rankRun.msg.kind}" data-rank-msg role="status" aria-live="polite">{rankRun.msg.text}</span>
  </div>
  <dl class="rank-explain">
    <dt>Keyword scores</dt>
    <dd>Every listing gets one instantly from its title, category, terms, locations and degree against your
      skills and preferences. They are rough: a title that doesn't name a skill scores lower.</dd>
    <dt>Claude scores <svg class="match-claude" viewBox="0 0 12 12" aria-hidden="true"><path d="M6 1.2 7.2 4.8 10.8 6 7.2 7.2 6 10.8 4.8 7.2 1.2 6 4.8 4.8Z"/></svg></dt>
    <dd>Claude reads your full profile and rescores the 40 best keyword matches that it hasn't scored yet,
      with a one-sentence reason. It sees titles and details, not full job descriptions. Takes about a minute
      and uses your Claude plan. Run it again to go further down the list.</dd>
  </dl>
  <p class="rank-tiers muted">Badges on the board:
    <span class="match-badge strong static"><span class="num">{STRONG}+</span></span> strong
    <span class="match-badge ok static"><span class="num">{OK}+</span></span> possible
    <span class="match-badge weak static"><span class="num">&lt;{OK}</span></span> weak.
    Choose Sort: Best match to see the best first.</p>
</section>
