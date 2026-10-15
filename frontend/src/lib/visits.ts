// "New since last visit" means since the end of your previous session. Reloads and coming back
// within SESSION_GAP stay in the same session, so they don't reset what counts as new.
// Keys: lastActive and baseline (lastVisit is the legacy name for lastActive).
import { load, remove, store } from "./storage";

const SESSION_GAP = 30 * 60;

export function visitBaseline(): number {
  const now = Math.floor(Date.now() / 1000);
  const lastActive = load<number | null>("lastActive", load<number | null>("lastVisit", null));
  let baseline = load<number | null>("baseline", null);
  if (lastActive === null) baseline = now; // first visit ever: nothing is new yet
  else if (baseline === null || now - lastActive > SESSION_GAP) baseline = lastActive;
  store("baseline", baseline);
  remove("lastVisit");
  markActive();
  return baseline;
}

export function markActive() {
  if (document.visibilityState === "visible") store("lastActive", Math.floor(Date.now() / 1000));
}

export function trackActivity(): () => void {
  const timer = setInterval(markActive, 60 * 1000);
  document.addEventListener("visibilitychange", markActive);
  return () => { clearInterval(timer); document.removeEventListener("visibilitychange", markActive); };
}
