"""우리 집 연금 찾기 — 주택연금 맞춤 정보 서비스 (Streamlit 프로토타입)

실행:  streamlit run app.py
"""
import hashlib

import streamlit as st

import ai_tools as A
import engine as E
import family as F
import llm

st.set_page_config(page_title="우리 집 연금 찾기", page_icon="🏠", layout="centered")

# ---------- 고령층용 큰 글씨 스타일 ----------
st.markdown(
    """
<style>
[data-testid="stMarkdownContainer"] p, [data-testid="stMarkdownContainer"] li { font-size: 1.15rem; line-height: 1.7; }
div.stButton > button, a[data-testid="stBaseLinkButton-secondary"], a[data-testid="stBaseLinkButton-primary"] {
  width: 100%; min-height: 3.4rem; font-size: 1.2rem; font-weight: 600; border-radius: 10px;
}
div[data-testid="stNumberInput"] input { font-size: 1.4rem; min-height: 3rem; }
div[data-testid="stNumberInput"] label p { font-size: 1.1rem; }
.qno { color: #1f6b5c; font-weight: 700; font-size: 1rem; letter-spacing: .05em; }
.qtext { font-size: 1.7rem; font-weight: 700; line-height: 1.4; margin: .2rem 0 .6rem; }
.badge { display: inline-block; padding: .15rem .7rem; border-radius: 99px; font-weight: 700; font-size: 1rem; }
.b-ok { background: #e2f2e8; color: #2c7a4b; } .b-check { background: #fbf0d4; color: #8a5f00; }
.b-no { background: #f6e3e3; color: #9b3a3a; } .b-pref { background: #f6ebdc; color: #a8641c; }
.small { font-size: .95rem; color: #6b7775; }
</style>
""",
    unsafe_allow_html=True,
)

Q = E.load_questions()
QMAP = {q["id"]: q for q in Q}

PRESETS = {
    "62세 부부 · 아파트 5억 · 대출 있음": dict(age_self=62, age_spouse=59, houses="1", price="le", market_price=7.0, type="apt", live="yes",
                                     farm="no", basic="no", loan="yes", period="life", lump="no"),
    "51세 조기퇴직 · 공시 9억": dict(age_self=51, age_spouse=50, houses="1", price="le", type="apt", live="yes",
                               job="yes", loan="no", period="term", lump="no"),
    "68세 부부 · 공시 15억 아파트": dict(age_self=68, age_spouse=64, houses="1", price="gt", type="apt", live="yes",
                                  farm="no", own2="yes", loan="no", period="life", lump="yes"),
    "71세 농업인 · 시골 단독주택": dict(age_self=71, age_spouse=None, houses="1", price="le", market_price=1.8, type="house", live="yes",
                                 farm="yes", basic="yes", loan="no", period="life", lump="no"),
}

DISCLAIMER = (
    "이 서비스는 입력하신 조건에 해당하는 상품 정보를 안내할 뿐, 특정 상품의 가입을 권유하지 않습니다. "
    "실제 가입 가능 여부와 받는 금액은 각 금융회사에서 최종 확인하세요."
)

# ---------- 상태 ----------
ss = st.session_state
ss.setdefault("answers", {})
ss.setdefault("cur", "intro")  # intro | 질문 id | result
ss.setdefault("guide", None)  # '잘 모르겠어요' 안내를 펼친 질문 id
ss.setdefault("age_error", "")
ss.setdefault("num_error", "")
# 상품 DB는 세션 사본을 쓴다. 관리자가 승인한 변경이 이 사본에 반영돼 바로 추천 결과에 적용된다.
ss.setdefault("products", E.load_products())
ss.setdefault("audit", [])          # 승인 기록
ss.setdefault("helper", {})         # 용어 도우미 답변 (화면별)
ss.setdefault("helper_cache", {})   # 같은 질문 재호출 방지
ss.setdefault("sim", dict(E.SIM_DEFAULTS))  # 상속 시뮬레이션 가정
ss.setdefault("family_view", False)
P = ss.products
G = A.load_glossary()

# 가족이 공유 링크(?r=...)로 들어오면 그 결과를 그대로 복원한다
_code = st.query_params.get("r")
if _code and ss.get("loaded_share") != _code:
    _dec = F.decode_share(_code)
    ss.loaded_share = _code
    if _dec:
        ss.answers = E.clean_answers(Q, _dec[0])
        ss.sim.update(_dec[1])
        ss.cur, ss.family_view = "result", True


# ---------- AI 연결 ----------
def _secret(name, default=""):
    try:
        return st.secrets.get(name, default)
    except Exception:  # secrets 파일이 없을 때
        return default


