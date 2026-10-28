"""강남대로 사례의 시간 경계·자료 검증·누수 방지·정책 패널을 합성 입력으로 검증한다."""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

CASE = Path(__file__).resolve().parents[1] / "cases/sgim49697-ops-gangnam-bus-2024"
sys.path.insert(0, str(CASE))

from gangnam.common import (  # noqa: E402
    PROTOCOL_FILES,
    read_yaml,
    require_data_contract,
    require_registration,
    sha256,
)
from gangnam.policy import balanced_wide, build_panel, daily_index, did_point  # noqa: E402
from gangnam.topis import (  # noqa: E402
    HEADERS,
    LEGACY_HEADERS,
    check_corridors,
    check_metadata,
    download,
    interval_start,
    parse_month,
    speed_value,
    validate_xlsx,
)
from gangnam.windows import (  # noqa: E402
    assert_common_keys,
    baseline,
    bounds,
    features,
    prediction_frame,
    prepare,
)


@pytest.fixture
def small_config():
    cfg = copy.deepcopy(read_yaml("ml_config.yaml"))
    cfg["required_links"] = ["a", "b", "c"]
    cfg["splits"] = {
        "train": ["2023-01-01", "2023-01-14"],
        "validation": ["2023-01-15", "2023-01-16"],
        "pre_test": ["2023-01-17", "2023-01-18"],
        "transition": ["2023-01-19", "2023-01-19"],
        "post_test": ["2023-01-20", "2023-01-21"],
    }
    return cfg


@pytest.fixture
def hourly(small_config):
    times = pd.date_range("2023-01-01", "2023-01-21 23:00", freq="h", tz="Asia/Seoul")
    return pd.DataFrame([
        (link, t, 20 + j * 2 + np.sin(i / 24) + i / 100, True, "")
        for j, link in enumerate(small_config["required_links"]) for i, t in enumerate(times)
    ], columns=["link_id", "interval_start_kst", "speed_kmh", "is_valid", "invalid_reason"])


def test_schema_and_calendar_index_match():
    from core.schema.plan import load_plan
    p = load_plan(CASE / "plan.yaml")
    cfg = read_yaml("corridors.yaml")
    assert p.case_id == CASE.name and not p.synthetic_data
    assert p.treatment.treat_time == (pd.Timestamp(cfg["policy_date"]) - pd.Timestamp(cfg["origin"])).days
    assert p.time.end == (pd.Timestamp(cfg["post"][1]) - pd.Timestamp(cfg["origin"])).days
    assert p.estimator.method == "did"
    assert any(r.when == "few_clusters" and r.verdict == "not_identified" for r in p.abstention)


@pytest.mark.parametrize("day,label,expected", [
    (20240229, "~24시", "2024-02-29 23:00"),
    (20240301, "~01시", "2024-03-01 00:00"),
    (20231231, "~24시", "2023-12-31 23:00"),
    (20240101, "~01시", "2024-01-01 00:00"),
])
def test_hour_label_is_interval_start_not_next_day(day, label, expected):
    assert interval_start(day, label) == pd.Timestamp(expected, tz="Asia/Seoul")


def test_unknown_semantics_blocks_real_data():
    contract = copy.deepcopy(read_yaml("data_contract.yaml"))
    contract["checks"]["hour_semantics"]["status"] = "pending"
    with pytest.raises(ValueError, match="공식 근거"):
        require_data_contract(contract)
    rules = {"blank_is_missing": True, "zero": "unresolved", "negative": "missing", "sentinels": [-9999]}
    with pytest.raises(ValueError, match="0 속도"):
        speed_value(0, rules)
    assert speed_value(-9999, rules)[1] == "sentinel"
    rules["sentinels"].extend(["9999", "NULL"])
    assert speed_value("NULL", rules)[1] == "sentinel"
    assert speed_value(9999.0, rules)[1] == "sentinel"
    assert speed_value(None, rules)[1] == "blank"
    assert speed_value(12.5, rules) == (12.5, "")
    with pytest.raises(ValueError, match="정의되지 않은"):
        speed_value("장애", rules)
    rules["zero"] = "valid"
    assert speed_value(0, rules) == (0.0, "")


