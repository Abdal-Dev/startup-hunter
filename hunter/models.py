"""The two data shapes the pipeline passes around."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Lead:
    """A company name we spotted somewhere, before we know much about it."""

    name: str
    website: str = ""        # may be empty until we look it up
    source: str = ""         # e.g. "search", "job board", "seed page"
    source_url: str = ""     # where we spotted it
    hint: str = ""           # anything useful we saw, e.g. a job title


@dataclass
class Company:
    """Everything we know about a company after enriching and scoring it."""

    name: str
    domain: str
    website: str
    source: str = ""
    source_url: str = ""
    hint: str = ""
    found_on: str = ""                       # date, YYYY-MM-DD
    emails_on_site: list[str] = field(default_factory=list)
    what_they_build: str = ""
    stage: str = ""
    team_size: str = ""
    tech_stack: list[str] = field(default_factory=list)
    founders: list[str] = field(default_factory=list)
    contact_email: str = ""
    fit_score: int = 0
    fit_reason: str = ""
    email_subject: str = ""
    email_body: str = ""
    status: str = "new"                      # you change this in the sheet
