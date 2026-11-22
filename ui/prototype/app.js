/* Data Designer console prototype — vanilla JS, no build step, hash routes.
   The production UI (Phase 2, IMPLEMENTATION_PLAN.md §4.2D) ports these screens to
   FastAPI + Jinja + HTMX and swaps window.DD for API calls. */
(() => {
const D = window.DD;
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const inr = n => new Intl.NumberFormat("en-IN").format(n);
const f2 = n => n.toFixed(2);

/* ---------- icons (stroke, 24 grid) ---------- */
const P = {
  logo: '<path d="M16 3 5 7v8c0 7 4.7 12 11 14 6.3-2 11-7 11-14V7L16 3Z" stroke="currentColor" stroke-width="2.2" stroke-linejoin="round"/><path d="m10.5 16 4 4 7-8" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>',
  down: '<path d="m6 9 6 6 6-6"/>', right: '<path d="M5 12h14M13 6l6 6-6 6"/>', chev: '<path d="m9 6 6 6-6 6"/>', x: '<path d="M6 6l12 12M18 6 6 18"/>',
  doc: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M9 13h6M9 17h6"/>',
  book: '<path d="M2 5h7a3 3 0 0 1 3 3v12a2 2 0 0 0-2-2H2zM22 5h-7a3 3 0 0 0-3 3v12a2 2 0 0 1 2-2h8z"/>',
  chart: '<path d="M3 3v18h18"/><path d="m7 15 4-4 3 3 5-6"/>', users: '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0M16 4.5a3.5 3.5 0 0 1 0 7M18 14a6 6 0 0 1 3.5 6"/>',
  mail: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/>', shield: '<path d="M12 3 4 6v6c0 5 3.4 8.6 8 10 4.6-1.4 8-5 8-10V6z"/><path d="m9 12 2 2 4-4"/>',
  spark: '<path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M6 18l2.5-2.5M15.5 8.5 18 6"/>', db: '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>', clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>', send: '<path d="M22 2 11 13M22 2l-7 20-4-9-9-4z"/>',
  map: '<path d="M9 3 3 6v15l6-3 6 3 6-3V3l-6 3z"/><path d="M9 3v15M15 6v15"/>', cpu: '<rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4"/>',
  check: '<path d="m5 12 5 5 9-10"/>', edit: '<path d="M4 20h4L19 9l-4-4L4 16z"/>', key: '<circle cx="8" cy="15" r="4"/><path d="m11 12 9-9M17 6l3 3"/>', play: '<path d="M7 4v16l13-8z"/>',
  list: '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>', rupee: '<path d="M6 4h12M6 9h12M9 4c4 0 6 2 6 5s-2 5-6 5H6l8 7"/>'
};
const ic = (n, s = 18) => n === "logo"
  ? `<svg viewBox="0 0 32 32" fill="none" width="${s}" height="${s}" aria-hidden="true">${P.logo}</svg>`
  : `<svg viewBox="0 0 24 24" width="${s}" height="${s}" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${P[n]}</svg>`;

/* ---------- verdict vocabulary (STANDARDS §2) ---------- */
const V = { verified: ["✅", "VERIFIED"], partial: ["🟢", "PARTIALLY"], unverified: ["🟡", "UNVERIFIED"], outdated: ["⏳", "OUTDATED"], nv: ["⚪", "NOT VERIFIABLE"], false: ["❌", "FALSE"], nc: ["⚫", "NOT CHECKED"] };
const vb = (cls, code) => `<span class="vb ${cls}">${V[cls][0]} ${V[cls][1]}${code ? ` <span class="code">${code}</span>` : ""}</span>`;
const lblClass = l => /^(RECOMMEND|PURSUE|CLEAR)$/.test(l) ? "pos" : /WITH CONDITIONS|CONSIDER/.test(l) ? "cond" : /HOLD/.test(l) ? "hold" : "neg";
const lbl = l => `<span class="lbl ${lblClass(l)}">${l}</span>`;
const pts = (f, c) => `<span class="pts" aria-label="${f} of 4, ceiling ${c}">${[1, 2, 3, 4].map(i => `<i class="${i <= f ? "f" : i <= c ? "c" : ""}"></i>`).join("")}</span>`;

/* ---------- state ---------- */
const S = { tab: "investing", mode: "full", query: D.tabs.investing[0].q, card: "acquire", runs: {}, decision: null, mail: D.approvals.map(a => ({ ...a })), mailSel: 0, ctab: "summary", rotI: 0 };

/* ---------- chrome: nav, footer ---------- */
function nav(route) {
  const pend = S.mail.filter(m => m.status === "pending").length;
  const on = r => route.startsWith(r) ? "on" : "";
  $("#nav").innerHTML = `<div class="nav-in" style="position:relative">
    <a class="logo" href="#/ask" aria-label="Data Designer home"><span style="color:var(--brand-logo)">${ic("logo", 34)}</span>Data Designer</a>
    <nav class="nav-links" aria-label="Primary">
      <a href="#/ask" class="${on("/ask")}">Ask</a>
      <a href="#/runs" class="${on("/run")}">Runs</a>
      <button id="memos-btn" aria-expanded="false" class="${/market|company|memo/.test(route) ? "on" : ""}">Memos ${ic("down", 16)}</button>
      <a href="#/approvals" class="${on("/approvals")}">Approvals ${pend ? `<span class="count">${pend}</span>` : ""}</a>
      <a href="#/audit" class="${on("/audit")}">Audit</a>
      <a href="#/setup" class="${on("/setup")}">Setup</a>
    </nav>
    <div class="nav-right">
      <span class="meter-mini" title="Crustdata credits used today">credits <b class="num">${inr(D.budgetToday.used)}</b> / ${inr(D.budgetToday.cap)}</span>
      <span class="env ${D.env === "live" ? "live" : ""}"><i></i>${D.env}</span>
      <a class="btn btn-primary" href="#/ask">New ask</a>
    </div>
    <div class="mega" id="mega" role="menu">
      <div><div class="label">Memos</div>
        ${mitem("chart", "Market IM", "Step 1 · ranked shortlist with R1", "#/market")}
        ${mitem("doc", "Company IM", "Step 4 · gates → score → decision", "#/company")}
        ${mitem("search", "Research Memo", "Answers with R3 and inference strength", "#/memo/research")}
        ${mitem("list", "Find-list Memo", "Ten companies, every attribute classed", "#/memo/findlist")}
      </div>
      <div><div class="label" style="margin-top:0">Work</div>
        ${mitem("clock", "Runs", "Stage timeline and credits", "#/runs")}
        ${mitem("mail", "Approvals", "Gmail drafts awaiting you", "#/approvals")}
        ${mitem("cpu", "Watchers", "Re-check on change", "#/runs", "Phase 3")}
      </div>
      <div class="col-r"><div class="label">Standards</div>
        <div class="arrow-list" style="margin-top:12px">
          ${["7 verdict classes", "Source tiers T1 → T4", "R1 scouting rubric", "R2 decision rubric", "R3 research rubric", "Leadership fit LF-01…07", "Regional fit RG-C", "Inference strength"].map(t => `<a href="#/company">${ic("right", 16)} ${t}</a>`).join("")}
        </div></div>
    </div></div>`;
  const btn = $("#memos-btn"), mega = $("#mega");
  const set = o => { mega.classList.toggle("open", o); btn.setAttribute("aria-expanded", o); };
  btn.onclick = e => { e.stopPropagation(); set(!mega.classList.contains("open")); };
  document.onclick = e => { if (!mega.contains(e.target)) set(false); };
  $$(".mitem", mega).forEach(m => m.onclick = () => { location.hash = m.dataset.href; set(false); });
}
const mitem = (i, t, s, href, soon) => `<div class="mitem" role="menuitem" tabindex="0" data-href="${href}"><div class="tile">${ic(i, 22)}</div><div><b>${t}</b><span>${s}</span></div>${soon ? `<span class="soon">${soon}</span>` : ""}</div>`;

function footer() {
  $("#footer").innerHTML = `<div class="divider"></div><div class="foot">
    <div><h4>Product</h4><a href="#/ask">Ask</a><a href="#/runs">Runs</a><a href="#/approvals">Approvals</a><a href="#/audit">Audit</a></div>
    <div><h4>Memos</h4><a href="#/market">Market IM</a><a href="#/company">Company IM</a><a href="#/memo/research">Research Memo</a><a href="#/memo/findlist">Find-list Memo</a></div>
    <div><h4>Standards</h4><a href="#/company">Verdict classes</a><a href="#/company">Rubrics R1 · R2 · R3</a><a href="#/company">Metric dictionary</a><a href="#/setup">Data sources</a></div>
    <div><h4>Built for</h4><a>ContextCon 05 · BITS Pilani</a><a>Trust &amp; compliance</a><a>Investing</a><a>Research &amp; markets</a></div>
    <div class="attrib"><p style="color:#fff;font-weight:500;margin:0 0 10px">Data by Crustdata · reasoning by Claude</p>
      <p style="margin:0 0 10px">Indian public records: MCA21, GST, EPFO, VAHAN, eCourts. Reliable media from a compliance-owned allow-list.</p>
      <p style="margin:0">Suggestions only. A person approves every irreversible action.</p>
      <p style="margin:14px 0 0">© 2026 Data Designer · team hackathon-Rohan</p></div></div>`;
}

/* ---------- ASK ---------- */
const ROT = ["checked", "sourced", "scored"];
function viewAsk() {
  const chips = D.tabs[S.tab];
  return `<section class="hero">
    <h1>Every claim, <span class="rot" id="rot">${ROT.map((w, i) => `<span class="${i ? "down" : ""}">${w}</span>`).join("")}</span><br>before you sign.</h1>
    <p class="lead">Diligence and market research on live Crustdata data and Indian public records</p>
    <div class="ask">
      <div class="tabs" role="tablist">
        ${["investing", "research", "compliance"].map(t => `<button class="tab ${S.tab === t ? "on" : ""}" role="tab" aria-selected="${S.tab === t}" data-tab="${t}">${t[0].toUpperCase() + t.slice(1)}</button>`).join("")}
        <div class="seg" role="group" aria-label="Depth"><button class="${S.mode === "answer" ? "on" : ""}" data-mode="answer">Answer</button><button class="${S.mode === "full" ? "on" : ""}" data-mode="full">Full diligence</button></div>
      </div>
      <div class="qbox"><label class="sr" for="q">Your request</label>
        <textarea id="q" rows="2" placeholder="Ask in plain words — e.g. acquirable logistic companies in maharashtra">${S.query}</textarea>
        <button class="btn btn-primary btn-lg" id="reason">Reason about it ${ic("right", 20)}</button></div>
      <div class="chips">${chips.map((c, i) => `<button class="chip" data-i="${i}" title="${c.q}">${c.q}</button>`).join("")}</div>
      <p class="sub" style="font-size:13px;margin:12px 4px 0">Press <span class="kbd">/</span> to focus · <span class="kbd">Ctrl</span> + <span class="kbd">Enter</span> to reason · nothing runs until you confirm the reasoning card</p>
    </div></section>

  <section class="section wrap">
    <div class="section-head"><h2>From a sentence to a signed decision</h2><p>Three steps, one fixed rubric, every number sourced</p></div>
    <div class="trio">
      <a class="fcard p" href="#/market"><span class="k">Step 1 · Scout</span><h3>“Acquirable” becomes ratios, tech and team requirements — shown before anything runs.</h3><p>Seven search streams, a constraint gate and the R1 rubric produce a Market IM.</p><span class="go">${ic("chev", 26)}</span></a>
      <a class="fcard c" href="#/company"><span class="k">Step 3 · Check</span><h3>Every deck claim lands in one of seven classes, with the record that proves it.</h3><p>MCA, GST, EPFO, VAHAN and reliable media outrank the deck. Wrong is worse than unknown.</p><span class="go">${ic("chev", 26)}</span></a>
      <a class="fcard g" href="#/approvals"><span class="k">Step 4–5 · Decide &amp; act</span><h3>Gates, a floor–ceiling score and a fixed rule suggest; you decide.</h3><p>Approved emails go out through Gmail exactly once, even across a crash.</p><span class="go">${ic("chev", 26)}</span></a>
    </div>
  </section>

  <section class="section wrap">
    <div class="section-head"><h2>Sources, ranked before they are read</h2><p>Higher tiers overrule lower ones; press releases count as self-published</p></div>
    <div class="grid-src">
      ${[["T1", "MCA21 master data", "Incorporation, directors, filings, AOC-4"], ["T1", "GST search", "State registrations by PAN · code 27 = Maharashtra"], ["T1", "EPFO · VAHAN", "Establishment members · vehicle registrations"], ["T1-M", "Reliable media", "Allow-list, own-reporting test, tier A/B"],
         ["T2", "Crustdata company", "search · identify · enrich · autocomplete"], ["T2", "Crustdata people", "person search · enrich · live profile"], ["T2", "Crustdata jobs & web", "job search · aggregation · web search/enrich"], ["T3 · T4", "Deck & self-published", "Counterparty documents · own website · PR"]]
        .map(([t, b, s]) => `<div><span class="tier">${t}</span><b>${b}</b><span class="muted">${s}</span></div>`).join("")}
    </div>
  </section>`;
}
function bindAsk() {
  const q = $("#q");
  $$(".tab").forEach(b => b.onclick = () => { S.tab = b.dataset.tab; S.query = D.tabs[S.tab][0].q; S.card = D.tabs[S.tab][0].key; render(); });
  $$(".seg button").forEach(b => b.onclick = () => { S.mode = b.dataset.mode; $$(".seg button").forEach(x => x.classList.toggle("on", x === b)); });
  $$(".hero .chip").forEach(c => c.onclick = () => { const t = D.tabs[S.tab][+c.dataset.i]; q.value = S.query = t.q; S.card = t.key; q.focus(); });
  q.oninput = () => { S.query = q.value; S.card = guessCard(q.value); };
  q.onkeydown = e => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) openCard(); };
  $("#reason").onclick = openCard;
  clearInterval(S.rotT);
  S.rotT = setInterval(() => {
    const spans = $$("#rot span"); if (!spans.length) return clearInterval(S.rotT);
    const cur = S.rotI, nxt = (cur + 1) % spans.length;
    spans[cur].className = "up"; spans[nxt].className = "";
    setTimeout(() => { spans[cur].className = "down"; }, 650); S.rotI = nxt;
  }, 2600);
}
const guessCard = t => /hiring|launch|quarter/i.test(t) ? "research" : /founded|grew|ten |founder/i.test(t) ? "findlist" : "acquire";

