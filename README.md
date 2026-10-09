# Startup Hunter

Finds young startups in and around Dresden, reads their websites, scores how well
they fit you, and drafts a personal email for the best ones. It works with
Claude (Anthropic), GPT (OpenAI) or Gemini (Google), whichever you have a key
for. Everything lands in a Google Sheet (and a CSV file). **It never sends emails.** You review and send them yourself.

```
python hunt.py
```

## What one run does

1. **Collects leads** from a free German job board (software jobs in Dresden) and
   from web searches (articles and lists about Dresden startups, read by the AI).
2. **Finds each company's website** and reads its homepage plus its Impressum and
   contact pages, where German companies must publish a contact email.
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

You can already try it now: `python hunt.py --no-sheet`. Without a key it only
uses the job board, which is a good first check that everything works.

### 3. AI API key (for reading pages, scoring and drafts)

Pick **one** provider. You only need a key for that one.

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

### 4. Your profile (what the emails say about you)

The drafts are written only from facts in `profile.md`, which you create from
the template:

```bash
cp profile.example.md profile.md
open -e profile.md
```

Replace every placeholder with your own details (name, contact, what you're
looking for, experience, results) and save. Without this file the bot only runs
with `--no-ai`.

`profile.md` is listed in `.gitignore`, so your personal details stay on your
machine and are never committed. Only the blank template is shared.

### 5. Google Sheet (optional, the CSV works without it)

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

---

## Everyday use

```bash
cd ~/Documents/startup-hunter && source .venv/bin/activate && python hunt.py
```

Tip: make it one word. Run this once:

```bash
echo 'alias hunt="cd ~/Documents/startup-hunter && source .venv/bin/activate && python hunt.py"' >> ~/.zshrc
```

Open a new Terminal window and from then on just type `hunt`.

**Then, in the sheet:**

1. Sort by **Fit**.
2. Open the website and check the founders on LinkedIn yourself.
3. Edit the draft so it sounds like you, and send it from your own Gmail.
4. Change **Status** to `contacted`, then `replied`, `interview` and so on.

Running it once or twice a week is plenty. Dresden is small, so the first runs find
most companies and later runs pick up the new ones.

| Option | What it does |
|---|---|
| `python hunt.py --no-ai` | Job board only, no AI (free) |
| `python hunt.py --no-sheet` | Write only the CSV file |

## Customizing (no code needed)

- **`config.yaml`**: search phrases, towns, how many companies per run, the minimum
  fit score for a draft, the email language, which AI provider
  and models to use.
  `seed_pages` lets you add any page that lists Dresden startups.
- **`profile.md`**: the facts the emails are built from (create it from
  `profile.example.md`, see setup step 4). Keep it current. The drafts only use
  what's written there, and they never name your past clients. It's private:
  `.gitignore` keeps it out of Git.

## How the code is organized

| File | Job |
|---|---|
| `hunt.py` | The command you run |
| `profile.example.md` | Template for your private `profile.md` |
| `hunter/main.py` | Reads settings, connects the pieces, prints progress |
| `hunter/pipeline.py` | The 4 steps: leads → websites → reading and scoring → drafts |
| `hunter/web.py` | Fetching pages politely (robots.txt, delays), emails, links |
| `hunter/llm.py` | The three AI calls (Claude, GPT or Gemini), each with a fixed JSON output shape |
| `hunter/store.py` | SQLite memory of every company seen, so nothing repeats |
| `hunter/output.py` | CSV and Google Sheet writing |
| `tests/` | Offline tests with fake web pages and a fake AI |

## Ground rules built in

- Reads only public websites, respects `robots.txt`, and waits between requests.
- No LinkedIn scraping, and no automatic sending.
- Only uses email addresses published on the company's own website, and skips
  privacy/legal and no-reply addresses.

## Troubleshooting

- **`command not found: python`**: run `source .venv/bin/activate` first.
- **`0 jobs in the region` / few results**: search engines sometimes rate-limit.
  Wait a few minutes and run again, or add `seed_pages` in `config.yaml`.
- **Google Sheet error `SpreadsheetNotFound`**: the sheet name must match
  `google_sheet_name` exactly, and the sheet must be shared with the service
  account email.
- **`No profile.md found`**: run `cp profile.example.md profile.md` and fill it
  in (setup step 4).
- **Start fresh**: delete the `data` folder.
