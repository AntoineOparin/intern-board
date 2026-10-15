<script lang="ts">
  // Stands in for a page until it moves to the new app (one page per migration step).
  let { title, view }: { title: string; view: string } = $props();
</script>

<div class="intro intro-compact">
  <div>
    <h1>{title}</h1>
    <p class="lede">This page hasn't moved to the new app yet. <a class="link" href={`../#${view}`}>Open it in the current app</a>.</p>
  </div>
</div>
