// An in-memory stand-in for the FastAPI backend. Every /api/* request the page makes is answered
// here from made-up fixtures, and recorded so tests can assert on method, path, query and body.
// Shapes follow the handlers in board/*.py. Anything else that leaves the page is blocked and
// reported, so a test fails if the app reaches the real backend, Claude, Prospeo or the internet.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import type { Page, Route } from "@playwright/test";
import { NOW } from "./clock";

const FIXTURES = fileURLToPath(new URL("../fixtures/", import.meta.url));
export const fixture = <T = any>(name: string): T => JSON.parse(readFileSync(FIXTURES + name, "utf8"));

// A 1x1 PNG, served for fixture logos.
const PNG = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=", "base64");

export type Req = { method: string; path: string; query: Record<string, string>; body: any; raw: string | null };
export type Reply = { status?: number; json?: unknown };
type Handler = (req: Req, api: MockApi) => Reply | Promise<Reply>;
export type JobOutcome = { status: "done" | "error"; result?: any; error?: string; polls?: number };

const KINDS = ["cover_letter", "extract_profile", "fetch_description", "outreach", "people_search", "rank_listings", "tailor_resume"];
const KNOWN_HOST_ASSETS = /^https:\/\/fonts\.(googleapis|gstatic)\.com\//;

/** Mirrors pydantic's 422 body, so the page shows exactly what it would for the real server. */
export const validationError = (field: string, msg: string, type = "string_too_short") => ({
  status: 422, json: { detail: [{ type, loc: ["body", field], msg, input: "", ctx: {} }] },
});
export const detail = (status: number, text: string): Reply => ({ status, json: { detail: text } });

export class MockApi {
  readonly requests: Req[] = [];
  readonly unexpected: string[] = [];
  /** Uncaught page errors a test expects (none today). Any other uncaught error fails the test. */
  readonly allowedPageErrors: RegExp[] = [];
  readonly origin: string;

  // ---- server state (mutable; tests may change it before or after loading the page) ----
  listings: any[] = fixture("listings.json");
  tracker = fixture("tracker.json");
  meta = fixture("meta.json");
  companies = fixture("companies.json").items as any[];
  profile: any = fixture("profile.json");
  ranking: any = fixture("ranking-status.json").with_profile;
  account: any = fixture("prospeo-accounts.json").ok;
  sessions: Record<string, any> = {
    "simplify:acme-swe-27": fixture("people-session-acme.json"),
    "negarprh:maple-firmware": fixture("people-session-maple.json"),
  };
  drafts: any[] = fixture("people-drafts.json").items;
  logos: Record<string, string> = fixture("people-logos.json");
  documents: any[] = fixture("documents.json").list;
  docs: Record<string, any> = { "doc-resume-1": fixture("documents.json").resume, "doc-letter-1": fixture("documents.json").letter };
  postings: Record<string, any> = fixture("documents.json").posting;
  refreshResult: any = { status: "ok", new: 3, simplify_active: 9, closed: 0, boards_checked: 4, seconds: 31.2 };
  addCompanyResult: any = {
    platform: "lever", token: "brightpath", name: "Brightpath", enabled: 1, origin: "manual", added_at: NOW,
    last_checked: NOW, last_status: "ok", last_error: null, jobs_total: 14, interns: 2, kept: 2,
  };
  profileAfterExtract: any = null; // the profile once an extract_profile job finishes

  /** How each AI job kind ends. A function gets the job payload. Defaults are in defaultOutcome(). */
  jobOutcomes: Partial<Record<string, JobOutcome | ((payload: any) => JobOutcome)>> = {};
  readonly jobs = new Map<string, { id: string; kind: string; payload: any; polls: number; outcome?: JobOutcome }>();

  private overrides: { method: string; path: string | RegExp; handler: Handler }[] = [];
  private holds: { method: string; path: string | RegExp; promise: Promise<void> }[] = [];
  private jobSeq = 0;
  private contactSeq = 0;

  constructor(appUrl: string) {
    this.origin = new URL(appUrl).origin;
  }

  // ---------- test helpers ----------

  /** Answer one endpoint differently for this test. Later calls win. */
  on(method: string, path: string | RegExp, handler: Handler | Reply) {
    this.overrides.unshift({ method, path, handler: typeof handler === "function" ? handler : () => handler });
    return this;
  }

