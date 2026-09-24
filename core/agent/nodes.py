"""6단계 노드. 각 노드는 순수 함수 `FlowState -> FlowState` (입력 상태를 바꾸지 않고 복사본 반환).

  ① define_problem → ② collect → ③ structure_metrics → ④ estimate → ⑤ guard → ⑥ report

노드 본문은 `(status, message, artifacts)` 만 돌려주고, 로그·시간·예외 처리는 @step 이 맡는다.
멘티가 단계를 추가할 때도 같은 패턴을 쓰면 된다.
"""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
import time
from functools import wraps
from importlib import metadata
from pathlib import Path

import pandas as pd
import yaml
from pydantic import ValidationError

from ..adapters import REGISTRY, LocalFileAdapter, SourceMeta
from ..pipeline import run_plan
from ..report import event_study_plot, its_plot, raw_trends, render_report
from ..schema.plan import Plan, load_plan
from . import guard as G
from . import llm
from .state import STEPS, FlowState, StepLog, now

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_PLAN = ROOT / "cases" / "_template" / "plan.yaml"
_TITLES = dict(STEPS)


class FlowError(Exception):
    """사용자에게 그대로 보여줄 한국어 오류."""


def step(fn):
    name = fn.__name__

    @wraps(fn)
    def node(state: FlowState) -> FlowState:
        s = state.model_copy(deep=True)
        log = StepLog(index=len(s.steps) + 1, step=name, title=_TITLES[name])
        t0 = time.perf_counter()
        try:
            log.status, log.message, log.artifacts = fn(s)
        except FlowError as e:
            log.status, log.message = "failed", str(e)
        except Exception as e:  # noqa: BLE001 — 흐름을 멈추고 로그에 남긴다
            log.status, log.message = "failed", f"{type(e).__name__}: {e}"
        log.ended_at, log.duration_s = now(), round(time.perf_counter() - t0, 3)
        s.steps.append(log)
        return s

    return node


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


def plan_committed(case_dir: Path) -> bool:
    """plan.yaml 이 git 에 추적되고 HEAD 대비 수정이 없으면 True (사전 등록 확인)."""
    tracked = _git(case_dir, "ls-files", "--error-unmatch", "plan.yaml").returncode == 0
    return tracked and _git(case_dir, "diff", "--quiet", "HEAD", "--", "plan.yaml").returncode == 0


# ① ------------------------------------------------------------------------------------------
@step
def define_problem(s: FlowState):
    path = s.case_dir / "plan.yaml"
    if not path.exists():
        s.case_dir.mkdir(parents=True, exist_ok=True)
        template = TEMPLATE_PLAN.read_text(encoding="utf-8")
        if s.use_llm and llm.configured() and s.question:
            text = llm.strip_fence(
                llm.chat(
                    "너는 정책 효과 분석 설계자다. 주어진 템플릿과 같은 필드만 사용해 plan.yaml 을 작성하라. "
                    "YAML 만 출력하라. 데이터를 보기 전 사전 등록 문서이므로 보류 조건(abstention)을 보수적으로 둔다.",
                    f"분석 질문: {s.question}\n\n템플릿:\n{template}",
                )
            )
            path.write_text(text, encoding="utf-8")
            try:
                Plan.model_validate(yaml.safe_load(text))
                msg = "LLM 이 plan.yaml 초안을 작성했습니다. 사람이 검토·수정 후 커밋하고 다시 실행하세요."
            except (ValidationError, yaml.YAMLError) as e:
                msg = f"LLM 초안이 스키마 검증에 실패했습니다 — 직접 수정하세요:\n{e}"
            return "needs_human", msg, {"plan": "plan.yaml", "drafted_by": "llm"}
        header = f"# 분석 질문(입력): {s.question}\n" if s.question else ""
        path.write_text(header + template, encoding="utf-8")
        return (
            "needs_human",
            "plan.yaml 이 없어 템플릿을 복사했습니다(LLM 미설정). 작성·커밋 후 다시 실행하세요.",
            {"plan": "plan.yaml", "drafted_by": "template"},
        )

    try:
        s.plan = load_plan(path)
    except ValidationError as e:
        errs = "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors())
        raise FlowError(f"plan.yaml 스키마 오류 — {errs}") from e
    arts = {
        "plan": "plan.yaml",
        "plan_sha256": _sha256(path),
        "committed": plan_committed(s.case_dir),
    }
    if arts["committed"]:
        return "ok", f"분석계획 검증 완료, 사전 등록(git 커밋) 확인: {s.plan.case_id}", arts
    if s.allow_uncommitted:
        return (
            "warn",
            "⚠️ plan.yaml 이 커밋되지 않았습니다(--allow-uncommitted, 데모 전용). "
            "실제 분석에서는 결과를 보기 전에 계획을 커밋해야 합니다.",
            arts,
        )
    return (
        "blocked",
        "사전 등록 게이트: plan.yaml 을 먼저 git 에 커밋하세요 "
        "(데이터를 본 뒤 계획을 바꾸는 것을 막기 위함). 데모는 --allow-uncommitted.",
        arts,
    )


