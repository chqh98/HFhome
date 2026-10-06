"""가족 공유 기능: 결과를 링크로 공유(복원), 가족 리포트(HTML) 만들기.

링크에는 이름·주소 같은 개인정보 없이 질문 답변과 시뮬레이션 가정만 담는다.
"""
from __future__ import annotations

import base64
import html
import json
from datetime import date

import engine as E


def encode_share(answers: dict, sim: dict) -> str:
    raw = json.dumps({"a": answers, "s": sim}, ensure_ascii=False, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")


def decode_share(code: str) -> tuple[dict, dict] | None:
    try:
        pad = "=" * (-len(code) % 4)
        data = json.loads(base64.urlsafe_b64decode(code + pad).decode("utf-8"))
        answers = {k: v for k, v in data.get("a", {}).items() if isinstance(k, str)}
        sim = {k: float(v) for k, v in data.get("s", {}).items() if k in E.SIM_DEFAULTS}
        return answers, sim
    except Exception:
        return None


DISCUSS = [
    "부모님 집을 꼭 물려받아야 하는 이유가 있나요? 아니면 부모님의 편안한 노후가 더 중요한가요?",
    "주택연금을 받지 않는다면, 부모님 생활비는 누가 얼마나 보탤 수 있나요?",
    "부모님이 앞으로 10년 안에 이사하거나 요양시설로 옮길 계획이 있나요?",
    "평생 받는 방식과 기간을 정해 더 받는 방식 중 무엇이 부모님 생활에 맞을까요?",
]


def message_text(link: str, est: dict | None, n_ok: int) -> str:
    lines = ["[우리 집 연금 찾기] 부모님 집으로 받을 수 있는 연금을 알아봤어요."]
    lines.append(f"- 가입할 수 있는 상품: {n_ok}개")
    if est:
        lines.append(f"- HF 주택연금(평생 정액형) 예상: 매달 약 {est['amount']:,.1f}만 원")
    lines.append("- 나중에 자녀에게 남는 금액도 같이 계산해 뒀어요. 함께 보고 이야기해요.")
    lines.append(link)
    return "\n".join(lines)


def _rows_table(rows: list[dict]) -> str:
    pick = [r for r in rows if r["year"] in (0, 5, 10, 15, 20, 25, 30)]
    tr = "".join(
        f"<tr><td>{r['year']}년 뒤<br>{r['age']}세</td><td>{r['house']:.2f}</td><td>{r['balance']:.2f}</td>"
        f"<td><b>{r['inherit_joined']:.2f}</b>{' *' if r['nonrecourse_used'] else ''}</td>"
        f"<td>{r['paid']:.2f}</td><td>{r['inherit_child_support']:.2f}</td></tr>" for r in pick)
    return ("<table><thead><tr><th>시점</th><th>집값</th><th>갚을 돈</th><th>가입 시 남는 돈</th>"
            "<th>받은 생활비</th><th>미가입·자녀 지원 시</th></tr></thead>"
            f"<tbody>{tr}</tbody></table>")


def build_report(answers: dict, res: dict, est: dict | None, rows: list[dict] | None, sim: dict,
                 answer_lines: list[str]) -> str:
    esc = html.escape
    ok = "".join(f"<li><b>{esc(v.product['name'])}</b> ({esc(v.product['org'])})<br>"
                 f"<span class='m'>{esc(v.product.get('summary', ''))}</span></li>" for v in res[E.OK])
    chk = "".join(f"<li><b>{esc(v.product['name'])}</b> — {esc('; '.join(v.reasons))}</li>" for v in res[E.CHECK])
    est_html = ""
    if est:
        est_html = (f"<div class='big'>HF 주택연금(평생 정액형) 예상 월지급금: 약 {est['amount']:,.1f}만 원</div>"
                    f"<p class='m'>HF {est['date']} 월지급금 예시표 기준 추정 · 나이가 적은 분 {est['age']}세 · "
                    f"시세 {est['price']:g}억 원. 실제 금액은 HF 평가에 따라 달라요.</p>")
    sim_html = ""
    if rows:
        ins = E.sim_insight(rows)
        cross = (f"<p>{ins['cross_year']}년 뒤({ins['cross_age']}세)부터는 대출잔액이 집값보다 커지지만, "
                 "HF 주택연금은 <b>비소구</b>라 넘는 금액을 자녀에게 청구하지 않아요 (표의 *).</p>"
                 if ins["cross_year"] is not None else
                 "<p>계산 기간 동안 집값이 대출잔액보다 커서, 정산 후 남는 금액은 자녀에게 상속돼요.</p>")
        sim_html = (
            "<h2>나중에 자녀에게 남는 금액 (단위: 억 원)</h2>" + cross + _rows_table(rows) +
            "<p class='m'>갚을 돈: 받은 연금 + 이자 + 보증료. 가입 시 남는 돈: 집값 − 갚을 돈. "
            "미가입·자녀 지원 시: 주택연금 대신 자녀가 같은 생활비를 드렸을 때 집값 − 자녀가 드린 돈.</p>" +
            f"<p class='m'>가정: 집값 연 {sim['house_growth']}% 상승, 대출금리 연 {sim['rate']}%, "
            f"초기보증료 {sim['fee_initial']}%, 연보증료 {sim['fee_annual']}% (2026.3.1 기준), 이자는 월 복리로 대출잔액에 더해짐. "
            "가정이 바뀌면 결과도 달라지는 참고용 계산이에요.</p>"
            "<p>주택연금은 이자와 보증료만큼 남는 금액이 줄어드는 대신, 부모님이 자녀 도움 없이 생활비를 마련해요. "
            "가입하지 않으면 집은 그대로 남지만, 그동안의 생활비를 가족이 함께 고민해야 해요.</p>")
    disc = "".join(f"<li>{esc(q)}</li>" for q in DISCUSS)
    ans = "".join(f"<li>{esc(a)}</li>" for a in answer_lines)
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>우리 집 연금 가족 리포트</title>
<style>
body{{font-family:"Apple SD Gothic Neo","Malgun Gothic",sans-serif;max-width:760px;margin:0 auto;padding:24px 16px;
color:#1d2a2a;font-size:17px;line-height:1.7;background:#fff}}
h1{{font-size:28px;margin:0 0 4px}} h2{{font-size:21px;margin-top:32px;border-top:1px solid #d9dfdc;padding-top:16px}}
.m{{color:#5d6b69;font-size:15px}} .big{{font-size:22px;font-weight:700;color:#1f6b5c;margin:8px 0}}
table{{border-collapse:collapse;width:100%;font-size:14px;margin:8px 0}} th,td{{border:1px solid #d9dfdc;padding:6px 8px;text-align:right}}
th{{background:#e3efeb}} td:first-child,th:first-child{{text-align:left}}
.box{{background:#f6ebdc;border-radius:8px;padding:12px 16px}}
</style></head><body>
<h1>우리 집 연금 가족 리포트</h1>
<p class="m">{date.today():%Y년 %m월 %d일} 작성 · 우리 집 연금 찾기</p>
<h2>입력한 내용</h2><ul>{ans}</ul>
<h2>가입할 수 있는 상품</h2><ul>{ok or '<li>없음</li>'}</ul>
{('<h2>확인이 필요한 상품</h2><ul>' + chk + '</ul>') if chk else ''}
{est_html}
{sim_html}
<h2>가족이 함께 이야기해 볼 질문</h2><div class="box"><ol>{disc}</ol></div>
<p class="m">이 리포트는 입력한 조건에 해당하는 상품 정보를 안내할 뿐, 특정 상품의 가입을 권유하지 않습니다.
실제 가입 가능 여부와 금액은 한국주택금융공사(☎1688-8114)와 각 금융회사에서 확인하세요.</p>
</body></html>"""
