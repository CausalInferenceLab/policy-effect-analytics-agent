"""정규화 실자료의 품질·시간 창과 메타데이터 기반 연결 가정을 기록한다."""

from __future__ import annotations

import json

import pandas as pd
from gangnam.common import CASE, read_yaml, real_data_gate, sha256, write_json
from gangnam.topis import check_corridors, check_metadata, read_hourly
from gangnam.windows import prepare


def main():
    registration = real_data_gate()
    contract, cfg = read_yaml("data_contract.yaml"), read_yaml("ml_config.yaml")
    paths = sorted((CASE / "data/metadata").glob("*.json"))
    summaries = [json.loads(p.read_text(encoding="utf-8")) for p in paths]
    metadata = check_metadata(summaries, contract.get("metadata_policy"))
    check_corridors(summaries, read_yaml("corridors.yaml"))
    hourly = read_hourly(CASE / "data/processed", verify=True)
    data = prepare(hourly, cfg)
    quality = {"registration": registration, "rows": len(hourly), "months": len(paths),
               "links_before_coverage_filter": hourly.link_id.nunique(), "selected_links": data.links,
               "invalid_reasons": {str(k): int(v) for k, v in hourly.invalid_reason.value_counts(dropna=False).items()},
               "valid_fraction": float(hourly.is_valid.mean()), "metadata": metadata,
               "prepared_identity": data.identity, "dataset_identity": data.dataset_identity,
               "splits": {name: {"windows": len(data.keys(name)), "date_range": dates}
                          for name, dates in cfg["splits"].items()}}
    write_json(CASE / "data/audit.json", quality)
    # 전체 월의 속성 일치는 위에서 검사한다. 차선 수는 연결의 근거로 쓰지 않는다.
    nodes = {m["링크아이디"]: m for m in summaries[0]["metadata"] if m["링크아이디"] in data.links}
    edges = []
    for left, a in nodes.items():
        for right, b in nodes.items():
            if left != right and (a["도로명"], a["방향"], a["종점명"]) == (b["도로명"], b["방향"], b["시점명"]):
                edges.append((left, right, 1.0))
    if not edges:
        raise ValueError("메타데이터로 구성할 수 있는 연결이 없습니다")
    target = CASE / "data/graph/edges.csv"
    target.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(edges, columns=["source_link", "target_link", "weight"]).to_csv(target, index=False)
    write_json(target.with_suffix(".source.json"), {
        "verified": False, "status": "assumed", "method": "stable_metadata_endpoints",
        "source": "https://topis.seoul.go.kr/refRoom/openRefRoom_1.do", "sha256": sha256(target),
        "valid_from": cfg["splits"]["train"][0], "valid_to": cfg["splits"]["post_test"][1],
        "node_ids": data.links, "edges": len(edges),
        "metadata_hashes": {p.name: sha256(p) for p in paths},
        "note": "유효 기간은 메타데이터 관측 범위. 시종점 이름으로 유도했으며 실제 회전 가능성·역사적 지도는 미검증"})
    print(json.dumps({k: v for k, v in quality.items() if k not in {"metadata", "registration", "selected_links"}},
                     ensure_ascii=False, indent=2))
    print(f"선택 링크 {len(data.links)}개, 메타데이터 기반 방향 연결 {len(edges)}개")


if __name__ == "__main__":
    main()
