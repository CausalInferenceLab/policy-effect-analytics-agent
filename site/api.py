"""공개 JSON API(_site/api/*.json)와 서비스(apps/) 호스팅 — 트랙 C(서비스 개발)의 재료.

사이트를 만들 때 함께 생성됩니다. 서버 없이 GitHub Pages 의 정적 파일이라 누구나 fetch 로 읽을 수 있습니다.

    api/index.json          엔드포인트 목록 · 생성 시각 · 이용 조건
    api/topics.json         주제 (세 가지 확인 상태, 사건, 근거 법률 요약)
    api/issues.json         지금 이슈인 정책 (시작일, 비교 대상, 설계, 쓰는 데이터)
    api/datasets.json       데이터 지도 (역할 · 단위 · 받는 법 · 이용 조건)
    api/legal/<주제>.json   법제처에서 모은 법령·행정규칙·조례 목록 (메타데이터)
    api/lineage.json        데이터 계보 그래프 (이슈 → 정책 → 데이터 → 가공 → 지표 → 분석)
    api/results.json        분석 결과 (cases/*/flow_log.json: 판정 · 추정치 · 신뢰구간 · 그림)

apps/<내ID>-<서비스>/ 의 정적 파일(html·css·js·json·이미지)은 _site/apps/<같은 이름>/ 으로 복사되어
https://causalinferencelab.github.io/policy-effect-analytics-agent/apps/<이름>/ 에서 열립니다.
"""

from __future__ import annotations

import json
import math
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
APPS = ROOT / "apps"
CASES = ROOT / "cases"
STATIC_EXT = {
    ".html",
    ".css",
    ".js",
    ".mjs",
    ".json",
    ".svg",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".ico",
    ".txt",
    ".md",
    ".csv",
}
TERMS = (
    "학습·연구용 오픈소스 분석이며 공식 평가·통계가 아닙니다. 법률 자문이 아닙니다. "
    "법령 정보 출처: 법제처 국가법령정보센터. 데이터셋마다 이용 조건(license)이 다르니 확인하세요."
)


def _clean(obj):
    """NaN·무한대는 브라우저 JSON.parse 가 읽지 못하므로 null 로 바꾼다."""
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    return obj


