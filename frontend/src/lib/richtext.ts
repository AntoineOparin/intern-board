// Formatted lines on the document page (board/documents.py has the stored shape). A line is a plain
// string, or runs when part of it is bold, italic, underlined or coloured. These helpers are pure
// (they only touch the nodes they're given) so they can be tested without a component.
import type { DocFormat, Line, LineStyle, PageFormat, Run } from "./types";

type Marks = Omit<Run, "t">;
/** What an element already looks like without formatting, e.g. a school name is bold. */
export type Defaults = { b?: boolean; i?: boolean };

export const PALETTE = [
  { name: "Black", value: "#000000" },
  { name: "Charcoal", value: "#3a3a3a" },
  { name: "Grey", value: "#6b6b6b" },
  { name: "Navy", value: "#1f3a5f" },
  { name: "Blue", value: "#1d4f91" },
  { name: "Teal", value: "#0f5e5a" },
  { name: "Green", value: "#2f5d34" },
  { name: "Burgundy", value: "#7a1f2b" },
] as const;
export const SPACING: [number, string][] = [[0, "None"], [0.25, "¼ line"], [0.5, "½ line"], [1, "1 line"], [1.5, "1½ lines"], [2, "2 lines"], [3, "3 lines"], [4, "4 lines"]];
export const LINE_HEIGHTS: [number, string][] = [[1, "1.0"], [1.15, "1.15"], [1.25, "1.25"], [1.5, "1.5"], [2, "2.0"]];
export const PAGE_SIZES: number[] = [8, 8.5, 9, 9.5, 10, 10.5, 11, 11.5, 12, 12.5, 13, 13.5, 14];
export const MARGIN_PRESETS: [string, number][] = [["Narrow", 0.5], ["Normal", 0.75], ["Wide", 1]];
export const SIZE_LIMITS = { min: 0.5, max: 4 }; // a style's size, as a multiple of the base size
export const MARGIN_LIMITS = { min: 0.25, max: 1.5 };

export const DEFAULT_PAGE: Required<PageFormat> = {
  margins: { top: 0.5, right: 0.5, bottom: 0.5, left: 0.5 },
  size: "auto",
  lineHeight: 1,
  font: "Source Serif 4",
};
export const pageOf = (format: DocFormat | undefined): Required<PageFormat> => {
  const page = format?.page ?? {};
  return { ...DEFAULT_PAGE, ...page, margins: { ...DEFAULT_PAGE.margins, ...page.margins } };
};

export function plain(line: Line | null | undefined): string {
  if (Array.isArray(line)) return line.map(r => r.t).join("");
  return line ?? "";
}

const MARKS = ["b", "i", "u", "c"] as const;
const sameMarks = (a: Marks, b: Marks) => MARKS.every(k => a[k] === b[k]);

