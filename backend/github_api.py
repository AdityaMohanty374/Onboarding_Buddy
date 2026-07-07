import requests
from config import settings

GITHUB_API = "https://api.github.com"


def _headers() -> dict:
    headers = {"Accept": "application/vnd.github+json"}
    if settings.GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {settings.GITHUB_TOKEN}"
    return headers


def fetch_pull_or_issue(owner: str, repo: str, number: int) -> dict | None:
    """
    GitHub's /issues/{n} endpoint returns both plain issues and PRs (PRs get
    an extra `pull_request` key), so one call covers both cases.
    """
    url = f"{GITHUB_API}/repos/{owner}/{repo}/issues/{number}"
    try:
        res = requests.get(url, headers=_headers(), timeout=8)
    except requests.RequestException:
        return None
    if not res.ok:
        return None
    data = res.json()
    return {
        "number": data.get("number"),
        "title": data.get("title", ""),
        "body": (data.get("body") or "")[:2000],
        "is_pr": "pull_request" in data,
        "url": data.get("html_url", ""),
        "labels": [l.get("name") for l in data.get("labels", [])],
    }