/* ---------- reasoning card modal ---------- */
function openCard() {
  const k = S.card = guessCard(S.query), c = D.cards[k];
  const origin = o => `<span class="tag ${/confirm|proxy/.test(o) ? (o.startsWith("proposed") ? "prop" : "ask") : /library|clock/.test(o) ? "lib" : ""}">${o}</span>`;
  openModal(`<div class="mh"><div><div class="label">Reasoning card · ${c.family}</div><h2 id="modal-title" style="margin-top:6px">How Data Designer read your request</h2>
      <p class="muted" style="margin:6px 0 0">“${S.query}”</p></div><button class="x" data-close aria-label="Close">${ic("x")}</button></div>
    <div class="mb">
      <div class="tbl-wrap"><table><thead><tr><th>Phrase</th><th>Intent</th><th>Parameters</th><th>Metric</th><th>Role</th><th>Origin</th></tr></thead>
      <tbody>${c.rows.map(r => `<tr><td><b>${r.phrase}</b></td><td class="muted">${r.intent}</td><td>${r.params}</td><td class="mono">${r.metric}</td><td><span class="tag">${r.role}</span></td><td>${origin(r.origin)}</td></tr>`).join("")}</tbody></table></div>
      <div class="qgrid">${c.questions.map((x, qi) => `<fieldset class="qcard" style="border:0"><b>${x.q}</b>${x.opts.map((o, oi) => `<label class="radio"><input type="radio" name="q${qi}" ${oi === x.def ? "checked" : ""}> ${o}</label>`).join("")}</fieldset>`).join("")}</div>
    </div>
    <div class="mf"><span class="muted" style="font-size:14px">${c.mandate} · rubric ${c.rubric} · budget ${c.credits} credits · ≤ ${c.minutes} min · nothing outside the term library is applied without your answer</span>
      <button class="btn btn-ghost" data-close style="margin-left:auto">Edit query</button>
      <button class="btn btn-primary" id="confirm">${ic("play", 16)} Confirm &amp; run</button></div>`);
  $("#confirm").onclick = () => { closeAll(); S.runs[k] = { i: 0, done: false }; location.hash = `#/run/${k}`; toast("Reasoning confirmed · mandate frozen · run started"); };
}

