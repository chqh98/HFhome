"""AI 기능 2가지.

1) 상품설명서 분석기: 금융회사 문서(비정형 텍스트)에서 핵심 조건을 정해진 형식으로 뽑고,
   형식을 검증한 뒤 현재 상품 DB와 항목별로 비교한다. 반영은 관리자가 승인해야만 한다.
2) 용어 설명 도우미: 용어집과 상품 DB에 있는 내용만 근거로 쉬운 말로 설명한다.
   특정 상품 가입을 권하지 않도록 지시문과 사후 점검을 둘 다 둔다.

판단(가입 가능 여부)은 AI가 아니라 engine.py의 Rule이 한다. AI는 데이터 구축과 이해 보조만 맡는다.
llm 함수는 인자로 받기 때문에, 테스트에서는 가짜 AI를 넣어 검증할 수 있다.
"""
from __future__ import annotations

import copy
import json
from datetime import datetime
from pathlib import Path
from typing import Callable

from llm import parse_json

DATA = Path(__file__).parent / "data"
LLM = Callable[..., str]  # chat(system, user, want_json=bool) -> str

# ---------------------------------------------------------------
# 1. 상품설명서 분석기
# ---------------------------------------------------------------
HOUSE_TYPES = ["아파트", "단독·빌라", "주거용 오피스텔", "기타"]
FIELDS = {
    # key: (화면 이름, 형식, 허용값, 영향받는 질문, 영향받는 곳)
    "min_age": ("가입 최소 연령", "int", None, "Q1 나이", "나이 조건 Rule"),
    "age_basis": ("연령 기준", "enum", ["본인", "부부 중 한 명", "부부 중 연소자", "언급없음"], "Q1 나이", "나이 조건 Rule"),
    "price_max_eok": ("주택가격 상한(억 원)", "num", None, "Q3 공시가격", "가격 조건 Rule, Q3 선택지 기준선"),
    "price_min_eok": ("주택가격 하한(억 원)", "num", None, "Q3 공시가격", "가격 조건 Rule, Q3 선택지 기준선"),
    "house_types": ("대상 주택", "list", HOUSE_TYPES, "Q4 주택 유형", "주택 유형 Rule"),
    "residence": ("실거주 요건", "enum", ["필수", "필수(예외 있음)", "불필요", "언급없음"], "Q5 실거주", "실거주 Rule, Q5 선택지"),
    "period_type": ("지급 기간 방식", "enum", ["종신", "확정기간", "언급없음"], "Q11 지급 방식", "결과 정렬"),
    "period_max_years": ("최장 지급기간(년)", "num", None, "-", "결과 화면 설명"),
    "limit_eok": ("대출 한도(억 원)", "num", None, "-", "결과 화면 설명"),
    "rate": ("금리", "text", None, "-", "결과 화면 설명"),
    "sale_status": ("판매 상태", "enum", ["판매 중", "판매 종료", "언급없음"], "-", "판정 결과(판매 중이 아니면 '확인 필요')"),
}

EXTRACT_SYSTEM = """너는 금융상품 문서에서 가입 조건을 뽑아 정해진 JSON으로 정리하는 도우미다.
규칙:
- 문서에 적힌 내용만 쓴다. 추측하거나 일반 상식으로 채우지 않는다.
- 문서에 없는 항목은 value를 null로 둔다.
- value가 null이 아니면 evidence에 그 근거가 된 문서 문장을 80자 이내로 그대로 옮긴다.
- 금액은 억 원 단위 숫자로 쓴다 (예: 12억원 → 12, 9천만원 → 0.9).
- 허용값이 정해진 항목은 반드시 그중 하나(목록은 그 값들만)로 쓴다.
- JSON 외의 말은 쓰지 않는다."""


