SYSTEM_PROMPT = {
    "role": "system",
    "content": (
        "You are an onboarding assistant for a specific codebase. Your job is to "
        "explain WHY code works the way it does, using the real evidence provided "
        "to you below (code snippets, git blame results, commit messages, and "
        "linked GitHub pull request / issue descriptions) — never invent history "
        "you weren't given.\n\n"
        "Rules:\n"
        "- Ground every claim in the evidence provided. If the evidence doesn't "
        "explain the 'why', say so plainly rather than speculating.\n"
        "- Always cite which commit (short hash) or PR/issue number supports each "
        "claim, e.g. '(commit a1b2c3d)' or '(PR #482)'.\n"
        "- If evidence is thin, give the best grounded answer you can and clearly "
        "flag which parts are your inference vs. documented fact.\n"
        "- Be concise and technical. Assume the reader is a competent engineer who "
        "is new to this repo, not a beginner programmer.\n"
        "- If several commits touched the code, mention how the reasoning evolved "
        "if that's relevant, don't just cite the latest one.\n"
    ),
}


def build_evidence_block(entries: list[dict]) -> str:
    """
    entries: list of dicts, each describing one piece of evidence gathered
    for a code location — snippet + blame + optional PR/issue.
    """
    blocks = []
    for i, e in enumerate(entries, start=1):
        parts = [f"### Evidence {i}: {e['file']}:{e['line_no']}"]
        if e.get("snippet"):
            parts.append("```\n" + e["snippet"] + "\n```")
        if e.get("commit"):
            c = e["commit"]
            parts.append(
                f"Last touched in commit {c['commit_hash'][:7]} by {c['author']} "
                f"on {c['date']}: \"{c['summary']}\""
            )
        if e.get("commit_body"):
            parts.append(f"Full commit message:\n{e['commit_body']}")
        if e.get("pr"):
            pr = e["pr"]
            kind = "Pull Request" if pr["is_pr"] else "Issue"
            parts.append(
                f"Linked {kind} #{pr['number']} — \"{pr['title']}\"\n{pr['body']}"
            )
        blocks.append("\n".join(parts))
    return "\n\n".join(blocks)


def build_user_message(question: str, repo_name: str, evidence: str) -> dict:
    content = (
        f"Repository: {repo_name}\n"
        f"Question: {question}\n\n"
        f"Evidence gathered from the repository:\n\n{evidence or '(no direct evidence found — answer from the code shown, if any, and say so)'}"
    )
    return {"role": "user", "content": content}
