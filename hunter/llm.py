"""All AI calls: finding startups on a page, scoring them, writing emails.

Works with Anthropic (Claude), OpenAI (GPT) or Google (Gemini). Each call
forces the model to answer with a fixed JSON shape, so we always get clean,
structured data back instead of free text.
"""

from __future__ import annotations

import json

EXTRACT_TOOL = {
    "name": "save_startups",
    "description": "Save the startups mentioned on the page.",
    "input_schema": {
        "type": "object",
        "properties": {
            "startups": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "website": {
                            "type": "string",
                            "description": "Their own website if the page shows it, else empty.",
                        },
                        "note": {"type": "string", "description": "One line: what they do."},
                    },
                    "required": ["name", "website", "note"],
                },
            }
        },
        "required": ["startups"],
    },
}

QUALIFY_TOOL = {
    "name": "save_assessment",
    "description": "Save the assessment of this company.",
    "input_schema": {
        "type": "object",
        "properties": {
            "is_young_startup": {
                "type": "boolean",
                "description": "Young/small startup (not an agency, corporation, university, investor, or news site).",
            },
            "in_region": {"type": "boolean", "description": "Based in or near the target region."},
            "builds_software": {
                "type": "boolean",
                "description": "Builds a software or tech product where a web/backend engineer would help.",
            },
            "what_they_build": {"type": "string", "description": "One or two plain sentences."},
            "stage": {
                "type": "string",
                "enum": ["pre-seed/idea", "seed", "series A or later", "established", "unknown"],
            },
            "team_size": {"type": "string", "description": "e.g. '2-5', or 'unknown'."},
            "tech_stack": {"type": "array", "items": {"type": "string"}},
            "founders": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Founder names only if the pages state them.",
            },
            "contact_email": {
                "type": "string",
                "description": "Best email from the list found on the site (prefer a founder's or a general one over legal/privacy addresses). Empty if none.",
            },
            "fit_score": {
                "type": "integer",
                "minimum": 0,
                "maximum": 10,
                "description": "How well the candidate fits as a part-time engineer here.",
            },
            "fit_reason": {"type": "string", "description": "One sentence explaining the score."},
        },
        "required": [
            "is_young_startup", "in_region", "builds_software", "what_they_build", "stage",
            "team_size", "tech_stack", "founders", "contact_email", "fit_score", "fit_reason",
        ],
    },
}

EMAIL_TOOL = {
    "name": "save_email",
    "description": "Save the email draft.",
    "input_schema": {
        "type": "object",
        "properties": {
            "subject": {"type": "string"},
            "body": {"type": "string"},
        },
        "required": ["subject", "body"],
    },
}


# The instructions for each task. Also handed to coding assistants in agent
# mode (see hunter/agent.py), so both modes follow exactly the same rules.
def extract_rules(region: str) -> str:
    return (
        "You read web pages and list the startups they mention. Only include "
        f"young companies based in or near {region}. Skip investors, universities, "
        "public bodies, service agencies, large corporations and news publishers. "
        "If the page is itself a startup's website, include that startup. "
        "Never invent websites."
    )


def qualify_rules(region: str) -> str:
    return (
        "You help a job seeker judge whether a company is a good place to ask for a "
        f"part-time engineering role. Target region: {region}. Base every answer on "
        "the website text only; use 'unknown' or empty values instead of guessing."
    )


def email_rules(language: str) -> str:
    return (
        f"You write short, genuine cold emails in {language} from a job seeker to a "
        "startup founder. Rules: under 150 words; open with something specific about "
        "what the startup builds; say clearly what the sender offers and asks for "
        "(a working-student/part-time role, starting with a small paid project); use "
        "only facts from the sender's profile; never name the sender's past clients; "
        "no flattery, buzzwords or exclamation marks; plain text; end with the "
        "sender's name and LinkedIn link."
    )


# Provider name in config.yaml -> the .env variable holding its API key.
PROVIDERS = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "google": "GEMINI_API_KEY",
}


class LLM:
    def __init__(self, provider: str, api_key: str, fast_model: str, writer_model: str):
        # SDKs are imported here so tests run without the packages.
        if provider == "anthropic":
            import anthropic
            self.client = anthropic.Anthropic(api_key=api_key)
        elif provider == "openai":
            import openai
            self.client = openai.OpenAI(api_key=api_key)
        elif provider == "google":
            from google import genai
            self.client = genai.Client(api_key=api_key)
        else:
            raise ValueError(f"Unknown provider {provider!r}, use one of: {', '.join(PROVIDERS)}")
        self.provider = provider
        self.fast_model = fast_model
        self.writer_model = writer_model

    def _call_tool(self, model: str, system: str, prompt: str, tool: dict) -> dict:
        call = {"anthropic": self._anthropic, "openai": self._openai, "google": self._google}
        return call[self.provider](model, system, prompt, tool)

    def _anthropic(self, model: str, system: str, prompt: str, tool: dict) -> dict:
        response = self.client.messages.create(
            model=model,
            max_tokens=1500,
            system=system,
            tools=[tool],
            tool_choice={"type": "tool", "name": tool["name"]},
            messages=[{"role": "user", "content": prompt}],
        )
        for block in response.content:
            if block.type == "tool_use":
                return block.input
        raise RuntimeError("The model did not return structured data")

    def _openai(self, model: str, system: str, prompt: str, tool: dict) -> dict:
        response = self.client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": prompt}],
            tools=[{"type": "function", "function": {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": tool["input_schema"],
            }}],
            tool_choice={"type": "function", "function": {"name": tool["name"]}},
        )
        calls = response.choices[0].message.tool_calls
        if not calls:
            raise RuntimeError("The model did not return structured data")
        return json.loads(calls[0].function.arguments)

    def _google(self, model: str, system: str, prompt: str, tool: dict) -> dict:
        from google.genai import types

        response = self.client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system,
                response_mime_type="application/json",
                response_json_schema=tool["input_schema"],
            ),
        )
        if not response.text:
            raise RuntimeError("The model did not return structured data")
        return json.loads(response.text)

    def extract_startups(self, page_text: str, page_url: str, region: str) -> list[dict]:
        result = self._call_tool(
            self.fast_model,
            system=extract_rules(region),
            prompt=f"Page: {page_url}\n\n{page_text}",
            tool=EXTRACT_TOOL,
        )
        return result.get("startups", [])

    def qualify(self, name: str, website: str, pages_text: str, emails: list[str],
                region: str, profile: str) -> dict:
        return self._call_tool(
            self.fast_model,
            system=qualify_rules(region),
            prompt=(
                f"Candidate profile:\n{profile}\n\n"
                f"Company: {name}\nWebsite: {website}\n"
                f"Emails found on their site: {', '.join(emails) or 'none'}\n\n"
                f"Website text:\n{pages_text}"
            ),
            tool=QUALIFY_TOOL,
        )

    def draft_email(self, company_summary: str, profile: str, language: str) -> dict:
        return self._call_tool(
            self.writer_model,
            system=email_rules(language),
            prompt=f"Sender profile:\n{profile}\n\nStartup:\n{company_summary}",
            tool=EMAIL_TOOL,
        )


def describe(company) -> str:
    """Short text summary of a company, used as input for the email draft."""
    return json.dumps(
        {
            "name": company.name,
            "website": company.website,
            "what_they_build": company.what_they_build,
            "stage": company.stage,
            "tech_stack": company.tech_stack,
            "founders": company.founders,
            "spotted_via": company.hint,
        },
        ensure_ascii=False,
        indent=1,
    )