def workbook(path, header=HEADERS, duplicate=False, speed="속도 열 접근 금지"):
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(header)
    row = [20240229, "목", "강남대로", "a", "A", "B", "하행", 100, 5, "주간선도로", "외곽", "서초구"] + [speed] * 24
    ws.append(row)
    if duplicate:
        ws.append(row)
    wb.save(path)
    wb.close()


@pytest.mark.parametrize("header", [HEADERS, LEGACY_HEADERS])
def test_metadata_only_does_not_interpret_speeds(tmp_path, header):
    path = tmp_path / "source.xlsx"
    workbook(path, header)
    frame, metadata = parse_month(path, "2024-02", ["강남대로"])
    assert frame.empty and metadata["header"] == header
    assert metadata["metadata"][0]["링크아이디"] == "a"


def test_normalization_preserves_missing_flags_and_all_24_intervals(tmp_path):
    path = tmp_path / "source.xlsx"
    workbook(path, speed=0)
    rules = {"blank_is_missing": True, "zero": "missing", "negative": "missing", "sentinels": []}
    frame, _ = parse_month(path, "2024-02", ["강남대로"], rules)
    assert len(frame) == 24 and not frame.is_valid.any()
    assert frame.speed_kmh.isna().all() and set(frame.invalid_reason) == {"zero"}
    assert frame.interval_start_kst.iloc[-1] == pd.Timestamp("2024-02-29 23:00", tz="Asia/Seoul")


def test_corrupt_xlsx_changed_header_duplicate_and_month_are_rejected(tmp_path):
    path = tmp_path / "source.xlsx"
    path.write_text("<html>error</html>")
    with pytest.raises(ValueError, match="HTML"):
        validate_xlsx(path)
    workbook(path, ["잘못된 날짜"] + HEADERS[1:])
    with pytest.raises(ValueError, match="헤더 변경"):
        parse_month(path, "2024-02", ["강남대로"])
    workbook(path, duplicate=True)
    with pytest.raises(ValueError, match="중복"):
        parse_month(path, "2024-02", ["강남대로"])
    workbook(path)
    with pytest.raises(ValueError, match="요청 월"):
        parse_month(path, "2024-03", ["강남대로"])


def test_changed_link_metadata_is_not_silently_joined(tmp_path):
    path = tmp_path / "source.xlsx"
    workbook(path)
    _, one = parse_month(path, "2024-02", ["강남대로"])
    other = copy.deepcopy(one)
    other["metadata"][0]["방향"] = "상행"
    with pytest.raises(ValueError, match="메타데이터 변경"):
        check_metadata([one, other])


def test_frozen_corridor_must_match_observed_direction_and_length(tmp_path):
    path = tmp_path / "source.xlsx"
    workbook(path)
    _, meta = parse_month(path, "2024-02", ["강남대로"])
    cfg = {"corridors": {"a": {"status": "verified", "direction": "하행",
                               "links": [{"id": "a", "start": "A", "end": "B", "length": 100}]}}}
    check_corridors([meta], cfg)
    cfg["corridors"]["a"]["links"][0]["length"] = 999
    with pytest.raises(ValueError, match="실제 링크 속성"):
        check_corridors([meta], cfg)


def test_corrupted_cache_is_not_overwritten(tmp_path):
    path = tmp_path / "2024-02.xlsx"
    workbook(path)
    entry = {"bdwrSeq": "1"}
    (tmp_path / "2024-02.source.json").write_text(json.dumps({"sha256": "bad", "request": entry}))
    with pytest.raises(ValueError, match="캐시 해시"):
        download(None, entry, "2024-02", tmp_path)


