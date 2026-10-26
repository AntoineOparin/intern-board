# Intern Board

A personal, local web app: software and tech internships in Canada and the US, an application tracker, and AI tools (ranking, tailored resumes, cover letters, Find People with intro drafts). It's single-user and runs only on this Mac. README.md describes the features for users; this file is for working on the code.

## Stack and layout
- **Backend:** Python 3.14, FastAPI and SQLite, in `board/`. Dependencies are in `requirements.txt` and the virtualenv is at `.venv/`.
  - `main.py`: app, listings/tracker/companies/meta API, AI job endpoints, static file serving.
  - `sources.py`: hourly refresh. Pulls SimplifyJobs, company boards (`ats.py`: Greenhouse, Lever, Ashby, Workday, SmartRecruiters, Workable, BambooHR, Rippling, Breezy, Recruiterbox, Oracle Cloud, iCIMS portals and "Jibe" career sites, SuccessFactors, Eightfold, Avature, JazzHR, plus finding the board behind a careers page) and other GitHub lists (`community.py`). Handles de-duplication and dates "first seen". `montreal.py` and `employers.py` list Montreal and well-known employers' boards that are always watched.
  - `sites.py`: big companies' own career sites (Amazon, Google, Microsoft, Apple, Meta, TikTok, ByteDance, Goldman Sachs, IBM, Shopify), each a board on the `site` platform, and `FRONTS`, career sites in front of a supported board. They aren't published for programs: a reader that stops matching must raise, never return an empty list, and a 404 must not switch the board off. `ats.py` imports it last, since it builds on `ats.py`.
  - `locations.py`: decides whether a location is US, Canada, remote, or neither (accents, French, city-only names). `fold()` is also the accent-insensitive search.
  - `visa.py`: after each refresh, reads new US postings through their board's API (`postings.api_text`, no Claude) for sponsorship statements, stored in `listings.visa` with the sentence. Zapply's sponsor flag is only an estimate ("May Offer Sponsorship") and must not be shown as the employer's statement.
  - `db.py`: schema and in-place migrations (`MIGRATIONS`), plus `visible()`, which hides listings older than 30 days.
  - `ai.py`: calls the local **Claude Code CLI** (`claude -p`) on the user's plan. There's no API key.
  - `jobs.py`: background AI jobs. The browser starts one and polls it.
  - `profile.py`: resume upload and extraction, preferences, and the points model: each experience or project bullet is a point with one or more phrasings (`normalize()` converts legacy `bullets`; `flat_data()` is what prompts other than tailoring see). A re-upload merges (`merge_profile`), `suggest_phrasings` is the job behind "Suggest variations", and `version` bumps only when facts change, never for an extra phrasing.
  - `postings.py`: full job descriptions (job-board APIs, or Claude WebFetch).
  - Features: `ranking.py`, `documents.py` (tailored resume, cover letter; edits may add formatting: runs inside lines, `format`, `headings`, validated on save), `docx_export.py` (the Word file, standard library only), `people.py` (search links, outreach job), `outreach.py` (writing chain: brief → write → check → repair), `contacts.py` (Find People via Prospeo), `prospeo.py` (API client), `settings.py` (`.env`).
- **Frontend:** Svelte 5 + TypeScript + Vite in `frontend/`. It builds into `board/static/`, which FastAPI serves at `/`. The build is committed so `./run.sh` needs only Python. **Never edit `board/static/` by hand**; it's overwritten by every build.
  - `src/lib/api.ts`: typed client for every endpoint, plus `runJob()` (polling, 10-minute limit). `src/lib/types.ts`: response shapes.
  - `src/lib/stores/`: shared state (router, filters, board, meta, tracker, profile, ranking, companies, credits, people, documents, drawer, toast). State that must survive leaving a page, such as running AI jobs or polling loops, lives here, not in components.
  - `src/lib/components/`: `Select` (accessible custom dropdown), `Drawer` (tracker side panel), `Sidebar`, `Toast`, `Icon`.
  - `src/pages/`: board, tracker, companies, documents (tool pages and the Documents section), people (Find People), profile, doc (`doc.html`, a second Vite entry, with `FormatBar` and the `editable` action).
  - `src/lib/richtext.ts`: formatted lines on the document page. A line is a string, or runs (`{t, b, i, u, c}`) when part of it is formatted. Unformatted lines are saved as plain strings, so older documents keep working. Styles are keyed by content path (`experience.0.bullets.2`).
  - `src/styles/`: `style.css` (tokens at the top) and per-feature styles.
  - After a change, run `npm run check`, `npm test` and `npm run build` in `frontend/`, and commit the build with the source.
- **Tests:** stdlib `unittest` in `tests/`. Run them with `.venv/bin/python -m unittest`. Claude and Prospeo are always mocked.
- **Frontend tests:** Vitest component tests in `frontend/src/**/*.test.ts`. Playwright tests in `e2e/` (`cd e2e && npm test`; see `e2e/README.md`) run against the build, with every `/api/*` call answered by made-up fixtures. Neither ever uses the real database, Claude or Prospeo.

## Running
- `./run.sh` serves http://localhost:8765 and refreshes listings hourly.
- For a dev or test server: `INTERN_BOARD_NO_REFRESH=1 .venv/bin/uvicorn board.main:app --host 127.0.0.1 --port <port>`. Use a port other than 8765 if the user's own app may be running, and stop only your own server (`pkill -f 'port <port>'`).

## Rules that matter
- **`data/board.db` holds the user's real data:** resume, profile, tracker, contacts, drafts and generated documents. Never delete or rewrite it in bulk. Clean up only rows you created while testing.
- **`.env` holds `PROSPEO_API_KEY`.** Never print it, log it, commit it, or send it to the browser. `data/`, `.env` and `.venv/` are git-ignored, and must stay that way.
- **Paid and metered calls:**
  - Prospeo searches cost 1 credit each, and so do email reveals. The free plan has 100 credits a month.
  - Every Claude call uses the user's plan.
  - In tests, mock both. For manual checks, ask before spending credits, and keep real Claude calls to a handful.
- **Never call Claude without a click.** The AI features (drafts, tailoring, cover letters, ranking) only start from a user's click or a resume upload.
- **AI output must stay honest.** Prompts include `ai.HONESTY_RULES`, and facts come from the profile. Keep the existing checks: invented numbers, claims to have applied when the user hasn't, banned phrases, and LinkedIn's note limit (200 characters free, 300 Premium).
- **Copy style:** plain, specific language; sentence case; no exclamation marks; no hype words.
- **UI:**
  - Light theme only. Use the CSS tokens at the top of `frontend/src/styles/style.css`, never hard-coded colours.
  - The left sidebar is modelled on InternDock.
  - Keyboard access and visible focus are required.
- **Browser storage keys** in use: `filters`, `view`, `baseline`, `lastActive`, `toolListing` (`lastVisit` is legacy). Keep them compatible so users don't lose their settings.

## Git
- Work on `develop`. `main` is the stable branch, updated by merging `develop`.
- End commit messages with the attribution line the harness provides.
