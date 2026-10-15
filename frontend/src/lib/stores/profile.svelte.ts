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
