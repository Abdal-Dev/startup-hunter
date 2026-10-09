"""Command line entry point:  python hunt.py  [--no-ai] [--no-sheet]"""

from __future__ import annotations

import argparse
import os
import sys

import yaml

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
    parser.add_argument("--config", default=os.path.join(HERE, "config.yaml"))
    args = parser.parse_args(argv)

    load_env()
    with open(args.config, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    profile_path = os.path.join(HERE, "profile.md")
    if os.path.exists(profile_path):
        with open(profile_path, encoding="utf-8") as f:
            profile = f.read()
    elif args.no_ai:
        profile = ""
    else:
        print("No profile.md found. Create yours from the template first:\n"
              "  cp profile.example.md profile.md\n"
              "then fill in your own details (see README step 4).")
        return 1
    out = cfg["output"]
    path = lambda p: p if os.path.isabs(p) else os.path.join(HERE, p)

    llm = None
    provider = cfg.get("provider", "anthropic")
    if provider not in PROVIDERS:
        print(f"Unknown provider {provider!r} in config.yaml. "
              f"Use one of: {', '.join(PROVIDERS)}.")
        return 1
    key_name = PROVIDERS[provider]
    key = os.environ.get(key_name, "").strip()
    if args.no_ai:
        print("Running without AI (--no-ai).")
    elif not key:
        print(f"No {key_name} found in .env, so running without AI.\n"
              "You'll get job-board leads only. See README step 3 to add a key.\n")
    else:
        models = cfg["models"][provider]
        llm = LLM(provider, key, models["fast"], models["writer"])

    store = Store(path(out["database_path"]))
    pipeline = Pipeline(cfg, store, Http(cfg["request_delay_seconds"]), web_search,
                        llm=llm, profile=profile)
    new = pipeline.run()

    print("4/4 Saving results")
    new.sort(key=lambda c: c.fit_score, reverse=True)
    write_csv(path(out["csv_path"]), new)
    print(f"  CSV: {path(out['csv_path'])}")

    # The sheet gets every company not yet sent to it, so if the sheet is set
    # up later (or a run fails), nothing found earlier is lost.
    if not args.no_sheet:
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

    print(f"\nDone: {len(new)} new companies, "
          f"{sum(1 for c in new if c.email_body)} email drafts. "
          f"{store.count()} companies found in total.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
