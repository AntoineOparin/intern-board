<script lang="ts" module>
  // Line icons from the old index.html (24x24, stroked by .icon in style.css).
  export const ICONS = {
    menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
    board: '<rect x="3.5" y="5" width="17" height="14" rx="2"/><path d="M3.5 9.5h17M8 5V3.5M16 5V3.5"/>',
    star: '<path d="M12 3.5l2.4 5 5.4.6-4 3.7 1.1 5.4L12 15.5l-4.9 2.7 1.1-5.4-4-3.7 5.4-.6z"/>',
    companies: '<path d="M4 20.5V6l7-2.5v17M11 9.5l9 3v8M2.5 20.5h19M7 9h1M7 12.5h1M7 16h1M15 15h1"/>',
    tracker: '<path d="M9 6h11M9 12h11M9 18h11M4 6l1 1 2-2M4 12l1 1 2-2M4 18l1 1 2-2"/>',
    resume: '<path d="M6.5 3.5h7l4 4v13h-11z"/><path d="M13.5 3.5v4h4M12 17v-6M9.5 13.5 12 11l2.5 2.5"/>',
    pen: '<path d="M4 20l1-4L16.5 4.5a2.1 2.1 0 0 1 3 3L8 19z"/><path d="M14.5 6.5l3 3"/>',
    people: '<circle cx="9" cy="8.5" r="3.2"/><path d="M3.5 19c.6-3 2.8-4.7 5.5-4.7s4.9 1.7 5.5 4.7M15.5 5.6a3 3 0 0 1 0 5.8M17 14.6c1.8.6 3 2.1 3.5 4.4"/>',
    profile: '<circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="10" r="3"/><path d="M6.6 18.2c1.2-2 3.1-3 5.4-3s4.2 1 5.4 3"/>',
    close: '<path d="M6 6l12 12M18 6 6 18"/>',
    search: '<circle cx="11" cy="11" r="6.5"/><path d="m20 20-4.2-4.2"/>',
    pin: '<path d="M12 21s-6.5-5.6-6.5-11a6.5 6.5 0 0 1 13 0c0 5.4-6.5 11-6.5 11z"/><circle cx="12" cy="10" r="2.3"/>',
    badge: '<path d="M12 3l2.2 1.6 2.7-.1.8 2.6 2.2 1.6-.9 2.6.9 2.6-2.2 1.6-.8 2.6-2.7-.1L12 21l-2.2-1.6-2.7.1-.8-2.6L4.1 15.3l.9-2.6-.9-2.6 2.2-1.6.8-2.6 2.7.1z"/><path d="m9 12 2 2 4-4"/>',
    coffee: '<path d="M5 9h11v5a5 5 0 0 1-5 5h-1a5 5 0 0 1-5-5z"/><path d="M16 10.5h1.5a2.5 2.5 0 0 1 0 5H16M8 3.5c0 1 1 1.3 1 2.3M11.5 3.5c0 1 1 1.3 1 2.3"/>',
    mail: '<rect x="3.5" y="5.5" width="17" height="13" rx="2"/><path d="m4 7 8 6 8-6"/>',
    linkedin: '<rect x="3.5" y="3.5" width="17" height="17" rx="3"/><path d="M8 10.5V16M8 7.8v.1M11.5 16v-3.3c0-1.3.9-2.2 2-2.2s2 .9 2 2.2V16M11.5 10.5V16"/>',
    check: '<path d="m5 12.5 4.2 4L19 7"/>',
    copy: '<rect x="8.5" y="8.5" width="11" height="11" rx="2"/><path d="M15.5 8.5V6a1.5 1.5 0 0 0-1.5-1.5H6A1.5 1.5 0 0 0 4.5 6v8A1.5 1.5 0 0 0 6 15.5h2.5"/>',
    back: '<path d="M15 6l-6 6 6 6"/>',
    chevron: '<path d="m9 6 6 6-6 6"/>',
    swap: '<path d="M7 4v13m0 0-3-3m3 3 3-3M17 20V7m0 0-3 3m3-3 3 3"/>',
    undo: '<path d="M9 14 4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11"/>',
    redo: '<path d="m15 14 5-5-5-5"/><path d="M20 9H9.5a5.5 5.5 0 0 0 0 11H13"/>',
    alignLeft: '<path d="M4 6h16M4 10h10M4 14h16M4 18h10"/>',
    alignCenter: '<path d="M4 6h16M7 10h10M4 14h16M7 18h10"/>',
    alignRight: '<path d="M4 6h16M10 10h10M4 14h16M10 18h10"/>',
    alignJustify: '<path d="M4 6h16M4 10h16M4 14h16M4 18h16"/>',
    blankLine: '<path d="M4 4.5h16M4 19.5h16M12 8v8M9.5 10.5 12 8l2.5 2.5M9.5 13.5 12 16l2.5-2.5"/>',
    clearFormat: '<path d="M5 6h11M10.5 6l-3 12M14 14l6 6M20 14l-6 6"/>',
    page: '<rect x="5.5" y="3.5" width="13" height="17" rx="1.5"/><path d="M8.5 7h7M8.5 10.5h7M8.5 14h4.5"/>',
  } as const;
  export type IconName = keyof typeof ICONS;
</script>

<script lang="ts">
  let { name, class: cls = "icon" }: { name: IconName; class?: string } = $props();
</script>

<svg class={cls} viewBox="0 0 24 24" aria-hidden="true">{@html ICONS[name]}</svg>
