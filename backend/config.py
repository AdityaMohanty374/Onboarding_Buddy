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


settings = Settings()
