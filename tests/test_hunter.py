"""Offline tests: no internet or API key needed.  Run:  python -m unittest -v"""

import csv
import os
import tempfile
import unittest

from hunter.llm import LLM
from hunter.models import Company
from hunter.output import HEADERS, write_csv, write_google_sheet
from hunter.pipeline import Pipeline, best_email
from hunter.store import Store
from hunter.web import extract_emails, find_links, html_to_text, is_blocked, normalize_domain

CONFIG = {
    "location_keywords": ["Dresden", "Sachsen"],
    "search_queries": ["startup dresden"],
    "max_search_results_per_query": 5,
    "seed_pages": [],
    "use_job_board": True,
    "job_board_pages": 2,
    "max_pages_to_read_per_run": 10,
    "max_new_companies_per_run": 10,
    "min_fit_score": 6,
    "email_language": "English",
}

PAGES = {
    "https://news.example/dresden-startups": "<html><body><h1>5 startups from Dresden</h1>"
        "<p>Robocrop builds farm robots.</p><p>Muenchen GmbH is in Munich.</p></body></html>",
    "https://robocrop.io": '<html><body><p>Robocrop - AI for farms, Dresden.</p>'
        '<a href="/impressum">Impressum</a><a href="https://twitter.com/x">Twitter</a></body></html>',
    "https://robocrop.io/impressum": "<p>Robocrop GmbH, 01069 Dresden. "
        "datenschutz@robocrop.io, hello@robocrop.io, logo@2x.png</p>",
    "https://munichtech.de": "<p>Munichtech, based in Munich, Bavaria.</p>",
    "https://quantdresden.de": "<p>Quant Dresden UG builds trading software in Dresden. "
        "jobs@quantdresden.de</p>",
}


class FakeHttp:
    def __init__(self):
        self.requested = []

    def get(self, url):
        self.requested.append(url)
        return PAGES.get(url)

    def get_json(self, url):
        if url.endswith("page=1"):
            return {"data": [
                {"company_name": "Quant Dresden UG", "title": "Backend Developer",
                 "location": "Dresden", "url": "https://jobs.example/1"},
                {"company_name": "Berlin Corp", "title": "Dev", "location": "Berlin",
                 "url": "https://jobs.example/2"},
            ]}
        return {"data": []}


def fake_search(query, max_results):
    results = {
        "startup dresden": [{"href": "https://news.example/dresden-startups"}],
        "Quant Dresden UG Dresden": [
            {"href": "https://www.linkedin.com/company/quant"},  # blocked, skipped
            {"href": "https://quantdresden.de/"},
        ],
        "Munichtech Dresden": [{"href": "https://munichtech.de"}],
    }
    return results.get(query, [])


class FakeLLM:
    def __init__(self):
        self.drafts = 0

    def extract_startups(self, text, url, region):
        return [
            {"name": "Robocrop", "website": "https://robocrop.io", "note": "farm robots"},
            {"name": "Munichtech", "website": "", "note": "?"},
        ]

    def qualify(self, name, website, text, emails, region, profile):
        good = name == "Robocrop"
        return {
            "is_young_startup": True, "in_region": True, "builds_software": True,
            "what_they_build": f"{name} product", "stage": "seed", "team_size": "2-5",
            "tech_stack": ["Python"], "founders": [], "fit_score": 8 if good else 4,
            "contact_email": "hello@robocrop.io" if good else "", "fit_reason": "test",
        }

    def draft_email(self, summary, profile, language):
        self.drafts += 1
        return {"subject": "Hello", "body": "Hi there"}


class WebHelpers(unittest.TestCase):
    def test_normalize_domain(self):
        self.assertEqual(normalize_domain("https://www.Robocrop.io/about?x=1"), "robocrop.io")
        self.assertEqual(normalize_domain("robocrop.io"), "robocrop.io")
        self.assertEqual(normalize_domain(""), "")
        self.assertEqual(normalize_domain("not a url"), "")

    def test_is_blocked_includes_subdomains(self):
        self.assertTrue(is_blocked("de.linkedin.com"))
        self.assertTrue(is_blocked("tu-dresden.de"))
        self.assertFalse(is_blocked("robocrop.io"))

    def test_extract_emails(self):
        text = "Mail: info [at] startup.de, Team@Startup.de, team@startup.de, icon@2x.png"
        self.assertEqual(extract_emails(text), ["info@startup.de", "team@startup.de"])

    def test_find_links_and_text(self):
        html = PAGES["https://robocrop.io"]
        self.assertEqual(find_links(html, "https://robocrop.io", ["impressum"]),
                         ["https://robocrop.io/impressum"])
        self.assertIn("AI for farms", html_to_text(html))

    def test_best_email_skips_privacy_addresses(self):
        self.assertEqual(best_email(["datenschutz@a.de", "hi@a.de"]), "hi@a.de")
        self.assertEqual(best_email(["privacy@a.de"]), "")


