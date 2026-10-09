"""Remembers every company ever found (SQLite), so nothing is added twice."""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import asdict, fields

from .models import Company

LIST_FIELDS = {"emails_on_site", "tech_stack", "founders"}


class Store:
    def __init__(self, path: str):
        if path != ":memory:":
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.db = sqlite3.connect(path)
        columns = ", ".join(
            f"{f.name} TEXT" for f in fields(Company) if f.name != "domain"
        )
        self.db.execute(
            f"CREATE TABLE IF NOT EXISTS companies (domain TEXT PRIMARY KEY, {columns}, "
            "exported INTEGER DEFAULT 0)"
        )
        # Domains we looked at but rejected (not a startup, wrong city...),
        # so the bot doesn't spend money checking them again next time.
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS rejected (domain TEXT PRIMARY KEY, reason TEXT)"
        )
        self.db.commit()

    def seen(self, domain: str) -> bool:
        for table in ("companies", "rejected"):
            row = self.db.execute(
                f"SELECT 1 FROM {table} WHERE domain = ?", (domain,)
            ).fetchone()
            if row:
                return True
        return False

    def reject(self, domain: str, reason: str):
        self.db.execute(
            "INSERT OR REPLACE INTO rejected VALUES (?, ?)", (domain, reason)
        )
        self.db.commit()

    def add(self, company: Company):
        data = asdict(company)
        for key in LIST_FIELDS:
            data[key] = json.dumps(data[key])
        names = ", ".join(data)
        marks = ", ".join("?" for _ in data)
        self.db.execute(
            f"INSERT OR REPLACE INTO companies ({names}) VALUES ({marks})",
            list(data.values()),
        )
        self.db.commit()

    def not_exported(self) -> list[Company]:
        names = [f.name for f in fields(Company)]
        rows = self.db.execute(
            f"SELECT {', '.join(names)} FROM companies WHERE exported = 0 "
            "ORDER BY CAST(fit_score AS INTEGER) DESC"
        ).fetchall()
        companies = []
        for row in rows:
            data = dict(zip(names, row))
            for key in LIST_FIELDS:
                data[key] = json.loads(data[key] or "[]")
            data["fit_score"] = int(data["fit_score"] or 0)
            companies.append(Company(**data))
        return companies

    def mark_exported(self, domains: list[str]):
        self.db.executemany(
            "UPDATE companies SET exported = 1 WHERE domain = ?",
            [(d,) for d in domains],
        )
        self.db.commit()

    def count(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
