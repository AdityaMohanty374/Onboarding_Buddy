import os


class Settings:
    # Groq-hosted OpenAI-compatible endpoint (same pattern as Dokument).
    GROQ_API_KEY: str = os.environ["GROQ_API_KEY"]
    MODEL: str = os.environ.get("MODEL", "llama-3.1-8b-instant")
    TEMPERATURE: float = 0.15
    TOP_P: float = 0.9

    # Optional. Only needed to fetch PR/issue bodies for private repos or to
    # raise the (very low) unauthenticated GitHub API rate limit.
    GITHUB_TOKEN: str = os.environ.get("GITHUB_TOKEN", "")

    # Where cloned repos are checked out.
    WORKSPACE_DIR: str = os.environ.get("WORKSPACE_DIR", "/tmp/onboarding-buddy-repos")

    # Safety limits
    MAX_SEARCH_HITS: int = 12
    MAX_BLAME_COMMITS: int = 6
    MAX_CONTEXT_CHARS: int = 12000

    # --- Access control ---
    # Set this to a long random secret and share it only with yourself/trusted
    # devs. Requests sent with header `X-Dev-Key: <this value>` skip rate
    # limiting entirely (developer mode). Everyone else (no key, or a wrong
    # key) is treated as "user mode" and rate limited below. If left unset,
    # developer mode is effectively disabled — nobody can bypass limits.
    DEV_API_KEY: str = os.environ.get("DEV_API_KEY", "")

    # Per-IP limits for user mode (developer mode is exempt from all of these)
    RATE_LIMIT_LOAD_PER_MIN: int = int(os.environ.get("RATE_LIMIT_LOAD_PER_MIN", "3"))
    RATE_LIMIT_ASK_PER_MIN: int = int(os.environ.get("RATE_LIMIT_ASK_PER_MIN", "8"))


settings = Settings()