def ai_config():
    """Secrets 설정을 우선 쓰고, 없으면 관리자 화면에서 이 세션에만 입력한 키를 쓴다."""
    if _secret("LLM_API_KEY"):
        return _secret("LLM_PROVIDER", "gemini"), _secret("LLM_API_KEY"), _secret("LLM_MODEL") or None
    return ss.get("ui_provider", "gemini"), ss.get("ui_api_key", ""), ss.get("ui_model") or None


def save_ai_settings():
    # 위젯 값은 다른 화면으로 가면 지워지므로 별도 키에 옮겨 둔다
    ss.ui_provider = ss.get("w_provider", "gemini")
    ss.ui_api_key = (ss.get("w_api_key") or "").strip()
    ss.ui_model = (ss.get("w_model") or "").strip()


def get_llm():
    provider, key, model = ai_config()
    if not key:
        return None

    def call(system, user, want_json=False):
        return llm.chat(system, user, provider=provider, api_key=key, model=model, want_json=want_json)
    return call


def visible_ids():
    return [q["id"] for q in E.visible_questions(Q, ss.answers)]


def go_next(after):
    ids = visible_ids()
    i = ids.index(after) if after in ids else -1
    ss.cur = ids[i + 1] if i + 1 < len(ids) else "result"
    ss.guide = None


def go_back():
    ids = visible_ids()
    if ss.cur == "result":
        ss.cur = ids[-1]
    elif ss.cur in ids and ids.index(ss.cur) > 0:
        ss.cur = ids[ids.index(ss.cur) - 1]
    else:
        ss.cur = "intro"
    ss.guide = None


def answer(qid, value):
    ss.answers[qid] = value
    ss.answers = E.clean_answers(Q, ss.answers)
    go_next(qid)


def submit_age():
    a, b = ss.get("in_age_self"), ss.get("in_age_spouse")
    if a is None or not 20 <= a <= 110:
        ss.age_error = "본인 나이를 20~110 사이 숫자로 적어주세요."
        return
    if b is not None and not 20 <= b <= 110:
        ss.age_error = "배우자 나이를 20~110 사이 숫자로 적거나 비워두세요."
        return
    ss.age_error = ""
    ss.answers["age_self"], ss.answers["age_spouse"] = int(a), (int(b) if b is not None else None)
    ss.answers = E.clean_answers(Q, ss.answers)
    go_next("age")


def submit_number(qid):
    q = QMAP[qid]
    v = ss.get(f"in_{qid}")
    if v is None or not q.get("min", 0) <= v <= q.get("max", 1e9):
        ss.num_error = f"{q.get('min', 0)}~{q.get('max')} 사이 숫자로 적어주세요."
        return
    ss.num_error = ""
    answer(qid, round(float(v), 2))


def toggle_guide(qid):
    ss.guide = None if ss.guide == qid else qid


def restart():
    ss.answers, ss.cur, ss.guide, ss.family_view = {}, "intro", None, False
    try:
        st.query_params.clear()
    except Exception:
        pass
    for k in ("in_age_self", "in_age_spouse", "in_market_price"):
        ss.pop(k, None)


def load_preset(name):
    ss.answers = E.clean_answers(Q, dict(PRESETS[name]))
    for k in ("in_age_self", "in_age_spouse", "in_market_price"):
        ss.pop(k, None)
    ss.cur, ss.guide = "result", None


def answer_label(qid, value):
    if value == E.UNKNOWN:
        return "잘 모르겠어요 (확인 필요)"
    if QMAP[qid]["type"] == "number":
        return f"{value:g} {QMAP[qid].get('unit', '')}"
    return dict(QMAP[qid].get("options", [])).get(value, str(value))


# ---------- 화면: 시작 ----------
def page_intro():
    st.title("우리 집 연금 찾기")
    st.markdown(
        "지금 살고 계신 집으로 **매달 연금을 받을 수 있는지** 알아보세요.\n\n"
        "한국주택금융공사(HF) 주택연금과 은행·보험사·농협의 비슷한 상품까지 "
        "**9개 상품**을 한 번에 비교해 드려요."
    )
    st.markdown("- 질문은 **10개 안팎**이고, 3분이면 끝나요.\n"
                "- 모르는 내용은 **'잘 모르겠어요'**를 누르면 어디서 확인하는지 알려드려요.\n"
                "- 이름·전화번호 같은 개인정보는 묻지 않아요.")
    st.button("시작하기", type="primary", on_click=lambda: ss.update(cur="age"))
    st.caption(DISCLAIMER)


# ---------- 화면: 질문 ----------
def progress_bar(qid):
    ids = visible_ids()
    n = ids.index(qid) + 1 if qid in ids else 1
    st.progress(n / (len(ids) + 1), text=f"{n}번째 질문 / 약 {len(ids)}개")