# ② ------------------------------------------------------------------------------------------
@step
def collect(s: FlowState):
    ds = s.plan.data_sources[0]
    path = s.case_dir / ds.path
    if path.exists():
        how = "기존 스냅샷 재사용 (새로 받으려면 파일 삭제 후 재실행)"
    elif (s.case_dir / "fetch.py").exists():
        r = subprocess.run(
            [sys.executable, "fetch.py"], cwd=s.case_dir, capture_output=True, text=True
        )
        if r.returncode != 0:
            raise FlowError(f"fetch.py 실행 실패:\n{r.stderr[-800:]}")
        how = "fetch.py 실행"
    elif ds.adapter == "local":
        meta = SourceMeta(ds.name, ds.provider, ds.license, ds.url)
        ad = LocalFileAdapter(s.case_dir / ds.query["path"], meta)
        ad.save(ad.fetch(), path, ds.query)
        how = "LocalFileAdapter"
    elif ds.adapter in REGISTRY:
        ad = REGISTRY[ds.adapter]()
        ad.save(ad.fetch(**ds.query), path, ds.query)
        how = f"{ds.adapter} 어댑터"
    else:
        raise FlowError(
            f"데이터가 없습니다: {ds.path} 가 없고 fetch.py 나 알려진 어댑터({list(REGISTRY)})도 없습니다."
        )
    if not path.exists():
        raise FlowError(f"수집 후에도 {ds.path} 가 생성되지 않았습니다.")
    s.data_path = path
    licenses = sorted({d.license for d in s.plan.data_sources})
    arts = {"data": ds.path, "data_sha256": _sha256(path), "licenses": licenses, "method": how}
    src = path.with_suffix(".source.json")
    if src.exists():
        arts["source_meta"] = str(src.relative_to(s.case_dir))
    notes = []
    if s.plan.synthetic_data:
        notes.append("⚠️ 합성 데이터 — 결과는 실제 정책 효과가 아님")
    if {"KOGL-3", "KOGL-4"} & set(licenses):
        notes.append("공공누리 3·4유형(변경금지) 포함 — 가공 데이터 재배포 불가")
    return ("warn" if notes else "ok"), " / ".join([how, *notes]), arts