def _schema_text() -> str:
    lines = []
    for k, (name, typ, allowed, *_rest) in FIELDS.items():
        rule = {"int": "정수", "num": "숫자", "text": "짧은 문장", "enum": f"다음 중 하나: {allowed}",
                "list": f"다음 값들의 목록: {allowed}"}[typ]
        lines.append(f'- "{k}": {name} ({rule})')
    return "\n".join(lines)


def build_extract_prompt(doc_text: str) -> str:
    return (
        "아래 문서에서 다음 항목을 뽑아줘.\n" + _schema_text() +
        '\n\n출력 형식:\n{"product_name": "문서에 나온 상품명",\n'
        ' "fields": {"min_age": {"value": 55, "evidence": "가입 연령: 만 55세 이상"}, ...모든 항목...},\n'
        ' "notes": "판매 종료, 조건 변경 예고 등 눈에 띄는 내용이 있으면 한 줄로"}\n\n'
        "판매 상태: 신규 판매 종료·중단 공지가 있으면 \"판매 종료\", 판매 중임이 드러나면 \"판매 중\", 알 수 없으면 \"언급없음\".\n\n"
        f"===== 문서 시작 =====\n{doc_text[:15000]}\n===== 문서 끝 ====="
    )


def _coerce(key: str, value):
    """AI가 준 값을 형식에 맞게 고친다. 맞출 수 없으면 (None, 경고)."""
    if value is None or value == "":
        return None, None
    _, typ, allowed, *_ = FIELDS[key]
    try:
        if typ == "int":
            return int(float(value)), None
        if typ == "num":
            return float(value), None
        if typ == "text":
            return str(value).strip(), None
        if typ == "enum":
            v = str(value).strip()
            return (v, None) if v in allowed else (None, f"허용되지 않은 값 '{v}'")
        if typ == "list":
            vals = value if isinstance(value, list) else [value]
            bad = [v for v in vals if v not in allowed]
            ok = sorted({v for v in vals if v in allowed}, key=allowed.index)
            return (ok or None), (f"허용되지 않은 값 {bad}" if bad else None)
    except (TypeError, ValueError):
        return None, f"형식이 맞지 않는 값 '{value}'"
    return None, None


def extract(doc_text: str, llm: LLM) -> dict:
    """문서 → {product_name, notes, fields: {key: {value, evidence, warning}}}"""
    raw = parse_json(llm(EXTRACT_SYSTEM, build_extract_prompt(doc_text), want_json=True))
    out = {"product_name": raw.get("product_name"), "notes": raw.get("notes") or "", "fields": {}}
    got = raw.get("fields", {}) or {}
    for k in FIELDS:
        item = got.get(k) or {}
        if not isinstance(item, dict):
            item = {"value": item}
        value, warn = _coerce(k, item.get("value"))
        evidence = (item.get("evidence") or "").strip()
        if value is not None and not evidence:
            warn = (warn + " / " if warn else "") + "근거 문장 없음"
        if value is not None and evidence and evidence[:15] not in doc_text:
            # 근거 문장이 원문에 없으면 AI가 지어냈을 가능성 → 사람이 꼭 확인
            warn = (warn + " / " if warn else "") + "근거 문장이 원문에서 확인되지 않음"
        out["fields"][k] = {"value": value, "evidence": evidence, "warning": warn}
    return out


def fmt(v) -> str:
    if v is None:
        return "-"
    if isinstance(v, list):
        return ", ".join(v)
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def _same(a, b) -> bool:
    if isinstance(a, list) or isinstance(b, list):
        return set(a or []) == set(b or [])
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) < 1e-9
    return str(a).replace(" ", "") == str(b).replace(" ", "")


