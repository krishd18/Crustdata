// Draws connector arrows between diagram boxes from their real positions.
// wire({from:[id, side, t], to:[id, side, t], via:[[x,y],...], kind, dash, label, lx, ly, curve})
//   side: l | r | t | b ; t = 0..1 along that side
(function () {
  const svg = document.getElementById("wires");
  const cv = document.getElementById("cv");
  const NS = "http://www.w3.org/2000/svg";
  function pt(id, side, t) {
    const el = document.getElementById(id);
    const c = cv.getBoundingClientRect(), r = el.getBoundingClientRect();
    const x = r.left - c.left, y = r.top - c.top, w = r.width, h = r.height;
    t = t == null ? 0.5 : t;
    return side === "l" ? [x, y + h * t] : side === "r" ? [x + w, y + h * t]
         : side === "t" ? [x + w * t, y] : [x + w * t, y + h];
  }
  window.wire = function (o) {
    const a = pt(...o.from), b = pt(...o.to);
    let d;
    if (o.curve) {
      const dx = Math.max(40, Math.abs(b[0] - a[0]) * 0.5);
      d = `M${a} C${a[0] + dx},${a[1]} ${b[0] - dx},${b[1]} ${b}`;
    } else {
      const pts = [a, ...(o.via || []), b];
      d = "M" + pts.map(p => p.join(",")).join(" L");
    }
    const p = document.createElementNS(NS, "path");
    p.setAttribute("d", d);
    p.setAttribute("class", "wl" + (o.kind && o.kind !== "retry" ? " " + o.kind : "") + (o.dash ? " dash" : ""));
    if (o.kind === "retry") p.style.stroke = "#7c3aed";
    p.setAttribute("marker-end", `url(#ah${o.kind ? "-" + o.kind : ""})`);
    svg.appendChild(p);
    if (o.label) {
      const tx = document.createElementNS(NS, "text");
      tx.setAttribute("x", o.lx); tx.setAttribute("y", o.ly);
      tx.setAttribute("class", "wlabel" + (o.kind ? " " + o.kind : ""));
      if (o.kind === "retry") tx.style.fill = "#7c3aed";
      tx.textContent = o.label;
      svg.appendChild(tx);
    }
  };
})();
