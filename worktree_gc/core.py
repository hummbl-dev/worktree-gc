"""Fail-closed git worktree classification and garbage collection.

Finds git worktrees under a set of roots (directories whose `.git` is a file
pointing at a gitdir), classifies each, and — only in `--fix` mode — removes
the provably-merged ones. The design is fail-closed: if any worktree cannot be
classified, no removal happens.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

RESERVED_BRANCHES = {"", "?", "HEAD", "main", "master"}
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__"}
GITDIR_RE = __import__("re").compile(r"^gitdir:\s*(.+)$")


@dataclass
class Worktree:
    path: Path
    branch: str
    clean: bool
    merged: bool
    open_pr: bool


def decide(branch: str, clean: bool, merged: bool, open_pr: bool) -> str:
    """Classify a worktree from its observable state.

    Returns one of: reclaimable, protected, dirty, unmerged.
    """
    if not clean:
        return "dirty"
    if branch in RESERVED_BRANCHES:
        return "protected"
    if not merged:
        return "unmerged"
    if open_pr:
        return "protected"
    return "reclaimable"


def _git(args: list[str], cwd: Path, timeout: int = 30) -> tuple[int, str]:
    try:
        p = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "").strip()
    except (OSError, subprocess.SubprocessError):
        return -1, ""


def inspect(path: Path) -> Worktree | None:
    """Inspect a worktree directory; None if it is not a git worktree or is unreadable."""
    dotgit = path / ".git"
    if not dotgit.is_file():
        return None
    try:
        head = dotgit.read_text(encoding="utf-8", errors="replace").splitlines()[0]
    except (OSError, IndexError):
        return None
    if not GITDIR_RE.match(head.strip()):
        return None
    rc, branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], path)
    if rc != 0:
        branch = "?"
    rc, status = _git(["status", "--porcelain"], path)
    clean = rc == 0 and not status
    merged = False
    if branch not in ("?", ""):
        for ref in ("origin/HEAD", "origin/main"):
            rc, _ = _git(["merge-base", "--is-ancestor", branch, ref], path)
            if rc == 0:
                merged = True
                break
    return Worktree(path=path, branch=branch, clean=clean, merged=merged, open_pr=False)


def find_worktrees(roots: list[Path], max_depth: int = 6) -> list[Path]:
    found: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        stack = [(root, 0)]
        while stack:
            d, depth = stack.pop()
            if depth > max_depth:
                continue
            if (d / ".git").is_file():
                found.append(d)
                continue  # a worktree; don't descend
            try:
                entries = list(d.iterdir())
            except OSError:
                continue
            for e in entries:
                if e.is_dir() and e.name not in SKIP_DIRS and not e.name.startswith(".git"):
                    stack.append((e, depth + 1))
    return found


def mark_open_pr(worktrees: list[Worktree], repo: Path) -> None:
    """Mark worktrees whose branch has an open PR (via `gh`), if available."""
    if not (repo / ".git").exists():
        return
    try:
        p = subprocess.run(
            ["gh", "pr", "list", "--state", "open", "--json", "headRefName"],
            cwd=str(repo), capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return
    if p.returncode != 0:
        return
    import json
    try:
        rows = json.loads(p.stdout)
    except ValueError:
        return
    if not isinstance(rows, list):
        return
    open_branches = {r.get("headRefName") for r in rows if isinstance(r, dict) and r.get("headRefName")}
    for w in worktrees:
        if w.branch in open_branches:
            w.open_pr = True


def remove(worktree: Worktree) -> tuple[bool, str]:
    """Remove a reclaimable worktree via `git worktree remove`. Fail-closed."""
    if decide(worktree.branch, worktree.clean, worktree.merged, worktree.open_pr) != "reclaimable":
        return False, "not reclaimable"
    repo = worktree.path
    rc, err = _git(["worktree", "remove", str(worktree.path)], repo, timeout=120)
    return rc == 0, err


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--roots", nargs="*", default=[os.getcwd()])
    ap.add_argument("--fix", action="store_true", help="remove reclaimable worktrees")
    args = ap.parse_args(argv)

    roots = [Path(os.path.abspath(r)) for r in args.roots]
    paths = find_worktrees(roots)
    worktrees: list[Worktree] = []
    unknown = 0
    for p in paths:
        wt = inspect(p)
        if wt is None:
            unknown += 1
            continue
        worktrees.append(wt)

    # Fail-closed: never remove anything unless every worktree classified cleanly.
    if args.fix and unknown:
        print(f"REFUSED: {unknown} worktree(s) could not be inspected; no removals", file=sys.stderr)
        return 2

    counts = {"reclaimable": 0, "protected": 0, "dirty": 0, "unmerged": 0}
    for w in worktrees:
        counts[decide(w.branch, w.clean, w.merged, w.open_pr)] += 1

    removed = 0
    if args.fix:
        for w in [w for w in worktrees if decide(w.branch, w.clean, w.merged, w.open_pr) == "reclaimable"]:
            ok, err = remove(w)
            if ok:
                removed += 1
            else:
                print(f"remove FAILED {w.path}: {err}", file=sys.stderr)

    print(f"worktrees={len(worktrees)} reclaimable={counts['reclaimable']} protected={counts['protected']} "
          f"dirty={counts['dirty']} unmerged={counts['unmerged']} unknown={unknown} removed={removed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