/* ---------- RUNS ---------- */
function viewRuns() {
  const rows = [["acquire", "acquirable logistic companies in maharashtra", "Market IM", "#/market", 394, "complete"], ["findlist", "Find ten Indian B2B software companies…", "Research Memo", "#/memo/findlist", 118, "complete"], ["research", "Which Indian fintech companies are hiring…", "Research Memo", "#/memo/research", 95, "complete"]];
  return `<div class="wrap page"><div class="title-row"><div><h1>Runs</h1><div class="meta">Each run is checkpointed; a killed run resumes from its last stage and never repeats an action.</div></div></div>
    <div class="tbl-wrap"><table><thead><tr><th>Run</th><th>Family</th><th>Request</th><th>Output</th><th class="r">Credits</th><th>Status</th><th></th></tr></thead><tbody>
    ${rows.map(([k, q, out, href, cr, st]) => `<tr class="click" data-href="#/run/${k}"><td class="mono">${D.runs[k].id}</td><td><span class="tag lib">${D.cards[k].family}</span></td><td>${q}</td><td><a href="${href}" style="color:var(--brand-label)">${out}</a></td><td class="r num">${cr}</td><td><span class="st sent">${st}</span></td><td>${ic("chev")}</td></tr>`).join("")}
    </tbody></table></div></div>`;
}
function viewRun(k) {
  const r = D.runs[k], st = S.runs[k] || (S.runs[k] = { i: r.log.length, done: true });
  const memoHref = { market: "#/market", findlist: "#/memo/findlist", research: "#/memo/research" }[r.memo];
  return `<div class="wrap page"><div class="crumbs"><a href="#/runs">Runs</a>${ic("chev", 14)}<span class="mono">${r.id}</span></div>
    <div class="title-row"><div><h1>${D.cards[k].family.replace("_", " ")} run</h1><div class="meta">${D.cards[k].mandate} · as of ${D.asOf} · replay cassettes · deterministic</div></div>
      <div class="actions"><button class="btn btn-ghost" id="kill">Kill &amp; resume</button><a class="btn btn-primary" id="open-memo" href="${memoHref}" ${st.done ? "" : "hidden"}>Open memo ${ic("right", 16)}</a></div></div>
    <div class="card" style="margin-bottom:24px"><div class="steps" id="steps"></div>
      <div class="budget" style="margin-top:22px"><span class="sub" style="font-size:13px">BUDGET</span><div class="bar"><i id="bud" style="width:0"></i></div><span class="num" id="budtxt"></span>
        <button class="btn btn-ghost btn-sm" id="cut">Cut budget</button></div></div>
    <div class="cols"><div class="card"><div class="card-h"><h3>Call log</h3><span class="right sub mono">X-Credits-Used per call</span></div><div class="log" id="log" aria-live="polite"></div></div>
      <div class="stack"><div class="card"><h3 style="margin-bottom:12px">What happens here</h3><ul class="list-num"><li><span>Every call goes through the gateway: rate limits, retries, cassette record/replay.</span></li><li><span>Claude only extracts and classifies with quoted evidence; code scores.</span></li><li><span>Kill the process at any stage — the journal resumes it exactly once.</span></li></ul></div>
        <details class="card api"><summary>${ic("chev", 16)} API call · company/search (key redacted)</summary><pre class="code" style="margin-top:14px">${apiSample()}</pre></details></div></div></div>`;
}
const apiSample = () => `<span class="k">POST</span> /company/search
<span class="k">authorization</span>: Bearer ••••••••
<span class="k">x-api-version</span>: <span class="s">2025-11-01</span>
{ <span class="k">"filters"</span>: { <span class="k">"op"</span>: <span class="s">"and"</span>, <span class="k">"conditions"</span>: [
   { <span class="k">"field"</span>: <span class="s">"locations.country"</span>, <span class="k">"type"</span>: <span class="s">"in"</span>, <span class="k">"value"</span>: [<span class="s">"IND"</span>] },
   { <span class="k">"field"</span>: <span class="s">"basic_info.year_founded"</span>, <span class="k">"type"</span>: <span class="s">"=&gt;"</span>, <span class="k">"value"</span>: <span class="n">2023</span> },
   { <span class="k">"field"</span>: <span class="s">"headcount.growth_percent.6m"</span>, <span class="k">"type"</span>: <span class="s">"=&gt;"</span>, <span class="k">"value"</span>: <span class="n">50</span> } ] },
  <span class="k">"limit"</span>: <span class="n">200</span> }`;
function bindRun(k) {
  const r = D.runs[k], st = S.runs[k], cap = D.cards[k].credits;
  const draw = () => {
    const n = r.stages.length, si = st.done ? n : Math.min(n - 1, Math.floor(st.i * n / r.log.length));
    $("#steps").innerHTML = r.stages.map((s, i) => `<div class="step ${i < si ? "done" : i === si ? "run" : ""}"><span class="dot"></span>${s.name}<span class="cr">${s.credits ? s.credits + " cr" : "—"}</span></div>`).join("");
    const used = r.log.slice(0, st.i).reduce((a, l) => a + l[3], 0);
    $("#bud").style.width = Math.min(100, used / cap * 100) + "%"; $("#budtxt").textContent = `${used} / ${cap} credits`;
    const log = $("#log"), have = log.querySelectorAll(".ln.call").length;
    log.insertAdjacentHTML("beforeend", r.log.slice(have, st.i).map((l, j) => { const i = have + j; return `<div class="ln call"><span class="t">16:0${2 + Math.floor(i / 2)}:${String(11 + i * 4).padStart(2, "0")}</span><span class="ep">${l[0]}</span><span>${l[1]} → <span class="res">${l[2]}</span></span><span class="c">${l[3] ? l[3] + " cr" : ""}</span></div>`; }).join(""));
    if (st.done && !log.querySelector(".fin")) log.insertAdjacentHTML("beforeend", `<div class="ln fin"><span class="t">done</span><span class="ep">journal</span><span class="res">run complete · checkpoint sealed</span><span></span></div>`);
    log.scrollTop = 1e6;
  };
  draw();
  clearInterval(S.runT);
  if (!st.done) S.runT = setInterval(() => {
    if (!location.hash.startsWith("#/run/")) return clearInterval(S.runT);
    st.i++; if (st.i >= r.log.length) { st.done = true; clearInterval(S.runT); $("#open-memo").hidden = false; toast("Run complete · memo drafted"); }
    draw();
  }, 650);
  $("#kill").onclick = () => { const at = st.i; toast(`Killed at step ${at} · restarting from checkpoint…`); setTimeout(() => toast(`Resumed from checkpoint ${at} · 0 actions repeated`), 1200); };
  $("#cut").onclick = () => toast("Budget cut to 300 credits · remaining stages re-planned (enrich top 60)");
}

