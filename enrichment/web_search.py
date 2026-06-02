"""Web search + LLM contact extraction — fallback when social scraping finds no email."""

import json
import re


def enrich_web(name, profession_hint="", openai_api_key=None):
    """
    Search DuckDuckGo for contact info, then extract with LLM (or regex fallback).
    Returns None if nothing useful is found.
    """
    snippets = _ddg_search(name, profession_hint)
    if not snippets:
        return None
    if openai_api_key:
        return _llm_extract(name, snippets, openai_api_key) or _regex_extract(snippets)
    return _regex_extract(snippets)


def _ddg_search(name, profession_hint=""):
    try:
        from duckduckgo_search import DDGS
        hint = profession_hint.strip()
        queries = [
            f'"{name}" {hint} email contact'.strip(),
            f'"{name}" {hint} site:twitter.com OR site:linkedin.com'.strip(),
        ]
        snippets = []
        with DDGS(timeout=8) as ddgs:
            for q in queries:
                try:
                    for r in ddgs.text(q, max_results=2):
                        body = r.get("body") or r.get("snippet", "")
                        if body:
                            snippets.append(body)
                except Exception:
                    pass
        return snippets
    except ImportError:
        return []
    except Exception:
        return []


def _regex_extract(snippets):
    text = " ".join(snippets)
    emails = list(dict.fromkeys(re.findall(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", text)))
    phones = list(dict.fromkeys(re.findall(r"\+?1?\s*[\(\-\.]?\d{3}[\)\-\.\s]\s*\d{3}[\-\.\s]\d{4}", text)))
    # strip common false-positive domains
    emails = [e for e in emails if not any(e.endswith(d) for d in ("example.com", "sentry.io", "w3.org"))]
    if not emails and not phones:
        return None
    return {"emails": emails, "phones": phones, "profiles": {}}


def _llm_extract(name, snippets, api_key):
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        combined = "\n\n".join(snippets[:6])[:3000]
        prompt = (
            f"Extract contact information for the person named '{name}' from these web snippets.\n"
            "Only include info clearly about THIS specific person — ignore unrelated mentions.\n"
            'Return JSON only: {"emails": [...], "phones": [...], "profiles": {"twitter": "url", "linkedin": "url"}}\n'
            "Return empty arrays/objects if nothing is found for a field.\n\n"
            + combined
        )
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        raw = resp.choices[0].message.content.strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        data = json.loads(raw)
        emails = data.get("emails") or []
        phones = data.get("phones") or []
        profiles = data.get("profiles") or {}
        if not emails and not phones and not profiles:
            return None
        return {"emails": emails, "phones": phones, "profiles": profiles}
    except Exception:
        return _regex_extract(snippets)