def compare(profile: dict, extracted: dict) -> list[dict]:
    """현재 DB(profile)와 AI 추출값을 항목별로 비교한다.
    상태: 변경 / 같음 / 새로 확인(DB가 비어 있던 항목) / 문서에 없음"""
    rows = []
    for k, (name, _typ, _allowed, question, where) in FIELDS.items():
        cur = profile.get(k)
        f = extracted["fields"][k]
        new = f["value"]
        if new is None or new == "언급없음":
            status = "문서에 없음"
        elif cur is None or cur == "언급없음":
            status = "새로 확인"
        elif _same(cur, new):
            status = "같음"
        else:
            status = "변경"
        rows.append({"key": k, "항목": name, "현재 DB": fmt(cur), "AI 추출": fmt(new), "상태": status,
                     "근거 문장": f["evidence"], "주의": f["warning"] or "", "영향 질문": question,
                     "영향 범위": where, "_new": new})
    return rows


def apply_change(products: list[dict], pid: str, key: str, value, approver: str) -> tuple[list[dict], dict]:
    """승인된 변경 1건을 상품 DB(메모리 사본)에 반영하고 감사 기록을 돌려준다.
    profile은 그대로 바꾸고, 판정 Rule에 바로 연결되는 항목(판매 상태, 최소 연령)은 Rule도 같이 고친다.
    가격 기준선처럼 질문 선택지까지 바뀌어야 하는 변경은 '질문 수정 필요'로 남긴다."""
    products = copy.deepcopy(products)
    p = next(x for x in products if x["id"] == pid)
    before = p.setdefault("profile", {}).get(key)
    p["profile"][key] = value
    follow_up = ""

    if key == "sale_status":
        p["sale_status"] = value if value in ("판매 중", "판매 종료") else "확인 필요"
        follow_up = "판정에 바로 반영됨" + (" (판매 종료 상품은 '가입할 수 있어요'에 나오지 않음)" if value == "판매 종료" else "")
    elif key == "min_age":
        for r in p["requires"]:
            c = r["cond"]
            if c["field"].startswith("age_") and c["op"] == ">=" and c["value"] == before:
                c["value"] = value
                r["label"] = r["label"].replace(str(before), str(value))
                follow_up = f"나이 Rule을 {before}세 → {value}세로 수정함"
        if not follow_up:
            follow_up = "나이 Rule을 자동으로 찾지 못함: 관리자가 Rule 직접 확인 필요"
    elif key in ("price_max_eok", "price_min_eok"):
        follow_up = "질문 수정 필요: Q3 선택지의 12억 기준선과 가격 Rule을 함께 고쳐야 함"
    elif key in ("residence", "house_types"):
        follow_up = f"질문 수정 필요: {FIELDS[key][3]} 선택지와 Rule 검토"
    else:
        follow_up = "결과 화면 설명에 반영"

    log = {"시각": datetime.now().strftime("%Y-%m-%d %H:%M"), "승인자": approver or "(이름 없음)",
           "상품": p["name"], "항목": FIELDS[key][0], "이전": fmt(before), "이후": fmt(value), "후속 조치": follow_up}
    return products, log


