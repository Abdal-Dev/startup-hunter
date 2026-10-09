"""Agent mode: no API key needed, your coding assistant does the AI part.

1. `python hunt.py` collects leads and reads their websites for free, then
   writes data/review/todo.json.
2. Your coding assistant (Claude Code, Codex, Cursor, ...) follows AGENTS.md:
   it scores each company, drafts emails and writes data/review/results.json.
3. `python hunt.py --import-review` checks those results and saves the good
   ones to the CSV and Google Sheet, exactly like an API run would.
"""

from __future__ import annotations

import datetime as dt
import json
import os

from .llm import EMAIL_TOOL, QUALIFY_TOOL, email_rules, extract_rules, qualify_rules
from .models import Lead
from .store import REVIEW_STATUS
from .web import normalize_domain

# What the assistant writes for each company: the same fields the API returns,
# plus which company it is and the email draft.
RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "companies": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "website": {"type": "string", "description": "Homepage URL."},
                    "name": {"type": "string"},
                    "note": {"type": "string", "description": "Only for startups you found "
                             "yourself: where you found them and what they do."},
                    **QUALIFY_TOOL["input_schema"]["properties"],
                    "email_subject": EMAIL_TOOL["input_schema"]["properties"]["subject"],
                    "email_body": EMAIL_TOOL["input_schema"]["properties"]["body"],
                },
                "required": ["website", "name", *QUALIFY_TOOL["input_schema"]["required"]],
            },
        }
    },
    "required": ["companies"],
}


def _load(path: str) -> dict | None:
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save(path: str, data: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def write_todo(review_dir: str, pipeline, cfg) -> dict:
    """Add this run's companies and article pages to todo.json (kept across runs)."""
    path = os.path.join(review_dir, "todo.json")
    todo = _load(path) or {"companies": [], "pages_to_read": []}
    known = {c["domain"] for c in todo["companies"]}
    for company, text in pipeline.to_review:
        if company.domain not in known:
            todo["companies"].append({
                "domain": company.domain, "name": company.name,
                "website": company.website, "spotted_via": company.hint or company.source,
                "source_page": company.source_url,
                "emails_on_site": company.emails_on_site, "website_text": text,
            })
    for url in pipeline.pages_for_agent:
        if url not in todo["pages_to_read"]:
            todo["pages_to_read"].append(url)
    todo["instructions"] = {
        "how_to": "Follow AGENTS.md in the project folder.",
        "region": pipeline.region,
        "min_fit_score_for_email": cfg["min_fit_score"],
        "max_new_startups_from_pages": cfg["max_new_companies_per_run"],
        "finding_startups_on_pages": extract_rules(pipeline.region),
        "scoring": qualify_rules(pipeline.region),
        "email_drafts": email_rules(cfg["email_language"]),
        "already_known_domains": pipeline.store.domains(),
        "results_file_schema": RESULT_SCHEMA,
    }
    _save(path, todo)
    return todo


def import_results(review_dir: str, pipeline, cfg, log=print) -> list:
    """Check results.json from the assistant and save the companies that pass."""
    results_path = os.path.join(review_dir, "results.json")
    results = _load(results_path)
    if results is None:
        log(f"No results file at {results_path}.\n"
            "Ask your coding assistant to review the startups first (see AGENTS.md).")
        return []
    todo_path = os.path.join(review_dir, "todo.json")
    todo = _load(todo_path) or {"companies": [], "pages_to_read": []}
    pending = {c["domain"]: c for c in todo["companies"]}
    required = RESULT_SCHEMA["properties"]["companies"]["items"]["required"]
    store, saved = pipeline.store, []

    for entry in results.get("companies", []):
        domain = normalize_domain(entry.get("website", ""))
        label = entry.get("name") or domain or "?"
        missing = [k for k in required if k not in entry]
        if not domain or missing:
            log(f"  ! {label}: skipped, missing {', '.join(missing) or 'website'}")
            continue

        company = store.get(domain)
        if company is None or company.status != REVIEW_STATUS:
            # A startup the assistant found itself: check its site like any other lead.
            if store.seen(domain):
                log(f"  - {label}: already in your list")
                continue
            found = pipeline.examine(Lead(
                name=entry["name"], website=entry["website"], source="coding assistant",
                hint=entry.get("note", "")))
            if not found:
                log(f"  - {label}: skipped (unreachable, blocked or not in the region)")
                continue
            company = found[0]

        pending.pop(domain, None)
        try:
            if not pipeline.apply_assessment(company, entry):
                log(f"  - {label}: not a fit ({entry.get('fit_reason', '')})")
                continue
        except (TypeError, ValueError) as error:
            log(f"  ! {label}: skipped, invalid values ({error})")
            continue
        company.status = "new"
        if company.fit_score >= cfg["min_fit_score"] and company.contact_email:
            company.email_subject = entry.get("email_subject", "")
            company.email_body = entry.get("email_body", "")
        store.add(company)
        saved.append(company)
        log(f"  + {company.name} ({domain}) fit {company.fit_score}/10"
            + (", draft saved" if company.email_body else ""))

    # Keep whatever wasn't reviewed for next time; the pages have been read.
    todo["companies"] = list(pending.values())
    todo["pages_to_read"] = []
    _save(todo_path, todo)
    stamp = dt.datetime.now().strftime("%Y-%m-%d-%H%M%S")
    os.replace(results_path, os.path.join(review_dir, f"imported-{stamp}.json"))
    if pending:
        log(f"  {len(pending)} companies still waiting for review in todo.json")
    return saved
