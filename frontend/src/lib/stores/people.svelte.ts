// Find People: pick a tracked job -> recruiters or coffee chats -> people with emails and intro drafts.
// People come from Prospeo (board/contacts.py); drafts from Claude (outreach job in board/people.py).
// State lives here, not in the page, so a draft or search keeps going when you navigate away.
import { SvelteMap, SvelteSet } from "svelte/reactivity";
import * as api from "../api";
import { toast } from "./toast.svelte";
import { credits, loadCredits as fetchCredits, noCredits } from "./credits.svelte";
import { navigate } from "./router.svelte";
import type { Channel, Contact, Draft, OutreachResult, PeopleKind, PeopleSession, PeopleSearchResult } from "../types";

export type Step = "blank" | "pick" | "choose" | "results";
export type Msg = { text: string; kind: "" | "busy" | "ok" | "error" };
export type AnyDraft = Draft | OutreachResult;

export const KINDS: PeopleKind[] = ["recruiters", "team"];
export const nounFor = (kind: PeopleKind, n: number) =>
  kind === "recruiters" ? (n === 1 ? "recruiter" : "recruiters") : n === 1 ? "person for a coffee chat" : "people for coffee chats";

export const people = $state({
  step: "blank" as Step,
  session: null as PeopleSession | null,
  kind: null as PeopleKind | null,
  open: null as string | null, // person_id of the open card
  add: false, // the add-a-person form starts open
  busy: false, // a Prospeo search is running
  searching: null as PeopleKind | null,
  chooseMsg: { text: "", kind: "" } as Msg,
  resultsMsg: { text: "", kind: "" } as Msg,
  channel: {} as Record<string, Channel>, // message type picked per person
  loadingRow: null as string | null, // job picker row being opened
});

/** "person|channel" -> the latest draft. */
export const drafts = new SvelteMap<string, AnyDraft>();
/** "person|channel" -> seconds while Claude writes it (null until the first progress report). */
export const writing = new SvelteMap<string, number | null>();
/** "person|channel" -> the last error writing it. */
export const draftErrors = new SvelteMap<string, string>();
// Drafts being written, so redraws and revisits never start a second request for the same one.
const pending = new Map<string, Promise<AnyDraft>>();
// Old emails re-checked quietly this visit (free inside Prospeo's window).
export const rechecked = new SvelteSet<string>();

export const draftKey = (personId: string, channel: Channel) => `${personId}|${channel}`;
export const channelFor = (c: Contact): Channel => people.channel[c.person_id] || (c.email ? "email" : "linkedin_note");
const listingId = () => people.session!.listing.id;

// ---------- loading ----------

export async function loadCredits() {
  const wasEmpty = noCredits();
  await fetchCredits();
  // Running out (or a renewal) changes which buttons work: reload the current step.
  if (wasEmpty !== noCredits() && people.session && people.step !== "pick") {
    await openListing(people.session.listing.id, people.kind, people.add);
  }
}

export async function openListing(id: string, kind: string | null, add = false) {
  let session: PeopleSession;
  try {
    session = await api.peopleSession(id);
  } catch {
    navigate("#people");
    return;
  }
  people.session = session;
  people.add = add;
  const has = (k: string | null): k is PeopleKind =>
    !!k && KINDS.includes(k as PeopleKind) && (!!session.searches[k as PeopleKind] || session.contacts[k as PeopleKind].length > 0);
  people.kind = has(kind) || (add && KINDS.includes(kind as PeopleKind)) ? (kind as PeopleKind) : null;
  people.chooseMsg = { text: "", kind: "" };
  people.resultsMsg = { text: "", kind: "" };
  if (!people.kind) {
    people.step = "choose";
    return;
  }
  const list = session.contacts[people.kind];
  if (!people.open || !list.some(c => c.person_id === people.open)) people.open = list[0]?.person_id ?? null; // first card opens
  await loadDrafts();
  people.step = "results";
}

async function loadDrafts() {
  drafts.clear();
  try {
    const { items } = await api.drafts(listingId(), { quiet: true });
    for (const d of [...items].sort((a, b) => a.created_at - b.created_at)) {
      if (d.person_id) drafts.set(draftKey(d.person_id, d.channel), d);
    }
  } catch { /* drafts are optional */ }
}

export function showPick() {
  people.session = null;
  people.step = "pick";
}

// ---------- step 2 ----------

export async function choose(kind: PeopleKind) {
  const s = people.session!;
  if (s.searches[kind] || s.contacts[kind].length) {
    navigate(`#people?listing=${encodeURIComponent(s.listing.id)}&kind=${kind}`);
    return;
  }
  await search(kind);
}

