// Response and request shapes of the FastAPI backend (board/*.py). Timestamps are Unix seconds.

export type Region = "US" | "CA" | "REMOTE";
export type Source = "simplify" | "board" | "negarprh" | "michelleokolie" | "zapply";
export type Sort = "posted" | "added" | "company" | "match";
export type Status = "saved" | "applied" | "interviewing" | "offer" | "rejected";

// ---------- listings and meta (main.py) ----------

export interface Listing {
  id: string;
  source: Source;
  company: string;
  title: string;
  url: string;
  locations: string; // " / "-joined
  regions: Region[];
  category: string | null;
  terms: string[];
  degrees: string[];
  sponsorship: string | null;
  date_posted: number | null;
  first_seen: number;
  active: number;
  posting_key: string | null;
  board: string | null;
  tracked_status: Status | null;
  match_score: number | null;
  match_reason: string | null;
  match_method: "quick" | "claude" | null;
}

export interface ListingsPage {
  total: number;
  items: Listing[];
}

export interface ListingQuery {
  q?: string;
  region?: Region | "";
  category?: string;
  term?: string;
  degree?: string;
  source?: Source | "";
  since?: number;
  hide_tracked?: boolean;
  sort?: Sort;
  offset?: number;
  limit?: number;
}

export interface Count<T = string> {
  value: T;
  count: number;
}

export interface Meta {
  last_refresh: number;
  last_error: string;
  active: number;
  regions: Count<Region>[];
  categories: Count<string | null>[];
  terms: Count[];
  degrees: Count[];
  sources: Count<Source>[];
  boards: { total: number; enabled: number | null; hiring: number | null };
}

export type RefreshResult =
  | { status: "ok"; new: number; [key: string]: unknown }
  | { status: "already_running" }
  | { status: "error"; error: string };

// ---------- tracker (main.py) ----------

export interface TrackerItem {
  id: string;
  listing_id: string;
  status: Status;
  notes: string;
  deadline: string | null; // YYYY-MM-DD
  position: number;
  updated_at: number;
  company: string;
  title: string;
  url: string;
  locations: string;
  active: number;
  date_posted: number | null;
  terms: string[];
  regions: Region[];
  degrees: string[];
  category: string | null;
  sponsorship: string | null;
  first_seen: number;
}

export interface TrackerResponse {
  statuses: Status[];
  items: TrackerItem[];
}

export interface TrackerUpdate {
  status?: Status;
  notes?: string;
  deadline?: string; // "" clears it
  position?: number;
}

// ---------- companies (main.py) ----------

export interface Company {
  platform: "greenhouse" | "lever" | "ashby";
  token: string;
  name: string;
  enabled: number;
  origin: "auto" | "manual";
  added_at: number;
  last_checked: number | null;
  last_status: "ok" | "not_found" | "error" | null;
  last_error: string | null;
  jobs_total: number | null;
  interns: number | null;
  listings: number;
  board_url: string;
}

export type AddedCompany = Omit<Company, "listings" | "board_url"> & { kept: number; jobs_total: number };

// ---------- AI jobs (jobs.py) ----------

export type JobKind =
  | "extract_profile" | "fetch_description" | "rank_listings" | "tailor_resume"
  | "cover_letter" | "outreach" | "people_search";

export type JobStatus = "queued" | "running" | "done" | "error";

export interface Job<R = unknown> {
  id: string;
  kind: JobKind;
  listing_id: string | null;
  payload: Record<string, unknown>;
  status: JobStatus;
  result: R | null;
  error: string | null;
  created_at: number;
  started_at: number | null;
  finished_at: number | null;
}

export interface AiStatus {
  claude: boolean;
  kinds: JobKind[];
}

// ---------- profile (profile.py) ----------

export interface ProfileData {
  name?: string;
  email?: string;
  phone?: string;
  location?: string;
  links?: { label: string; url: string }[];
  education?: { school: string; degree: string; field: string; location: string; start: string; end: string; gpa: string; details: string[] }[];
  experience?: { organization: string; role: string; location: string; start: string; end: string; bullets: string[] }[];
  projects?: { name: string; tech: string[]; link: string; date: string; bullets: string[] }[];
  skills?: { languages: string[]; frameworks: string[]; tools: string[]; other: string[] };
  awards?: string[];
  summary?: string;
}

export interface Preferences {
  target_roles: string[];
  categories: string[];
  regions: Region[];
  terms: string[];
  degree_level: string;
  graduation: string;
  work_authorization: string;
  school: string;
  notes: string;
  linkedin_premium: boolean;
}

export interface Profile {
  resume_filename: string | null;
  data: ProfileData; // {} until a resume is read
  preferences: Preferences;
  version: number;
  updated_at: number | null;
  has_resume: boolean;
  resume_chars: number;
  extract_job?: string | null; // only from GET /api/profile
}

// ---------- ranking (ranking.py) ----------

export interface RankingStatus {
  has_profile: boolean;
  profile_version: number;
  active: number;
  quick: number;
  quick_at: number | null;
  claude: number;
  claude_at: number | null;
  unscored: number;
  computed: number;
  running_job: string | null;
}

export interface QuickRankResult {
  computed: number;
  seconds: number;
  status: RankingStatus;
}

