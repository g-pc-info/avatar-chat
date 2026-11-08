"""Smoke test: copies the project to a temp dir, runs the app against a mock LLM, checks the API.
Usage: python3 misc/smoke_test.py   (needs fastapi/uvicorn/httpx/pillow installed)
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path

import httpx
from PIL import Image

SRC = Path(__file__).resolve().parent.parent
import socket


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


MOCK_PORT, APP_PORT = free_port(), free_port()
system_prompts = []
fp_values = []
extract_prompts = []
main_counts = []
planner_prompts = []
brave_calls = []
jma_calls = []


def jma_forecast(office_name):
    from datetime import datetime, timedelta
    d0 = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    iso = lambda d, h=0: (d + timedelta(days=0, hours=h)).strftime("%Y-%m-%dT%H:%M:%S+09:00")
    days = [d0 + timedelta(days=i) for i in range(3)]
    wk = [d0 + timedelta(days=i) for i in range(1, 8)]
    return [
        {"publishingOffice": "テスト気象台", "reportDatetime": iso(d0, 11), "timeSeries": [
            {"timeDefines": [iso(d) for d in days], "areas": [
                {"area": {"name": office_name + "地方", "code": "X1"}, "weatherCodes": ["100", "200", "300"],
                 "weathers": ["晴れ", "くもり", "雨"]}]},
            {"timeDefines": [iso(d0, 12), iso(d0, 18)], "areas": [
                {"area": {"name": office_name + "地方", "code": "X1"}, "pops": ["0", "30"]}]},
            {"timeDefines": [iso(d0, 9), iso(d0, 0)], "areas": [
                {"area": {"name": office_name, "code": "P1"}, "temps": ["11", "17"]}]}]},
        {"timeSeries": [
            {"timeDefines": [iso(d) for d in wk], "areas": [
                {"area": {"name": office_name, "code": "A"}, "weatherCodes": ["100"] * 7, "pops": ["10"] * 7}]},
            {"timeDefines": [iso(d) for d in wk], "areas": [
                {"area": {"name": office_name, "code": "P1"}, "tempsMin": ["8"] * 7, "tempsMax": ["20"] * 7}]}]}]


JMA_AREA = {
    "centers": {}, "class15s": {"130011": {"name": "東京地方", "parent": "130010"}},
    "offices": {"130000": {"name": "東京都"}, "400000": {"name": "福岡県", "enName": "Fukuoka Prefecture"}, "410000": {"name": "佐賀県"}},
    "class10s": {"130010": {"name": "東京地方", "parent": "130000"}},
    "class20s": {"1310100": {"name": "千代田区", "parent": "130011"}},
}


class Mock(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, obj):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path.startswith("/jma/"):
            jma_calls.append(self.path)
            if self.path.endswith("/area.json"):
                return self._send(JMA_AREA)
            m = re.search(r"/(overview_forecast|forecast)/(\d+)\.json$", self.path)
            names = {"130000": "東京", "400000": "福岡"}
            if m and m.group(2) in names:
                if m.group(1) == "forecast":
                    return self._send(jma_forecast(names[m.group(2)]))
                return self._send({"text": f"{names[m.group(2)]}は、高気圧に覆われて晴れています。"})
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self.path.startswith("/res/v1/web/search"):
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            token = self.headers.get("X-Subscription-Token", "")
            brave_calls.append({"token": token, "q": q.get("q", [""])[0], "country": q.get("country", [""])[0]})
            if token == "bad":
                self.send_response(401)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if q.get("q", [""])[0] == "ゴミ":  # 中身のない抜粋だけが返るケース(天気ポータルなど)
                self._send({"web": {"results": [
                    {"title": "ポータルA", "url": "https://example.com/a", "description": "{{ticker_title}} {{item}}"},
                    {"title": "ポータルB", "url": "https://example.com/b", "description": "{{x}}"}]}})
                return
            self._send({"web": {"results": [
                {"title": "東京の天気 <b>晴れ</b>", "url": "https://example.com/tenki",
                 "description": "今日は<strong>晴れ</strong>です &amp; 暖かい。最高気温は18度、風はやや強く、"
                                "夜は冷え込みます。明日は雨の予報です。"},
                {"title": "bad", "url": "javascript:alert(1)", "description": "x"},
                {"title": "二件目", "url": "https://example.org/2", "description": "snippet2"},
                {"title": "テンプレ", "url": "https://example.net/3", "description": "{{ticker_title}} {{item}}"}]}})
            return
        self._send({"data": [{"id": "mock-model"}]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        msgs = body["messages"]
        if "検索判断" in msgs[0]["content"]:
            content = msgs[0]["content"]
            planner_prompts.append(content)
            forced = "今回は必ず search を true" in content
            latest = content.split("# ユーザーの最新の発言\n")[-1]
            hit = "天気" in latest
            junk = "ゴミ検索" in latest
            out = json.dumps({"search": forced or hit or junk,
                              "query": "東京 天気" if hit else ("ゴミ" if junk else ("テスト" if forced else ""))},
                             ensure_ascii=False)
        elif "覚えておく価値" in msgs[0]["content"]:
            content = msgs[0]["content"]
            extract_prompts.append(content)
            convo_part = content.split("# 会話\n")[-1]
            if "五郎" in convo_part:
                out = json.dumps([{"text": "ユーザーの名前は五郎です", "importance": 5}], ensure_ascii=False)
            elif "三郎" in convo_part:
                ids = [int(x) for x in re.findall(r"\[(\d+)\] ユーザーの名前は次郎です", content)]
                out = json.dumps([{"text": "ユーザーの名前は三郎です", "importance": 5, "replaces": ids}],
                                 ensure_ascii=False)
            elif "次郎" in convo_part:  # 名前の言い直し: 古い記憶を置き換える
                ids = [int(x) for x in re.findall(r"\[(\d+)\] ユーザーの名前は太郎です", content)]
                out = json.dumps([{"text": "ユーザーの名前は次郎です", "importance": 5, "replaces": ids}],
                                 ensure_ascii=False)
            elif "太郎" in convo_part:
                out = '<think>x</think>```json\n[{"text":"ユーザーの名前は太郎です","importance":5}]\n```'
            else:
                out = "[]"
        else:
            system_prompts.append(msgs[0]["content"])
            main_counts.append(len(msgs))
            n = len(system_prompts)
            out = json.dumps({"emotion": ["happy", "nonexistent", "sad"][n % 3], "text": f"返答{n}もち"},
                             ensure_ascii=False)
            if n == 4:
                out = "[surprised] タグ形式の返答もち"
            fp_values.append(body.get("frequency_penalty"))
            loop_text = json.dumps({"emotion": "sad", "text": "天気は...。えっと...。" * 8}, ensure_ascii=False)
            if "ずっとくりかえして" in msgs[-1]["content"]:
                out = loop_text
            elif "くりかえして" in msgs[-1]["content"]:
                out = (json.dumps({"emotion": "happy", "text": "ふつうの返答もち"}, ensure_ascii=False)
                       if "繰り返しになりました" in msgs[0]["content"] else loop_text)
            if "二つ返して" in msgs[-1]["content"]:
                out = (json.dumps({"emotion": "happy", "text": "一つ目"}, ensure_ascii=False) + "\n\n"
                       + json.dumps({"emotion": "embarrassed", "text": "二つ目"}, ensure_ascii=False))
        self._send({"choices": [{"message": {"content": out}}]})


def check(cond, msg):
    print(("OK   " if cond else "FAIL ") + msg)
    if not cond:
        check.failed = True


check.failed = False


def main():
    tmp = Path(tempfile.mkdtemp(prefix="avatar-smoke-"))
    proj = tmp / "p"
    shutil.copytree(SRC, proj, ignore=shutil.ignore_patterns("system", "user-data", "__pycache__", "downloads"))
    (proj / "user-data").mkdir()
    (proj / "user-data" / "config.json").write_text(json.dumps({
        "base_url": f"http://127.0.0.1:{MOCK_PORT}/v1", "model": "mock-model",
        "memory_every_turns": 2, "port": APP_PORT}), encoding="utf-8")
    srv = ThreadingHTTPServer(("127.0.0.1", MOCK_PORT), Mock)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    env = dict(os.environ, AVATAR_NO_BROWSER="1", PYTHONDONTWRITEBYTECODE="1",
               AVATAR_BRAVE_URL=f"http://127.0.0.1:{MOCK_PORT}/res/v1/web/search",
               AVATAR_JMA_URL=f"http://127.0.0.1:{MOCK_PORT}/jma")
    app = subprocess.Popen([sys.executable, str(proj / "app" / "main.py")], env=env,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    base = f"http://127.0.0.1:{APP_PORT}"
    try:
        c = httpx.Client(base_url=base, timeout=30)
        for _ in range(50):
            try:
                c.get("/")
                break
            except Exception:
                time.sleep(0.2)
        check(c.get("/").status_code == 200, "GET / serves index.html")
        all_chars = c.get("/api/characters").json()
        check({x["id"] for x in all_chars} == {"builtin_mochi", "builtin_honoka", "builtin_rei"}
              and all(len(x["emotions"]) == 8 and x["motion"] in ("squash", "soft") for x in all_chars),
              "3 builtin characters, each with 8 emotions")
        for x in all_chars:
            if x["id"] != "builtin_mochi":
                im = c.get(x["emotions"]["neutral"]["url"])
                check(im.status_code == 200 and "webp" in im.headers["content-type"], f"{x['id']}: neutral image served")
        check(all_chars[0]["id"] == "builtin_mochi", "builtin_mochi is listed first (default character)")
        chars = [x for x in all_chars if x["id"] == "builtin_mochi"]
        check(chars[0]["motion"] == "squash", "builtin motion is squash")
        cid = chars[0]["id"]
        img = c.get(chars[0]["emotions"]["happy"]["url"])
        check(img.status_code == 200 and "svg" in img.headers["content-type"], "emotion svg is served")
        check(c.get("/chars/builtin/builtin_mochi/..%2f..%2fapp/main.py").status_code == 404, "path traversal blocked")
        cfg = c.get("/api/config").json()
        check("api_key" not in cfg and cfg["has_api_key"] is False, "api_key not exposed")
        check(c.get("/api/models").json()["models"] == ["mock-model"], "model list")

        r1 = c.post("/api/chat", json={"character_id": cid, "text": "こんにちは"}).json()
        check(r1["emotion"] == "neutral" and r1["text"].startswith("返答"),
              "unknown emotion falls back to neutral")
        r2 = c.post("/api/chat", json={"character_id": cid, "text": "私の名前は太郎です"}).json()
        check(r2["emotion"] == "sad", "valid emotion is passed through")
        time.sleep(2.0)
        mems = c.get(f"/api/memories/{cid}").json()
        check(len(mems) == 1 and "太郎" in mems[0]["text"] and mems[0]["strength"] > 0.9, "memory extracted (think/fence stripped)")
        r3 = c.post("/api/chat", json={"character_id": cid, "text": "太郎です、よろしく"}).json()
        check(r3["recalled"] and "覚えていること" in system_prompts[-1] and "太郎" in system_prompts[-1],
              "memory recalled via FTS5 and injected into prompt")
        check("今回の発言を優先" in system_prompts[-1], "prompt tells the model to prefer what the user says now")
        r4 = c.post("/api/chat", json={"character_id": cid, "text": "ほんとに?"}).json()
        check(r4["emotion"] == "surprised" and "タグ形式" in r4["text"], "[tag] reply format parsed")
        mems = c.get(f"/api/memories/{cid}").json()
        check(mems[0]["access_count"] >= 1, "access_count increments on recall")
        hist = c.get(f"/api/history/{cid}").json()
        check(len(hist) == 8, "history stored (8 messages)")
        r2j = c.post("/api/chat", json={"character_id": cid, "text": "二つ返して", "web": "off"}).json()
        check("一つ目" in r2j["text"] and "二つ目" in r2j["text"] and "{" not in r2j["text"]
              and r2j["emotion"] == "embarrassed", "two JSON objects in one reply are merged")

        n0 = len(main_counts)
        r = c.post("/api/chat", json={"character_id": cid, "text": "くりかえして", "web": "off"}).json()
        check(r["text"] == "ふつうの返答もち" and len(main_counts) == n0 + 2 and fp_values[-1] == 0.6,
              "looping reply is retried once with a repetition penalty")
        n0 = len(main_counts)
        r = c.post("/api/chat", json={"character_id": cid, "text": "ずっとくりかえして", "web": "off"}).json()
        sents = [s for s in re.split(r"[。！？\n]+", r["text"]) if s]
        check(len(main_counts) == n0 + 2 and sents and len(sents) == len(set(sents)) and len(r["text"]) < 60,
              f"still looping after retry: duplicates removed ({r['text']!r})")

        # ---- web search (Brave) ----
        def chat(text, web):
            return c.post("/api/chat", json={"character_id": cid, "text": text, "web": web}).json()

        cfg0 = c.get("/api/config").json()
        check(cfg0["has_brave_key"] is False and "brave_api_key" not in cfg0, "no brave key by default")
        r = chat("天気を教えて", "auto")
        check(r["searched"] is None and not brave_calls, "no search without a brave key")
        r = chat("天気を教えて", "always")
        check(r["searched"] is None and "APIキー" in r["web_note"], "'always' without key explains why")
        long_hist = main_counts[-1]
        c.post("/api/config", json={"brave_api_key": "good-key"})
        cfg1 = c.get("/api/config").json()
        check(cfg1["has_brave_key"] is True and "brave_api_key" not in cfg1, "brave key stored but not exposed")
        r = chat("天気を教えて", "auto")
        check(r["searched"] == "東京 天気" and len(r["sources"]) == 3
              and all(s["url"].startswith("https://") for s in r["sources"]),
              "auto: planner decides to search; non-http URLs dropped")
        check(r["web_note"] == "" and "【注意】" not in system_prompts[-1]
              and "{{" not in system_prompts[-1] and "(抜粋なし)" in system_prompts[-1],
              "useful snippets: no warning; template junk is blanked")
        check(brave_calls[-1]["token"] == "good-key" and brave_calls[-1]["q"] == "東京 天気"
              and brave_calls[-1]["country"] == "JP", "brave called with key header, query and country")
        check(long_hist > 6 and main_counts[-1] <= 6,
              f"search turn trims history ({long_hist} -> {main_counts[-1]} messages)")
        sp = system_prompts[-1]
        check("以前の会話の返答から流用しない" in sp.replace("\n", ""), "prompt forbids reusing numbers from earlier replies")
        check("ネット検索の結果" in sp and "今日は晴れです & 暖かい" in sp and "<b>" not in sp
              and "<strong>" not in sp, "results injected into prompt (HTML stripped)")
        import re as _re
        check(_re.search(r"\d{4}-\d{2}-\d{2}\([月火水木金土日]\) \d{2}:\d{2}", sp) and "時刻を知っています" in sp,
              "prompt has date+weekday+time and says the character knows it")
        check("現在の日付・時刻" in planner_prompts[-1], "planner is told not to search for date/time")
        n = len(brave_calls)
        r = chat("こんにちは", "auto")
        check(r["searched"] is None and len(brave_calls) == n, "auto: chit-chat does not search")
        r = chat("天気を教えて", "off")
        check(r["searched"] is None and len(brave_calls) == n, "off: never searches")
        r = chat("こんにちは", "always")
        check(r["searched"] == "テスト" and len(brave_calls) == n + 1, "always: searches every time")
        # ---- 気象庁(天気の質問で地域が分かるとき) ----
        n_brave = len(brave_calls)
        r = chat("福岡の天気を教えて", "auto")
        check(r["searched"] == "気象庁 福岡" and len(brave_calls) == n_brave
              and r["sources"][0]["url"].startswith("https://www.jma.go.jp/")
              and "晴れ" in system_prompts[-1] and "福岡は、高気圧" in system_prompts[-1]
              and "気象庁ホームページ" in system_prompts[-1] and "【注意】" not in system_prompts[-1],
              "weather question with a place: uses JMA data, no Brave call")
        r = chat("九州の天気は?", "auto")
        check(len(r["sources"]) == 1 and r["searched"] == "気象庁 九州",
              "region name: offices missing from the data are skipped")
        r = chat("千代田区の天気", "always")
        check(r["searched"] == "気象庁 千代田区" and "東京地方の天気" in system_prompts[-1],
              "municipality resolves to its forecast area")
        r = chat("福岡の天気を教えて", "off")
        check(r["searched"] is None and not r["sources"], "off: JMA is not used either")
        r = chat("札幌の天気を教えて", "auto")
        check(r["searched"] == "東京 天気" and len(brave_calls) == n_brave + 1,
              "unknown place in the (mock) data: falls back to Brave")
        r = chat("ゴミ検索して", "auto")
        check(r["searched"] == "ゴミ" and "確認" in r["web_note"] and "【注意】" in system_prompts[-1]
              and "{{" not in system_prompts[-1], "junk-only results: model told to answer briefly + UI note")
        c.post("/api/config", json={"brave_api_key": "bad"})
        r = chat("天気を教えて", "auto")
        check(r["text"].startswith("返答") and "無効" in r["web_note"] and r["searched"] is None,
              "bad key: reply still works, error shown")
        c.post("/api/config", json={"brave_api_key": "__clear__"})
        check(c.get("/api/config").json()["has_brave_key"] is False, "brave key can be cleared")

        # ---- memory: name correction replaces the old memory ----
        # 抽出は「ユーザー発言数が memory_every_turns の倍数」のときに動く。偶数に揃えてから始める
        n_user = sum(1 for m in c.get(f"/api/history/{cid}").json() if m["role"] == "user")
        if n_user % 2:
            c.post("/api/chat", json={"character_id": cid, "text": "調整用の一言", "web": "off"})
            time.sleep(1.0)
        c.post("/api/chat", json={"character_id": cid, "text": "私の名前は次郎です", "web": "off"})
        c.post("/api/chat", json={"character_id": cid, "text": "よろしくね", "web": "off"})
        time.sleep(2.5)
        texts = [m["text"] for m in c.get(f"/api/memories/{cid}").json()]
        check(any("次郎" in t for t in texts) and not any("太郎" in t for t in texts),
              f"name correction replaces the old memory ({texts})")
        # 抽出がまだ動いていない発言(しきい値未満)は、会話を消す前に記憶へ整理される
        c.post("/api/chat", json={"character_id": cid, "text": "私の名前は三郎です", "web": "off"})
        n_ext = len(extract_prompts)
        time.sleep(0.5)
        check(len(extract_prompts) == n_ext and not any("三郎" in m["text"] for m in c.get(f"/api/memories/{cid}").json()),
              "1 message is below the threshold: not extracted yet")
        check(c.delete(f"/api/history/{cid}").status_code == 200, "clear history (forces extraction first)")
        texts = [m["text"] for m in c.get(f"/api/memories/{cid}").json()]
        check(any("三郎" in t for t in texts) and not any("次郎" in t for t in texts),
              f"pending statements are remembered before clearing ({texts})")
        check(c.get(f"/api/history/{cid}").json() == [], "history is empty after clearing")
        # タブを閉じるとき(pagehide)に呼ばれる: しきい値未満の発言も整理に回す
        c.post("/api/chat", json={"character_id": cid, "text": "私の誕生日は四月です", "web": "off"})
        n_ext = len(extract_prompts)
        time.sleep(0.5)
        check(len(extract_prompts) == n_ext, "1 message below the threshold: nothing extracted yet")
        check(c.post(f"/api/flush/{cid}").status_code == 200, "flush endpoint answers immediately")
        time.sleep(1.5)
        check(len(extract_prompts) == n_ext + 1 and "四月" in extract_prompts[-1],
              "flush (tab closing) extracts the pending statements")
        check(c.post("/api/flush/nonexistent").status_code == 200, "flush for an unknown character is harmless")
        ep = extract_prompts[-1]
        check("ユーザー自身の発言だけ" in ep and "現在の日付・時刻" in ep and "# 既存の記憶" in ep,
              "extraction prompt: user-only source, no transient facts, existing memories listed")

        def png(color):
            b = BytesIO()
            Image.new("RGB", (1600, 1200), color).save(b, "PNG")
            return b.getvalue()

        files = {"img_neutral": ("a.png", png("red"), "image/png"), "img_happy": ("b.png", png("blue"), "image/png")}
        resp = c.post("/api/characters", data={"name": "テスト子", "persona": "p", "motion": "soft"}, files=files)
        check(resp.status_code == 200, "user character created")
        uid = resp.json()["id"]
        u = [x for x in c.get("/api/characters").json() if x["id"] == uid][0]
        w = Image.open(BytesIO(c.get(u["emotions"]["neutral"]["url"]).content))
        check(set(u["emotions"]) == {"neutral", "happy"} and max(w.size) == 768 and w.format == "WEBP",
              f"images re-encoded to WebP {w.size}")
        check(u["motion"] == "soft", "user character keeps motion=soft")
        r_bad = c.post("/api/characters", data={"name": "y", "motion": "evil"}, files={"img_neutral": ("a.png", png("red"), "image/png")})
        bad = [x for x in c.get("/api/characters").json() if x["id"] == r_bad.json()["id"]][0]
        check(bad["motion"] == "squash", "invalid motion falls back to squash")
        c.delete(f"/api/characters/{r_bad.json()['id']}")
        check(c.post("/api/characters", data={"name": "x"}, files={"img_happy": ("b.png", png("blue"), "image/png")}).status_code == 400,
              "neutral is required")
        check(c.post("/api/characters", data={"name": "x"}, files={"img_neutral": ("b.png", b"notanimage", "image/png")}).status_code == 400,
              "invalid image rejected")
        check(c.post(f"/api/characters/{uid}/image/sad", files={"file": ("s.png", png("green"), "image/png")}).status_code == 200,
              "single emotion image added")
        check(c.delete(f"/api/characters/{uid}").status_code == 200, "user character deleted")
        check(c.delete(f"/api/characters/{cid}").status_code == 404, "builtin character cannot be deleted")
        c.delete(f"/api/history/{cid}")
        check(c.get(f"/api/history/{cid}").json() == [], "history cleared")

        # ---- キャラごとにDBが分かれている(履歴・記憶・忘却の基準が混ざらない) ----
        c.post("/api/chat", json={"character_id": "builtin_honoka", "text": "私は犬が好きです", "web": "off"})
        c.post("/api/chat", json={"character_id": "builtin_honoka", "text": "私の名前は五郎です", "web": "off"})
        time.sleep(2.0)
        hh = c.get("/api/history/builtin_honoka").json()
        hm = c.get(f"/api/history/{cid}").json()
        check(len(hh) == 4 and not any("犬" in m["text"] for m in hm), "history is separate per character")
        mh = [m["text"] for m in c.get("/api/memories/builtin_honoka").json()]
        mm = [m["text"] for m in c.get(f"/api/memories/{cid}").json()]
        check(any("五郎" in t for t in mh) and not any("五郎" in t for t in mm),
              f"memories are separate per character ({mh} / {mm})")
        c.post("/api/chat", json={"character_id": cid, "text": "もちへの一言", "web": "off"})
        c.delete("/api/history/builtin_honoka")
        check(c.get("/api/history/builtin_honoka").json() == []
              and [m["text"] for m in c.get(f"/api/history/{cid}").json() if m["role"] == "user"] == ["もちへの一言"],
              "clearing one character's history leaves the other's untouched")
        c.delete(f"/api/history/{cid}")

        # ---- 多言語化 ----
        import re as _re
        i18n = c.get("/api/i18n").json()
        check(set(i18n) == {"ja", "en", "zh", "es", "pt"}, "i18n: 5 languages")
        ph = lambda s: sorted(_re.findall(r"\{(\w+)\}", s))
        bad = [(lg, k) for lg in i18n for k in i18n["ja"] if k not in i18n[lg]]
        bad += [(lg, k) for lg in i18n for k in i18n[lg] if k not in i18n["ja"]]
        check(not bad, f"i18n: identical key sets {bad[:5]}")
        bad = [(lg, k) for lg in i18n for k in i18n["ja"]
               if k in i18n[lg] and ph(i18n[lg][k]) != ph(i18n["ja"][k])]
        check(not bad, f"i18n: identical placeholders {bad[:5]}")
        check(not [(lg, k) for lg in i18n for k, v in i18n[lg].items() if not v.strip()], "i18n: no empty strings")
        html = (proj / "app" / "static" / "index.html").read_text(encoding="utf-8")
        used = set(_re.findall(r'data-i18n(?:-ph|-title)?="(\w+)"', html)) | set(_re.findall(r'\bt\("(\w+)"', html))
        used = {k for k in used if not k.endswith("_")}
        used |= {f"emo_{e}" for e in ["neutral", "happy", "sad", "angry", "surprised", "embarrassed", "thinking", "sleepy"]}
        check(not [k for k in used if k not in i18n["ja"]], f"i18n: keys used by index.html exist {[k for k in used if k not in i18n['ja']]}")
        srcs = "".join((proj / "app" / f).read_text(encoding="utf-8") for f in ("main.py", "search.py", "weather.py"))
        usedsrv = set(_re.findall(r'"(srv_\w+)"', srcs))
        check(not [k for k in usedsrv if k not in i18n["ja"]], f"i18n: srv keys used by server exist {[k for k in usedsrv if k not in i18n['ja']]}")
        c.post("/api/config", json={"ui_lang": "en"})
        en = {x["id"]: x for x in c.get("/api/characters").json()}
        check(en["builtin_honoka"]["name"] == "Honoka" and en["builtin_honoka"]["greeting"] != "", "en: builtin character is translated")
        c.post("/api/chat", json={"character_id": cid, "text": "hello", "web": "off"})
        check("English" in system_prompts[-1], "en: system prompt tells the model to reply in English")
        for lg, word in (("zh", "简体中文"), ("es", "español"), ("pt", "português")):
            c.post("/api/config", json={"ui_lang": lg})
            c.post("/api/chat", json={"character_id": cid, "text": "hello", "web": "off"})
            check(word in system_prompts[-1], f"{lg}: system prompt language directive")
        c.post("/api/config", json={"ui_lang": "en"})
        r = c.post("/api/chat", json={"character_id": cid, "text": "weather in Fukuoka", "web": "auto"}).json()
        check("JMA" in str(r.get("web_note", "")) or "gion" in str(r.get("sources", "")) or "福岡" in str(r.get("sources", "")),
              f"en: English weather question is answered from JMA ({r.get('searched')})")
        c.post("/api/config", json={"ui_lang": "ja"})
        ja = {x["id"]: x for x in c.get("/api/characters").json()}
        check(ja["builtin_honoka"]["name"] == "ほのか", "ja: switching back restores Japanese names")
        c.post("/api/config", json={"ui_lang": "xx"})
        check(c.get("/api/config").json()["ui_lang"] == "ja", "invalid ui_lang is ignored")
        c.delete(f"/api/history/{cid}")  # この後の再起動テストのため、発言数の偶奇をそろえる

        # ---- 起動時の取りこぼし回収: 未整理の発言を残したまま落とし、再起動して整理されるか ----
        c.post("/api/chat", json={"character_id": cid, "text": "私の趣味は釣りです", "web": "off"})
        time.sleep(0.5)
        n_ext = len(extract_prompts)
        app.kill()
        app.wait()
        app = subprocess.Popen([sys.executable, str(proj / "app" / "main.py")], env=env,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for _ in range(50):
            try:
                c.get("/")
                break
            except Exception:
                time.sleep(0.2)
        time.sleep(4)
        check(len(extract_prompts) == n_ext + 1 and "釣り" in extract_prompts[-1],
              "restart: pending statements are extracted at startup")
    finally:
        app.terminate()
        try:
            out = app.communicate(timeout=5)[0]
        except Exception:
            out = ""
        srv.shutdown()
        shutil.rmtree(tmp, ignore_errors=True)
    if "Traceback" in out:
        print("--- server log ---\n" + out[-2000:])
        check.failed = True
    print("\nRESULT:", "FAILED" if check.failed else "ALL PASSED")
    sys.exit(1 if check.failed else 0)


if __name__ == "__main__":
    main()
