# Intern Board

A personal, local web app: software and tech internships in Canada and the US, an application tracker, and AI tools (ranking, tailored resumes, cover letters, Find People with intro drafts). It's single-user and runs only on this Mac. README.md describes the features for users; this file is for working on the code.

## Stack and layout
- **Backend:** Python 3.14, FastAPI and SQLite, in `board/`. Dependencies are in `requirements.txt` and the virtualenv is at `.venv/`.
  - `main.py`: app, listings/tracker/companies/meta API, AI job endpoints, static file serving.
  - `sources.py`: hourly refresh. Pulls SimplifyJobs, company boards (`ats.py`: Greenhouse, Lever, Ashby) and other GitHub lists (`community.py`). Handles de-duplication and dates "first seen".
  - `locations.py`: decides whether a location is US, Canada, remote, or neither.
  - `db.py`: schema and in-place migrations (`MIGRATIONS`), plus `visible()`, which hides listings older than 30 days.
  - `ai.py`: calls the local **Claude Code CLI** (`claude -p`) on the user's plan. There's no API key.
  - `jobs.py`: background AI jobs. The browser starts one and polls it.
  - `profile.py`: resume upload and extraction, and preferences.
  - `postings.py`: full job descriptions (job-board APIs, or Claude WebFetch).
  - Features: `ranking.py`, `documents.py` (tailored resume, cover letter), `people.py` (search links, outreach job), `outreach.py` (writing chain: brief → write → check → repair), `contacts.py` (Find People via Prospeo), `prospeo.py` (API client), `settings.py` (`.env`).
- **Frontend:** Svelte 5 + TypeScript + Vite in `frontend/`. It builds into `board/static/`, which FastAPI serves at `/`. The build is committed so `./run.sh` needs only Python. **Never edit `board/static/` by hand**; it's overwritten by every build.
  - `src/lib/api.ts`: typed client for every endpoint, plus `runJob()` (polling, 10-minute limit). `src/lib/types.ts`: response shapes.
  - `src/lib/stores/`: shared state (router, filters, board, meta, tracker, profile, ranking, companies, credits, people, documents, drawer, toast). State that must survive leaving a page, such as running AI jobs or polling loops, lives here, not in components.
  - `src/lib/components/`: `Select` (accessible custom dropdown), `Drawer` (tracker side panel), `Sidebar`, `Toast`, `Icon`.
  - `src/pages/`: board, tracker, companies, documents (tool pages and the Documents section), people (Find People), profile, doc (`doc.html`, a second Vite entry).
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
