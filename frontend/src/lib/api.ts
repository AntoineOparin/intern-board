// Typed client for every backend endpoint (board/*.py). Errors behave like the old api():
// a failed request shows a toast unless `quiet`, and throws an ApiError whose message is fit to show.
import { toast } from "./stores/toast.svelte";
import type * as T from "./types";

export class ApiError extends Error {
  constructor(message: string, readonly status: number, public shown = false) {
    super(message);
  }
}

type Options = { method?: string; body?: unknown; quiet?: boolean };

// FastAPI sends a string for errors the app raises, and a list of field errors for validation.
export function errorDetail(detail: unknown): string | null {
  if (typeof detail === "string") return detail;
  if (!Array.isArray(detail)) return null;
  return detail.map((d: { loc?: unknown[]; msg?: string }) => {
    const field = String(d.loc?.at(-1) ?? "").replace(/_/g, " ");
    return field ? `${field[0].toUpperCase()}${field.slice(1)}: ${d.msg}` : String(d.msg);
  }).join("; ");
}

export async function request<R>(path: string, { method = "GET", body, quiet = false }: Options = {}): Promise<R> {
  let res: Response;
  try {
    const isForm = body instanceof FormData; // uploads set their own content type
    res = await fetch(path, {
      method,
      headers: body === undefined || isForm ? {} : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : isForm ? body : JSON.stringify(body),
    });
  } catch {
    const message = "Couldn't reach Intern Board. Is ./run.sh still running?";
    toast(message);
    throw new ApiError(message, 0, true);
  }
  if (!res.ok) {
    let detail = String(res.status);
    try { detail = errorDetail((await res.json()).detail) ?? detail; } catch { /* not JSON */ }
    if (!quiet) toast(`Request failed: ${detail}`);
    throw new ApiError(detail, res.status, !quiet);
  }
  return res.json() as Promise<R>;
}

// A failed request has already been shown in a toast; don't also report it as an uncaught error.
if (typeof window !== "undefined") {
  window.addEventListener("unhandledrejection", e => { if (e.reason instanceof ApiError && e.reason.shown) e.preventDefault(); });
}

const enc = encodeURIComponent;
const query = (params: Record<string, string | number | boolean | undefined | null>) => {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "" && v !== false) p.set(k, String(v));
  return p.toString();
};
type Quiet = { quiet?: boolean };

// ---------- listings, meta, refresh ----------
export const listings = (q: T.ListingQuery) => request<T.ListingsPage>(`/api/listings?${query({ ...q })}`);
export const meta = () => request<T.Meta>("/api/meta");
export const refresh = () => request<T.RefreshResult>("/api/refresh", { method: "POST" });
export const pasteDescription = (listingId: string, text: string, o: Quiet = {}) =>
  request<{ ok: true }>(`/api/listings/${enc(listingId)}/description`, { method: "PUT", body: { text }, ...o });

// ---------- tracker ----------
export const tracker = () => request<T.TrackerResponse>("/api/tracker");
export const track = (listingId: string, update: T.TrackerUpdate) =>
  request<{ ok: true }>(`/api/tracker/${enc(listingId)}`, { method: "PUT", body: update });
export const untrack = (listingId: string) => request<{ ok: true }>(`/api/tracker/${enc(listingId)}`, { method: "DELETE" });

// ---------- companies ----------
export const companies = () => request<{ items: T.Company[] }>("/api/companies");
export const addCompany = (url: string, name: string | null, o: Quiet = {}) =>
  request<T.AddedCompany>("/api/companies", { method: "POST", body: { url, name }, ...o });
export const setCompanyEnabled = (platform: string, token: string, enabled: boolean) =>
  request<{ ok: true }>(`/api/companies/${enc(platform)}/${enc(token)}`, { method: "PATCH", body: { enabled } });

// ---------- AI jobs ----------
export const startJob = (kind: T.JobKind, payload: Record<string, unknown> = {}) =>
  request<{ job_id: string }>("/api/ai/jobs", { method: "POST", body: { kind, payload } });
export const job = <R = unknown>(id: string, o: Quiet = {}) => request<T.Job<R>>(`/api/ai/jobs/${enc(id)}`, o);
export const aiStatus = () => request<T.AiStatus>("/api/ai/status");

export const JOB_POLL_MS = 1500;
export const JOB_LIMIT_MS = 10 * 60 * 1000;

/** Start an AI job and wait for it (same polling and 10-minute limit as the old IB.runJob).
 *  Resolves with the result; rejects with an Error fit to show. */
