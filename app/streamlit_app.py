"""Case browser: discovers cases/*/ and renders plan.yaml, report.md and figures.

Run:  streamlit run app/streamlit_app.py   (or `make app`)
Needs no API keys; it only reads files committed to the repo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
CASES_DIR = ROOT / "cases"


@dataclass
class Case:
    slug: str
    path: Path
    plan: dict[str, Any] = field(default_factory=dict)
    plan_error: str | None = None
    report: str | None = None
    figures: list[Path] = field(default_factory=list)

    @property
    def is_template(self) -> bool:
        return self.slug.startswith("_")

    @property
    def title(self) -> str:
        return str(self.plan.get("title") or self.plan.get("case_id") or self.slug)


def load_case(path: Path) -> Case:
    case = Case(slug=path.name, path=path)
    plan_path = path / "plan.yaml"
    if plan_path.exists():
        try:
            data = yaml.safe_load(plan_path.read_text(encoding="utf-8")) or {}
            case.plan = data if isinstance(data, dict) else {}
        except yaml.YAMLError as exc:
            case.plan_error = str(exc)
    report_path = path / "report.md"
    if report_path.exists():
        case.report = report_path.read_text(encoding="utf-8")
    fig_dir = path / "figures"
    if fig_dir.is_dir():
        case.figures = sorted(fig_dir.glob("*.png"))
    return case


def discover_cases(cases_dir: Path = CASES_DIR, include_templates: bool = False) -> list[Case]:
    if not cases_dir.is_dir():
        return []
    cases = [
        load_case(p)
        for p in sorted(cases_dir.iterdir())
        if p.is_dir() and not p.name.startswith(".") and (p / "plan.yaml").exists()
    ]
    return [c for c in cases if include_templates or not c.is_template]


def _describe(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("description", "definition", "method", "name"):
            if value.get(key):
                return str(value[key])
        return str(value)
    if isinstance(value, list):
        return ", ".join(str(v.get("name", v)) if isinstance(v, dict) else str(v) for v in value)
    return "" if value is None else str(value)


def _treat_time(plan: dict[str, Any]) -> str:
    treatment = plan.get("treatment")
    if isinstance(treatment, dict) and treatment.get("treat_time"):
        return str(treatment["treat_time"])
    return str(plan.get("treatment_time") or "-")


def render_card(st: Any, case: Case) -> None:
    plan = case.plan
    with st.container(border=True):
        st.subheader(case.title)
        st.caption(f"`cases/{case.slug}` · owners: {_describe(plan.get('owners')) or '-'}")
        if case.plan_error:
            st.error(f"plan.yaml 파싱 오류: {case.plan_error}")
            return
        st.markdown(f"**질문** {plan.get('question', '-')}")
        cols = st.columns(3)
        cols[0].markdown(f"**처치**  \n{_describe(plan.get('treatment'))}")
        cols[1].markdown(f"**대조**  \n{_describe(plan.get('control'))}")
        cols[2].markdown(
            f"**시점 / 방법**  \n{_treat_time(plan)} · {_describe(plan.get('estimator'))}"
        )
        licenses = {
            str(s.get("license", "?"))
            for s in plan.get("data_sources") or []
            if isinstance(s, dict)
        }
        st.caption("데이터 라이선스: " + (", ".join(sorted(licenses)) or "미기재"))


def render_detail(st: Any, case: Case) -> None:
    tab_report, tab_figs, tab_plan = st.tabs(["리포트", "그림", "plan.yaml"])
    with tab_report:
        if case.report:
            st.markdown(case.report)
        else:
            st.info("report.md가 아직 없습니다.")
    with tab_figs:
        if case.figures:
            for fig in case.figures:
                st.image(str(fig), caption=fig.name)
        else:
            st.info("figures/*.png가 아직 없습니다.")
    with tab_plan:
        st.code((case.path / "plan.yaml").read_text(encoding="utf-8"), language="yaml")


def main() -> None:
    import streamlit as st

    st.set_page_config(page_title="정책 효과 분석 케이스", layout="wide")
    st.title("정책 효과 분석 케이스")
    st.caption("에이전틱 AI × 데이터 — CausalInferenceLab/policy-effect-analytics-agent")

    show_templates = st.sidebar.toggle("템플릿/예시 포함", value=False)
    cases = discover_cases(include_templates=show_templates)
    if not cases:
        st.info("아직 케이스가 없습니다. `cases/_template`을 복사해 시작하세요.")
        return

    for case in cases:
        render_card(st, case)

    st.divider()
    selected = st.sidebar.selectbox(
        "케이스 상세", cases, format_func=lambda c: f"{c.title} ({c.slug})"
    )
    st.header(selected.title)
    render_detail(st, selected)


if __name__ == "__main__":
    main()
