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
  - **Company job boards (the watchlist):** the free public feeds that Greenhouse, Lever and Ashby publish for each company's board, read directly. These listings are tagged **Direct**.
    - **Building the list:** every board the SimplifyJobs list has linked to in the past 18 months is added automatically. You can add others on the **Companies** tab by pasting a board link, or switch boards off there.
    - **Schedule:** boards that currently have matching internships are checked every hour. All others are checked every 6 hours. A board that no longer exists is switched off automatically.
    - **What's kept:** only titles that are internships or co-ops and look like software or tech roles (software, AI/ML/data, hardware, product, quant). The title filter is deliberately strict. It skips some real tech roles with vague titles, and lets through the odd non-tech one.
    - **Duplicates:** if the same posting is on both sources, it's shown once, from SimplifyJobs.
  - **Three more community lists**, read on every hourly refresh. Each listing links back to its source list.
    - [Canadian Tech Internships 2027](https://github.com/negarprh/Canadian-Tech-Internships-2027) (negarprh): a README table. Rows marked closed are skipped.
    - [Canada Tech Internships Summer 2027](https://github.com/michelleokolie/canada-tech-internships-summer-2027) (michelleokolie): a JSON file.
    - [Zapply Internships 2027](https://github.com/zapplyjobs/Internships-2027): a README table of US internships. Only its tech sections are used, and only tech titles are kept. Zapply allows reuse if you credit them and link to the repository, so its listings show "via Zapply" with that link.
  - **Duplicates:** if the same internship appears in several sources, only one copy is kept. The first source in this order wins: SimplifyJobs, company boards, negarprh, michelleokolie, Zapply. Matching uses the posting's link where possible, otherwise company plus title.
  - **Locations:** only locations in the US, Canada, or plain "Remote" are kept. Remote roles tied to another country are dropped.
  - **Age:** only listings posted in the last 30 days are shown. Internships you've tracked stay in the tracker regardless of age.
- **Closed postings:** a listing that leaves the list is marked closed. It stays on your tracker cards with a "Posting closed" tag.
- **New since last visit:** shows listings first seen after your previous visit, based on the last visit time stored in your browser.
- **Tracker:** has five columns (Saved, Applied, Interviewing, Offer, Rejected). Drag cards between columns. Click a card to set a deadline or add notes.
- **Storage:** everything is kept in `data/board.db` (SQLite). Back up that file to keep your tracker.

## AI tools

These run through the Claude Code CLI on your Mac (`claude -p`), using the Claude plan you're logged into. There's no API key and no separate bill, but each request counts toward your plan's usage limits. Requests run in the background, and the page shows progress while they do.

1. **Profile tab:** upload your resume (PDF, .docx or text). Claude turns it into a structured profile; you can check it and fix mistakes there. Also set what you're looking for: roles, categories, Canada/US, terms, graduation, work authorization and school.
2. **Ranking:** every listing gets a quick keyword match score, which takes milliseconds. Under **Profile → Ranking**, "Rank top 40 with Claude" adds a one-sentence reason to each of the top 40. On the board, sort by **Best match**, and click a score to see why.
3. **Tracker side panel → Documents:**
   - **Tailored resume:** a one-page resume for that posting. Open it, edit any text in place, then **Download PDF** (choose "Save as PDF").
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

Frontend tests need Node: `cd e2e && npm ci && npx playwright install chromium && npm test`. See `e2e/README.md`.