# ③ ------------------------------------------------------------------------------------------
def quality_checks(p: Plan, df: pd.DataFrame) -> list[dict]:
    """(점검, 값, 상태, 메시지) 목록. status: ok | warn | failed."""
    t, u, g = p.time.col, p.unit.id_col, p.treatment.group_col
    outs = [o.col for o in p.outcomes]
    cols = [u, t, g, p.treatment.first_treat_col, p.estimator.cluster_col, *outs]
    need = [t, *outs] if p.estimator.method == "its" else [c for c in cols if c]
    need = list(dict.fromkeys(need + p.estimator.covariates))
    q = []

    def add(check, value, fail=False, warn=False, msg=""):
        status = "failed" if fail else "warn" if warn else "ok"
        q.append({"check": check, "value": value, "status": status, "message": msg})

    missing = [c for c in need if c not in df.columns]
    add("필수 컬럼", len(need) - len(missing), bool(missing), msg=f"없는 컬럼: {missing}")
    if missing:
        return q
    ints = df[t].dropna()
    ok = pd.api.types.is_integer_dtype(ints) or bool(ints.mod(1).eq(0).all())
    add("시간 컬럼 정수형", str(df[t].dtype), not ok, msg=f"'{t}' 는 정수(연도/0,1,2…)여야 함")
    for c in need:
        rate, key = float(df[c].isna().mean()), c in (u, t, g)
        add(f"결측률 {c}", round(rate, 4), (key and rate > 0) or rate > 0.2, rate > 0,
            msg=f"결측 {rate:.1%}" + (" — 식별 컬럼은 결측 불가" if key else ""))  # fmt: skip
    if (tt := p.treatment.treat_time) is not None:
        periods = df[t].dropna().unique()
        n_pre, n_post = int((periods < tt).sum()), int((periods >= tt).sum())
        min_pre = p.thresholds.min_pre_periods
        add("사전 기간 수", n_pre, n_pre == 0, n_pre < min_pre, f"최소 {min_pre}기 권장")
        add("사후 기간 수", n_post, n_post == 0, msg="사후 기간이 없습니다")
    if p.estimator.method != "its":
        by = df.groupby(u)[g].max()
        n_t, n_c, dup = int((by == 1).sum()), int((by == 0).sum()), int(df.duplicated([u, t]).sum())
        add("처치 단위 수", n_t, n_t == 0, msg="처치 단위가 없습니다")
        add("통제 단위 수", n_c, n_c == 0, msg="통제 단위가 없습니다")
        add("단위×시점 중복", dup, dup > 0, msg="한 단위·시점에 행이 여러 개")
    for x in q:  # 통과한 항목은 메시지 비움
        x["message"] = x["message"] if x["status"] != "ok" else ""
    return q


@step
def structure_metrics(s: FlowState):
    df = pd.read_csv(s.data_path)
    s.quality = q = quality_checks(s.plan, df)
    if failed := [x for x in q if x["status"] == "failed"]:
        detail = "; ".join(f"{x['check']}: {x['message']}" for x in failed)
        raise FlowError(f"데이터 품질 점검 실패 — {detail}")
    warns = [x["check"] for x in q if x["status"] == "warn"]
    msg = f"{len(q)}개 점검" + (f", 주의: {warns}" if warns else " 모두 통과")
    return (
        ("warn" if warns else "ok"),
        msg,
        {"rows": len(df), "units": int(df[s.plan.unit.id_col].nunique())},
    )


# ④ ------------------------------------------------------------------------------------------
@step
def estimate(s: FlowState):
    s.results = run_plan(s.plan, pd.read_csv(s.data_path))  # 숫자는 여기서만 계산 (LLM 관여 없음)
    arts = {
        r.outcome: {
            "estimate": round(r.estimate, 4),
            "ci": [round(r.ci_low, 4), round(r.ci_high, 4)],
            "verdict": r.verdict,
        }
        for r in s.results
    }
    r = s.results[0]
    msg = f"{r.method}: {r.estimate:+.3f} [{r.ci_low:.3f}, {r.ci_high:.3f}] → {r.verdict}"
    return ("warn" if any(x.warnings for x in s.results) else "ok"), msg, arts


# ⑤ ------------------------------------------------------------------------------------------
@step
def guard(s: FlowState):
    r = next(x for x in s.results if x.outcome == s.plan.primary_outcome.col)
    zero = r.ci_low <= 0 <= r.ci_high
    o = s.plan.primary_outcome
    text, source, rejected = G.template_narrative(r, o.unit, o.name), "template", []
    if s.use_llm and llm.configured():
        facts = {k: v for k, v in r.to_dict().items() if k != "extra"}
        draft = llm.chat(
            "너는 정책 효과 분석 결과를 3문장 이내 한국어로 요약한다. 주어진 수치만 쓰고 새 숫자를 만들지 마라. "
            "판정이 identified 가 아니면 인과·확정 표현(입증, 때문에, 덕분에 등)을 쓰지 마라. "
            "신뢰구간이 0을 포함하면 '효과 없음' 대신 '판별 불가'라고 써라.",
            json.dumps(facts, ensure_ascii=False, default=str),
        )
        rejected = G.lint(draft, r.verdict, zero)
        if not rejected:
            text, source = draft, "llm"
    violations = G.lint(text, r.verdict, zero)
    s.guard = {
        "verdict": r.verdict,
        "narrative_source": source,
        "passed": not violations,
        "violations": violations,
        "rejected_llm_violations": rejected,
        "narrative": text,
    }
    if violations:
        raise FlowError(f"서술 린트 실패: {violations}")
    msg = f"판정 {r.verdict}, 서술={source}"
    if rejected:
        msg += f" (LLM 서술에서 과잉해석 {len(rejected)}건 → 템플릿으로 대체)"
    return (
        ("ok" if r.verdict == "identified" and not rejected else "warn"),
        msg,
        {"triggers": r.triggers},
    )


