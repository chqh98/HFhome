"""자동 감시 전체 흐름 테스트. 내 컴퓨터에 가짜 상품 페이지 서버를 띄우고, 가짜 AI로 점검한다.
실행: python tests/test_monitor.py"""
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ai_tools as A
import engine as E
import monitor as M

PAGES = {}


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        body = PAGES.get(self.path)
        if body is None:
            self.send_response(404); self.end_headers(); return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8"); self.end_headers()
        self.wfile.write(body.encode("utf-8"))

    def log_message(self, *a):
        pass


srv = HTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_port}"

PAGES["/robots.txt"] = "User-agent: *\nDisallow: /private/\n"
FILLER = "<p>" + "본 상품은 하나생명보험이 대출기관으로서 취급하는 역모기지론입니다. " * 6 + "</p>"


def page(age, review):
    return (f"<html><head><style>.x{{}}</style><script>var a=1;</script></head><body><h1>하나더넥스트 내집연금</h1>{FILLER}"
            f"<table><tr><th>가입 연령</th><td>만 {age}세 이상 (가입자와 배우자 중 연소자 기준)</td></tr>"
            "<tr><th>대출 한도</th><td>최대 15억원</td></tr></table>"
            f"<p>준법감시인 심의필 제{review}호</p><p>접속시각 12:34:56</p></body></html>")


def fake_llm(system, user, want_json=False):
    if want_json:
        age = 60 if "만 60세" in user else 55
        return json.dumps({"product_name": "하나더넥스트 내집연금", "fields": {
            "min_age": {"value": age, "evidence": f"만 {age}세 이상 (가입자와 배우자 중 연소자 기준)"},
            "limit_eok": {"value": 15, "evidence": "최대 15억원"}}}, ensure_ascii=False)
    return "하나생명 내집연금의 가입 최소 연령이 55세에서 60세로 높아졌습니다. Q1 나이 질문과 나이 판정 규칙에 영향이 있습니다."


P = E.load_products()
src = {"id": "t1", "product": "하나더넥스트 내집연금(역모기지론)", "product_id": "hana_life", "url": BASE + "/hl",
       "mode": "auto", "priority": "중요"}

# 1) 첫 점검: DB(55세)와 같음 → 기준만 저장
PAGES["/hl"] = page(55, "하생 2025-1055")
r1 = M.check_source(src, P, fake_llm)
print("1 첫 점검:", r1["status"], r1["message"]); assert r1["status"] == "baseline"

# 2) 접속 시각만 바뀐 경우 → 지문 같음, AI 호출 없음
PAGES["/hl"] = page(55, "하생 2025-1055").replace("12:34:56", "09:00:01")
calls = []
r2 = M.check_source(src, P, lambda *a, **k: calls.append(1) or fake_llm(*a, **k), snapshot=r1["snapshot"])
print("2 사소한 변화:", r2["status"], "| AI 호출", len(calls)); assert r2["status"] == "unchanged" and not calls

# 3) 연령 55→60, 심의필 번호 변경 → 알림
PAGES["/hl"] = page(60, "하생 2026-0412")
r3 = M.check_source(src, P, fake_llm, snapshot=r1["snapshot"])
a = r3["alert"]
print("3 조건 변경:", r3["status"], a["level"], a["signals"], [(x["항목"], x["현재 DB"], x["AI 추출"]) for x in a["rows"]])
print("   요약:", a["summary"])
assert r3["status"] == "alert" and a["rows"][0]["key"] == "min_age" and a["level"] == "중요"

# 4) 승인 → DB 반영 → 58세 부부 판정 변화
P2, log = A.apply_change(P, a["product_id"], "min_age", a["rows"][0]["_new"], "관리자")
ans = dict(age_self=58, age_spouse=58, houses="1", price="gt", type="apt", live="yes", own2="yes")
print("4 승인 후 58세 부부:", E.judge(next(p for p in P if p["id"] == "hana_life"), ans).status, "→",
      E.judge(next(p for p in P2 if p["id"] == "hana_life"), ans).status)

# 5) 판매 종료 문구 / 6) 페이지 삭제(404)
PAGES["/hl"] = page(55, "하생 2025-1055").replace("<h1>", "<p>본 상품은 2026년 11월부로 신규 판매 종료 예정입니다.</p><h1>")
r5 = M.check_source(src, P, fake_llm, snapshot=r1["snapshot"])
print("5 판매종료 문구:", r5["status"], r5["alert"]["signals"]); assert r5["alert"]["level"] == "중요"
del PAGES["/hl"]
r6 = M.check_source(src, P, fake_llm, snapshot=r1["snapshot"])
print("6 페이지 삭제:", r6["status"], [(x["항목"], x["AI 추출"]) for x in r6["alert"]["rows"]])
assert r6["alert"]["rows"][0]["_new"] == "판매 종료"

# 7) robots.txt 차단 / 8) 스크립트로만 그리는 빈 페이지 / 9) 수동 대상
r7 = M.check_source({**src, "url": BASE + "/private/x"}, P, fake_llm)
print("7 robots 차단:", r7["status"], r7["message"]); assert r7["status"] == "skipped"
PAGES["/js"] = "<html><body><div id='app'></div><script>render()</script></body></html>"
r8 = M.check_source({**src, "url": BASE + "/js"}, P, fake_llm)
print("8 빈 페이지:", r8["status"], r8["message"]); assert r8["status"] == "error"
r9 = M.check_source({**src, "mode": "manual"}, P, fake_llm)
print("9 수동 대상:", r9["status"]); assert r9["status"] == "skipped"

# 10) 보고서·감시 대상 목록
print("\n감시 대상:", [(s["id"], s["mode"], s["priority"]) for s in M.load_sources()])
md = M.report_markdown([r3, r7])
assert "승인" in md and "가입 최소 연령" in md
srv.shutdown()
print("\n모든 자동 감시 테스트 통과")
