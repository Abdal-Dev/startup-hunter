"""Supported countries and turning city + country into search settings."""

from __future__ import annotations

# Search phrases used in every country. {city} is filled in.
ENGLISH_QUERIES = [
    "{city} startups list",
    "{city} software startup founded",
    "{city} AI startup",
    "{city} startup hiring developer",
]

# name: DuckDuckGo search region, other names people may type, and phrases in the
# local language (they find far more local startups than English alone).
COUNTRIES = {
    "Austria": {"search_region": "at-de", "aliases": ["at", "österreich"], "queries": [
        "Startup {city} Software gegründet", "Startups in {city} Liste", "{city} KI Startup"]},
    "Belgium": {"search_region": "be-nl", "aliases": ["be", "belgië", "belgique"], "queries": [
        "startups in {city} lijst", "startup {city} logiciel", "liste startups {city}"]},
    "Czechia": {"search_region": "cz-cs", "aliases": ["cz", "czech republic", "česko"], "queries": [
        "startupy {city} seznam", "startup {city} software", "{city} AI startup česko"]},
    "Denmark": {"search_region": "dk-da", "aliases": ["dk", "danmark"], "queries": [
        "startups i {city}", "iværksættere {city} software", "{city} AI startup danmark"]},
    "Estonia": {"search_region": "ee-et", "aliases": ["ee", "eesti"], "queries": [
        "idufirmad {city}", "{city} idufirma tarkvara"]},
    "Finland": {"search_region": "fi-fi", "aliases": ["fi", "suomi"], "queries": [
        "startup-yritykset {city}", "{city} startup ohjelmisto"]},
    "France": {"search_region": "fr-fr", "aliases": ["fr"], "queries": [
        "liste startups {city}", "startup {city} logiciel", "startup IA {city}"]},
    "Germany": {"search_region": "de-de", "aliases": ["de", "deutschland"], "job_board": True,
                "queries": ["Startup {city} Software gegründet", "Startups in {city} Liste",
                            "{city} KI Startup", "{city} Ausgründung Startup Software"]},
    "Ireland": {"search_region": "ie-en", "aliases": ["ie", "éire"], "queries": [
        "{city} tech startups Ireland"]},
    "Italy": {"search_region": "it-it", "aliases": ["it", "italia"], "queries": [
        "elenco startup {city}", "startup {city} software", "startup intelligenza artificiale {city}"]},
    "Netherlands": {"search_region": "nl-nl", "aliases": ["nl", "nederland", "holland"], "queries": [
        "startups in {city} lijst", "startup {city} software", "{city} AI startup"]},
    "Poland": {"search_region": "pl-pl", "aliases": ["pl", "polska"], "queries": [
        "startupy {city} lista", "startup {city} oprogramowanie", "{city} startup AI"]},
    "Portugal": {"search_region": "pt-pt", "aliases": ["pt"], "queries": [
        "startups em {city} lista", "startup {city} software", "startup inteligência artificial {city}"]},
    "Spain": {"search_region": "es-es", "aliases": ["es", "españa"], "queries": [
        "startups en {city} lista", "startup {city} software", "startup inteligencia artificial {city}"]},
    "Sweden": {"search_region": "se-sv", "aliases": ["se", "sverige"], "queries": [
        "startups i {city}", "startup {city} mjukvara", "{city} AI startup"]},
    "Switzerland": {"search_region": "ch-de", "aliases": ["ch", "schweiz", "suisse"], "queries": [
        "Startup {city} Software gegründet", "Startups in {city} Liste", "startup {city} logiciel"]},
    "United Kingdom": {"search_region": "uk-en", "aliases": ["uk", "gb", "england", "great britain"],
                       "queries": ["{city} tech startups UK"]},
}


def find_country(name: str) -> str | None:
    """'de', 'deutschland' or 'germany' -> 'Germany'. None if not supported."""
    wanted = (name or "").strip().lower()
    for country, info in COUNTRIES.items():
        if wanted == country.lower() or wanted in info["aliases"]:
            return country
    return None


def apply_location(cfg: dict) -> list[str]:
    """Turn `country`, `city` and `nearby` into the settings the pipeline uses.

    Fills in location_keywords, region, search_queries, search_region and
    use_job_board. Old configs that set location_keywords and search_queries
    directly keep working. Returns notes to show the user.
    """
    notes = []
    if "city" not in cfg:  # old-style config
        cfg.setdefault("search_region", "de-de")
        return notes
    country = find_country(cfg.get("country", ""))
    if country is None:
        raise ValueError(f"Country {cfg.get('country')!r} isn't supported. "
                         f"Use one of: {', '.join(COUNTRIES)}.")
    info, city = COUNTRIES[country], cfg["city"].strip()
    cfg["country"] = country
    # Only the city and nearby places count as "in the area", not the whole country.
    cfg["location_keywords"] = [city, *(cfg.get("nearby") or [])]
    cfg["region"] = f"{city}, {country}"
    phrases = info["queries"] + ENGLISH_QUERIES + list(cfg.get("extra_search_queries") or [])
    queries = []
    for phrase in phrases:
        query = phrase.format(city=city, country=country)
        if query not in queries:
            queries.append(query)
    cfg["search_queries"] = queries
    cfg["search_region"] = info["search_region"]
    if cfg.get("use_job_board") and not info.get("job_board"):
        cfg["use_job_board"] = False
        notes.append("The job board only covers Germany, so it's skipped for "
                     f"{country}. Web searches still run.")
    return notes