/** A Prospeo search (1 credit when it finds anyone). Runs only from a click. */
export async function search(kind: PeopleKind) {
  if (people.busy) return;
  people.busy = true;
  people.searching = kind;
  const which = people.step === "choose" ? "chooseMsg" : "resultsMsg";
  const id = listingId();
  try {
    await api.runJob<PeopleSearchResult>("people_search", { listing_id: id, kind }, sec => {
      people[which] = { text: `Searching Prospeo… ${sec}s`, kind: "busy" };
    });
    people.busy = false;
    const target = `#people?listing=${encodeURIComponent(id)}&kind=${kind}`;
    if (location.hash === target) await openListing(id, kind);
    else navigate(target);
  } catch (err) {
    people[which] = { text: (err as Error).message, kind: "error" };
  } finally {
    people.busy = false;
    people.searching = null;
    loadCredits();
  }
}

export async function saveSite(website: string) {
  const s = people.session!;
  try {
    await api.setSite(s.listing.id, website);
    await openListing(s.listing.id, people.kind, people.add);
    toast("Website saved. Run the search again to find people there.");
  } catch { /* the request showed a toast */ }
}

// ---------- step 3 ----------

function replaceContact(kind: PeopleKind, c: Contact) {
  const list = people.session!.contacts[kind];
  const i = list.findIndex(x => x.person_id === c.person_id);
  if (i >= 0) list[i] = c;
}

export async function revealEmail(kind: PeopleKind, personId: string) {
  try {
    const c = await api.revealEmail({ listing_id: listingId(), kind, person_id: personId }, { quiet: true });
    replaceContact(kind, c);
    if (!c.email) toast("Prospeo has no verified email for this person. No credit was used.");
  } catch (err) {
    toast((err as Error).message); // e.g. out of credits, with the renewal date
    throw err;
  } finally {
    loadCredits();
  }
}

export async function recheck(kind: PeopleKind, personId: string, { quiet = false } = {}) {
  const company = people.session!.company;
  try {
    const { charged, ...c } = await api.recheck({ listing_id: listingId(), kind, person_id: personId }, { quiet: true });
    replaceContact(kind, c);
    if (c.moved_to) toast(`${c.full_name} now appears to work at ${c.moved_to}.`);
    else if (c.email_status === "NO_LONGER_VERIFIED") toast(`Prospeo no longer verifies ${c.full_name}'s email. They may have left.`);
    else if (!quiet) toast(`Still at ${company}; email still verified.`);
  } catch (err) {
    if (!quiet) toast((err as Error).message);
    throw err;
  } finally {
    loadCredits();
  }
}

/** Old email still inside Prospeo's free window: re-check quietly, once per visit. */
export function autoRecheck(kind: PeopleKind, c: Contact) {
  if (!c.email_stale || !c.recheck_free || rechecked.has(c.person_id)) return;
  rechecked.add(c.person_id);
  recheck(kind, c.person_id, { quiet: true }).catch(() => {});
}

export async function removePerson(kind: PeopleKind, personId: string) {
  try {
    await api.removeContact({ listing_id: listingId(), kind, person_id: personId });
    people.session!.contacts[kind] = people.session!.contacts[kind].filter(c => c.person_id !== personId);
  } catch { /* the request showed a toast */ }
}

export async function addPerson(kind: PeopleKind, f: { full_name: string; title: string; linkedin_url: string; email: string }) {
  const c = await api.addContact({ listing_id: listingId(), kind, ...f }, { quiet: true });
  people.session!.contacts[kind].push(c);
  people.open = c.person_id;
  people.add = false;
  return c;
}

// ---------- intro drafts (Claude, only on click) ----------

export function writeDraft(kind: PeopleKind, c: Contact, channel: Channel) {
  const key = draftKey(c.person_id, channel);
  if (pending.has(key)) return;
  const previous = drafts.get(key); // "Rewrite" asks for a different angle than this one
  draftErrors.delete(key);
  writing.set(key, null);
  const promise = api.runJob<OutreachResult>("outreach", {
    listing_id: listingId(), person_id: c.person_id, channel,
    recipient_type: kind === "recruiters" ? "recruiter" : "engineer", previous_id: previous?.id,
  }, sec => writing.set(key, sec))
    .then(d => { drafts.set(key, d); return d as AnyDraft; })
    .catch(err => { draftErrors.set(key, (err as Error).message); throw err; })
    .finally(() => { pending.delete(key); writing.delete(key); });
  pending.set(key, promise);
  promise.catch(() => {});
}

export async function saveDraft(d: AnyDraft, body: string, subject: string) {
  if (d.body === body && (d.subject || "") === subject) return;
  await api.updateDraft(d.id, { body, subject }, { quiet: true });
  Object.assign(d, { body, subject });
}

export { credits };
