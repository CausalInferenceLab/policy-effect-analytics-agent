# core/ 의존성 (Data 담당 → pyproject 병합용)

Python 3.11.15 에서 설치·테스트한 버전입니다. pyproject 에는 `>=` 하한으로 넣고, lock 은 uv 로 관리 권장.

| 패키지 | 검증 버전 | 용도 |
|---|---|---|
| pydantic | 2.13.3 | plan.yaml 스키마 |
| PyYAML | 6.0.3 | plan.yaml 로드 |
| pandas | 3.0.2 | 데이터 처리 |
| numpy | 2.4.4 | |
| scipy | 1.17.1 | Wald/정규 검정 |
| pyfixest | 0.60.0 | DiD/TWFE/event study, 군집-강건 SE |
| statsmodels | 0.15.0 | ITS (Newey-West HAC) |
| matplotlib | 3.10.9 | 그림 |
| requests | 2.33.1 | KOSIS 어댑터 |
| pytest (dev) | 9.1.1 | tests/core |

```toml
dependencies = [
  "pydantic>=2.7", "pyyaml>=6", "pandas>=2.2", "numpy>=1.26", "scipy>=1.11",
  "pyfixest>=0.60", "statsmodels>=0.14", "matplotlib>=3.8", "requests>=2.31",
]
[project.optional-dependencies]
dev = ["pytest>=8"]
```

- **현재 root pyproject 와의 차이 (병합 요청)**: ① `scipy` 누락 → 추가 필요, ② `pyfixest>=0.25` → `>=0.60` 권장
  (event study 결합검정에서 `fit._vcov` 사용, 0.60 에서만 검증). `pandas<3` 핀은 OK — pandas 2.3.3 에서도 16개 테스트 통과.
- pytest 는 `tests/core/conftest.py` 가 repo 루트를 `sys.path` 에 넣으므로 설치 없이 동작합니다.
  pyproject 에 `[tool.pytest.ini_options] pythonpath = ["."]` 를 넣어도 됩니다.
- 선택: `dowhy`(반박검정 확장), Callaway–Sant'Anna 용 `csdid`/`differences` — 아직 미도입.

## 모듈 지도
```
core/schema/plan.py      plan.yaml 스키마 (Plan, load_plan)
core/adapters/           BaseAdapter · KosisAdapter · LocalFileAdapter · SyntheticAdapter
core/estimators/         did · event_study · placebo_time · its → EffectResult, apply_abstention
core/pipeline.py         run_plan(plan, df): 추정 → 반박검정 → 보류판정
core/report/             raw_trends · event_study_plot · its_plot · render_report(markdown)
core/agent/              validate_plan · run_estimate (LangGraph 래핑용 얇은 인터페이스)
```