def test_registration_checks_every_config_and_waits_24_hours(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    for f in PROTOCOL_FILES:
        (tmp_path / f).write_text("version: 1\n")
    env = {**os.environ, "GIT_AUTHOR_DATE": "2026-01-01T00:00:00+00:00", "GIT_COMMITTER_DATE": "2026-01-01T00:00:00+00:00"}
    subprocess.run(["git", "-C", str(tmp_path), "add", "--", *PROTOCOL_FILES], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "-c", "user.name=검증", "-c", "user.email=test@example.org",
                    "commit", "-qm", "계획 등록"], env=env, check=True)
    with pytest.raises(ValueError, match="24시간"):
        require_registration(tmp_path, datetime(2026, 1, 1, 23, tzinfo=UTC))
    assert require_registration(tmp_path, datetime(2026, 1, 2, tzinfo=UTC))["commits"]
    (tmp_path / "ml_config.yaml").write_text("version: 2\n")
    with pytest.raises(ValueError, match="먼저 커밋"):
        require_registration(tmp_path, datetime(2026, 1, 3, tzinfo=UTC))


def test_holdout_changes_cannot_change_fit_or_earlier_input(hourly, small_config):
    data = prepare(hourly, small_config)
    cutoff = pd.Timestamp("2023-01-17", tz="Asia/Seoul")
    changed = hourly.copy()
    changed.loc[changed.interval_start_kst >= cutoff, "speed_kmh"] += 10000
    other = prepare(changed, small_config)
    assert data.identity == other.identity
    np.testing.assert_array_equal(data.means, other.means)
    np.testing.assert_array_equal(data.calendar_means, other.calendar_means)
    keys = data.keys("pre_test")[:3]
    np.testing.assert_array_equal(data.batch(keys)[0], other.batch(keys)[0])
    pd.testing.assert_frame_equal(features(data, keys, 3, set()), features(other, keys, 3, set()))


def test_targets_never_imputed_and_windows_do_not_cross_splits(hourly, small_config):
    hole = (hourly.link_id == "a") & (hourly.interval_start_kst == pd.Timestamp("2023-01-17 01:00", tz="Asia/Seoul"))
    hourly.loc[hole, ["speed_kmh", "is_valid"]] = [np.nan, False]
    data = prepare(hourly, small_config)
    keys = data.keys("pre_test")
    start, end = bounds(small_config, "pre_test")
    assert all(start <= data.times[i] and data.times[i] + timedelta(hours=3) <= end for i, _ in keys)
    i = data.times.get_loc(pd.Timestamp("2023-01-17", tz="Asia/Seoul"))
    assert [i, data.links.index("a")] not in keys.tolist()
    assert np.isfinite(data.filled).all() and np.isnan(data.raw[i + 1, 0])
    assert data.observed[i + 1, 0] == 0


def test_ffill_three_hours_then_training_calendar_fallback(hourly, small_config):
    begin = pd.Timestamp("2023-01-17", tz="Asia/Seoul")
    hole = (hourly.link_id == "a") & hourly.interval_start_kst.between(begin, begin + timedelta(hours=4))
    hourly.loc[hole, ["speed_kmh", "is_valid"]] = [np.nan, False]
    data = prepare(hourly, small_config)
    i, j = data.times.get_loc(begin), data.links.index("a")
    assert (data.filled[i:i + 3, j] == data.raw[i - 1, j]).all()
    t = data.times[i + 3]
    assert data.filled[i + 3, j] == data.calendar_means[t.weekday() * 24 + t.hour, j]


def test_weekly_naive_target_alignment_and_common_evaluation(hourly, small_config):
    data = prepare(hourly, small_config)
    keys = data.keys("validation")[:4]
    pred = baseline("weekly_naive", data, keys)
    i, j = keys[0]
    assert pred[0, 2] == data.filled[i - 166, j]
    frame = prediction_frame(data, keys, pred, "weekly_naive", 0, "validation")
    h3 = frame[frame.horizon == 3].iloc[0]
    assert h3.target_start_kst == h3.issue_time_kst + timedelta(hours=2)
    assert_common_keys([frame, frame.copy()])
    with pytest.raises(ValueError, match="평가 키"):
        assert_common_keys([frame, frame.iloc[1:]])


