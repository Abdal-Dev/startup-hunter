# Startup Hunter

Finds young startups in and around your city, reads their websites, scores how well
they fit you, and drafts a personal email for the best ones. Everything lands in
a Google Sheet (and a CSV file). **It never sends emails.** You review and send
them yourself.

The AI part (reading articles, scoring, writing drafts) can be done in two ways:

| | **Agent mode** (no API key) | **API mode** |
|---|---|---|
| Who does the AI part | Your coding assistant (Claude Code, Codex, Cursor, Gemini CLI...) on the subscription you already pay for | The bot itself, through Claude, GPT or Gemini |
| Cost | Nothing extra | A few cents per run |
| How you run it | `python hunt.py`, then tell your assistant *"review the startups"* | `python hunt.py`, fully automatic |

With `ai_mode: auto` (the default) it uses API mode when a key is in `.env`,
and agent mode otherwise. You can switch any time.

## Countries covered

You pick one country and a city in `config.yaml` (setup step 4). The bot searches
in English plus the country's own language:

- Austria (German)
- Belgium (Dutch and French)
- Czechia (Czech)
- Denmark (Danish)
- Estonia (Estonian)
- Finland (Finnish)
- France (French)
- Germany (German), the only country where the job board is also used
- Ireland (English)
- Italy (Italian)
- Netherlands (Dutch)
- Poland (Polish)
- Portugal (Portuguese)
- Spain (Spanish)
- Sweden (Swedish)
- Switzerland (German and French)
- United Kingdom (English)

Any city in these countries works. Adding a country takes one entry in
`hunter/countries.py`.

## What one run does

1. **Collects leads** from web searches in English and your country's language
   (articles and lists about startups in your city), plus a free job board in
   Germany.
2. **Finds each company's website** and reads its homepage plus its legal notice
   (Impressum, mentions légales...) and contact pages, where companies publish a
   contact email.
3. **Skips** anything outside the region, already seen, or not a startup. Rejected
   sites are remembered, so they never cost money again.
4. **Scores fit (0–10)** with the AI and **drafts an email** for every company that
   scores 6 or more and has a contact email on its own website.
5. **Saves** new rows to your Google Sheet and `data/startups.csv`. It only ever
   *adds* rows, so your edits in the sheet are safe.

---

## Setup (once, about 20 minutes)

### 1. Python

Open **Terminal** and check your version:

```bash
python3 --version
```

