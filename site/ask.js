/* 대화창 — "궁금한 정책 이야기를 적어 보세요"
 *
 * 두 가지 방식으로 답합니다.
 *  1) 가이드 모드(키 없이): 카탈로그(주제·이슈·데이터셋)를 규칙으로 찾아 대화처럼 안내합니다.
 *  2) AI 모드: 사용자가 넣은 자기 AI 키로 브라우저가 직접 모델을 부릅니다. 키는 이 페이지 메모리에만 있고
 *     어디에도 저장·전송되지 않습니다(새로고침하면 사라짐). 서버가 없어도 동작합니다.
 * 대화에서 나온 질문·제안은 "제안으로 올리기"로 GitHub 이슈가 되어 오픈소스에 반영됩니다.
 */
(function () {
  const CAT = JSON.parse(document.getElementById("catalog").textContent);
  const REPO = CAT.repo;
  const $ = (s) => document.querySelector(s);
  const log = $("#chat-log"), input = $("#q"), form = $("#chat-form");
  const state = { messages: [], topic: null, issue: null, mode: "guide", key: "", pending: null };

  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const norm = (s) => s.replace(/\s+/g, "").toLowerCase();
  const byId = (arr) => Object.fromEntries(arr.map((x) => [x.id, x]));
  const T = byId(CAT.topics), I = byId(CAT.issues), D = byId(CAT.datasets);
  const ROLE = { treatment: "처치 · 누가 언제", outcome: "결과 · 무엇이 변했나", covariate: "통제 · 다른 요인" };
  const GATE = { when: "언제 시작했나", who: "누가 받았나", what: "무엇으로 재나" };
  const STATUS = { pass: "통과", check: "확인 필요", key: "데이터 키 필요", fail: "탈락" };

  // ─── 화면 ───────────────────────────────────────────────────────────
  function bubble(role, html, actions) {
    const el = document.createElement("div");
    el.className = "msg " + role;
    el.innerHTML = `<div class="who">${role === "user" ? "나" : "플랫폼"}</div><div class="body">${html}</div>`;
    if (actions && actions.length) {
      const bar = document.createElement("div");
      bar.className = "chips";
      actions.forEach(([label, fn]) => {
        const b = document.createElement("button");
        b.type = "button"; b.className = "chip"; b.textContent = label;
        b.onclick = () => fn();
        bar.appendChild(b);
      });
      el.appendChild(bar);
    }
    log.appendChild(el);
    log.hidden = false;
    el.scrollIntoView({ block: "nearest", behavior: "smooth" });
    return el;
  }
  function toPlain(html) {
    const d = document.createElement("textarea");
    d.innerHTML = html.replace(/<\/(p|li|pre)>|<br>/g, "\n").replace(/<li>/g, "- ").replace(/<[^>]+>/g, "");
    return d.value.replace(/[ \t]+/g, " ").replace(/\n\s*/g, "\n").trim();
  }
  function say(html, actions, plain) {
    state.messages.push({ role: "assistant", content: plain || toPlain(html) });
    return bubble("bot", html, actions);
  }

  // ─── 가이드 모드: 규칙 기반 대화 ─────────────────────────────────────
  function matchTopic(text) {
    const t = norm(text);
    let best = null, bs = 0, hits = [];
    for (const tp of CAT.topics) {
      const h = tp.keywords.filter((k) => t.includes(norm(k)));
      const s = h.reduce((a, k) => a + Math.min(norm(k).length, 6), 0);
      if (s > bs) { bs = s; best = tp; hits = h; }
    }
    return best ? { topic: best, hits } : null;
  }
  function matchIssue(text, topic) {
    const t = norm(text);
    const cands = CAT.issues.filter((i) => !topic || i.topic === topic.id);
    let best = null, bs = 0;
    for (const i of cands) {
      const words = (i.name + " " + i.issue + " " + i.treatment).split(/[\s·,()—\-]+/).filter((w) => w.length >= 2);
      // 완전히 같은 말은 1점, 앞 두 글자만 같으면 0.5점 (예: "강남" ↔ "강남3구")
      const s = words.reduce((a, w) => a + (t.includes(norm(w)) ? 1 : w.length >= 3 && t.includes(norm(w).slice(0, 2)) ? 0.5 : 0), 0);
      if (s > bs) { bs = s; best = i; }
    }
    return best;
  }
  const dsLink = (d) => `<a href="${esc(d.url)}" target="_blank" rel="noopener">${esc(d.name)}</a> <span class="muted small">${esc(d.space)}×${esc(d.time)} · ${d.access === "open_api" ? "오픈API" : "파일"}(${esc(d.approval)})</span>`;

  function topicReply(m) {
    const tp = m.topic;
    state.topic = tp;
    const issues = CAT.issues.filter((i) => i.topic === tp.id);
    const ds = CAT.datasets.filter((d) => d.topics.includes(tp.id));
    const cnt = (r) => ds.filter((d) => d.roles.includes(r)).length;
    const gates = Object.entries(tp.gates).map(([k, g]) => `<li>${GATE[k]}: <b>${STATUS[g.status]}</b> — ${esc(g.note)}</li>`).join("");
    const iss = issues.length
      ? `<p>이 주제에서 지금 이슈인 정책은 ${issues.length}개입니다.</p><ul>${issues.map((i) => `<li><a href="issues.html#${i.id}">${esc(i.name)}</a> <span class="muted small">(${esc(i.effective)})</span></li>`).join("")}</ul>`
      : "";
    say(
      `<p><b>${esc(tp.name)}</b> 주제로 보입니다. <span class="muted small">(찾은 말: ${m.hits.map(esc).join(", ")})</span></p>
       <p>질문 하나만 보지 않고, 이 주제의 정책을 모두 모아 비교합니다. ${esc(tp.question)}</p>${iss}
       <p>분석 전에 확인할 세 가지:</p><ul>${gates}</ul>
       <p>받을 수 있는 데이터 ${ds.length}개 — 처치 ${cnt("treatment")} · 결과 ${cnt("outcome")} · 통제 ${cnt("covariate")}</p>
       <p>무엇부터 해볼까요?</p>`,
      [
        ["분석 계획 초안", () => planReply(state.issue || issues[0] || null)],
        ["받을 수 있는 데이터", () => dataReply()],
        ["조심할 점", () => pitfallReply(state.issue || issues[0] || null)],
        ["제안으로 올리기", () => propose()],
      ],
    );
  }
  function dataReply() {
    const tp = state.topic;
    if (!tp) return say("먼저 궁금한 정책 이야기를 적어 주세요.");
    const ds = CAT.datasets.filter((d) => d.topics.includes(tp.id));
    const block = ["treatment", "outcome", "covariate"].map((r) => {
      const xs = ds.filter((d) => d.roles.includes(r));
      return xs.length ? `<p><b>${ROLE[r]}</b></p><ul>${xs.slice(0, 5).map((d) => `<li>${dsLink(d)}</li>`).join("")}</ul>` : `<p><b>${ROLE[r]}</b>: 아직 정리된 데이터가 없습니다. 찾으면 제안해 주세요.</p>`;
    }).join("");
    say(`${block}<p class="muted small">전체 목록과 검색은 <a href="data.html">데이터 지도</a>에 있습니다.</p>`,
      [["분석 계획 초안", () => planReply(null)], ["제안으로 올리기", () => propose()]]);
  }
  function pitfallReply(issue) {
    const tp = state.topic;
    const pits = [...(issue ? issue.pitfalls : []), ...(tp ? tp.pitfalls : [])];
    if (!pits.length) return say("아직 정리된 주의점이 없습니다. 공통으로는 ① 정책 전 추세가 나란했는지, ② 같은 시기의 다른 정책, ③ 옆 지역으로 효과가 번지는지를 먼저 확인합니다.");
    say(`<ul>${pits.map((p) => `<li>${esc(p)}</li>`).join("")}</ul>`, [["분석 계획 초안", () => planReply(issue)]]);
  }
  const DESIGN = { did_simultaneous: "event_study", did_staggered: "event_study", scm: "did", its: "its" };
  const DESIGN_KO = { did_simultaneous: "이중차분", did_staggered: "시차 도입 이중차분(준비 중)", scm: "합성통제(준비 중)", its: "단절 시계열" };
  function planReply(issue) {
    const tp = state.topic;
    issue = issue || state.issue || (tp && CAT.issues.find((i) => i.topic === tp.id));
    if (!issue) {
      return say("이 주제에는 아직 정리된 이슈가 없어 초안의 빈칸이 많습니다. 정책 이름과 시작일, 정책을 받은 곳을 알려 주시면 채워 드릴게요.");
    }
    state.issue = issue;
    const ds = issue.datasets.map((x) => D[x]).filter(Boolean);
    const yaml = [
      `case_id: <내ID>-${issue.id}`,
      `title: "${issue.name}"`,
      `question: >\n  ${issue.issue}`,
      `synthetic_data: false`,
      `unit: {name: 시군구, id_col: region_id}   # 데이터에 맞게`,
      `time: {col: month_idx, freq: month, start: 0, end: 24}`,
      `treatment:\n  definition: "${issue.treatment}"\n  group_col: treated\n  treat_time: 12   # 시작일 ${issue.effective} 에 해당하는 인덱스`,
      `control:\n  definition: "${issue.control}"\n  rationale: "정책이 없었다면의 추세를 대신 보여주는 이유"`,
      `outcomes:\n${issue.outcomes.map((o, k) => `  - name: ${o}\n    col: y${k + 1}\n    definition: "측정 방법"${k === 0 ? "\n    primary: true" : ""}`).join("\n")}`,
      `estimator: {method: ${DESIGN[issue.design]}, cluster_col: region_id}   # ${DESIGN_KO[issue.design]}`,
      `assumptions:\n  - {name: 평행추세, description: "정책 전 두 집단이 나란히 움직임", check: pretrend_test}`,
      `refutations:\n  - {kind: placebo_time, params: {shift: 3}}`,
      `abstention:\n  - {when: pretrend_rejected, verdict: not_identified}\n  - {when: ci_crosses_zero, verdict: conditional}`,
      `data_sources:\n${ds.map((d) => `  - name: "${d.name}"\n    provider: "${d.provider}"\n    url: "${d.url}"\n    license: ${d.license === "KOGL-1" || d.license === "KOGL-3" ? d.license : "other"}`).join("\n")}`,
    ].join("\n");
    state.plan = yaml;
    say(
      `<p><b>${esc(issue.name)}</b> 분석 계획 초안입니다. <code>cases/_template</code>을 복사한 폴더의 <code>plan.yaml</code>에 붙여 넣고, 데이터를 보기 전에 커밋하세요.</p>
       <pre class="code"><code>${esc(yaml)}</code></pre>`,
      [["복사", () => navigator.clipboard && navigator.clipboard.writeText(yaml)], ["조심할 점", () => pitfallReply(issue)], ["제안으로 올리기", () => propose()]],
      `분석 계획 초안(${issue.name}) — 전체는 '정리된 제안' 칸에 있습니다.`,
    );
  }
  function unknownReply(text) {
    state.pending = { question: text, step: 0, answers: [] };
    say(
      `<p>아직 정리된 주제가 아닙니다. 새 주제로 함께 만들어 볼까요? 세 가지만 알려 주세요.</p>
       <ol><li>어떤 정책이고 <b>언제</b> 시작했나요?</li><li><b>누가</b> 받았고, 누가 안 받았나요?</li><li><b>무엇</b>이 달라졌는지 알고 싶나요?</li></ol>
       <p class="muted small">한 번에 적어도 되고, 하나씩 적어도 됩니다. 다 모이면 제안으로 올릴 수 있게 정리해 드립니다.</p>`,
      [["바로 제안으로 올리기", () => propose()], ["주제 목록 보기", () => (location.hash = "#topics")]],
    );
  }
  function guide(text) {
    const t = norm(text);
    if (state.pending && !matchTopic(text)) {
      state.pending.answers.push(text);
      if (state.pending.answers.length < 3 && text.length < 40) {
        const next = ["누가 받았고, 누가 안 받았나요?", "무엇이 달라졌는지 알고 싶나요?"][state.pending.answers.length - 1];
        return say(next || "고맙습니다.");
      }
      return say("정리됐습니다. 아래 버튼으로 올리면 이슈가 만들어지고, 확인을 거쳐 카탈로그에 새 주제로 들어갑니다.", [["제안으로 올리기", () => propose()]]);
    }
    if (/계획|plan|초안/.test(t) && state.topic) return planReply(matchIssue(text, state.topic));
    if (/데이터|api|어디서/.test(t) && state.topic) return dataReply();
    if (/조심|함정|주의|한계/.test(t) && state.topic) return pitfallReply(matchIssue(text, state.topic));
    const m = matchTopic(text);
    if (m) {
      state.issue = matchIssue(text, m.topic);
      return topicReply(m);
    }
    return unknownReply(text);
  }

  // ─── AI 모드: 사용자 키로 브라우저에서 직접 호출 ─────────────────────────
  function systemPrompt() {
    const compact = {
      topics: CAT.topics.map((t) => ({ id: t.id, name: t.name, question: t.question, gates: t.gates })),
      issues: CAT.issues.map((i) => ({ id: i.id, name: i.name, topic: i.topic, effective: i.effective, treatment: i.treatment, control: i.control, outcomes: i.outcomes, design: i.design, datasets: i.datasets, pitfalls: i.pitfalls })),
      datasets: CAT.datasets.map((d) => ({ id: d.id, name: d.name, provider: d.provider, roles: d.roles, space: d.space, time: d.time, access: d.access, approval: d.approval, url: d.url, topics: d.topics })),
    };
    return `너는 한국 공공데이터로 정책 효과를 확인하는 오픈소스 프로젝트의 안내자다. 한국어로 짧고 쉬운 문장으로 답한다.
규칙:
1. 사용자의 이야기를 '주제'로 연결한다. 화제가 된 정책 하나만 골라 분석하지 않고, 그 주제의 정책 전체를 모아 비교하도록 안내한다.
2. 분석 전에 세 가지를 확인한다: 언제 시작했나(공식 날짜), 누가 받았나(받은 곳과 안 받은 곳), 무엇으로 재나(전후 데이터).
3. 데이터셋은 아래 카탈로그에 있는 것만 이름과 URL로 추천한다. 카탈로그에 없으면 "카탈로그에 없음, 공공데이터포털에서 찾아 제안해 달라"고 말한다. 데이터 ID나 날짜를 지어내지 않는다.
4. 효과가 '있다/없다'를 단정하지 않는다. 너는 결과를 계산하지 않는다. 방법은 이중차분·시차 도입 이중차분·합성통제·단절 시계열 중에서 데이터 모양에 맞게 제안만 한다.
5. 이 프로젝트는 공식 평가가 아니다. 공식 결과처럼 말하지 않는다.
6. 카탈로그에 없는 새 주제·데이터·이슈를 사용자와 정리했다면 답 마지막에 다음 형식의 블록을 붙인다:
\`\`\`proposal
{"type":"topic|dataset|issue","title":"...","summary":"...","when":"...","who":"...","what":"...","datasets":["url 또는 이름"]}
\`\`\`
카탈로그(JSON):
${JSON.stringify(compact)}`;
  }
  async function callAI() {
    const provider = $("#ai-provider").value, model = $("#ai-model").value.trim(), key = state.key;
    const msgs = state.messages.filter((m) => m.role === "user" || m.role === "assistant").slice(-12);
    if (provider === "anthropic") {
      const r = await fetch("https://api.anthropic.com/v1/messages", {
        method: "POST",
        headers: { "content-type": "application/json", "x-api-key": key, "anthropic-version": "2023-06-01", "anthropic-dangerous-direct-browser-access": "true" },
        body: JSON.stringify({ model: model || "claude-sonnet-5", max_tokens: 1200, system: systemPrompt(), messages: msgs }),
      });
      const j = await r.json();
      if (!r.ok) throw new Error((j.error && j.error.message) || r.status);
      return j.content.map((c) => c.text || "").join("");
    }
    const base = $("#ai-base").value.trim().replace(/\/$/, "") || "http://localhost:11434/v1";
    const r = await fetch(base + "/chat/completions", {
      method: "POST",
      headers: Object.assign({ "content-type": "application/json" }, key ? { authorization: "Bearer " + key } : {}),
      body: JSON.stringify({ model: model || "qwen2.5:7b", messages: [{ role: "system", content: systemPrompt() }, ...msgs] }),
    });
    const j = await r.json();
    if (!r.ok) throw new Error((j.error && j.error.message) || r.status);
    return j.choices[0].message.content;
  }
  function renderAI(text) {
    const m = text.match(/```proposal\s*([\s\S]*?)```/);
    if (m) { try { state.proposal = JSON.parse(m[1]); } catch (_) { state.proposal = { summary: m[1] }; } }
    const clean = text.replace(/```proposal[\s\S]*?```/, "").trim();
    const html = esc(clean)
      .replace(/```(\w+)?\n([\s\S]*?)```/g, (_, __, c) => `<pre class="code"><code>${c}</code></pre>`)
      .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")
      .replace(/(https?:\/\/[^\s)<]+)/g, '<a href="$1" target="_blank" rel="noopener">$1</a>')
      .split(/\n{2,}/).map((p) => `<p>${p.replace(/\n/g, "<br>")}</p>`).join("");
    state.messages.push({ role: "assistant", content: text });
    bubble("bot", html + (state.proposal ? `<p class="muted small">새 제안이 정리됐습니다: ${esc(state.proposal.title || state.proposal.summary || "")}</p>` : ""), [["제안으로 올리기", () => propose()]]);
  }

  // ─── 대화 → GitHub 이슈 (오픈소스에 반영) ─────────────────────────────
  // GitHub 이슈 작성 주소는 너무 길면 열리지 않습니다(한글은 한 글자가 9자로 늘어남).
  // 주소에는 질문·주제·제안을 먼저 넣고 대화는 남는 만큼만 넣습니다. 잘렸으면 전체 대화를 클립보드에 복사합니다.
  const URL_BUDGET = 7000;
  function issueUrl(fields) {
    return `${REPO}/issues/new?${new URLSearchParams(Object.assign({ template: "site-question.yml" }, fields)).toString()}`;
  }
  function fit(text, room) {
    if (encodeURIComponent(text).length <= room) return text;
    let lo = 0, hi = text.length;
    while (lo < hi) { const mid = (lo + hi + 1) >> 1; encodeURIComponent(text.slice(-mid)).length + 60 <= room ? (lo = mid) : (hi = mid - 1); }
    return "…(앞부분 생략, 전체 대화는 아래에 붙여 넣어 주세요)\n" + text.slice(-lo);
  }
  function propose() {
    const first = state.messages.find((m) => m.role === "user");
    const q = (first ? first.content : input.value.trim()).slice(0, 300);
    const convo = state.messages.map((m) => `${m.role === "user" ? "Q" : "A"}: ${m.content}`).join("\n\n");
    const prop = state.proposal ? JSON.stringify(state.proposal, null, 2) : state.plan || (state.pending ? [state.pending.question, ...state.pending.answers].join("\n") : "");
    const base = {
      title: "[사이트 질문] " + q.slice(0, 60),
      question: q,
      topic: state.topic ? `${state.topic.name} (${state.topic.id})` : "새 주제",
    };
    let fields = Object.assign({}, base, { proposal: fit(prop, 3000) });
    const room = URL_BUDGET - issueUrl(fields).length - 20;
    const shortConvo = fit(convo, Math.max(room, 200));
    fields.conversation = shortConvo;
    const cut = shortConvo !== convo || fields.proposal !== prop;
    if (cut && navigator.clipboard) navigator.clipboard.writeText(convo + (prop ? "\n\n---\n" + prop : "")).catch(() => {});
    window.open(issueUrl(fields), "_blank", "noopener");
    say("GitHub 이슈 작성 화면을 새 창으로 열었습니다. 내용을 확인하고 제출하면 멘토와 멘티가 검토해 카탈로그와 분석에 반영합니다. (GitHub 로그인이 필요합니다)" +
      (cut ? " 대화가 길어 앞부분을 줄였습니다. 전체 대화는 클립보드에 복사해 두었으니 이슈 본문에 붙여 넣어 주세요." : ""));
  }

  // ─── 입력 처리 ───────────────────────────────────────────────────────
  async function send(text) {
    text = text.trim();
    if (!text) return;
    bubble("user", esc(text));
    state.messages.push({ role: "user", content: text });
    input.value = "";
    const m = matchTopic(text);
    if (m) state.topic = m.topic;
    document.querySelectorAll("#cards .topic").forEach((c) => c.classList.toggle("hit", !!state.topic && c.dataset.topic === state.topic.id));
    if (state.mode === "ai" && state.key !== null && ($("#ai-provider").value !== "anthropic" || state.key)) {
      const wait = bubble("bot", '<span class="muted">생각하는 중…</span>');
      try {
        const out = await callAI();
        wait.remove();
        renderAI(out);
      } catch (err) {
        wait.remove();
        say(`<p>AI 호출에 실패했습니다: ${esc(err.message || err)}</p><p class="muted small">키·모델·주소를 확인하세요. 우선 가이드 모드로 답합니다.</p>`);
        guide(text);
      }
      return;
    }
    guide(text);
  }
  form.addEventListener("submit", (e) => { e.preventDefault(); send(input.value); });
  input.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(input.value); } });
  document.querySelectorAll("[data-ask]").forEach((b) => (b.onclick = () => send(b.dataset.ask)));

  // AI 설정
  const panel = $("#ai-panel");
  $("#ai-toggle").onclick = () => { panel.hidden = !panel.hidden; };
  $("#ai-provider").onchange = () => { $("#ai-base-row").hidden = $("#ai-provider").value === "anthropic"; };
  $("#ai-save").onclick = () => {
    state.key = $("#ai-key").value.trim();
    $("#ai-key").value = "";
    const ok = $("#ai-provider").value !== "anthropic" || state.key;
    state.mode = ok ? "ai" : "guide";
    $("#mode").textContent = ok ? "AI 모드" : "가이드 모드";
    $("#mode").className = "badge " + (ok ? "go" : "info");
    panel.hidden = true;
  };
  $("#ai-off").onclick = () => { state.key = ""; state.mode = "guide"; $("#mode").textContent = "가이드 모드"; $("#mode").className = "badge info"; panel.hidden = true; };
})();
