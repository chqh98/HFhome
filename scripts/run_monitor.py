"""상품 조건 변경 감시를 한 번 실행한다. (정기 실행용)

  python scripts/run_monitor.py

필요한 환경변수 (GitHub Actions에서는 저장소 Secrets로 넣는다)
  LLM_PROVIDER, LLM_API_KEY, (선택) LLM_MODEL   : AI 추출·요약
  NOTIFY_WEBHOOK_URL (선택)                     : 슬랙/디스코드로 알림
실행 결과
  data/snapshots/*.json  각 페이지의 지문(다음 비교 기준)
  data/alerts.json       '승인 대기' 알림 (앱의 변경 알림함에 표시)
  monitor_report.md      이번 실행 보고서 (새 알림이 있을 때 GitHub 이슈 본문으로 사용)
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import engine as E  # noqa: E402
import llm as L     # noqa: E402
import monitor as M  # noqa: E402


def make_llm():
    key = os.environ.get("LLM_API_KEY", "")
    if not key:
        print("! LLM_API_KEY가 없어 AI 비교 없이 페이지 변경만 확인합니다.")
        return None
    provider, model = os.environ.get("LLM_PROVIDER", "gemini"), os.environ.get("LLM_MODEL") or None
    return lambda s, u, want_json=False: L.chat(s, u, provider=provider, api_key=key, model=model, want_json=want_json)


def main():
    results = M.run_all(E.load_products(), make_llm())
    for r in results:
        print(f"[{r['status']:<15}] {r['product']}: {r['message']}")
    report = M.report_markdown(results)
    new = [r for r in results if r.get("alert")]
    out = ROOT / "monitor_report.md"
    if new:
        out.write_text(report, encoding="utf-8")
        hook = os.environ.get("NOTIFY_WEBHOOK_URL")
        if hook:
            print(M.notify_webhook(hook, report))
    elif out.exists():
        out.unlink()
    print(f"\n새 알림 {len(new)}건")


if __name__ == "__main__":
    main()