You need 3.10 or newer. If it's older (or missing), install it with
[Homebrew](https://brew.sh): `brew install python@3.12`, or download it from
[python.org](https://www.python.org/downloads/).

### 2. Install the project

```bash
cd ~/project-directory
python3 -m venv .venv            # a private Python just for this project
source .venv/bin/activate        # turn it on (your prompt shows "(.venv)")
pip install -r requirements.txt  # install the libraries
python -m unittest               # should end with "OK"
```

You can already try it now: `python hunt.py --no-ai --no-sheet`. It only uses
the job board, which is a good first check that everything works.

### 3. Choose who does the AI part

**Option A: agent mode (no API key, nothing extra to pay).** Skip to step 4.
Any coding assistant that can run commands and read files in this folder works:
Claude Code, Codex, Cursor, GitHub Copilot, Gemini CLI and others. Its
instructions are in [`AGENTS.md`](AGENTS.md); `CLAUDE.md` and `GEMINI.md` point
there too. See [Everyday use](#everyday-use).

**Option B: API mode (fully automatic, a few cents per run).** Pick **one**
provider. You only need a key for that one.

| Provider | Get a key | Line in `.env` | `provider:` in `config.yaml` |
|---|---|---|---|
| Anthropic (Claude) | [platform.claude.com](https://platform.claude.com) → Settings → API keys | `ANTHROPIC_API_KEY=` | `anthropic` (default) |
| OpenAI (GPT) | [platform.openai.com/api-keys](https://platform.openai.com/api-keys) | `OPENAI_API_KEY=` | `openai` |
| Google (Gemini) | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) | `GEMINI_API_KEY=` | `google` |

1. Create an account with the provider and add a little credit under billing.
   $5 lasts a long time. One run costs a few cents, mostly for the email drafts.
   (Gemini also has a free tier.)
2. Create an API key and copy it.
3. In the project folder:
   ```bash
   cp .env.example .env
   open -e .env
   ```
   Paste the key after the matching line (see the table), save and close.
4. If you're not using Claude, open `config.yaml` and set `provider:` to
   `openai` or `google`. The models for each provider are listed under
   `models:` there; change them if you want a newer or cheaper one.

Treat the key like a password. `.gitignore` already keeps `.env` out of Git.

### 4. Your city and country

Open `config.yaml` and set where to look:

```yaml
country: France
city: Lyon
nearby: ["Villeurbanne", "Auvergne-Rhône-Alpes"]   # optional
```

The country must be one of the [countries covered](#countries-covered); the
English name or a short form like `fr`, `de` or `uk` works. The bot searches in English and in the country's language, and
only keeps companies whose website mentions your city or a `nearby` place. Add
local spellings to `nearby` if they differ (e.g. `München` for Munich). The job
board only covers Germany and is skipped elsewhere.

To try another city once, without editing the file:

```bash
python hunt.py --agent --city Utrecht --country nl
```

### 5. Your profile (what the emails say about you)

The drafts are written only from facts in `profile.md`, which you create from
the template:

```bash
cp profile.example.md profile.md
open -e profile.md
```

Replace every placeholder with your own details (name, contact, what you're
looking for, experience, results) and save. Without it, no email drafts can be
written in either mode.

The profile is also what companies are scored against, so list your skills in
two tiers:

- **Experience**: your main skills. Companies that need these score highest.
- **Also willing to work with** (optional): skills that aren't your strongest
  but that you'd use if needed, e.g. "C++ and Python, as long as the work is
  related to my field". Companies that mainly need these still count, but rank
  below the ones that match your main skills. Emails mention these skills only
  when a company needs them.

`profile.md` is listed in `.gitignore`, so your personal details stay on your
machine and are never committed. Only the blank template is shared.

### 6. Google Sheet (optional, the CSV works without it)

1. Open [console.cloud.google.com](https://console.cloud.google.com) and create a
   project, e.g. "startup-hunter".
2. **APIs & Services → Library**: enable **Google Sheets API** and **Google Drive API**.
3. **APIs & Services → Credentials → Create credentials → Service account**. Give
   it any name, then skip the optional steps.
4. Open the new service account → **Keys → Add key → Create new key → JSON**.
   A file downloads. Rename it to `google-credentials.json` and move it into the
   project folder.
5. Create a Google Sheet named **Startup Hunter**. Click **Share** and add the
   service account's email (it's the `client_email` inside the JSON file, ending in
   `iam.gserviceaccount.com`) as **Editor**.

The next run fills the sheet, including everything found before you set it up.

**Tracking columns.** Besides the bot's columns, a new sheet gets **Email sent**
and **LinkedIn message**, and every new row starts with `Not sent` in both. Update
them by hand as you reach out; the bot never changes them after that.

**Your own columns are safe.** Add any columns you like (notes, interview date...)
anywhere in the sheet, and reorder or move the bot's columns if you want. The bot:

- matches its columns by header name, not position, and leaves yours empty on
  new rows;
- never changes existing rows, your formatting or the header row;
- inserts new rows below the last one, so nothing further down is overwritten;
- writes to the tab whose header row has `Company` and `Website`, so you can add
  other tabs.

Don't rename the bot's own column headers: a renamed column is skipped (its
values stay in the CSV) and the run prints a warning.

---

## Everyday use

### Agent mode (no API key)

Open this folder in your coding assistant and say:

> review the startups

It runs `python hunt.py --agent` to collect new companies for free, reads
`data/review/todo.json`, scores each company against your `profile.md`, writes
the email drafts, and saves everything with `python hunt.py --import-review`.
That last command double-checks the work: it drops any email address that isn't
on the company's own website, and checks the location and website of every
startup the assistant found itself. Then it writes the results to the CSV and
the sheet, just like API mode.

You can also split it up: run `python hunt.py --agent` yourself whenever you like
(it's free, and new companies pile up in `todo.json`), then ask your assistant to
review them all at once.

### API mode

```bash
cd ~/project-directory/startup-hunter && source .venv/bin/activate && python hunt.py
```

Tip: make it one word. Run this once:

```bash
echo 'alias hunt="cd ~/project-directory/startup-hunter && source .venv/bin/activate && python hunt.py"' >> ~/.zshrc
```

Open a new Terminal window and from then on just type `hunt`.

**Then, in the sheet:**

1. Sort by **Fit**.
2. Open the website and check the founders on LinkedIn yourself.
3. Edit the draft so it sounds like you, and send it from your own Gmail.
4. Change **Status** to `contacted`, then `replied`, `interview` and so on.

Running it once or twice a week is plenty. The first runs find most companies in
your city, and later runs pick up the new ones.

| Option | What it does |
|---|---|
| `python hunt.py --agent` | Agent mode, even if an API key is set |
| `python hunt.py --import-review` | Agent mode: save the results your assistant wrote |
| `python hunt.py --city Lyon --country France` | Search another city this time |
| `python hunt.py --no-ai` | Job board only, no AI at all |
| `python hunt.py --no-sheet` | Write only the CSV file |

## Customizing (no code needed)

- **`config.yaml`**: country, city and nearby towns, extra search phrases, how many companies per run, the minimum
  fit score for a draft, the email language, `ai_mode` (auto, api or agent),
  and which AI provider and models to use in API mode.
  `seed_pages` lets you add any page that lists startups in your city.
- **`profile.md`**: the facts the emails are built from (create it from
  `profile.example.md`, see setup step 5). Keep it current. The drafts only use
  what's written there, and they never name your past clients. It's private:
  `.gitignore` keeps it out of Git.

## How the code is organized

| File | Job |
|---|---|
| `hunt.py` | The command you run |
| `profile.example.md` | Template for your private `profile.md` |
| `hunter/main.py` | Reads settings, connects the pieces, prints progress |
| `hunter/pipeline.py` | The 4 steps: leads → websites → reading and scoring → drafts |
| `hunter/countries.py` | Supported countries, their search region and local-language search phrases |
| `hunter/web.py` | Fetching pages politely (see Ground rules), emails, links |
| `hunter/llm.py` | The three AI calls (Claude, GPT or Gemini), each with a fixed JSON output shape, and the rules they follow |
| `hunter/agent.py` | Agent mode: writes `todo.json` for your assistant and checks its `results.json` |
| `AGENTS.md` | Step-by-step instructions for coding assistants (agent mode) |
| `hunter/store.py` | SQLite memory of every company seen, so nothing repeats |
| `hunter/output.py` | CSV and Google Sheet writing |
| `tests/` | Offline tests with fake web pages and a fake AI |

## Ground rules built in

The bot is built to behave like a polite visitor, so sites have no reason to block it:

- **Never touches** LinkedIn, X/Twitter, Facebook, Instagram, Xing, TikTok,
  Glassdoor, Indeed, Crunchbase and similar sites, in any country. Their terms
  forbid bots, so not a single request goes to them. Check founders there
  yourself, by hand.
- **Obeys `robots.txt`**, including `Crawl-delay`. If a site's `robots.txt` can't
  be read because of a server error, the site is skipped (as the robots.txt
  standard, RFC 9309, says).
- **Goes slowly**: it waits at least 3 seconds between any two requests
  (`request_delay_seconds`), 5 seconds between pages of the same website
  (`site_delay_seconds`), and 3 seconds between searches. It reads at most 4
  pages per company website. It doesn't use a browser or click anything: it
  downloads each page once and reads the text, which is the lightest kind of
  visit a site can get.
- **Backs off**: if a site answers "too many requests" (429) or "unavailable"
  (503), it's skipped for the rest of the run. If the search engine rate-limits,
  searching stops for that run instead of retrying.
- **Says who it is**: its User-Agent names the bot and links to this project.
- Reads only public pages: no logins, no paywalls, no automatic sending.
- Only uses email addresses published on the company's own website, and skips
  privacy/legal and no-reply addresses.

## Troubleshooting

- **`command not found: python`**: run `source .venv/bin/activate` first.
- **`0 jobs in the region` / few results**: search engines sometimes rate-limit.
  Wait a few minutes and run again, or add `seed_pages` in `config.yaml`.
- **`Country ... isn't supported`**: use one of the
  [countries covered](#countries-covered) (English name, or a short form like
  `de`, `fr`, `uk`).
- **Companies rejected as "no sign of the region"**: their site doesn't mention
  your city. Add local spellings or nearby towns to `nearby` in `config.yaml`.
- **Google Sheet error `SpreadsheetNotFound`**: the sheet name must match
  `google_sheet_name` exactly, and the sheet must be shared with the service
  account email.
- **Agent mode: `No results file`**: your assistant hasn't written
  `data/review/results.json` yet. Ask it to "review the startups" first.
- **`No profile.md found`**: run `cp profile.example.md profile.md` and fill it
  in (setup step 5).
- **Start fresh**: delete the `data` folder.
