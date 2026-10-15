<script lang="ts">
  import { untrack } from "svelte";
  import * as api from "../../lib/api";
  import { ago } from "../../lib/format";
  import { companies, loadCompanies } from "../../lib/stores/companies.svelte";
  import { loadMeta } from "../../lib/stores/meta.svelte";
  import { loadListings } from "../../lib/stores/board.svelte";
  import type { Company } from "../../lib/types";

  let q = $state("");
  let show = $state<"hiring" | "all" | "off">("hiring");

  // Which rows show is worked out when the filter or the list changes, not when a switch is
  // flipped, so a board you just turned off stays in view until you change the filter.
  let rows = $state<Company[]>([]);
  function filterRows() {
    const term = q.trim().toLowerCase();
    rows = companies.items.filter(c =>
      (show === "all" || (show === "hiring" ? c.enabled && c.listings > 0 : !c.enabled)) &&
      (!term || c.name.toLowerCase().includes(term) || c.token.includes(term)));
  }
  $effect(() => { void companies.version; untrack(filterRows); });
  const enabled = $derived(companies.items.filter(c => c.enabled).length);

  async function toggle(c: Company, e: Event) {
    const input = e.currentTarget as HTMLInputElement;
    const on = input.checked;
    try {
      await api.setCompanyEnabled(c.platform, c.token, on);
      c.enabled = on ? 1 : 0;
      if (!on) c.listings = 0;
      loadMeta().catch(() => {});
      loadListings(true);
    } catch {
      input.checked = !on;
    }
  }

  // ---------- add a board by link ----------
  let url = $state("");
  let name = $state("");
  let adding = $state(false);
  let invalid = $state(false);
  let msg = $state({ text: "", kind: "" });
  let urlInput: HTMLInputElement;

  async function add(e: SubmitEvent) {
    e.preventDefault();
    const link = url.trim();
    invalid = false;
    msg = { text: "", kind: "" };
    if (link.length < 3) {
      invalid = true;
      msg = { text: "Paste a link to the company's Greenhouse, Lever or Ashby job board.", kind: "error" };
      urlInput.focus();
      return;
    }
    adding = true;
    try {
      const c = await api.addCompany(link, name.trim() || null, { quiet: true });
      msg = { text: `Added ${c.name}: ${c.kept} matching internship${c.kept === 1 ? "" : "s"} out of ${c.jobs_total} open jobs.`, kind: "ok" };
      url = "";
      name = "";
      await Promise.all([loadCompanies(), loadMeta(), loadListings(true)]);
    } catch (err) {
      invalid = true;
      msg = { text: (err as Error).message, kind: "error" };
    } finally {
      adding = false;
    }
  }

  function status(c: Company) {
    if (c.last_status === "not_found") return { err: true, text: "Board not found", title: "" };
    if (c.last_status === "error") return { err: true, text: "Last check failed", title: c.last_error ?? "" };
    return { err: false, text: c.last_checked ? ago(c.last_checked) : "Not yet", title: "" };
  }
</script>

<div class="intro intro-compact">
  <div>
    <h1 id="companies-heading">Company watchlist</h1>
    <p class="lede">These Greenhouse, Lever and Ashby job boards are read directly. Boards with internships are checked hourly, the rest every 6 hours.</p>
  </div>
</div>

<form id="add-company" class="add-company" class:invalid autocomplete="off" novalidate onsubmit={add}>
  <label class="field grow">
    <span>Job board link</span>
    <input name="url" type="text" required placeholder="jobs.lever.co/company or job-boards.greenhouse.io/company" bind:value={url} bind:this={urlInput}>
  </label>
  <label class="field">
    <span>Name <em>(optional)</em></span>
    <input name="name" type="text" placeholder="Company name" bind:value={name}>
  </label>
  <button class="btn btn-primary" type="submit" disabled={adding}>{adding ? "Checking board…" : "Add company"}</button>
  <p id="add-company-msg" class="form-msg {msg.kind}" role="status">{msg.text}</p>
</form>

<div class="companies-tools">
  <label class="search small">
    <svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="6.5"/><path d="m20 20-4.2-4.2"/></svg>
    <input id="company-search" type="search" placeholder="Filter companies" aria-label="Filter companies" bind:value={q} oninput={filterRows}>
  </label>
  <div class="segmented" role="radiogroup" aria-label="Show">
    <label><input type="radio" name="company-show" value="hiring" bind:group={show} onchange={filterRows}><span>With internships</span></label>
    <label><input type="radio" name="company-show" value="all" bind:group={show} onchange={filterRows}><span>All</span></label>
    <label><input type="radio" name="company-show" value="off" bind:group={show} onchange={filterRows}><span>Turned off</span></label>
  </div>
  <span id="company-summary" class="muted">{companies.loaded ? `Watching ${enabled.toLocaleString()} of ${companies.items.length.toLocaleString()} boards` : ""}</span>
</div>
<div class="table-wrap">
  <table class="companies">
    <thead>
      <tr><th scope="col">Company</th><th scope="col">Board</th><th scope="col" class="r">Internships</th><th scope="col" class="r">All jobs</th><th scope="col">Last checked</th><th scope="col" class="r">Watching</th></tr>
    </thead>
    <tbody id="company-rows">
      {#each rows as c (`${c.platform}/${c.token}`)}
        {@const st = status(c)}
        <tr class:off={!c.enabled}>
          <td class="c-name"><a href={c.board_url} target="_blank" rel="noopener">{c.name}</a>{#if c.origin === "manual"}<span class="manual">added by you</span>{/if}</td>
          <td class="platform">{c.platform}</td>
          <td class="r">{c.listings || "–"}</td>
          <td class="r">{c.jobs_total ?? "–"}</td>
          <td class="muted">{#if st.err}<span class="status-err" title={st.title || undefined}>{st.text}</span>{:else}{st.text}{/if}</td>
          <td class="r"><label class="switch" title={`${c.enabled ? "Stop" : "Start"} checking this board`}>
            <input type="checkbox" checked={!!c.enabled} aria-label={`Watch ${c.name}`} onchange={e => toggle(c, e)}><span></span></label></td>
        </tr>
      {:else}
        {#if companies.loaded}<tr><td colspan="6" class="empty">No companies match.</td></tr>{/if}
      {/each}
    </tbody>
  </table>
</div>
