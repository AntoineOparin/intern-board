// Every test runs with the page clock frozen here (timers still run), so "2h ago", date groups,
// deadlines and "new since last visit" are the same on every run. Fixture timestamps are relative
// to it: Wednesday 14 October 2026, 14:00 in Toronto (the tests' time zone).
export const NOW = 1792000800;
export const NOW_MS = NOW * 1000;
export const HOUR = 3600;
export const DAY = 86400;