  /** Hold matching requests until the returned function is called (for busy states). */
  hold(method: string, path: string | RegExp): () => void {
    let release!: () => void;
    const promise = new Promise<void>(r => { release = r; });
    const entry = { method, path, promise };
    this.holds.push(entry);
    return () => { this.holds.splice(this.holds.indexOf(entry), 1); release(); };
  }

  calls(method: string, path?: string | RegExp): Req[] {
    return this.requests.filter(r => r.method === method && (path === undefined || match(path, r.path)));
  }
  last(method: string, path: string | RegExp): Req | undefined {
    return this.calls(method, path).at(-1);
  }
  /** Board queries, without the "new since last visit" count query (limit=1). */
  listingQueries(): Record<string, string>[] {
    return this.calls("GET", "/api/listings").filter(r => r.query.limit !== "1").map(r => r.query);
  }
  jobRequests(kind?: string): Req[] {
    return this.calls("POST", "/api/ai/jobs").filter(r => !kind || r.body?.kind === kind);
  }
  tracked(id: string) {
    return this.tracker.items.find((i: any) => i.id === id);
  }

  // ---------- routing ----------

  async install(page: Page) {
    this.page = page;
    await page.route("**/*", route => this.route(route));
  }
  private page!: Page;

  private async route(route: Route) {
    const request = route.request();
    const url = new URL(request.url());
    if (url.origin === this.origin && url.pathname.startsWith("/api/")) return this.answer(route, url);
    if (url.origin === this.origin) return route.continue(); // the frontend's own files
    if (KNOWN_HOST_ASSETS.test(url.href)) return route.fulfill({ status: 200, contentType: "text/css", body: "" });
    if (url.hostname === "img.fixture.test") {
      return url.pathname === "/missing.png"
        ? route.fulfill({ status: 404, body: "" })
        : route.fulfill({ status: 200, contentType: "image/png", body: PNG });
    }
    this.unexpected.push(`${request.method()} ${url.href}`);
    return route.abort("blockedbyclient");
  }

  private async answer(route: Route, url: URL) {
    const request = route.request();
    const raw = request.postData();
    let body: any = raw;
    const type = request.headers()["content-type"] || "";
    if (raw && type.includes("application/json")) {
      try { body = JSON.parse(raw); } catch { /* keep raw */ }
    } else if (type.includes("multipart/form-data")) {
      body = { multipart: true, filename: /filename="([^"]+)"/.exec(raw || "")?.[1] ?? null };
    }
    const req: Req = { method: request.method(), path: decodeURIComponent(url.pathname), query: Object.fromEntries(url.searchParams), body, raw };
    this.requests.push(req);

    for (const h of [...this.holds]) if (h.method === req.method && match(h.path, req.path)) await h.promise;