def page_age(q):
    progress_bar("age")
    st.markdown(f'<div class="qno">{q["no"]}</div><div class="qtext">{q["text"]}</div>', unsafe_allow_html=True)
    st.caption(q.get("help", ""))
    # 위젯 값은 session_state로만 넣는다 (value= 와 같이 쓰면 경고가 뜬다)
    if "in_age_self" not in ss:
        ss.in_age_self = ss.answers.get("age_self")
    if "in_age_spouse" not in ss:
        ss.in_age_spouse = ss.answers.get("age_spouse")
    c1, c2 = st.columns(2)
    with c1:
        st.number_input("본인 (만 나이)", min_value=0, max_value=120, step=1,
                        key="in_age_self", placeholder="예: 63")
    with c2:
        st.number_input("배우자 (없으면 비워두세요)", min_value=0, max_value=120, step=1,
                        key="in_age_spouse", placeholder="예: 60")
    if ss.age_error:
        st.error(ss.age_error)
    st.button("다음", type="primary", on_click=submit_age)
    st.button("← 이전", on_click=go_back)


def page_choice(q):
    progress_bar(q["id"])
    st.markdown(f'<div class="qno">{q["no"]}</div><div class="qtext">{q["text"]}</div>', unsafe_allow_html=True)
    if q.get("help"):
        st.caption(q["help"])
    current = ss.answers.get(q["id"])
    for value, label in q["options"]:
        picked = current == value
        st.button(("✓ " if picked else "") + label, key=f"opt_{q['id']}_{value}",
                  type="primary" if picked else "secondary", on_click=answer, args=(q["id"], value))
    unknown_box(q)
    st.button("← 이전", key=f"back_{q['id']}", on_click=go_back)


def page_number(q):
    progress_bar(q["id"])
    st.markdown(f'<div class="qno">{q["no"]}</div><div class="qtext">{q["text"]}</div>', unsafe_allow_html=True)
    if q.get("help"):
        st.caption(q["help"])
    key = f"in_{q['id']}"
    if key not in ss:
        cur = ss.answers.get(q["id"])
        ss[key] = cur if isinstance(cur, (int, float)) else None
    st.number_input(f"{q.get('unit', '')} 단위로 적어주세요", min_value=0.0, max_value=float(q.get("max", 100)),
                    step=float(q.get("step", 0.1)), format="%.1f", key=key, placeholder="예: 4.5")
    if ss.get("num_error"):
        st.error(ss.num_error)
    st.button("다음", type="primary", key=f"next_{q['id']}", on_click=submit_number, args=(q["id"],))
    unknown_box(q)
    st.button("← 이전", key=f"back_{q['id']}", on_click=go_back)


def unknown_box(q):
    if q.get("allow_unknown", True):
        st.button("잘 모르겠어요", key=f"unk_{q['id']}", on_click=toggle_guide, args=(q["id"],))
        if ss.guide == q["id"]:
            g = q.get("guide", {})
            with st.container(border=True):
                st.markdown("**이렇게 확인할 수 있어요**")
                st.markdown(g.get("text", ""))
                for name, url in g.get("links", []):
                    st.link_button(f"{name} 바로가기 ↗", url)
                st.markdown('<span class="small">확인하신 뒤 위에서 답을 골라주세요. '
                            '확인이 어려우면 일단 넘어가도 돼요. 결과에 \'확인 필요\'로 표시해 드려요.</span>',
                            unsafe_allow_html=True)
                st.button("확인하지 못했어요. 일단 넘어갈게요", key=f"skip_{q['id']}",
                          on_click=answer, args=(q["id"], E.UNKNOWN))


# ---------- 용어 설명 도우미 ----------
QUICK_QUESTIONS = ["종신방식과 확정기간 방식은 뭐가 달라요?", "공시가격이랑 시세는 뭐가 달라요?",
                   "보증료는 언제 내요?", "나중에 자식한테 빚이 넘어가나요?"]


def ask_helper(slot, question, summary):
    question = (question or "").strip()
    if not question:
        return
    ck = hashlib.md5(f"{question}|{summary}|{ai_config()[0]}".encode()).hexdigest()
    if ck not in ss.helper_cache:
        ss.helper_cache[ck] = A.explain(question, G, P, get_llm(), summary)
    ss.helper[slot] = {"q": question, **ss.helper_cache[ck]}


