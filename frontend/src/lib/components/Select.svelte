<script lang="ts" module>
  // Only one dropdown is open at a time.
  let closeOpen: (() => void) | null = null;
  const finePointer = () => typeof matchMedia === "function" && matchMedia("(pointer: fine)").matches;
  let uid = 0;
</script>

<script lang="ts">
  // A dropdown that looks the same in Safari, Chrome and Firefox (replaces select.js).
  // A hidden native <select> stays in the form, so FormData and the `name` still work. On touch
  // screens the native picker is shown instead, since it works better there.
  export type Option = { value: string; label: string; disabled?: boolean };
  let {
    value = $bindable(""),
    options,
    label,
    name,
    id,
    class: cls = "",
    disabled = false,
    onchange,
  }: {
    value?: string;
    options: Option[];
    label: string;
    name?: string;
    id?: string;
    class?: string;
    disabled?: boolean;
    onchange?: (value: string) => void;
  } = $props();

  const listId = `ui-select-${++uid}`;
  const native = !finePointer();
  let open = $state(false);
  let up = $state(false);
  let active = $state(-1);
  let button: HTMLButtonElement | undefined = $state();
  let list: HTMLUListElement | undefined = $state();
  let wrap: HTMLSpanElement | undefined = $state();

  const current = $derived(Math.max(0, options.findIndex(o => o.value === value)));
  const shown = $derived(options[current]?.label ?? "");

  function scrollActive() {
    (list?.children[active] as HTMLElement | undefined)?.scrollIntoView({ block: "nearest" });
  }

  async function show() {
    if (disabled) return;
    closeOpen?.();
    closeOpen = hide;
    active = current;
    const rect = button!.getBoundingClientRect();
    // Open upwards when there's no room below.
    up = innerHeight - rect.bottom < 260 && rect.top > innerHeight - rect.bottom;
    open = true;
    await Promise.resolve();
    scrollActive();
  }

  function hide() {
    if (!open) return;
    open = false;
    if (closeOpen === hide) closeOpen = null;
  }

  function choose(i: number) {
    const changed = i !== current;
    value = options[i].value;
    hide();
    button?.focus();
    if (changed) onchange?.(value);
  }

  function step(from: number, dir: number) {
    for (let i = from + dir; i >= 0 && i < options.length; i += dir) if (!options[i].disabled) return i;
    return from;
  }

  function setActive(i: number, scroll = true) {
    active = i;
    if (scroll) queueMicrotask(scrollActive);
  }

  let typed = "", typedAt = 0;
  function onkeydown(e: KeyboardEvent) {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (!open) return void show();
      setActive(step(active, e.key === "ArrowDown" ? 1 : -1));
    } else if (e.key === "Home" || e.key === "End") {
      if (!open) return;
      e.preventDefault();
      setActive(e.key === "Home" ? step(-1, 1) : step(options.length, -1));
    } else if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      if (open && active >= 0) choose(active);
      else show();
    } else if (e.key === "Escape" && open) {
      e.preventDefault();
      e.stopPropagation(); // don't also close a surrounding dialog
      hide();
    } else if (e.key === "Tab") {
      hide();
    } else if (e.key.length === 1 && /\S/.test(e.key)) {
      // Type to jump to an option.
      typed = Date.now() - typedAt > 700 ? e.key.toLowerCase() : typed + e.key.toLowerCase();
      typedAt = Date.now();
      const i = options.findIndex(o => o.label.trim().toLowerCase().startsWith(typed));
      if (i >= 0) {
        if (open) setActive(i);
        else if (i !== current) { value = options[i].value; onchange?.(value); }
      }
    }
  }

  function onblur() {
    setTimeout(() => { if (!wrap?.contains(document.activeElement)) hide(); }, 0);
  }

  function onDocMousedown(e: MouseEvent) {
    if (open && !wrap?.contains(e.target as Node)) hide();
  }
</script>

<svelte:document onmousedown={onDocMousedown} />
<svelte:window onresize={hide} />

{#if native}
  <select class={cls} {name} {id} {disabled} aria-label={label} bind:value onchange={() => onchange?.(value)}>
    {#each options as o (o.value)}<option value={o.value} disabled={o.disabled}>{o.label}</option>{/each}
  </select>
{:else}
  <span class="ui-select {cls}" class:open class:up bind:this={wrap}>
    <select class="ui-select-native" {name} {id} tabindex="-1" aria-hidden="true" {disabled} bind:value>
      {#each options as o (o.value)}<option value={o.value} disabled={o.disabled}>{o.label}</option>{/each}
    </select>
    <!-- svelte-ignore a11y_role_supports_aria_props_implicit (kept from select.js: screen readers announce the highlighted option; a combobox role is a later change) -->
    <button type="button" class="ui-select-button" aria-haspopup="listbox" aria-expanded={open} aria-controls={listId}
      aria-label={label} aria-activedescendant={open && active >= 0 ? `${listId}-${active}` : ""} {disabled}
      bind:this={button} onclick={() => (open ? hide() : show())} {onkeydown} {onblur}>
      <span class="ui-select-value">{shown}</span><svg class="ui-select-caret" viewBox="0 0 24 24" aria-hidden="true"><path d="m7 10 5 5 5-5"/></svg>
    </button>
    <ul class="ui-select-list" id={listId} role="listbox" hidden={!open} bind:this={list}>
      {#each options as o, i (o.value)}
        <!-- svelte-ignore a11y_click_events_have_key_events (the button handles the keyboard) -->
        <li role="option" id={`${listId}-${i}`} aria-selected={i === current} aria-disabled={o.disabled ? "true" : undefined}
          class:active={i === active} onmousedown={e => e.preventDefault()} onclick={() => { if (!o.disabled) choose(i); }}
          onmousemove={() => setActive(i, false)}>{o.label}</li>
      {/each}
    </ul>
  </span>
{/if}