/* ---------- MARKET IM ---------- */
function viewMarket() {
  const m = D.market;
  return `<div class="wrap page"><div class="crumbs"><a href="#/runs">Runs</a>${ic("chev", 14)}<span>Market IM</span></div>
    <div class="title-row"><div><div class="label">Market IM · ${m.id}</div><h1 style="margin-top:6px">Acquirable logistics companies operating in Maharashtra</h1><div class="meta">as of ${D.asOf} · R1-2026.11.22-2 · location basis = operates · ${m.credits} credits</div></div>
      <div class="actions"><button class="btn btn-ghost">${ic("doc", 16)} Export PDF</button><button class="btn btn-primary" id="screen">Screen C, A, B ${ic("right", 16)}</button></div></div>
    <div class="banner" style="margin-bottom:24px"><div class="label">Suggestion</div><div class="sugg" style="color:var(--l-pos)">Screen the 8 RECOMMEND companies, starting with C, A and B</div>
      <div class="facts"><span>R1 floors 66–73 · no risk flags</span><span>Each has an active GST 27 registration</span><span>Revenue inside ₹25–400 cr (estimate)</span><span>Financial-ratio and governance requirements open → tested at Check</span></div></div>
    <div class="stat-row" style="margin-bottom:24px">${[["Found", 380], ["Scored on R1", 52], ["Recommend", m.split.recommend], ["Credits", m.credits]].map(([k, v]) => `<div class="stat"><div class="k">${k}</div><div class="v num">${inr(v)}</div></div>`).join("")}</div>
    <div class="cols"><div class="card" style="padding:0;overflow:hidden"><div class="card-h" style="padding:20px 22px 0"><h3>Shortlist</h3><span class="right sub" style="font-size:13px">click a row for its Company IM</span></div>
      <div style="overflow-x:auto;margin-top:14px"><table><thead><tr><th>#</th><th>Company (sample)</th><th>HQ</th><th>Regions</th><th>MH share</th><th>Revenue (est.)</th><th>R1 floor–ceiling</th><th>Requirements</th><th>Label</th></tr></thead><tbody>
      ${m.rows.map((r, i) => `<tr class="click" data-href="#/company" title="${r.note || ""}"><td class="sub">${i + 1}</td><td><b>${r.name}</b>${r.note ? `<div class="sub" style="font-size:12.5px">${r.note}</div>` : ""}</td><td>${r.hq}</td><td class="muted">${r.regions}</td>
        <td style="min-width:120px"><div class="bar cyan"><i style="width:${r.mh}%"></i></div><span class="num sub" style="font-size:12.5px">${r.mh}%</span></td><td class="num">${r.rev}</td>
        <td style="min-width:150px">${rangeMini(r.floor, r.ceil)}<span class="num" style="font-size:12.5px">${f2(r.floor)}–${f2(r.ceil)}</span></td><td class="muted" style="font-size:13.5px">${r.req}</td><td>${lbl(r.label)}</td></tr>`).join("")}
      </tbody></table></div><p class="sub" style="padding:12px 22px 18px;margin:0;font-size:13.5px">Excluded on estimates: ${m.excluded}</p></div>
      <div class="stack"><div class="card"><h3 style="margin-bottom:14px">Funnel</h3><div class="funnel">${m.funnel.map(([k, v]) => `<div class="f"><span class="muted">${k}</span><div class="bar"><i style="width:${v / 380 * 100}%"></i></div><span class="num r">${v}</span></div>`).join("")}</div>
        <p class="sub" style="font-size:13px;margin:14px 0 0">Gate failures: listed 4 · acquired 7 · not logistics-core 15 · inactive 3 · no MH presence 9</p></div>
        <div class="card"><h3 style="margin-bottom:12px">R1 labels</h3><div class="kv"><dt>${lbl("RECOMMEND")}</dt><dd>floor ≥ 60, no flag — <b>${m.split.recommend}</b></dd><dt>${lbl("CONSIDER")}</dt><dd>ceiling ≥ 60 — <b>${m.split.consider}</b></dd><dt>${lbl("NOT RECOMMENDED")}</dt><dd>otherwise — <b>${m.split.notrec}</b></dd></div></div>
        <div class="card"><h3 style="margin-bottom:8px">Delhi HQ, Mumbai fleet?</h3><p class="muted" style="margin:0;font-size:14px">Included. You chose “operates there”: Company C holds GST state code 27 and 62% of its footprint is in Maharashtra, so it passes the gate and scores on regional fit.</p></div></div></div></div>`;
}
const rangeMini = (f, c) => `<div style="position:relative;height:8px;border-radius:5px;background:var(--panel-3);margin-bottom:4px"><div style="position:absolute;left:${f}%;width:${c - f}%;top:0;bottom:0;border-radius:5px;background:var(--brand-label)"></div><div style="position:absolute;left:60%;top:-3px;bottom:-3px;width:1px;background:rgba(255,255,255,.5)"></div></div>`;

