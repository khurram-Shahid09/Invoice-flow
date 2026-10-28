// A visible mouse pointer for screen recordings (Playwright videos don't show the real one).
(() => {
  if (window.__demoCursor) return;
  window.__demoCursor = true;
  const make = () => {
    const dot = document.createElement("div");
    dot.innerHTML =
      '<svg width="26" height="26" viewBox="0 0 24 24"><path d="M4 2l16 9.5-7 1.6-3.6 6.6z" fill="#111827" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>';
    Object.assign(dot.style, {
      position: "fixed", left: "0px", top: "0px", zIndex: 2147483647, pointerEvents: "none",
      transform: "translate(-3px,-2px)", transition: "left 40ms linear, top 40ms linear",
      filter: "drop-shadow(0 2px 3px rgba(0,0,0,.35))",
    });
    document.documentElement.appendChild(dot);
    document.addEventListener("mousemove", (e) => {
      dot.style.left = `${e.clientX}px`;
      dot.style.top = `${e.clientY}px`;
    }, true);
    document.addEventListener("mousedown", (e) => {
      const ring = document.createElement("div");
      Object.assign(ring.style, {
        position: "fixed", left: `${e.clientX - 18}px`, top: `${e.clientY - 18}px`, width: "36px",
        height: "36px", borderRadius: "50%", border: "3px solid #0f766e", zIndex: 2147483646,
        pointerEvents: "none", transition: "transform 450ms ease-out, opacity 450ms ease-out",
      });
      document.documentElement.appendChild(ring);
      requestAnimationFrame(() => { ring.style.transform = "scale(1.8)"; ring.style.opacity = "0"; });
      setTimeout(() => ring.remove(), 500);
    }, true);
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", make);
  else make();
})();