def helper_box(slot, summary=""):
    st.markdown("#### 모르는 말이 있으세요?")
    st.caption("주택연금 용어를 쉬운 말로 풀어드려요. 아래를 누르거나 직접 물어보세요.")
    for i, qq in enumerate(QUICK_QUESTIONS):
        st.button(qq, key=f"{slot}_quick_{i}", on_click=ask_helper, args=(slot, qq, summary))
    st.text_input("직접 물어보기", key=f"{slot}_input", placeholder="예: 대출상환방식이 뭐예요?")
    st.button("물어보기", key=f"{slot}_ask", type="primary",
              on_click=lambda: ask_helper(slot, ss.get(f"{slot}_input", ""), summary))
    a = ss.helper.get(slot)
    if a:
        with st.container(border=True):
            st.markdown(f"**Q. {a['q']}**")
            st.markdown(a["text"])
            src = {"ai": "AI 답변 · 용어집과 상품 DB에 있는 내용만 근거로 답해요",
                   "glossary": "용어집 검색 결과", "none": ""}[a["source"]]
            if src:
                st.caption(src)
            if a.get("note"):
                st.caption(a["note"])


def result_summary(res):
    return " / ".join(f"{E.STATUS_LABEL[k]}: " + (", ".join(v.product["name"] for v in res[k]) or "없음")
                      for k in (E.OK, E.CHECK, E.NO))


def answer_lines():
    out = []
    for q in E.visible_questions(Q, ss.answers):
        if q["id"] == "age":
            sp = ss.answers.get("age_spouse")
            val = f"본인 {ss.answers.get('age_self')}세" + (f", 배우자 {sp}세" if sp else "")
        else:
            val = answer_label(q["id"], ss.answers.get(q["id"])) if q["id"] in ss.answers else "-"
        out.append(f"{q['no']} {q['text']} → {val}")
    return out


# ---------- 상속 시뮬레이션 ----------
def sim_rows(est):
    s = ss.sim
    return E.simulate_inheritance(est["age"], est["price"], est["amount"], house_growth=s["house_growth"],
                                  rate=s["rate"], fee_initial=s["fee_initial"], fee_annual=s["fee_annual"])


def set_sim(key, widget):
    ss.sim[key] = float(ss[widget])


def sim_section(est):
    st.markdown("### 나중에 자녀에게 남는 금액은?")
    st.caption("주택연금에 가입하지 않는 이유 1위는 '자녀에게 상속하려고'예요(HF 2022 실태조사, 54.4%). "
               "가입했을 때와 안 했을 때 자녀에게 남는 금액을 직접 비교해 보세요.")
    for widget, key, label, lo, hi, step in (("w_growth", "house_growth", "집값 상승률 (연 %)", 0.0, 4.0, 0.5),
                                              ("w_rate", "rate", "주택연금 대출금리 (연 %)", 3.0, 6.0, 0.25)):
        if widget not in ss:
            ss[widget] = float(ss.sim[key])
        st.slider(label, lo, hi, step=step, key=widget, on_change=set_sim, args=(key, widget))
    rows = sim_rows(est)
    try:
        import pandas as pd
        df = pd.DataFrame([{"년 뒤": r["year"], "주택연금 가입 시": r["inherit_joined"],
                            "가입 안 함 (집 그대로)": r["inherit_not_joined"],
                            "가입 안 함 + 자녀가 같은 생활비를 드린 경우": r["inherit_child_support"]}
                           for r in rows if r["year"] <= 35]).set_index("년 뒤")
        st.line_chart(df, y_label="자녀에게 남는 금액 (억 원)", x_label="가입 후 년수")
    except ImportError:
        pass
    ins = E.sim_insight(rows)
    at = ins["at"]
    lines = []
    for y in (10, 20):
        r = at.get(y)
        if r:
            lines.append(f"- **{y}년 뒤({r['age']}세)**: 가입 시 약 **{r['inherit_joined']:.1f}억**, "
                         f"가입 안 함 {r['inherit_not_joined']:.1f}억 "
                         f"(그동안 받은 생활비 {r['paid']:.1f}억은 부모님이 자녀 도움 없이 마련)")
    st.markdown("\n".join(lines))
    if ins["cross_year"] is not None:
        st.info(f"{ins['cross_year']}년 뒤({ins['cross_age']}세)부터는 갚을 돈이 집값보다 커져요. "
                "그래도 HF 주택연금은 **비소구**라서 넘는 금액을 자녀에게 청구하지 않아요. "
                "오래 사실수록 부모님께 유리한 구조예요.")
    st.caption(f"가정: 집값 연 {ss.sim['house_growth']}% 상승 · 대출금리 연 {ss.sim['rate']}% · 초기보증료 "
               f"{ss.sim['fee_initial']}% · 연보증료 {ss.sim['fee_annual']}%(2026.3.1 기준) · 이자는 월 복리. "
               "참고용 계산이며 실제와 다를 수 있어요.")
    return rows


