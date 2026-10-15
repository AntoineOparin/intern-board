<script lang="ts">
  import Icon from "./Icon.svelte";
  import DocsSection from "../../pages/documents/DocsSection.svelte";
  import { drawer, closeDrawer } from "../stores/drawer.svelte";
  import { tracker, updateTracked, removeTracked } from "../stores/tracker.svelte";
  import type { Status } from "../types";

  // Stage, deadline and notes for one tracked listing, plus sections from other pages.
  const item = $derived(tracker.items.find(i => i.id === drawer.id) ?? null);
  let dialog: HTMLDialogElement;
  let status = $state<Status>("saved");
  let deadline = $state("");
  let notes = $state("");
  let shownId: string | null = null;

  // Fill the form each time the panel opens (not when the tracker reloads behind it).
  $effect(() => {
    if (!item) { if (dialog?.open) dialog.close(); shownId = null; return; }
    if (shownId !== item.id) {
      shownId = item.id;
      status = item.status;
      deadline = item.deadline ?? "";
      notes = item.notes ?? "";
    }
    if (!dialog.open) dialog.showModal();
  });

  async function save(e: SubmitEvent) {
    const submitter = e.submitter as HTMLButtonElement | null;
    if (submitter?.value !== "save" || !item) return; // the close button closes as usual
    e.preventDefault(); // close only once the save worked, so a failure keeps your edits
    const id = item.id;
    try {
      await updateTracked(id, { status, deadline, notes });
      if (drawer.id === id) closeDrawer();
    } catch { /* the request showed a toast */ }
  }

  async function remove() {
    if (!item) return;
    const id = item.id;
    closeDrawer();
    try { await removeTracked(id); } catch { /* shown */ }
  }
</script>

<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_noninteractive_element_interactions (Escape closes a dialog) -->
<dialog id="drawer" class="drawer" aria-labelledby="drawer-title" bind:this={dialog}
  onclose={() => { if (!dialog.open) { shownId = null; closeDrawer(); } /* a late close event after reopening is stale */ }} onclick={e => { if (e.target === dialog) dialog.close(); }}>
  {#if item}
    <form method="dialog" id="card-form" onsubmit={save}>
      <header class="drawer-head">
        <div>
          <p id="drawer-company" class="eyebrow">{item.company}</p>
          <h2 id="drawer-title">{item.title}</h2>
          <p id="drawer-sub" class="muted">{item.locations}{item.active ? "" : " · posting closed"}</p>
        </div>
        <button value="cancel" class="icon-btn" aria-label="Close"><Icon name="close" /></button>
      </header>
      <fieldset class="field">
        <legend>Stage</legend>
        <div class="stage-picker" id="stage-picker">
          {#each tracker.statuses as s (s)}
            <label data-stage={s}><input type="radio" name="status" value={s} bind:group={status} />
              <span><span class="stage-dot"></span>{s}</span></label>
          {/each}
        </div>
      </fieldset>
      <label class="field"><span>Deadline</span><input type="date" name="deadline" bind:value={deadline} /></label>
      <label class="field"><span>Notes</span><textarea name="notes" rows="5" placeholder="Referral, recruiter name, OA date…" bind:value={notes}></textarea></label>
      <div id="drawer-extras" class="drawer-extras">
        {#key item.id}
          <DocsSection {item} />
          <section class="drawer-section">
            <h3>People</h3>
            <p class="muted">Find recruiters and people on the team at {item.company}, with emails and intro drafts.</p>
            <a class="btn btn-quiet fp-drawer-link" href={`#people?listing=${encodeURIComponent(item.id)}`} onclick={() => dialog.close()}><Icon name="people" />Find people at {item.company}</a>
          </section>
        {/key}
      </div>
      <footer class="drawer-foot">
        <button type="button" id="drawer-remove" class="btn btn-danger-quiet" onclick={remove}>Remove</button>
        <span class="spacer"></span>
        <a id="drawer-link" target="_blank" rel="noopener" class="btn btn-quiet" href={item.url}>Open posting ↗</a>
        <button value="save" class="btn btn-primary">Save</button>
      </footer>
    </form>
  {/if}
</dialog>
