"""Print commits and files changed per cases/<group> over the last N days.

Uses local `git log` only (no network). Run `git fetch --all` first to include
branches that have not been merged yet.

    python scripts/weekly_activity.py              # last 7 days, all refs
    python scripts/weekly_activity.py --days 14 --ref origin/main
"""

from __future__ import annotations

import argparse
import subprocess
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

SEP = "\x1e"


@dataclass
class Stat:
    commits: set[str] = field(default_factory=set)
    authors: set[str] = field(default_factory=set)
    files: set[str] = field(default_factory=set)
    added: int = 0
    deleted: int = 0


def area_of(path: str) -> str:
    parts = path.split("/")
    if parts[0] == "cases" and len(parts) > 2:
        return f"cases/{parts[1]}"
    return parts[0] if len(parts) > 1 else "(root)"


def collect(repo: Path, days: int, ref: str | None) -> dict[str, Stat]:
    cmd = [
        "git",
        "-C",
        str(repo),
        "log",
        f"--since={days}.days.ago",
        "--no-merges",
        "--numstat",
        f"--format={SEP}%h\t%an",
    ]
    cmd += [ref] if ref else ["--all"]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout

    stats: dict[str, Stat] = defaultdict(Stat)
    for block in out.split(SEP)[1:]:
        lines = block.strip().splitlines()
        if not lines:
            continue
        sha, _, author = lines[0].partition("\t")
        for line in lines[1:]:
            cols = line.split("\t")
            if len(cols) != 3:
                continue
            add, delete, path = cols
            if " => " in path:  # rename: keep destination
                path = path.split(" => ")[-1].strip("{}")
            s = stats[area_of(path)]
            s.commits.add(sha)
            s.authors.add(author)
            s.files.add(path)
            s.added += int(add) if add.isdigit() else 0
            s.deleted += int(delete) if delete.isdigit() else 0
    return dict(stats)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--ref", default=None, help="branch/ref to scan (default: all refs)")
    args = ap.parse_args(argv)

    stats = collect(args.repo, args.days, args.ref)
    groups = sorted(
        p.name
        for p in (args.repo / "cases").glob("*")
        if p.is_dir() and not p.name.startswith(("_", "."))
    )
    for g in groups:  # show silent groups explicitly
        stats.setdefault(f"cases/{g}", Stat())

    print(f"# Activity, last {args.days} days ({args.ref or 'all refs'})")
    print(f"{'area':<36}{'commits':>8}{'authors':>8}{'files':>7}{'+/-':>14}")
    for area in sorted(stats, key=lambda a: (not a.startswith("cases/"), a)):
        s = stats[area]
        flag = "  <- no activity" if not s.commits else ""
        print(
            f"{area:<36}{len(s.commits):>8}{len(s.authors):>8}{len(s.files):>7}"
            f"{f'+{s.added}/-{s.deleted}':>14}{flag}"
        )


if __name__ == "__main__":
    main()
