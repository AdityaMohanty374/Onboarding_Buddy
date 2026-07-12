import base64
import json
import os

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import git_tools
import github_api
import prompts
import ratelimit
from llm import stream_response
from config import settings

app = FastAPI(title="Onboarding Buddy")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Evidence", "X-Access-Mode"],
)

# in-memory session state — this is a local dev tool, not a multi-user service
STATE = {"repo_path": None, "repo_name": None, "owner_repo": None}


class LoadRepoRequest(BaseModel):
    source: str  # local path or git URL


class AskRequest(BaseModel):
    question: str
    file_path: str | None = None
    line: int | None = None


@app.get("/")
def home():
    return {"status": "running", "message": "Onboarding Buddy API"}


@app.get("/repo/debug")
def repo_debug(request: Request):
    """
    Diagnostic info for whatever repo is currently loaded — no shell access
    needed, just open this URL in a browser. Exists specifically because
    Render's free tier doesn't give shell access, so this is the fastest way
    to see what actually happened during a clone.

    Gated behind the developer key: it reveals internal server filesystem
    paths and git state, which is exactly the kind of thing that shouldn't
    be world-readable on a public deployment just because the source code
    is open on GitHub — no reason to hand that to anyone with the URL.
    """
    if not ratelimit.is_developer(request):
        raise HTTPException(
            status_code=403,
            detail="This endpoint requires a developer key (X-Dev-Key header).",
        )
    if not STATE["repo_path"]:
        raise HTTPException(status_code=400, detail="No repo loaded yet — load one first.")

    repo_path = STATE["repo_path"]
    info: dict = {"repo_path": repo_path, "path_exists": os.path.isdir(repo_path)}

    if not info["path_exists"]:
        return info

    info["has_git_dir"] = os.path.isdir(os.path.join(repo_path, ".git"))
    info["is_shallow"] = git_tools._is_shallow(repo_path)
    info["top_level_entries"] = sorted(os.listdir(repo_path))[:30]

    def _safe_run(args):
        try:
            return git_tools._run(args, cwd=repo_path, timeout=15).strip()
        except git_tools.GitError as e:
            return f"ERROR: {e}"

    info["remote_url"] = _safe_run(["git", "config", "--get", "remote.origin.url"])
    info["current_branch"] = _safe_run(["git", "branch", "--show-current"])
    info["head_commit"] = _safe_run(["git", "log", "-1", "--oneline"])
    info["status"] = _safe_run(["git", "status", "--short", "--branch"])
    info["ls_files_count"] = len(_safe_run(["git", "ls-files"]).splitlines())

    return info


@app.post("/repo/load")
def load_repo(req: LoadRepoRequest, request: Request):
    ratelimit.enforce(request, settings.RATE_LIMIT_LOAD_PER_MIN, bucket="load")

    try:
        repo_path = git_tools.load_repo(req.source)
    except git_tools.GitError as e:
        raise HTTPException(status_code=400, detail=str(e))

    remote = git_tools.repo_remote_url(repo_path)
    owner_repo = git_tools.parse_github_owner_repo(remote)
    repo_name = req.source.rstrip("/").split("/")[-1].removesuffix(".git")

    STATE["repo_path"] = repo_path
    STATE["repo_name"] = repo_name
    STATE["owner_repo"] = owner_repo

    files = git_tools.list_tracked_files(repo_path, limit=200)
    return {
        "repo_name": repo_name,
        "github": f"{owner_repo[0]}/{owner_repo[1]}" if owner_repo else None,
        "file_count": len(git_tools.list_tracked_files(repo_path, limit=100000)),
        "sample_files": files,
        "access_mode": "developer" if ratelimit.is_developer(request) else "user",
    }


