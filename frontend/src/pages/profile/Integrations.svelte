<script lang="ts">
  import { onMount } from "svelte";
  import * as api from "../../lib/api";
  import { credits, ready } from "../../lib/stores/credits.svelte";
  import type { ProspeoAccount } from "../../lib/types";

  // Profile -> Integrations: the Prospeo key (shown masked, never in full) and saved contacts.
  let s: ProspeoAccount | null = $state(null);
  let key = $state("");
  let msg = $state({ text: "", kind: "" });

  function draw(next: ProspeoAccount) {
    s = next;
    key = "";
    msg = { text: "", kind: "" };
  }

  onMount(() => { api.prospeo({ quiet: true }).then(draw).catch(() => draw({ configured: false })); });

  async function save(e: SubmitEvent) {
    e.preventDefault();
    const k = key.trim();
    if (!k) return;
    if (!/^[A-Za-z0-9_-]{10,200}$/.test(k)) {
      msg = { text: "That doesn't look like a Prospeo API key. Copy it from the API page on prospeo.io.", kind: "error" };
      return;
    }
    try {
      draw(await api.setProspeoKey(k, { quiet: true }));
      credits.account = null;
    } catch (err) {
      msg = { text: (err as Error).message, kind: "error" };
    }
  }

  async function removeKey() {
    try { await api.removeProspeoKey(); draw({ configured: false }); } catch { /* shown */ }
  }

  async function forget() {
    if (!confirm("Delete every saved contact and search? This can't be undone.")) return;
    try {
      const r = await api.forgetContacts();
      msg = { text: `Deleted ${r.deleted} saved contact${r.deleted === 1 ? "" : "s"}.`, kind: "ok" };
    } catch { /* shown */ }
  }
</script>

<section class="panel fp-integrations">
  <h2 class="panel-title">Integrations</h2>
  {#if !s}
    <p class="muted">Loading…</p>
  {:else}
    <div class="fp-int-row">
      <div><strong>Prospeo</strong> <span class="muted">· finds people and verified emails for Find People</span>
        <p class="muted fp-int-status">
          {#if !s.configured}
            Not connected. Create a free account at prospeo.io, copy your API key from its API page, and paste it here.
          {:else if !ready(s)}
            <span class="form-msg error">{s.error}</span>
          {:else}
            Key {s.masked} · {s.plan || ""} plan · <strong>{s.remaining}</strong> credits left, renews {(s.renews || "").slice(0, 10)}
          {/if}
        </p></div>
    </div>
    <form class="fp-key-form" autocomplete="off" onsubmit={save}>
      <input type="password" name="key" placeholder={s.configured ? "Paste a new key to replace it" : "Prospeo API key"} aria-label="Prospeo API key" bind:value={key} />
      <button class="btn btn-quiet">{s.configured ? "Replace key" : "Save key"}</button>
      {#if s.configured}<button type="button" class="btn btn-danger-quiet fp-key-remove" onclick={removeKey}>Remove key</button>{/if}
    </form>
    <p class="muted fp-int-note">The key is saved in the app's <code>.env</code> file on your Mac and only sent to Prospeo.
      People you find are saved locally. <button type="button" class="link fp-forget" onclick={forget}>Delete saved contacts</button></p>
    <p class="form-msg fp-int-msg {msg.kind}" role="status">{msg.text}</p>
  {/if}
</section>
