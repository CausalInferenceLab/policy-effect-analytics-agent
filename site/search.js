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
  // ─── 문장 검증: 뉴스 문장이 결과가 말할 수 있는 범위를 넘는지 (키워드 규칙) ───────────
  const NULL_RE = /효과\s*(가|는|도)?\s*없|변화\s*(가|는|도)?\s*없|아무\s*변화|그대로였|실패|소용\s*없|안\s*먹혔|못\s*했|못했|헛수고/;
  const UP_RE = /늘었|늘어|증가|올랐|오르|상승|개선|좋아|활성|살아났|많아/;
  const DOWN_RE = /줄었|줄어|감소|떨어|내렸|하락|잡혔|잡았|억제|낮아|안정|적어/;
  const EFFECT_RE = /효과|덕분|때문|성공|먹혔|통했|영향/;
  const PCT_RE = /([+-]?\d+(?:\.\d+)?)\s*%/;
  function looksLikeClaim(q) {
    const t = q.trim();
    return t.length >= 12 && /\s/.test(t) && (NULL_RE.test(t) || UP_RE.test(t) || DOWN_RE.test(t) || EFFECT_RE.test(t) || PCT_RE.test(t));
  }
  const RANK = { ok: 0, inside: 1, beyond: 2, conflict: 3 };
  const MARK = { ok: ["뒷받침", "go"], inside: ["범위 안", "info"], beyond: ["결과를 넘어섬", "warn"], conflict: ["결과와 다름", "stop"] };
  function checkClaim(q, r) {
    const parts = [], v = r.v, pr = r.pr;
    const isNull = NULL_RE.test(q), up = UP_RE.test(q), down = DOWN_RE.test(q) && !up, dir = up ? 1 : down ? -1 : 0;
    const effect = !isNull && (dir !== 0 || EFFECT_RE.test(q));
    if (isNull) {
      if (v === "identified") parts.push(["conflict", "'효과가 없다'고 했지만, 이 분석은 효과 근거가 있다고 판정했어요."]);
      else if (v === "conditional") parts.push(["beyond", "판별하지 못한 것과 효과가 없는 것은 달라요. 이 자료로는 있다·없다 모두 단정할 수 없어요."]);
      else parts.push(["beyond", "이 분석은 효과를 판단하지 않았어요(판단 불가·관측 통계). '없다'고 말할 근거도 없어요."]);
    } else if (effect) {
      if (v === "identified" && pr) {
        const sign = Math.sign(pr.est);
        if (dir && dir !== sign) parts.push(["conflict", `방향이 반대예요. 분석의 추정치는 ${pr.est > 0 ? "증가" : "감소"} 쪽이에요.`]);
        else parts.push(["ok", "효과가 있었다는 말은 이 분석의 판정과 맞아요. 같은 지역·기간·지표에 한정해서 쓰세요."]);
      } else if (v === "conditional") parts.push(["beyond", "효과가 '있었다'고 말할 근거는 부족해요. 이 자료로는 효과가 있었는지 판별하지 못했어요."]);
      else if (v === "descriptive") parts.push(["beyond", "관측값의 변화는 인용할 수 있지만, 정책 '때문'이라고 할 근거는 없어요(효과 미추정)."]);
      else parts.push(["beyond", "이 설계로는 효과를 판단할 수 없었어요. 원인이라고 말할 근거가 없어요."]);
    }
    const m = q.match(PCT_RE);
    if (m) {
      let n = parseFloat(m[1]);
      if (!/^[+-]/.test(m[1]) && down) n = -n;
      if (!pr || pr.unit !== "%") parts.push(["beyond", v === "not_identified" ? "판단 불가 결과의 숫자는 진단용이라 비교하지 않아요." : "이 분석의 주 지표는 %로 비교할 수 없어요."]);
      else if (n < pr.lo || n > pr.hi) parts.push(["conflict", `${n > 0 ? "+" : ""}${n}%는 이 자료의 95% 범위(${pr.lo.toFixed(1)}% ~ ${pr.hi.toFixed(1)}%) 밖이라 자료와 맞지 않아요.`]);
      else parts.push(["inside", `${n > 0 ? "+" : ""}${n}%는 95% 범위(${pr.lo.toFixed(1)}% ~ ${pr.hi.toFixed(1)}%) 안이에요. ` + (v === "identified" ? "자료와 맞는 크기예요." : "자료와 어긋나지는 않지만, 그 크기로 판별된 것은 아니에요.")]);
    }
    if (!parts.length) parts.push(["inside", "문장에서 효과·방향·크기 주장을 찾지 못했어요. 아래 결과에서 직접 확인해 보세요."]);
    const worst = parts.reduce((a, b) => (RANK[b[0]] > RANK[a[0]] ? b : a))[0];
    return { worst, parts };
  }
  function renderClaim(q, results) {
    const box = $("#claim");
    if (!looksLikeClaim(q) || !results.length) { box.hidden = true; return; }
    const r = results[0], c = checkClaim(q, r), [lab, cls] = MARK[c.worst];
    box.className = "c-panel c-" + cls;
    box.innerHTML = `<div class="c-head"><span class="v-label">이 문장, 분석 결과로 뒷받침되나요?</span><span class="c-stamp">${lab}</span></div>` +
      `<blockquote>${esc(q)}</blockquote>` +
      `<ul class="c-parts">${c.parts.map(([k, t]) => `<li><span class="badge ${MARK[k][1]}">${MARK[k][0]}</span>${esc(t)}</li>`).join("")}</ul>` +
      (r.rules && r.rules[0] && r.rules[0][0] ? `<div class="takeaway"><span>이렇게 쓰면 결과 안에서 말할 수 있어요</span><p>${esc(r.rules[0][0])}</p></div>` : "") +
      `<p class="v-note"><a data-track="claim-record" href="${esc(REPO + "/issues/new?template=claim-review.yml&title=" + encodeURIComponent("[주장 검토] " + q.slice(0, 60)) + "&claim=" + encodeURIComponent(q.slice(0, 300)) + "&case=" + encodeURIComponent(r.url.replace(/^answers\//, "").replace(/\.html$/, "")) + "&auto=" + encodeURIComponent(lab))}">실제 기사·발표의 주장이면 검토 기록으로 남기기</a></p>` +
      `<p class="v-note">비교한 분석: <a href="${esc(r.url)}">${esc(r.title)}</a>. 키워드 규칙으로 읽은 결과라, 문장의 지역·기간·지표가 이 분석과 같은지는 직접 확인하세요. 법률 자문이나 공식 팩트체크가 아니에요.</p>`;
    box.hidden = false;
    if (window.track) window.track("claim-check");
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
    if (!qn) { res.innerHTML = ""; none.hidden = true; verdict.hidden = true; $("#claim").hidden = true; counts([]); return 0; }
    const hits = items.map((it) => [it, score(it, tks, qn)]).filter(([, s]) => s > 0).sort((a, b) => b[1] - a[1]).map(([it]) => it);
    counts(hits);
    const shown = kind ? hits.filter((it) => it.t === kind) : hits;
    res.innerHTML = ORDER.map((t) => [t, shown.filter((it) => it.t === t)]).filter(([, xs]) => xs.length).map(([t, xs]) => group(t, xs)).join("");
    const results = hits.filter((it) => it.t === "result");
    renderClaim(q, results);
    const propose = `${REPO}/issues/new?template=case-proposal.yml&title=${encodeURIComponent("[작업] " + q.trim().slice(0, 60))}`;
    $("#snone-propose").href = propose;
    if (results.length) {
      const top = results[0];
      verdict.className = "v-panel v-" + top.cls;
      verdict.innerHTML = `<div class="v-head"><span class="v-label">가장 가까운 분석의 판정</span><span class="v-stamp">${esc(top.badge)}</span>` +
        (top.rev ? `<span class="badge go">검토됨</span>` : `<span class="badge plain" title="작성자 외의 사람이 아직 검토하지 않았어요">검토 전</span>`) + `</div>` +
        `<div class="v-body"><div><h2><a href="${esc(top.url)}">${esc(top.title)}</a></h2><p>${esc(top.sub)}</p></div>` +
        `<div class="v-glyph">${top.g || ""}</div></div>` +
        (top.ro ? `<div class="takeaway"><span>${esc(top.ro.head)}</span><p>${esc(top.ro.text)}</p></div>` : "") +
        `<div class="v-foot"><a href="${esc(top.url)}#use">인용해도 되는 문장</a><a href="${esc(top.url)}#lineage">숫자가 나온 길</a>` +
        `<a href="${esc(top.url)}#run">직접 돌려 보기</a>` +
        (results.length > 1 ? `<span>비슷한 분석 ${results.length - 1}개 더</span>` : "") + `</div>` +
        `<p class="v-note">판정은 '이 데이터와 이 비교로는'이라는 조건이 붙은 답이에요.</p>`;
      verdict.hidden = false;
    } else if (hits.length) {
      const tp = hits.find((it) => it.t === "topic" && it.feas);
      const MK = { ok: ["✓", "go"], warn: ["!", "warn"], miss: ["✕", "stop"] };
      const feas = tp ? `<div class="v-feas"><p class="v-label">지금 있는 데이터로 분석할 수 있나 · <a href="${esc(tp.url)}#feasibility">${esc(tp.title)}</a></p>` +
        `<p class="v-feas-stamp c-${MK[{ go: "ok", warn: "warn", stop: "miss" }[tp.feas.verdict]][1]}">${esc(tp.feas.label)}</p>` +
        `<p class="small">${esc(tp.feas.hyp)}</p><ul class="v-checks">` +
        tp.feas.checks.map(([st, lab, det]) => `<li><span class="badge ${MK[st][1]}">${MK[st][0]}</span> <b>${esc(lab)}</b> <span class="muted small">${esc(det)}</span></li>`).join("") +
        `</ul></div>` : "";
      verdict.className = "v-panel v-none";
      verdict.innerHTML = `<div class="v-head"><span class="v-label">판정</span><span class="v-stamp">아직 분석 없음</span></div>` +
        `<p class="v-msg">이 정책의 효과를 잰 분석은 아직 없어요. 아래 이슈·데이터·계보로 시작할 수 있어요.</p>` + feas +
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