/** "rgb(31, 58, 95)" or "#1F3A5F" -> "#1f3a5f"; anything else -> undefined. */
export function hex(colour: string | null | undefined): string | undefined {
  const s = (colour ?? "").trim().toLowerCase();
  if (/^#[0-9a-f]{6}$/.test(s)) return s;
  if (/^#[0-9a-f]{3}$/.test(s)) return `#${[...s.slice(1)].map(c => c + c).join("")}`;
  const m = s.match(/^rgba?\((\d+),\s*(\d+),\s*(\d+)/);
  return m ? `#${m.slice(1, 4).map(n => Number(n).toString(16).padStart(2, "0")).join("")}` : undefined;
}

function marksOf(el: HTMLElement, m: Marks): Marks {
  const out = { ...m };
  const tag = el.tagName;
  if (tag === "B" || tag === "STRONG") out.b = true;
  if (tag === "I" || tag === "EM") out.i = true;
  if (tag === "U") out.u = true;
  const st = el.style;
  if (st?.fontWeight) out.b = st.fontWeight === "bold" || st.fontWeight === "bolder" || Number(st.fontWeight) >= 600;
  if (st?.fontStyle) out.i = st.fontStyle === "italic";
  const deco = st?.textDecorationLine || st?.textDecoration;
  if (deco?.includes("underline")) out.u = true;
  const colour = hex(st?.color) ?? (tag === "FONT" ? hex(el.getAttribute("color")) : undefined);
  if (colour) out.c = colour;
  return out;
}

/** Drops runs' marks that match what the element looks like anyway, and empty runs. */
function normalize(runs: Run[], d: Defaults): Run[] {
  const out: Run[] = [];
  for (const r of runs) {
    const run: Run = { t: r.t };
    if (r.b !== undefined && r.b !== !!d.b) run.b = r.b;
    if (r.i !== undefined && r.i !== !!d.i) run.i = r.i;
    if (r.u) run.u = true;
    if (r.c && r.c !== "#000000") run.c = r.c;
    const last = out.at(-1);
    if (last && sameMarks(last, run)) last.t += run.t;
    else if (run.t) out.push(run);
  }
  return out;
}

/** Collapses spaces (keeping line breaks) across runs and trims the ends of the line. */
function tidy(runs: Run[]): Run[] {
  let prevSpace = true; // trims the start
  for (const r of runs) {
    let t = r.t.replace(/[^\S\n]+/g, " ").replace(/ *\n */g, "\n");
    if (prevSpace) t = t.replace(/^ +/, "");
    if (t.startsWith("\n")) { // no space before a line break in the previous run
      const prev = runs.slice(0, runs.indexOf(r)).findLast(p => p.t);
      if (prev) prev.t = prev.t.replace(/ +$/, "");
    }
    if (t) prevSpace = /[ \n]$/.test(t);
    r.t = t;
  }
  for (let i = runs.length - 1; i >= 0; i--) {
    runs[i].t = runs[i].t.replace(/\s+$/, "");
    if (runs[i].t) break;
  }
  return runs;
}

/** A line as stored: a plain string when nothing is formatted. */
export function compact(runs: Run[], d: Defaults = {}): Line {
  const out = normalize(tidy(runs.map(r => ({ ...r }))), d);
  return out.every(r => Object.keys(r).length === 1) ? out.map(r => r.t).join("") : out;
}

/** Reads an edited element back into a line. */
export function fromDom(root: Node, d: Defaults = {}): Line {
  const runs: Run[] = [];
  const walk = (node: Node, m: Marks) => {
    for (const child of Array.from(node.childNodes)) {
      if (child.nodeType === 3) runs.push({ t: child.textContent ?? "", ...m });
      else if (child.nodeType === 1) {
        const el = child as HTMLElement;
        if (el.tagName === "BR") runs.push({ t: "\n", ...m });
        else {
          // A browser can wrap new lines in a div or p; each one starts a new line.
          if ((el.tagName === "DIV" || el.tagName === "P") && runs.length) runs.push({ t: "\n", ...m });
          walk(el, marksOf(el, m));
        }
      }
    }
  };
  walk(root, {});
  return compact(runs, d);
}

/** Fills an element with a line's text and formatting, without innerHTML. */
export function toDom(line: Line | null | undefined, node: HTMLElement) {
  const doc = node.ownerDocument;
  node.replaceChildren();
  const runs: Run[] = Array.isArray(line) ? line : line ? [{ t: line }] : [];
  for (const r of runs) {
    const frag = doc.createDocumentFragment();
    r.t.split("\n").forEach((part, n) => {
      if (n) frag.append(doc.createElement("br"));
      if (part) frag.append(doc.createTextNode(part));
    });
    let out: Node = frag;
    const wrap = (el: HTMLElement) => { el.append(out); out = el; };
    if (r.u) wrap(doc.createElement("u"));
    if (r.i !== undefined) {
      if (r.i) wrap(doc.createElement("i"));
      else { const s = doc.createElement("span"); s.style.fontStyle = "normal"; wrap(s); }
    }
    if (r.b !== undefined) {
      if (r.b) wrap(doc.createElement("b"));
      else { const s = doc.createElement("span"); s.style.fontWeight = "normal"; wrap(s); }
    }
    if (r.c) { const s = doc.createElement("span"); s.style.color = r.c; wrap(s); }
    node.append(out);
  }
}

/** Removes and re-numbers the styles of a list's items when some are dropped (keep[i] false). */
export function shiftKeys(styles: Record<string, LineStyle>, prefix: string, keep: boolean[]): Record<string, LineStyle> {
  const out: Record<string, LineStyle> = {};
  const re = new RegExp(`^${prefix.replace(/\./g, "\\.")}\\.(\\d+)(\\..*)?$`);
  const newIndex = keep.map((_, i) => keep.slice(0, i).filter(Boolean).length);
  for (const [key, style] of Object.entries(styles)) {
    const m = key.match(re);
    if (!m) { out[key] = style; continue; }
    const i = Number(m[1]);
    if (i >= keep.length) out[key] = style;
    else if (keep[i]) out[`${prefix}.${newIndex[i]}${m[2] ?? ""}`] = style;
  }
  return out;
}

/** A style without empty values, or null when nothing is left. */
export function pruned(style: LineStyle): LineStyle | null {
  const out: LineStyle = {};
  if (style.align) out.align = style.align;
  if (style.size) out.size = Math.round(style.size * 1000) / 1000;
  if (style.before) out.before = style.before;
  if (style.after) out.after = style.after;
  return Object.keys(out).length ? out : null;
}

const isRuns = (v: unknown): v is Run[] => Array.isArray(v) && v.length > 0 && v.every(r => r && typeof r === "object" && "t" in r);

/** A copy of the content with every line back to plain text (styles are dropped by the caller). */
export function withoutFormatting<T>(value: T): T {
  if (isRuns(value)) return plain(value) as T;
  if (Array.isArray(value)) return value.map(withoutFormatting) as T;
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, withoutFormatting(v)])) as T;
  }
  return value;
}

// ---------- keeping a selection while a field is redrawn ----------
const textLength = (node: Node): number => {
  if (node.nodeType === 3) return node.textContent?.length ?? 0;
  if ((node as Element).tagName === "BR") return 1;
  let n = 0;
  node.childNodes.forEach(c => { n += textLength(c); });
  return n;
};

/** A range's start and end as character offsets in the field (a line break counts as one). */
export function textOffsets(root: Node, range: Range): [number, number] {
  const r = root.ownerDocument!.createRange();
  r.selectNodeContents(root);
  r.setEnd(range.startContainer, range.startOffset);
  const start = textLength(r.cloneContents());
  r.setEnd(range.endContainer, range.endOffset);
  return [start, textLength(r.cloneContents())];
}

/** The range between two character offsets in the field. */
export function rangeAt(root: Node, start: number, end: number): Range {
  const doc = root.ownerDocument!;
  const find = (n: number): [Node, number] => {
    let acc = 0;
    const walker = doc.createTreeWalker(root, 5 /* elements and text */);
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      if (node.nodeType === 3) {
        const len = node.textContent?.length ?? 0;
        if (n <= acc + len) return [node, n - acc];
        acc += len;
      } else if ((node as Element).tagName === "BR") {
        if (n <= acc) return [node.parentNode!, Array.prototype.indexOf.call(node.parentNode!.childNodes, node)];
        acc += 1;
      }
    }
    return [root, root.childNodes.length];
  };
  const r = doc.createRange();
  r.setStart(...find(start));
  r.setEnd(...find(Math.max(start, end)));
  return r;
}
