/* 통합 검색 — api/search.json 을 받아 이 브라우저 안에서 찾습니다(서버 없음).
 * 점수: 제목에 있으면 6, 설명·키워드에 있으면 2, 그 주제의 키워드와 맞으면 3.
 * 검색어에 주제 키워드(예: 토허제)가 들어 있으면 그 주제의 항목에 3을 더합니다.
 * 통계: window.trackSearch(검색어, 결과 수) — track.js 가 다듬어서(숫자·이메일 제거) 셉니다. 꺼져 있으면 아무 일도 없음.
 */
(function () {
  const ORDER = ["result", "project", "issue", "topic", "law", "lineage", "dataset"];
  const KO = { result: "이미 확인한 분석 결과", project: "진행 중인 분석", issue: "지금 이슈인 정책", topic: "주제 · 이슈 보드",
    law: "근거 법률 · 행정규칙", lineage: "데이터 계보", dataset: "쓸 수 있는 공공데이터" };
  // 거의 모든 항목에 들어 있어 순위를 흐리는 말 — 다른 단어와 함께 쓰이면 무시
  const STOP = new Set(["효과", "정책", "분석", "진짜", "영향", "결과", "변화", "있었나", "있을까", "먹혔나", "됐나", "실제", "데이터"]);
  const PARTICLE = /(으로|에서|에게|까지|부터|은|는|이|가|을|를|의|에|로|과|와|도|만)$/;
  const $ = (s) => document.querySelector(s);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const norm = (s) => String(s || "").toLowerCase().replace(/\s+/g, "");
  const input = $("#sq"), res = $("#sres"), none = $("#snone"), verdict = $("#verdict");
  const REPO = "https://github.com/CausalInferenceLab/policy-effect-analytics-agent";
  let items = [], kind = "", logged = new Set(), timer = null;

  function tokens(q) {
    const raw = q.trim().split(/\s+/).filter(Boolean);
    let out = raw.map((t) => (t.length > 2 ? t.replace(PARTICLE, "") : t)).map(norm).filter((t) => t.length >= 2 || raw.length === 1);
    const core = out.filter((t) => !STOP.has(t));
    if (core.length) out = core;
    if (raw.length > 1 && core.length > 1) out.push(norm(raw.filter((t) => !STOP.has(norm(t))).join("")));
    return [...new Set(out)];
  }
  function score(it, tks, qn) {
    const ti = norm(it.title), su = norm(it.sub) + norm(it.kw), tk = norm(it.tk);
    let s = 0, hit = 0;
    for (const t of tks) {
      let h = 0;
      if (ti.includes(t)) h += 6;
      if (su.includes(t)) h += 2;
      if (tk.includes(t)) h += 3;
      if (h) hit++;
      s += h;
    }
    // 검색어 안에 주제 키워드가 통째로 들어 있으면(예: "토허제 효과") 그 주제 항목을 올린다
    if (it.tk && it.tk.split(" ").some((k) => k.length >= 2 && qn.includes(norm(k)))) s += 3;
    return hit || s >= 3 ? s : 0;
  }
  function row(it) {
    const ext = /^https?:/.test(it.url);
    const badge = it.badge ? `<span class="badge ${esc(it.cls || "plain")}">${esc(it.badge)}</span>` : "";
    return `<a class="s-item s-${it.t}" href="${esc(it.url)}"${ext ? ' rel="noopener"' : ""}>` +
      `<span class="s-top">${badge}${it.who ? `<span class="muted small">${esc(it.who)}</span>` : ""}</span>` +
      `<b>${esc(it.title)}</b><span class="muted small">${esc(it.sub)}</span></a>`;
  }
  function render(q) {
    const qn = norm(q), tks = tokens(q);
    if (!qn) { res.innerHTML = ""; none.hidden = true; verdict.hidden = true; return 0; }
    const hits = items.map((it) => [it, score(it, tks, qn)]).filter(([, s]) => s > 0).sort((a, b) => b[1] - a[1]).map(([it]) => it);
    const shown = kind ? hits.filter((it) => it.t === kind) : hits;
    const groups = ORDER.map((t) => [t, shown.filter((it) => it.t === t)]).filter(([, xs]) => xs.length);
    res.innerHTML = groups.map(([t, xs]) =>
      `<section class="s-group"><h2>${KO[t]} <span class="muted small">${xs.length}</span></h2><div class="s-list">${xs.slice(0, 8).map(row).join("")}</div>` +
      (xs.length > 8 ? `<details><summary class="small">${xs.length - 8}개 더 보기</summary><div class="s-list">${xs.slice(8).map(row).join("")}</div></details>` : "") +
      `</section>`).join("");
    const results = hits.filter((it) => it.t === "result");
    const propose = `${REPO}/issues/new?template=case-proposal.yml&title=${encodeURIComponent("[작업] " + q.trim().slice(0, 60))}`;
    $("#snone-propose").href = propose;
    if (results.length) {
      const top = results[0];
      verdict.innerHTML = `<p class="small muted" style="margin:0">이 질문과 가장 가까운 분석</p>` +
        `<h3 style="margin:6px 0"><a href="${esc(top.url)}">${esc(top.title)}</a></h3>` +
        `<p style="margin:0 0 6px"><span class="badge ${esc(top.cls)}">${esc(top.badge)}</span> ${esc(top.sub)}</p>` +
        `<p class="small muted" style="margin:0">판정은 '이 데이터와 이 비교로는' 이라는 조건이 붙은 답입니다. 결과 페이지에서 쓸 수 있는 문장과 한계를 함께 보세요.` +
        (results.length > 1 ? ` 비슷한 분석 ${results.length - 1}개가 더 있어요.` : "") + `</p>`;
      verdict.hidden = false;
    } else if (hits.length) {
      verdict.innerHTML = `<p style="margin:0"><b>아직 이 정책의 효과를 잰 분석은 없어요.</b> 대신 아래 이슈·데이터·계보로 시작할 수 있어요. ` +
        `<a href="${esc(propose)}" data-track="search-propose">분석 요청하기</a></p>`;
      verdict.hidden = false;
    } else verdict.hidden = true;
    none.hidden = hits.length > 0;
    return hits.length;
  }
  function log(q, n) {
    const k = norm(q);
    if (k.length < 2 || logged.has(k)) return;
    logged.add(k);
    if (window.trackSearch) window.trackSearch(q, n);
  }
  function run(q, now) {
    const n = render(q);
    try { history.replaceState(null, "", q ? "?q=" + encodeURIComponent(q) : location.pathname); } catch (e) { /* 미리보기 등 */ }
    clearTimeout(timer);
    if (now) log(q, n);
    else timer = setTimeout(() => log(q, n), 1500);
  }
  fetch("api/search.json").then((r) => r.json()).then((data) => {
    items = data;
    const q = new URLSearchParams(location.search).get("q") || "";
    input.value = q;
    if (q) run(q, true);
  }).catch(() => { res.innerHTML = '<p class="card">검색 목록을 불러오지 못했어요. 새로고침해 보세요.</p>'; });
  input.addEventListener("input", () => run(input.value, false));
  $("#sform").addEventListener("submit", (ev) => { ev.preventDefault(); run(input.value, true); });
  document.querySelectorAll("[data-q]").forEach((a) => a.addEventListener("click", (ev) => {
    ev.preventDefault(); input.value = a.dataset.q; run(a.dataset.q, true);
  }));
  document.querySelectorAll(".sf").forEach((b) => b.addEventListener("click", () => {
    document.querySelectorAll(".sf").forEach((x) => x.setAttribute("aria-pressed", x === b));
    kind = b.dataset.t; render(input.value);
  }));
})();
