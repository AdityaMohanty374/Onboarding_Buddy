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
        "- If your evidence is 3 test-file call sites and no real definition, do not "
        "fabricate a commit hash or code snippet under any circumstances — say the "
        "definition site wasn't found and stop.\n"
    ),
}


def build_evidence_block(entries: list[dict]) -> str:
    """
    entries: list of dicts, each describing one piece of evidence gathered
    for a code location — snippet + the line's commit history (oldest
    relevant to most recent) + any linked PR/issue per commit.
    """
    blocks = []
    for i, e in enumerate(entries, start=1):
        parts = [f"### Evidence {i}: {e['file']}:{e['line_no']}"]
        if e.get("snippet"):
            parts.append("```\n" + e["snippet"] + "\n```")

        commits = e.get("commits") or []
        if commits:
            parts.append(f"This line's history ({len(commits)} commit(s) found, most recent first):")
            for j, c in enumerate(commits, start=1):
                sub = [
                    f"  {j}. Commit {c['commit_hash'][:7]} by {c['author']} on {c['date']}: "
                    f"\"{c['summary']}\""
                ]
                if c.get("commit_body") and c["commit_body"] != c["summary"]:
                    sub.append(f"     Full message:\n     " + c["commit_body"].replace("\n", "\n     "))
                if c.get("pr"):
                    pr = c["pr"]
                    kind = "Pull Request" if pr["is_pr"] else "Issue"
                    sub.append(f"     Linked {kind} #{pr['number']} — \"{pr['title']}\"\n     {pr['body']}")
                parts.append("\n".join(sub))
        blocks.append("\n\n".join(parts))
    return "\n\n".join(blocks)


def build_user_message(question: str, repo_name: str, evidence: str) -> dict:
    content = (
        f"Repository: {repo_name}\n"
        f"Question: {question}\n\n"
        f"Evidence gathered from the repository:\n\n{evidence or '(no direct evidence found — answer from the code shown, if any, and say so)'}"
    )
    return {"role": "user", "content": content}