/* ---------- COMPANY IM ---------- */
function viewCompany() {
  const c = D.company;
  const tabs = [["summary", "Decision"], ["claims", "Deck fact-check"], ["leaders", "Leadership"], ["fin", "Financials"], ["tech", "Technology"], ["region", "Regions"]];
  return `<div class="wrap page"><div class="crumbs"><a href="#/market">Market IM</a>${ic("chev", 14)}<span>${c.name} (sample)</span></div>
    <div class="title-row"><div><div class="label">Company IM · ${c.id} · ${c.profile}</div><h1 style="margin-top:6px">${c.name} (sample)</h1><div class="meta">CIN ${c.cin} · ${c.rubric} · DRAFT — awaiting decision</div></div>
      <div class="actions">${lbl(c.suggestion)}<button class="btn btn-ghost">${ic("doc", 16)} Export PDF</button></div></div>
    <div class="subtabs" role="tablist">${tabs.map(([k, t]) => `<button role="tab" data-ct="${k}" class="${S.ctab === k ? "on" : ""}">${t}</button>`).join("")}</div>
    <div id="ctab">${companyTab(S.ctab)}</div></div>`;
}
function companyTab(t) {
  const c = D.company;
  if (t === "summary") return `<div class="cols"><div class="stack">
      <div class="card"><div class="card-h"><span class="label">1 · Gates</span><span class="right sub" style="font-size:13px">all 8 pass → scoring allowed</span></div>
        <div class="gates">${c.gates.map(([g, t]) => `<div class="gate"><span class="ok">✓</span><span><b>${g}</b>${t}</span></div>`).join("")}</div></div>
      <div class="card" style="padding:0;overflow:hidden"><div class="card-h" style="padding:22px 22px 0"><span class="label">2 · Scorecard · R2 target profile</span><span class="right sub" style="font-size:13px">[?] shows the working</span></div>
        <div style="overflow-x:auto;margin-top:12px"><table><thead><tr><th>Criterion</th><th>Value</th><th>Points</th><th class="r">Wt</th><th class="r">Floor</th><th class="r">Ceiling</th><th></th></tr></thead><tbody>
        ${c.score.map((r, i) => `<tr><td><span class="mono sub">${r.c}</span> ${r.name}</td><td class="muted" style="font-size:13.5px">${r.val}</td><td>${pts(r.pf, r.pc)} <span class="sub num" style="font-size:12px">${r.pf}/${r.pc}</span></td><td class="r num">${r.w}</td><td class="r num">${f2(r.f)}</td><td class="r num">${f2(r.cl)}</td><td><button class="qhelp" data-why="${i}" aria-expanded="false" aria-label="Why ${r.c}">?</button></td></tr>
          <tr class="whyrow" id="why${i}" hidden><td colspan="7">${r.why}</td></tr>`).join("")}</tbody>
        <tfoot><tr><td>Total</td><td></td><td></td><td class="r">100</td><td class="r num">${f2(c.floor)}</td><td class="r num">${f2(c.ceil)}</td><td></td></tr></tfoot></table></div></div>
      <div class="card"><span class="label">3 · Result</span>
        <div class="scorebar" aria-label="Score range ${c.floor} to ${c.ceil}"><div class="track"></div><span class="tick" style="left:50%">50</span><span class="tick" style="left:75%">75</span><div class="range" style="left:${c.floor}%;width:${c.ceil - c.floor}%"></div></div>
        <div class="legend-row"><span>0 · PASS / HOLD zone</span><span>50 · with conditions</span><span>75 · PURSUE</span><span>100</span></div>
        <p style="margin:16px 0 0"><b>Rule ${c.rule}:</b> floor ${f2(c.floor)} is ≥ 50 and &lt; 75 → <b style="color:var(--l-cond)">${c.suggestion}</b>. Coverage ${c.coverage.toFixed(1)}%. Requirements: ${c.reqs.met} met · ${c.reqs.open} open · ${c.reqs.unmet} unmet → no cap.</p>
        <div class="tbl-wrap" style="margin-top:14px"><table><thead><tr><th>“Acquirable” requirement</th><th>Status</th><th>Value</th></tr></thead><tbody>${c.requirements.map(([r, s, v]) => `<tr><td>${r}</td><td>${s === "met" ? vb("verified", "met").replace("VERIFIED", "") : `<span class="vb unverified">◐ open</span>`}</td><td class="muted">${v}</td></tr>`).join("")}</tbody></table></div></div>
      <div class="banner"><div class="label">4 · Suggested decision</div><div class="sugg">${c.suggestion}</div>
        <div class="facts"><span>Score ${f2(c.floor)}–${f2(c.ceil)}</span><span>Leadership FIT WITH GAPS</span><span>MH share 63%</span><span>Health grade B</span></div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:24px;margin-top:22px;position:relative;z-index:1">
          <div><h3 style="margin-bottom:12px;color:var(--l-pos)">Why pursue</h3><ol class="list-num">${c.why.map(([b, t]) => `<li><span><b>${b}</b> <span class="muted">${t}</span></span></li>`).join("")}</ol></div>
          <div><h3 style="margin-bottom:12px;color:var(--l-hold)">What holds it back</h3><ol class="list-num">${c.hold.map(([b, t]) => `<li><span><b>${b}</b> <span class="muted">${t}</span></span></li>`).join("")}</ol></div></div>
        <h3 style="margin:24px 0 12px;position:relative;z-index:1">Conditions, by points each adds</h3>
        <div class="tbl-wrap" style="position:relative;z-index:1"><table><tbody>${c.conditions.map(([a, b], i) => `<tr><td class="sub">${i + 1}</td><td>${a}</td><td class="r" style="color:var(--brand-label)">${b}</td></tr>`).join("")}</tbody></table></div>
        <p style="margin:16px 0 0;position:relative;z-index:1;color:var(--ink-2)">${c.wouldBe}</p></div>
      <div class="card" id="decide-card"><span class="label">5 · Your decision</span>${decideBlock()}</div>
    </div>
    <div class="stack">${sideSnapshot()}</div></div>`;
  if (t === "claims") {
    const counts = Object.keys(V).map(k => [k, c.claims.filter(x => x.cls === k).length]).filter(x => x[1]);
    return `<div class="card" style="margin-bottom:20px;display:flex;flex-wrap:wrap;gap:10px;align-items:center"><b style="margin-right:6px">37 statements · 23 business (14 critical)</b>${counts.map(([k, n]) => `${vb(k)}<span class="num sub">× ${n}</span>`).join("")}<span class="sub" style="margin-left:auto;font-size:13px">sample of 13 shown · click a row for the evidence</span></div>
      <div class="tbl-wrap"><table><thead><tr><th>Slide</th><th>Claim</th><th>Critical</th><th>Class</th><th>Evidence</th><th>Tier</th><th>Record date</th></tr></thead><tbody>
      ${c.claims.map((x, i) => `<tr class="click" data-claim="${i}"><td class="num">${x.s}</td><td>“${x.t}”</td><td>${x.crit ? "✓" : "—"}</td><td>${vb(x.cls, x.code)}</td><td class="muted" style="font-size:13.5px">${x.ev}</td><td class="mono">${x.tier}</td><td class="sub">${x.date}</td></tr>`).join("")}</tbody></table></div>`;
  }
  if (t === "leaders") return `<div class="cols"><div class="tbl-wrap"><table><thead><tr><th>Leader (sample)</th><th>Bio claims → class</th><th class="r">Domain yrs</th><th>Scale</th><th>Track record</th></tr></thead><tbody>
      ${c.leaders.map(l => `<tr><td><b>${l.role}</b></td><td>${l.bio.map(([t, k, code]) => `<div style="margin-bottom:6px">${t} ${vb(k, code)}</div>`).join("")}</td><td class="r num">${l.yrs}</td><td class="muted">${l.scale}</td><td>${vb("verified").replace("VERIFIED", l.rec)}</td></tr>`).join("")}</tbody></table></div>
      <div class="card"><h3 style="margin-bottom:14px">Leadership fit</h3>${c.lf.map(([id, n, v, p]) => `<div style="display:grid;grid-template-columns:58px 1fr 44px;gap:10px;align-items:center;margin-bottom:12px"><span class="mono sub">${id}</span><div><div style="font-size:14px">${n} <span class="sub">· ${v}</span></div><div class="bar" style="margin-top:6px"><i style="width:${p * 25}%"></i></div></div><span class="num r">${p}/4</span></div>`).join("")}
        <div class="banner" style="padding:18px;margin-top:8px"><div class="label">LF-C</div><div class="sugg" style="font-size:24px">3.0 · FIT WITH GAPS</div><span class="muted" style="font-size:14px">mean 3.29 rounded down · gap: no technology leader for the “tech-led” pillar</span></div></div></div>`;
  if (t === "fin") return `<div class="cols"><div class="card"><h3 style="margin-bottom:16px">FY26 pillars (points out of 4)</h3>${c.pillars.map(([n, m, p]) => `<div style="display:grid;grid-template-columns:150px 1fr 50px;gap:14px;align-items:center;padding:12px 0;border-top:1px solid var(--line)"><b style="font-weight:500">${n}</b><div><div class="bar green"><i style="width:${p * 25}%"></i></div><div class="sub" style="font-size:13px;margin-top:6px">${m}</div></div><span class="num r">${p}</span></div>`).join("")}</div>
      <div class="stack"><div class="banner"><div class="label">Health grade</div><div class="sugg" style="color:var(--l-pos)">B</div><span class="muted">pillar mean 2.79 · A ≥ 3.5 · B ≥ 2.75 · C ≥ 2.0 · D ≥ 1.25</span></div>
        <div class="card"><h3 style="margin-bottom:10px">Earnings quality</h3><div class="kv"><dt>Altman Z″</dt><dd>3.1 · safe</dd><dt>Beneish M</dt><dd>−2.41 · no manipulation flag</dd><dt>Piotroski F</dt><dd>6 of 9</dd></div><p class="sub" style="font-size:13px;margin:12px 0 0">Source: FY24–FY26 AOC-4 filings (T1). Computed in code; Claude never touches a number.</p></div></div></div>`;
  if (t === "tech") return `<div class="cols"><div class="tbl-wrap"><table><thead><tr><th>Claim (slide 8)</th><th>Class</th><th>Evidence</th></tr></thead><tbody>${c.tech.map(([n, k, code, e]) => `<tr><td>${n}</td><td>${vb(k, code)}</td><td class="muted">${e}</td></tr>`).join("")}</tbody></table></div>
      <div class="card"><h3 style="margin-bottom:10px">Tech soundness</h3><div class="kv"><dt>TC-01 verified share</dt><dd>55% (ceiling 75%) → 1 (ceiling 3)</dd><dt>TC-02 engineering share</dt><dd>3% while “tech-led” is claimed → 1</dd><dt>TC-C</dt><dd><b>1.0</b> (ceiling 2.0) → requirement ≥ 2 <span style="color:var(--v-un)">open</span></dd></div></div></div>`;
  return `<div class="cols"><div class="card"><h3 style="margin-bottom:16px">Footprint share by state (GST, staff, openings, sites, fleet)</h3>${c.regions.map(([s, p]) => `<div style="display:grid;grid-template-columns:130px 1fr 60px;gap:14px;align-items:center;margin-bottom:14px"><span>${s}</span><div class="bar cyan"><i style="width:${p}%"></i></div><span class="num r">${p}%</span></div>`).join("")}
      <p class="sub" style="font-size:13.5px;margin:6px 0 0">RG-01 regions: West, North, South (4 states) · RG-02 target share 63.4% → 4 · RG-03 network fit 25% → 2 · RG-C 3</p></div>
    <div class="card"><h3 style="margin-bottom:10px">Location basis</h3><p class="muted" style="margin:0;font-size:14px">HQ is Delhi (CIN state at incorporation). GSTIN prefix 27 proves a Maharashtra registration; one PAN search lists every state registration. Fleet: 33 of 48 RCs Maharashtra-registered (VAHAN sample).</p></div></div>`;
}
function decideBlock() {
  if (S.decision) return `<div class="decided" style="margin-top:14px">${ic("check")} ${S.decision.kind === "accept" ? "Accepted" : "Overridden"} by Head of Corporate Development${S.decision.reason ? ` — “${S.decision.reason}”` : ""} · journaled</div>`;
  return `<div class="decide" style="margin-top:14px"><p class="muted" style="margin:0;font-size:14px">Suggestion only. Accept it, or override with a reason; both are journaled into the IM.</p>
    <div style="display:flex;gap:10px;flex-wrap:wrap"><button class="btn btn-primary" id="accept">${ic("check", 16)} Accept · pursue with conditions</button><button class="btn btn-ghost" id="override">Override…</button></div>
    <div id="ov" hidden><label class="sub" for="ovr" style="font-size:13px">Override to</label><div style="display:flex;gap:8px;margin:6px 0 10px;flex-wrap:wrap">${["PURSUE", "HOLD", "PASS"].map(x => `<label class="radio" style="border:1px solid var(--line)"><input type="radio" name="ovto" value="${x}"> ${x}</label>`).join("")}</div>
      <textarea id="ovr" placeholder="Reason (required) — e.g. strategic fit outweighs the tech gap"></textarea><button class="btn btn-primary" id="ovgo" style="margin-top:10px" disabled>Record override</button></div></div>`;
}
function sideSnapshot() {
  const c = D.company;
  return `<div class="card"><h3 style="margin-bottom:12px">Snapshot</h3><div class="kv"><dt>HQ</dt><dd>Delhi</dd><dt>Operates</dt><dd>MH · DL · KA · GJ</dd><dt>FY26 revenue</dt><dd>₹186 cr ${vb("verified", "V2")}</dd><dt>Employees</dt><dd>655 (EPFO) ${vb("verified", "V4")}</dd><dt>Fleet</dt><dd>48 trucks ${vb("verified", "V1")}</dd><dt>Founded</dt><dd>2011 ${vb("verified", "V1")}</dd></div></div>
    <div class="card"><h3 style="margin-bottom:12px">Critical claims</h3>${[["verified", 10], ["partial", 2], ["unverified", 1], ["nv", 1]].map(([k, n]) => `<div style="display:grid;grid-template-columns:150px 1fr 24px;gap:10px;align-items:center;margin-bottom:10px">${vb(k)}<div class="bar"><i style="width:${n / 14 * 100}%"></i></div><span class="num">${n}</span></div>`).join("")}</div>
    <div class="card"><h3 style="margin-bottom:10px">Cost of this job</h3><div class="kv"><dt>Crustdata</dt><dd class="num">212 credits</dd><dt>Claude</dt><dd class="num">≈ 1.9 M tokens · cached 61%</dd><dt>Public records</dt><dd class="num">₹300 (3 AOC-4)</dd><dt>Elapsed</dt><dd class="num">18 min</dd></div></div>`;
}
function bindCompany() {
  $$("[data-ct]").forEach(b => b.onclick = () => { S.ctab = b.dataset.ct; $$("[data-ct]").forEach(x => x.classList.toggle("on", x === b)); $("#ctab").innerHTML = companyTab(S.ctab); bindCompanyTab(); });
  bindCompanyTab();
}
function bindCompanyTab() {
  $$("[data-why]").forEach(b => b.onclick = () => { const r = $("#why" + b.dataset.why); r.hidden = !r.hidden; b.setAttribute("aria-expanded", !r.hidden); });
  $$("[data-claim]").forEach(tr => tr.onclick = () => openEvidence(D.company.claims[+tr.dataset.claim]));
  const acc = $("#accept"); if (!acc) return;
  acc.onclick = () => { S.decision = { kind: "accept" }; D.audit.push(["16:31:05", "decision.accepted", "IM-2026-11-29-003 · PURSUE WITH CONDITIONS", "9c1f…"]); $("#decide-card").innerHTML = `<span class="label">5 · Your decision</span>${decideBlock()}`; toast("Decision journaled · 2 document requests drafted for approval"); };
  $("#override").onclick = () => $("#ov").hidden = false;
  const ovr = $("#ovr"), go = $("#ovgo"), ok = () => go.disabled = !(ovr.value.trim().length > 5 && $("input[name=ovto]:checked"));
  ovr.oninput = ok; $$("input[name=ovto]").forEach(r => r.onchange = ok);
  go.onclick = () => { S.decision = { kind: "override", reason: `${$("input[name=ovto]:checked").value}: ${ovr.value.trim()}` }; D.audit.push(["16:31:40", "decision.overridden", S.decision.reason, "9c2a…"]); $("#decide-card").innerHTML = `<span class="label">5 · Your decision</span>${decideBlock()}`; toast("Override journaled with your reason"); };
}
const FP = [[/MCA master/, "mca.master.date_of_incorporation"], [/GST/, "gst.search_by_pan.registrations[].status"], [/AOC-4/, "mca.aoc4.fy26.revenue_from_operations"], [/EPFO/, "epfo.establishment.members"], [/RC|VAHAN/, "vahan.rc[].registration_state"], [/lease/, "docs.lease_deeds[].area_sqft"], [/Tier-A|daily/, "media.article.passage"], [/certificate/i, "docs.iso_certificate.valid_to"]];
const fieldPath = x => (FP.find(([r]) => r.test(x.ev)) || [, "deck.slide_" + x.s + ".text"])[1];
function openEvidence(x) {
  const passage = x.cls === "nv" ? `<span class="sub">No record found. ${x.ev}.</span>` : `… ${x.ev.replace(/(\d[\d,.]*\s?[A-Za-z%₹]*)/, "<mark>$1</mark>")} …`;
  $("#drawer").innerHTML = `<div style="display:flex;align-items:center;gap:12px;margin-bottom:18px"><div class="label">Evidence · slide ${x.s}</div><button class="x" data-close aria-label="Close">${ic("x")}</button></div>
    <h3 style="font-size:22px;margin-bottom:12px">“${x.t}”</h3><div style="margin-bottom:18px">${vb(x.cls, x.code)}</div>
    <div class="label" style="margin-bottom:8px">Quote-locked passage</div><div class="passage">${passage}</div>
    <dl class="kv" style="margin-top:20px"><dt>Source tier</dt><dd class="mono">${x.tier}</dd><dt>Record date</dt><dd>${x.date}</dd><dt>Retrieved</dt><dd>${D.asOf}</dd><dt>Field path</dt><dd class="mono">${fieldPath(x)}</dd><dt>sha256</dt><dd class="mono">3f0e9a…c41d</dd><dt>Critical</dt><dd>${x.crit ? "yes — counts in C1" : "no — FALSE costs 1 point"}</dd></dl>
    <p class="sub" style="font-size:13px;margin-top:20px">The class comes from the first-match procedure in STANDARDS §2.3. Claude proposed the passage; code checked that it exists verbatim in the stored record.</p>`;
  open("#drawer");
}

