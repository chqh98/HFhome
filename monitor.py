"""상품 조건 변경 자동 감시.

흐름:  공식 URL 수집 → 본문 텍스트 추출 → (이전과 같으면 종료) → AI로 핵심 항목 추출 → 기존 DB와 비교
       → 변경 발견 시 AI 변경 요약 → '승인 대기' 알림 생성 → 관리자 승인 → DB 반영(ai_tools.apply_change)

원칙
- robots.txt가 막은 주소는 수집하지 않는다.
- 페이지 전체의 사소한 변화(배너, 날짜 등)로 매번 AI를 부르지 않도록, 본문 지문(해시)이 바뀐 경우에만 AI 추출을 한다.
- AI가 뽑은 값이 DB와 실제로 다를 때만 알림을 만든다. 반영은 항상 사람이 승인해야 한다.
"""
from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.request
import urllib.robotparser
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

import ai_tools as A

DATA = Path(__file__).parent / "data"
SNAP_DIR = DATA / "snapshots"
ALERTS = DATA / "alerts.json"
UA = "Mozilla/5.0 (compatible; JutaekPensionMonitor/1.0; +https://github.com)"

STOP_WORDS = ["판매 종료", "판매종료", "판매 중단", "판매중단", "신규 판매를 종료", "신규판매 종료", "취급 중단"]


# ---------- 감시 대상 ----------
def load_sources() -> list[dict]:
    data = json.loads((DATA / "sources.json").read_text(encoding="utf-8"))["sources"]
    for i, s in enumerate(data, 1):
        s.setdefault("id", f"src{i:02d}")
        url = s.get("watch_url") or s.get("page_url") or ""
        s["url"] = url
        auto = s.get("auto", "")
        s["mode"] = "auto" if auto.startswith("가능") and "API" not in auto and url.startswith("http") else "manual"
        # 금리·기타 탭처럼 보조 페이지는 '참고' 등급으로 알린다
        s["priority"] = "참고" if "탭" in s.get("product", "") else "중요"
    return data


