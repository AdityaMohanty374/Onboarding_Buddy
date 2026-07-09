# Onboarding Buddy — Codebase Archaeology

Point it at any git repo and ask "why does this work this way?" — instead of
guessing, it traces the answer through real evidence:

```
your question
   → git grep (find relevant code)
   → git blame (find the commit that last touched it)
   → git show (read the full commit message)
   → GitHub API (fetch the linked PR/issue, if the commit message references one)
   → LLM (answer, citing the commit hash / PR number as evidence)
```

If there's no good evidence, the model is instructed to say so rather than
invent history.

## Setup

```bash
cd backend
pip install -r requirements.txt

export GROQ_API_KEY=your_key_here       # https://console.groq.com or any api key at your convenience
export GITHUB_TOKEN=your_token_here     # optional — raises GitHub's 60/hr
                                         # unauthenticated rate limit to 5000/hr

uvicorn main:app --reload --port 8000
```

Then open **http://localhost:8000** — the FastAPI app serves the frontend
directly, no separate server needed.

## Using it

1. Paste a local path to an already-cloned repo (fastest), or a GitHub URL
   (it'll be shallow-cloned into `/tmp/onboarding-buddy-repos`), and click
   **Load repository**.
2. Ask a question like:
   - "Why does the retry logic wait 3 seconds instead of using exponential backoff?"
   - "Why was this validation moved out of the constructor?"
3. Optionally point it at an exact `file_path` + `line` in the sidebar if you
   already know where the code lives — this skips the keyword search and
   blames that exact line directly.

## Design notes / known limits

- **Search is keyword-based (`git grep`), not semantic.** This is the
  honest v1 trade-off: no embeddings/vector DB to stand up, and `git grep`
  is instant on any repo size. It works well when your question shares
  vocabulary with the code (function/variable names, error strings). A
  natural v2 is swapping `search_code()` for an embedding index — the rest
  of the pipeline (blame → commit → PR → LLM) doesn't need to change.
- **PR/issue linking only works for GitHub-hosted repos**, and only when a
  commit message actually references `#123` (common with squash-merged PRs,
  less common with rebase workflows). GitLab/Bitbucket support would mean
  adding equivalent API clients in `github_api.py`.
- **State is in-memory and single-repo-at-a-time** (`STATE` dict in
  `main.py`) — intentional for a local dev tool. Turning this into a
  multi-user hosted product would mean session-scoping that state per user,
  same as the auth/DB pattern in a typical multi-tenant app.
- Shallow clones (`--depth 200`) mean blame can occasionally hit the clone
  boundary on very old code. Increase the depth in `git_tools.load_repo()`
  if you're working with a repo with deep history you care about.

## Project structure

```
backend/
  main.py         FastAPI app — /repo/load, /ask, serves frontend
  git_tools.py    git grep / blame / show wrappers (subprocess, no GitPython)
  github_api.py   fetches PR/issue title+body for citation context
  prompts.py      system prompt + evidence-block formatting
  llm.py          Groq (OpenAI-compatible) streaming client
  config.py       env-based settings
frontend/
  assets/
    favicon.png
  index.html      single-file UI (same design language as Dokument)
```
