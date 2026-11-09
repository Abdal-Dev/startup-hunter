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


# Extra columns only in the Google Sheet, for you to track outreach by hand.
# New rows start with these values; the bot never changes them after that.
TRACKING_COLUMNS = {"Email sent": "Not sent", "LinkedIn message": "Not sent"}
SHEET_HEADERS = HEADERS + list(TRACKING_COLUMNS)


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


def sheet_rows(header: list[str], companies: list[Company]) -> tuple[list[list[str]], list[str]]:
    """Rows laid out to match the sheet's own header row, matched by column name.

    The tracking columns ("Email sent", "LinkedIn message") start as "Not sent",
    any other columns you added yourself are left empty, and all columns can be
    moved or reordered freely. Returns the rows and the
    names of bot columns that are missing from the sheet (those are skipped).
    """
    where = {name.strip().lower(): i for i, name in enumerate(header) if name.strip()}
    ours = [(i, where.get(name.lower())) for i, name in enumerate(SHEET_HEADERS)]
    # Tracking columns are optional: if you deleted one, that's fine.
    missing = [SHEET_HEADERS[i] for i, col in ours if col is None and i < len(HEADERS)]
    width = max((col for _, col in ours if col is not None), default=-1) + 1
    rows = []
    for company in companies:
        values, row = to_row(company) + list(TRACKING_COLUMNS.values()), [""] * width
        for i, col in ours:
            if col is not None:
                row[col] = values[i]
        rows.append(row)
    return rows, missing


def _find_tab(sheet):
    """The tab whose header row has the bot's columns, or an empty first tab."""
    for tab in sheet.worksheets():
        header = {h.strip().lower() for h in tab.row_values(1)}
        if {"company", "website"} <= header:
            return tab
    first = sheet.sheet1
    if not first.row_values(1):
        return first
    raise RuntimeError("no tab has the 'Company' and 'Website' columns. Add them back, "
                       "or add an empty first tab for the bot to fill.")


def write_google_sheet(credentials_file: str, sheet_name: str,
                       companies: list[Company], log=print) -> str | None:
    """Add new rows to the sheet. Returns the sheet URL, or None if not set up.

    It never changes what's already in the sheet: existing rows, what you've
    written in "Email sent", "LinkedIn message" or your own columns, formatting
    and column order are left alone. New rows are inserted below the last row, so nothing
    further down is ever written over.
    """
    if not os.path.exists(credentials_file):
        return None
    import gspread  # imported here so the bot works without Google set up

    client = gspread.service_account(filename=credentials_file)
    sheet = client.open(sheet_name)
    tab = _find_tab(sheet)
    header = tab.row_values(1)
    if not header:  # brand-new sheet: write the header row once
        tab.append_row(SHEET_HEADERS)
        tab.format("1:1", {"textFormat": {"bold": True}})
        tab.freeze(rows=1)
        header = SHEET_HEADERS
    rows, missing = sheet_rows(header, companies)
    if missing:
        log(f"  ! Google Sheet has no column named {', '.join(missing)}; "
            "those values are only in the CSV")
    if rows:
        tab.append_rows(rows, value_input_option="RAW", insert_data_option="INSERT_ROWS",
                        table_range="A1")
    return sheet.url