/* ---------- RESEARCH MEMOS ---------- */
function memoHead(m, title, extra) {
  return `<div class="crumbs"><a href="#/runs">Runs</a>${ic("chev", 14)}<span>Research Memo</span></div>
  <div class="title-row"><div><div class="label">Research Memo · ${m.id}</div><h1 style="margin-top:6px;max-width:900px">${title}</h1><div class="meta">as of ${D.asOf} ${extra || ""} · R3</div></div>
    <div class="actions"><span class="lbl pos">${m.status}</span><span class="lbl cond">confidence ${m.confidence}</span></div></div>
  <div class="banner" style="margin-bottom:24px"><div class="label">Answer</div><p style="font-size:19px;line-height:1.55;margin:10px 0 0;position:relative;z-index:1">${m.answer}</p></div>`;
}
function viewResearch() {
  const m = D.research, max = Math.max(...m.rows.map(r => r.d));
  return `<div class="wrap page">${memoHead(m, "Indian fintechs hiring the most engineers this quarter — and what it suggests they launch next", `· window ${m.window}`)}
    <div class="testmode" style="color:var(--ink-2);background:var(--panel-2);border-color:var(--line)">${ic("clock", 16)} Job postings indicate intent to hire, not hires made. Counts are deduped by company, title, city and 14 days.</div>
    <div class="cols"><div class="stack"><div class="tbl-wrap"><table><thead><tr><th>#</th><th>Company (sample)</th><th>Eng postings (deduped)</th><th class="r">Raw</th><th class="r">Share of its postings</th><th>Top themes</th></tr></thead><tbody>
      ${m.rows.map((r, i) => `<tr><td class="sub">${i + 1}</td><td><b>${r.n}</b></td><td style="min-width:200px"><div style="display:flex;gap:10px;align-items:center"><div class="bar" style="flex:1"><i style="width:${r.d / max * 100}%"></i></div><b class="num">${r.d}</b></div></td><td class="r num sub">${r.raw}</td><td class="r num">${r.share}%</td><td class="muted">${r.themes}</td></tr>`).join("")}</tbody></table></div>
      <h3>What their hiring suggests</h3>
      ${m.inferences.map(x => `<div class="inf"><div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap"><b>${x.n}</b><span class="muted">· likely next:</span><b style="color:var(--brand-label)">${x.next}</b><span class="strength ${x.strength}" style="margin-left:auto">INFERENCE · ${x.strength}</span></div>
        <div class="q">“${x.quote}”</div><div class="kv"><dt>Postings on theme</dt><dd>${x.posts} (${x.share}% of its engineering postings)</dd><dt>Corroboration</dt><dd>${x.corr}</dd></div><p class="note" style="margin:10px 0 0">Inference — not a verified fact.</p></div>`).join("")}</div>
    <div class="stack">${r3Card([["Q1 criteria compliance", "100%"], ["Q2 premise check", "“most” = deduped postings (proxy shown)"], ["Q3 rows", "10 / 10"], ["Q4 corroborated themes", "4 of 10"], ["Q6 padding", "none"]])}
      <div class="card"><h3 style="margin-bottom:10px">Strength rule</h3><div class="kv"><dt><span class="strength STRONG">STRONG</span></dt><dd>n ≥ 5, share ≥ 25%, corroborated</dd><dt><span class="strength MODERATE">MODERATE</span></dt><dd>n ≥ 3, share ≥ 10%</dd><dt><span class="strength WEAK">WEAK</span></dt><dd>otherwise</dd></div></div>
      <div class="card"><h3 style="margin-bottom:10px">Method &amp; cost</h3><p class="muted" style="font-size:14px;margin:0">job/search aggregation grouped by company id; listings for the top 25; fintech classifier (claude-haiku-5-5, quoted descriptions); reliable-media corroboration. ${m.credits} credits.</p></div></div></div></div>`;
}
const r3Card = rows => `<div class="card"><h3 style="margin-bottom:12px">R3 checks</h3>${rows.map(([k, v]) => `<div style="display:flex;justify-content:space-between;gap:12px;padding:9px 0;border-top:1px solid var(--line);font-size:14px"><span class="muted">${k}</span><b style="font-weight:500;text-align:right">${v}</b></div>`).join("")}</div>`;
function viewFindlist() {
  const m = D.findlist;
  return `<div class="wrap page">${memoHead(m, "Indian B2B software companies founded since 2023 whose team grew by half in six months", "· window 24 May – 22 Nov 2026")}
    <div class="cols"><div class="stack"><div class="tbl-wrap"><table><thead><tr><th>#</th><th>Company (sample)</th><th>HQ</th><th>Founded</th><th>Staff 6 mo → now</th><th>Growth</th><th>B2B evidence</th><th>Founders → before</th></tr></thead><tbody>
      ${m.rows.map((r, i) => `<tr><td class="sub">${i + 1}</td><td><b>${r.n}</b></td><td>${r.hq}</td><td class="num">${r.yr}</td><td class="num">${r.from} → ${r.to}</td><td><b class="num" style="color:var(--v-ok)">+${r.g}%</b> ${vb("partial", "P1")}</td><td class="muted" style="font-size:13.5px">${r.b2b}</td><td>${r.f.map(([t, k, c]) => `<div style="margin-bottom:6px;font-size:13.5px">${t} ${vb(k, c)}</div>`).join("")}</td></tr>`).join("")}
      <tr><td colspan="8" class="sub">… 5 more rows in the full memo</td></tr></tbody></table></div>
      <div class="card"><h3 style="margin-bottom:10px">Near-misses (shown, never padded in)</h3><ul class="list-num">${m.near.map(n => `<li><span class="muted">${n}</span></li>`).join("")}</ul></div></div>
    <div class="stack">${r3Card(m.r3)}<div class="card"><h3 style="margin-bottom:10px">Why 🟢 and not ✅?</h3><p class="muted" style="font-size:14px;margin:0">Growth and prior roles come from public profiles via Crustdata (T2). They are PARTIALLY VERIFIED unless a T1 record (MCA director data) or a reliable-media report confirms them.</p></div>
      <div class="card"><h3 style="margin-bottom:10px">Cost</h3><p class="muted" style="font-size:14px;margin:0">≈ ${m.credits} Crustdata credits · classifier tokens on claude-haiku-5-5</p></div></div></div></div>`;
}

