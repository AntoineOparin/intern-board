import * as api from "../api";
import type { Profile } from "../types";

export const profile = $state({ data: null as Profile | null });

export const hasProfileData = () => !!profile.data && Object.keys(profile.data.data).length > 0;
/** LinkedIn allows 200-character notes on free accounts and 300 on Premium. */
export const noteLimit = () => (profile.data?.preferences?.linkedin_premium ? 300 : 200);

export async function loadProfile(): Promise<Profile> {
  const p = await api.profile();
  profile.data = p;
  return p;
}

// ---------- resume extraction ----------
// Lives here, not in the page, so leaving and revisiting My profile doesn't start a second loop.

/** A status line that overrides the one derived from the profile (upload progress, errors). */
export const resumeStatus = $state({ override: null as null | { text: string; kind: string } });
let extracting: string | null = null;

export async function refreshProfile() {
  try {
    const fresh = await loadProfile();
    resumeStatus.override = null;
    if (fresh.extract_job) waitForExtraction(fresh.extract_job);
  } catch { /* the request showed a toast */ }
}

export async function waitForExtraction(jobId: string) {
  if (extracting === jobId) return;
  extracting = jobId;
  const started = Date.now();
  try {
    for (;;) {
      await new Promise(r => setTimeout(r, 2000));
      const job = await api.job(jobId);
      if (job.status === "error") { resumeStatus.override = { text: job.error || "", kind: "error" }; return; }
      if (job.status === "done") { extracting = null; await refreshProfile(); return; }
      if (Date.now() - started > 10 * 60 * 1000) {
        resumeStatus.override = { text: "Reading your resume is taking too long. The app may have restarted; upload it again.", kind: "error" };
        return;
      }
    }
  } catch { /* shown */ } finally {
    if (extracting === jobId) extracting = null;
  }
}

export async function uploadResume(file: File) {
  resumeStatus.override = { text: `Uploading ${file.name}…`, kind: "busy" };
  try {
    const r = await api.uploadResume(file, { quiet: true });
    resumeStatus.override = { text: "Claude is reading your resume… (about 20–40 seconds)", kind: "busy" };
    await waitForExtraction(r.job_id);
  } catch (err) {
    resumeStatus.override = { text: (err as Error).message, kind: "error" };
  }
}
