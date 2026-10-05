"""AI 기능 테스트. 실제 AI 대신 정해진 답을 돌려주는 가짜 AI로 검증한다. 실행: python tests/test_ai_tools.py"""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ai_tools as A
import engine as E

P = E.load_products()
doc = (Path(__file__).resolve().parent.parent / "data/samples/hana_life_demo.txt").read_text(encoding="utf-8")

def fake_extract(system, user, want_json=False):
    return "```json\n" + json.dumps({
        "product_name": "하나더넥스트 내집연금",
        "fields": {
            "min_age": {"value": "60", "evidence": "가입 연령: 만 60세 이상 (가입자와 배우자 중 연소자 기준)"},
            "age_basis": {"value": "부부 중 연소자", "evidence": "가입자와 배우자 중 연소자 기준"},
            "price_min_eok": {"value": 12, "evidence": "공시가격 12억원 초과 주택"},
            "house_types": {"value": ["아파트", "빌라"], "evidence": "KB인터넷시세 확인이 가능한 주택"},
            "residence": {"value": "필수", "evidence": "담보주택에 실제 거주하여야 합니다"},
            "period_type": {"value": "종신", "evidence": "지급 방식: 종신 지급"},
            "limit_eok": {"value": 15, "evidence": "대출 한도: 최대 15억원"},
            "rate": {"value": "10년 만기 국고채 직전월 평균금리 + 1.3% 고정", "evidence": "적용 금리: 10년 만기 국고채"},
            "sale_status": {"value": "판매 중", "evidence": "지어낸 문장입니다 판매중"},
        }, "notes": ""}, ensure_ascii=False) + "\n```"

ex = A.extract(doc, fake_extract)
rows = A.compare(next(p for p in P if p["id"] == "hana_life")["profile"], ex)
for r in rows:
    print(f"{r['항목']:<14} {r['현재 DB']:<20} → {r['AI 추출']:<20} [{r['상태']}] {r['주의']}")
st = {r["key"]: r["상태"] for r in rows}
assert st["min_age"] == "변경" and st["limit_eok"] == "같음" and st["price_max_eok"] == "문서에 없음"
assert "허용되지 않은" in ex["fields"]["house_types"]["warning"]          # '빌라'는 허용값 아님
assert "원문에서 확인되지 않음" in ex["fields"]["sale_status"]["warning"]  # 지어낸 근거 감지

# 승인 → Rule 반영: 58세/58세 부부는 55세 기준이면 가능, 60세 기준이면 불가
P2, log = A.apply_change(P, "hana_life", "min_age", 60, "홍길동")
print("\n감사 기록:", log)
ans = dict(age_self=58, age_spouse=58, houses="1", price="gt", type="apt", live="yes", own2="yes", loan="no", farm="no")
before = E.judge(next(p for p in P if p["id"] == "hana_life"), ans).status
after = E.judge(next(p for p in P2 if p["id"] == "hana_life"), ans).status
print("58세 부부 판정:", before, "→", after)
assert before == E.OK and after == E.NO

# 판매 종료 승인 → '확인 필요'가 아니라 결과에서 '가입 가능'으로 안 나와야 함
P3, log2 = A.apply_change(P, "kb", "sale_status", "판매 종료", "홍길동")
v = E.judge(next(p for p in P3 if p["id"] == "kb"), dict(age_self=62, age_spouse=None, houses="1", price="le", type="apt", live="yes"))
print("KB 판매 종료 후:", v.status, v.reasons[-1]); assert v.status == E.NO
json.loads(A.export_products_json(P2))  # 내보내기 JSON이 깨지지 않는지

# 용어 도우미
G = A.load_glossary()
print("\n[용어집 검색]", A.explain("종신혼합방식이 뭐예요?", G, P, None)["text"][:60])
pushy = lambda s, u, want_json=False: "종신방식이 좋아요. 이 상품 가입하세요.\n근거: 종신방식"
r = A.explain("뭐가 좋아요?", G, P, pushy); print("[권유 감지]", r["note"]); assert A.SAFETY_NOTE in r["text"]
def broken(*a, **k): raise RuntimeError("timeout")
r = A.explain("공시가격이 뭐예요", G, P, broken); print("[AI 실패 대체]", r["source"], r["note"]); assert r["source"] == "glossary"
assert "자료" in A.build_context(G, P, "가입 가능: KB")
print("\n모든 AI 기능 테스트 통과")
