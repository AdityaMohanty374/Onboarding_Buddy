"""
Thin wrappers around the `git` CLI. We shell out instead of using GitPython
so the only runtime dependency is git itself being installed.
"""
import os
import re
import subprocess
import hashlib
from dataclasses import dataclass, field

from config import settings

os.makedirs(settings.WORKSPACE_DIR, exist_ok=True)


class GitError(Exception):
    pass


def _run(args: list[str], cwd: str, timeout: int = 30) -> str:
    try:
        result = subprocess.run(
            args, cwd=cwd, capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        raise GitError(f"Command timed out: {' '.join(args)}")
    if result.returncode != 0:
        raise GitError(result.stderr.strip() or f"Command failed: {' '.join(args)}")
    return result.stdout


def _repo_slug(source: str) -> str:
    """Deterministic, filesystem-safe folder name for a repo path/URL."""
    digest = hashlib.sha1(source.encode()).hexdigest()[:10]
    name = re.sub(r"[^a-zA-Z0-9_-]+", "-", source.rstrip("/").split("/")[-1])
    name = name.removesuffix(".git") or "repo"
    return f"{name}-{digest}"


def load_repo(source: str) -> str:
    """
    Ensure a working copy exists locally and return its path.
    `source` can be a local filesystem path or a git remote URL (https/ssh).
    """
    if os.path.isdir(source):
        if not os.path.isdir(os.path.join(source, ".git")):
            raise GitError(f"{source} is not a git repository (no .git folder).")
        return os.path.abspath(source)

    dest = os.path.join(settings.WORKSPACE_DIR, _repo_slug(source))
    if os.path.isdir(os.path.join(dest, ".git")):
        try:
            _run(["git", "fetch", "--depth", "200", "origin"], cwd=dest, timeout=90)
        except GitError:
            pass  # offline / rate-limited — fall back to whatever we already have
        return dest

    os.makedirs(dest, exist_ok=True)
    _run(["git", "clone", "--depth", "200", source, dest], cwd=settings.WORKSPACE_DIR, timeout=120)
    return dest


def repo_remote_url(repo_path: str) -> str | None:
    try:
        out = _run(["git", "config", "--get", "remote.origin.url"], cwd=repo_path)
        return out.strip() or None
    except GitError:
        return None


def parse_github_owner_repo(remote_url: str | None) -> tuple[str, str] | None:
    if not remote_url:
        return None
    m = re.search(r"github\.com[:/]+([\w.-]+)/([\w.-]+?)(?:\.git)?/?$", remote_url)
    if not m:
        return None
    return m.group(1), m.group(2)


def list_tracked_files(repo_path: str, limit: int = 500) -> list[str]:
    out = _run(["git", "ls-files"], cwd=repo_path)
    files = [f for f in out.splitlines() if f.strip()]
    return files[:limit]


@dataclass
class SearchHit:
    file: str
    line_no: int
    line_text: str

# File types that talk *about* code rather than *being* code. A keyword match
# here is usually someone's prose mentioning a name, not the definition site —
# so we rank these below real source hits instead of treating every hit equally.
_DOC_LIKE_EXTENSIONS = {".md", ".rst", ".txt", ".adoc"}
_DOC_LIKE_BASENAMES = {"changes", "changelog", "history", "news", "authors", "contributors"}

_STOPWORDS = {"the", "why", "does", "this", "work", "way", "what", "how", "and", "for"}

def _extract_terms(query: str) -> list[str]:
    return [t for t in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", query) if t.lower() not in _STOPWORDS]

def _score_hit(hit: "SearchHit", terms: list[str]) -> int:
    """Higher score = more likely to be the actual definition/behavior site,
    rather than an incidental mention (docs, changelogs, comments about it)."""
    score = 0
    ext = os.path.splitext(hit.file)[1].lower()
    base = os.path.splitext(os.path.basename(hit.file))[0].lower()

    if ext in _DOC_LIKE_EXTENSIONS or base in _DOC_LIKE_BASENAMES:
        score -= 5

    for term in terms:
        escaped = re.escape(term)
        # `def term(` / `class Term` — this line *is* the definition.
        if re.search(rf"\b(def|class)\s+{escaped}\b", hit.line_text):
            score += 10
        # `def something_with_term(` — a function whose name contains the term.
        elif re.search(rf"\bdef\s+\w*{escaped}\w*\s*\(", hit.line_text):
            score += 6
        # plain mention of the term anywhere else on the line.
        elif re.search(rf"\b{escaped}\b", hit.line_text, re.IGNORECASE):
            score += 1
    return score

def search_code(repo_path: str, query: str, max_hits: int) -> list[SearchHit]:
    """Keyword search via `git grep` — fast, no index to build, works on any
    commit already checked out. Falls back to per-term OR search if the
    literal phrase has no hits."""
    def _grep(pattern: str) -> list[SearchHit]:
        try:
            out = _run(
                ["git", "grep", "-n", "-i", "-I", "--max-count=3", pattern],
                cwd=repo_path,
            )
        except GitError:
            return []
        hits = []
        for line in out.splitlines():
            parts = line.split(":", 2)
            if len(parts) < 3:
                continue
            file, line_no, text = parts
            try:
                hits.append(SearchHit(file=file, line_no=int(line_no), line_text=text.strip()))
            except ValueError:
                continue
        return hits

    hits = _grep(query)
    if not hits:
        terms = [t for t in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", query) if t.lower() not in
                  {"the", "why", "does", "this", "work", "way", "what", "how", "and", "for"}]
        for term in terms[:4]:
            hits.extend(_grep(term))
            if len(hits) >= max_hits:
                break

    # de-dupe by (file, line_no)
    seen = set()
    unique = []
    for h in hits:
        key = (h.file, h.line_no)
        if key not in seen:
            seen.add(key)
            unique.append(h)
    return unique[:max_hits]


def read_snippet(repo_path: str, file: str, line_no: int, context: int = 6) -> str:
    full_path = os.path.join(repo_path, file)
    try:
        with open(full_path, "r", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return ""
    start = max(0, line_no - 1 - context)
    end = min(len(lines), line_no + context)
    numbered = [f"{i+1:>5} | {lines[i].rstrip()}" for i in range(start, end)]
    return "\n".join(numbered)


@dataclass
class BlameCommit:
    commit_hash: str
    author: str
    date: str
    summary: str
    file: str
    line_no: int


def blame_line(repo_path: str, file: str, line_no: int) -> BlameCommit | None:
    try:
        out = _run(
            ["git", "blame", "-L", f"{line_no},{line_no}", "--porcelain", "--", file],
            cwd=repo_path,
        )
    except GitError:
        return None

    lines = out.splitlines()
    if not lines:
        return None
    commit_hash = lines[0].split(" ")[0]
    author = ""
    date = ""
    for line in lines[1:]:
        if line.startswith("author "):
            author = line.removeprefix("author ").strip()
        elif line.startswith("author-time "):
            import datetime
            ts = int(line.removeprefix("author-time ").strip())
            date = datetime.datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d")
        elif line.startswith("summary "):
            summary = line.removeprefix("summary ").strip()
            return BlameCommit(
                commit_hash=commit_hash, author=author, date=date,
                summary=summary, file=file, line_no=line_no,
            )
    return None


def commit_body(repo_path: str, commit_hash: str) -> str:
    try:
        return _run(
            ["git", "show", "-s", "--format=%B", commit_hash], cwd=repo_path
        ).strip()
    except GitError:
        return ""


def extract_pr_number(commit_message: str) -> int | None:
    m = re.search(r"#(\d+)", commit_message)
    return int(m.group(1)) if m else None
