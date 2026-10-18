"""트랙 페이지 본문 — 데이터 계보(lineage.html, 트랙 A)와 서비스·API(apps.html, 트랙 C)."""

from __future__ import annotations

from collections import Counter

EMPTY = '<p class="muted small">아직 없음</p>'
REPO = "https://github.com/CausalInferenceLab/policy-effect-analytics-agent"
COLS = [("이슈 · 정책", 0), ("원천 데이터", 1), ("가공", 2), ("지표", 3)]
KIND_KO = {
    "issue": "이슈",
    "policy": "정책",
    "dataset": "원천 데이터",
    "transform": "가공",
    "metric": "지표",
}
API_DOC = [
    ("index.json", "목록 · 생성 시각 · 이용 조건"),
    ("topics.json", "주제 (세 가지 확인 상태, 사건, 근거 법률과 최근 개정)"),
    ("issues.json", "지금 이슈인 정책 (시작일, 비교 대상, 설계, 쓰는 데이터)"),
    ("datasets.json", "데이터 지도 (역할 · 단위 · 받는 법 · 이용 조건)"),
    ("legal/housing-regulation.json", "법제처에서 모은 법령·행정규칙·조례 목록 (주제마다 하나)"),
    ("lineage.json", "데이터 계보 (개수 = 계보 파일 수) — 트랙 A 산출물"),
    ("results.json", "분석 결과: 판정 · 추정치 · 신뢰구간 · 그림 — 트랙 B 산출물"),
]


def _lineage_card(lin, e, issues_by_id, ds_by_id) -> str:
    from core.discovery.lineage import depth

    d = depth(lin)
    cases = sorted({c for s in lin.steps for c in s.used_by})
    cols = []
    for title, k in COLS:
        cards = []
        for s in lin.steps:
            if d[s.id] != k and not (k == 3 and d[s.id] > 3):
                continue
            if s.kind == "issue":
                name = issues_by_id.get(s.ref, s.ref)
                link = f"issues.html#{s.ref}"
            elif s.kind == "dataset" and s.ref:
                name = ds_by_id.get(s.ref, (s.ref, ""))[0]
                link = ds_by_id.get(s.ref, ("", ""))[1]
            else:
                name, link = s.title, s.source or s.url
            title_html = f'<a href="{e(link)}">{e(name)}</a>' if link else e(name)
            meta = [KIND_KO[s.kind]] + ([e(s.date)] if s.date else [])
            body = f"<p class='small' style='margin:4px 0 0'>{e(s.how)}</p>" if s.how else ""
            body += (
                f"<p class='muted small' style='margin:4px 0 0'>{e(s.note)}</p>" if s.note else ""
            )
            ins = (
                f"<p class='muted small' style='margin:4px 0 0'>← {', '.join(e(i) for i in s.inputs)}</p>"
                if s.inputs
                else ""
            )
            keys = (
                f"<p class='muted small' style='margin:2px 0 0'>키: {', '.join(e(x) for x in s.keys)}</p>"
                if s.keys
                else ""
            )
            cards.append(
                f'<div class="lin-step k-{s.kind}"><span class="muted small">{" · ".join(meta)} · <code>{e(s.id)}</code></span>'
                f"<div><b>{title_html}</b></div>{body}{keys}{ins}</div>"
            )
        cols.append(
            f'<div class="lin-col"><div class="lin-head">{title}</div>{"".join(cards)}</div>'
        )
    case_links = "".join(
        f'<div class="lin-step k-case"><b><a href="{REPO}/tree/main/cases/{e(c)}">{e(c)}</a></b></div>'
        for c in cases
    )
    cols.append(f'<div class="lin-col"><div class="lin-head">분석</div>{case_links or EMPTY}</div>')
    return (
        f'<div class="card" style="margin-bottom:14px" id="{e(lin.id)}"><h3>{e(lin.title)}</h3>'
        f"<p class='muted small'>작성 {e(lin.owner)} · 주제 <a href='topics/{e(lin.topic)}.html'>{e(lin.topic)}</a> · "
        f"<a href='{REPO}/blob/main/catalog/lineage/{e(lin.id)}.yaml'>YAML 보기</a></p>"
        + (f"<p>{e(lin.question)}</p>" if lin.question else "")
        + f'<div class="lin-grid">{"".join(cols)}</div></div>'
    )


