// Hash routing, compatible with the old app: "#board", "#people?listing=…&kind=…&add=1".
// The last page is remembered under the `view` storage key.
import { load, store } from "../storage";

export type View = "board" | "matches" | "tracker" | "companies" | "profile" | "resume" | "cover" | "people";
export type Section = "board" | "tracker" | "companies" | "profile" | "tool" | "people";

/** Sidebar views -> the section that shows them. "matches" is the board sorted by match; the tools share a page. */
export const VIEWS: Record<View, Section> = {
  board: "board", matches: "board", tracker: "tracker", companies: "companies", profile: "profile",
  resume: "tool", cover: "tool", people: "people",
};
export const SECTIONS: Section[] = ["board", "tracker", "companies", "profile", "tool", "people"];

export function parseHash(hash: string): { view: string; params: URLSearchParams } {
  const [view, q] = hash.replace(/^#/, "").split("?");
  return { view, params: new URLSearchParams(q || "") };
}

const isView = (v: string): v is View => v in VIEWS;

export const route = $state({ view: "board" as View, params: new URLSearchParams(), previous: null as View | null });

function apply(hash: string, fallback?: View) {
  const { view, params } = parseHash(hash);
  const next: View = isView(view) ? view : !view && fallback ? fallback : "board";
  route.previous = route.view;
  route.view = next;
  route.params = params;
  store("view", next);
}

/** Read the current hash (or the remembered view) and follow later changes. Returns a cleanup function. */
export function startRouter(): () => void {
  route.previous = null;
  const remembered = load<string>("view", "board");
  apply(location.hash, isView(remembered) ? remembered : "board");
  route.previous = null;
  const onHash = () => apply(location.hash);
  window.addEventListener("hashchange", onHash);
  return () => window.removeEventListener("hashchange", onHash);
}

export function navigate(hash: string) {
  location.hash = hash;
}