def policy_hourly():
    records = []
    for date in pd.date_range("2024-05-20", "2024-08-16", tz="Asia/Seoul"):
        post = date >= pd.Timestamp("2024-06-29", tz="Asia/Seoul")
        for link, base in [("t1", 20), ("t2", 40), ("t3", 60), ("c1", 30), ("c2", 50)]:
            for hour in (17, 18, 19):
                value = base + int(post) * (7 if link.startswith("t") else 2)
                records.append((link, date + timedelta(hours=hour), value, True, ""))
    return pd.DataFrame(records, columns=["link_id", "interval_start_kst", "speed_kmh", "is_valid", "invalid_reason"])


def policy_config():
    cfg = copy.deepcopy(read_yaml("corridors.yaml"))
    cfg["corridors"] = {
        "treated": {"treated": True, "status": "verified", "source": "synthetic", "direction": "하행",
                    "links": [{"id": f"t{i}", "length": i * 10} for i in (1, 2, 3)]},
        **{f"control{i}": {"treated": False, "status": "verified", "source": "synthetic", "direction": "하행",
                          "links": [{"id": f"c{i}", "length": 10}]} for i in (1, 2)},
    }
    return cfg


def test_fixed_weights_require_all_nine_observations():
    h, cfg = policy_hourly(), policy_config()
    spec = cfg["corridors"]["treated"]
    full = daily_index(h, spec, cfg["hours"], set())
    assert full.iloc[0] == pytest.approx((20 * 10 + 40 * 20 + 60 * 30) / 60)
    h.loc[0, "is_valid"] = False
    missing = daily_index(h, spec, cfg["hours"], set())
    assert np.isnan(missing.iloc[0])


def test_policy_common_dates_calendar_index_and_known_did():
    h, cfg = policy_hourly(), policy_config()
    panel, quality = build_panel(h, cfg, {"2024-06-06", "2024-08-15"})
    assert quality["comparative"]
    assert did_point(panel, cfg["policy_date"])[0] == pytest.approx(5)
    assert 5 not in set(panel.day_idx)  # 5월 25일 토요일, 인덱스를 다시 매기지 않는다.
    assert not panel.date.between("2024-06-29", "2024-07-07").any()
    with pytest.raises(ValueError, match="날짜 집합"):
        balanced_wide(panel.iloc[1:])
    cfg["corridors"]["control1"]["status"] = "pending"
    _, quality = build_panel(h, cfg, set())
    assert not quality["comparative"]


def test_catboost_selection_checkpoint_and_data_identity(tmp_path, hourly, small_config):
    pytest.importorskip("catboost")
    from gangnam.models import predict_model, train_model
    small_config["models"]["catboost"] = {"depth": [2, 3], "learning_rate": [0.1], "iterations": 8, "early_stopping_rounds": 3}
    small_config["seeds"] = [17, 42]
    data = prepare(hourly, small_config)
    train_model("catboost", data, tmp_path, set(), {"synthetic": True})
    folder = tmp_path / "catboost"
    info = json.loads((folder / "selection.json").read_text())
    assert len(info["trials"]) == 2 and info["seeds"] == [17, 42]
    for seed in info["seeds"]:
        pred = predict_model("catboost", data, data.keys("pre_test")[:3], folder, seed, set())
        assert np.isfinite(pred[:, [0, 2]]).all()
    with pytest.raises(ValueError, match="덮어쓰지"):
        train_model("catboost", data, tmp_path, set(), {})
    changed = hourly.copy()
    changed.loc[changed.interval_start_kst >= pd.Timestamp("2023-01-17", tz="Asia/Seoul"), "speed_kmh"] += 1
    other = prepare(changed, small_config)
    with pytest.raises(ValueError, match="저장된 모델"):
        predict_model("catboost", other, other.keys("pre_test")[:3], folder, 17, set())


