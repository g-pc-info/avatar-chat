"""気象庁の予報JSON(https://www.jma.go.jp/bosai/)から、質問文に出てきた地域の天気を取得する。

ネット検索(Brave)のスニペットは天気ポータルだと中身が空になりやすいので、
「天気の質問」かつ「地域が特定できる」ときは、気象庁の公式データを使う。
気象庁ホームページの利用規約: 出典を明示すれば二次利用できる(加工した旨も記載)。
"""
import asyncio
import os
import re
import time
from datetime import datetime

import httpx

BASE = os.environ.get("AVATAR_JMA_URL", "https://www.jma.go.jp/bosai").rstrip("/")
PAGE_URL = "https://www.jma.go.jp/bosai/forecast/#area_type=offices&area_code={code}"
TIMEOUT = httpx.Timeout(10.0, connect=5.0)
MAX_OFFICES = 9

# 天気の質問かどうか(日本語・中国語・英語・スペイン語・ポルトガル語)
WEATHER_RE = re.compile(
    r"天気|天候|気温|降水|予報|傘|(?:雨|雪)(?:が|は)?降|天气|气温|下雨|下雪|天氣|"
    r"\b(?:weather|forecast|temperature|umbrella|rain|raining|snow|snowing)\b|"
    r"\b(?:tiempo|clima|pron[oó]stico|temperatura|lluvia|llover|paraguas|nieve)\b|"
    r"\b(?:previs[aã]o|chuva|chover|guarda-chuva|neve)\b", re.I)

# 広い地域名 → 気象庁の府県予報区コード
REGIONS = {
    "北海道": ["011000", "012000", "013000", "014030", "014100", "015000", "016000", "017000"],
    "東北": ["020000", "030000", "040000", "050000", "060000", "070000"],
    "関東": ["080000", "090000", "100000", "110000", "120000", "130000", "140000"],
    "関東甲信": ["080000", "090000", "100000", "110000", "120000", "130000", "140000", "190000", "200000"],
    "甲信": ["190000", "200000"],
    "東海": ["210000", "220000", "230000", "240000"],
    "北陸": ["150000", "160000", "170000", "180000"],
    "近畿": ["250000", "260000", "270000", "280000", "290000", "300000"],
    "関西": ["250000", "260000", "270000", "280000", "290000", "300000"],
    "中国": ["310000", "320000", "330000", "340000", "350000"],
    "四国": ["360000", "370000", "380000", "390000"],
    "九州": ["400000", "410000", "420000", "430000", "440000", "450000", "460100"],
    "九州北部": ["400000", "410000", "420000", "430000", "440000"],
    "九州南部": ["450000", "460100"],
    "沖縄": ["471000", "472000", "473000", "474000"],
}

# 英語・簡体字・スペイン語/ポルトガル語の呼び方(広い地域と、よく聞かれる都市)
REGIONS.update({
    "Hokkaido": REGIONS["北海道"], "Tohoku": REGIONS["東北"], "Kanto": REGIONS["関東"],
    "Tokai": REGIONS["東海"], "Hokuriku": REGIONS["北陸"], "Kinki": REGIONS["近畿"],
    "Kansai": REGIONS["近畿"], "Chugoku": REGIONS["中国"], "Shikoku": REGIONS["四国"],
    "Kyushu": REGIONS["九州"], "Okinawa": REGIONS["沖縄"],
    "关东": REGIONS["関東"], "东北": REGIONS["東北"], "东海": REGIONS["東海"], "北陆": REGIONS["北陸"],
    "关西": REGIONS["近畿"], "近畿": REGIONS["近畿"], "冲绳": REGIONS["沖縄"], "九州": REGIONS["九州"],
})
ALIASES = {  # 名前 -> 府県予報区コード
    "东京": "130000", "大阪": "270000", "福冈": "400000", "横滨": "140000", "神户": "280000",
    "广岛": "340000", "长崎": "420000", "鹿儿岛": "460100", "冈山": "330000", "静冈": "220000",
    "Tokio": "130000", "Kioto": "260000", "Quioto": "260000",
}
STOP_EN = {"date", "nose", "kami", "tome", "line", "view", "sand", "mino", "mori"}  # ふつうの英単語と紛らわしい地名

_area = None
_names = None
_fc_cache = {}   # code -> (time, json)
_ov_cache = {}


class WeatherError(Exception):
    pass


async def _get_json(url: str):
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False) as c:
            r = await c.get(url)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        raise WeatherError(f"{type(e).__name__}: {e}")


async def _load_area():
    global _area, _names
    if _area is None:
        _area = await _get_json(f"{BASE}/common/const/area.json")
        _names = _build_names(_area)
    return _area


