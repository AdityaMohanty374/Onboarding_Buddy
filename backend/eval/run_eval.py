"""
Retrieval eval for Onboarding Buddy.

This tests RETRIEVAL, not generation — it never calls the LLM. Each case
checks whether git_tools.search_code() / line_history() actually surface the
real, hand-verified evidence a human confirmed by running `git log -L`
directly against the repo. That's a much stronger claim than "the answer
looked plausible": it's measuring whether the pipeline finds the right
needle in the haystack, independent of how the LLM writes it up afterward.

Usage:
    cd backend
    GROQ_API_KEY=unused python eval/run_eval.py
    GROQ_API_KEY=unused python eval/run_eval.py --repo /path/to/local/flask/clone

(GROQ_API_KEY is only required because config.py insists on it at import
time — this script never actually calls the LLM, so any placeholder value
works.)
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import git_tools  # noqa: E402

DEFAULT_REPO_SOURCE = "https://github.com/pallets/flask"
CASES_PATH = os.path.join(os.path.dirname(__file__), "eval_cases.json")


def run_pinpoint_case(repo_path: str, case: dict) -> tuple[bool, str]:
    history = git_tools.line_history(repo_path, case["file"], case["line"], max_commits=4)
    hashes = [c.commit_hash for c in history]
    expected = case["expected_commit_prefix"]
    hit = any(h.startswith(expected) for h in hashes)
    found = ", ".join(h[:7] for h in hashes) or "(none)"
    detail = f"expected {expected} in [{found}]"
    return hit, detail


def run_search_case(repo_path: str, case: dict) -> tuple[bool, str]:
    hits = git_tools.search_code(repo_path, case["query"], max_hits=max(case["top_k"], 12))
    top_files = [h.file for h in hits[: case["top_k"]]]
    expected_any = case["expected_file_any_of"]
    hit = any(f in top_files for f in expected_any)
    detail = f"expected one of {expected_any} in top {case['top_k']}: {top_files}"
    return hit, detail


def main():
    parser = argparse.ArgumentParser(description="Run the retrieval eval.")
    parser.add_argument("--repo", default=DEFAULT_REPO_SOURCE,
                         help="Local path or git URL (default: pallets/flask)")
    parser.add_argument("--cases", default=CASES_PATH)
    args = parser.parse_args()

    print(f"Loading repo: {args.repo}")
    repo_path = git_tools.load_repo(args.repo)
    print(f"  -> {repo_path}\n")

    with open(args.cases) as f:
        cases = json.load(f)

    results = []
    for case in cases:
        if case["type"] == "pinpoint":
            passed, detail = run_pinpoint_case(repo_path, case)
        elif case["type"] == "search":
            passed, detail = run_search_case(repo_path, case)
        else:
            raise ValueError(f"Unknown case type: {case['type']}")
        results.append((case["id"], case["type"], passed, detail, case.get("note", "")))

    print(f"{'ID':<32} {'TYPE':<9} {'RESULT':<6}  DETAIL")
    print("-" * 100)
    for case_id, case_type, passed, detail, note in results:
        mark = "PASS" if passed else "FAIL"
        print(f"{case_id:<32} {case_type:<9} {mark:<6}  {detail}")
        if not passed and note:
            print(f"{'':<32} {'':<9} {'':<6}  note: {note}")

    total = len(results)
    passed_count = sum(1 for r in results if r[2])
    pinpoint_results = [r for r in results if r[1] == "pinpoint"]
    search_results = [r for r in results if r[1] == "search"]

    print("-" * 100)
    print(f"Overall:  {passed_count}/{total} passed ({passed_count/total:.0%})")
    if pinpoint_results:
        p_passed = sum(1 for r in pinpoint_results if r[2])
        print(f"  History accuracy (blame/log -L finds the real originating commit): "
              f"{p_passed}/{len(pinpoint_results)} ({p_passed/len(pinpoint_results):.0%})")
    if search_results:
        s_passed = sum(1 for r in search_results if r[2])
        print(f"  Search accuracy (grep ranking finds real code, not docs): "
              f"{s_passed}/{len(search_results)} ({s_passed/len(search_results):.0%})")

    sys.exit(0 if passed_count == total else 1)


if __name__ == "__main__":
    main()