export async function runJob<R = unknown>(kind: T.JobKind, payload: Record<string, unknown> = {},
  onProgress?: (seconds: number, status: T.JobStatus) => void): Promise<R> {
  const { job_id } = await startJob(kind, payload);
  const started = Date.now();
  for (;;) {
    await new Promise(r => setTimeout(r, JOB_POLL_MS));
    const j = await job<R>(job_id);
    onProgress?.(Math.round((Date.now() - started) / 1000), j.status);
    if (j.status === "done") return j.result as R;
    if (j.status === "error") throw new Error(j.error || "The AI request failed.");
    if (Date.now() - started > JOB_LIMIT_MS) throw new Error("This is taking too long. The app may have restarted; try again.");
  }
}

// ---------- profile and ranking ----------
export const profile = () => request<T.Profile>("/api/profile");
export const updateProfile = (update: { data?: T.ProfileData; preferences?: T.Preferences }) =>
  request<T.Profile>("/api/profile", { method: "PUT", body: update });
export function uploadResume(file: File, o: Quiet = {}) {
  const body = new FormData();
  body.append("file", file);
  return request<{ job_id: string; chars: number }>("/api/profile/resume", { method: "POST", body, ...o });
}
export const rankingStatus = (o: Quiet = {}) => request<T.RankingStatus>("/api/ranking/status", o);
export const rankQuick = (o: Quiet = {}) => request<T.QuickRankResult>("/api/ranking/quick", { method: "POST", ...o });

// ---------- documents ----------
export const documents = (listingId: string, o: Quiet = {}) =>
  request<{ items: T.DocumentSummary[] }>(`/api/documents?${query({ listing_id: listingId })}`, o);
export const document = (id: string, o: Quiet = {}) => request<T.FullDocument>(`/api/documents/${enc(id)}`, o);
export const saveDocument = (id: string, content: T.ResumeContent | T.LetterContent) =>
  request<T.DocumentRow>(`/api/documents/${enc(id)}`, { method: "PUT", body: { content } });
export const deleteDocument = (id: string) => request<{ ok: true }>(`/api/documents/${enc(id)}`, { method: "DELETE" });
export const postingStatus = (listingId: string, o: Quiet = {}) =>
  request<T.PostingStatus>(`/api/documents/posting/${enc(listingId)}`, o);

// ---------- Find People ----------
export const peopleSession = (listingId: string) =>
  request<T.PeopleSession>(`/api/people/session?${query({ listing_id: listingId })}`);
export const peopleLinks = (listingId: string) => request<T.SearchLinks>(`/api/people/links?${query({ listing_id: listingId })}`);
export const peopleLogos = (o: Quiet = {}) => request<Record<string, string>>("/api/people/logos", o);
export const drafts = (listingId: string, o: Quiet = {}) =>
  request<{ items: T.Draft[] }>(`/api/people/drafts?${query({ listing_id: listingId })}`, o);
export const updateDraft = (id: string, update: { subject?: string; body?: string }, o: Quiet = {}) =>
  request<T.Draft>(`/api/people/drafts/${enc(id)}`, { method: "PUT", body: update, ...o });
export const deleteDraft = (id: string) => request<{ ok: true }>(`/api/people/drafts/${enc(id)}`, { method: "DELETE" });
export const setSite = (listingId: string, website: string) =>
  request<{ domain: string }>("/api/people/site", { method: "PUT", body: { listing_id: listingId, website } });
type PersonRef = { listing_id: string; kind: T.PeopleKind; person_id: string };
export const revealEmail = (ref: PersonRef, o: Quiet = {}) => request<T.Contact>("/api/people/email", { method: "POST", body: ref, ...o });
export const recheck = (ref: PersonRef, o: Quiet = {}) =>
  request<T.Contact & { charged: boolean }>("/api/people/recheck", { method: "POST", body: ref, ...o });
export const addContact = (body: { listing_id: string; kind: T.PeopleKind; full_name: string; title: string; linkedin_url: string; email: string }, o: Quiet = {}) =>
  request<T.Contact>("/api/people/contacts", { method: "POST", body, ...o });
export const removeContact = (ref: PersonRef) => request<{ ok: true }>(`/api/people/contacts/one?${query(ref)}`, { method: "DELETE" });
export const forgetContacts = () => request<{ deleted: number }>("/api/people/contacts", { method: "DELETE" });

// ---------- integrations ----------
export const prospeo = (o: Quiet = {}) => request<T.ProspeoAccount>("/api/integrations/prospeo", o);
export const setProspeoKey = (key: string, o: Quiet = {}) =>
  request<T.ProspeoAccount>("/api/integrations/prospeo", { method: "PUT", body: { key }, ...o });
export const removeProspeoKey = () => request<{ configured: boolean }>("/api/integrations/prospeo", { method: "DELETE" });