def _dump(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(_clean(obj), ensure_ascii=False, indent=1, default=str, allow_nan=False)
    path.write_text(text, encoding="utf-8")


# ─── 분석 결과 ────────────────────────────────────────────────────────────────
def case_results(out: Path) -> list[dict]:
    """cases/*/flow_log.json 을 서비스가 쓰기 쉬운 모양으로. 그림은 _site/cases/<케이스>/ 로 복사."""
    from core.discovery.lineage import load_lineages
    from core.schema.plan import load_plan

    topic_of = {Path(p).name: t for t, p in _sample_cases().items()} | {
        c: lin.topic for lin in load_lineages() for s in lin.steps for c in s.used_by
    }
    rows = []
    for log_path in sorted(CASES.glob("*/flow_log.json")):
        case = log_path.parent
        if case.name.startswith("_"):
            continue
        try:
            log = json.loads(log_path.read_text(encoding="utf-8"))
        except ValueError:  # 기록 하나가 깨져도 사이트 빌드는 계속한다
            print(f"건너뜀: {log_path} 를 읽을 수 없습니다")
            continue
        try:
            plan = load_plan(case / "plan.yaml")
            meta = {
                "title": plan.title,
                "question": plan.question.strip(),
                "synthetic": plan.synthetic_data,
            }
            names = {o.col: o.name for o in plan.outcomes}
        except Exception:  # 계획이 바뀌는 중이어도 결과 목록은 만든다
            meta, names = (
                {
                    "title": case.name,
                    "question": log.get("question"),
                    "synthetic": _raw_synthetic(case),
                },
                {},
            )
        figs = []
        dest = out / "cases" / case.name
        for f in sorted((case / "figures").glob("*.png")):
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copy(f, dest / f.name)
            figs.append(f"cases/{case.name}/{f.name}")
        rows.append(
            {
                "case": case.name,
                "topic": topic_of.get(case.name),
                **meta,
                "status": log.get("status"),
                "verdict": log.get("verdict"),
                "finished_at": log.get("ended_at"),
                "outcomes": [
                    {
                        "col": r.get("outcome"),
                        "name": names.get(r.get("outcome"), r.get("outcome")),
                        "method": r.get("method"),
                        "estimate": r.get("estimate"),
                        "ci": [r.get("ci_low"), r.get("ci_high")],
                        "p_value": r.get("p_value"),
                        "n_obs": r.get("n_obs"),
                        "verdict": r.get("verdict"),
                        "warnings": r.get("warnings", []),
                    }
                    for r in log.get("results", [])
                ],
                "figures": figs,
                "source": f"cases/{case.name}",
            }
        )
    return rows


def _raw_synthetic(case: Path) -> bool | None:
    """검증에 실패한 계획이라도 synthetic_data 표시는 살린다 (시뮬레이션 배지가 빠지지 않게)."""
    try:
        return bool(
            (yaml.safe_load((case / "plan.yaml").read_text(encoding="utf-8")) or {}).get(
                "synthetic_data"
            )
        )
    except (OSError, yaml.YAMLError):
        return None


def _sample_cases() -> dict[str, str]:
    from core.discovery.catalog import load_catalog, load_topics

    pol_topic = {p: t.id for t in load_topics() for p in t.policies}
    return {
        pol_topic[p.id]: p.sample_case
        for p in load_catalog()
        if p.sample_case and p.id in pol_topic
    }


# ─── API 전체 ─────────────────────────────────────────────────────────────────
def write_api(out: Path, topics, issues, datasets, legal_summary) -> dict:
    from core.discovery.lineage import graph

    api = out / "api"
    files = {
        "topics.json": [
            {
                **t.model_dump(mode="json", exclude={"collect", "legal"}),
                "legal": legal_summary(t),
            }
            for t in topics
        ],
        "issues.json": [i.model_dump(mode="json") for i in issues],
        "datasets.json": [d.model_dump(mode="json") for d in datasets],
        "lineage.json": graph(),
        "results.json": case_results(out),
    }
    for name, obj in files.items():
        _dump(api / name, obj)
    legal = []
    for f in sorted((ROOT / "catalog" / "snapshots").glob("legal_*.csv")):
        topic = f.stem.removeprefix("legal_")
        rows = pd.read_csv(f, dtype=str).fillna("").to_dict("records")
        _dump(api / "legal" / f"{topic}.json", rows)
        legal.append(f"legal/{topic}.json")
    index = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "terms": TERMS,
        "endpoints": sorted(files) + legal,
        "counts": {
            k: len(v) if isinstance(v, list) else len(v.get("lineages", []))
            for k, v in files.items()
        },
    }
    _dump(api / "index.json", index)
    return index


# ─── 서비스(apps/) ────────────────────────────────────────────────────────────
def load_apps() -> list[dict]:
    apps = []
    for d in sorted(p for p in APPS.glob("*") if p.is_dir()):
        meta_path = d / "app.yaml"
        if not meta_path.exists():
            continue
        meta = yaml.safe_load(meta_path.read_text(encoding="utf-8")) or {}
        apps.append(
            {
                "slug": d.name,
                "title": meta.get("title", d.name),
                "owner": meta.get("owner", ""),
                "description": meta.get("description", ""),
                "uses": meta.get("uses", []),
                "url": meta.get("url"),  # 다른 곳에 배포했다면 그 주소
                "template": d.name.startswith("_"),
                "has_page": (d / "index.html").exists(),
            }
        )
    return apps


def copy_apps(out: Path) -> list[dict]:
    apps = load_apps()
    for a in apps:
        if not a["has_page"]:
            continue
        src, dest = APPS / a["slug"], out / "apps" / a["slug"]
        for f in src.rglob("*"):
            if f.is_file() and f.suffix.lower() in STATIC_EXT and f.name != "app.yaml":
                target = dest / f.relative_to(src)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(f, target)
    return apps
