# Intern Board: a tour

Intern Board is a personal, local web app for finding software and tech internships in Canada and the US, tracking applications, and preparing each one with AI help. It runs on your Mac. The AI features use the Claude Code CLI on your own Claude plan.

> **About these images:** they were captured from the real built app, but every API response comes from the made-up fixtures in `e2e/fixtures/`. "Sam Rivera", the companies and the recruiters are all invented. No real data, Claude call or Prospeo credit was used. To regenerate them, see [How these were made](#how-these-were-made).

**Contents**

1. [Internship board](#1-internship-board)
2. [Application tracker](#2-application-tracker)
3. [Tailored resumes and cover letters](#3-tailored-resumes-and-cover-letters)
4. [Find People and intro drafts](#4-find-people-and-intro-drafts)
5. [Profile and ranking](#5-profile-and-ranking)
6. [Company job boards](#6-company-job-boards)
7. [On a phone](#7-on-a-phone)

---

## 1. Internship board

One list of open internships from the SimplifyJobs list, three more community lists, and company job boards (Greenhouse, Lever, Ashby) read directly. Duplicates are merged, only US, Canada and remote roles are kept, and anything older than 30 days is hidden. The board refreshes every hour.

![The board: filters, quick stats and listings grouped by posting date](media/board.png)

Each row shows the source, location, category, term and age. Listings from a company's own board are tagged **Direct**. The coloured number is the match score against your profile.

![Recording: reading a match reason, filtering, searching and tracking a listing](media/board.gif)

*Recording ([MP4](media/board.mp4)): open a match reason, filter to Canada and Software, sort by best match, search with `/`, then track a listing.*

| Why it matched | Filters and sorting |
| --- | --- |
| ![Clicking a score shows Claude's one-line reason](media/board-match-reason.png) | ![The Sort dropdown open over the filtered board](media/board-dropdown.png) |

Filters are remembered between visits. The stat cards at the top (new since last visit, in Canada, direct from companies, deadlines this week) are shortcuts to the matching filter.

![The board filtered to Canada and Software, sorted by best match](media/board-filtered.png)

---

## 2. Application tracker

A kanban board with five stages: Saved, Applied, Interviewing, Offer and Rejected. Drag cards between columns, or move them with Alt and the arrow keys. Cards show deadlines, closed postings and region.

![The tracker's five columns](media/tracker.png)

![Recording: dragging a card and updating a stage, deadline and notes](media/tracker.gif)

*Recording ([MP4](media/tracker.mp4)): drag a card to Applied, then open another card to set the stage, a deadline and a note.*

Clicking a card opens a side panel with the stage, deadline, notes, the job's documents and a link to Find People for that company.

| Side panel | After saving |
| --- | --- |
| ![The side panel for a tracked internship](media/tracker-drawer.png) | ![The card moved to Interviewing with its new due date and note](media/tracker-after.png) |

---

## 3. Tailored resumes and cover letters

For any tracked internship, Claude writes a one-page resume or a cover letter (formal, conversational or enthusiastic) from your profile and the job description. Names, employers, dates and links are copied from your profile, never written by Claude. Each document lists what it emphasised and the requirements in the posting you *don't* meet.

![The Resume tailor page with existing documents](media/documents.png)

![Recording: tailoring a resume, then opening the resume and cover letter](media/documents.gif)

*Recording ([MP4](media/documents.mp4)): Claude only starts after the click. The page shows progress, then the new document and its notes.*

| In progress | Ready |
| --- | --- |
| ![Tailoring in progress with a timer](media/documents-tailoring.png) | ![The resume is ready, with notes on what was emphasised and the gaps](media/documents-ready.png) |

Documents open in an editor. Click any text to change it, check that it still fits on one page, then **Download PDF**.

![The tailored resume with its tailoring notes](media/doc-resume.png)

![The cover letter with tone, word count and things to check before sending](media/doc-letter.png)

---

## 4. Find People and intro drafts

Pick a tracked job, then look for recruiters or people on the team, using Prospeo's people database (a free account gives 100 credits a month). Credit costs are shown on every paid button, and saved searches open again for free.

| Pick a job | Recruiters or the team |
| --- | --- |
| ![Tracked jobs to choose from](media/people-pick.png) | ![Choosing recruiters or coffee chats](media/people-choose.png) |

![Six recruiters at Acme Robotics with email and LinkedIn](media/people-results.png)

Claude writes a LinkedIn note or an email only when you click. Each draft goes through four steps: a brief, the draft, automatic checks (length, stock phrases, invented numbers, claiming you applied when you haven't) and one repair if a check fails. LinkedIn notes are kept under 200 characters, or 300 with Premium.

![Recording: opening a recruiter and writing a LinkedIn note](media/people.gif)

*Recording ([MP4](media/people.mp4)).*

![A finished LinkedIn note with its reasoning and character count](media/people-draft.png)

---

## 5. Profile and ranking

Upload a resume (PDF, Word or text) and Claude turns it into a structured profile you can check and correct. Set the roles, categories, locations, terms, graduation date and work authorization you're looking for.

![The profile page: extracted resume summary and preferences](media/profile.png)

Every listing gets an instant keyword score. **Rank top 40 with Claude** adds a one-sentence reason to the best 40, which shows up on the board.

![Recording: ranking the top 40 listings with Claude](media/profile.gif)

*Recording ([MP4](media/profile.mp4)).* The [full profile page](media/profile-full.png) also covers ranking and the Prospeo integration.

---

## 6. Company job boards

Every Greenhouse, Lever and Ashby board that the SimplifyJobs list has linked to is watched automatically. Paste any other board link to add it, or switch boards off.

![The Companies page with board status and internship counts](media/companies.png)

![Recording: adding a Lever board](media/companies.gif)

*Recording ([MP4](media/companies.mp4)).*

![Brightpath added, with the number of matching internships it found](media/companies-added.png)

---

## 7. On a phone

Below 900 px the sidebar becomes a menu.

| Board | Menu | Tracker |
| --- | --- | --- |
| ![The board at 400 px wide](media/mobile-board.png) | ![The sidebar opened from the menu button](media/mobile-menu.png) | ![The tracker at 400 px wide](media/mobile-tracker.png) |

---

## How these were made

The script `e2e/showcase/showcase.spec.ts` drives the built app in Playwright. The mocked API and fixtures are the same ones the browser tests use. It saves screenshots and a `.webm` recording per section to `docs/showcase/media/`, and a blue dot shows the pointer in the recordings.

```sh
cd frontend && npm run build                     # so the images show the latest frontend
cd ../e2e && npx playwright test -c showcase.config.ts
../docs/showcase/make-gifs.sh                     # webm → gif + mp4; needs ffmpeg (or FFMPEG=/path/to/ffmpeg)
```
