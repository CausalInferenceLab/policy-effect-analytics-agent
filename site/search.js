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
  const input = $("#sq"), res = $("#sres"), none = $("#snone"), verdict = $("#verdict"), idle = $("#sidle");
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
  const TYPE = { result: "결과", project: "진행 중", issue: "이슈", topic: "주제", law: "법령", lineage: "계보", dataset: "데이터" };
  function card(it) {  // 분석 결과: 판정 + 95% 범위 그림
    return `<a class="r-card v-${esc(it.cls)}" href="${esc(it.url)}"><span class="r-main">` +
      `<span class="badge ${esc(it.cls)}">${esc(it.badge)}</span><b>${esc(it.title)}</b>` +
      `<span class="r-line">${esc(it.sub)}</span><span class="r-who">${esc(it.who)}</span></span>` +
      `<span class="r-glyph">${it.g || ""}</span></a>`;
  }
  function row(it) {  // 그 밖: 한 줄짜리 목록
    const ext = /^https?:/.test(it.url);
    return `<a class="s-row t-${it.t}" href="${esc(it.url)}"${ext ? ' rel="noopener" target="_blank"' : ""}>` +
      `<span class="s-kind">${TYPE[it.t]}</span><span class="s-txt"><b>${esc(it.title)}</b>` +
      `<span>${esc(it.sub)}</span></span>${it.badge ? `<span class="s-meta">${esc(it.badge)}</span>` : ""}</a>`;
  }
  function group(t, xs) {
    const draw = t === "result" ? card : row, cls = t === "result" ? "r-list" : "s-rows";
    return `<section class="s-group"><h2>${KO[t]}<span class="n">${xs.length}</span></h2><div class="${cls}">${xs.slice(0, 8).map(draw).join("")}</div>` +
      (xs.length > 8 ? `<details class="s-more"><summary>${xs.length - 8}개 더 보기</summary><div class="${cls}">${xs.slice(8).map(draw).join("")}</div></details>` : "") +
      `</section>`;
  }
  function counts(hits) {
    document.querySelectorAll(".sf").forEach((b) => {
      const n = b.dataset.t ? hits.filter((it) => it.t === b.dataset.t).length : hits.length;
      b.querySelector(".n").textContent = hits.length ? n : "";
      b.disabled = !!b.dataset.t && hits.length > 0 && n === 0;
    });
  }
  function render(q) {
    const qn = norm(q), tks = tokens(q);
    idle.hidden = !!qn;
    if (!qn) { res.innerHTML = ""; none.hidden = true; verdict.hidden = true; counts([]); return 0; }
    const hits = items.map((it) => [it, score(it, tks, qn)]).filter(([, s]) => s > 0).sort((a, b) => b[1] - a[1]).map(([it]) => it);
    counts(hits);
    const shown = kind ? hits.filter((it) => it.t === kind) : hits;
    res.innerHTML = ORDER.map((t) => [t, shown.filter((it) => it.t === t)]).filter(([, xs]) => xs.length).map(([t, xs]) => group(t, xs)).join("");
    const results = hits.filter((it) => it.t === "result");
    const propose = `${REPO}/issues/new?template=case-proposal.yml&title=${encodeURIComponent("[작업] " + q.trim().slice(0, 60))}`;
    $("#snone-propose").href = propose;
    if (results.length) {
      const top = results[0];
      verdict.className = "v-panel v-" + top.cls;
      verdict.innerHTML = `<div class="v-head"><span class="v-label">가장 가까운 분석의 판정</span><span class="v-stamp">${esc(top.badge)}</span></div>` +
        `<div class="v-body"><div><h2><a href="${esc(top.url)}">${esc(top.title)}</a></h2><p>${esc(top.sub)}</p></div>` +
        `<div class="v-glyph">${top.g || ""}</div></div>` +
        `<div class="v-foot"><a href="${esc(top.url)}#use">인용해도 되는 문장</a><a href="${esc(top.url)}#lineage">숫자가 나온 길</a>` +
        `<a href="${esc(top.url)}#run">직접 돌려 보기</a>` +
        (results.length > 1 ? `<span>비슷한 분석 ${results.length - 1}개 더</span>` : "") + `</div>` +
        `<p class="v-note">판정은 '이 데이터와 이 비교로는'이라는 조건이 붙은 답이에요.</p>`;
      verdict.hidden = false;
    } else if (hits.length) {
      verdict.className = "v-panel v-none";
      verdict.innerHTML = `<div class="v-head"><span class="v-label">판정</span><span class="v-stamp">아직 분석 없음</span></div>` +
        `<p class="v-msg">이 정책의 효과를 잰 분석은 아직 없어요. 아래 이슈·데이터·계보로 시작할 수 있어요.</p>` +
        `<div class="v-foot"><a href="${esc(propose)}" data-track="search-propose">이 정책 분석 요청하기</a></div>`;
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
  }).catch(() => { res.innerHTML = '<p class="s-empty">검색 목록을 불러오지 못했어요. 새로고침해 보세요.</p>'; });
  input.addEventListener("input", () => run(input.value, false));
  document.addEventListener("keydown", (ev) => {  // '/' 로 검색창에 바로
    if (ev.key === "/" && document.activeElement !== input && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) {
      ev.preventDefault(); input.focus(); input.select();
    }
  });
  $("#sform").addEventListener("submit", (ev) => { ev.preventDefault(); run(input.value, true); });
  document.querySelectorAll("[data-q]").forEach((a) => a.addEventListener("click", (ev) => {
    ev.preventDefault(); input.value = a.dataset.q; run(a.dataset.q, true);
  }));
  document.querySelectorAll(".sf").forEach((b) => b.addEventListener("click", () => {
    document.querySelectorAll(".sf").forEach((x) => x.setAttribute("aria-pressed", x === b));
    kind = b.dataset.t; render(input.value);
  }));
})();
