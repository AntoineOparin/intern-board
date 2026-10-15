<script lang="ts">
  import { untrack } from "svelte";
  import Select from "../../lib/components/Select.svelte";
  import RankingPanel from "./RankingPanel.svelte";
  import Integrations from "./Integrations.svelte";
  import * as api from "../../lib/api";
  import { ago } from "../../lib/format";
  import { profile, resumeStatus, refreshProfile, uploadResume } from "../../lib/stores/profile.svelte";
  import { meta } from "../../lib/stores/meta.svelte";
  import { route } from "../../lib/stores/router.svelte";
  import { toast } from "../../lib/stores/toast.svelte";
  import type { Preferences, Profile } from "../../lib/types";

  // Claude writes from this profile. Ranking, tailored resumes and cover letters all use it.
  const CATEGORY_CHOICES = ["Software", "AI/ML/Data", "Hardware", "Product", "Quant"];
  const REGION_CHOICES: [string, string][] = [["US", "US"], ["CA", "Canada"], ["REMOTE", "Remote"]];
  const DEGREES = [{ value: "", label: "Any" }, ...["Associate's", "Bachelor's", "Master's", "PhD"].map(d => ({ value: d, label: d }))];

  const p = $derived(profile.data);
  const hasData = $derived(!!p && Object.keys(p.data).length > 0);

  // ---------- resume ----------
  const status = $derived.by(() => {
    if (resumeStatus.override) return resumeStatus.override;
    if (!p) return { text: "", kind: "" };
    if (p.extract_job) return { text: "Claude is reading your resume…", kind: "busy" };
    if (p.has_resume && !hasData) return { text: "Your resume was uploaded but not read yet. Upload it again to retry.", kind: "error" };
    if (p.has_resume) return { text: `Profile updated ${ago(p.updated_at)}.`, kind: "ok" };
    return { text: "", kind: "" };
  });

  // Each visit reloads the profile and follows an extraction that is still running.
  $effect(() => {
    if (route.view !== "profile") return;
    untrack(() => refreshProfile());
  });
  const upload = uploadResume;

  let fileInput: HTMLInputElement;
  let over = $state(false);
  function onFile() { const f = fileInput.files?.[0]; if (f) upload(f); fileInput.value = ""; }
  function onDrop(e: DragEvent) { e.preventDefault(); over = false; const f = e.dataTransfer?.files[0]; if (f) upload(f); }

  // ---------- profile JSON ----------
  let rawOpen = $state(false);
  let rawJson = $state("");
  $effect(() => { if (p && hasData && !untrack(() => rawOpen)) rawJson = JSON.stringify(p.data, null, 2); });
  async function saveJson() {
    let data;
    try { data = JSON.parse(rawJson); } catch { toast("That isn't valid JSON. Check for a missing comma or quote."); return; }
    try {
      profile.data = { ...profile.data!, ...(await api.updateProfile({ data })) };
      toast("Profile saved.");
    } catch { /* shown */ }
  }

  // ---------- preferences ----------
  let prefs = $state({ target_roles: "", categories: [] as string[], regions: [] as string[], terms: [] as string[],
    degree_level: "", graduation: "", work_authorization: "", school: "", notes: "", linkedin_premium: false });
  let shownPrefs: Preferences | null = null;
  // Fill the form whenever a new profile arrives.
  $effect(() => {
    const pr = p?.preferences;
    if (!pr || pr === shownPrefs) return;
    shownPrefs = pr;
    prefs = { target_roles: pr.target_roles.join(", "), categories: [...pr.categories], regions: [...pr.regions], terms: [...pr.terms],
      degree_level: pr.degree_level ?? "", graduation: pr.graduation ?? "", work_authorization: pr.work_authorization ?? "",
      school: pr.school ?? "", notes: pr.notes ?? "", linkedin_premium: !!pr.linkedin_premium };
  });
  const termChoices = $derived([...new Set([...(p?.preferences.terms ?? []), ...(meta.data?.terms ?? []).slice(0, 8).map(t => t.value)])]);
  let prefsMsg = $state({ text: "", kind: "" });
  let msgTimer: ReturnType<typeof setTimeout> | undefined;

  async function savePrefs(e: SubmitEvent) {
    e.preventDefault();
    // In the order the choices are shown, like the old form.
    const inOrder = (choices: string[], picked: string[]) => choices.filter(c => picked.includes(c));
    const preferences = {
      target_roles: prefs.target_roles.split(",").map(x => x.trim()).filter(Boolean),
      categories: inOrder(CATEGORY_CHOICES, prefs.categories),
      regions: inOrder(REGION_CHOICES.map(r => r[0]), prefs.regions),
      terms: inOrder(termChoices, prefs.terms),
      degree_level: prefs.degree_level, graduation: prefs.graduation.trim(),
      work_authorization: prefs.work_authorization.trim(), school: prefs.school.trim(), notes: prefs.notes.trim(),
      linkedin_premium: prefs.linkedin_premium,
    } as Preferences;
    try {
      profile.data = { ...profile.data!, ...(await api.updateProfile({ preferences })) } as Profile;
      prefsMsg = { text: "Saved.", kind: "ok" };
    } catch (err) {
      prefsMsg = { text: (err as Error).message, kind: "error" };
    }
    clearTimeout(msgTimer);
    msgTimer = setTimeout(() => { prefsMsg = { ...prefsMsg, text: "" }; }, 3000);
  }

  const d = $derived(p?.data ?? {});
  const edu = $derived(d.education?.[0]);
  const skills = $derived([...(d.skills?.languages ?? []), ...(d.skills?.frameworks ?? [])].slice(0, 14));