def test_neural_seeds_are_distinct_and_graph_backward():
    torch = pytest.importorskip("torch")
    pytest.importorskip("neuralforecast")
    from gangnam.graph import DCRNN, STGCN, transition
    from gangnam.models import network
    cfg = read_yaml("ml_config.yaml")
    a = network("dlinear", {"moving_avg_window": 25}, cfg, seed=17)
    b = network("dlinear", {"moving_avg_window": 25}, cfg, seed=42)
    assert any(not torch.equal(x, y) for x, y in zip(a.parameters(), b.parameters(), strict=True))
    graph = np.array([[0, 0.2, 0], [0, 0, 0.5], [0, 0, 0]], dtype="float32")
    np.testing.assert_allclose(transition(graph).sum(axis=1), [1, 1, 0])
    for cls in (DCRNN, STGCN):
        model = cls(graph, hidden_size=8)
        x = torch.randn(2, 168, 3, 2)
        result = model(x)
        assert result.shape == (2, 3, 3) and torch.isfinite(result).all()
        result.square().mean().backward()
        assert all(p.grad is None or torch.isfinite(p.grad).all() for p in model.parameters())


def test_weather_blanks_need_explicit_official_definition(tmp_path):
    from gangnam.weather import load_verified_weather, normalize_weather
    path, evidence, output = tmp_path / "raw.csv", tmp_path / "raw.json", tmp_path / "daily.csv"
    path.write_text("지점,일시,일강수량(mm)\n108,2024-07-08,\n108,2024-07-09,2.5\n", encoding="utf-8")
    proof = {"verified": True, "source": "synthetic", "raw_sha256": sha256(path), "unit": "mm", "blank_precipitation": "missing"}
    evidence.write_text(json.dumps(proof))
    with pytest.raises(ValueError, match="결측"):
        normalize_weather(path, evidence, output)
    proof["blank_precipitation"] = "zero"
    evidence.write_text(json.dumps(proof))
    normalize_weather(path, evidence, output)
    assert load_verified_weather(output).precipitation_mm.tolist() == [0, 2.5]


def test_forecast_cli_train_evaluate_compare_with_synthetic_inputs(tmp_path, monkeypatch, hourly, small_config):
    pytest.importorskip("pyarrow")
    spec = importlib.util.spec_from_file_location("gangnam_forecast_cli", CASE / "forecast.py")
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    monkeypatch.setattr(cli, "CASE", tmp_path)
    monkeypatch.setattr(cli, "read_yaml", lambda _: small_config)
    monkeypatch.setattr(cli, "real_data_gate", lambda: {"hashes": {"test": "synthetic"}})
    monkeypatch.setattr(cli, "read_hourly", lambda *a, **kw: hourly)
    monkeypatch.setattr(cli, "holiday_dates", lambda *a: set())
    for action in ("train", "evaluate", "compare"):
        monkeypatch.setattr(sys, "argv", ["forecast.py", action, "--run", "synthetic", "--models", "last_value", "weekly_naive"])
        cli.main()
    report = json.loads((tmp_path / "runs/synthetic/comparison-pre_test.json").read_text())
    assert {r["model"] for r in report["results"]} == {"last_value", "weekly_naive"}
    assert report["common_keys"] == 46 * 3 * 2


def test_exploratory_assumptions_are_explicit_and_do_not_verify_evidence():
    contract = copy.deepcopy(read_yaml('data_contract.yaml'))
    require_data_contract(contract)
    assert contract['checks']['hour_semantics']['status'] == 'assumed'
    contract['execution'].pop('authorization')
    with pytest.raises(ValueError, match='공식 근거'):
        require_data_contract(contract)