def _build_names(a: dict) -> list:
    """(文字列, 種類, コード) の一覧。文字列が長い順に照合する。"""
    items, seen = [], set()

    def add(s, kind, code):
        s = s.strip()
        ascii_ = s.isascii()
        if len(s) < (4 if ascii_ else 2) or s.lower() in seen or s.lower() in STOP_EN:
            return
        seen.add(s.lower())
        # 英字の名前は、大文字小文字を区別せず、前後が英字でないときだけ一致させる
        pat = re.compile(r"(?<![A-Za-z])" + re.escape(s) + r"(?![A-Za-z])", re.I) if ascii_ else None
        items.append((s, kind, code, pat))

    for k, codes in REGIONS.items():
        if k.isascii():
            add(k, "region", k)
        else:
            add(k + "地方", "region", k)
            add(k, "region", k)
    for k, code in ALIASES.items():
        add(k, "office", code)
    for code, o in a["offices"].items():
        n = re.sub(r"（.*?）", "", o["name"])
        add(n, "office", code)
        stripped = re.sub(r"[県府]$|地方$", "", n)
        if n == "東京都":
            stripped = "東京"
        add(stripped, "office", code)
        en = re.sub(r"\s*(\(.*?\)|Prefecture|Region|Metropolis)\s*", "", o.get("enName", "")).strip()
        add(en, "office", code)
    for code, o in a["class10s"].items():
        n = o["name"]
        add(n, "class10", code)
        add(re.sub(r"地方$", "", n), "class10", code)
        add(re.sub(r"\s*(Region|Area)$", "", o.get("enName", "")), "class10", code)
    for code, o in a["class20s"].items():
        n = o["name"]
        add(n, "class20", code)
        b = re.sub(r"[市町村]$", "", n)
        if not n.endswith("区"):
            add(b, "class20", code)
        add(re.sub(r"\s*(City|Town|Village|Ward)$", "", o.get("enName", "")), "class20", code)
    items.sort(key=lambda t: -len(t[0]))  # 長い名前を先に照合(「東京都」を先に取り、「京都」と誤認しない)
    return items


def is_weather_question(text: str) -> bool:
    return bool(WEATHER_RE.search(text))


def _office_of(a: dict, kind: str, code: str):
    """(府県予報区コード, 絞り込むclass10コードまたはNone)"""
    if kind == "office":
        return code, None
    if kind == "class10":
        return a["class10s"][code]["parent"], code
    c15 = a["class20s"][code]["parent"]
    c10 = a["class15s"][c15]["parent"]
    return a["class10s"][c10]["parent"], c10


def find_places(text: str, a: dict) -> list:
    """質問文に出てきた地域を、出現順に [(label, [(office, class10|None), ...])] で返す。"""
    spans, hits = [], []
    for s, kind, code, pat in _names:
        if pat is not None:
            found = [(m.start(), m.end()) for m in pat.finditer(text)]
        else:
            found, start = [], 0
            while True:
                i = text.find(s, start)
                if i < 0:
                    break
                found.append((i, i + len(s)))
                start = i + len(s)
        for i, j in found:
            if not any(i < e and j > b for b, e in spans):
                spans.append((i, j))
                hits.append((i, s, kind, code))
    hits.sort()
    out, used = [], set()
    for _, s, kind, code in hits:
        if kind == "region":
            targets = [(o, None) for o in REGIONS[code]]
        else:
            targets = [_office_of(a, kind, code)]
        key = tuple(targets)
        if key in used:
            continue
        used.add(key)
        out.append((s, targets))
    return out


async def _forecast(code: str):
    now = time.time()
    hit = _fc_cache.get(code)
    if hit and now - hit[0] < 600:
        return hit[1]
    data = await _get_json(f"{BASE}/forecast/data/forecast/{code}.json")
    _fc_cache[code] = (now, data)
    return data


async def _overview(code: str) -> str:
    now = time.time()
    hit = _ov_cache.get(code)
    if hit and now - hit[0] < 600:
        return hit[1]
    try:
        d = await _get_json(f"{BASE}/forecast/data/overview_forecast/{code}.json")
        text = re.sub(r"\s+", "", str(d.get("text", "")))
    except WeatherError:
        text = ""
    _ov_cache[code] = (now, text)
    return text


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


def _day_label(d: datetime, today) -> str:
    diff = (d.date() - today).days
    base = {0: "今日", 1: "明日", 2: "明後日"}.get(diff, "")
    return f"{base}({d:%m/%d})" if base else f"{d:%m/%d}"


def _clean(s: str) -> str:
    return re.sub(r"[　\s]+", " ", s).strip()


_CODE_WORD = {"1": "晴れ", "2": "くもり", "3": "雨", "4": "雪"}


