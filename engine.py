"""주택연금 추천 Rule 엔진.

상품 조건(data/products.json)과 질문(data/questions.json)을 읽어
답변에 따라 다음 질문과 상품별 판정(가입 가능 / 확인 필요 / 해당 없음)을 계산한다.
화면(app.py)과 분리돼 있어서 이 파일만 따로 테스트할 수 있다.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

DATA = Path(__file__).parent / "data"
UNKNOWN = "?"

OK, CHECK, NO = "ok", "check", "no"
STATUS_LABEL = {OK: "가입할 수 있어요", CHECK: "확인이 필요해요", NO: "해당되지 않아요"}


def load_questions() -> list[dict]:
    return json.loads((DATA / "questions.json").read_text(encoding="utf-8"))["questions"]


def load_products() -> list[dict]:
    raw = json.loads((DATA / "products.json").read_text(encoding="utf-8"))
    groups = raw.get("groups", {})
    products = []
    for p in raw["products"]:
        reqs = p["requires"] if isinstance(p["requires"], list) else [p["requires"]]
        expanded = []
        for r in reqs:
            if isinstance(r, str) and r.startswith("@"):
                expanded.extend(groups[r[1:]])
            else:
                expanded.append(r)
        products.append({**p, "requires": expanded})
    return products


# ---------- 답변 → 판단용 값 ----------

def derive(answers: dict) -> dict:
    """원래 답변에 나이 파생값(age_older, age_younger)을 더한다."""
    v = dict(answers)
    a, b = answers.get("age_self"), answers.get("age_spouse")
    if a is not None:
        ages = [a] + ([b] if b is not None else [])
        v["age_older"], v["age_younger"] = max(ages), min(ages)
    # 시세를 입력했으면 '시세 2.5억 미만?' 질문은 묻지 않고 자동으로 채운다
    mp = answers.get("market_price")
    if isinstance(mp, (int, float)) and v.get("cheap") in (None, UNKNOWN):
        v["cheap"] = "yes" if mp < 2.5 else "no"
    return v


def test(cond: dict, values: dict):
    """조건 하나를 평가한다. True / False / None(모름)."""
    x = values.get(cond["field"])
    op, want = cond["op"], cond.get("value")
    if op == "empty":  # 아직 답이 없을 때만 참 (예: 시세를 몰라서 따로 물어야 할 때)
        return x is None or x == UNKNOWN
    if x is None or x == UNKNOWN:
        return None
    if op == "in":
        return x in want
    if op == ">=":
        return x >= want
    if op == "<=":
        return x <= want
    if op == "between":
        return want[0] <= x <= want[1]
    raise ValueError(f"알 수 없는 연산자: {op}")


def all_true(conds: list[dict], values: dict):
    results = [test(c, values) for c in conds]
    if any(r is False for r in results):
        return False
    if any(r is None for r in results):
        return None
    return True


# ---------- 질문 흐름 ----------

def visible_questions(questions: list[dict], answers: dict) -> list[dict]:
    """지금까지의 답으로 보여줄 질문 목록. show_if가 모두 참인 질문만."""
    values = derive(answers)
    return [q for q in questions if all_true(q.get("show_if", []), values) is True]


def clean_answers(questions: list[dict], answers: dict) -> dict:
    """보이지 않는 질문의 답은 지운다 (앞 답을 바꿔 분기가 달라졌을 때 대비)."""
    shown = {q["id"] for q in visible_questions(questions, answers)}
    keep = {"age_self", "age_spouse"} if "age" in shown else set()
    if "market_price" not in shown:
        keep.discard("market_price")
    return {k: v for k, v in answers.items() if k in shown or k in keep}


# ---------- 상품 판정 ----------

@dataclass
class Verdict:
    product: dict
    status: str
    reasons: list[str] = field(default_factory=list)
    tips: list[str] = field(default_factory=list)
    preferred: bool = False


def judge_requirement(req: dict, values: dict) -> tuple[str, str]:
    x = values.get(req["cond"]["field"])
    if x is None or x == UNKNOWN:
        return CHECK, f"{req['label']} (답하지 않아 확인 필요)"
    if x in req.get("check_values", []):
        return CHECK, req.get("check_label", req["label"])
    if test(req["cond"], values):
        return OK, req["label"]
    for alt in req.get("otherwise", []):
        r = all_true(alt["if"], values)
        if r is True:
            return alt["result"], alt["label"]
        if r is None:
            return CHECK, f"{alt['label']} (확인 필요)"
    return NO, req["label"]


def judge(product: dict, answers: dict) -> Verdict:
    values = derive(answers)
    results = [judge_requirement(r, values) for r in product["requires"]]
    failed = [label for s, label in results if s == NO]
    unsure = [label for s, label in results if s == CHECK]

    if product.get("sale_status") == "판매 종료":
        v = Verdict(product, NO, ["신규 판매가 종료된 상품이에요"])
    elif failed:
        v = Verdict(product, NO, [f"조건을 충족하지 못함 · {l}" for l in failed])
    elif unsure or product.get("sale_status") != "판매 중":
        reasons = list(unsure)
        if product.get("sale_status") != "판매 중":
            reasons.append("현재 신규 판매 여부를 금융회사에 확인해 주세요")
        v = Verdict(product, CHECK, reasons)
    else:
        v = Verdict(product, OK, [l for _, l in results])

    if v.status != NO:
        v.tips = [t["text"] for t in product.get("tips", []) if all_true(t["if"], values) is True]
    pref = answers.get("period")
    v.preferred = pref in ("life", "term") and pref == product["pay"]
    return v


def recommend(products: list[dict], answers: dict) -> dict[str, list[Verdict]]:
    """상태별로 묶고, 같은 상태 안에서는 선호(평생/기간)에 맞는 상품을 위로 올린다."""
    out = {OK: [], CHECK: [], NO: []}
    for p in products:
        v = judge(p, answers)
        out[v.status].append(v)
    for k in out:
        out[k].sort(key=lambda v: not v.preferred)
    return out


def field_usage(products: list[dict]) -> dict[str, list[str]]:
    """질문 변경 영향도: 각 답변 항목을 어떤 상품이 판정에 쓰는지."""
    usage: dict[str, set] = {}
    for p in products:
        for r in p["requires"]:
            fields = [r["cond"]["field"]] + [c["field"] for alt in r.get("otherwise", []) for c in alt["if"]]
            for f in fields:
                usage.setdefault(f, set()).add(p["name"])
    return {k: sorted(v) for k, v in usage.items()}


# ---------- HF 예상 월지급금 ----------

def load_payment_table() -> dict:
    return json.loads((DATA / "hf_payment_table.json").read_text(encoding="utf-8"))


def estimate_hf_monthly(younger_age, market_price_eok, table: dict | None = None) -> dict | None:
    """HF 종신 정액형 예상 월지급금(만 원).

    HF 예시표는 '시세 x 나이별 1억당 금액'에 나이별 상한을 둔 모양이라
    (표 전체를 ±0.1만 원 안에서 재현), 5세 단위 표 사이의 나이는 1억당 금액과 상한을 선형 보간한다.
    """
    if younger_age is None or not isinstance(market_price_eok, (int, float)) or market_price_eok <= 0:
        return None
    t = table or load_payment_table()
    ages = sorted(int(a) for a in t["table"])
    i5 = t["prices_eok"].index(5)
    rate = {a: t["table"][str(a)][i5] / 5 for a in ages}   # 1억당 월지급금
    cap = {a: t["table"][str(a)][-1] for a in ages}        # 나이별 상한 (12억 칸)
    notes = []
    age = younger_age
    if age < ages[0]:
        return None
    if age > ages[-1]:
        notes.append(f"표가 {ages[-1]}세까지라 {ages[-1]}세 기준으로 계산했어요 (실제로는 더 많을 수 있어요)")
        age = ages[-1]
    lo = max(a for a in ages if a <= age)
    hi = min(a for a in ages if a >= age)
    w = 0 if hi == lo else (age - lo) / (hi - lo)
    r = rate[lo] + (rate[hi] - rate[lo]) * w
    c = cap[lo] + (cap[hi] - cap[lo]) * w
    if lo != hi:
        notes.append(f"{lo}세와 {hi}세 표 사이를 나이 비율로 보간했어요")
    price = market_price_eok
    if price > t["price_cap_eok"]:
        notes.append(f"HF 예시표가 시세 {t['price_cap_eok']}억 원까지라 {t['price_cap_eok']}억 원 기준으로 계산했어요")
        price = t["price_cap_eok"]
    raw = r * price
    amount = min(raw, c)
    if raw > c:
        notes.append(f"{age}세의 월지급금 상한({c:.1f}만 원)이 적용됐어요")
    return {"amount": round(amount, 1), "age": younger_age, "price": market_price_eok,
            "notes": notes, "method": t["method"], "date": t["effective_date"], "source": t["source"]}
