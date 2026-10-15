// Edit text in place. The text is set once; edits go back through `set` without re-rendering the
// node, so the caret never jumps. Enter finishes the line.
export function editable(node: HTMLElement, { value, set, onEdit }: { value: string | null | undefined; set: (v: string) => void; onEdit: () => void }) {
  node.textContent = value ?? "";
  try { node.contentEditable = "plaintext-only"; } catch { node.contentEditable = "true"; }
  if (node.contentEditable !== "plaintext-only") node.contentEditable = "true";
  node.spellcheck = true;
  const keydown = (e: KeyboardEvent) => { if (e.key === "Enter") { e.preventDefault(); node.blur(); } };
  const input = () => { set((node.textContent ?? "").replace(/\s+/g, " ").trim()); onEdit(); };
  node.addEventListener("keydown", keydown);
  node.addEventListener("input", input);
  return { destroy() { node.removeEventListener("keydown", keydown); node.removeEventListener("input", input); } };
}
