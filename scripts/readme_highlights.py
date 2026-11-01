"""README 의 '지금까지 만든 것' 표를 레포 파일에서 다시 만든다.

    python scripts/readme_highlights.py          # README.md 의 표시 구간을 갱신
    python scripts/readme_highlights.py --check  # 갱신이 필요하면 종료 코드 1 (CI 경고용)

README 안의 <!-- highlights:start --> 와 <!-- highlights:end --> 사이만 바꾼다.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "site"))

SITE = "https://causalinferencelab.github.io/policy-effect-analytics-agent"
REPO = "https://github.com/CausalInferenceLab/policy-effect-analytics-agent"
START, END = "<!-- highlights:start -->", "<!-- highlights:end -->"
STAGE = ["계획", "수집", "분석", "해석"]


def table() -> str:
    import answers as ans
    import projects as proj

    from core.discovery.catalog import load_topics

    topics = {t.id: t for t in load_topics()}
    results = {a["case"]: a for a in ans.load_answers()}
    rows = []
    for p in sorted(
        proj.load_projects(), key=lambda p: (p["mentor"], p["case"] not in results, -p["stage"])
    ):
        t = topics.get(p["topic"])
        a = results.get(p["case"])
        if a:
            state = ans.VERDICT.get(a["verdict"], (a["verdict"],))[0]
            link = f"[결과 보기]({SITE}/{a['page']})"
        else:
            state = f"{STAGE[p['stage']]} 단계" if p["stage"] >= 0 else "준비"
            link = f"[폴더]({REPO}/tree/main/cases/{p['case']})"
        who = "멘토 예시" if p["mentor"] else f"[@{p['owner']}](https://github.com/{p['owner']})"
        title = p["title"].replace("|", "·")
        rows.append(f"| {title} | {t.name if t else '-'} | {who} | {state} | {link} |")
    from core.discovery.lineage import load_lineages
    from core.discovery.ontology import load_datasets, load_issues

    mentee = [p for p in proj.load_projects() if not p["mentor"]]
    crew = proj.people(proj.load_projects(), load_lineages(), activity={})
    n_res = sum(1 for p in mentee if p["case"] in results)
    stats = (
        f"**주제 {len(topics)}개 · 지금 이슈 {len(load_issues())}개 · 공공데이터 {len(load_datasets())}개 · "
        f"계보 {len(load_lineages())}개 · 참여자 프로젝트 {len(mentee)}개(결과 {n_res}개) · 함께 만든 사람 {len(crew)}명**"
    )
    head = "| 프로젝트 | 주제 | 누가 | 지금 | 보기 |\n|---|---|---|---|---|"
    return stats + "\n\n" + head + "\n" + "\n".join(rows)


def render(text: str) -> str:
    a, b = text.index(START) + len(START), text.index(END)
    return text[:a] + "\n" + table() + "\n" + text[b:]


def main() -> int:
    f = ROOT / "README.md"
    old = f.read_text(encoding="utf-8")
    new = render(old)
    if "--check" in sys.argv:
        if new != old:
            print("README 의 프로젝트 표가 최신이 아닙니다: python scripts/readme_highlights.py")
            return 1
        return 0
    f.write_text(new, encoding="utf-8")
    print("README 프로젝트 표 갱신")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