class StoreTests(unittest.TestCase):
    def test_add_seen_reject_and_export(self):
        store = Store(":memory:")
        store.add(Company(name="A", domain="a.de", website="https://a.de", fit_score=3,
                          tech_stack=["Go"]))
        store.add(Company(name="B", domain="b.de", website="https://b.de", fit_score=9))
        store.reject("c.de", "not a startup")
        self.assertTrue(store.seen("a.de"))
        self.assertTrue(store.seen("c.de"))
        self.assertFalse(store.seen("d.de"))
        pending = store.not_exported()
        self.assertEqual([c.name for c in pending], ["B", "A"])  # best fit first
        self.assertEqual(pending[1].tech_stack, ["Go"])
        store.mark_exported(["a.de", "b.de"])
        self.assertEqual(store.not_exported(), [])
        self.assertEqual(store.count(), 2)


class PipelineTests(unittest.TestCase):
    def make(self, llm):
        return Pipeline(CONFIG, Store(":memory:"), FakeHttp(), fake_search, llm=llm,
                        profile="me", log=lambda *a: None)

    def test_full_run_with_ai(self):
        llm = FakeLLM()
        pipeline = self.make(llm)
        new = pipeline.run()
        names = sorted(c.name for c in new)
        self.assertEqual(names, ["Quant Dresden UG", "Robocrop"])  # Munich rejected
        robo = next(c for c in new if c.name == "Robocrop")
        self.assertEqual(robo.contact_email, "hello@robocrop.io")
        self.assertEqual(robo.email_subject, "Hello")
        quant = next(c for c in new if c.name == "Quant Dresden UG")
        self.assertEqual(quant.website, "https://quantdresden.de")
        self.assertEqual(quant.hint, "Hiring: Backend Developer")
        self.assertEqual(quant.contact_email, "jobs@quantdresden.de")  # fallback email
        self.assertEqual(quant.email_body, "")  # fit 4 < 6, so no draft
        self.assertEqual(llm.drafts, 1)
        self.assertTrue(pipeline.store.seen("munichtech.de"))  # remembered as rejected

        # A second run finds nothing new and never re-reads rejected sites.
        pipeline.http.requested.clear()
        self.assertEqual(pipeline.run(), [])
        self.assertNotIn("https://munichtech.de", pipeline.http.requested)

    def test_run_without_ai_uses_job_board_only(self):
        new = self.make(None).run()
        self.assertEqual([c.name for c in new], ["Quant Dresden UG"])
        self.assertEqual(new[0].fit_score, 0)

    def test_respects_max_new_companies(self):
        pipeline = self.make(FakeLLM())
        pipeline.cfg = dict(CONFIG, max_new_companies_per_run=1)
        self.assertEqual(len(pipeline.run()), 1)


class LLMGuardTests(unittest.TestCase):
    def test_qualify_drops_invented_email(self):
        llm = object.__new__(LLM)  # skip __init__, no API client needed
        llm.fast_model = "x"
        llm._call_tool = lambda *a, **k: {"contact_email": "ceo@invented.de"}
        result = llm.qualify("A", "https://a.de", "text", ["hi@a.de"], "Dresden", "me")
        self.assertEqual(result["contact_email"], "")


class OutputTests(unittest.TestCase):
    def test_csv_appends_with_one_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "out", "s.csv")
            c = Company(name="A", domain="a.de", website="https://a.de", fit_score=7,
                        email_body="Hi,\nline two")
            write_csv(path, [c])
            write_csv(path, [c])
            with open(path, encoding="utf-8") as f:
                rows = list(csv.reader(f))
            self.assertEqual(rows[0], HEADERS)
            self.assertEqual(len(rows), 3)
            self.assertEqual(rows[1][HEADERS.index("Email draft")], "Hi,\nline two")

    def test_sheet_skipped_without_credentials(self):
        self.assertIsNone(write_google_sheet("/nonexistent.json", "x", []))


if __name__ == "__main__":
    unittest.main()
