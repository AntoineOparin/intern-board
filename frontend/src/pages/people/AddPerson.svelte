<script lang="ts">
  import Icon from "../../lib/components/Icon.svelte";
  import { people, addPerson } from "../../lib/stores/people.svelte";
  import type { PeopleKind } from "../../lib/types";

  // Someone you found yourself (e.g. from the free search links). Costs nothing.
  let { kind }: { kind: PeopleKind } = $props();
  let open = $state(people.add);
  let f = $state({ full_name: "", title: "", linkedin_url: "", email: "" });
  let msg = $state({ text: "", error: false });

  async function submit(e: SubmitEvent) {
    e.preventDefault();
    const name = f.full_name.trim();
    if (!name) { msg = { text: "Enter their name.", error: true }; return; }
    if (name.length < 2) { msg = { text: "Enter their full name.", error: true }; return; }
    try {
      await addPerson(kind, { ...f });
      f = { full_name: "", title: "", linkedin_url: "", email: "" };
      msg = { text: "", error: false };
      open = false;
    } catch (err) {
      msg = { text: (err as Error).message, error: true };
    }
  }
</script>

<details class="fp-add" bind:open>
  <summary><Icon name="people" />Add a person yourself</summary>
  <form class="fp-add-form" autocomplete="off" novalidate onsubmit={submit}>
    <label class="field"><span>Name</span><input name="full_name" required maxlength="100" bind:value={f.full_name} /></label>
    <label class="field"><span>Title <em>(optional)</em></span><input name="title" maxlength="150" bind:value={f.title}
      placeholder={kind === "recruiters" ? "University Recruiter" : "Software Engineer"} /></label>
    <label class="field"><span>LinkedIn <em>(optional)</em></span><input name="linkedin_url" placeholder="linkedin.com/in/their-name" bind:value={f.linkedin_url} /></label>
    <label class="field"><span>Email <em>(optional)</em></span><input name="email" type="email" bind:value={f.email} /></label>
    <div class="fp-add-actions"><button class="btn btn-primary">Add</button>
      <span class="form-msg" class:error={msg.error} role="status">{msg.text}</span></div>
  </form>
</details>