def lineage_body(e, topics, issues, datasets, lineages, results) -> str:
    issues_by_id = {i.id: i.name for i in issues}
    ds_by_id = {d.id: (d.name, d.url) for d in datasets}
    # 주제별 연결 상태: 트랙 A가 어디를 채우면 좋을지 보여 준다
    rows = []
    for t in topics:
        ds = [d for d in datasets if t.id in d.topics]
        roles = Counter(r for d in ds for r in d.roles)
        n_lin = sum(lin.topic == t.id for lin in lineages)
        n_res = sum(r["topic"] == t.id for r in results)
        laws = len(t.legal.laws) if t.legal else 0
        gaps = [
            lab
            for ok, lab in (
                (roles["treatment"], "처치 데이터"),
                (roles["outcome"], "결과 데이터"),
                (roles["covariate"], "통제 데이터"),
                (n_lin, "계보"),
            )
            if not ok
        ]
        gap = f'<span class="badge warn">{", ".join(gaps)}</span>' if gaps else "—"
        rows.append(
            f"<tr><td><a href='topics/{t.id}.html'>{e(t.name)}</a></td>"
            f"<td>{sum(i.topic == t.id for i in issues)}</td><td>{laws}</td>"
            f"<td>{roles['treatment']} · {roles['outcome']} · {roles['covariate']}</td>"
            f"<td>{n_lin}</td><td>{n_res}</td><td>{gap}</td></tr>"
        )
    cards = "".join(_lineage_card(lin, e, issues_by_id, ds_by_id) for lin in lineages)
    return f"""
<div class="hero" style="padding-bottom:0"><span class="eyebrow">트랙 A · 데이터 온톨로지</span>
<h1>데이터 계보</h1>
<p class="lede">공공 이슈에서 출발해 정책 · 원천 데이터 · 가공 · 지표를 거쳐 분석까지 이어지는 길입니다.
"이 숫자는 어디서 와서 어떻게 만들어졌나"를 누구나 따라갈 수 있게 적습니다.</p></div>

<section style="padding-top:28px"><h2>주제별 연결 상태</h2><p class="sub">빈칸이 트랙 A가 채울 곳입니다. 데이터는 처치 · 결과 · 통제 개수입니다.</p>
<div class="tablewrap"><table><tr><th>주제</th><th>이슈</th><th>근거 법률</th><th>데이터 (처치·결과·통제)</th><th>계보</th><th>분석 결과</th><th>비어 있는 것</th></tr>{"".join(rows)}</table></div></section>

<section><h2>계보 {len(lineages)}개</h2><p class="sub">한 파일이 한 길입니다. 왼쪽에서 오른쪽으로 읽고, ← 는 그 단계의 입력입니다.</p>
{cards or "<p class='card'>아직 없습니다. 트랙 A에서 첫 계보를 만들어 주세요.</p>"}</section>

<section><h2>계보 만들기</h2>
<div class="grid3">
<div class="card"><div class="icon">1</div><h3>이슈 고르기</h3><p class="muted"><a href="issues.html">지금 이슈</a>나 사이트 질문에서 하나를 고르고, 주제 페이지의 관련 법령에서 정책 시작 근거를 찾습니다.</p></div>
<div class="card"><div class="icon">2</div><h3>데이터 찾고 잇기</h3><p class="muted"><code>catalog/lineage/_template.yaml</code>을 복사해 원천 데이터 → 가공 → 지표를 적습니다. 새 데이터는 <code>datasets.yaml</code>에도 추가합니다.</p></div>
<div class="card"><div class="icon">3</div><h3>검사하고 PR</h3><p class="muted"><code>make lineage</code>로 참조가 맞는지 확인하고 PR을 올립니다. 합쳐지면 이 페이지와 <code>api/lineage.json</code>에 나옵니다.</p></div>
</div><div class="cta"><a class="btn primary" href="{REPO}/blob/main/docs/tracks/ontology.md">트랙 A 가이드</a>
<a class="btn ghost" href="api/lineage.json">api/lineage.json</a></div></section>
"""