def share_section(res, est, rows):
    st.markdown("### 가족과 함께 보기")
    st.caption("주택연금은 가족이 함께 정하는 경우가 많아요. 이 결과를 자녀나 배우자에게 보내보세요. "
               "이름·주소 같은 개인정보는 담기지 않아요.")
    code = F.encode_share(ss.answers, ss.sim)
    base = _secret("APP_URL", "").rstrip("/")
    link = f"{base}/?r={code}" if base else f"?r={code}"
    msg = F.message_text(link, est if any(v.product["id"] == "hf_life" for v in res[E.OK]) else None, len(res[E.OK]))
    st.text_area("카카오톡·문자로 보낼 내용 (길게 눌러 복사하세요)", msg, height=170)
    if not base:
        st.caption("관리자: Secrets에 APP_URL(앱 주소)을 넣으면 완성된 링크가 만들어져요.")
    report = F.build_report(ss.answers, res, est, rows, ss.sim, answer_lines())
    st.download_button("가족 리포트 내려받기 (인쇄·공유용)", report, file_name="우리집연금_가족리포트.html",
                       mime="text/html", type="primary")


# ---------- 화면: 결과 ----------
BADGE = {E.OK: ("b-ok", "가입할 수 있어요"), E.CHECK: ("b-check", "확인이 필요해요"), E.NO: ("b-no", "해당되지 않아요")}


PAY_TABLE = E.load_payment_table()


def hf_estimate():
    vals = E.derive(ss.answers)
    return E.estimate_hf_monthly(vals.get("age_younger"), ss.answers.get("market_price"), PAY_TABLE)


def estimate_lines(pid, est):
    """상품 카드에 붙일 예상 금액 안내. HF 예시표가 있는 종신 정액형만 금액을 계산한다."""
    if not pid.startswith("hf_"):
        return None, None
    if est is None:
        return None, "Q3-1에서 집 시세를 입력하면 예상 월지급금을 계산해 드려요."
    base = f"{est['amount']:,.1f}만 원"
    if pid == "hf_life":
        return f"예상 월지급금 약 **{base}** (종신 정액형)", None
    if pid == "hf_pref":
        return None, f"일반 종신방식(약 {base})보다 매달 더 받아요. 정확한 금액은 HF에서 확인하세요."
    if pid == "hf_term":
        return None, f"종신방식(약 {base})보다 매달 더 받지만, 정한 기간이 끝나면 지급이 멈춰요."
    if pid == "hf_loan":
        return None, f"대출을 갚는 데 쓴 만큼 종신방식(약 {base})보다 매달 받는 돈이 줄어요."
    return None, None


def product_card(v, est=None):
    p = v.product
    with st.container(border=True):
        tags = f'<span class="badge {BADGE[v.status][0]}">{BADGE[v.status][1]}</span>'
        if v.preferred and v.status != E.NO:
            tags += ' <span class="badge b-pref">원하시는 지급 방식</span>'
        st.markdown(tags, unsafe_allow_html=True)
        st.markdown(f"### {p['name']}")
        st.markdown(f'<span class="small">{p["org"]} · 정보 확인 {p["last_checked"]}</span>', unsafe_allow_html=True)
        st.markdown(p.get("summary", ""))
        if v.status != E.NO:
            big, small = estimate_lines(p["id"], est)
            if big:
                st.markdown(f"#### {big}")
                st.caption(f"HF {est['date']} 월지급금 예시표 기준 추정 · 나이가 적은 분 {est['age']}세 · 시세 {est['price']:g}억 원"
                           + ("".join(f" · {n}" for n in est["notes"])))
            if small:
                st.caption(small)
        title = {"ok": "이런 조건이 맞아요", "check": "이 부분을 확인해 주세요", "no": "이런 이유로 어려워요"}[v.status]
        st.markdown(f"**{title}**\n" + "\n".join(f"- {r}" for r in v.reasons))
        for t in v.tips:
            st.info(t)
        if v.status != E.NO:
            st.link_button("공식 안내 보기 ↗", p["source"])


