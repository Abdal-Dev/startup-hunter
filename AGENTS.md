# Startup Hunter: instructions for coding assistants

This project finds young startups, scores how well they fit the user, and drafts
cold emails. In **agent mode** you (the coding assistant) do the AI part, so the user
needs no API key. The Python code does everything else: searching, reading websites,
checking your output and saving it.

This file has two parts:

- **Working on the code**: rules for any change to the project (code, docs,
  commits). They always apply.
- **Running the hunt** (steps 1–5): use this workflow when the user asks you to
  "review the startups", "run the hunt", "find startups" or similar. Run every
  command from the project folder.

# Working on the code

**Commits**
- Never add yourself (or any AI tool) as an author or co-author: no
  `Co-Authored-By: Claude`, `Generated with ...` or similar lines in commit
  messages or pull requests. Commits show only the user.
- Commit only when the user asks. Make one commit per changed file, with a short
  subject saying what changed in that file and a body saying why.
- Run `.venv/bin/python -m unittest` before committing, and don't commit if a
  test fails.
- Push only when the user asks. Never force-push or rewrite history without the
  user's explicit go-ahead.

**Privacy: never commit or upload**
- `profile.md`, `.env`, `google-credentials.json` or anything in `data/`. They
  are in `.gitignore`; keep it that way.
- The user's name, email, LinkedIn URL or API keys in any committed file.
  Before committing, check the diff for them.

**Code and docs**
- Match the existing style: small functions, plain names, short comments that
  explain why.
- Add or update tests in `tests/` for every behaviour change. Tests must run
  offline (use the fakes in `tests/test_hunter.py`).
- Update `README.md` (and this file, if the workflow changes) in the same change
  as the code. Docs are written for non-programmers: plain words, short steps.
- Don't weaken the scraping rules in `hunter/web.py` (never-fetch list,
  robots.txt, delays, backing off), and don't add automation for LinkedIn, X or
  other sites on that list, or anything that logs into accounts.
- Never write to existing rows or user columns of the Google Sheet. The bot only
  adds new rows (see `hunter/output.py`).

# Running the hunt

## 1. Check the setup

- If `.venv` is missing, create it and install:
  `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`
- If `profile.md` is missing, stop and ask the user to create it:
  `cp profile.example.md profile.md`, then fill in their own details. Never write
  facts about the user yourself.

## 2. Collect (free)

```bash
.venv/bin/python hunt.py --agent
```

This finds new companies, reads their websites and adds them to
`data/review/todo.json`. Skip this step if the user only wants to review what's
already collected. Always pass `--agent`: without it, an API key in `.env` makes
the bot call the paid API instead.

## 3. Review

Read `profile.md` and `data/review/todo.json`. The `instructions` block in
`todo.json` has the exact rules: `scoring`, `email_drafts`,
`finding_startups_on_pages`, `min_fit_score_for_email`, `region` and
`results_file_schema`. Follow them as written.

**Companies** (`todo.json` → `companies`): for each one, judge it from
`website_text`. If you can browse and the text is thin, you may open more pages on
the company's own site. Fill in every field of the schema. Also write an entry for
the ones that don't fit (set `is_young_startup`, `in_region` or `builds_software` to
false), so they're remembered and never come back.

**Pages** (`todo.json` → `pages_to_read`): only if you can fetch web pages. Read
them, list the startups they mention following `finding_startups_on_pages`, and skip
anything in `already_known_domains`. Add at most `max_new_startups_from_pages`. For
each one, find its own website, assess it like the companies above, and add a short
`note` saying where you found it. Open the website first and check that it really
belongs to that company: web searches often return a different company with a
similar name. If you can't browse, skip this part.

**Email drafts:** write `email_subject` and `email_body` only when `fit_score` is at
least `min_fit_score_for_email` and there is a `contact_email`. Follow
`email_drafts` and use only facts from `profile.md`.

**Hard rules**
- `contact_email` must be an address from that company's `emails_on_site` (or one
  you saw on its own website for startups you found). Never guess an address. The
  import drops any email it can't verify.
- Never invent facts about a company or the user. Use "unknown" or empty values.
- Never send emails or contact anyone. The user reviews and sends every draft.
- Don't edit `profile.md`, `.env` or anything in `data/` except
  `data/review/results.json`.

**Browsing rules** (the same ones the bot follows, see "Ground rules" in the README)
- Never open LinkedIn, X/Twitter, Facebook, Instagram, Xing, TikTok, Glassdoor,
  Indeed or Crunchbase pages, even if a search result points there.
- Respect `robots.txt`, and stop visiting a site that answers 429 or 503.
- Go slowly: one request at a time, a few seconds between pages (at least 5
  seconds between pages of the same site), and at most about 4 pages per company website.
- Only public pages: no logins, forms or paywalls.
- The search area is in `instructions.region`. A company only counts if it's based
  there; the import also checks that its website mentions the city or a nearby place.

## 4. Save

Write `data/review/results.json`, matching `results_file_schema`, then run:

```bash
.venv/bin/python hunt.py --import-review
```

This verifies your results, saves them to `data/startups.csv` (and the Google Sheet
if one is set up), and archives the results file. Companies you didn't get to stay in
`todo.json` for next time.

## 5. Report

Show the user a short table: company, fit score, one-line reason, and whether a
draft was written. Then tell them where the drafts are (the CSV or the sheet).