def _gather_evidence(question: str, file_path: str | None, line: int | None) -> list[dict]:
    repo_path = STATE["repo_path"]
    owner_repo = STATE["owner_repo"]
    entries: list[dict] = []

    if file_path and line:
        hits = [git_tools.SearchHit(file=file_path, line_no=line, line_text="")]
    else:
        hits = git_tools.search_code(repo_path, question, settings.MAX_SEARCH_HITS)

    seen_commits: set[str] = set()
    seen_prs: set[tuple] = set()

    for hit in hits[: settings.MAX_BLAME_COMMITS]:
        snippet = git_tools.read_snippet(repo_path, hit.file, hit.line_no)
        entry = {"file": hit.file, "line_no": hit.line_no, "snippet": snippet, "commits": []}

        # Walk the line's full history, not just its most recent edit — the
        # last commit to touch a line is frequently a cosmetic change
        # (reformatting, a merge, a type hint) that has nothing to do with
        # why the line exists. Surfacing 2-3 commits lets the model see both
        # "what changed most recently" and "why this exists in the first
        # place", instead of only ever citing whichever came last.
        history = git_tools.line_history(repo_path, hit.file, hit.line_no, max_commits=3)

        for commit in history:
            commit_entry = {
                "commit_hash": commit.commit_hash,
                "author": commit.author,
                "date": commit.date,
                "summary": commit.summary,
            }

            if commit.commit_hash and commit.commit_hash not in seen_commits:
                seen_commits.add(commit.commit_hash)
                body = git_tools.commit_body(repo_path, commit.commit_hash)
                commit_entry["commit_body"] = body

                pr_number = git_tools.extract_pr_number(body or commit.summary)
                if pr_number and owner_repo:
                    pr_key = (owner_repo[0], owner_repo[1], pr_number)
                    if pr_key not in seen_prs:
                        seen_prs.add(pr_key)
                        pr = github_api.fetch_pull_or_issue(owner_repo[0], owner_repo[1], pr_number)
                        if pr:
                            commit_entry["pr"] = pr

            entry["commits"].append(commit_entry)

        entries.append(entry)

    return entries


@app.post("/ask")
def ask(req: AskRequest, request: Request):
    ratelimit.enforce(request, settings.RATE_LIMIT_ASK_PER_MIN, bucket="ask")

    if not STATE["repo_path"]:
        raise HTTPException(status_code=400, detail="Load a repository first via /repo/load.")

    evidence_entries = _gather_evidence(req.question, req.file_path, req.line)
    evidence_text = prompts.build_evidence_block(evidence_entries)

    # keep the prompt within budget — trim lowest-ranked evidence blocks first
    # (search_code already returns best-ranked hits first, so popping from the
    # end drops the weakest evidence, not the strongest)
    while len(evidence_text) > settings.MAX_CONTEXT_CHARS and evidence_entries:
        evidence_entries.pop()
        evidence_text = prompts.build_evidence_block(evidence_entries)

    messages = [
        prompts.SYSTEM_PROMPT,
        prompts.build_user_message(req.question, STATE["repo_name"], evidence_text),
    ]

    # Compact evidence summary for the UI's "Evidence" panel — deliberately
    # excludes full snippets/commit bodies (those stay server-side, in the
    # LLM's prompt only) to keep the header small and avoid ever shipping
    # more repo content to the browser than the sidebar's file list already
    # implies is public.
    owner_repo = STATE["owner_repo"]
    summary = []
    for e in evidence_entries:
        item = {"file": e["file"], "line_no": e["line_no"], "commits": []}
        for c in e.get("commits", []):
            commit_item = {
                "hash": c["commit_hash"][:7],
                "author": c["author"],
                "date": c["date"],
                "summary": c["summary"],
                "url": (
                    f"https://github.com/{owner_repo[0]}/{owner_repo[1]}/commit/{c['commit_hash']}"
                    if owner_repo else None
                ),
            }
            if c.get("pr"):
                commit_item["pr"] = {
                    "number": c["pr"]["number"],
                    "title": c["pr"]["title"],
                    "url": c["pr"]["url"],
                    "is_pr": c["pr"]["is_pr"],
                }
            item["commits"].append(commit_item)
        summary.append(item)

    evidence_header = base64.b64encode(json.dumps(summary).encode()).decode()

    def generate():
        yield from stream_response(messages)

    return StreamingResponse(
        generate(),
        media_type="text/plain",
        headers={
            "X-Evidence": evidence_header,
            "X-Access-Mode": "developer" if ratelimit.is_developer(request) else "user",
        },
    )


# Serve the frontend as static files (index.html sits in ../frontend)
app.mount("/", StaticFiles(directory="../frontend", html=True), name="frontend")
