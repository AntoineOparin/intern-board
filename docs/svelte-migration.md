# Svelte and TypeScript migration plan

## Goal
Replace the plain-JavaScript frontend in `board/static/` with **Svelte 5 + TypeScript, built with Vite**, without changing what the app does or how it looks. The Python backend and its API stay as they are.

### Why
The current frontend builds the page by assembling HTML strings: 34 `innerHTML` renders and 107 manual `esc()` calls across about 2,500 lines. That has already caused real bugs:
- whole lists re-rendering and starting duplicate Claude requests (Find People needed a "pending" guard);
- state going stale across screens (the credit count, dropdown labels);
- browser caching of outdated scripts.

Components, reactive state and types remove these problems by design.

## Ground rules
- **No change to behaviour, copy or look.** Each migrated page must match the current one: same API calls, same text, same CSS tokens (light theme only), same keyboard behaviour.
- **One page at a time.** The old frontend keeps working until every page has moved, and every step ends with a working app.
- **No backend changes**, except serving the new build. If an API change seems needed, note it and ask first.
- **Testing:** follow `CLAUDE.md` (real user data, no unprompted Claude or Prospeo calls). Mock the API in frontend tests.

## Target setup
- `frontend/`: a Vite + Svelte 5 + TypeScript project, managed with npm. Node 24 and npm 11 are installed, and pnpm is also available.
  - `src/lib/api.ts`: typed client for every endpoint (list below), including `runJob(kind, payload, onProgress)` with the same polling and 10-minute limit as `IB.runJob`.
  - `src/lib/types.ts`: types for Listing, TrackerItem, Profile, Company, Contact, Document, Job and so on, taken from the API responses.
  - `src/lib/stores/`: shared state (filters, tracker, profile, meta, credits).
  - `src/lib/components/`: Select (replaces `select.js` with an accessible listbox), Drawer, Toast, Tag, Stat, Skeleton and so on.
  - `src/routes/` or `src/pages/`: Board, BestMatches, Companies, Tracker, ToolPage (resume or cover letter), FindPeople, Profile.
  - Routing stays hash-based (`#board`, `#people?listing=…&kind=…`), so existing links and the `view` storage key keep working.
- Styles: start by importing the existing `style.css` tokens globally, then move component styles into `<style>` blocks.
- Build output goes to `board/static/app/`. FastAPI serves it.
  - Option A: mount it at `/` once everything has moved.
  - Option B, during the migration: serve the new app at `/next/` while the old one stays at `/`.
- `./run.sh` must keep working for someone with only Python installed. Commit the built files, or build them in `run.sh` when Node is present. Choose one and document it in the README.
- Dev workflow: `npm run dev` with a Vite proxy forwarding `/api` to `http://127.0.0.1:8766`, a test server started with `INTERN_BOARD_NO_REFRESH=1`.
- Checks: `npm run check` (svelte-check), `npm run build`, and Vitest + @testing-library/svelte for component tests with the API mocked.

## Order of work
1. **Scaffold:** Vite + Svelte + TS project, typed API client, the app shell (sidebar, routing, toast), the build served at `/next/`.
   - **Done when:** the shell loads with the sidebar and every nav item routes to a placeholder, `npm run check` is clean, and the Python tests pass.
2. **Find People**, the most complex page, which proves the approach. Its three steps:
   1. pick a tracked job;
   2. Recruiters or Coffee chats;
   3. the results:
      - person cards with email and LinkedIn rows;
      - Find email, Re-check and Add a person;
      - the out-of-credits states;
      - intro drafts written **only on click**, with Copy, Rewrite, "Why this message" and remaining checks.

   It also includes the Integrations panel on the Profile page.
   - **Done when:** it does the same as `features/people.js`, verified in the browser, and component tests cover the credits states and "no Claude call without a click".
3. **Internship board and Best matches:**
   - filters (custom Select), date or match groups, infinite scroll;
   - the stats strip, the Refresh button and its "Updated … ago" status;
   - "New since last visit" (keys `baseline` and `lastActive`), Track buttons, match badges and reasons.
4. **Tracker:** kanban with drag and drop and keyboard alternatives, plus the side panel (stage, deadline, notes, Documents and People sections).
5. **Resume tailor / Cover letter pages and `doc.html`:** the printable page with the one-page fit check, in-place editing and Save.
6. **Companies and Profile:** watchlist table, add-by-link form, resume upload and extraction, preferences (including LinkedIn Premium), Ranking panel.
7. **Switch over:** serve the new app at `/`, delete the old `board/static/*.js`, `features/` and `select.js`, update the README and CLAUDE.md, and run full browser QA (desktop, and a 400 px narrow width).

Commit after each step on `develop`, with a clear message.

## API to type
- Listings and meta: `GET /api/listings` (query: q, region, category, term, degree, source, since, hide_tracked, sort, offset, limit) and `GET /api/meta`.
- Tracker: `GET /api/tracker`, plus `PUT` and `DELETE /api/tracker/{listing_id}`.
- Companies: `GET` and `POST /api/companies`, plus `PATCH /api/companies/{platform}/{token}`.
- Refresh: `POST /api/refresh`, and `PUT /api/listings/{id}/description`.
- AI jobs: `POST /api/ai/jobs`, `GET /api/ai/jobs/{id}` and `GET /api/ai/status`.
  - Job kinds: `extract_profile`, `fetch_description`, `rank_listings`, `tailor_resume`, `cover_letter`, `outreach`, `people_search`.
- Profile: `GET` and `PUT /api/profile`, plus `POST /api/profile/resume` (multipart).
- Ranking: `GET /api/ranking/status` and `POST /api/ranking/quick`.
- Documents: `GET /api/documents`, `GET`/`PUT`/`DELETE /api/documents/{id}`, and `GET /api/documents/posting/{listing_id}`.
- People:
  - `GET /api/people/session`, `/links`, `/logos` and `/drafts`.
  - `PUT /api/people/site` and `PUT`/`DELETE /api/people/drafts/{id}`.
  - `POST /api/people/email`, `/recheck` and `/contacts`.
  - `DELETE /api/people/contacts/one` and `DELETE /api/people/contacts`.
- Integrations: `GET`, `PUT` and `DELETE /api/integrations/prospeo`.

Read the handlers in `board/*.py` for the exact request and response shapes. Don't guess them.
