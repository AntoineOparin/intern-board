<script lang="ts">
  // Experience and project points: one fact each, said in several phrasings, so tailoring has more
  // to pick from. The draft and Claude's suggestions live in the profile store, so leaving the page
  // keeps them. Nothing reaches the server until Save; Claude only runs from the Suggest button.
  import { untrack } from "svelte";
  import Icon from "../../lib/components/Icon.svelte";
  import * as api from "../../lib/api";
  import { profile, editor, suggestions, suggestPhrasings } from "../../lib/stores/profile.svelte";
  import { MAX_PHRASINGS, SECTIONS, entryTitle, newEntry, newId, splitList, withPoints, type Entry, type Section } from "../../lib/points";
  import type { ExperienceEntry, Point, Profile, ProfileData, ProjectEntry } from "../../lib/types";

  let saving = $state(false);
  let msg = $state({ text: "", kind: "" });
  let shown = ""; // the profile version the draft was built from
  let detailsOpen = $state(new Set<string>()); // entries whose facts form is open (new ones start open)

  // A fresh profile replaces the draft, unless there are unsaved edits to protect.
  $effect(() => {
    const p = profile.data;
    if (!p) return;
    const key = `${p.version}:${p.updated_at}`;
    untrack(() => {
      if (key === shown || editor.dirty) return;
      shown = key;
      editor.draft = withPoints($state.snapshot(p.data) as ProfileData);
    });
  });

  function touch() {
    editor.dirty = true;
    if (msg.kind !== "busy") msg = { text: "Unsaved changes", kind: "" };
  }

  async function save(): Promise<boolean> {
    if (!editor.draft) return false;
    saving = true;
    msg = { text: "Saving…", kind: "busy" };
    try {
      const saved = await api.updateProfile({ data: $state.snapshot(editor.draft) as ProfileData });
      editor.dirty = false;
      shown = ""; // take the server's copy (ids filled in, blanks dropped)
      profile.data = { ...profile.data!, ...saved } as Profile;
      msg = { text: "Saved.", kind: "ok" };
      return true;
    } catch (err) {
      msg = { text: (err as Error).message, kind: "error" };
      return false;
    } finally {
      saving = false;
    }
  }

  function discard() {
    if (!profile.data) return;
    editor.dirty = false;
    editor.draft = withPoints($state.snapshot(profile.data.data) as ProfileData);
    msg = { text: "", kind: "" };
  }

  // ---------- points and phrasings (edits touch the draft only) ----------
  function addPoint(entry: Entry) { entry.points.push({ id: newId("p"), phrasings: [""] }); touch(); }
  function deletePoint(entry: Entry, i: number) { suggestions.delete(entry.points[i].id); entry.points.splice(i, 1); touch(); }
  function move(entry: Entry, i: number, by: number) { const [pt] = entry.points.splice(i, 1); entry.points.splice(i + by, 0, pt); touch(); }
  function addPhrasing(point: Point) { point.phrasings.push(""); touch(); }
  function removePhrasing(point: Point, j: number) { point.phrasings.splice(j, 1); touch(); }
  function makePrimary(point: Point, j: number) { const [s] = point.phrasings.splice(j, 1); point.phrasings.unshift(s); touch(); }
  function removeEntry(section: Section, i: number) {
    const entries = editor.draft?.[section];
    if (!entries) return;
    if (!confirm(`Remove ${entryTitle(section, entries[i])} and all its points from your profile?`)) return;
    for (const pt of entries[i].points) suggestions.delete(pt.id);
    entries.splice(i, 1);
    touch();
  }

  // ---------- entries ----------
  function addEntry(section: Section) {
    if (!editor.draft) return;
    const entry = newEntry(section);
    ((editor.draft[section] ??= []) as Entry[]).push(entry);
    toggleDetails(entry.id, true);
    touch();
  }
  function toggleDetails(id: string, open = !detailsOpen.has(id)) {
    const next = new Set(detailsOpen);
    if (open) next.add(id); else next.delete(id);
    detailsOpen = next;
  }
  const exp = (entry: Entry) => entry as ExperienceEntry;
  const proj = (entry: Entry) => entry as ProjectEntry;

  // ---------- suggestions ----------
  // Claude reads the saved profile, so unsaved edits are saved first (the click covers both).
  async function suggest(point: Point) {
    if (editor.dirty && !(await save())) return;
    suggestPhrasings(point.id);
  }
  function keep(point: Point, text: string) { point.phrasings.push(text); dropSuggestion(point.id, text); touch(); }
  function dropSuggestion(id: string, text: string) {
    const s = suggestions.get(id);
    if (!s) return;
    const items = s.items.filter(x => x !== text);
    if (items.length) suggestions.set(id, { ...s, items });
    else suggestions.delete(id);
  }
  const canSuggest = (point: Point) =>
    !saving && point.phrasings.length < MAX_PHRASINGS && !!point.phrasings[0]?.trim() && suggestions.get(point.id)?.status !== "running";