def test_metadata_allowlist_cannot_hide_direction_change(tmp_path):
    path = tmp_path / 'month.xlsx'
    workbook(path)
    _, one = parse_month(path, '2024-02', ['강남대로'])
    other = copy.deepcopy(one)
    other['metadata'][0]['차선수'] = 7
    result = check_metadata([one, other], {'allowed_changed_fields': ['차선수']})
    assert result['allowed_changes'][0]['field'] == '차선수'
    other['metadata'][0]['방향'] = '상행'
    with pytest.raises(ValueError, match='메타데이터 변경'):
        check_metadata([one, other], {'allowed_changed_fields': ['차선수']})


def test_train_subsample_is_stable_and_excludes_holdouts(hourly, small_config):
    from gangnam.models import sampled_train_keys
    small_config['training']['catboost_max_train_windows'] = 31
    data = prepare(hourly, small_config)
    keys = sampled_train_keys(data)
    assert len(keys) == 31
    np.testing.assert_array_equal(keys, sampled_train_keys(data))
    _, end = bounds(small_config, 'train')
    assert (data.times[keys[:, 0] + 2] < end).all()
    past, _, _ = data.batch(keys, scaled=False)
    actual = features(data, keys, 3, set())
    np.testing.assert_allclose(actual.lag168, past[:, 0])
    np.testing.assert_allclose(actual.mean24, past[:, -24:].mean(axis=1))
    np.testing.assert_array_equal(actual.hour, data.times[keys[:, 0] + 2].hour)


def test_committed_exploratory_protocol_can_run_without_24_hour_wait(tmp_path):
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
    for name in PROTOCOL_FILES:
        (tmp_path / name).write_text('version: 1\n')
    (tmp_path / 'data_contract.yaml').write_text('version: 1\nexecution:\n  mode: exploratory\n  authorization: 사용자 즉시 실행 요청\n')
    env = {**os.environ, 'GIT_AUTHOR_DATE': '2026-01-01T00:00:00+00:00', 'GIT_COMMITTER_DATE': '2026-01-01T00:00:00+00:00'}
    subprocess.run(['git', '-C', str(tmp_path), 'add', '--', *PROTOCOL_FILES], check=True)
    subprocess.run(['git', '-C', str(tmp_path), '-c', 'user.name=검증', '-c', 'user.email=test@example.org',
                    'commit', '-qm', '탐색 실행 규약'], env=env, check=True)
    result = require_registration(tmp_path, datetime(2026, 1, 1, 0, 1, tzinfo=UTC))
    assert result['mode'] == 'exploratory'
    (tmp_path / 'ml_config.yaml').write_text('version: 2\n')
    with pytest.raises(ValueError, match='먼저 커밋'):
        require_registration(tmp_path)


def test_assumed_graph_requires_exploratory_authorization(tmp_path, small_config):
    pytest.importorskip('torch')
    from gangnam.common import write_json
    from gangnam.graph import load_graph
    path = tmp_path / 'edges.csv'
    path.write_text('source_link,target_link,weight\na,b,1\nb,c,1\n')
    write_json(path.with_suffix('.source.json'), {
        'verified': False, 'status': 'assumed', 'method': 'stable_metadata_endpoints',
        'source': 'https://topis.seoul.go.kr/refRoom/openRefRoom_1.do', 'sha256': sha256(path),
        'valid_from': '2023-01-01', 'valid_to': '2024-08-31', 'node_ids': ['a', 'b', 'c']})
    contract = copy.deepcopy(read_yaml('data_contract.yaml'))
    graph, evidence = load_graph(path, ['a', 'b', 'c'], contract, small_config)
    assert graph[0, 1] == 1 and evidence['verified'] is False
    contract['execution']['mode'] = 'preregistered'
    with pytest.raises(ValueError, match='공식 근거'):
        load_graph(path, ['a', 'b', 'c'], contract, small_config)