export interface RankResult {
  ranked: number;
  requested: number;
  skipped: number;
  batches: number;
  seconds: number;
  failed_batches?: number;
  error?: string | null;
  message?: string;
}

// ---------- documents (documents.py) ----------

export type DocumentKind = "resume" | "cover_letter";

export interface DocumentNotes {
  emphasized?: string[];
  gaps?: string[];
  drew_on?: string[];
  checks?: string[];
  description_used?: boolean;
}

export interface DocumentSummary {
  id: string;
  listing_id: string;
  kind: DocumentKind;
  title: string | null;
  profile_version: number | null;
  created_at: number;
  updated_at: number;
  stale: boolean;
  notes: DocumentNotes;
}

export interface DocHeader {
  name: string;
  contact: string[];
  links: { label: string; url: string }[];
}

export interface ResumeContent {
  header: DocHeader;
  education: { school: string; degree: string; location: string; dates: string; details: string[] }[];
  experience: { organization: string; role: string; location: string; dates: string; bullets: string[] }[];
  projects: { name: string; tech: string; link: string; dates: string; bullets: string[] }[];
  skills: { label: string; items: string[] }[];
  awards: string[];
  notes: DocumentNotes;
}

export interface LetterContent {
  tone: "formal" | "conversational" | "enthusiastic";
  header: DocHeader;
  date: string;
  recipient: string;
  greeting: string;
  paragraphs: string[];
  closing: string;
  signature: string;
  notes: DocumentNotes;
}

interface DocumentBase {
  id: string;
  listing_id: string;
  title: string | null;
  profile_version: number | null;
  created_at: number;
  updated_at: number;
  stale: boolean;
}
export type DocumentRow =
  | (DocumentBase & { kind: "resume"; content: ResumeContent })
  | (DocumentBase & { kind: "cover_letter"; content: LetterContent });
export type FullDocument = DocumentRow & { listing: { company: string; title: string; url: string } | null };

export interface PostingStatus {
  available: boolean;
  source: "api" | "claude" | "pasted" | null;
  fetched_at: number | null;
  chars: number;
}

export interface DescriptionResult {
  text: string | null;
  source: string | null;
  fetched_at: number | null;
}

// ---------- Find People (people.py, contacts.py) ----------

export type PeopleKind = "recruiters" | "team";
export type Channel = "linkedin_note" | "email" | "follow_up";
export type RecipientType = "recruiter" | "engineer" | "alum" | "hiring_manager";

export interface Contact {
  listing_id: string;
  kind: PeopleKind;
  person_id: string; // Prospeo id, or "manual:…" for people you added
  rank: number;
  full_name: string;
  title: string | null;
  city: string | null;
  state: string | null;
  country: string | null;
  linkedin_url: string | null;
  email: string | null;
  email_status: string | null; // VERIFIED, NO_LONGER_VERIFIED, NOT_FOUND, UNAVAILABLE, ADDED…
  found_at: number;
  source: "prospeo" | "manual";
  email_found_at: number | null;
  job_change_at: number | null;
  moved_to: string | null;
  location: string;
  email_stale: boolean;
  recheck_free: boolean;
  new_in_role: boolean;
}

export interface PeopleSearch {
  listing_id: string;
  kind: PeopleKind;
  domain: string;
  total: number;
  country_filtered: number;
  searched_at: number;
  stale: boolean;
}

export interface CompanySite {
  company: string;
  domain: string;
  source: "url" | "claude" | "user";
  prospeo_name: string | null;
  logo_url: string | null;
  updated_at: number;
}

export interface LinkGroup {
  id: "recruiters" | "team" | "alumni" | "google";
  title: string;
  hint: string;
  items: { label: string; url: string; hint: string }[];
  note?: string;
}

export interface SearchLinks {
  company: string;
  keywords: string[];
  school: string;
  groups: LinkGroup[];
}

export interface PeopleSession {
  listing: { id: string; company: string; title: string; locations: string; url: string; category: string | null };
  company: string;
  site: CompanySite | null;
  searches: Partial<Record<PeopleKind, PeopleSearch>>;
  contacts: Record<PeopleKind, Contact[]>;
  team_label: string;
  links: SearchLinks;
  configured: boolean;
}

export interface Draft {
  id: string;
  listing_id: string;
  title: string;
  created_at: number;
  updated_at: number;
  recipient_type: RecipientType;
  channel: Channel;
  recipient_name: string;
  recipient_title: string;
  person_id: string | null;
  context: string;
  subject: string;
  body: string;
  angle: string;
  checks: string[];
  chars: number;
}

export interface OutreachResult {
  document_id: string;
  id: string;
  title: string;
  subject: string;
  body: string;
  angle: string;
  checks: string[];
  channel: Channel;
  person_id: string | null;
  chars: number;
  limit: number | null;
}

export interface PeopleSearchResult {
  count: number;
  free: boolean;
  charged: boolean;
}

export type ProspeoAccount =
  | { configured: false }
  | { configured: true; error: string }
  | {
      configured: true;
      error?: undefined;
      masked: string;
      plan: string | null;
      remaining: number;
      used: number | null;
      renews: string | null;
      low: boolean;
      empty: boolean;
    };
