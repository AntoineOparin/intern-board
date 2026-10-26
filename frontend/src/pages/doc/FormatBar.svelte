<script lang="ts" module>
  import type { Align, PageFormat } from "../../lib/types";

  /** The field the toolbar acts on: the last one focused on the page. */
  export interface FormatTarget {
    label: string;
    rich: boolean; // bold, italic, underline and colour work here
    alignable: boolean;
    block: boolean; // has spacing (every field but a few inside rows)
  }
  export interface FormatActions {
    undo(): void;
    redo(): void;
    mark(cmd: "bold" | "italic" | "underline"): void;
    colour(value: string): void;
    size(step: number): void;
    align(value: Align): void;
    spacing(which: "before" | "after", lines: number): void;
    blankLine(): void;
    clear(): void;
    page(update: Partial<PageFormat>): void;
    resetPage(): void;
    clearAll(): void;
  }
</script>

<script lang="ts">
  // The formatting toolbar on the document page. Buttons keep the page's text selection: they don't
  // take focus on click, and the page remembers the selection for keyboard use.
  import { tick } from "svelte";
  import Icon from "../../lib/components/Icon.svelte";
  import Select from "../../lib/components/Select.svelte";
  import { LINE_HEIGHTS, MARGIN_LIMITS, MARGIN_PRESETS, PAGE_SIZES, PALETTE, SPACING } from "../../lib/richtext";
  import { FONTS } from "../../lib/types";

  let {
    target,
    canUndo,
    canRedo,
    marks,
    colour,
    style,
    page,
    act,
  }: {
    target: FormatTarget | null;
    canUndo: boolean;
    canRedo: boolean;
    marks: { b: boolean; i: boolean; u: boolean };
    colour: string;
    style: { align: Align | null; before: number; after: number; sizePt: number | null };
    page: Required<PageFormat>;
    act: FormatActions;
  } = $props();

  let bar: HTMLElement | undefined = $state();
  let menu = $state<"colour" | "page" | null>(null);
  let menuEl: HTMLElement | undefined = $state();

  const noTarget = "Click a line on the page first";
  const inlineReason = $derived(!target ? noTarget : target.rich ? "" : "Lists of skills and awards are plain text");
  const alignReason = $derived(!target ? noTarget : target.alignable ? "" : "Rows with dates can't be aligned");
  const blockReason = $derived(!target ? noTarget : target.block ? "" : "Not available for this field");
  const ALIGNS: [Align, string, "alignLeft" | "alignCenter" | "alignRight" | "alignJustify"][] = [
    ["left", "Align left", "alignLeft"], ["center", "Centre", "alignCenter"], ["right", "Align right", "alignRight"], ["justify", "Justify", "alignJustify"],
  ];
  const spacingOptions = SPACING.map(([v, label]) => ({ value: String(v), label }));
  const sizeOptions = [{ value: "auto", label: "Auto (fit one page)" }, ...PAGE_SIZES.map(s => ({ value: String(s), label: `${s} pt` }))];
  const lineOptions = LINE_HEIGHTS.map(([v, label]) => ({ value: String(v), label }));
  const fontOptions = FONTS.map(f => ({ value: f, label: f }));
  const MARGINS = [["top", "Top"], ["bottom", "Bottom"], ["left", "Left"], ["right", "Right"]] as const;
  const colourName = $derived(PALETTE.find(p => p.value === colour)?.name ?? "Custom");

  const keep = (e: PointerEvent) => e.preventDefault(); // keep the page's selection

  async function toggle(which: "colour" | "page") {
    menu = menu === which ? null : which;
    if (menu) { await tick(); menuEl?.querySelector<HTMLElement>("button, input")?.focus(); }
  }
  function close(refocus = true) {
    const was = menu;
    menu = null;
    if (refocus && was) bar?.querySelector<HTMLElement>(`[data-menu="${was}"]`)?.focus();
  }
  $effect(() => {
    if (!menu) return;
    const onDown = (e: PointerEvent) => {
      const t = e.target as Element;
      if (!t.closest?.(".fmt-menu, .fmt-menu-button, .ui-select-list")) close(false);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") { e.preventDefault(); close(); } };
    window.addEventListener("pointerdown", onDown);
    window.addEventListener("keydown", onKey);
    return () => { window.removeEventListener("pointerdown", onDown); window.removeEventListener("keydown", onKey); };
  });

  // Arrow keys move between the toolbar's buttons (Tab still works too).
  function onkeydown(e: KeyboardEvent) {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    const t = e.target as HTMLElement;
    if (t.closest(".fmt-menu") || t.tagName === "INPUT") return;
    const items = [...bar!.querySelectorAll<HTMLElement>(".fmt-group > button:not(:disabled), .fmt-group .ui-select-button:not(:disabled)")];
    const i = items.indexOf(t.closest("button") as HTMLElement);
    if (i < 0) return;
    e.preventDefault();
    items[(i + (e.key === "ArrowRight" ? 1 : items.length - 1)) % items.length].focus();
  }

  function margin(side: "top" | "right" | "bottom" | "left", raw: string) {
    const v = Number(raw);
    if (!Number.isFinite(v)) return;
    const clamped = Math.min(MARGIN_LIMITS.max, Math.max(MARGIN_LIMITS.min, Math.round(v * 100) / 100));
    act.page({ margins: { ...page.margins, [side]: clamped } });
  }
</script>

<div class="fmt-bar" role="toolbar" aria-label="Formatting" tabindex="-1" bind:this={bar} {onkeydown}>
  <span class="fmt-target muted" aria-live="polite">{target ? target.label : "Click text to format it"}</span>

  <div class="fmt-group">
    <button type="button" class="fmt-btn" aria-label="Undo" title="Undo (⌘Z)" disabled={!canUndo} onpointerdown={keep} onclick={act.undo}><Icon name="undo" /></button>
    <button type="button" class="fmt-btn" aria-label="Redo" title="Redo (⇧⌘Z)" disabled={!canRedo} onpointerdown={keep} onclick={act.redo}><Icon name="redo" /></button>
  </div>

  <div class="fmt-group">
    <button type="button" class="fmt-btn fmt-b" aria-label="Bold" aria-pressed={marks.b} title={inlineReason || "Bold (⌘B)"} disabled={!!inlineReason} onpointerdown={keep} onclick={() => act.mark("bold")}>B</button>
    <button type="button" class="fmt-btn fmt-i" aria-label="Italic" aria-pressed={marks.i} title={inlineReason || "Italic (⌘I)"} disabled={!!inlineReason} onpointerdown={keep} onclick={() => act.mark("italic")}>I</button>
    <button type="button" class="fmt-btn fmt-u" aria-label="Underline" aria-pressed={marks.u} title={inlineReason || "Underline (⌘U)"} disabled={!!inlineReason} onpointerdown={keep} onclick={() => act.mark("underline")}>U</button>
    <span class="fmt-menu-wrap">
      <button type="button" class="fmt-btn fmt-menu-button" data-menu="colour" aria-label="Text colour: {colourName}" aria-expanded={menu === "colour"}
        title={inlineReason || "Text colour"} disabled={!!inlineReason} onpointerdown={keep} onclick={() => toggle("colour")}>
        <span class="fmt-a">A</span><span class="fmt-swatch-bar" style:background={colour}></span>
      </button>
      {#if menu === "colour"}
        <div class="fmt-menu fmt-colours" role="group" aria-label="Text colour" bind:this={menuEl}>
          {#each PALETTE as p (p.value)}
            <button type="button" class="fmt-colour" aria-label={p.name} aria-pressed={colour === p.value} title={p.name} onpointerdown={keep}
              onclick={() => { act.colour(p.value); close(false); }}><span style:background={p.value}></span></button>
          {/each}
        </div>
      {/if}
    </span>
  </div>

  <div class="fmt-group">
    <button type="button" class="fmt-btn" aria-label="Smaller text" title={target ? "Smaller text" : noTarget} disabled={!target} onpointerdown={keep} onclick={() => act.size(-1)}>A−</button>
    <span class="fmt-size" aria-live="polite" title="Text size of this field">{style.sizePt ? `${style.sizePt} pt` : "– pt"}</span>
    <button type="button" class="fmt-btn" aria-label="Larger text" title={target ? "Larger text" : noTarget} disabled={!target} onpointerdown={keep} onclick={() => act.size(1)}>A+</button>
  </div>

  <div class="fmt-group">
    {#each ALIGNS as [value, label, icon] (value)}
      <button type="button" class="fmt-btn" aria-label={label} aria-pressed={style.align === value} title={alignReason || label} disabled={!!alignReason}
        onpointerdown={keep} onclick={() => act.align(value)}><Icon name={icon} /></button>
    {/each}
  </div>

  <div class="fmt-group fmt-spacing">
    <span class="fmt-label" aria-hidden="true">Before</span>
    <Select label="Space before" class="fmt-select" options={spacingOptions} value={String(style.before)} disabled={!!blockReason} onchange={v => act.spacing("before", Number(v))} />
    <span class="fmt-label" aria-hidden="true">After</span>
    <Select label="Space after" class="fmt-select" options={spacingOptions} value={String(style.after)} disabled={!!blockReason} onchange={v => act.spacing("after", Number(v))} />
    <button type="button" class="fmt-btn" aria-label="Add a blank line after" title={blockReason || "Add a blank line after"} disabled={!!blockReason} onpointerdown={keep} onclick={act.blankLine}><Icon name="blankLine" /></button>
  </div>

  <div class="fmt-group">
    <button type="button" class="fmt-btn" aria-label="Clear formatting" title={target ? "Clear this field's formatting" : noTarget} disabled={!target} onpointerdown={keep} onclick={act.clear}><Icon name="clearFormat" /></button>
  </div>

  <span class="spacer"></span>

  <div class="fmt-group">
    <span class="fmt-menu-wrap">
      <button type="button" class="btn btn-quiet fmt-menu-button fmt-page-button" data-menu="page" aria-expanded={menu === "page"} onclick={() => toggle("page")}>
        <Icon name="page" /> Page
      </button>
      {#if menu === "page"}
        <div class="fmt-menu fmt-page" role="group" aria-label="Page settings" bind:this={menuEl}>
          <fieldset>
            <legend>Margins (inches)</legend>
            <div class="fmt-presets">
              {#each MARGIN_PRESETS as [label, v] (label)}
                <button type="button" class="btn btn-quiet" aria-pressed={MARGINS.every(([s]) => page.margins[s] === v)}
                  onclick={() => act.page({ margins: { top: v, right: v, bottom: v, left: v } })}>{label} {v}"</button>
              {/each}
            </div>
            <div class="fmt-margins">
              {#each MARGINS as [side, label] (side)}
                <label>{label}<input type="number" min={MARGIN_LIMITS.min} max={MARGIN_LIMITS.max} step="0.05" value={page.margins[side]}
                  onchange={e => margin(side, e.currentTarget.value)} /></label>
              {/each}
            </div>
          </fieldset>
          <div class="fmt-page-row"><span>Font</span><Select label="Font" options={fontOptions} value={page.font} onchange={v => act.page({ font: v as Required<PageFormat>["font"] })} /></div>
          <div class="fmt-page-row"><span>Text size</span><Select label="Text size" options={sizeOptions} value={String(page.size)} onchange={v => act.page({ size: v === "auto" ? "auto" : Number(v) })} /></div>
          <div class="fmt-page-row"><span>Line spacing</span><Select label="Line spacing" options={lineOptions} value={String(page.lineHeight)} onchange={v => act.page({ lineHeight: Number(v) })} /></div>
          <div class="fmt-page-actions">
            <button type="button" class="btn btn-quiet" onclick={act.resetPage}>Reset page</button>
            <button type="button" class="btn btn-quiet" onclick={() => { act.clearAll(); close(); }}>Remove all formatting</button>
          </div>
        </div>
      {/if}
    </span>
  </div>
</div>
