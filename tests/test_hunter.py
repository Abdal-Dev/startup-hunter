"""Offline tests: no internet or API key needed.  Run:  python -m unittest -v"""

import csv
import json
import os
import tempfile
import unittest

from hunter.agent import import_results, write_todo
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


def assessment(**changes):
    a = {"is_young_startup": True, "in_region": True, "builds_software": True,
         "what_they_build": "x", "stage": "seed", "team_size": "2-5", "tech_stack": [],
         "founders": [], "contact_email": "", "fit_score": 8, "fit_reason": "test"}
    return dict(a, **changes)


class AssessmentGuardTests(unittest.TestCase):
    def test_drops_invented_email(self):
        pipeline = Pipeline(CONFIG, Store(":memory:"), FakeHttp(), fake_search)
        c = Company(name="A", domain="a.de", website="https://a.de",
                    emails_on_site=["hi@a.de"], contact_email="hi@a.de")
        self.assertTrue(pipeline.apply_assessment(c, assessment(contact_email="ceo@a.de")))
        self.assertEqual(c.contact_email, "hi@a.de")  # kept the one actually on the site


class AgentModeTests(unittest.TestCase):
    """No API key: the pipeline collects, a coding assistant reviews, we import."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.pipeline = Pipeline(CONFIG, Store(":memory:"), FakeHttp(), fake_search,
                                 log=lambda *a: None, agent_mode=True)

    def tearDown(self):
        self.tmp.cleanup()

    def collect(self):
        self.pipeline.run()
        return write_todo(self.tmp.name, self.pipeline, CONFIG)

    def review(self, companies):
        with open(os.path.join(self.tmp.name, "results.json"), "w") as f:
            json.dump({"companies": companies}, f)
        return import_results(self.tmp.name, self.pipeline, CONFIG, log=lambda *a: None)

    def test_collect_holds_companies_for_review(self):
        todo = self.collect()
        self.assertEqual([c["domain"] for c in todo["companies"]], ["quantdresden.de"])
        self.assertIn("trading software", todo["companies"][0]["website_text"])
        self.assertEqual(todo["pages_to_read"], ["https://news.example/dresden-startups"])
        self.assertIn("quantdresden.de", todo["instructions"]["already_known_domains"])
        self.assertEqual(self.pipeline.store.not_exported(), [])  # not in the sheet yet

    def test_import_saves_checked_results(self):
        self.collect()
        saved = self.review([
            # From todo.json, with an invented email that must be dropped.
            dict(assessment(contact_email="ceo@invented.de"), website="https://quantdresden.de",
                 name="Quant Dresden UG", email_subject="Hi", email_body="Draft"),
            # Found by the assistant on a page: the site is checked like any lead.
            dict(assessment(contact_email="hello@robocrop.io", fit_score=7),
                 website="https://robocrop.io", name="Robocrop", note="news page",
                 email_subject="Hello", email_body="Draft 2"),
            # Not in the region, so the import rejects it.
            dict(assessment(), website="https://munichtech.de", name="Munichtech"),
            {"website": "https://broken.de", "name": "Broken"},  # missing fields
        ])
        by_name = {c.name: c for c in saved}
        self.assertEqual(sorted(by_name), ["Quant Dresden UG", "Robocrop"])
        self.assertEqual(by_name["Quant Dresden UG"].contact_email, "jobs@quantdresden.de")
        self.assertEqual(by_name["Robocrop"].email_body, "Draft 2")
        self.assertEqual(by_name["Robocrop"].source, "coding assistant")
        self.assertEqual(len(self.pipeline.store.not_exported()), 2)
        self.assertTrue(self.pipeline.store.seen("munichtech.de"))
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "results.json")))
        with open(os.path.join(self.tmp.name, "todo.json")) as f:
            self.assertEqual(json.load(f)["companies"], [])

    def test_import_rejects_and_keeps_unreviewed(self):
        self.collect()
        saved = self.review([dict(assessment(is_young_startup=False),
                                  website="https://quantdresden.de", name="Quant")])
        self.assertEqual(saved, [])
        self.assertIsNone(self.pipeline.store.get("quantdresden.de"))  # removed
        self.assertTrue(self.pipeline.store.seen("quantdresden.de"))   # and remembered


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
