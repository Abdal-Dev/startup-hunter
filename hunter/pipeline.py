"""The main flow: collect leads -> find websites -> read them -> score -> draft emails."""

from __future__ import annotations

import datetime as dt

from .llm import describe
from .models import Company, Lead
from .web import extract_emails, find_links, html_to_text, is_blocked, normalize_domain

JOB_BOARD_URL = "https://www.arbeitnow.com/api/job-board-api?page={page}"
EXTRA_PAGE_WORDS = ["impressum", "imprint", "kontakt", "contact", "about", "team", "über uns"]
LEGAL_EMAIL_WORDS = ("datenschutz", "privacy", "dsgvo", "gdpr", "legal", "noreply", "no-reply")


def best_email(emails: list[str]) -> str:
    """First email that isn't a legal/privacy/no-reply address."""
    for email in emails:
        if not email.startswith(LEGAL_EMAIL_WORDS):
            return email
    return ""


class Pipeline:
    def __init__(self, config, store, http, search, llm=None, profile="", log=print):
        self.cfg = config
        self.store = store
        self.http = http          # fetches pages (hunter.web.Http)
        self.search = search      # function(query, max_results) -> results
        self.llm = llm            # hunter.llm.LLM, or None to skip the AI steps
        self.profile = profile
        self.log = log
        self.region = ", ".join(config["location_keywords"][:3])

    # ------------------------------------------------------------ step 1: leads
    def leads_from_job_board(self) -> list[Lead]:
        leads = []
        keywords = [k.lower() for k in self.cfg["location_keywords"]]
        for page in range(1, self.cfg.get("job_board_pages", 3) + 1):
            data = self.http.get_json(JOB_BOARD_URL.format(page=page))
            if data is None and page == 1:
                self.log("  ! job board could not be reached (check your internet)")
            if not data or not data.get("data"):
                break
            for job in data["data"]:
                if any(k in (job.get("location") or "").lower() for k in keywords):
                    leads.append(Lead(
                        name=job.get("company_name", "").strip(),
                        source="job board",
                        source_url=job.get("url", ""),
                        hint=f"Hiring: {job.get('title', '')}",
                    ))
        self.log(f"  job board: {len(leads)} jobs in the region")
        return leads

    def pages_to_read(self) -> list[str]:
        urls = list(self.cfg.get("seed_pages") or [])
        for query in self.cfg["search_queries"]:
            for result in self.search(query, self.cfg["max_search_results_per_query"]):
                url = result.get("href", "")
                if url and url not in urls and not normalize_domain(url).endswith(
                        ("linkedin.com", "xing.com", "facebook.com", "instagram.com")):
                    urls.append(url)
        return urls[: self.cfg["max_pages_to_read_per_run"]]

    def leads_from_pages(self) -> list[Lead]:
        if not self.llm:
            self.log("  web pages: skipped (needs an AI API key to read them)")
            return []
        leads = []
        pages = self.pages_to_read()
        self.log(f"  reading {len(pages)} web pages...")
        for url in pages:
            html = self.http.get(url)
            if not html:
                continue
            try:
                found = self.llm.extract_startups(html_to_text(html), url, self.region)
            except Exception as error:
                self.log(f"  ! could not read {url}: {error}")
                continue
            for s in found:
                leads.append(Lead(name=s["name"].strip(), website=s.get("website", ""),
                                  source="web", source_url=url, hint=s.get("note", "")))
        self.log(f"  web pages: {len(leads)} startup mentions")
        return leads

    # ------------------------------------------------------- step 2: websites
    def find_website(self, lead: Lead) -> str:
        if lead.website and not is_blocked(normalize_domain(lead.website)):
            return lead.website
        for result in self.search(f"{lead.name} {self.cfg['location_keywords'][0]}", 5):
            domain = normalize_domain(result.get("href", ""))
            if domain and not is_blocked(domain):
                return f"https://{domain}"
        return ""

    # --------------------------------------------------- step 3: read the site
    def read_site(self, website: str) -> tuple[str, list[str]]:
        html = self.http.get(website)
        if not html:
            return "", []
        texts = [html_to_text(html, 4000)]
        emails = extract_emails(html)
        for link in find_links(html, website, EXTRA_PAGE_WORDS)[:3]:
            if normalize_domain(link) != normalize_domain(website):
                continue
            sub = self.http.get(link)
            if sub:
                texts.append(html_to_text(sub, 2500))
                emails += [e for e in extract_emails(sub) if e not in emails]
        return "\n\n".join(texts), emails

    # ------------------------------------------------------------- the run
    def run(self) -> list[Company]:
        self.log("1/4 Collecting leads")
        leads = []
        if self.cfg.get("use_job_board"):
            leads += self.leads_from_job_board()
        leads += self.leads_from_pages()

        self.log("2/4 Checking companies")
        new, seen_names = [], set()
        keywords = [k.lower() for k in self.cfg["location_keywords"]]
        for lead in leads:
            if len(new) >= self.cfg["max_new_companies_per_run"]:
                self.log("  reached max_new_companies_per_run, stopping")
                break
            key = lead.name.lower()
            if not lead.name or key in seen_names:
                continue
            seen_names.add(key)

            website = self.find_website(lead)
            domain = normalize_domain(website)
            if not domain or is_blocked(domain) or self.store.seen(domain):
                continue

            text, emails = self.read_site(website)
            if not text:
                self.store.reject(domain, "website unreachable")
                continue
            if not any(k in (text + lead.hint).lower() for k in keywords):
                self.store.reject(domain, "no sign of the region on the site")
                continue

            company = Company(
                name=lead.name, domain=domain, website=website, source=lead.source,
                source_url=lead.source_url, hint=lead.hint,
                found_on=dt.date.today().isoformat(), emails_on_site=emails,
                contact_email=best_email(emails),
            )
            if self.llm and not self.score(company, text):
                continue
            self.store.add(company)
            new.append(company)
            self.log(f"  + {company.name} ({domain}) fit {company.fit_score}/10")

        self.log("3/4 Drafting emails")
        drafted = 0
        if self.llm:
            for company in new:
                if company.fit_score >= self.cfg["min_fit_score"] and company.contact_email:
                    try:
                        draft = self.llm.draft_email(
                            describe(company), self.profile, self.cfg["email_language"])
                        company.email_subject = draft["subject"]
                        company.email_body = draft["body"]
                        self.store.add(company)
                        drafted += 1
                    except Exception as error:
                        self.log(f"  ! draft failed for {company.name}: {error}")
        self.log(f"  {drafted} drafts written")
        return new

    def score(self, company: Company, text: str) -> bool:
        """Fill in the AI's assessment. Returns False if the company is rejected."""
        try:
            a = self.llm.qualify(company.name, company.website, text,
                                 company.emails_on_site, self.region, self.profile)
        except Exception as error:
            self.log(f"  ! could not score {company.name}: {error}")
            return False
        if not (a["is_young_startup"] and a["in_region"] and a["builds_software"]):
            self.store.reject(company.domain, a.get("fit_reason", "not a fit"))
            return False
        company.what_they_build = a["what_they_build"]
        company.stage = a["stage"]
        company.team_size = a["team_size"]
        company.tech_stack = a["tech_stack"]
        company.founders = a["founders"]
        company.contact_email = a["contact_email"] or company.contact_email
        company.fit_score = int(a["fit_score"])
        company.fit_reason = a["fit_reason"]
        return True
