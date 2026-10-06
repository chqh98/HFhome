"""상속 시뮬레이션·가족 공유 테스트. 실행: python tests/test_family.py"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import engine as E
import family as F

# 1) 대출잔액 직접 계산과 비교: 1년 뒤 잔액 = 초기보증료 + 월지급금 12번을 월복리
m, price, r = 100.0, 5.0, (4.0 + 0.95) / 100 / 12
b = 5.0 * 10000 * 0.01
for _ in range(12):
    b = (b + m) * (1 + r)
rows = E.simulate_inheritance(65, price, m)
assert abs(rows[1]["balance"] - round(b / 10000, 2)) < 0.01, (rows[1], b)
assert rows[1]["paid"] == 0.12 and rows[0]["inherit_joined"] == 4.95

# 2) 비소구: 잔액이 집값을 넘으면 자녀에게 남는 금액은 0 (마이너스 아님)
long = E.simulate_inheritance(60, 3.0, 63.2, house_growth=0.0)
over = [x for x in long if x["nonrecourse_used"]]
assert over and all(x["inherit_joined"] == 0 for x in over)
ins = E.sim_insight(long)
print(f"60세·시세 3억·집값 동결: {ins['cross_year']}년 뒤({ins['cross_age']}세)부터 잔액 > 집값 → 비소구")

# 3) 집값 상승률이 높을수록 남는 금액이 커야 함
lo = E.simulate_inheritance(70, 4.0, 134.9, house_growth=0.0)[20]["inherit_joined"]
hi = E.simulate_inheritance(70, 4.0, 134.9, house_growth=3.0)[20]["inherit_joined"]
assert hi > lo, (lo, hi)
print(f"70세·4억 20년 뒤 가입 시 상속: 집값 동결 {lo}억 / 연 3% 상승 {hi}억")

# 4) 공유 링크 복원
ans = {"age_self": 62, "age_spouse": 59, "houses": "1", "price": "le", "market_price": 7.0, "type": "apt"}
code = F.encode_share(ans, {"house_growth": 2.0, "rate": 4.5})
a2, s2 = F.decode_share(code)
assert a2 == ans and s2 == {"house_growth": 2.0, "rate": 4.5}
assert F.decode_share("깨진코드") is None and F.decode_share("abc") is None
print("공유 코드 길이:", len(code))

# 5) 리포트 생성
Q, P = E.load_questions(), E.load_products()
res = E.recommend(P, E.clean_answers(Q, ans))
est = E.estimate_hf_monthly(59, 7.0)
html = F.build_report(ans, res, est, E.simulate_inheritance(59, 7.0, est["amount"]), dict(E.SIM_DEFAULTS), ["Q1 나이 → 62세"])
assert "비소구" in html or "상속" in html
assert "<script" not in html
print("리포트 크기:", len(html), "자")
print("\n모든 가족 기능 테스트 통과")