def page_result():
    res = E.recommend(P, ss.answers)
    if ss.family_view:
        st.info("가족이 보낸 주택연금 진단 결과예요. 아래 '나중에 자녀에게 남는 금액'을 함께 살펴보세요.")
    st.title("알아본 결과예요")
    n_ok, n_chk = len(res[E.OK]), len(res[E.CHECK])
    if n_ok:
        st.success(f"가입할 수 있는 상품이 **{n_ok}개** 있어요. 확인이 필요한 상품은 {n_chk}개예요.")
    else:
        st.warning(f"바로 가입할 수 있는 상품은 없지만, 확인해 볼 상품이 {n_chk}개 있어요.")
    pref = ss.answers.get("period")
    if pref in ("life", "term"):
        st.caption("원하시는 방식(" + ("평생 받기" if pref == "life" else "정해진 기간 동안 받기")
                   + ")에 맞는 상품을 먼저 보여드려요.")

    est = hf_estimate()
    hf_ok = any(v.product["id"] == "hf_life" for v in res[E.OK] + res[E.CHECK])
    if est and hf_ok:
        with st.container(border=True):
            st.markdown("**HF 주택연금(종신 정액형)으로 받으면 매달**")
            st.markdown(f"## 약 {est['amount']:,.1f}만 원")
            st.caption(f"HF {est['date']} 월지급금 예시표 기준 추정이에요. 실제 금액은 HF의 주택 가격 평가와 "
                       "가입 시점 기준에 따라 달라져요.")
            st.link_button("HF에서 정확한 예상 연금 조회하기 ↗", "https://www.hf.go.kr")
    rows = None
    if est and hf_ok:
        with st.container(border=True):
            rows = sim_section(est)

    for v in res[E.OK] + res[E.CHECK]:
        product_card(v, est)
    if res[E.NO]:
        with st.expander(f"해당되지 않는 상품 {len(res[E.NO])}개와 그 이유"):
            for v in res[E.NO]:
                product_card(v, est)

    st.divider()
    share_section(res, est if hf_ok else None, rows)
    st.divider()
    summ = result_summary(res)
    if est and hf_ok:
        summ += f" / HF 종신 정액형 예상 월지급금: 약 {est['amount']:.1f}만 원 (HF {est['date']} 예시표 기준 추정)"
    if rows:
        at = E.sim_insight(rows)["at"]
        summ += " / 상속 시뮬레이션(가정: 집값 연 {g}%, 금리 연 {r}%): ".format(g=ss.sim["house_growth"], r=ss.sim["rate"])
        summ += ", ".join(f"{y}년 뒤 가입 시 {x['inherit_joined']:.1f}억·미가입 시 {x['inherit_not_joined']:.1f}억"
                          for y, x in at.items() if y in (10, 20))
    helper_box("result", summ)
    st.divider()

    with st.expander("내가 고른 답 다시 보기"):
        for line in answer_lines():
            st.markdown(f"- {line}")

    c1, c2 = st.columns(2)
    with c1:
        st.button("← 이전 질문", on_click=go_back)
    with c2:
        st.button("처음부터 다시", on_click=restart)
    st.caption(DISCLAIMER)


# ---------- 화면: 관리자 ----------
def page_admin():
    st.title("상품 DB · 관리자 화면")
    st.markdown("추천은 상품 DB의 조건(Rule)으로만 판정해요. AI는 판정하지 않고, "
                "상품설명서에서 조건을 뽑아 **사람이 승인할 후보**를 만드는 일만 해요.")
    t1, t2, t3 = st.tabs(["상품 DB", "AI 상품설명서 분석기", "변경 이력"])
    with t1:
        tab_db()
    with t2:
        tab_analyzer()
    with t3:
        tab_audit()


def tab_db():
    st.subheader("상품 목록")
    st.dataframe(
        [{"상품": p["name"], "기관": p["org"], "지급": "평생" if p["pay"] == "life" else "기간",
          "판매 상태": p["sale_status"], "마지막 확인": p["last_checked"], "조건 수": len(p["requires"]),
          "출처": p["source"]} for p in P],
        use_container_width=True, hide_index=True,
        column_config={"출처": st.column_config.LinkColumn("출처")},
    )
    st.subheader("질문 변경 영향도")
    st.markdown("상품 조건이 바뀌면 아래 표로 영향받는 질문과 상품을 바로 찾을 수 있어요.")
    usage = E.field_usage(P)
    rows = []
    for q in Q:
        fields = ["age_self", "age_older", "age_younger"] if q["id"] == "age" else [q["id"]]
        names = sorted({n for f in fields for n in usage.get(f, [])})
        rows.append({"질문": q["no"], "내용": q["text"],
                     "판정에 쓰는 상품": ", ".join(names) if names else "(결과 순서·안내에만 사용)"})
    st.dataframe(rows, use_container_width=True, hide_index=True)
    st.subheader("상품별 조건")
    for p in P:
        with st.expander(p["name"]):
            for r in p["requires"]:
                c = r["cond"]
                st.markdown(f"- **{r['label']}** — `{c['field']} {c['op']} {c['value']}`")


SAMPLES = {
    "하나생명 상품설명서 (가입연령 변경 시연)": ("hana_life", "hana_life_demo.txt"),
    "신한은행 판매 종료 공지 (판매 중단 시연)": ("shinhan", "shinhan_notice_demo.txt"),
}


