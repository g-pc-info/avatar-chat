"""Brave Search API client (web search)."""
import html
import os
import re

import httpx

# テスト用に差し替え可能(通常は変更不要)
BRAVE_URL = os.environ.get("AVATAR_BRAVE_URL", "https://api.search.brave.com/res/v1/web/search")

# 画面の言語 → Brave の ui_lang / search_lang (合わなければ422になり、指定なしで再試行する)
LANG_PARAMS = {
    "en": {"ui_lang": "en-US", "search_lang": "en"},
    "zh": {"ui_lang": "zh-CN", "search_lang": "zh-hans"},
    "es": {"ui_lang": "es-ES", "search_lang": "es"},
    "pt": {"ui_lang": "pt-BR", "search_lang": "pt-br"},
}


class SearchError(Exception):
    """User-facing search failure. `key` is an i18n key (server side translates it);
    the message never contains the API key."""

    def __init__(self, key: str, **params):
        super().__init__(key)
        self.key = key
        self.params = params


def _clean(s, limit: int = 300) -> str:
    s = html.unescape(re.sub(r"<[^>]+>", "", s or ""))
    return re.sub(r"\s+", " ", s).strip()[:limit]


async def brave_search(query: str, api_key: str, count: int = 5, country: str = "JP", lang: str = "ja") -> list:
    if not api_key:
        raise SearchError("srv_s_nokey")
    query = query.strip()[:400]
    if not query:
        raise SearchError("srv_s_emptyq")
    count = max(1, min(10, int(count)))
    params = {"q": query, "count": count}
    if country:
        params["country"] = country
        if country == "JP" and lang == "ja":
            params["ui_lang"] = "ja-JP"
    params.update(LANG_PARAMS.get(lang, {}))
    headers = {"X-Subscription-Token": api_key, "Accept": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=8.0)) as c:
            r = await c.get(BRAVE_URL, params=params, headers=headers)
            if r.status_code == 422:  # 国・言語の指定が合わなかった場合は最小の指定で再試行
                r = await c.get(BRAVE_URL, params={"q": query, "count": count}, headers=headers)
    except httpx.HTTPError as e:
        raise SearchError("srv_s_conn", err=type(e).__name__)
    if r.status_code in (401, 403):
        raise SearchError("srv_s_badkey")
    if r.status_code == 429:
        raise SearchError("srv_s_rate")
    if r.status_code >= 400:
        raise SearchError("srv_s_fail", code=r.status_code)
    try:
        data = r.json()
    except Exception:
        raise SearchError("srv_s_parse")
    out = []
    for it in (data.get("web") or {}).get("results") or []:
        url = it.get("url") or ""
        if not re.match(r"https?://", url):
            continue
        desc = it.get("description") or ""
        if "{{" in desc:  # ページのテンプレートの残骸(中身のない抜粋)は捨てる
            desc = ""
        out.append({"title": _clean(it.get("title"), 120) or url, "url": url,
                    "snippet": _clean(desc)})
    return out[:count]