</script>

<section class="panel points-panel" id="points-editor" aria-labelledby="points-title">
  <h2 class="panel-title" id="points-title">Experience and project points</h2>
  <p class="muted pe-lede">Each point is one fact. Give it several phrasings and tailoring picks the one that fits each job; only one phrasing per point ends up on a resume. <strong>Suggest variations</strong> asks Claude for other ways to say the same thing, and nothing is added until you keep it.</p>

  {#if editor.draft}
    {#each SECTIONS as [section, label] (section)}
      {@const entries = editor.draft[section] ?? []}
      <div class="pe-section-head">
        <h3 class="pe-section">{label}</h3>
        <button type="button" class="btn btn-quiet pe-small" onclick={() => addEntry(section)}>{section === "experience" ? "Add experience" : "Add project"}</button>
      </div>
      {#if !entries.length}<p class="muted pe-empty">None in your profile.</p>{/if}
      {#each entries as entry, ei (entry.id)}
        {@const title = entryTitle(section, entry)}
        {@const open = detailsOpen.has(entry.id)}
        <article class="pe-entry" aria-label={title}>
          <header class="pe-entry-head">
            <div>
              <strong>{title}</strong>
              {#if entry.missing_from_resume}<span class="tag warn">Not on your latest resume</span>{/if}
            </div>
            <div class="pe-actions">
              <button type="button" class="btn btn-quiet pe-small" aria-expanded={open} onclick={() => toggleDetails(entry.id)}>{open ? "Hide details" : "Edit details"}</button>
              <button type="button" class="btn btn-quiet pe-small" onclick={() => addPoint(entry)}>Add point</button>
              <button type="button" class="btn btn-danger-quiet pe-small" onclick={() => removeEntry(section, ei)}>Remove entry</button>
            </div>
          </header>
          {#if open}
            <div class="pe-details">
              {#if section === "experience"}
                {@const e = exp(entry)}
                <label class="field"><span>Organization</span><input bind:value={e.organization} oninput={touch} placeholder="Harbourview Labs"></label>
                <label class="field"><span>Role</span><input bind:value={e.role} oninput={touch} placeholder="Software Developer Intern"></label>
                <label class="field"><span>Location</span><input bind:value={e.location} oninput={touch} placeholder="Toronto, ON"></label>
                <label class="field"><span>Start</span><input bind:value={e.start} oninput={touch} placeholder="May 2025"></label>
                <label class="field"><span>End</span><input bind:value={e.end} oninput={touch} placeholder="Aug 2025 or Present"></label>
              {:else}
                {@const p = proj(entry)}
                <label class="field"><span>Name</span><input bind:value={p.name} oninput={touch} placeholder="Trailmap"></label>
                <label class="field pe-wide"><span>Tech <em>(comma-separated)</em></span>
                  <input value={p.tech.join(", ")} oninput={touch} onchange={e => { p.tech = splitList(e.currentTarget.value); }} placeholder="TypeScript, Go"></label>
                <label class="field"><span>Link</span><input bind:value={p.link} oninput={touch} placeholder="github.com/you/trailmap"></label>
                <label class="field"><span>Date</span><input bind:value={p.date} oninput={touch} placeholder="2024"></label>
              {/if}
            </div>
          {/if}
          {#if !entry.points.length}<p class="muted pe-empty">No points yet. Add one so tailoring has something to pick from.</p>{/if}
          <ol class="pe-points">
            {#each entry.points as point, pi (point.id)}
              {@const s = suggestions.get(point.id)}
              <li class="pe-point">
                <span class="pe-point-label">Point {pi + 1}{point.phrasings.length > 1 ? ` · ${point.phrasings.length} phrasings` : ""}</span>
                <ol class="pe-phrasings">
                  {#each point.phrasings as _, j (j)}
                    <li class="pe-phrasing">
                      <textarea rows="2" aria-label="Phrasing {j + 1} of point {pi + 1}, {title}" placeholder={j === 0 ? "What you did, with the real numbers" : "Another way to say the same thing"}
                        bind:value={point.phrasings[j]} oninput={touch}></textarea>
                      <div class="pe-phrasing-actions">
                        {#if j === 0}<span class="tag">Primary</span>{:else}<button type="button" class="link" onclick={() => makePrimary(point, j)}>Make primary</button>{/if}
                        <button type="button" class="icon-btn" aria-label="Remove phrasing {j + 1} of point {pi + 1}" disabled={point.phrasings.length === 1} onclick={() => removePhrasing(point, j)}><Icon name="close" /></button>
                      </div>
                    </li>
                  {/each}
                </ol>
                <div class="pe-point-actions">
                  <button type="button" class="btn btn-quiet pe-small" disabled={point.phrasings.length >= MAX_PHRASINGS} onclick={() => addPhrasing(point)}>Add phrasing</button>
                  <button type="button" class="btn btn-quiet pe-small" disabled={!canSuggest(point)} onclick={() => suggest(point)}>Suggest variations</button>
                  <span class="pe-spacer"></span>
                  <button type="button" class="icon-btn" aria-label="Move point {pi + 1} up" disabled={pi === 0} onclick={() => move(entry, pi, -1)}>↑</button>
                  <button type="button" class="icon-btn" aria-label="Move point {pi + 1} down" disabled={pi === entry.points.length - 1} onclick={() => move(entry, pi, 1)}>↓</button>
                  <button type="button" class="btn btn-danger-quiet pe-small" onclick={() => deletePoint(entry, pi)}>Delete point</button>
                </div>
                {#if s}
                  <div class="pe-suggest">
                    {#if s.status === "running"}
                      <p class="form-msg busy" role="status">Asking Claude for other phrasings… {s.seconds}s</p>
                    {:else}
                      {#if s.status === "error"}
                        <p class="form-msg error" role="status">{s.error}</p>
                      {:else if !s.items.length}
                        <p class="form-msg" role="status">Claude's suggestions changed the facts or repeated your phrasings, so none were kept. Try again.</p>
                      {:else}
                        <ul aria-label="Suggested phrasings for point {pi + 1}">
                          {#each s.items as text (text)}
                            <li>
                              <p>{text}</p>
                              <div class="pe-suggest-actions">
                                <button type="button" class="btn btn-primary pe-small" disabled={point.phrasings.length >= MAX_PHRASINGS} onclick={() => keep(point, text)}>Keep</button>
                                <button type="button" class="btn btn-quiet pe-small" onclick={() => dropSuggestion(point.id, text)}>Discard</button>
                              </div>
                            </li>
                          {/each}
                        </ul>
                      {/if}
                      <div class="pe-suggest-foot">
                        <span>{s.items.length ? `${s.dropped ? `${s.dropped} left out for changing the facts. ` : ""}Kept phrasings are saved with your changes.` : ""}</span>
                        <button type="button" class="link" onclick={() => suggestions.delete(point.id)}>{s.items.length ? "Discard all" : "Dismiss"}</button>
                      </div>
                    {/if}
                  </div>
                {/if}
              </li>
            {/each}
          </ol>
        </article>
      {/each}
    {/each}
    <div class="pe-foot">
      <span id="points-msg" class="form-msg {msg.kind}" role="status">{msg.text}</span>
      <button type="button" class="btn btn-quiet" id="points-discard" disabled={!editor.dirty || saving} onclick={discard}>Discard changes</button>
      <button type="button" class="btn btn-primary" id="points-save" disabled={!editor.dirty || saving} onclick={save}>Save changes</button>
    </div>
  {/if}
</section>
