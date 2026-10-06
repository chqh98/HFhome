"""예시 인물 4명으로 추천 결과를 확인하는 테스트. 실행: python tests/test_engine.py"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import engine as E

Q, P = E.load_questions(), E.load_products()

PERSONAS = {
    "62세 부부 · 아파트 5억 · 대출 있음": dict(age_self=62, age_spouse=59, houses="1", price="le", market_price=7.0, type="apt", live="yes",
                                     farm="no", basic="no", loan="yes", period="life", lump="no"),
    "51세 조기퇴직 · 공시 9억": dict(age_self=51, age_spouse=50, houses="1", price="le", type="apt", live="yes",
                               job="yes", loan="no", period="term", lump="no"),
    "68세 부부 · 공시 15억 아파트": dict(age_self=68, age_spouse=64, houses="1", price="gt", type="apt", live="yes",
                                  farm="no", own2="yes", loan="no", period="life", lump="yes"),
    "71세 농업인 · 시골 단독주택": dict(age_self=71, age_spouse=None, houses="1", price="le", market_price=1.8, type="house", live="yes",
                                 farm="yes", basic="yes", loan="no", period="life", lump="no"),
}

EXPECT_OK = {
    "62세 부부 · 아파트 5억 · 대출 있음": {"hf_life", "hf_term", "hf_loan", "kb"},
    "51세 조기퇴직 · 공시 9억": set(),
    "68세 부부 · 공시 15억 아파트": {"hana_life", "kb", "hana_bank"},
    "71세 농업인 · 시골 단독주택": {"hf_life", "hf_term", "hf_pref", "kb", "nh"},
}

ok = True
for name, ans in PERSONAS.items():
    ans = E.clean_answers(Q, ans)
    res = E.recommend(P, ans)
    shown = [q["no"] for q in E.visible_questions(Q, ans)]
    print(f"\n■ {name}  (질문 {len(shown)}개: {' '.join(shown)})")
    for st in (E.OK, E.CHECK, E.NO):
        print(f"  {E.STATUS_LABEL[st]}: " + ", ".join(v.product["name"] + (" ★" if v.preferred else "") for v in res[st]))
    got = {v.product["id"] for v in res[E.OK]}
    if got != EXPECT_OK[name]:
        ok = False
        print("  !! 예상과 다름:", EXPECT_OK[name])

# HF 예상 월지급금: 예시표 값을 그대로 재현하는지
T = E.load_payment_table()
for age, row in T["table"].items():
    for price, want in zip(T["prices_eok"], row):
        got = E.estimate_hf_monthly(int(age), price, T)["amount"]
        assert abs(got - want) <= 0.15, (age, price, got, want)
e = E.estimate_hf_monthly(59, 7.0, T)
print(f"\n예상 월지급금 (59세, 시세 7억): {e['amount']}만 원", e["notes"])
# 시세를 입력하면 Q7-1(시세 2.5억 미만?)은 묻지 않고 자동 판단
ans4 = E.clean_answers(Q, PERSONAS["71세 농업인 · 시골 단독주택"])
assert "cheap" not in [q["id"] for q in E.visible_questions(Q, ans4)]

# '잘 모르겠어요'로 남긴 답은 '확인 필요'로 가야 한다
unk = E.clean_answers(Q, dict(age_self=60, age_spouse=None, houses="1", price="?", type="apt", live="yes", farm="no", loan="no"))
hf = E.judge(next(p for p in P if p["id"] == "hf_life"), unk)
assert hf.status == E.CHECK, hf
print("\n'잘 모르겠어요' 처리:", hf.status, hf.reasons)
print("\n모든 테스트 통과" if ok else "\n실패한 테스트 있음")
sys.exit(0 if ok else 1)