def load_sample(name):
    pid, fname = SAMPLES[name]
    ss.doc_text = (A.DATA / "samples" / fname).read_text(encoding="utf-8")
    ss.an_pid = pid
    ss.an_error = ""
    ss.pop("analysis", None)


def load_upload():
    f = ss.get("doc_file")
    if f is None:
        return
    data = f.getvalue()
    if f.name.lower().endswith(".pdf"):
        try:
            import io
            from pypdf import PdfReader
            ss.doc_text = "\n".join((pg.extract_text() or "") for pg in PdfReader(io.BytesIO(data)).pages)
        except Exception as e:  # pypdf 미설치 또는 스캔본
            ss.doc_text = ""
            ss.an_error = f"PDF에서 글자를 읽지 못했어요 ({e}). 텍스트를 복사해 붙여넣어 주세요."
            return
    else:
        for enc in ("utf-8", "cp949"):
            try:
                ss.doc_text = data.decode(enc)
                break
            except UnicodeDecodeError:
                continue
    ss.pop("analysis", None)


def run_analysis():
    ss.an_error = ""
    text = (ss.get("doc_text") or "").strip()
    if len(text) < 30:
        ss.an_error = "분석할 문서 내용을 넣어주세요."
        return
    call = get_llm()
    if call is None:
        ss.an_error = "AI API 키가 없어요. 아래 'AI 연결 설정'에서 키를 넣거나 Secrets를 설정해 주세요."
        return
    try:
        ex = A.extract(text, call)
    except Exception as e:
        ss.an_error = f"AI 분석에 실패했어요: {e}"
        return
    prod = next(p for p in P if p["id"] == ss.an_pid)
    ss.analysis = {"pid": ss.an_pid, "ex": ex, "rows": A.compare(prod.get("profile", {}), ex)}


def approve_selected():
    a = ss.get("analysis")
    if not a:
        return
    picked = [r for r in a["rows"] if ss.get(f"ok_{a['pid']}_{r['key']}")]
    if not picked:
        ss.an_error = "승인할 항목을 하나 이상 체크해 주세요."
        return
    for r in picked:
        ss.products, log = A.apply_change(ss.products, a["pid"], r["key"], r["_new"], ss.get("approver", ""))
        ss.audit.append(log)
    ss.approved_msg = f"{len(picked)}개 항목을 반영했어요. 추천 결과에 바로 적용돼요. '변경 이력' 탭에서 확인할 수 있어요."
    ss.pop("analysis", None)


