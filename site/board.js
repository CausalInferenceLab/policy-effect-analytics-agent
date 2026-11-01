/* 이슈 보드의 작은 동작 — 흐름 띠가 한 번 그려지기, 단계 레일 따라 켜지기, 그림 값 보기.
 * '동작 줄이기'를 켠 브라우저에서는 움직임 없이 바로 최종 상태를 보여 줍니다. */
(function () {
  const calm = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const root = document.documentElement;
  root.classList.add("js");
  if (calm) root.classList.add("calm");

  // 1) 흐름 띠: 화면에 들어오면 한 번 왼쪽부터 켜지고 숫자가 올라간다
  const flow = document.querySelector(".flow");
  if (flow) {
    const go = () => {
      flow.classList.add("in");
      if (calm) return;
      flow.querySelectorAll("[data-count]").forEach((el, i) => {
        const end = +el.dataset.count, t0 = performance.now() + i * 140, dur = 700;
        const tick = (now) => {
          const p = Math.min(1, Math.max(0, (now - t0) / dur));
          el.textContent = Math.round(end * (1 - Math.pow(1 - p, 3)));
          if (p < 1) requestAnimationFrame(tick);
        };
        el.textContent = "0";
        requestAnimationFrame(tick);
      });
    };
    if ("IntersectionObserver" in window && !calm) {
      const io = new IntersectionObserver((es) => { if (es.some((x) => x.isIntersecting)) { go(); io.disconnect(); } }, { threshold: 0.3 });
      io.observe(flow);
    } else go();
  }

  // 2) 계보 그림: 화면에 들어오면 연결선이 그려진다
  document.querySelectorAll(".lin-svg").forEach((svg) => {
    if (calm || !("IntersectionObserver" in window)) { svg.classList.add("in"); return; }
    const io = new IntersectionObserver((es) => { if (es.some((x) => x.isIntersecting)) { svg.classList.add("in"); io.disconnect(); } }, { threshold: 0.25 });
    io.observe(svg);
  });

  // 3) 단계 레일: 지금 보고 있는 단계를 켠다
  const links = [...document.querySelectorAll(".rail [data-spy]")];
  if (links.length && "IntersectionObserver" in window) {
    const byId = Object.fromEntries(links.map((a) => [a.dataset.spy, a]));
    const io = new IntersectionObserver((es) => {
      es.forEach((x) => {
        if (x.isIntersecting) {
          links.forEach((a) => a.removeAttribute("aria-current"));
          byId[x.target.id] && byId[x.target.id].setAttribute("aria-current", "step");
        }
      });
    }, { rootMargin: "-35% 0px -55% 0px" });
    links.forEach((a) => { const s = document.getElementById(a.dataset.spy); if (s) io.observe(s); });
  }

  // 4) 그림 값 보기: 점에 마우스·키보드 포커스를 두면 값이 뜬다
  let tip = null;
  const show = (el) => {
    if (!tip) { tip = document.createElement("div"); tip.className = "tip"; tip.setAttribute("role", "status"); document.body.appendChild(tip); }
    tip.textContent = el.dataset.tip;
    const r = el.getBoundingClientRect();
    tip.style.left = Math.min(window.innerWidth - 16 - tip.offsetWidth, Math.max(16, r.left + r.width / 2 - tip.offsetWidth / 2)) + "px";
    tip.style.top = (window.scrollY + r.top - tip.offsetHeight - 8) + "px";
    tip.hidden = false;
  };
  const hide = () => { if (tip) tip.hidden = true; };
  document.querySelectorAll("[data-tip]").forEach((el) => {
    el.addEventListener("mouseenter", () => show(el));
    el.addEventListener("focus", () => show(el));
    el.addEventListener("mouseleave", hide);
    el.addEventListener("blur", hide);
  });
})();
