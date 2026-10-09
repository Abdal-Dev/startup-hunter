"""Command line entry point:  python hunt.py  [--no-ai] [--agent] [--import-review] [--no-sheet]"""

from __future__ import annotations

import argparse
import os
import sys

import yaml

from .agent import import_results, write_todo
from .llm import LLM, PROVIDERS
from .output import write_csv, write_google_sheet
from .pipeline import Pipeline
from .store import Store
from .web import Http, web_search

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_env():
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(HERE, ".env"))
    except ImportError:
        pass


def main(argv=None):
    parser = argparse.ArgumentParser(description="Find young Dresden startups and draft emails.")
    parser.add_argument("--no-ai", action="store_true",
                        help="skip the AI (only job-board leads, no scoring or drafts)")
    parser.add_argument("--no-sheet", action="store_true",
                        help="only write the CSV file, not the Google Sheet")
    parser.add_argument("--agent", action="store_true",
                        help="agent mode even if an API key is set (no API costs)")
    parser.add_argument("--import-review", action="store_true",
                        help="agent mode: save the results your coding assistant wrote")
    parser.add_argument("--config", default=os.path.join(HERE, "config.yaml"))
    args = parser.parse_args(argv)

    load_env()
    with open(args.config, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    out = cfg["output"]
    path = lambda p: p if os.path.isabs(p) else os.path.join(HERE, p)
    review_dir = os.path.join(os.path.dirname(path(out["database_path"])), "review")
    store = Store(path(out["database_path"]))
    http = Http(cfg["request_delay_seconds"])

    if args.import_review:
        pipeline = Pipeline(cfg, store, http, web_search)
        print("Importing your coding assistant's review")
        saved = import_results(review_dir, pipeline, cfg)
        save(store, saved, out, path, args.no_sheet)
        print(f"\nDone: {len(saved)} companies saved, "
              f"{sum(1 for c in saved if c.email_body)} email drafts.")
        return 0

    mode = "off" if args.no_ai else "agent" if args.agent else choose_mode(cfg)
    if mode is None:
        return 1
    profile_path = os.path.join(HERE, "profile.md")
    if mode == "api" and not os.path.exists(profile_path):
        print("No profile.md found. Create yours from the template first:\n"
              "  cp profile.example.md profile.md\n"
              "then fill in your own details (see README step 4).")
        return 1
    if mode == "agent" and not os.path.exists(profile_path):
        print("Note: no profile.md yet. Your coding assistant needs it for the email\n"
              "drafts: cp profile.example.md profile.md, then fill it in.\n")
    profile = ""
    if os.path.exists(profile_path):
        with open(profile_path, encoding="utf-8") as f:
            profile = f.read()

    llm = None
    if mode == "api":
        provider = cfg.get("provider", "anthropic")
        models = cfg["models"][provider]
        llm = LLM(provider, os.environ[PROVIDERS[provider]].strip(),
                  models["fast"], models["writer"])

    pipeline = Pipeline(cfg, store, http, web_search, llm=llm, profile=profile,
                        agent_mode=mode == "agent")
    new = pipeline.run()

    if mode == "agent":
        print("4/4 Handing over to your coding assistant")
        if not args.no_sheet:
            sync_sheet(store, out, path)  # catch up on anything reviewed earlier
        todo = write_todo(review_dir, pipeline, cfg)
        print(f"  {os.path.join(review_dir, 'todo.json')}: "
              f"{len(todo['companies'])} companies to review, "
              f"{len(todo['pages_to_read'])} pages to read")
        print("\nNext: open this folder in Claude Code, Codex, Cursor or similar and say\n"
              '  "review the startups"\n'
              "It follows AGENTS.md and saves the results with --import-review.")
        return 0

    print("4/4 Saving results")
    save(store, new, out, path, args.no_sheet)
    print(f"\nDone: {len(new)} new companies, "
          f"{sum(1 for c in new if c.email_body)} email drafts. "
          f"{store.count()} companies found in total.")
    return 0


def choose_mode(cfg) -> str | None:
    """'api' (the bot calls the AI itself) or 'agent' (a coding assistant does it)."""
    mode = cfg.get("ai_mode", "auto")
    provider = cfg.get("provider", "anthropic")
    if mode not in ("auto", "api", "agent"):
        print(f"Unknown ai_mode {mode!r} in config.yaml. Use auto, api or agent.")
        return None
    if mode == "agent":
        return "agent"
    if provider not in PROVIDERS:
        print(f"Unknown provider {provider!r} in config.yaml. "
              f"Use one of: {', '.join(PROVIDERS)}.")
        return None
    key_name = PROVIDERS[provider]
    if os.environ.get(key_name, "").strip():
        return "api"
    if mode == "api":
        print(f"ai_mode is api but no {key_name} found in .env. See README step 3.")
        return None
    print(f"No {key_name} in .env, so using agent mode: your coding assistant\n"
          "does the AI part with your existing subscription (see AGENTS.md).\n")
    return "agent"


def save(store, new, out, path, no_sheet):
    """Append new companies to the CSV, and everything not yet exported to the sheet."""
    new.sort(key=lambda c: c.fit_score, reverse=True)
    write_csv(path(out["csv_path"]), new)
    print(f"  CSV: {path(out['csv_path'])}")
    if not no_sheet:
        sync_sheet(store, out, path)


def sync_sheet(store, out, path):
    """Send every company not yet in the sheet, so if the sheet is set up later
    (or a run fails), nothing found earlier is lost."""
    pending = store.not_exported()
    try:
        url = write_google_sheet(path(out["google_credentials_file"]),
                                 out["google_sheet_name"], pending)
        if url:
            store.mark_exported([c.domain for c in pending])
            print(f"  Google Sheet: {len(pending)} rows added, {url}")
        else:
            print("  Google Sheet: not set up yet (see README step 5), CSV only")
    except Exception as error:
        print(f"  ! Google Sheet failed: {error}\n"
              "    These rows will be added on the next successful run.")


if __name__ == "__main__":
    sys.exit(main())