def tab_analyzer():
    st.markdown("금융회사의 상품설명서나 공지를 넣으면 AI가 핵심 조건을 뽑아 **현재 DB와 비교**해요. "
                "바뀐 항목은 근거 문장과 함께 보여주고, **관리자가 체크해서 승인한 항목만** 반영돼요.")
    provider, key, model = ai_config()
    if key:
        st.success(f"AI 연결됨: {provider} · {model or llm.DEFAULT_MODELS.get(provider, '')}")
    else:
        st.warning("AI API 키가 없어요. 아래 'AI 연결 설정'을 열어 키를 넣어주세요.")
    with st.expander("AI 연결 설정"):
        st.caption("배포할 때는 Streamlit Secrets에 넣는 걸 권장해요(README 참고). 여기 넣은 키는 지금 접속한 화면에서만 쓰여요.")
        for w, saved, default in (("w_provider", "ui_provider", "gemini"), ("w_api_key", "ui_api_key", ""),
                                  ("w_model", "ui_model", "")):
            if w not in ss:
                ss[w] = ss.get(saved, default)
        st.selectbox("AI 서비스", ["gemini", "openai", "anthropic"], key="w_provider", on_change=save_ai_settings)
        st.text_input("API 키", type="password", key="w_api_key", on_change=save_ai_settings)
        st.text_input("모델 이름 (비우면 기본값)", key="w_model", on_change=save_ai_settings,
                      placeholder=", ".join(f"{k}: {v}" for k, v in llm.DEFAULT_MODELS.items()))

    if ss.get("approved_msg"):
        st.success(ss.pop("approved_msg"))

    st.markdown("##### 1. 비교할 상품")
    names = {p["id"]: p["name"] for p in P}
    ss.setdefault("an_pid", "hana_life")
    st.selectbox("상품", list(names), format_func=names.get, key="an_pid", label_visibility="collapsed")

    st.markdown("##### 2. 문서 넣기")
    st.caption("시연용 예시 문서 (실제 조건이 아닌 가상 문서예요)")
    for name in SAMPLES:
        st.button(name, key=f"sample_{name}", on_click=load_sample, args=(name,))
    st.file_uploader("파일 올리기 (txt, pdf)", type=["txt", "pdf"], key="doc_file", on_change=load_upload)
    st.text_area("또는 문서 내용을 붙여넣기", key="doc_text", height=220)

    st.button("AI로 분석하기", type="primary", on_click=run_analysis)
    if ss.get("an_error"):
        st.error(ss.an_error)

    a = ss.get("analysis")
    if not a:
        return
    ex, rows = a["ex"], a["rows"]
    st.markdown("##### 3. 분석 결과")
    if ex.get("product_name"):
        st.caption(f"AI가 읽은 상품명: {ex['product_name']}")
        if names[a["pid"]].replace(" ", "")[:4] not in ex["product_name"].replace(" ", ""):
            st.warning("문서의 상품명이 선택한 상품과 달라 보여요. 비교할 상품이 맞는지 확인하세요.")
    if ex.get("notes"):
        st.info(f"AI 메모: {ex['notes']}")
    cnt = {s: sum(r["상태"] == s for r in rows) for s in ("변경", "새로 확인", "같음", "문서에 없음")}
    st.markdown(" · ".join(f"**{k}** {v}개" for k, v in cnt.items()))
    st.dataframe([{k: r[k] for k in ("항목", "현재 DB", "AI 추출", "상태", "근거 문장", "주의")} for r in rows],
                 use_container_width=True, hide_index=True)

    cands = [r for r in rows if r["상태"] in ("변경", "새로 확인")]
    st.markdown("##### 4. 검토하고 승인하기")
    if not cands:
        st.success("DB와 다른 항목이 없어요. 반영할 내용이 없습니다.")
        return
    st.caption("근거 문장을 원문과 대조한 뒤, 맞는 항목만 체크하세요. 주의 표시가 있는 항목은 특히 꼼꼼히 확인하세요.")
    for r in cands:
        with st.container(border=True):
            st.checkbox(f"[{r['상태']}] {r['항목']}: {r['현재 DB']} → {r['AI 추출']}", key=f"ok_{a['pid']}_{r['key']}")
            if r["근거 문장"]:
                st.markdown(f"> {r['근거 문장']}")
            if r["주의"]:
                st.warning(f"주의: {r['주의']}")
            st.caption(f"영향 질문: {r['영향 질문']} · 영향 범위: {r['영향 범위']}")
    st.text_input("승인자 이름", key="approver", placeholder="예: 관리자 홍길동")
    st.button("체크한 항목 승인하고 반영", type="primary", on_click=approve_selected)


def reset_db():
    ss.products, ss.audit = E.load_products(), []
    ss.pop("analysis", None)


def tab_audit():
    st.markdown("누가 언제 어떤 변경을 승인했는지 기록해요. 질문이나 선택지까지 바꿔야 하는 변경은 '후속 조치'에 표시돼요.")
    if not ss.audit:
        st.info("아직 승인된 변경이 없어요. 'AI 상품설명서 분석기' 탭에서 시연용 문서로 해보세요.")
    else:
        st.dataframe(ss.audit, use_container_width=True, hide_index=True)
        need = [x for x in ss.audit if x["후속 조치"].startswith("질문 수정 필요")]
        if need:
            st.warning("질문 수정이 필요한 변경이 있어요: " + ", ".join(f"{x['상품']} {x['항목']}" for x in need))
    st.markdown("이 화면의 변경은 지금 접속한 화면에만 적용돼요. 영구 반영하려면 아래 파일을 내려받아 "
                "저장소의 `data/products.json`을 바꾸세요.")
    st.download_button("승인 반영된 products.json 내려받기", A.export_products_json(ss.products),
                       file_name="products.json", mime="application/json")
    st.button("DB를 처음 상태로 되돌리기", on_click=reset_db)


# ---------- 사이드바 ----------
with st.sidebar:
    mode = st.radio("화면", ["추천받기", "용어 물어보기", "상품 DB (관리자)"])
    st.divider()
    st.markdown("**발표용 예시 인물**")
    st.caption("누르면 답이 채워지고 결과로 바로 이동해요.")
    for name in PRESETS:
        st.button(name, key=f"preset_{name}", on_click=load_preset, args=(name,))

if mode == "상품 DB (관리자)":
    page_admin()
elif mode == "용어 물어보기":
    st.title("용어 물어보기")
    helper_box("page")
    st.caption(DISCLAIMER)
elif ss.cur == "intro":
    page_intro()
elif ss.cur == "result":
    page_result()
else:
    q = QMAP.get(ss.cur)
    if q is None or q["id"] not in visible_ids():
        ss.cur = "result"
        st.rerun()
    elif q["type"] == "age":
        page_age(q)
    elif q["type"] == "number":
        page_number(q)
    else:
        page_choice(q)
