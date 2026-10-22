# Intern Board

A personal internship board for software and tech roles in Canada and the US, with an application tracker. It runs locally on your Mac.

## Run

```sh
./run.sh
```

This opens http://localhost:8765. The first start creates a virtualenv and imports the listings, which takes a few seconds. Stop it with Ctrl+C.

## How it works

- **Listings:** come from several sources. The board shows where each one came from.
  - **The [SimplifyJobs Summer 2027 list](https://github.com/SimplifyJobs/Summer2027-Internships):** community-maintained and checked by people. The full list is re-downloaded every hour while the app runs, or when you click **Refresh**.
  - **Company job boards (the watchlist):** the free public feeds and search pages that company job boards publish, read directly. These listings are tagged **Direct**. Supported boards: Greenhouse (including EU boards), Lever (including EU boards), Ashby, Workday, SmartRecruiters, Workable, BambooHR, Rippling, Breezy, Recruiterbox (Trakstar Hire), Oracle Cloud, iCIMS (its own portals and the company career sites built on it, like careers.amd.com), SuccessFactors career sites, Eightfold, Avature and JazzHR.
    - **Company career sites:** Amazon, Google, Microsoft, Apple, Meta, TikTok, ByteDance, Goldman Sachs, IBM and Shopify run their own job sites. `board/sites.py` reads each one like a job board, using the site's own internship filter. These sites aren't published for programs, so they can change without notice; when one stops matching, its listings are kept and the Companies page shows the error. Meta, TikTok and ByteDance don't say when a job was posted, so their postings have no date.
    - **Building the list:** every board the SimplifyJobs list has linked to in the past 18 months is added automatically, and so is every board the Canadian community lists link to. Workday boards are added only if they've had a Canadian internship: there are over a thousand, and SimplifyJobs already covers the US ones. Some company career sites only front a board the app reads (Stripe's, Waymo's and Uber's, for example); links to them count as links to that board.
    - **Montreal employers:** `board/montreal.py` lists 95 boards from about 90 Montreal employers, from banks, CAE and Ubisoft to startups like Ludia, CM Labs and TS Imagine. Their boards are always on the watchlist, because the community lists rarely carry Montreal internships.
    - **Well-known employers:** `board/employers.py` lists about 100 boards and career sites of big software and tech employers, from Stripe, Databricks and Waymo to AMD, Qualcomm, EA and Shopify. Many were never added automatically because the lists link to their own careers sites.
    - **Adding a company:** on the **Companies** tab, paste the company's careers page (like `tsimagine.com/careers`) or any of its job postings. The app finds the job board behind the page. Pages that load their jobs with JavaScript (Wix sites, for example) can't be read; paste a posting's link instead. You can also switch boards off there.
    - **Schedule:** boards that currently have matching internships are checked every hour. All others are checked every 6 hours. A board that no longer exists is switched off automatically.
    - **What's kept:** only titles that are internships or co-ops and look like software or tech roles (software, AI/ML/data, hardware, product, quant). French titles count too: "Stagiaire", "Stage en …", "Étudiant(e)", with terms like "Été 2027". The title filter is deliberately strict. It skips some real tech roles with vague titles, and lets through the odd non-tech one.
    - **Big boards:** Workday, SmartRecruiters, Oracle Cloud, iCIMS, SuccessFactors, Eightfold and Avature boards can hold thousands of jobs, so they're searched for internships instead of read whole (Workday through its "job type" filter where the board has one, Eightfold through its internship filter). Eightfold limits how often it can be asked, so its boards are read one at a time.
    - **Not used:** LinkedIn and Indeed (their terms forbid automated collection, and both block it), Prosple (a bot check on every page), and the career sites of Tesla and Citadel (same). Their internships come only from the community lists.
  - **Four more community lists**, read on every hourly refresh. Each listing links back to its source list.
    - [Canadian Tech Internships 2027](https://github.com/negarprh/Canadian-Tech-Internships-2027) (negarprh): a README table. Rows marked closed are skipped.
    - [Canada Tech Internships Summer 2027](https://github.com/michelleokolie/canada-tech-internships-summer-2027) (michelleokolie): a JSON file.
    - [Frogg Canadian Internships](https://github.com/seun-ipaye/frogg-canadian-internships): a JSON file of Canadian internships, updated every 30 minutes. It has no license file, so its listings link to the employer's posting and show "via Frogg Canadian Internships".
    - [Zapply Internships 2027](https://github.com/zapplyjobs/Internships-2027): a README table of US internships. Only its tech sections are used, and only tech titles are kept. Zapply allows reuse if you credit them and link to the repository, so its listings show "via Zapply" with that link.
  - **Duplicates:** if the same internship appears in several sources, only one copy is kept. The first source in this order wins: SimplifyJobs, company boards, negarprh, michelleokolie, Frogg, Zapply. Matching uses the posting's link where possible, otherwise company plus title.
  - **Locations:** only locations in the US, Canada, or plain "Remote" are kept. Remote roles tied to another country are dropped.
  - **Age:** only listings posted in the last 30 days are shown. Internships you've tracked stay in the tracker regardless of age.
  - **Search:** matches title, company or city, and ignores accents, so "montreal" finds "Montréal".
- **Visa sponsorship:** after each refresh, the descriptions of new US listings are read from their job board's free API (never Claude) and checked for plain statements, such as "we are unable to sponsor visas", "must be a U.S. citizen", "an active security clearance is required" or "visa sponsorship is available". Each listing shows a tag (**Offers sponsorship**, **No sponsorship** or **US citizens only**); hover over it to see the sentence it came from.
  - **Where it comes from:** what the posting says wins. Otherwise the tag comes from the source list: SimplifyJobs marks a few listings, and Zapply marks many with its own estimate. Zapply's estimate shows as **May sponsor** with a dashed outline, since it isn't a statement from the employer; about a fifth of those postings turned out to rule sponsorship out.
  - **The Sponsorship filter:** **Offers sponsorship** (the posting or SimplifyJobs says so), **Offers or may sponsor** (adds Zapply's estimates) and **Not ruled out** (hides listings that say no, or that need US citizenship or a clearance).
  - **Limits:** most postings don't mention sponsorship, and postings on sites the app can't read (Tesla, IBM's posting pages, smaller custom sites) can't be checked, so "Not ruled out" doesn't mean a company will sponsor you. Canadian listings aren't checked.
- **Closed postings:** a listing that leaves the list is marked closed. It stays on your tracker cards with a "Posting closed" tag.
- **New since last visit:** shows listings first seen after your previous visit, based on the last visit time stored in your browser.
- **Tracker:** has five columns (Saved, Applied, Interviewing, Offer, Rejected). Drag cards between columns. Click a card to set a deadline or add notes.
- **Storage:** everything is kept in `data/board.db` (SQLite). Back up that file to keep your tracker.

## AI tools

These run through the Claude Code CLI on your Mac (`claude -p`), using the Claude plan you're logged into. There's no API key and no separate bill, but each request counts toward your plan's usage limits. Requests run in the background, and the page shows progress while they do.

1. **Profile tab:** upload your resume (PDF, .docx or text). Claude turns it into a structured profile; you can check it and fix mistakes there. Also set what you're looking for: roles, categories, Canada/US, terms, graduation, work authorization and school.
   - **Experience and project points:** each bullet from your resume becomes a point (one fact) that can have several phrasings, and an entry can hold more points than fit on one page. Add experiences, projects, points and phrasings yourself, or click **Suggest variations** for Claude's take on other ways to say the same thing; suggestions that change a number or add a claim are dropped, and nothing is added until you keep it. Uploading a new resume keeps your points and adds the new bullets, but replaces skills, education and awards.
2. **Ranking:** every listing gets a quick keyword match score, which takes milliseconds. Under **Profile → Ranking**, "Rank top 40 with Claude" adds a one-sentence reason to each of the top 40. On the board, sort by **Best match**, and click a score to see why.
3. **Tracker side panel → Documents:**
   - **Tailored resume:** a one-page resume for that posting. Claude picks the points and phrasings that fit the job; the text is copied from your profile word for word, never reworded. Open it, edit any text in place, hover a bullet to swap it for another phrasing or point, then **Download PDF** (choose "Save as PDF").
   - **Cover letter:** formal, conversational or enthusiastic tone.
   - **Job description:** fetched automatically. If a site blocks it, paste it in.
   - **Honesty checks:** names, employers, dates and links are copied from your profile, never written by Claude. Each document lists the requirements in the posting that you *don't* meet, and flags any number that isn't in your profile.
4. **Find people** (sidebar): pick a tracked job, then **Recruiters** or **Coffee chats** (people in the role you're applying for).
   - **Data source:** [Prospeo](https://prospeo.io)'s people database. You need a free account (100 credits a month). Put the API key in `.env` as `PROSPEO_API_KEY=...`, or paste it under **My profile → Integrations**.
   - **Credit costs:**
     - A search costs 1 credit when it finds anyone. It looks in the job's country first, which is free if nobody matches, then anywhere.
     - **Find email** costs 1 credit only when Prospeo has a verified email. A ✓ means Prospeo verified it.
   - **Company website:** Prospeo searches by company website. It's taken from the company's own careers link when that matches the company name, and otherwise looked up by Claude. Use **Change website** if it picked the wrong company.
   - **Intro drafts:** nothing is written until you click **Write LinkedIn note** or **Write email**. Each draft is made in four steps (`board/outreach.py`):
     1. A quick brief: why this person, your single best proof for this posting, and one small ask.
     2. The draft itself, using per-channel rules and banned phrases.
     3. Automatic checks for length, stock phrases, invented numbers, placeholders, and claiming you applied when you haven't.
     4. One repair if a check fails.
   - **Notes and emails:** connection notes are limited to 200 characters, LinkedIn's limit for free accounts. Tick **I have LinkedIn Premium** on the Profile page for 300. Emails aim for 60–110 words. **Rewrite** asks for a different angle.
   - **Your data:** people you find are saved only on your Mac. Delete them under **My profile → Integrations**.

## Tests

```sh
.venv/bin/python -m unittest
```

## Frontend development

The frontend is Svelte and TypeScript, in `frontend/`. It builds into `board/static/`, which the app serves. The built files are committed, so `./run.sh` only needs Python. After changing anything in `frontend/`, rebuild and commit the result:

```sh
cd frontend
npm ci
npm run check   # svelte-check
npm test        # Vitest
npm run build   # writes board/static/
```

For live reloading, run a test server with `INTERN_BOARD_NO_REFRESH=1 .venv/bin/uvicorn board.main:app --port 8766`, then `npm run dev` in `frontend/`. Vite forwards `/api` to it.

Browser tests need Node: `cd e2e && npm ci && npx playwright install chromium && npm test`. They run against the built files in `board/static/`, so build first. See `e2e/README.md`.