def export_products_json(products: list[dict]) -> str:
    """승인된 변경이 반영된 products.json 내용 (저장소에 올려 영구 반영할 때 사용)."""
    raw = json.loads((DATA / "products.json").read_text(encoding="utf-8"))
    by_id = {p["id"]: p for p in products}
    for item in raw["products"]:
        cur = by_id.get(item["id"])
        if not cur:
            continue
        item["profile"] = cur.get("profile", item.get("profile"))
        item["sale_status"] = cur.get("sale_status", item["sale_status"])
        if isinstance(item["requires"], list):
            # 그룹(@hf_base)을 쓰지 않는 상품만 Rule을 통째로 갱신
            if not any(isinstance(r, str) for r in item["requires"]):
                item["requires"] = cur["requires"]
    return json.dumps(raw, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------
# 2. 용어 설명 도우미
# ---------------------------------------------------------------
def load_glossary() -> list[dict]:
    return json.loads((DATA / "glossary.json").read_text(encoding="utf-8"))["terms"]


HELPER_SYSTEM = """너는 50~70대 어르신께 주택연금 용어를 쉽게 설명하는 도우미다.
반드시 지킬 것:
1. [자료]에 있는 내용만으로 답한다. 자료에 없으면 지어내지 말고
   "제가 가진 자료에는 없는 내용이에요. 한국주택금융공사(☎1688-8114)나 해당 금융회사에 물어보세요."라고 답한다.
2. 어떤 상품에 가입하라고 권하거나 "이 상품이 좋다", "추천한다"고 말하지 않는다.
   비교를 물으면 차이점만 설명하고, 결정은 본인과 가족, 금융회사 상담을 통해 하시라고 안내한다.
3. 숫자(금액·나이·기간)는 자료에 있는 것만 쓴다. 월 수령액을 계산하거나 추정하지 않는다.
4. 존댓말로, 쉬운 단어로, 3~5문장으로 짧게 답한다. 어려운 금융 용어는 풀어서 말한다.
5. 마지막 줄에 "근거: " 뒤에 참고한 자료 이름(용어 이름이나 상품 이름)을 쓴다."""

PUSH_WORDS = ["가입하세요", "가입하시는 게 좋", "추천합니다", "추천드립니다", "추천해요", "이 상품이 가장 좋", "가입을 권"]
SAFETY_NOTE = "※ 이 설명은 정보 제공용이에요. 가입 여부는 가족과 상의하시고 금융회사 상담을 통해 결정하세요."


def build_context(glossary: list[dict], products: list[dict], result_summary: str = "") -> str:
    g = "\n".join(f"- {t['term']}: {t['text']} (출처: {t['source']})" for t in glossary)
    p = "\n".join(f"- {x['name']} ({x['org']}): {x.get('summary', '')} / 판매 상태: {x['sale_status']}"
                  for x in products)
    ctx = f"[자료: 용어집]\n{g}\n\n[자료: 상품 DB]\n{p}"
    if result_summary:
        ctx += f"\n\n[자료: 이 사용자의 판정 결과]\n{result_summary}"
    return ctx


def match_terms(question: str, glossary: list[dict]) -> list[dict]:
    q = question.replace(" ", "")
    hits = []
    for t in glossary:
        names = [t["term"]] + t.get("aliases", [])
        if any(n.replace(" ", "") in q for n in names if n):
            hits.append(t)
    # 긴 용어가 먼저 (예: '종신혼합방식'이 '종신방식'보다 앞)
    return sorted(hits, key=lambda t: -len(t["term"]))


def explain(question: str, glossary: list[dict], products: list[dict], llm: LLM | None,
            result_summary: str = "") -> dict:
    """답변 {text, source: 'ai'|'glossary'|'none', note}. AI가 없거나 실패하면 용어집에서 찾아 보여준다."""
    question = (question or "").strip()[:300]
    if not question:
        return {"text": "", "source": "none", "note": ""}
    if llm is not None:
        try:
            ans = llm(HELPER_SYSTEM, build_context(glossary, products, result_summary) + f"\n\n[질문]\n{question}",
                      want_json=False).strip()
            note = ""
            if any(w in ans for w in PUSH_WORDS):
                ans += "\n\n" + SAFETY_NOTE
                note = "권유 표현이 감지되어 안내 문구를 덧붙였어요."
            return {"text": ans, "source": "ai", "note": note}
        except Exception as e:  # AI 실패 시 용어집으로 대신 답한다
            fallback = _glossary_answer(question, glossary)
            fallback["note"] = f"AI 연결에 실패해 용어집으로 답했어요. ({e})"
            return fallback
    return _glossary_answer(question, glossary)


def _glossary_answer(question: str, glossary: list[dict]) -> dict:
    hits = match_terms(question, glossary)
    if not hits:
        return {"text": "용어집에서 찾지 못했어요. 한국주택금융공사(☎1688-8114)나 해당 금융회사에 물어보세요.",
                "source": "none", "note": ""}
    text = "\n\n".join(f"**{t['term']}**: {t['text']}" for t in hits[:2])
    return {"text": text + "\n\n근거: " + ", ".join(t["source"] for t in hits[:2]), "source": "glossary", "note": ""}