/* ---------- APPROVALS (Gmail) ---------- */
function viewApprovals() {
  return `<div class="wrap page"><div class="title-row"><div><h1>Approvals</h1><div class="meta">Every email waits for you. Sent through Gmail SMTP, exactly once, reconciled against your Sent folder.</div></div></div>
    <div class="testmode">${ic("shield", 16)} <b>TEST MODE</b> · MAIL_MODE=test — every approved email is redirected to TEST_INBOX; the original recipient is kept in the X-DD-Original-To header.</div>
    <div class="mail-grid"><div id="mlist">${mailList()}</div><div id="mview">${mailView()}</div></div></div>`;
}
const mailList = () => S.mail.map((m, i) => `<button class="mail-item ${i === S.mailSel ? "on" : ""}" data-m="${i}"><div class="top"><span class="st ${m.status}">${m.status}</span><span class="sub" style="font-size:12.5px">${m.kind}</span><span class="mono sub" style="margin-left:auto">${m.id}</span></div><b style="font-weight:600">${m.company} (sample)</b><div class="muted" style="font-size:13.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${m.subject}</div></button>`).join("");
function mailView() {
  const m = S.mail[S.mailSel], done = m.status !== "pending";
  const eo = ["intent", "sent", "reconciled"].map((s, i) => `<span class="eo"><i class="${m.status === "sent" || (m.status === "sending" && i === 0) ? "on" : ""}"></i>${s}</span>`).join("");
  return `<div class="mailview"><div class="hdr"><div><span>From</span>${"&lt;GMAIL_ADDRESS&gt;"} <span class="sub" style="width:auto">(set at first run)</span></div><div><span>To</span>${m.to}</div><div><span>Subject</span><b style="font-weight:600">${m.subject}</b></div><div><span>Template</span><span class="mono" style="width:auto">${m.tmpl}.md.j2</span> · <span class="mono" style="width:auto">Message-ID &lt;${m.id.toLowerCase()}@datadesigner.local&gt;</span></div></div>
    <div class="body" id="mbody" contenteditable="false">${m.body}</div>
    <div class="foot">${done ? `<span class="st ${m.status}">${m.status === "sent" ? "Sent · 250 OK · reconciled via IMAP" : m.status}</span>` : `<button class="btn btn-primary" id="approve">${ic("send", 16)} Approve &amp; send</button><button class="btn btn-ghost" id="edit">${ic("edit", 16)} Edit</button><button class="btn btn-danger" id="reject">Reject</button>`}
      <span style="margin-left:auto;display:flex;gap:14px">${eo}</span></div></div>`;
}
function bindApprovals() {
  $$("[data-m]").forEach(b => b.onclick = () => { S.mailSel = +b.dataset.m; $("#mlist").innerHTML = mailList(); $("#mview").innerHTML = mailView(); bindApprovals(); });
  const m = S.mail[S.mailSel], ap = $("#approve"); if (!ap) return;
  $("#edit").onclick = () => { const b = $("#mbody"), on = b.contentEditable !== "true"; b.contentEditable = on; $("#edit").innerHTML = on ? `${ic("check", 16)} Done` : `${ic("edit", 16)} Edit`; if (on) b.focus(); else m.body = b.innerText; };
  ap.onclick = () => {
    m.status = "sending"; ap.disabled = true; $("#mlist").innerHTML = mailList(); $("#mview").innerHTML = mailView();
    D.audit.push(["16:32:10", "action.intent", `${m.id} ${m.tmpl} → ${m.company}`, "f01c…"]);
    setTimeout(() => { m.status = "sent"; D.audit.push(["16:32:11", "action.sent", "smtp.gmail.com:587 STARTTLS · 250 OK", "f01d…"], ["16:32:13", "action.reconciled", "IMAP [Gmail]/Sent Mail rfc822msgid match", "f01e…"]); render(); toast("Sent once · reconciled against Gmail Sent folder"); }, 1400);
  };
  $("#reject").onclick = () => { m.status = "rejected"; D.audit.push(["16:32:40", "action.rejected", m.id, "f020…"]); render(); toast("Rejected · nothing sent · journaled"); };
}