def _summarize(fc: list, detail: bool, only_class10: str = None) -> str:
    today = datetime.now().date()
    short = fc[0]["timeSeries"]
    head = f"気象庁 {fc[0].get('publishingOffice', '')} {_dt(fc[0]['reportDatetime']):%m/%d %H:%M}発表"
    lines = [head]

    areas = short[0]["areas"]
    if only_class10:
        sel = [x for x in areas if x["area"]["code"] == only_class10] or areas[:1]
    else:
        sel = areas if detail else areas[:1]
    days = [_dt(t) for t in short[0]["timeDefines"]]
    for x in sel:
        parts = []
        for d, w in zip(days, x.get("weathers", [])):
            parts.append(f"{_day_label(d, today)} {_clean(w)}")
        lines.append(f"{x['area']['name']}の天気: " + " / ".join(parts))

    # 降水確率(6時間ごと)
    pops = short[1] if len(short) > 1 else None
    if pops:
        pd = [_dt(t) for t in pops["timeDefines"]]
        sel_codes = {x["area"]["code"] for x in sel}
        for x in pops["areas"]:
            if x["area"]["code"] not in sel_codes:
                continue
            seq = [f"{d:%d日%H}-{(d.hour + 6 - 1) % 24 + 1:02d}時 {p}%" for d, p in zip(pd, x.get("pops", [])) if p != ""]
            if seq:
                lines.append(f"{x['area']['name']}の降水確率: " + " / ".join(seq))

    # 気温(代表地点)
    if len(short) > 2:
        temps = short[2]
        td = [_dt(t) for t in temps["timeDefines"]]
        for x in temps["areas"][:(3 if detail else 1)]:
            by = {}
            for d, v in zip(td, x.get("temps", [])):
                if v != "":
                    by.setdefault(d.date(), []).append(int(v))
            seq = []
            for day in sorted(by):
                v = by[day]
                lab = _day_label(datetime.combine(day, datetime.min.time()), today)
                seq.append(f"{lab} {min(v)}℃" if len(set(v)) == 1 else f"{lab} {min(v)}〜{max(v)}℃")
            if seq:
                lines.append(f"{x['area']['name']}の気温: " + " / ".join(seq))

    # 週間(短期予報より先の日だけ)
    if detail and len(fc) > 1:
        wk = fc[1]["timeSeries"]
        wd = [_dt(t) for t in wk[0]["timeDefines"]]
        last = days[-1].date() if days else today
        wa = wk[0]["areas"][0]
        tmin = tmax = []
        if len(wk) > 1 and wk[1]["areas"]:
            tmin = wk[1]["areas"][0].get("tempsMin", [])
            tmax = wk[1]["areas"][0].get("tempsMax", [])
        seq = []
        for i, d in enumerate(wd):
            if d.date() <= last:
                continue
            code = (wa.get("weatherCodes") or [""] * 9)[i] or ""
            pop = (wa.get("pops") or [""] * 9)[i] if i < len(wa.get("pops", [])) else ""
            lo = tmin[i] if i < len(tmin) else ""
            hi = tmax[i] if i < len(tmax) else ""
            s = f"{d:%m/%d} {_CODE_WORD.get(code[:1], '?')}"
            if pop != "":
                s += f"(降水{pop}%)"
            if lo != "" or hi != "":
                s += f" {lo or '?'}〜{hi or '?'}℃"
            seq.append(s)
        if seq:
            lines.append("週間予報(目安): " + " / ".join(seq))
    return "\n".join(lines)


def _default_tr(key, **kw):
    return {"srv_wx_title": "気象庁 {name}の天気予報", "srv_wx_label": "気象庁 {places}"}[key].format(**kw)


async def lookup(text: str, tr=None):
    """天気の質問で地域が特定できれば、LLMに渡す資料を返す。できなければ None。

    戻り値: {"label": 画面に出す検索名, "items": [{"title","url","snippet"}]}
    取得に失敗したときも None(呼び出し側がBrave検索へ戻る)。
    """
    tr = tr or _default_tr
    if not is_weather_question(text):
        return None
    try:
        a = await _load_area()
    except WeatherError:
        return None
    places = find_places(text, a)
    if not places:
        return None

    # 取得する(府県予報区, 絞り込み)を最大 MAX_OFFICES 件に
    jobs, labels = [], []
    for label, targets in places[:3]:
        for office, c10 in targets:
            if all(office != j[0] or c10 != j[1] for j in jobs):
                jobs.append((office, c10, len(targets) == 1))
        labels.append(label)
    jobs = [j for j in jobs if j[0] in a["offices"]][:MAX_OFFICES]
    results = await asyncio.gather(*[_forecast(o) for o, _, _ in jobs], return_exceptions=True)
    ovs = await asyncio.gather(*[_overview(o) if single else asyncio.sleep(0, "")
                                 for o, _, single in jobs])
    items = []
    for (office, c10, single), fc, ov in zip(jobs, results, ovs):
        if isinstance(fc, Exception) or not fc:
            continue
        try:
            body = _summarize(fc, detail=single, only_class10=c10)
        except Exception:
            continue
        if ov:
            body += "\n概況: " + ov
        name = a["offices"][office]["name"]
        items.append({"title": tr("srv_wx_title", name=name), "url": PAGE_URL.format(code=office),
                      "snippet": body + "\n(出典: 気象庁ホームページのデータを加工して作成)"})
    if not items:
        return None
    return {"label": tr("srv_wx_label", places="・".join(labels)), "items": items}
