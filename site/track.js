/* 이용 통계 — 쿠키 없이 페이지 조회와 버튼 사용 수만 셉니다 (GoatCounter).
 *
 * 메인테이너가 Actions 변수 GOATCOUNTER_CODE 를 넣었을 때만 켜집니다(<html data-gc="코드">).
 * 브라우저의 '추적 안 함(Do Not Track)'이 켜져 있으면 아무것도 보내지 않습니다.
 * 버튼에는 data-track="이름" 을 붙입니다. 이름 목록: site/impact.py 의 EVENTS.
 * 다른 스크립트는 window.track("이름") 으로 부릅니다(꺼져 있으면 아무 일도 하지 않음).
 */
(function () {
  const code = document.documentElement.dataset.gc;
  const off = !code || navigator.doNotTrack === "1" || window.doNotTrack === "1";
  const sent = new Set();
  window.track = function (name, once) {
    if (off || !name) return;
    if (once && sent.has(name)) return;
    sent.add(name);
    const go = () => window.goatcounter && window.goatcounter.count && window.goatcounter.count({ path: "ev-" + name, title: name, event: true });
    if (window.goatcounter && window.goatcounter.count) go();
    else window.addEventListener("load", go, { once: true });
  };
  document.addEventListener("click", (e) => {
    const t = e.target.closest && e.target.closest("[data-track]");
    if (t) window.track(t.dataset.track);
  });
  if (off) return;
  const s = document.createElement("script");
  s.async = true;
  s.src = "https://gc.zgo.at/count.js";
  s.dataset.goatcounter = "https://" + code + ".goatcounter.com/count";
  document.head.appendChild(s);
})();