/* ---------- AUDIT + SETUP ---------- */
function viewAudit() {
  return `<div class="wrap page"><div class="title-row"><div><h1>Audit journal</h1><div class="meta">Append-only. Each entry hashes the previous one, so any edit breaks the chain.</div></div>
    <div class="actions"><input id="af" placeholder="Filter events…" style="background:var(--panel-2);border:1px solid var(--line);border-radius:10px;padding:10px 12px;outline:none"><button class="btn btn-ghost" id="verify">${ic("shield", 16)} Verify chain</button></div></div>
    <div class="card"><div class="journal" id="jl">${journal("")}</div></div></div>`;
}
const journal = f => D.audit.filter(a => a.join(" ").toLowerCase().includes(f)).map(([t, e, d, h]) => `<div class="jrow"><span class="num sub">${t}</span><span class="ev">${e}</span><span>${d}</span><span class="mono sub">${h}</span></div>`).join("");
function bindAudit() { $("#af").oninput = e => $("#jl").innerHTML = journal(e.target.value.toLowerCase()); $("#verify").onclick = () => toast(`Hash chain intact · ${D.audit.length} entries`); }
function viewSetup() {
  return `<div class="wrap page"><div class="title-row"><div><h1>Setup &amp; connections</h1><div class="meta">Secrets live only in the gitignored .env. On first run Claude Code asks you for them through tools/setup_secrets.py (hidden input).</div></div></div>
    <div class="conn">${D.connections.map(c => `<div class="card"><div class="tile">${ic(c.icon, 22)}</div><div style="min-width:0"><b style="font-size:17px">${c.name}</b><div class="muted" style="font-size:14px;margin:4px 0">${c.detail}</div><div class="mono sub">${c.key}</div><div class="sub" style="font-size:13px;margin-top:6px">${c.note}</div></div><span class="state ${c.state}">${c.state === "ok" ? "connected" : "asked at first run"}</span></div>`).join("")}</div>
    <div class="cols" style="margin-top:24px"><div class="card"><h3 style="margin-bottom:12px">First run</h3><pre class="code">$ make setup-secrets
<span class="k">ANTHROPIC_API_KEY</span>  (hidden): ••••••••••••   <span class="s">✓ /v1/models 200</span>
<span class="k">GMAIL_ADDRESS</span>             : you@gmail.com
<span class="k">GMAIL_APP_PASSWORD</span> (hidden): ••••••••••••••••  <span class="s">✓ SMTP login 235</span>
<span class="k">TEST_INBOX</span>                : you+dd-test@gmail.com
wrote .env (mode 600) · .env is gitignored ✓
$ make smoke   <span class="s"># Crustdata · Claude · Gmail — all green</span></pre></div>
      <div class="card"><h3 style="margin-bottom:10px">Models in use</h3><div class="kv"><dt>Extract · reason</dt><dd class="mono">claude-sonnet-5-5</dd><dt>Classify</dt><dd class="mono">claude-haiku-5-5</dd><dt>Adversarial tests</dt><dd class="mono">claude-opus-5-5</dd><dt>Output</dt><dd>structured outputs (JSON schema)</dd><dt>Determinism</dt><dd>response cache + replay</dd></div></div></div></div>`;
}

/* ---------- modal / drawer / toast / chat ---------- */
function openModal(html) { $("#modal").innerHTML = html; open("#modal"); }
function open(sel) { $("#scrim").classList.add("open"); $(sel).classList.add("open"); setTimeout(() => ($(sel).querySelector("button,input,textarea,[tabindex]") || $(sel)).focus(), 60); $$("[data-close]", $(sel)).forEach(b => b.onclick = closeAll); }
function closeAll() { ["#scrim", "#modal", "#drawer"].forEach(s => $(s).classList.remove("open")); }
let toastT; function toast(t) { const el = $("#toast"); el.innerHTML = `${ic("check", 16)} ${t}`; el.classList.add("show"); clearTimeout(toastT); toastT = setTimeout(() => el.classList.remove("show"), 2600); }
function initChat() {
  $("#bubble").innerHTML += ic("logo", 34);
  const sugs = Object.keys(D.analyst);
  $("#chat").innerHTML = `<div class="ch"><div class="tile" style="width:40px;height:40px">${ic("spark", 18)}</div><div><b>Ask the analyst</b><div class="sub" style="font-size:12.5px">Explains any number on screen · never changes a score</div></div><button class="x" id="chat-x" aria-label="Close">${ic("x")}</button></div>
    <div class="cb" id="cb"><div class="msg ai">Hi — I can walk you through any score, class or rule in this memo. Every answer cites the evidence store.</div></div>
    <div class="sugs">${sugs.map(s => `<button class="chip" data-s="${s}" style="font-size:13px">${s}</button>`).join("")}</div>
    <form id="cf"><input id="ci" placeholder="Ask about this memo…" aria-label="Message"><button class="btn btn-primary btn-sm">${ic("send", 16)}</button></form>`;
  const ask = q => {
    const cb = $("#cb"); cb.insertAdjacentHTML("beforeend", `<div class="msg me">${q.replace(/</g, "&lt;")}</div><div class="msg ai typing" id="ty"><span></span><span></span><span></span></div>`); cb.scrollTop = 1e6;
    const a = D.analyst[q] || Object.entries(D.analyst).find(([k]) => k.toLowerCase().split(" ").filter(w => w.length > 4).some(w => q.toLowerCase().includes(w)))?.[1] || "In the build this calls claude-sonnet-5-5 over this memo’s evidence store and answers with citations. Try one of the suggested questions.";
    setTimeout(() => { $("#ty").remove(); cb.insertAdjacentHTML("beforeend", `<div class="msg ai">${a}</div>`); cb.scrollTop = 1e6; }, 700);
  };
  $$("[data-s]", $("#chat")).forEach(b => b.onclick = () => ask(b.dataset.s));
  $("#cf").onsubmit = e => { e.preventDefault(); const v = $("#ci").value.trim(); if (v) { ask(v); $("#ci").value = ""; } };
  const tog = o => { $("#chat").classList.toggle("open", o); if (o) { $(".bubble .badge")?.remove(); $("#ci").focus(); } };
  $("#bubble").onclick = () => tog(!$("#chat").classList.contains("open")); $("#chat-x").onclick = () => tog(false);
}

/* ---------- router ---------- */
function render() {
  const route = (location.hash || "#/ask").slice(1);
  nav(route);
  const [, a, b] = route.split("/");
  const main = $("#main");
  const views = {
    ask: [viewAsk, bindAsk], runs: [viewRuns, () => {}], market: [viewMarket, () => {}], company: [viewCompany, bindCompany],
    approvals: [viewApprovals, bindApprovals], audit: [viewAudit, bindAudit], setup: [viewSetup, () => {}]
  };
  if (a === "run" && D.runs[b]) { main.innerHTML = viewRun(b); bindRun(b); }
  else if (a === "memo") { main.innerHTML = b === "findlist" ? viewFindlist() : viewResearch(); }
  else { const v = views[a] || views.ask; main.innerHTML = v[0](); v[1](); }
  $$("tr[data-href]").forEach(tr => tr.onclick = () => location.hash = tr.dataset.href);
  $("#screen") && ($("#screen").onclick = () => { toast("3 teaser requests drafted → Approvals"); setTimeout(() => location.hash = "#/approvals", 700); });
}
window.addEventListener("hashchange", () => { closeAll(); render(); window.scrollTo({ top: 0 }); });
document.addEventListener("keydown", e => {
  if (e.key === "Escape") { closeAll(); $("#chat").classList.remove("open"); }
  if (e.key === "/" && !/INPUT|TEXTAREA/.test(document.activeElement.tagName) && !document.activeElement.isContentEditable) { e.preventDefault(); location.hash !== "#/ask" && (location.hash = "#/ask"); setTimeout(() => $("#q")?.focus(), 30); }
});
$("#scrim").onclick = closeAll;
footer(); initChat(); render();
})();
