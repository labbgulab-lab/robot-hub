"""Web search for Pepper's free conversation (asked for 2026-11-05).

The Realtime model gets one function tool, `web_search(query)`. This module
runs it through the OpenAI Responses API with its built-in `web_search` tool,
on the same GPT key, and returns a 2-3 sentence answer that is fed back to the
Realtime model. Free conversation only: the scripted demo is a closed flow
and never looks anything up. Lab questions still come only from lab_facts.md.
"""

from __future__ import annotations

from typing import Optional

RESPONSES_URL = "https://api.openai.com/v1/responses"
MODEL_URL = "https://api.openai.com/v1/models/"
MODEL = "gpt-4.1-mini"
TIMEOUT_S = 8.0
PROBE_TIMEOUT_S = 6.0

# Said by Pepper while it searches, so the silence is not awkward. Pre-made in
# the conversation voice (offline cache), like the quick phrases.
CHECK_LINES = {"en": "Let me check…", "he": "רגע, אני בודק…"}

TOOL = {
    "type": "function", "name": "web_search",
    "description": ("Look something up on the internet: news, sports results, weather, "
                    "opening hours, prices, recent events, or any fact you do not know. "
                    "Never for questions about the lab you are in."),
    "parameters": {"type": "object", "properties": {
        "query": {"type": "string", "description": "What to look up, as a short search query"}},
        "required": ["query"]},
}

PROMPT = ("You can look things up online with the web_search tool. Use it only for current "
          "facts you do not know (news, sports, weather, prices, opening hours, recent events). "
          "When you call it, say nothing first: Pepper says 'let me check' by itself. When the "
          "result comes back, answer in one or two short sentences. If the search failed, say "
          "briefly that you could not check it online and answer from what you know. Never "
          "search for questions about the lab you are in: those come only from the lab facts.")

FOLLOW_UP = ("The web search result is in. Answer the person's question now in one or two "
             "short sentences, in the language they spoke. If the search failed, say briefly "
             "that you could not check it online, then answer from what you know.")


class SearchFailed(RuntimeError):
    pass


def _sources(data: dict) -> int:
    urls = set()
    for item in data.get("output") or []:
        if item.get("type") == "message":
            for part in item.get("content") or []:
                for a in part.get("annotations") or []:
                    if a.get("type") == "url_citation" and a.get("url"):
                        urls.add(a["url"])
        elif item.get("type") == "web_search_call":
            for s in ((item.get("action") or {}).get("sources") or []):
                if isinstance(s, dict) and s.get("url"):
                    urls.add(s["url"])
    return len(urls)


def _text(data: dict) -> str:
    if isinstance(data.get("output_text"), str) and data["output_text"].strip():
        return data["output_text"].strip()
    out = []
    for item in data.get("output") or []:
        if item.get("type") == "message":
            for part in item.get("content") or []:
                if part.get("type") == "output_text" and part.get("text"):
                    out.append(part["text"])
    return " ".join(out).strip()


async def search(key: str, query: str, language: str, timeout: float = TIMEOUT_S) -> tuple[str, int]:
    """(answer, number of sources). Raises SearchFailed (or asyncio.TimeoutError)."""
    import httpx
    if not key:
        raise SearchFailed("no GPT key")
    body = {"model": MODEL, "tools": [{"type": "web_search"}],
            "input": "{}\n\nAnswer in 2-3 short sentences in {}. Plain text, no links, no lists."
                     .format(query.strip()[:300], language)}
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            r = await client.post(RESPONSES_URL, json=body,
                                  headers={"Authorization": "Bearer " + key})
        except httpx.TimeoutException as exc:
            raise SearchFailed("timeout") from exc
        except httpx.HTTPError as exc:
            raise SearchFailed("no connection") from exc
    if r.status_code != 200:
        raise SearchFailed("HTTP {}".format(r.status_code))
    try:
        data = r.json()
    except ValueError as exc:
        raise SearchFailed("a reply that is not JSON") from exc
    text = _text(data)
    if not text:
        raise SearchFailed("an empty answer")
    return text[:900], _sources(data)


async def probe(key: str) -> str:
    """Can this laptop search with this key? 'ok' | 'no_internet' | 'no_access' | 'no_key'.
    A free call (the model's details), made when the toggle is turned on."""
    import httpx
    if not key:
        return "no_key"
    try:
        async with httpx.AsyncClient(timeout=PROBE_TIMEOUT_S) as client:
            r = await client.get(MODEL_URL + MODEL, headers={"Authorization": "Bearer " + key})
    except httpx.HTTPError:
        return "no_internet"
    if r.status_code == 200:
        return "ok"
    if r.status_code in (401, 403, 404):
        return "no_access"
    return "ok" if r.status_code >= 500 else "no_access"


REASONS = {"no_internet": "No internet on this network", "no_access": "This key can't search",
           "no_key": "No GPT key"}


def availability(experience: str, has_key: bool, check: str) -> dict:
    """What the dashboard shows for the Web search toggle."""
    if experience != "free":
        reason = "Not in the scripted demo" if experience == "feelings:script" else "Only in free conversation"
    elif not has_key:
        reason = "No GPT key"
    else:
        reason = REASONS.get(check, "")
    return {"available": not reason, "reason": reason, "check": check}


def language_of(text: Optional[str], fallback: str) -> str:
    from .speech import is_hebrew
    if text and is_hebrew(text):
        return "he"
    if text and any(c.isalpha() for c in text):
        return "en"
    return "he" if fallback == "he" else "en"
