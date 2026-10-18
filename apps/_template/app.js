// 공개 API 주소. 사이트 안(apps/<이름>/)에서는 상대 경로, 다른 곳에 배포하면 전체 주소를 씁니다.
const API = location.hostname.endsWith("github.io") || location.pathname.includes("/apps/")
  ? "../../api/"
  : "https://causalinferencelab.github.io/policy-effect-analytics-agent/api/";
const SITE = API.replace(/api\/$/, "");
const VERDICT = { identified: "효과 근거 있음", conditional: "조건부", not_identified: "판단 불가" };
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const get = (name) => fetch(API + name).then((r) => { if (!r.ok) throw new Error(name + " " + r.status); return r.json(); });

function ciBar(o) {
  // 신뢰구간을 -1 ~ +1 범위의 막대로 (로그 지표 기준). 0 위치에 세로선.
  const [lo, hi] = o.ci;
  if (lo == null || hi == null) return "";
  const x = (v) => Math.max(0, Math.min(100, (v + 1) * 50));
  return `<div class="ci" title="95% 신뢰구간 ${lo.toFixed(3)} ~ ${hi.toFixed(3)}"><b style="left:50%"></b><i style="left:${x(lo)}%;width:${Math.max(1, x(hi) - x(lo))}%"></i></div>`;
}

function render(t, issues, results, lineage) {
  const iss = issues.filter((i) => i.topic === t.id);
  const res = results.filter((r) => r.topic === t.id);
  const lins = lineage.lineages.filter((l) => l.topic === t.id);
  const recent = (t.legal && t.legal.recent) || [];
  let h = `<div class="card"><b>${esc(t.name)}</b><p>${esc(t.question)}</p></div>`;
  h += `<h2>지금 이슈 ${iss.length}개</h2>` + (iss.map((i) => `<div class="card"><div class="row"><b>${esc(i.name)}</b><span class="muted">${esc(i.effective)}</span></div><p class="muted">${esc(i.issue)}</p></div>`).join("") || `<p class="muted">없음</p>`);
  h += `<h2>최근 바뀐 법령</h2>` + (recent.length ? `<ol>${recent.map((r) => `<li>${esc(r.announced)} ${esc(r.name)} <span class="muted">${esc(r.change)}</span></li>`).join("")}</ol>` : `<p class="muted">수집된 법령 없음</p>`);
  h += `<h2>데이터 계보 ${lins.length}개</h2>` + (lins.map((l) => `<div class="card"><b>${esc(l.title)}</b> <span class="muted">by ${esc(l.owner)}</span><ol>${l.steps.map((s) => `<li>${esc(s.label || s.ref || s.id)} <span class="muted">${esc(s.kind)}${s.how ? " · " + esc(s.how) : ""}</span></li>`).join("")}</ol></div>`).join("") || `<p class="muted">아직 없음 — 트랙 A에서 만들 수 있습니다</p>`);
  h += `<h2>분석 결과 ${res.length}개</h2>` + (res.map((r) => `<div class="card"><div class="row"><b>${esc(r.title)}</b>${r.synthetic ? '<span class="badge conditional">시뮬레이션</span>' : ""}</div>
      ${r.outcomes.map((o) => `<div style="margin-top:8px"><div class="row"><span>${esc(o.name)}</span><span class="badge ${o.verdict}">${VERDICT[o.verdict] || esc(o.verdict)}</span><span class="muted">추정 ${o.estimate?.toFixed(3)} · p=${o.p_value}</span></div>${ciBar(o)}</div>`).join("")}
      ${r.figures[0] ? `<img alt="${esc(r.title)} 그림" src="${SITE + r.figures[r.figures.length - 1]}">` : ""}</div>`).join("") || `<p class="muted">아직 없음 — 트랙 B에서 만들 수 있습니다</p>`);
  document.getElementById("out").innerHTML = h;
}

Promise.all([get("index.json"), get("topics.json"), get("issues.json"), get("results.json"), get("lineage.json")])
  .then(([index, topics, issues, results, lineage]) => {
    document.getElementById("terms").textContent = index.terms + " · 데이터 생성: " + index.generated_at;
    const sel = document.getElementById("topic");
    sel.innerHTML = topics.map((t) => `<option value="${esc(t.id)}">${esc(t.name)}</option>`).join("");
    const first = topics.find((t) => results.some((r) => r.topic === t.id)) || topics[0];
    sel.value = first.id;
    const show = () => render(topics.find((t) => t.id === sel.value), issues, results, lineage);
    sel.onchange = show;
    show();
  })
  .catch((e) => { document.getElementById("out").innerHTML = `<p>API를 불러오지 못했습니다: ${esc(e.message)}</p>`; });