    let reply: Reply | undefined;
    const override = this.overrides.find(o => o.method === req.method && match(o.path, req.path));
    try {
      reply = override ? await override.handler(req, this) : this.handle(req);
    } catch (err) {
      reply = { status: 500, json: { detail: `Mock error: ${(err as Error).message}` } };
    }
    if (!reply) {
      this.unexpected.push(`${req.method} ${url.pathname}${url.search} (no mock)`);
      reply = { status: 501, json: { detail: "Not mocked" } };
    }
    await route.fulfill({ status: reply.status ?? 200, contentType: "application/json", body: JSON.stringify(reply.json ?? null) });
  }

  // ---------- the API, following board/*.py ----------

  private handle(req: Req): Reply | undefined {
    const { method: m, path: p, query: q, body: b } = req;
    let x: RegExpMatchArray | null;

    if (m === "GET" && p === "/api/meta") return { json: this.meta };
    if (m === "GET" && p === "/api/listings") return { json: this.queryListings(q) };
    if (m === "POST" && p === "/api/refresh") {
      if (this.refreshResult.status === "ok") this.meta.last_refresh = NOW;
      return { json: this.refreshResult };
    }
    if (m === "PUT" && (x = p.match(/^\/api\/listings\/(.+)\/description$/))) {
      if (!b?.text || b.text.length < 50) return validationError("text", "String should have at least 50 characters");
      this.postings[x[1]] = { source: "pasted", fetched_at: NOW, chars: b.text.length, available: true };
      return { json: { ok: true } };
    }

    // tracker
    if (m === "GET" && p === "/api/tracker") return { json: this.tracker };
    if (m === "PUT" && (x = p.match(/^\/api\/tracker\/(.+)$/))) return this.track(x[1], b);
    if (m === "DELETE" && (x = p.match(/^\/api\/tracker\/(.+)$/))) {
      this.tracker.items = this.tracker.items.filter((i: any) => i.id !== x![1]);
      return { json: { ok: true } };
    }

    // companies
    if (m === "GET" && p === "/api/companies") return { json: { items: this.companies } };
    if (m === "POST" && p === "/api/companies") {
      const c = { ...this.addCompanyResult, board_url: `https://jobs.lever.co/${this.addCompanyResult.token}` };
      this.companies.push({ ...c, listings: c.kept });
      return { json: this.addCompanyResult };
    }
    if (m === "PATCH" && (x = p.match(/^\/api\/companies\/([^/]+)\/(.+)$/))) {
      const c = this.companies.find(c => c.platform === x![1] && c.token === x![2]);
      if (!c) return detail(404, "Unknown company");
      c.enabled = b.enabled ? 1 : 0;
      return { json: { ok: true } };
    }

    // AI jobs
    if (m === "POST" && p === "/api/ai/jobs") {
      if (!KINDS.includes(b?.kind)) return detail(404, `Unknown job kind: ${b?.kind}`);
      const id = `job${++this.jobSeq}`;
      this.jobs.set(id, { id, kind: b.kind, payload: b.payload || {}, polls: 0 });
      return { json: { job_id: id } };
    }
    if (m === "GET" && (x = p.match(/^\/api\/ai\/jobs\/(.+)$/))) return this.pollJob(x[1]);
    if (m === "GET" && p === "/api/ai/status") return { json: { claude: true, kinds: KINDS } };

    // profile and ranking
    if (m === "GET" && p === "/api/profile") return { json: this.profile };
    if (m === "PUT" && p === "/api/profile") {
      if (b.data !== undefined && b.data !== null) this.profile.data = b.data;
      if (b.preferences) this.profile.preferences = { ...fixture("profile-empty.json").preferences, ...b.preferences };
      this.profile.version += 1;
      this.profile.updated_at = NOW;
      const { extract_job, ...pub } = this.profile;
      return { json: pub };
    }
    if (m === "POST" && p === "/api/profile/resume") {
      const id = `job${++this.jobSeq}`;
      this.jobs.set(id, { id, kind: "extract_profile", payload: {}, polls: 0 });
      return { json: { job_id: id, chars: 3120 } };
    }
    if (m === "GET" && p === "/api/ranking/status") return { json: this.ranking };
    if (m === "POST" && p === "/api/ranking/quick") {
      if (!this.ranking.has_profile) return detail(409, "Add your resume on the Profile tab first.");
      return { json: { computed: 1234, seconds: 0.41, status: this.ranking } };
    }

    // documents
    if (m === "GET" && p === "/api/documents") {
      return { json: { items: this.documents.filter(d => !q.listing_id || d.listing_id === q.listing_id) } };
    }
    if (m === "GET" && (x = p.match(/^\/api\/documents\/posting\/(.+)$/))) {
      return { json: this.postings[x[1]] ?? { available: false, source: null, fetched_at: null, chars: 0 } };
    }
    if ((x = p.match(/^\/api\/documents\/([^/]+)$/))) {
      const doc = this.docs[x[1]];
      if (!doc) return detail(404, "That document doesn't exist.");
      if (m === "GET") return { json: doc };
      if (m === "DELETE") {
        delete this.docs[x[1]];
        this.documents = this.documents.filter(d => d.id !== x![1]);
        return { json: { ok: true } };
      }
      if (m === "PUT") {
        Object.assign(doc, { content: b.content, updated_at: NOW });
        const { listing, ...row } = doc;
        return { json: row };
      }
    }

    // Find People
    if (m === "GET" && p === "/api/people/session") {
      const s = this.sessions[q.listing_id] ?? this.defaultSession(q.listing_id);
      if (!s) return detail(404, "Unknown listing");
      return { json: { ...s, configured: !!this.account.configured } };
    }
    if (m === "GET" && p === "/api/people/logos") return { json: this.logos };
    if (m === "GET" && p === "/api/people/links") return { json: this.sessions[q.listing_id]?.links };
    if (m === "GET" && p === "/api/people/drafts") {
      return { json: { items: this.drafts.filter(d => d.listing_id === q.listing_id).sort((a, b) => b.created_at - a.created_at) } };
    }
    if (m === "PUT" && (x = p.match(/^\/api\/people\/drafts\/(.+)$/))) {
      const d = this.drafts.find(d => d.id === x![1]);
      if (!d) return detail(404, "That draft no longer exists.");
      if (b.subject != null) d.subject = b.subject.trim();
      if (b.body != null) d.body = b.body.trim();
      d.chars = d.body.length;
      d.updated_at = NOW;
      return { json: d };
    }
    if (m === "PUT" && p === "/api/people/site") {
      const domain = String(b.website || "").replace(/^https?:\/\//, "").replace(/^www\./, "").split("/")[0];
      if (!domain.includes(".")) return detail(422, "Enter a website like stripe.com.");
      const s = this.sessions[b.listing_id];
      if (s) s.site = { company: s.company.toLowerCase(), domain, source: "user", prospeo_name: null, logo_url: null, updated_at: NOW };
      return { json: { domain } };
    }
    if (m === "POST" && p === "/api/people/email") {
      return this.updateContact(b, c => c.email ? c : {
        ...c, email: `${c.full_name.split(" ")[0].toLowerCase()}@${this.sessions[b.listing_id]?.site?.domain ?? "example.com"}`,
        email_status: "VERIFIED", email_found_at: NOW, recheck_free: true,
      });
    }
    if (m === "POST" && p === "/api/people/recheck") {
      return this.updateContact(b, c => c.source !== "prospeo" ? null
        : { ...c, email_found_at: NOW, email_stale: false, recheck_free: true, charged: false });
    }
    if (m === "POST" && p === "/api/people/contacts") return this.addContact(b);
    if (m === "DELETE" && p === "/api/people/contacts/one") {
      const list = this.sessions[q.listing_id]?.contacts?.[q.kind] ?? [];
      const i = list.findIndex((c: any) => c.person_id === q.person_id);
      if (i < 0) return detail(404, "Unknown contact");
      list.splice(i, 1);
      return { json: { ok: true } };
    }
    if (m === "DELETE" && p === "/api/people/contacts") {
      let n = 0;
      for (const s of Object.values(this.sessions)) {
        for (const k of ["recruiters", "team"]) { n += s.contacts[k].length; s.contacts[k] = []; }
        s.searches = {};
      }
      return { json: { deleted: n } };
    }
    if (p === "/api/integrations/prospeo") {
      if (m === "GET") return { json: this.account };
      if (m === "PUT") {
        if (!/^[A-Za-z0-9_-]{10,200}$/.test(b?.key || "")) {
          return validationError("key", "String should have at least 10 characters");
        }
        this.account = { ...fixture("prospeo-accounts.json").ok, masked: `${b.key.slice(0, 5)}…${b.key.slice(-4)}` };
        return { json: this.account };
      }
      if (m === "DELETE") {
        this.account = { configured: false };
        return { json: { configured: false } };
      }
    }
    return undefined;
  }

  queryListings(q: Record<string, string>) {
    const trackedIds = new Set(this.tracker.items.map((i: any) => i.id));
    let items = this.listings.filter(l => l.active);
    if (q.source) items = items.filter(l => l.source === q.source);
    for (const word of (q.q || "").toLowerCase().split(/\s+/).filter(Boolean)) {
      items = items.filter(l => `${l.title} ${l.company} ${l.locations}`.toLowerCase().includes(word));
    }
    if (q.region) items = items.filter(l => l.regions.includes(q.region));
    if (q.category) items = items.filter(l => l.category === q.category);
    if (q.term) items = items.filter(l => l.terms.includes(q.term));
    if (q.degree) items = items.filter(l => l.degrees.includes(q.degree));
    if (+q.since) items = items.filter(l => l.first_seen > +q.since);
    if (q.hide_tracked === "true") items = items.filter(l => !trackedIds.has(l.id));
    const desc = (k: string) => (a: any, b: any) => (b[k] ?? -Infinity) - (a[k] ?? -Infinity);
    const sorts: Record<string, (a: any, b: any) => number> = {
      posted: desc("date_posted"),
      added: (a, b) => desc("first_seen")(a, b) || desc("date_posted")(a, b),
      company: (a, b) => a.company.toLowerCase().localeCompare(b.company.toLowerCase()) || desc("date_posted")(a, b),
      match: (a, b) => (a.match_score == null ? 1 : 0) - (b.match_score == null ? 1 : 0) || desc("match_score")(a, b) || desc("date_posted")(a, b),
    };
    items = [...items].sort(sorts[q.sort || "posted"]);
    const offset = +(q.offset || 0), limit = +(q.limit || 50);
    const page = items.slice(offset, offset + limit).map(l => ({
      ...l, tracked_status: this.tracker.items.find((i: any) => i.id === l.id)?.status ?? null,
    }));
    return { total: items.length, items: page };
  }

  private track(id: string, b: any): Reply {
    const listing = this.listings.find(l => l.id === id);
    if (!listing) return detail(404, "Unknown listing");
    let item = this.tracked(id);
    if (!item) {
      const { source, posting_key, board, tracked_status, match_score, match_reason, match_method, ...rest } = listing;
      item = { listing_id: id, status: b.status || "saved", notes: "", deadline: null, position: 0, updated_at: NOW, ...rest };
      this.tracker.items.push(item);
    }
    for (const k of ["status", "notes", "deadline", "position"]) if (b[k] !== undefined && b[k] !== null) item[k] = b[k];
    if (item.deadline === "") item.deadline = null;
    item.updated_at = NOW;
    return { json: { ok: true } };
  }

  private pollJob(id: string): Reply {
    const job = this.jobs.get(id);
    if (!job) return detail(404, "Unknown job");
    if (!job.outcome) {
      const o = this.jobOutcomes[job.kind];
      job.outcome = (typeof o === "function" ? o(job.payload) : o) ?? this.defaultOutcome(job.kind, job.payload);
    }
    const base = { id, kind: job.kind, listing_id: job.payload.listing_id ?? null, payload: job.payload, created_at: NOW, started_at: NOW };
    if (job.polls++ < (job.outcome.polls ?? 0)) return { json: { ...base, status: "running", result: null, error: null, finished_at: null } };
    if (job.outcome.status === "done" && !("_applied" in job)) {
      (job as any)._applied = true;
      this.applyJob(job.kind, job.payload, job.outcome.result);
    }
    return { json: { ...base, status: job.outcome.status, result: job.outcome.result ?? null, error: job.outcome.error ?? null, finished_at: NOW } };
  }

  private defaultOutcome(kind: string, payload: any): JobOutcome {
    switch (kind) {
      case "outreach": {
        const id = `draft-new-${this.jobSeq}`;
        const email = payload.channel === "email";
        const body = email
          ? "Hi Jordan,\n\nI'm a computer engineering student applying to Acme's software internship. Could you tell me which teams take interns?\n\nThanks,\nSam"
          : "Hi, I'm applying to Acme's Summer 2027 software internship and built a Python service at Harbourview Labs. Could I ask how your intern team works?";
        return { status: "done", result: {
          document_id: id, id, title: `${email ? "Email" : "LinkedIn note"} · recruiter`, subject: email ? "Question about Summer 2027 internships" : "",
          body, angle: "Asks one small question about the intern team.", checks: [], channel: payload.channel, person_id: payload.person_id,
          chars: body.length, limit: email ? null : 200,
        } };
      }
      case "people_search": return { status: "done", result: { count: 0, free: false, charged: true } };
      case "tailor_resume": return { status: "done", result: { document_id: "doc-resume-new" } };
      case "cover_letter": return { status: "done", result: { document_id: "doc-letter-new" } };
      case "fetch_description": return { status: "done", result: { text: "Full job description. ".repeat(20), source: "claude", fetched_at: NOW } };
      case "rank_listings": return { status: "done", result: { ranked: 40, requested: 40, skipped: 0, batches: 2, failed_batches: 0, error: null, seconds: 52.3 } };
      case "extract_profile": return { status: "done", result: { ok: true } };
    }
    return { status: "error", error: "Unknown job" };
  }

  /** Server-side effects of a finished job, so the next GET reflects it. */
  private applyJob(kind: string, payload: any, result: any) {
    if (kind === "outreach") {
      this.drafts.push({ ...result, listing_id: payload.listing_id, created_at: NOW + this.jobSeq, updated_at: NOW,
                         recipient_type: payload.recipient_type, context: "" });
    } else if (kind === "people_search") {
      const s = this.sessions[payload.listing_id];
      if (s) s.searches[payload.kind] = { listing_id: payload.listing_id, kind: payload.kind, domain: s.site?.domain ?? "example.com",
                                           total: 0, country_filtered: 1, searched_at: NOW, stale: false };
    } else if (kind === "tailor_resume" || kind === "cover_letter") {
      const resume = kind === "tailor_resume";
      const base = structuredClone(this.docs[resume ? "doc-resume-1" : "doc-letter-1"] ?? fixture("documents.json")[resume ? "resume" : "letter"]);
      const doc = { ...base, id: result.document_id, listing_id: payload.listing_id, created_at: NOW, updated_at: NOW, stale: false, profile_version: 7 };
      this.docs[doc.id] = doc;
      const { content, listing, ...row } = doc;
      this.documents.unshift({ ...row, notes: content.notes });
    } else if (kind === "fetch_description" && result?.text) {
      this.postings[payload.listing_id] = { source: "claude", fetched_at: NOW, chars: result.text.length, available: true };
    } else if (kind === "extract_profile" && this.profileAfterExtract) {
      this.profile = this.profileAfterExtract;
    }
  }

  private defaultSession(listingId: string) {
    const item = this.tracked(listingId) ?? this.listings.find(l => l.id === listingId);
    if (!item) return null;
    const maple = fixture("people-session-maple.json");
    return {
      ...maple,
      listing: { id: item.id, company: item.company, title: item.title, locations: item.locations, url: item.url, category: item.category },
      company: item.company,
    };
  }

  private updateContact(b: any, change: (c: any) => any): Reply {
    const list = this.sessions[b.listing_id]?.contacts?.[b.kind] ?? [];
    const i = list.findIndex((c: any) => c.person_id === b.person_id);
    if (i < 0) return detail(404, "Unknown contact");
    const next = change(list[i]);
    if (!next) return detail(404, "Only people found through Prospeo can be re-checked.");
    const { charged, ...stored } = next;
    list[i] = stored;
    return { json: next };
  }

  private addContact(b: any): Reply {
    if (!["recruiters", "team"].includes(b.kind)) return detail(422, "Choose recruiters or coffee chats.");
    if ((b.full_name || "").length < 2) return validationError("full_name", "String should have at least 2 characters");
    const linkedin = (b.linkedin_url || "").trim();
    if (linkedin && !/^(https?:\/\/)?([a-z]{2,3}\.)?linkedin\.com\/in\/[^\s/]+\/?/i.test(linkedin)) {
      return detail(422, "Paste a LinkedIn profile link like linkedin.com/in/their-name.");
    }
    const email = (b.email || "").trim();
    if (email && !/^[^@\s]+@[^@\s]+\.[a-z]{2,}$/i.test(email)) return detail(422, "That email address doesn't look right.");
    const s = this.sessions[b.listing_id] ?? (this.sessions[b.listing_id] = this.defaultSession(b.listing_id));
    if (!s) return detail(404, "Unknown listing");
    const contact = {
      listing_id: b.listing_id, kind: b.kind, person_id: `manual:new${++this.contactSeq}`, rank: s.contacts[b.kind].length,
      full_name: b.full_name.trim(), title: (b.title || "").trim() || null, city: null, state: null, country: null,
      linkedin_url: linkedin ? (linkedin.startsWith("http") ? linkedin : `https://${linkedin}`) : null,
      email: email || null, email_status: email ? "ADDED" : null, found_at: NOW, source: "manual", email_found_at: null,
      job_change_at: null, moved_to: null, location: "", email_stale: false, recheck_free: false, new_in_role: false,
    };
    s.contacts[b.kind].push(contact);
    return { json: contact };
  }
}

function match(pattern: string | RegExp, path: string) {
  return typeof pattern === "string" ? pattern === path : pattern.test(path);
}