</script>

<div class="intro intro-compact">
  <div>
    <h1 id="profile-heading">Your profile</h1>
    <p class="lede">Claude writes from this profile. It never adds anything that isn't in your resume. Ranking, tailored resumes and cover letters all use it.</p>
  </div>
</div>

<div class="profile-grid">
  <div class="panel">
    <h2 class="panel-title">Resume</h2>
    <label class="dropzone" class:over id="dropzone" ondragover={e => { e.preventDefault(); over = true; }} ondragleave={() => (over = false)} ondrop={onDrop}>
      <input type="file" id="resume-file" accept=".pdf,.docx,.txt,.md" bind:this={fileInput} onchange={onFile}>
      <svg class="icon icon-lg" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 16V4m0 0-4.5 4.5M12 4l4.5 4.5M4 16v2.5A1.5 1.5 0 0 0 5.5 20h13a1.5 1.5 0 0 0 1.5-1.5V16"/></svg>
      <span class="dz-main">Drop your resume here or <u>choose a file</u></span>
      <span class="dz-sub">PDF, Word (.docx) or text, up to 5 MB</span>
    </label>
    <p id="resume-status" class="form-msg {status.kind}" role="status">{status.text}</p>
    <div id="profile-summary" class="profile-summary" hidden={!hasData}>
      {#if hasData && p}
        <div class="ps-head"><strong>{d.name || "Unnamed"}</strong><span class="muted">{p.resume_filename ?? ""}</span></div>
        {#if d.summary}<p class="ps-summary">{d.summary}</p>{/if}
        <dl class="ps-facts">
          {#if edu}<dt>Education</dt><dd>{[edu.degree, edu.field].filter(Boolean).join(", ")} · {edu.school} {edu.end ? `· ${edu.end}` : ""}</dd>{/if}
          <dt>Experience</dt><dd>{(d.experience ?? []).map(e => `${e.role}, ${e.organization}`).join(" · ") || "None listed"}</dd>
          <dt>Projects</dt><dd>{(d.projects ?? []).map(x => x.name).join(" · ") || "None listed"}</dd>
          <dt>Skills</dt><dd class="ps-skills">{#each skills as x (x)}<span class="tag">{x}</span>{/each}</dd>
        </dl>
      {/if}
    </div>
    <details class="raw-edit" id="raw-edit" hidden={!hasData} bind:open={rawOpen}>
      <summary>Fix extraction mistakes (edit profile JSON)</summary>
      <textarea id="profile-json" rows="16" spellcheck="false" bind:value={rawJson}></textarea>
      <div class="row-end"><button type="button" class="btn btn-quiet" id="save-json" onclick={saveJson}>Save profile</button></div>
    </details>
  </div>

  <form class="panel" id="prefs-form" autocomplete="off" onsubmit={savePrefs}>
    <h2 class="panel-title">What you're looking for</h2>
    <label class="field"><span>Roles you want <em>(comma-separated)</em></span>
      <input name="target_roles" placeholder="backend, ML infrastructure, mobile" bind:value={prefs.target_roles}></label>
    <fieldset class="field"><legend>Categories</legend><div class="chips" id="pref-categories">
      {#each CATEGORY_CHOICES as c (c)}<label class="chip"><input type="checkbox" name="categories" value={c} bind:group={prefs.categories}>
        <span>{c}</span></label>{/each}
    </div></fieldset>
    <fieldset class="field"><legend>Where</legend><div class="chips" id="pref-regions">
      {#each REGION_CHOICES as [value, label] (value)}<label class="chip"><input type="checkbox" name="regions" {value} bind:group={prefs.regions}>
        <span>{label}</span></label>{/each}
    </div></fieldset>
    <fieldset class="field"><legend>Terms</legend><div class="chips" id="pref-terms">
      {#each termChoices as t (t)}<label class="chip"><input type="checkbox" name="terms" value={t} bind:group={prefs.terms}>
        <span>{t}</span></label>{/each}
    </div></fieldset>
    <div class="field-pair">
      <label class="field"><span>Degree level</span>
        <Select name="degree_level" label="Degree level" options={DEGREES} bind:value={prefs.degree_level} /></label>
      <label class="field"><span>Graduation</span><input name="graduation" placeholder="May 2028" bind:value={prefs.graduation}></label>
    </div>
    <label class="field"><span>Work authorization</span>
      <input name="work_authorization" placeholder="Canadian citizen; needs sponsorship for the US" bind:value={prefs.work_authorization}></label>
    <label class="field"><span>School <em>(for alumni searches)</em></span><input name="school" bind:value={prefs.school}></label>
    <label class="check-row"><input type="checkbox" name="linkedin_premium" bind:checked={prefs.linkedin_premium}>
      <span>I have LinkedIn Premium <em class="muted">(connection notes can be 300 characters instead of 200)</em></span></label>
    <label class="field"><span>Anything else Claude should know</span>
      <textarea name="notes" rows="3" placeholder="Prefer smaller companies; strongest in Python and Go…" bind:value={prefs.notes}></textarea></label>
    <div class="row-end"><span id="prefs-msg" class="form-msg {prefsMsg.kind}" role="status">{prefsMsg.text}</span><button class="btn btn-primary">Save preferences</button></div>
  </form>
</div>
<div id="profile-extras">
  <RankingPanel />
  <Integrations />
</div>
