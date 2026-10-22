// Tailored resumes, cover letters and job descriptions for a tracked listing.
// Jobs keep running when the side panel closes; reopening it (or the tool page) shows their progress.
import { SvelteMap } from "svelte/reactivity";
import * as api from "../api";
import type { DescriptionResult, DocumentNotes, DocumentKind } from "../types";

export const KIND_LABEL: Record<DocumentKind, string> = { resume: "Resume", cover_letter: "Cover letter" };
export type DocMsg = { text: string; kind: "" | "busy" | "ok" | "error" };

/** listing id -> the job running for it ({label, seconds}). */
export const running = new SvelteMap<string, { label: string; seconds: number }>();
/** listing id -> the last message to show in its Documents section. */
export const messages = new SvelteMap<string, DocMsg>();
/** listing id -> notes from the last document written this session. */
export const lastNotes = new SvelteMap<string, DocumentNotes | undefined>();
/** listing id -> bumped when its documents or description change, so open sections reload. */
export const versions = new SvelteMap<string, number>();
/** listing id -> open the paste box (the description couldn't be loaded). */
export const openPaste = new SvelteMap<string, boolean>();

const bump = (id: string) => versions.set(id, (versions.get(id) ?? 0) + 1);

type Outcome<R> = { ok: true; result: R } | { ok: false };

async function start<R>(listingId: string, kind: "tailor_resume" | "cover_letter" | "fetch_description",
  payload: Record<string, unknown>, label: string): Promise<Outcome<R>> {
  if (running.has(listingId)) return { ok: false };
  running.set(listingId, { label, seconds: 0 });
  messages.set(listingId, { text: `${label} 0s`, kind: "busy" });
  try {
    const result = await api.runJob<R>(kind, payload, s => {
      running.set(listingId, { label, seconds: s });
      messages.set(listingId, { text: `${label} ${s}s`, kind: "busy" });
    });
    return { ok: true, result };
  } catch (err) {
    messages.set(listingId, { text: (err as Error).message, kind: "error" });
    return { ok: false };
  } finally {
    running.delete(listingId);
  }
}

/** Claude writes a tailored resume or cover letter. Runs only from a click. */
export async function writeDocument(listingId: string, kind: DocumentKind, tone?: string) {
  const job = kind === "resume" ? "tailor_resume" : "cover_letter";
  const label = kind === "resume" ? "Tailoring resume…" : "Writing cover letter…";
  const payload = { listing_id: listingId, ...(kind === "cover_letter" ? { tone } : {}) };
  const outcome = await start<{ document_id: string }>(listingId, job, payload, label);
  if (!outcome.ok) return;
  bump(listingId);
  try {
    const doc = await api.document(outcome.result.document_id, { quiet: true });
    lastNotes.set(listingId, doc.content.notes);
  } catch { /* notes are optional */ }
  messages.set(listingId, { text: `${KIND_LABEL[kind]} ready. Open it to review, edit and download.`, kind: "ok" });
}

/** Load the job description (from the job board's API, or Claude reading the page). */
export async function loadDescription(listingId: string) {
  const outcome = await start<DescriptionResult>(listingId, "fetch_description", { listing_id: listingId }, "Loading job description…");
  if (!outcome.ok) return;
  bump(listingId);
  if (outcome.result?.text) messages.set(listingId, { text: "Job description loaded.", kind: "ok" });
  else {
    messages.set(listingId, { text: "Couldn't load the job description. Paste it below instead.", kind: "error" });
    openPaste.set(listingId, true);
  }
}

export async function pasteDescription(listingId: string, text: string): Promise<boolean> {
  if (text.length < 50) {
    messages.set(listingId, { text: "Paste the full job description (at least 50 characters).", kind: "error" });
    return false;
  }
  try {
    await api.pasteDescription(listingId, text, { quiet: true });
    messages.set(listingId, { text: "Job description saved. New documents will use it.", kind: "ok" });
    bump(listingId);
    return true;
  } catch (err) {
    messages.set(listingId, { text: (err as Error).message, kind: "error" });
    return false;
  }
}
