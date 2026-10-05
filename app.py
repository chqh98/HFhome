"""우리 집 연금 찾기 — 주택연금 맞춤 정보 서비스 (Streamlit 프로토타입)

실행:  streamlit run app.py
"""
import streamlit as st

import engine as E

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
P = E.load_products()
QMAP = {q["id"]: q for q in Q}

PRESETS = {
    "62세 부부 · 아파트 5억 · 대출 있음": dict(age_self=62, age_spouse=59, houses="1", price="le", type="apt", live="yes",
                                     farm="no", basic="no", loan="yes", period="life", lump="no"),
    "51세 조기퇴직 · 공시 9억": dict(age_self=51, age_spouse=50, houses="1", price="le", type="apt", live="yes",
                               job="yes", loan="no", period="term", lump="no"),
    "68세 부부 · 공시 15억 아파트": dict(age_self=68, age_spouse=64, houses="1", price="gt", type="apt", live="yes",
                                  farm="no", own2="yes", loan="no", period="life", lump="yes"),
    "71세 농업인 · 시골 단독주택": dict(age_self=71, age_spouse=None, houses="1", price="le", type="house", live="yes",
                                 farm="yes", basic="yes", cheap="yes", loan="no", period="life", lump="no"),
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


def toggle_guide(qid):
    ss.guide = None if ss.guide == qid else qid


def restart():
    ss.answers, ss.cur, ss.guide = {}, "intro", None
    for k in ("in_age_self", "in_age_spouse"):
        ss.pop(k, None)


def load_preset(name):
    ss.answers = E.clean_answers(Q, dict(PRESETS[name]))
    for k in ("in_age_self", "in_age_spouse"):
        ss.pop(k, None)
    ss.cur, ss.guide = "result", None


def answer_label(qid, value):
    if value == E.UNKNOWN:
        return "잘 모르겠어요 (확인 필요)"
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
    if q.get("allow_unknown", True):
        st.button("? 잘 모르겠어요", key=f"unk_{q['id']}", on_click=toggle_guide, args=(q["id"],))
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
    st.button("← 이전", key=f"back_{q['id']}", on_click=go_back)


# ---------- 화면: 결과 ----------
BADGE = {E.OK: ("b-ok", "가입할 수 있어요"), E.CHECK: ("b-check", "확인이 필요해요"), E.NO: ("b-no", "해당되지 않아요")}


def product_card(v):
    p = v.product
    with st.container(border=True):
        tags = f'<span class="badge {BADGE[v.status][0]}">{BADGE[v.status][1]}</span>'
        if v.preferred and v.status != E.NO:
            tags += ' <span class="badge b-pref">원하시는 지급 방식</span>'
        st.markdown(tags, unsafe_allow_html=True)
        st.markdown(f"### {p['name']}")
        st.markdown(f'<span class="small">{p["org"]} · 정보 확인 {p["last_checked"]}</span>', unsafe_allow_html=True)
        st.markdown(p.get("summary", ""))
        title = {"ok": "이런 조건이 맞아요", "check": "이 부분을 확인해 주세요", "no": "이런 이유로 어려워요"}[v.status]
        st.markdown(f"**{title}**\n" + "\n".join(f"- {r}" for r in v.reasons))
        for t in v.tips:
            st.info(t)
        if v.status != E.NO:
            st.link_button("공식 안내 보기 ↗", p["source"])


def page_result():
    res = E.recommend(P, ss.answers)
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

    for v in res[E.OK] + res[E.CHECK]:
        product_card(v)
    if res[E.NO]:
        with st.expander(f"해당되지 않는 상품 {len(res[E.NO])}개와 그 이유"):
            for v in res[E.NO]:
                product_card(v)

    with st.expander("내가 고른 답 다시 보기"):
        for q in E.visible_questions(Q, ss.answers):
            if q["id"] == "age":
                sp = ss.answers.get("age_spouse")
                val = f"본인 {ss.answers.get('age_self')}세" + (f", 배우자 {sp}세" if sp else "")
            else:
                val = answer_label(q["id"], ss.answers.get(q["id"])) if q["id"] in ss.answers else "-"
            st.markdown(f"- **{q['no']}** {q['text']} → {val}")

    c1, c2 = st.columns(2)
    with c1:
        st.button("← 이전 질문", on_click=go_back)
    with c2:
        st.button("처음부터 다시", on_click=restart)
    st.caption(DISCLAIMER)


# ---------- 화면: 관리자 ----------
def page_admin():
    st.title("상품 DB · 관리자 화면")
    st.markdown("추천은 `data/products.json`의 조건으로만 판정돼요. 변경감지에서 조건이 바뀌면 "
                "이 파일만 고치면 되고, 화면 코드는 건드리지 않아요.")
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


# ---------- 사이드바 ----------
with st.sidebar:
    mode = st.radio("화면", ["추천받기", "상품 DB (관리자)"])
    st.divider()
    st.markdown("**발표용 예시 인물**")
    st.caption("누르면 답이 채워지고 결과로 바로 이동해요.")
    for name in PRESETS:
        st.button(name, key=f"preset_{name}", on_click=load_preset, args=(name,))

if mode == "상품 DB (관리자)":
    page_admin()
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
    else:
        page_choice(q)
