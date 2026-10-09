"""Writes new companies to a CSV file and, if set up, to a Google Sheet."""

from __future__ import annotations

import csv
import os

from .models import Company

HEADERS = [
    "Status", "Fit (0-10)", "Company", "Website", "What they build", "Stage",
    "Team size", "Tech stack", "Founders", "Contact email", "Why it fits",
    "Email subject", "Email draft", "Found via", "Source page", "Found on",
]


def to_row(c: Company) -> list[str]:
    return [
        c.status, str(c.fit_score), c.name, c.website, c.what_they_build, c.stage,
        c.team_size, ", ".join(c.tech_stack), ", ".join(c.founders), c.contact_email,
        c.fit_reason, c.email_subject, c.email_body, c.hint or c.source,
        c.source_url, c.found_on,
    ]


def write_csv(path: str, companies: list[Company]):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    new_file = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if new_file:
            writer.writerow(HEADERS)
        writer.writerows(to_row(c) for c in companies)


def write_google_sheet(credentials_file: str, sheet_name: str,
                       companies: list[Company]) -> str | None:
    """Append rows to the sheet. Returns the sheet URL, or None if not set up.

    Only ever appends: your edits in the sheet (like the Status column)
    are never overwritten.
    """
    if not os.path.exists(credentials_file):
        return None
    import gspread  # imported here so the bot works without Google set up

    client = gspread.service_account(filename=credentials_file)
    sheet = client.open(sheet_name)
    tab = sheet.sheet1
    if not tab.row_values(1):
        tab.append_row(HEADERS)
        tab.format("1:1", {"textFormat": {"bold": True}})
        tab.freeze(rows=1)
    if companies:
        tab.append_rows([to_row(c) for c in companies], value_input_option="RAW")
    return sheet.url