# ⑥ ------------------------------------------------------------------------------------------
def _checks(plan, r) -> dict:
    out, ac = {}, r.assumptions_checked
    for a in plan.assumptions:
        if a.check == "pretrend_test" and "parallel_pretrends" in ac:
            x = ac["parallel_pretrends"]
            out[a.name] = (
                f"사전계수 결합 Wald p={x['p_value']:.3f} → {'통과' if x['passed'] else '기각'}"
            )
        elif a.check == "placebo_time" and "placebo_time" in ac:
            x = ac["placebo_time"]
            out[a.name] = (
                f"가짜 도입({x['fake_treat_time']}) 추정 {x['estimate']:.3f}, "
                f"p={x['p_value']:.3f} → {'통과' if x['passed'] else '실패'}"
            )
    return out


def _versions() -> dict:
    pk = "pandas numpy scipy pyfixest statsmodels pydantic matplotlib langgraph".split()
    out = {"python": platform.python_version()}
    for p in pk:
        try:
            out[p] = metadata.version(p)
        except metadata.PackageNotFoundError:
            pass
    return out


@step
def report(s: FlowState):
    p, df = s.plan, pd.read_csv(s.data_path)
    r = next(x for x in s.results if x.outcome == p.primary_outcome.col)
    figdir = s.case_dir / "figures"
    figdir.mkdir(exist_ok=True)
    figs = {}
    if p.estimator.method == "its":
        its_plot(
            df,
            r.outcome,
            p.time.col,
            p.treatment.treat_time,
            r.extra["fitted"],
            r.extra["counterfactual"],
            figdir / "its.png",
        )
        figs["ITS"] = "figures/its.png"
    else:
        tt = p.treatment.treat_time or df[p.treatment.first_treat_col].min()
        raw_trends(df, r.outcome, p.time.col, p.treatment.group_col, tt, figdir / "raw_trends.png")
        figs["Raw trends"] = "figures/raw_trends.png"
        if "coefs" in r.extra:
            event_study_plot(r.extra["coefs"], figdir / "event_study.png")
            figs["Event study"] = "figures/event_study.png"
    md = render_report(p, s.results, figs, _checks(p, r), narrative=s.guard.get("narrative"))
    s.report_path = s.case_dir / "report.md"
    s.report_path.write_text(md, encoding="utf-8")

    sha = _git(s.case_dir, "rev-parse", "HEAD")
    dirty = _git(s.case_dir, "status", "--porcelain", "--", ".")
    manifest = {
        "case_id": p.case_id,
        "started_at": s.started_at,
        "finished_at": now(),
        "git_sha": sha.stdout.strip() if sha.returncode == 0 else None,
        "git_dirty": bool(dirty.stdout.strip()) if dirty.returncode == 0 else None,
        "plan_sha256": _sha256(s.case_dir / "plan.yaml"),
        "data_sha256": _sha256(s.data_path),
        "data_path": str(s.data_path.relative_to(s.case_dir)),
        "versions": _versions(),
        "platform": platform.platform(),
        "verdicts": {x.outcome: x.verdict for x in s.results},
    }
    (s.case_dir / "run_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), "utf-8"
    )
    arts = {"report": "report.md", "manifest": "run_manifest.json", "figures": list(figs.values())}
    return "ok", f"리포트 {len(figs)}개 그림 포함 작성", arts


NODES = [define_problem, collect, structure_metrics, estimate, guard, report]

__all__ = ["NODES", "FlowError", "plan_committed"]