def apps_body(e, apps, index) -> str:
    cards = []
    for a in apps:
        href = a["url"] or (f"apps/{a['slug']}/" if a["has_page"] else None)
        badge = '<span class="badge info">템플릿 · 예시</span> ' if a["template"] else ""
        cards.append(
            f'<div class="card"><h3>{badge}{e(a["title"])}</h3><p class="muted">{e(a["description"])}</p>'
            f"<p class='small'>만든 사람 {e(a['owner'])} · 쓰는 API: {', '.join(e(u) for u in a['uses']) or '—'}</p>"
            + (
                f'<div class="cta" style="margin-top:8px"><a class="btn primary" href="{e(href)}">열기</a>'
                if href
                else "<div class='cta'>"
            )
            + f' <a class="btn ghost" href="{REPO}/tree/main/apps/{e(a["slug"])}">코드</a></div></div>'
        )
    counts = index.get("counts", {})
    api_rows = "".join(
        f"<tr><td><a href='api/{p}'><code>api/{p}</code></a></td><td>{e(desc)}</td>"
        f"<td>{counts.get(p, '')}</td></tr>"
        for p, desc in API_DOC
    )
    return f"""
<div class="hero" style="padding-bottom:0"><span class="eyebrow">트랙 C · 서비스 개발</span>
<h1>서비스</h1>
<p class="lede">분석 Cycle에서 나온 데이터로 만든 웹·앱 서비스입니다. 모든 데이터는 아래 공개 API로 열려 있어,
서버 없이 브라우저에서 바로 불러 쓸 수 있습니다.</p></div>

<section style="padding-top:28px"><h2>서비스 {len(apps)}개</h2>
<div class="grid">{"".join(cards) or "<p class='card'>아직 없습니다.</p>"}</div></section>

<section><h2>공개 API</h2><p class="sub">매일 다시 만들어집니다 (생성 {e(index.get("generated_at", ""))}). 주소 앞에
<code>https://causalinferencelab.github.io/policy-effect-analytics-agent/</code>를 붙여 어디서든 읽을 수 있습니다.</p>
<div class="tablewrap"><table><tr><th>주소</th><th>내용</th><th>개수</th></tr>{api_rows}</table></div>
<p class="muted small">{e(index.get("terms", ""))}</p>
<pre class="code"><code>const r = await fetch("https://causalinferencelab.github.io/policy-effect-analytics-agent/api/results.json");
const results = await r.json();   // [{{case, topic, title, verdict, outcomes:[{{name, estimate, ci, p_value, verdict}}], figures}}]</code></pre></section>

<section><h2>서비스 만들기</h2>
<div class="grid3">
<div class="card"><div class="icon">1</div><h3>복사하기</h3><p class="muted"><code>cp -r apps/_template apps/&lt;내ID&gt;-&lt;서비스&gt;</code> 후 <code>app.yaml</code>에 이름·설명을 적습니다.</p></div>
<div class="card"><div class="icon">2</div><h3>만들기</h3><p class="muted"><code>index.html</code>·<code>app.js</code>를 고칩니다. <code>make site</code>로 내 컴퓨터에서 바로 확인합니다.</p></div>
<div class="card"><div class="icon">3</div><h3>공개하기</h3><p class="muted">PR이 합쳐지면 <code>/apps/&lt;폴더 이름&gt;/</code>에서 열립니다. 다른 곳에 배포했다면 <code>app.yaml</code>의 <code>url</code>에 적습니다.</p></div>
</div><div class="cta"><a class="btn primary" href="{REPO}/blob/main/docs/tracks/service.md">트랙 C 가이드</a></div></section>
"""
