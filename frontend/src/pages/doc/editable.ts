// Edit a line in place. The text is set once; edits go back through `set` without re-rendering the
// node, so the caret never jumps. Enter finishes the line and Shift+Enter starts a new line in it.
// A rich field keeps bold, italic, underline and colour (see lib/richtext.ts); a plain one (a list
// of skills) is text only. The page talks to a field with two events: "doc:refresh" redraws it
// from its stored line (after a formatting command) and "doc:clear" removes its formatting.
import { fromDom, plain, toDom, type Defaults } from "../../lib/richtext";
import type { Line } from "../../lib/types";

export interface EditableOptions {
  value: Line | null | undefined;
  set: (v: Line) => void;
  onEdit: () => void;
  key: string; // the field's path, which its formatting is stored under
  rich?: boolean;
}

export function editable(node: HTMLElement, { value, set, onEdit, key, rich = true }: EditableOptions) {
  let current: Line = value ?? "";
  node.dataset.key = key;
  if (rich) {
    toDom(current, node);
    node.contentEditable = "true";
  } else {
    node.dataset.plain = "";
    node.textContent = plain(current);
    try { node.contentEditable = "plaintext-only"; } catch { node.contentEditable = "true"; }
    if (node.contentEditable !== "plaintext-only") node.contentEditable = "true";
  }
  node.spellcheck = true;

  // What the field looks like without formatting (a school name is bold), read once it's styled.
  let defaults: Defaults | null = null;
  const defs = (): Defaults => {
    if (defaults) return defaults;
    const cs = getComputedStyle(node);
    return (defaults = { b: cs.fontWeight === "bold" || Number(cs.fontWeight) >= 600, i: cs.fontStyle === "italic" });
  };
  const read = () => {
    current = rich ? fromDom(node, defs()) : (node.textContent ?? "").replace(/\s+/g, " ").trim();
    set(current);
  };

  const keydown = (e: KeyboardEvent) => {
    if (e.key !== "Enter") return;
    e.preventDefault();
    if (e.shiftKey && rich) document.execCommand("insertLineBreak");
    else node.blur();
  };
  const input = () => { read(); onEdit(); };
  // Pasted or dropped text comes in plain, so no outside formatting or markup gets in.
  const paste = (e: ClipboardEvent) => {
    e.preventDefault();
    const text = (e.clipboardData?.getData("text/plain") ?? "").replace(/\s*\n\s*/g, " ");
    if (text) document.execCommand("insertText", false, text);
  };
  const drop = (e: DragEvent) => e.preventDefault();
  const beforeinput = (e: InputEvent) => { if (!rich && e.inputType.startsWith("format")) e.preventDefault(); };
  const refresh = () => { toDom(current, node); };
  const clear = () => {
    current = plain(current);
    if (rich) toDom(current, node); else node.textContent = current;
    set(current);
  };

  const events: [string, EventListener][] = [
    ["keydown", keydown as EventListener], ["input", input], ["paste", paste as EventListener], ["drop", drop as EventListener],
    ["beforeinput", beforeinput as EventListener], ["doc:refresh", refresh], ["doc:clear", clear],
  ];
  for (const [name, fn] of events) node.addEventListener(name, fn);
  return { destroy() { for (const [name, fn] of events) node.removeEventListener(name, fn); } };
}
