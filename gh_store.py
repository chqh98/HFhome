"""승인 결과를 GitHub 저장소 파일에 바로 저장한다 (선택 기능).

Streamlit Secrets에 아래 두 값을 넣으면, 관리자가 앱에서 승인할 때
data/products.json 과 data/alerts.json 이 저장소에 커밋되어 영구 반영된다.
  GITHUB_TOKEN = "github_pat_..."   (이 저장소의 Contents 읽기/쓰기 권한만 준 토큰)
  GITHUB_REPO  = "아이디/저장소이름"
"""
from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request


def put_file(token: str, repo: str, path: str, content: str, message: str, branch: str = "main") -> str:
    api = f"https://api.github.com/repos/{repo}/contents/{path}"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
               "User-Agent": "jutaek-app"}
    sha = None
    try:
        with urllib.request.urlopen(urllib.request.Request(f"{api}?ref={branch}", headers=headers), timeout=15) as r:
            sha = json.loads(r.read())["sha"]
    except urllib.error.HTTPError as e:
        if e.code != 404:
            return f"{path} 저장 실패 ({e.code})"
    body = {"message": message, "branch": branch,
            "content": base64.b64encode(content.encode("utf-8")).decode("ascii")}
    if sha:
        body["sha"] = sha
    req = urllib.request.Request(api, data=json.dumps(body).encode("utf-8"), headers=headers, method="PUT")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return f"{path} 저장 완료"
    except urllib.error.HTTPError as e:
        return f"{path} 저장 실패 ({e.code}: {e.read().decode('utf-8', 'ignore')[:120]})"
    except Exception as e:
        return f"{path} 저장 실패 ({e})"