# ---------- 수집 ----------
def robots_allowed(url: str, timeout: int = 10) -> tuple[bool, str]:
    u = urlparse(url)
    rp = urllib.robotparser.RobotFileParser()
    robots = f"{u.scheme}://{u.netloc}/robots.txt"
    try:
        req = urllib.request.Request(robots, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            rp.parse(r.read().decode("utf-8", "ignore").splitlines())
    except urllib.error.HTTPError as e:
        if 400 <= e.code < 500:      # robots.txt가 없으면 수집 허용이 관례
            return True, "robots.txt 없음"
        return False, f"robots.txt 확인 실패({e.code})"
    except Exception as e:           # 확인할 수 없으면 수집하지 않는다 (보수적으로)
        return False, f"robots.txt 확인 실패({type(e).__name__})"
    ok = rp.can_fetch(UA, url)
    return ok, "허용" if ok else "robots.txt가 수집을 막음"


def _decode(raw: bytes, ctype: str) -> str:
    m = re.search(r"charset=([\w-]+)", ctype or "", re.I) or re.search(rb'charset=["\']?([\w-]+)', raw[:3000], re.I)
    encs = []
    if m:
        encs.append(m.group(1).decode() if isinstance(m.group(1), bytes) else m.group(1))
    encs += ["utf-8", "cp949", "euc-kr"]
    for e in encs:
        try:
            return raw.decode(e)
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("utf-8", "ignore")


def fetch(url: str, timeout: int = 20) -> dict:
    """{'status': HTTP 코드 또는 None, 'html': str, 'error': str}"""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return {"status": r.status, "html": _decode(r.read(), r.headers.get("Content-Type", "")), "error": ""}
    except urllib.error.HTTPError as e:
        return {"status": e.code, "html": "", "error": f"HTTP {e.code}"}
    except Exception as e:
        return {"status": None, "html": "", "error": f"{type(e).__name__}: {e}"}


class _Text(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "head"}
    BLOCK = {"p", "div", "li", "tr", "br", "h1", "h2", "h3", "h4", "h5", "td", "th", "dt", "dd", "section", "table"}

    def __init__(self):
        super().__init__()
        self.out, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        elif tag in ("td", "th"):
            self.out.append(" | ")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def html_to_text(html: str) -> str:
    p = _Text()
    p.feed(html)
    text = "".join(p.out)
    lines = [re.sub(r"[ \t ]+", " ", ln).strip(" |") for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)


# ---------- 지문·신호 ----------
def fingerprint(text: str) -> str:
    # 접속 시각·조회수처럼 매번 바뀌는 숫자 줄은 빼고 지문을 만든다
    stable = "\n".join(ln for ln in text.splitlines() if not re.search(r"\d{1,2}:\d{2}(:\d{2})?|조회수|방문", ln))
    return hashlib.sha256(stable.encode("utf-8")).hexdigest()[:16]


def signals(text: str) -> dict:
    """변경 신호: 준법감시인 심의필 번호, 판매 중단 문구."""
    review = sorted({re.sub(r"\s+", " ", m).strip() for m in re.findall(r"심의필[^\n]{0,40}", text)})[:5]
    stop = [w for w in STOP_WORDS if w in text]
    return {"review_no": review, "stop_words": stop}


def load_snapshot(sid: str) -> dict | None:
    f = SNAP_DIR / f"{sid}.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


def save_snapshot(sid: str, snap: dict) -> None:
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    (SNAP_DIR / f"{sid}.json").write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------- AI 변경 요약 ----------
SUMMARY_SYSTEM = """너는 금융상품 관리자에게 상품 조건 변경을 보고하는 도우미다.
주어진 변경 항목만 근거로 2~3문장으로 요약한다. 없는 내용을 추측하지 않는다.
첫 문장에 무엇이 어떻게 바뀌었는지, 다음 문장에 서비스의 어떤 질문·판정에 영향이 있는지 쓴다."""


def summarize(product_name: str, rows: list[dict], sig_note: str, llm) -> str:
    lines = [f"- {r['항목']}: {r['현재 DB']} → {r['AI 추출']} (근거: {r['근거 문장'] or '없음'}; 영향: {r['영향 질문']}/{r['영향 범위']})"
             for r in rows]
    fallback = f"{product_name}: " + ", ".join(f"{r['항목']} {r['현재 DB']}→{r['AI 추출']}" for r in rows)
    if sig_note:
        fallback += f" ({sig_note})"
    if llm is None:
        return fallback
    try:
        return llm(SUMMARY_SYSTEM, f"상품: {product_name}\n{sig_note}\n변경 항목:\n" + "\n".join(lines)).strip()
    except Exception:
        return fallback


# ---------- 점검 1건 ----------
def check_source(src: dict, products: list[dict], llm, *, snapshot: dict | None = None,
                 text_override: str | None = None, check_robots: bool = True) -> dict:
    """감시 대상 1곳을 점검한다. 결과: {status, message, snapshot, alert}
    status: skipped | error | unchanged | changed_no_diff | alert | baseline"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    res = {"source_id": src["id"], "product": src["product"], "time": now, "snapshot": None, "alert": None}

    if text_override is None:
        if src.get("mode") != "auto":
            return {**res, "status": "skipped", "message": "관리자 정기 확인 대상 (자동 수집 안 함)"}
        if check_robots:
            ok, why = robots_allowed(src["url"])
            if not ok:
                return {**res, "status": "skipped", "message": why}
        got = fetch(src["url"])
        if got["status"] in (404, 410):
            text, http_gone = "", True
        elif got["error"]:
            return {**res, "status": "error", "message": f"수집 실패: {got['error']}"}
        else:
            text, http_gone = html_to_text(got["html"]), False
    else:
        text, http_gone = text_override, False

    sig = signals(text)
    fp = fingerprint(text) if text else "gone"
    snap = {"fingerprint": fp, "signals": sig, "checked_at": now, "url": src.get("url", ""), "length": len(text)}
    res["snapshot"] = snap

    if snapshot and snapshot.get("fingerprint") == fp:
        return {**res, "status": "unchanged", "message": "변경 없음 (본문 지문 동일, AI 호출 안 함)"}
    if not http_gone and len(text) < 200:
        return {**res, "status": "error", "message": "본문이 거의 비어 있음 (화면을 스크립트로 그리는 페이지일 수 있음)"}

    sig_notes = []
    if snapshot and snapshot.get("signals", {}).get("review_no") != sig["review_no"] and sig["review_no"]:
        sig_notes.append(f"심의필 번호 변경: {snapshot['signals'].get('review_no')} → {sig['review_no']}")
    if sig["stop_words"]:
        sig_notes.append(f"판매 중단 문구 발견: {', '.join(sig['stop_words'])}")
    if http_gone:
        sig_notes.append("상품 페이지가 사라짐 (HTTP 404/410)")

    prod = next((p for p in products if p["id"] == src.get("product_id")), None)
    rows = []
    if prod is None:
        # HF처럼 여러 상품이 걸린 페이지: 지문 변화만 알린다
        if snapshot:
            return {**res, "status": "alert", "message": "본문 변경 감지 (상품 연결 없음)",
                    "alert": _alert(src, None, [], f"{src['product']} 페이지 내용이 바뀌었어요. 관리자 확인이 필요해요.",
                                    sig_notes, "참고", now)}
        return {**res, "status": "baseline", "message": "첫 점검: 기준 저장"}

    if http_gone:
        rows.append({"key": "sale_status", "항목": "판매 상태", "현재 DB": prod.get("sale_status", "-"), "AI 추출": "판매 종료",
                     "상태": "변경", "근거 문장": "상품 페이지가 사라짐 (HTTP 404/410)", "주의": "페이지 이동일 수도 있어 확인 필요",
                     "영향 질문": "-", "영향 범위": A.FIELDS["sale_status"][4], "_new": "판매 종료"})
    elif llm is not None:
        try:
            ex = A.extract(text, llm)
        except Exception as e:
            return {**res, "status": "error", "message": f"AI 추출 실패: {e}"}
        rows = [r for r in A.compare(prod.get("profile", {}), ex) if r["상태"] in ("변경", "새로 확인")]
    elif sig_notes or snapshot:
        sig_notes.append("AI 키가 없어 항목 비교는 하지 못함")

    if not rows and not sig_notes:
        status = "baseline" if snapshot is None else "changed_no_diff"
        msg = "첫 점검: 기준 저장, DB와 다른 항목 없음" if snapshot is None else "본문은 바뀌었지만 핵심 조건은 그대로 (알림 안 함)"
        return {**res, "status": status, "message": msg}

    level = "중요" if any(r["상태"] == "변경" for r in rows) or sig["stop_words"] or http_gone else src.get("priority", "참고")
    if src.get("priority") == "참고" and not sig["stop_words"]:
        level = "참고"
    summary = summarize(prod["name"], rows, " / ".join(sig_notes), llm) if rows else \
        f"{prod['name']}: " + " / ".join(sig_notes)
    return {**res, "status": "alert", "message": f"변경 {len(rows)}건 발견", "alert": _alert(src, prod, rows, summary, sig_notes, level, now)}


def _alert(src, prod, rows, summary, sig_notes, level, now) -> dict:
    aid = hashlib.md5(f"{src['id']}{now}{summary}".encode()).hexdigest()[:8]
    return {"id": aid, "created": now, "source_id": src["id"], "product_id": prod["id"] if prod else "",
            "product_name": prod["name"] if prod else src["product"], "url": src.get("url", ""), "level": level,
            "status": "승인 대기", "summary": summary, "signals": sig_notes,
            "rows": [{k: r[k] for k in ("key", "항목", "현재 DB", "AI 추출", "상태", "근거 문장", "주의", "영향 질문", "영향 범위", "_new")}
                     for r in rows]}


# ---------- 전체 점검 ----------
def load_alerts() -> list[dict]:
    return json.loads(ALERTS.read_text(encoding="utf-8")) if ALERTS.exists() else []


def save_alerts(alerts: list[dict]) -> None:
    ALERTS.write_text(json.dumps(alerts, ensure_ascii=False, indent=2), encoding="utf-8")


def run_all(products: list[dict], llm, *, persist: bool = True, check_robots: bool = True) -> list[dict]:
    results = []
    for src in load_sources():
        snap = load_snapshot(src["id"])
        r = check_source(src, products, llm, snapshot=snap, check_robots=check_robots)
        if persist and r["snapshot"] and r["status"] != "error":
            save_snapshot(src["id"], r["snapshot"])
        results.append(r)
    if persist:
        new = [r["alert"] for r in results if r.get("alert")]
        if new:
            save_alerts(load_alerts() + new)
    return results


def report_markdown(results: list[dict]) -> str:
    alerts = [r["alert"] for r in results if r.get("alert")]
    lines = [f"## 상품 조건 변경 감시 결과 ({datetime.now():%Y-%m-%d %H:%M})", "",
             f"새 알림 **{len(alerts)}건**. 앱의 관리자 화면 → '변경 알림함'에서 승인해 주세요.", ""]
    for a in alerts:
        lines += [f"### [{a['level']}] {a['product_name']}", a["summary"], ""]
        for r in a["rows"]:
            lines.append(f"- {r['항목']}: {r['현재 DB']} → **{r['AI 추출']}** (근거: {r['근거 문장'] or '-'})")
        lines += [f"- 출처: {a['url']}", ""]
    lines += ["### 전체 점검 내역", "| 대상 | 결과 |", "|---|---|"]
    lines += [f"| {r['product']} | {r['message']} |" for r in results]
    return "\n".join(lines)


def notify_webhook(url: str, text: str) -> str:
    """슬랙·디스코드 웹훅으로 알림. 둘 다 받을 수 있게 text/content를 함께 보낸다."""
    body = json.dumps({"text": text[:3500], "content": text[:1900]}).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return f"알림 전송 ({r.status})"
    except Exception as e:
        return f"알림 전송 실패: {e}"
