<script lang="ts">
  import Icon from "../../lib/components/Icon.svelte";
  import { toast } from "../../lib/stores/toast.svelte";
  import { noteLimit } from "../../lib/stores/profile.svelte";
  import { people, drafts, writing, draftErrors, draftKey, channelFor, writeDraft, saveDraft } from "../../lib/stores/people.svelte";
  import type { Channel, Contact, PeopleKind } from "../../lib/types";

  // An intro draft for one person. Nothing is written until you ask: each draft is a Claude request on your plan.
  let { kind, contact: c }: { kind: PeopleKind; contact: Contact } = $props();
  const channel = $derived(channelFor(c));
  const key = $derived(draftKey(c.person_id, channel));
  const draft = $derived(drafts.get(key));
  const seconds = $derived(writing.get(key));
  const isWriting = $derived(writing.has(key));
  const label = $derived(channel === "email" ? "email" : "LinkedIn note");
  const hasDraft = $derived(!!draft || isWriting);

  // The text fields start from the draft and are saved back when they lose focus.
  let body = $state("");
  let subject = $state("");
  let saveError = $state("");
  $effect(() => {
    body = isWriting ? "" : draft?.body || "";
    subject = isWriting ? "" : draft?.subject || "";
  });

  const limit = $derived(noteLimit());
  const count = $derived(channel === "linkedin_note" ? `${body.length} / ${limit}` : `${body.split(/\s+/).filter(Boolean).length} words`);
  const over = $derived(channel === "linkedin_note" && body.length > limit);
  const msg = $derived(isWriting ? { text: seconds == null ? "Writing…" : `Writing… ${seconds}s`, kind: "busy" }
    : draftErrors.get(key) ? { text: draftErrors.get(key)!, kind: "error" }
    : saveError ? { text: saveError, kind: "error" } : { text: "", kind: "" });

  function pick(value: Channel) {
    people.channel = { ...people.channel, [c.person_id]: value };
    saveError = "";
  }

  async function save() {
    if (!draft || isWriting) return;
    try { await saveDraft(draft, body, subject); saveError = ""; } catch (err) { saveError = (err as Error).message; }
  }

  let textarea: HTMLTextAreaElement;
  async function copy() {
    const text = channel === "email" && subject ? `Subject: ${subject}\n\n${body}` : body;
    try { await navigator.clipboard.writeText(text); } catch { textarea.select(); document.execCommand("copy"); }
    toast("Copied.");
  }
</script>

<div class="fp-draft" data-person={c.person_id}>
  <div class="fp-draft-head">
    <span class="fp-draft-label">Intro draft</span>
    <div class="fp-channel" role="radiogroup" aria-label="Message type">
      <label><input type="radio" name={`fp-ch-${c.person_id}`} value="linkedin_note" checked={channel === "linkedin_note"} onchange={() => pick("linkedin_note")} /><span>LinkedIn note</span></label>
      <label><input type="radio" name={`fp-ch-${c.person_id}`} value="email" checked={channel === "email"} onchange={() => pick("email")} /><span>Email</span></label>
    </div>
    <button type="button" class="btn btn-quiet fp-copy" hidden={!draft || isWriting} onclick={copy}><Icon name="copy" />Copy</button>
  </div>
  <div class="fp-draft-empty" hidden={hasDraft}>
    <p class="muted">Claude can write a {label} to {c.full_name.split(" ")[0]} from your profile. It takes about 20–40 seconds and uses your Claude plan.</p>
    <button type="button" class="btn btn-primary fp-write" onclick={() => writeDraft(kind, c, channel)}>Write {label}</button>
  </div>
  <input class="fp-subject" type="text" aria-label="Email subject" hidden={!hasDraft || channel !== "email"} bind:value={subject} onblur={save} />
  <textarea class="fp-body" rows="5" aria-label="Intro draft" hidden={!hasDraft} bind:value={body} bind:this={textarea} onblur={save}
    placeholder={isWriting ? `Writing a ${label} with Claude…` : ""}></textarea>
  <p class="fp-angle muted" hidden={isWriting || !draft?.angle}>{draft?.angle ? `Why this message: ${draft.angle}` : ""}</p>
  <ul class="fp-checks" hidden={isWriting || !draft?.checks?.length}>
    {#each isWriting ? [] : draft?.checks ?? [] as check, i (i)}<li>{check}</li>{/each}
  </ul>
  <div class="fp-draft-foot"><span class="fp-count muted" class:over hidden={!hasDraft}>{count}</span>
    <span class="form-msg fp-draft-msg {msg.kind}" role="status">{msg.text}</span>
    <button type="button" class="link fp-rewrite" hidden={!draft || isWriting} onclick={() => writeDraft(kind, c, channel)}>Rewrite</button></div>
</div>
