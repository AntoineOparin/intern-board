<script lang="ts">
  import * as api from "../../lib/api";
  import { deadlineInfo } from "../../lib/format";
  import { tracker } from "../../lib/stores/tracker.svelte";
  import { openDrawer } from "../../lib/stores/drawer.svelte";
  import type { Status, TrackerItem } from "../../lib/types";

  // Applications by stage. Drag cards between columns, or use Alt + arrow keys on a focused card.
  const REGION_LABELS: Record<string, string> = { US: "US", CA: "Canada", REMOTE: "Remote" };
  const columns = $derived(tracker.statuses.map(s => ({
    status: s, cards: tracker.items.filter(i => i.status === s).sort((a, b) => a.position - b.position),
  })));

  function deadlineTag(deadline: string | null) {
    const d = deadlineInfo(deadline);
    if (!d) return null;
    if (d.days < 0) return { cls: "tag danger", text: `Overdue · ${d.label}` };
    if (d.days <= 3) return { cls: "tag warn", text: `Due ${d.days === 0 ? "today" : d.label}` };
    return { cls: "tag", text: `Due ${d.label}` };
  }

  // Move a card and save it; put it back if saving fails.
  async function move(item: TrackerItem, status: Status, position: number) {
    const before = { status: item.status, position: item.position };
    Object.assign(item, { status, position });
    try {
      await api.track(item.id, { status, position });
    } catch {
      Object.assign(item, before);
    }
  }

  // ---------- drag and drop ----------
  let dragId: string | null = $state(null);
  let dropOn: Status | null = $state(null);

  function ondragstart(e: DragEvent, item: TrackerItem) {
    dragId = item.id;
    e.dataTransfer!.effectAllowed = "move";
    e.dataTransfer!.setData("text/plain", item.id);
  }
  function ondragend() { dragId = null; dropOn = null; }
  function ondragover(e: DragEvent, status: Status) {
    if (!dragId) return;
    e.preventDefault();
    dropOn = status;
  }
  function ondrop(e: DragEvent, status: Status) {
    if (!dragId) return;
    e.preventDefault();
    const item = tracker.items.find(i => i.id === dragId);
    const col = (e.currentTarget as HTMLElement);
    dragId = null;
    dropOn = null;
    if (!item) return;
    // Position the card between its new neighbours, based on where it was dropped.
    const others = [...col.querySelectorAll<HTMLElement>(".card")].filter(c => c.dataset.id !== item.id);
    const after = others.findIndex(c => e.clientY < c.getBoundingClientRect().top + c.offsetHeight / 2);
    const pos = (i: number) => tracker.items.find(t => t.id === others[i].dataset.id)!.position;
    let position;
    if (!others.length) position = 0;
    else if (after === -1) position = pos(others.length - 1) + 1;
    else if (after === 0) position = pos(0) - 1;
    else position = (pos(after - 1) + pos(after)) / 2;
    move(item, status, position);
  }

  // ---------- keyboard ----------
  let announce = $state("");
  function onkeydown(e: KeyboardEvent, item: TrackerItem) {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openDrawer(item.id); return; }
    if (!e.altKey || !["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(e.key)) return;
    e.preventDefault();
    const target = e.currentTarget as HTMLElement;
    const stages = tracker.statuses;
    if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
      const s = stages[stages.indexOf(item.status) + (e.key === "ArrowLeft" ? -1 : 1)];
      if (!s) return;
      const cards = columns.find(c => c.status === s)!.cards;
      move(item, s, cards.length ? cards.at(-1)!.position + 1 : 0);
      announce = `Moved to ${s}.`;
    } else {
      const cards = columns.find(c => c.status === item.status)!.cards;
      const i = cards.indexOf(item), j = i + (e.key === "ArrowUp" ? -1 : 1);
      if (j < 0 || j >= cards.length) return;
      // Swap places with the neighbour: just past it, keeping the rest in order.
      const beyond = cards[j + (e.key === "ArrowUp" ? -1 : 1)];
      const position = beyond ? (cards[j].position + beyond.position) / 2 : cards[j].position + (e.key === "ArrowUp" ? -1 : 1);
      move(item, item.status, position);
      announce = `Moved ${e.key === "ArrowUp" ? "up" : "down"} in ${item.status}.`;
    }
    queueMicrotask(() => target.ownerDocument.querySelector<HTMLElement>(`#kanban .card[data-id="${CSS.escape(item.id)}"]`)?.focus());
  }
</script>

<div class="intro intro-compact">
  <div>
    <h1 id="tracker-heading">Applications</h1>
    <p class="lede">Drag cards between stages. Click one to add a deadline or notes.</p>
  </div>
</div>
<div id="tracker-empty" class="empty empty-panel" hidden={!tracker.loaded || tracker.items.length > 0}>
  <p class="empty-title">Nothing tracked yet</p>
  <p>Press <strong>Track</strong> on a listing to save it here. Move it along as you apply, interview and hear back.</p>
  <a class="btn btn-primary" href="#board">Browse listings</a>
</div>
<p id="kanban-help" class="sr-only">Press Enter to open. Press Alt with the left or right arrow to move to another stage, or with up or down to reorder.</p>
<p class="sr-only" role="status" aria-live="polite">{announce}</p>
<div id="kanban" class="kanban">
  {#each columns as col (col.status)}
    <section class="column" class:drop={dropOn === col.status} data-status={col.status} data-stage={col.status} aria-label={col.status}
      ondragover={e => ondragover(e, col.status)} ondrop={e => ondrop(e, col.status)}>
      <h2><span class="stage-dot"></span>{col.status}<span class="num">{col.cards.length}</span></h2>
      {#each col.cards as i (i.id)}
        {@const due = deadlineTag(i.deadline)}
        <!-- svelte-ignore a11y_no_noninteractive_tabindex, a11y_no_noninteractive_element_interactions (cards open the side panel on Enter) -->
        <article class="card" class:dragging={dragId === i.id} draggable="true" data-id={i.id} tabindex="0" aria-label={`${i.company}: ${i.title}`}
          aria-describedby="kanban-help" ondragstart={e => ondragstart(e, i)} {ondragend} onclick={() => openDrawer(i.id)} onkeydown={e => onkeydown(e, i)}>
          <div class="c-company">{i.company}</div>
          <div class="c-title">{i.title}</div>
          <div class="c-tags">
            {#if due}<span class={due.cls}>{due.text}</span>{/if}
            {#if !i.active}<span class="tag danger">Posting closed</span>{/if}
            {#each i.regions as r (r)}<span class="tag">{REGION_LABELS[r] ?? r}</span>{/each}
          </div>
          {#if i.notes}<div class="c-notes">{i.notes}</div>{/if}
        </article>
      {:else}
        <div class="col-empty">Drop cards here</div>
      {/each}
    </section>
  {/each}
</div>
