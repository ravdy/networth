/* Net Worth Tracker — frontend (no build step, no external dependencies). */
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const SVGNS = "http://www.w3.org/2000/svg";

const CAT_COLOR = { equity: "--s1", debt: "--s2", real_estate: "--s3", gold: "--s4", cash: "--s5", crypto: "--s6", other: "--s7" };
const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const catColor = (key) => `var(${CAT_COLOR[key] || "--s7"})`;

const state = { meta: null, summary: null, assets: [], liabilities: [], recs: null, settings: null };

// ---------- formatting ----------
const inr = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 });
const fmt = (v) => (v == null ? "—" : inr.format(v));
function fmtShort(v) {
  if (v == null) return "—";
  const a = Math.abs(v), s = v < 0 ? "-" : "";
  if (a >= 1e7) return `${s}₹${(a / 1e7).toFixed(2)} Cr`;
  if (a >= 1e5) return `${s}₹${(a / 1e5).toFixed(2)} L`;
  if (a >= 1e3) return `${s}₹${(a / 1e3).toFixed(1)} K`;
  return `${s}₹${a.toFixed(0)}`;
}
const fmtTenure = (m) => (m == null || m === "" ? "—" : m < 12 ? `${m} mo` : `${Math.floor(m / 12)} yr${m % 12 ? ` ${m % 12} mo` : ""}`);
const pct = (v, d = 1) => (v == null ? "—" : `${v.toFixed(d)}%`);
const signed = (v, f = fmt) => (v > 0 ? "+" : "") + f(v);
const cls = (v) => (v > 0 ? "up" : v < 0 ? "down" : "");
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const todayISO = () => new Date().toLocaleDateString("en-CA");
const fmtDate = (d) => (d ? new Date(d + "T00:00:00").toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }) : "—");

// ---------- api ----------
async function api(path, opts = {}) {
  const res = await fetch(path, {
    ...opts,
    headers: { "Content-Type": "application/json", "X-NW": "1" },  // X-NW: proves the request comes from this app
    credentials: "same-origin",
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (res.status === 401 && !path.startsWith("/api/auth/")) {  // session expired -> back to sign-in
    location.replace("/login");
    throw new Error("Signed out");
  }
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const j = await res.json();
      msg = Array.isArray(j.detail) ? j.detail.map((d) => `${d.loc.slice(-1)[0]}: ${d.msg}`).join("; ") : j.detail || msg;
    } catch (_) { /* ignore */ }
    throw new Error(msg);
  }
  return res.status === 204 ? null : res.json();
}

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => (t.hidden = true), 2600);
}

// ---------- tooltip ----------
const tip = $("#tooltip");
function showTip(html, ev) {
  tip.innerHTML = html;
  tip.hidden = false;
  const pad = 14, w = tip.offsetWidth, h = tip.offsetHeight;
  let x = ev.clientX + pad, y = ev.clientY + pad;
  if (x + w > innerWidth - 8) x = ev.clientX - w - pad;
  if (y + h > innerHeight - 8) y = ev.clientY - h - pad;
  tip.style.left = x + "px";
  tip.style.top = y + "px";
}
const hideTip = () => (tip.hidden = true);

// ---------- tabs ----------
function showTab(name) {
  $$(".tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  $$(".tab").forEach((t) => t.classList.toggle("active", t.id === "tab-" + name));
  if (location.hash !== "#" + name) history.replaceState(null, "", "#" + name);
  if (name === "dashboard") { // width-dependent charts
    renderHistory();
    if (state.growth) renderGrowth($("#growth"), state.growth);
  }
}
$$(".tabs button").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));
$$("[data-goto]").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.goto)));

// ---------- data refresh ----------
async function refresh() {
  const [summary, assets, liabilities, recs] = await Promise.all([
    api("/api/summary"), api("/api/assets"), api("/api/liabilities"), api("/api/recommendations"),
  ]);
  Object.assign(state, { summary, assets, liabilities, recs });
  renderDashboard();
  renderAssets();
  renderLiabilities();
  renderInsights();
  refreshExcelStatus();
}
addEventListener("focus", () => refreshExcelStatus());

const primaryCat = (weights) => Object.entries(weights).sort((a, b) => b[1] - a[1])[0][0];
const typeMeta = (key) => state.meta.asset_types.find((t) => t.key === key);

// ===================================================================
// DASHBOARD
// ===================================================================
function renderDashboard() {
  const s = state.summary;
  $("#nw-value").textContent = fmt(s.net_worth);
  $("#nw-sub").textContent = `${fmtShort(s.net_worth)} · ${s.asset_count} assets · ${s.liability_count} liabilities`;
  $("#t-assets").textContent = fmtShort(s.total_assets);
  $("#t-liabs").textContent = fmtShort(s.total_liabilities);
  $("#t-invested").textContent = fmtShort(s.total_invested);
  const g = $("#t-gain");
  const gp = s.total_invested > 0 ? (s.total_gain / s.total_invested) * 100 : null;
  g.innerHTML = `<span class="${cls(s.total_gain)}">${signed(s.total_gain, fmtShort)}</span>` + (gp != null ? ` <small class="muted">${pct(gp)}</small>` : "");

  renderDonut(s.by_category.filter((c) => c.value > 0), s.total_assets);
  renderTypeBars(s.by_group.map((g) => ({
    label: `${g.group} (${g.count})`, value: g.value, pct: g.pct,
    detail: g.types.map((t) => `${esc(t.label)}: ${fmtShort(t.value)}`).join("<br>"),
  })));
  renderHistory();
  loadGrowth();
  renderRecs($("#dash-recs"), state.recs.items.filter((r) => r.severity !== "good").slice(0, 3));
}

function arcPath(cx, cy, r0, r1, a0, a1) {
  const large = a1 - a0 > Math.PI ? 1 : 0;
  const p = (r, a) => [cx + r * Math.sin(a), cy - r * Math.cos(a)];
  const [x0, y0] = p(r1, a0), [x1, y1] = p(r1, a1), [x2, y2] = p(r0, a1), [x3, y3] = p(r0, a0);
  return `M${x0},${y0} A${r1},${r1} 0 ${large} 1 ${x1},${y1} L${x2},${y2} A${r0},${r0} 0 ${large} 0 ${x3},${y3} Z`;
}

function renderDonut(cats, total) {
  const wrap = $("#donut");
  if (!cats.length) {
    wrap.innerHTML = `<div class="empty">Add assets to see how your money is split across segments.</div>`;
    return;
  }
  const size = 200, cx = 100, cy = 100, r1 = 96, r0 = 64;
  const svg = document.createElementNS(SVGNS, "svg");
  svg.setAttribute("viewBox", `0 0 ${size} ${size}`);
  svg.setAttribute("width", size);
  svg.setAttribute("height", size);
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", "Allocation by segment: " + cats.map((c) => `${c.label} ${c.pct.toFixed(1)}%`).join(", "));

  let a = 0;
  const segs = {};
  cats.forEach((c) => {
    const sweep = (c.value / total) * Math.PI * 2;
    let el;
    if (cats.length === 1) {
      el = document.createElementNS(SVGNS, "path");
      el.setAttribute("d", arcPath(cx, cy, r0, r1, 0, Math.PI * 1.9999));
    } else {
      el = document.createElementNS(SVGNS, "path");
      el.setAttribute("d", arcPath(cx, cy, r0, r1, a, a + sweep));
    }
    el.setAttribute("fill", catColor(c.key));
    el.setAttribute("stroke", "var(--surface)");
    el.setAttribute("stroke-width", "2");
    el.classList.add("donut-seg");
    el.dataset.key = c.key;
    svg.appendChild(el);
    segs[c.key] = el;
    a += sweep;
  });
  const t1 = document.createElementNS(SVGNS, "text");
  t1.setAttribute("x", cx); t1.setAttribute("y", cy - 4); t1.setAttribute("text-anchor", "middle");
  t1.setAttribute("style", "fill:var(--text);font-size:18px;font-weight:700");
  t1.textContent = fmtShort(total);
  const t2 = document.createElementNS(SVGNS, "text");
  t2.setAttribute("x", cx); t2.setAttribute("y", cy + 16); t2.setAttribute("text-anchor", "middle");
  t2.setAttribute("style", "fill:var(--text-2);font-size:11px");
  t2.textContent = "total assets";
  svg.append(t1, t2);

  const ul = document.createElement("ul");
  ul.className = "legend";
  ul.innerHTML = cats.map((c) => `
    <li data-key="${c.key}"><span class="sw" style="background:${catColor(c.key)}"></span>
      <span>${esc(c.label)}</span><span class="val">${fmtShort(c.value)}</span><span class="pct">${c.pct.toFixed(1)}%</span></li>`).join("");

  wrap.replaceChildren(svg, ul);

  const hl = (key, ev) => {
    wrap.classList.toggle("hovering", !!key);
    Object.entries(segs).forEach(([k, el]) => el.classList.toggle("hl", k === key));
    $$("li", ul).forEach((li) => li.classList.toggle("hl", li.dataset.key === key));
    if (key && ev) {
      const c = cats.find((x) => x.key === key);
      showTip(`${esc(c.label)}<br><b>${fmt(c.value)}</b> · ${c.pct.toFixed(1)}%`, ev);
    } else hideTip();
  };
  Object.values(segs).forEach((el) => {
    el.addEventListener("mousemove", (ev) => hl(el.dataset.key, ev));
    el.addEventListener("mouseleave", () => hl(null));
  });
  $$("li", ul).forEach((li) => {
    li.addEventListener("mouseenter", () => hl(li.dataset.key));
    li.addEventListener("mouseleave", () => hl(null));
  });
}

function renderTypeBars(types) {
  const el = $("#type-bars");
  if (!types.length) {
    el.innerHTML = `<div class="empty">No assets yet.</div>`;
    return;
  }
  let rows = types;
  if (types.length > 9) {
    const rest = types.slice(8);
    rows = [...types.slice(0, 8), {
      label: `Other (${rest.length} types)`,
      value: rest.reduce((s, t) => s + t.value, 0),
      pct: rest.reduce((s, t) => s + t.pct, 0),
    }];
  }
  const max = Math.max(...rows.map((r) => r.pct));
  el.innerHTML = rows.map((r) => `
    <div class="tb-row" data-tip="${esc(r.label)}<br><b>${fmt(r.value)}</b> · ${r.pct.toFixed(1)}%${r.detail ? `<br><span style='opacity:.75'>${r.detail}</span>` : ""}">
      <div class="tb-label" title="${esc(r.label)}">${esc(r.label)}</div>
      <div class="tb-pct">${r.pct.toFixed(1)}%</div>
      <div class="tb-track"><div class="tb-fill" style="width:${(r.pct / max) * 100}%"></div></div>
    </div>`).join("");
  $$(".tb-row", el).forEach((row) => {
    row.addEventListener("mousemove", (ev) => showTip(row.dataset.tip, ev));
    row.addEventListener("mouseleave", hideTip);
  });
}

function niceTicks(min, max, n = 4) {
  if (min === max) { min = min * 0.9; max = max * 1.1 || 1; }
  const step0 = (max - min) / n;
  const mag = Math.pow(10, Math.floor(Math.log10(Math.abs(step0))));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= step0);
  const lo = Math.floor(min / step) * step, hi = Math.ceil(max / step) * step;
  const ticks = [];
  for (let v = lo; v <= hi + step / 2; v += step) ticks.push(v);
  return ticks;
}

function renderHistory() {
  const el = $("#history");
  const h = state.summary?.history || [];
  if (!el.offsetWidth) return; // hidden tab; re-rendered when shown
  if (h.length < 2) {
    el.innerHTML = `<div class="empty">History builds up automatically — one point is saved for each day you add or update values.${h.length === 1 ? ` First point: ${fmt(h[0].net_worth)} on ${fmtDate(h[0].date)}.` : ""}</div>`;
    return;
  }
  const W = el.offsetWidth, H = 240, m = { t: 12, r: 16, b: 26, l: 64 };
  const xs = h.map((p) => new Date(p.date + "T00:00:00").getTime());
  const ys = h.map((p) => p.net_worth);
  const ticks = niceTicks(Math.min(0, ...ys) < 0 ? Math.min(...ys) : Math.min(...ys), Math.max(...ys));
  const y0 = ticks[0], y1 = ticks[ticks.length - 1];
  const X = (t) => m.l + ((t - xs[0]) / (xs[xs.length - 1] - xs[0])) * (W - m.l - m.r);
  const Y = (v) => m.t + (1 - (v - y0) / (y1 - y0)) * (H - m.t - m.b);

  let s = `<svg width="${W}" height="${H}" role="img" aria-label="Net worth over time">`;
  ticks.forEach((t) => {
    s += `<line x1="${m.l}" x2="${W - m.r}" y1="${Y(t)}" y2="${Y(t)}" stroke="var(--grid)" stroke-width="1"/>`;
    s += `<text x="${m.l - 8}" y="${Y(t) + 4}" text-anchor="end">${fmtShort(t)}</text>`;
  });
  // x labels: up to 6
  const nx = Math.min(6, h.length);
  for (let i = 0; i < nx; i++) {
    const idx = Math.round((i * (h.length - 1)) / (nx - 1));
    const anchor = i === 0 ? "start" : i === nx - 1 ? "end" : "middle";
    s += `<text x="${X(xs[idx])}" y="${H - 6}" text-anchor="${anchor}">${new Date(xs[idx]).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "2-digit" })}</text>`;
  }
  const pts = h.map((p, i) => `${X(xs[i])},${Y(p.net_worth)}`);
  const base = Y(Math.max(y0, 0));
  s += `<path d="M${pts[0]} L${pts.join(" L")} L${X(xs[xs.length - 1])},${base} L${X(xs[0])},${base} Z" fill="var(--s1)" opacity="0.10"/>`;
  s += `<path d="M${pts.join(" L")}" fill="none" stroke="var(--s1)" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>`;
  s += `<line id="hx" y1="${m.t}" y2="${H - m.b}" stroke="var(--axis)" stroke-width="1" visibility="hidden"/>`;
  s += `<circle id="hd" r="5" fill="var(--s1)" stroke="var(--surface)" stroke-width="2" visibility="hidden"/>`;
  s += `<rect x="${m.l}" y="${m.t}" width="${W - m.l - m.r}" height="${H - m.t - m.b}" fill="transparent" id="hz"/>`;
  s += `</svg>`;
  el.innerHTML = s;

  const zone = $("#hz", el), line = $("#hx", el), dot = $("#hd", el);
  zone.addEventListener("mousemove", (ev) => {
    const r = el.getBoundingClientRect();
    const mx = ev.clientX - r.left;
    let best = 0;
    xs.forEach((x, i) => { if (Math.abs(X(x) - mx) < Math.abs(X(xs[best]) - mx)) best = i; });
    const p = h[best];
    line.setAttribute("x1", X(xs[best])); line.setAttribute("x2", X(xs[best]));
    dot.setAttribute("cx", X(xs[best])); dot.setAttribute("cy", Y(p.net_worth));
    line.setAttribute("visibility", "visible"); dot.setAttribute("visibility", "visible");
    showTip(`${fmtDate(p.date)}<br>Net worth <b>${fmt(p.net_worth)}</b><br>Assets ${fmtShort(p.assets)} · Liabilities ${fmtShort(p.liabilities)}`, ev);
  });
  zone.addEventListener("mouseleave", () => {
    line.setAttribute("visibility", "hidden"); dot.setAttribute("visibility", "hidden"); hideTip();
  });
}
// ---------- invested vs current value over time (+ growth % bars) ----------
async function loadGrowth() {
  const sel = $("#growth-asset");
  const keep = sel.value;
  sel.innerHTML = `<option value="">All assets</option>` +
    state.assets.map((a) => `<option value="${a.id}">${esc(a.name)}</option>`).join("");
  sel.value = state.assets.some((a) => String(a.id) === keep) ? keep : "";
  state.growth = await api("/api/growth" + (sel.value ? `?asset_id=${sel.value}` : ""));
  renderGrowth($("#growth"), state.growth);
}
$("#growth-asset").addEventListener("change", loadGrowth);

function renderGrowth(el, pts, opts = {}) {
  if (!el || !el.offsetWidth) return;
  if (!pts.length) {
    el.innerHTML = `<div class="empty">Add an asset to start the chart.</div>`;
    return;
  }
  // Invested = running total on every purchase/sale date.
  // Current value = only the dates you actually recorded a value (Update value), plus today.
  const last = pts[pts.length - 1];
  const vpts = pts.filter((p, i) => p.value_update || i === pts.length - 1);

  const W = el.offsetWidth, H1 = opts.height || 260, H2 = 80, gap = 16;
  const m = { t: 14, r: 96, b: 24, l: 68 };
  const H = H1 + gap + H2;
  const t = (p) => new Date(p.date + "T00:00:00").getTime();
  const xs = pts.map(t);
  const span = xs[xs.length - 1] - xs[0];
  const X = (ms) => (span ? m.l + ((ms - xs[0]) / span) * (W - m.l - m.r) : (m.l + W - m.r) / 2);

  const vals = [...pts.map((p) => p.invested), ...vpts.map((p) => p.value)];
  const ticks = niceTicks(Math.min(0, ...vals), Math.max(...vals));
  const y0 = ticks[0], y1 = ticks[ticks.length - 1];
  const Y = (v) => m.t + (1 - (v - y0) / (y1 - y0)) * (H1 - m.t - m.b);

  let s = `<svg width="${W}" height="${H}" role="img" aria-label="Total invested over time versus current value at each update">`;
  ticks.forEach((tk) => {
    s += `<line x1="${m.l}" x2="${W - m.r}" y1="${Y(tk)}" y2="${Y(tk)}" stroke="var(--grid)"/>`;
    s += `<text x="${m.l - 8}" y="${Y(tk) + 4}" text-anchor="end">${fmtShort(tk)}</text>`;
  });
  // x labels: first, last, and a few evenly spaced in between
  const nx = Math.min(5, pts.length);
  for (let i = 0; i < nx; i++) {
    const idx = nx === 1 ? 0 : Math.round((i * (pts.length - 1)) / (nx - 1));
    const anchor = nx === 1 ? "middle" : i === 0 ? "start" : i === nx - 1 ? "end" : "middle";
    s += `<text x="${X(xs[idx])}" y="${H1 - 6}" text-anchor="${anchor}">${new Date(xs[idx]).toLocaleDateString("en-IN", { month: "short", year: "2-digit" })}</text>`;
  }

  // accumulated invested: step area (only changes on purchase/sale dates)
  let inv = `M${X(xs[0])},${Y(pts[0].invested)}`;
  for (let i = 1; i < pts.length; i++) inv += ` L${X(xs[i])},${Y(pts[i - 1].invested)} L${X(xs[i])},${Y(pts[i].invested)}`;
  const base = Y(Math.max(0, y0));
  s += `<path d="${inv} L${X(xs[xs.length - 1])},${base} L${X(xs[0])},${base} Z" fill="var(--text-2)" opacity="0.08"/>`;
  s += `<path d="${inv}" fill="none" stroke="var(--text-2)" stroke-width="2"/>`;

  // current value: line through the recorded values, dot at each update
  if (vpts.length > 1) s += `<path d="M${vpts.map((p) => `${X(t(p))},${Y(p.value)}`).join(" L")}" fill="none" stroke="var(--s1)" stroke-width="2" stroke-linejoin="round"/>`;
  vpts.forEach((p) => {
    s += `<circle cx="${X(t(p))}" cy="${Y(p.value)}" r="5" fill="var(--s1)" stroke="var(--surface)" stroke-width="2"/>`;
  });
  // gap between invested and current value today
  if (Math.abs(last.value - last.invested) > 0) {
    const xl = X(xs[xs.length - 1]) + 10;
    s += `<line x1="${xl}" x2="${xl}" y1="${Y(last.value)}" y2="${Y(last.invested)}" stroke="${last.gain >= 0 ? "var(--good)" : "var(--critical)"}" stroke-width="2"/>`;
  }
  // direct end labels (nudged apart if they collide)
  let ly1 = Y(last.value), ly2 = Y(last.invested);
  if (Math.abs(ly1 - ly2) < 30) { const mid = (ly1 + ly2) / 2, up = last.value >= last.invested ? -1 : 1; ly1 = mid + up * 15; ly2 = mid - up * 15; }
  s += `<text class="end-label" x="${W - m.r + 18}" y="${ly1 - 2}">Current</text><text x="${W - m.r + 18}" y="${ly1 + 11}">${fmtShort(last.value)}</text>`;
  s += `<text class="end-label" x="${W - m.r + 18}" y="${ly2 - 2}">Invested</text><text x="${W - m.r + 18}" y="${ly2 + 11}">${fmtShort(last.invested)}</text>`;

  // growth % at each value update
  const g = vpts.map((p) => p.gain_pct ?? 0);
  const gPos = Math.max(0, ...g), gNeg = Math.min(0, ...g);
  const gScale = (H2 - 22) / (gPos - gNeg || 1);
  const gTop = H1 + gap, gZero = gTop + 10 + gPos * gScale;
  const GH = (v) => Math.abs(v) * gScale;
  const bw = Math.max(6, Math.min(16, ((W - m.l - m.r) / Math.max(vpts.length, 1)) * 0.5));
  s += `<line x1="${m.l}" x2="${W - m.r}" y1="${gZero}" y2="${gZero}" stroke="var(--axis)"/>`;
  s += `<text x="${m.l - 8}" y="${gZero + 4}" text-anchor="end">0%</text>`;
  s += `<text x="${m.l - 8}" y="${gTop + 8}" text-anchor="end">Growth</text>`;
  vpts.forEach((p) => {
    if (p.gain_pct == null) return;
    const h = Math.max(1, GH(p.gain_pct)), x = X(t(p)) - bw / 2;
    const yTop = p.gain_pct >= 0 ? gZero - h : gZero;
    const r = Math.min(4, bw / 2, h);
    // rounded only on the data end, flat on the baseline
    const d = p.gain_pct >= 0
      ? `M${x},${gZero} V${yTop + r} Q${x},${yTop} ${x + r},${yTop} H${x + bw - r} Q${x + bw},${yTop} ${x + bw},${yTop + r} V${gZero} Z`
      : `M${x},${gZero} V${gZero + h - r} Q${x},${gZero + h} ${x + r},${gZero + h} H${x + bw - r} Q${x + bw},${gZero + h} ${x + bw},${gZero + h - r} V${gZero} Z`;
    s += `<path d="${d}" fill="${p.gain_pct >= 0 ? "var(--good)" : "var(--critical)"}"/>`;
  });
  if (last.gain_pct != null) {
    const ly = last.gain_pct >= 0 ? gZero - GH(last.gain_pct) : gZero + GH(last.gain_pct);
    s += `<text class="end-label" x="${W - m.r + 18}" y="${ly + 4}">${last.gain_pct >= 0 ? "+" : ""}${last.gain_pct.toFixed(1)}%</text>`;
  }

  s += `<line class="gx" y1="${m.t}" y2="${H - 4}" stroke="var(--axis)" visibility="hidden"/>`;
  s += `<rect class="gz" x="${m.l - 6}" y="0" width="${W - m.l - m.r + 12}" height="${H}" fill="transparent"/>`;
  s += `</svg>`;
  el.innerHTML = `<div class="chart-legend">` +
    `<span><i class="box" style="background:var(--text-2);opacity:.5"></i>Total invested (accumulated)</span>` +
    `<span><i style="border-color:var(--s1)"></i>Current value (each update)</span>` +
    `<span><i class="box" style="background:var(--good)"></i>Growth %</span>` +
    `<span><i class="box" style="background:var(--critical)"></i>Loss %</span></div>` + s;

  const zone = $(".gz", el), line = $(".gx", el);
  zone.addEventListener("mousemove", (ev) => {
    const mx = ev.clientX - $("svg", el).getBoundingClientRect().left;
    let best = 0;
    xs.forEach((x, i) => { if (Math.abs(X(x) - mx) < Math.abs(X(xs[best]) - mx)) best = i; });
    const p = pts[best];
    const isValue = p.value_update || best === pts.length - 1;
    line.setAttribute("x1", X(xs[best])); line.setAttribute("x2", X(xs[best])); line.setAttribute("visibility", "visible");
    showTip(`<b>${fmtDate(p.date)}</b>${p.value_update ? " · value updated" : ""}<br>Total invested <b>${fmt(p.invested)}</b>` +
      (isValue
        ? `<br>Current value <b>${fmt(p.value)}</b><br>Gain <b>${signed(p.gain)}</b> (${p.gain_pct != null ? signed(p.gain_pct, (v) => v.toFixed(1) + "%") : "—"})`
        : `<br><span style="opacity:.75">purchase / payment — no value recorded on this date</span>`), ev);
  });
  zone.addEventListener("mouseleave", () => { line.setAttribute("visibility", "hidden"); hideTip(); });
}

let resizeT;
addEventListener("resize", () => {
  clearTimeout(resizeT);
  resizeT = setTimeout(() => { renderHistory(); if (state.growth) renderGrowth($("#growth"), state.growth); }, 150);
});

function renderRecs(el, items) {
  const icon = { high: "▲ Act", medium: "● Review", info: "ⓘ Tip", good: "✓ Good" };
  if (!items.length) {
    el.innerHTML = `<div class="muted">Nothing urgent — your portfolio looks in good shape.</div>`;
    return;
  }
  el.innerHTML = items.map((r) => `
    <div class="rec ${r.severity}">
      <span class="badge">${icon[r.severity]}</span>
      <div class="title">${esc(r.title)}<span class="area">${esc(r.area)}</span></div>
      <div class="detail">${esc(r.detail)}</div>
    </div>`).join("");
}

// ===================================================================
// ASSETS
// ===================================================================
// ---------- sortable tables ----------
const sortState = (() => {
  try { return JSON.parse(localStorage.getItem("nw-sort") || "{}"); } catch (_) { return {}; }
})();
sortState.assets ||= { key: "current_value", dir: "desc" };
sortState.liabs ||= { key: "outstanding", dir: "desc" };
function sortRows(list, { key, dir }) {
  const sign = dir === "asc" ? 1 : -1;
  return [...list].sort((a, b) => {
    const x = a[key], y = b[key];
    if (x == null && y == null) return 0;
    if (x == null) return 1;            // empty values always last
    if (y == null) return -1;
    return (typeof x === "string" ? x.localeCompare(y, "en-IN", { sensitivity: "base" }) : x - y) * sign;
  });
}
function wireSort(tableSel, which, render) {
  const ths = $$(`${tableSel} th[data-sort]`);
  const paint = () => ths.forEach((th) => {
    const on = th.dataset.sort === sortState[which].key;
    th.classList.toggle("sorted", on);
    th.dataset.arrow = on ? (sortState[which].dir === "asc" ? "▲" : "▼") : "";
    th.setAttribute("aria-sort", on ? (sortState[which].dir === "asc" ? "ascending" : "descending") : "none");
  });
  ths.forEach((th) => {
    th.tabIndex = 0;
    const go = () => {
      const k = th.dataset.sort, cur = sortState[which];
      // first click: names A→Z and dates oldest first, numbers biggest first; next click reverses
      const textual = ["name", "first_date", "start_date", "end_date"].includes(k);
      sortState[which] = cur.key === k ? { key: k, dir: cur.dir === "asc" ? "desc" : "asc" } : { key: k, dir: textual ? "asc" : "desc" };
      try { localStorage.setItem("nw-sort", JSON.stringify(sortState)); } catch (_) { /* ignore */ }
      paint();
      render();
    };
    th.addEventListener("click", go);
    th.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } });
  });
  paint();
}

// collapsed groups are remembered per browser
const collapsed = new Set((() => { try { return JSON.parse(localStorage.getItem("nw-collapsed") || "[]"); } catch (_) { return []; } })());
const saveCollapsed = () => { try { localStorage.setItem("nw-collapsed", JSON.stringify([...collapsed])); } catch (_) { /* ignore */ } };

function assetRow(a) {
  return `
    <tr data-id="${a.id}" class="asset-row">
      <td class="indent"><div class="asset-name">${esc(a.name)}</div>
        <div class="asset-type"><span class="dot" style="background:${catColor(primaryCat(a.weights))}"></span>${esc(a.type_label)}${a.units ? ` · ${a.units} units` : ""}</div></td>
      <td>${fmtDate(a.first_date)}${a.tx_count > 1 ? `<br><small class="muted">${a.tx_count} purchases/sales</small>` : ""}</td>
      <td class="num">${fmt(a.invested)}</td>
      <td class="num"><b>${fmt(a.current_value)}</b><br><small class="muted">as of ${fmtDate(a.value_date)}</small></td>
      <td class="num ${cls(a.gain)}">${signed(a.gain)}<br><small>${a.gain_pct != null ? signed(a.gain_pct, (v) => v.toFixed(1) + "%") : ""}</small></td>
      <td class="num ${cls(a.xirr)}">${a.xirr != null ? pct(a.xirr) : "—"}</td>
      <td><div class="row-actions">
        <button class="small primary" data-act="value">Update value</button>
        <button class="small" data-act="tx">Add payment</button>
        <button class="small" data-act="detail">Details</button>
      </div></td>
    </tr>`;
}

function renderAssets() {
  const q = $("#asset-search").value.trim().toLowerCase();
  const f = $("#asset-filter").value;
  const list = state.assets.filter((a) =>
    (!q || a.name.toLowerCase().includes(q) || a.type_label.toLowerCase().includes(q) || a.group.toLowerCase().includes(q)) &&
    (!f || a.weights[f]));
  $("#asset-empty").hidden = state.assets.length > 0;

  // group in catalog order (same order the server uses for by_group)
  const order = [...new Set(state.meta.asset_types.map((t) => t.group))];
  const groups = new Map();
  sortRows(list, sortState.assets).forEach((a) => {
    if (!groups.has(a.group)) groups.set(a.group, []);
    groups.get(a.group).push(a);
  });
  const names = [...groups.keys()].sort((a, b) => (order.indexOf(a) + 1 || 99) - (order.indexOf(b) + 1 || 99));
  const searching = !!(q || f);

  $("#asset-rows").innerHTML = names.map((g) => {
    const items = groups.get(g);
    const inv = items.reduce((s, a) => s + a.invested, 0), cur = items.reduce((s, a) => s + a.current_value, 0);
    const gp = inv > 0 ? ((cur - inv) / inv) * 100 : null;
    const open = searching || !collapsed.has(g);
    return `
      <tr class="group-row" data-group="${esc(g)}" aria-expanded="${open}">
        <td><button class="group-toggle" type="button"><span class="chev">${open ? "▾" : "▸"}</span>${esc(g)} <span class="muted">(${items.length})</span></button></td>
        <td></td>
        <td class="num">${fmt(inv)}</td>
        <td class="num"><b>${fmt(cur)}</b></td>
        <td class="num ${cls(cur - inv)}">${signed(cur - inv)}<br><small>${gp != null ? signed(gp, (v) => v.toFixed(1) + "%") : ""}</small></td>
        <td></td><td></td>
      </tr>` + (open ? items.map(assetRow).join("") : "");
  }).join("");

  if (list.length) {
    const inv = list.reduce((s, a) => s + a.invested, 0), cur = list.reduce((s, a) => s + a.current_value, 0);
    $("#asset-foot").innerHTML = `<tr><td>Total (${list.length})</td><td></td><td class="num">${fmt(inv)}</td><td class="num">${fmt(cur)}</td>
      <td class="num ${cls(cur - inv)}">${signed(cur - inv)}</td><td></td><td></td></tr>`;
  } else {
    $("#asset-foot").innerHTML = state.assets.length ? `<tr><td colspan="7" class="muted">No assets match the filter.</td></tr>` : "";
  }
}
$("#asset-search").addEventListener("input", renderAssets);
$("#asset-filter").addEventListener("change", renderAssets);
$("#asset-rows").addEventListener("click", (ev) => {
  const gr = ev.target.closest("tr.group-row");
  if (gr) {
    const g = gr.dataset.group;
    collapsed.has(g) ? collapsed.delete(g) : collapsed.add(g);
    saveCollapsed();
    return renderAssets();
  }
  const b = ev.target.closest("button[data-act]");
  if (!b) return;
  const id = +b.closest("tr").dataset.id;
  ({ value: valueModal, tx: txModal, detail: assetDetailModal })[b.dataset.act](id);
});

function typeOptions(selected) {
  const groups = {};
  state.meta.asset_types.forEach((t) => (groups[t.group] ||= []).push(t));
  return `<option value="" disabled ${selected ? "" : "selected"}>Select asset type…</option>` +
    Object.entries(groups).map(([g, ts]) => `<optgroup label="${esc(g)}">${ts.map((t) =>
      `<option value="${t.key}" ${t.key === selected ? "selected" : ""}>${esc(t.label)}</option>`).join("")}</optgroup>`).join("");
}

// ---------- modal helper ----------
const modal = $("#modal");
modal.addEventListener("close", () => modal.classList.remove("wide"));
function openModal(html, onSubmit, onReady) {
  // fresh <form> each time, so click listeners from a previous dialog can't pile up
  const old = $("#modal-form");
  const form = old.cloneNode(false);
  old.replaceWith(form);
  form.innerHTML = html;
  form.onsubmit = async (ev) => {
    ev.preventDefault();
    if (ev.submitter?.value === "cancel") return modal.close();
    const data = Object.fromEntries(new FormData(form));
    const btn = $("button[type=submit]:not([value=cancel])", form);
    if (btn) btn.disabled = true;
    try {
      const ok = await onSubmit(data);
      if (ok !== false) modal.close();
    } catch (e) {
      toast("Error: " + e.message);
    } finally {
      if (btn) btn.disabled = false;
    }
  };
  if (!modal.open) modal.showModal(); // re-opening while open (after a delete/edit) just swaps content
  onReady?.(form);
  $("input:not([type=hidden]), select", form)?.focus();
}
const footer = (label = "Save") => `<div class="actions"><button type="submit" value="cancel" formnovalidate>Cancel</button><button type="submit" class="primary">${label}</button></div>`;
const num = (v) => (v === "" || v == null ? null : Number(v));

function addAssetModal() {
  openModal(`
    <h3>Add asset</h3>
    <label>Asset type<select name="type" required>${typeOptions()}</select></label>
    <label>Name / description<input name="name" required maxlength="120" placeholder="e.g. Parag Parikh Flexi Cap, HDFC FD, Flat in Pune"></label>
    <fieldset><legend>Purchase</legend>
      <div class="row">
        <label>Purchase date<input type="date" name="date" value="${todayISO()}" max="${todayISO()}"></label>
        <label>Amount invested (₹)<input type="number" name="amount" min="0" step="any" required></label>
      </div>
      <label>Units held (optional)<input type="number" name="units" min="0" step="any" placeholder="e.g. 152.37 MF units, 50 shares, 20 grams"></label>
      <div class="hint">Number of units, not rupees. With units, the app shows buy price vs current price per unit.</div>
    </fieldset>
    <label>Current market value (₹)<input type="number" name="current_value" min="0" step="any" placeholder="Leave blank to use amount invested"></label>
    <div class="hint">You can add more purchases later with “Buy / Sell”, and update market value any time.</div>
    <label>Notes<input name="notes" maxlength="500" placeholder="Folio no., bank, location…"></label>
    ${footer("Add asset")}`,
  async (d) => {
    await api("/api/assets", {
      method: "POST",
      body: {
        name: d.name, type: d.type, notes: d.notes,
        purchase: { date: d.date, amount: Number(d.amount), units: num(d.units), kind: "BUY" },
        current_value: num(d.current_value),
      },
    });
    toast("Asset added");
    await refresh();
  },
  (form) => {
    // suggest a name from the type if left empty
    $("select[name=type]", form).addEventListener("change", (e) => {
      const n = $("input[name=name]", form);
      if (!n.value) n.placeholder = typeMeta(e.target.value).label;
    });
  });
}
$("#btn-add-asset").addEventListener("click", addAssetModal);

function valueModal(id) {
  const a = state.assets.find((x) => x.id === id);
  openModal(`
    <h3>Update market value</h3>
    <p class="muted">${esc(a.name)} · last value ${fmt(a.current_value)} on ${fmtDate(a.value_date)}</p>
    <div class="row">
      <label>As of date<input type="date" name="date" value="${todayISO()}" max="${todayISO()}" required></label>
      <label>Current market value (₹)<input type="number" name="value" min="0" step="any" required value="${a.current_value}"></label>
    </div>
    ${a.units ? `<label>…or price per unit (₹) × ${a.units} units<input type="number" name="ppu" min="0" step="any"></label>` : ""}
    ${footer("Save value")}`,
  async (d) => {
    await api(`/api/assets/${id}/valuations`, { method: "POST", body: { date: d.date, value: Number(d.value) } });
    toast("Value updated");
    await refresh();
  },
  (form) => {
    const ppu = $("input[name=ppu]", form);
    if (ppu) ppu.addEventListener("input", () => {
      if (ppu.value) $("input[name=value]", form).value = (Number(ppu.value) * a.units).toFixed(2);
    });
    $("input[name=value]", form).select();
  });
}

const FREQ = { monthly: 1, quarterly: 3, half_yearly: 6, yearly: 12 };
function scheduleDates(start, end, freq) {
  // mirror of the server's schedule(): every N months from start, up to end (or today), never in the future
  if (!start || !FREQ[freq]) return [];
  const today = todayISO(), stop = end && end < today ? end : today;
  const [y, m, d] = start.split("-").map(Number);
  const out = [];
  for (let i = 0; out.length < 600; i++) {
    const mm = m - 1 + i * FREQ[freq], yy = y + Math.floor(mm / 12), mo = (mm % 12) + 1;
    const dd = Math.min(d, new Date(yy, mo, 0).getDate());
    const iso = `${yy}-${String(mo).padStart(2, "0")}-${String(dd).padStart(2, "0")}`;
    if (iso > stop) break;
    out.push(iso);
  }
  return out;
}

function txModal(id, tx = null) {
  const a = state.assets.find((x) => x.id === id);
  const kind = tx?.kind || "BUY";
  openModal(`
    <h3>${tx ? "Edit transaction" : "Record payment / transaction"}</h3>
    <p class="muted">${esc(a.name)} · net invested ${fmt(a.invested)}</p>
    <div class="seg" role="radiogroup">
      <label><input type="radio" name="kind" value="BUY" ${kind === "BUY" ? "checked" : ""}>Buy / Pay once</label>
      <label><input type="radio" name="kind" value="SELL" ${kind === "SELL" ? "checked" : ""}>Sell / Redeem</label>
      ${tx ? "" : `<label><input type="radio" name="kind" value="RECURRING">Recurring (premium / EMI / SIP)</label>`}
    </div>

    <div id="once" class="form">
      <div class="row">
        <label>Date<input type="date" name="date" value="${tx?.date || todayISO()}" max="${todayISO()}" required></label>
        <label>Amount (₹)<input type="number" name="amount" min="0" step="any" required value="${tx?.amount ?? ""}"></label>
      </div>
      <div class="row">
        <label>Units (optional)<input type="number" name="units" min="0" step="any" value="${tx?.units ?? ""}" placeholder="units, shares or grams"></label>
        <label>Note<input name="note" maxlength="200" value="${esc(tx?.note)}" placeholder="SIP, bonus, partial redemption…"></label>
      </div>
      <div class="hint">Units = number of units/shares/grams, not rupees. ${tx ? "" : "If you've recorded a market value before, this amount is added to (or subtracted from) it."}</div>
    </div>

    <div id="recurring" class="form" hidden>
      <div class="row">
        <label>Amount per payment (₹)<input type="number" name="r_amount" min="1" step="any" placeholder="e.g. 150000"></label>
        <label>How often
          <select name="r_frequency">
            <option value="yearly">Yearly</option><option value="half_yearly">Half-yearly</option>
            <option value="quarterly">Quarterly</option><option value="monthly">Monthly</option>
          </select>
        </label>
      </div>
      <div class="row">
        <label>First payment date<input type="date" name="r_start" max="${todayISO()}"></label>
        <label>Last payment date (optional)<input type="date" name="r_end" max="${todayISO()}"></label>
      </div>
      <label>Note<input name="r_note" maxlength="200" placeholder="e.g. Annual premium, Gold EMI instalment"></label>
      <div class="hint">One entry is created for every payment from the first date up to the last date, or up to today if you leave it empty. Future dates are skipped.</div>
      <div class="preview" id="r-preview"></div>
    </div>
    ${footer("Save")}`,
  async (d) => {
    if (d.kind === "RECURRING") {
      const r = await api(`/api/assets/${id}/transactions/recurring`, {
        method: "POST",
        body: { frequency: d.r_frequency, amount: Number(d.r_amount), start_date: d.r_start, end_date: d.r_end || null, note: d.r_note },
      });
      toast(`Added ${r.created} payments (${fmt(r.total)}), ${fmtDate(r.first)} → ${fmtDate(r.last)}`);
      await refresh();
      return;
    }
    const body = { date: d.date, kind: d.kind, amount: Number(d.amount), units: num(d.units), note: d.note };
    if (tx) await api(`/api/transactions/${tx.id}`, { method: "PUT", body });
    else await api(`/api/assets/${id}/transactions`, { method: "POST", body });
    toast(tx ? "Transaction updated" : d.kind === "BUY" ? "Purchase recorded" : "Sale recorded");
    await refresh();
    if (tx) assetDetailModal(id);
  },
  (form) => {
    const once = $("#once", form), rec = $("#recurring", form), prev = $("#r-preview", form);
    const sync = () => {
      const isRec = form.elements.kind.value === "RECURRING";
      once.hidden = isRec; rec.hidden = !isRec;
      $$("input[name=date], input[name=amount]", once).forEach((i) => (i.required = !isRec));
      $$("input[name=r_amount], input[name=r_start]", rec).forEach((i) => (i.required = isRec));
      if (!isRec) return;
      const dates = scheduleDates(form.elements.r_start.value, form.elements.r_end.value, form.elements.r_frequency.value);
      const amt = Number(form.elements.r_amount.value) || 0;
      const shown = dates.length > 5
        ? dates.slice(0, 4).map(fmtDate).join(", ") + " … " + fmtDate(dates[dates.length - 1])
        : dates.map(fmtDate).join(", ");
      prev.innerHTML = dates.length
        ? `Will add <b>${dates.length}</b> payment${dates.length > 1 ? "s" : ""} of ${fmt(amt)} = <b>${fmt(dates.length * amt)}</b><br><span class="muted">${shown}</span>`
        : `<span class="muted">Pick the first payment date to see the schedule.</span>`;
    };
    form.addEventListener("input", sync);
    form.addEventListener("change", sync);
    sync();
  });
}

async function assetDetailModal(id) {
  const [a, growth] = await Promise.all([api(`/api/assets/${id}`), api(`/api/growth?asset_id=${id}`)]);
  const atDate = Object.fromEntries(growth.map((p) => [p.date, p]));
  modal.classList.add("wide");
  openModal(`
    <h3>${esc(a.name)}</h3>
    <p class="muted">${esc(a.type_label)} · current ${fmt(a.current_value)} · invested ${fmt(a.invested)}
      · <span class="${cls(a.gain)}">${signed(a.gain)}</span>${a.xirr != null ? ` · XIRR ${pct(a.xirr)}` : ""}</p>
    <label>Name<input name="name" required maxlength="120" value="${esc(a.name)}"></label>
    <label>Asset type<select name="type" required>${typeOptions(a.type)}</select></label>
    <label>Notes<input name="notes" maxlength="500" value="${esc(a.notes)}"></label>

    <div class="eyebrow">Purchases &amp; sales</div>
    <div class="history-list"><table class="data">${a.transactions.length ? a.transactions.map((t) => `
      <tr><td>${fmtDate(t.date)}</td><td>${t.kind === "BUY" ? "Buy" : "Sell"}</td><td class="num">${fmt(t.amount)}</td>
        <td class="muted">${t.units ? t.units + " u" : ""} ${esc(t.note)}</td>
        <td class="num"><button type="button" class="small" data-edit-tx="${t.id}" aria-label="Edit">✎ Edit</button>
          <button type="button" class="small danger" data-del-tx="${t.id}" aria-label="Delete">✕</button></td></tr>`).join("")
      : `<tr><td class="muted">No transactions</td></tr>`}</table></div>

    <div class="eyebrow">Invested vs current value</div>
    <div class="growth-mini" id="asset-growth"></div>

    <div class="eyebrow">Market value updates</div>
    <div class="history-list"><table class="data">${a.valuations.length ? `
      <thead><tr><th>Date</th><th class="num">Market value</th><th class="num">Invested till then</th><th class="num">Growth</th><th></th></tr></thead>` +
      a.valuations.map((v) => {
        const g = atDate[v.date];
        return `<tr><td>${fmtDate(v.date)}</td><td class="num">${fmt(v.value)}</td>
          <td class="num">${g ? fmt(g.invested) : "—"}</td>
          <td class="num ${cls(g?.gain)}">${g && g.gain_pct != null ? signed(g.gain_pct, (x) => x.toFixed(1) + "%") : "—"}</td>
          <td class="num"><button type="button" class="small danger" data-del-val="${v.id}" aria-label="Delete">✕</button></td></tr>`;
      }).join("")
      : `<tr><td class="muted">No value updates — current value = net invested</td></tr>`}</table></div>

    <div class="actions" style="justify-content:space-between">
      <button type="button" class="danger" id="del-asset">Delete asset</button>
      <span><button type="submit" value="cancel" formnovalidate>Close</button> <button type="submit" class="primary">Save changes</button></span>
    </div>`,
  async (d) => {
    await api(`/api/assets/${id}`, { method: "PUT", body: { name: d.name, type: d.type, notes: d.notes } });
    toast("Saved");
    await refresh();
  },
  (form) => {
    renderGrowth($("#asset-growth", form), growth, { height: 170 });
    form.addEventListener("click", async (ev) => {
      const t = ev.target;
      try {
        if (t.dataset.editTx) {
          txModal(id, a.transactions.find((x) => x.id === +t.dataset.editTx));
        } else if (t.dataset.delTx && confirm("Delete this transaction?")) {
          await api(`/api/transactions/${t.dataset.delTx}`, { method: "DELETE" });
          await refresh(); assetDetailModal(id);
        } else if (t.dataset.delVal && confirm("Delete this value entry?")) {
          await api(`/api/valuations/${t.dataset.delVal}`, { method: "DELETE" });
          await refresh(); assetDetailModal(id);
        } else if (t.id === "del-asset" && confirm(`Delete “${a.name}” and all its history? This cannot be undone.`)) {
          await api(`/api/assets/${id}`, { method: "DELETE" });
          modal.close(); toast("Asset deleted"); await refresh();
        }
      } catch (e) { toast("Error: " + e.message); }
    });
  });
}

// ===================================================================
// LIABILITIES
// ===================================================================
function renderLiabilities() {
  const L = sortRows(state.liabilities, sortState.liabs);
  $("#liab-empty").hidden = L.length > 0;
  const tot = L.reduce((s, l) => s + l.outstanding, 0);
  $("#liab-sub").textContent = L.length ? `Outstanding ${fmt(tot)} · EMIs ${fmt(state.summary.monthly_emi)}/month` : "";
  $("#liab-rows").innerHTML = L.map((l) => `
    <tr data-id="${l.id}">
      <td><div class="asset-name">${esc(l.name)}</div><div class="asset-type">${esc(l.type_label)}</div></td>
      <td>${fmtDate(l.start_date)}</td>
      <td class="num">${fmtTenure(l.tenure_months)}</td>
      <td>${fmtDate(l.end_date)}${l.months_left != null ? `<br><small class="muted">${l.months_left ? fmtTenure(l.months_left) + " left" : "tenure over"}</small>` : ""}</td>
      <td class="num">${fmt(l.principal)}</td>
      <td class="num"><b>${fmt(l.outstanding)}</b><br><small class="muted">${fmtDate(l.outstanding_date)}</small></td>
      <td class="num">${l.interest_rate != null ? l.interest_rate + "%" : "—"}</td>
      <td class="num">${l.emi ? fmt(l.emi) : "—"}</td>
      <td>${l.repaid_pct != null ? `<span class="progress"><span style="width:${Math.max(0, Math.min(100, l.repaid_pct))}%"></span></span>${l.repaid_pct}%` : "—"}</td>
      <td><div class="row-actions">
        <button class="small primary" data-act="out">Update balance</button>
        <button class="small" data-act="edit">Details</button>
      </div></td>
    </tr>`).join("");
}
$("#liab-rows").addEventListener("click", (ev) => {
  const b = ev.target.closest("button[data-act]");
  if (!b) return;
  const id = +b.closest("tr").dataset.id;
  b.dataset.act === "out" ? outstandingModal(id) : liabilityModal(id);
});

const liabTypeOptions = (sel) => `<option value="" disabled ${sel ? "" : "selected"}>Select type…</option>` +
  state.meta.liability_types.map((t) => `<option value="${t.key}" ${t.key === sel ? "selected" : ""}>${esc(t.label)}</option>`).join("");

async function liabilityModal(id) {
  const l = id ? await api(`/api/liabilities/${id}`) : null;
  openModal(`
    <h3>${l ? esc(l.name) : "Add liability"}</h3>
    <label>Type<select name="type" required>${liabTypeOptions(l?.type)}</select></label>
    <label>Name / lender<input name="name" required maxlength="120" value="${esc(l?.name)}" placeholder="e.g. SBI Home Loan, HDFC Credit Card"></label>
    <div class="row">
      <label>Original amount (₹)<input type="number" name="principal" min="0" step="any" required value="${l?.principal ?? ""}"></label>
      ${l ? "" : `<label>Outstanding today (₹)<input type="number" name="outstanding" min="0" step="any" placeholder="Same as original"></label>`}
    </div>
    <div class="row">
      <label>Interest rate (% p.a.)<input type="number" name="interest_rate" min="0" max="100" step="any" value="${l?.interest_rate ?? ""}"></label>
      <label>Monthly EMI (₹)<input type="number" name="emi" min="0" step="any" value="${l?.emi ?? ""}"></label>
    </div>
    <div class="row">
      <label>Loan start date<input type="date" name="start_date" value="${l?.start_date ?? todayISO()}"></label>
      <label>Tenure (months)<input type="number" name="tenure_months" min="0" max="600" step="1" value="${l?.tenure_months ?? ""}" placeholder="e.g. 240 for 20 years"></label>
    </div>
    <label>Notes<input name="notes" maxlength="500" value="${esc(l?.notes)}"></label>
    ${l ? `<div class="eyebrow">Balance history</div>
      <div class="history-list"><table class="data">${l.updates.length ? l.updates.map((u) => `
        <tr><td>${fmtDate(u.date)}</td><td class="num">${fmt(u.outstanding)}</td>
        <td class="num"><button type="button" class="small danger" data-del-upd="${u.id}" aria-label="Delete">✕</button></td></tr>`).join("")
        : `<tr><td class="muted">No balance updates yet</td></tr>`}</table></div>
      <div class="actions" style="justify-content:space-between">
        <button type="button" class="danger" id="del-liab">Delete liability</button>
        <span><button type="submit" value="cancel" formnovalidate>Close</button> <button type="submit" class="primary">Save changes</button></span>
      </div>` : footer("Add liability")}`,
  async (d) => {
    const body = {
      name: d.name, type: d.type, principal: Number(d.principal), interest_rate: num(d.interest_rate),
      emi: num(d.emi), tenure_months: num(d.tenure_months), start_date: d.start_date || null, notes: d.notes,
    };
    if (l) await api(`/api/liabilities/${id}`, { method: "PUT", body });
    else await api("/api/liabilities", { method: "POST", body: { ...body, outstanding: num(d.outstanding) } });
    toast(l ? "Saved" : "Liability added");
    await refresh();
  },
  (form) => {
    if (!l) return;
    form.addEventListener("click", async (ev) => {
      const t = ev.target;
      try {
        if (t.dataset.delUpd && confirm("Delete this balance entry?")) {
          await api(`/api/liability-updates/${t.dataset.delUpd}`, { method: "DELETE" });
          await refresh(); liabilityModal(id);
        } else if (t.id === "del-liab" && confirm(`Delete “${l.name}”?`)) {
          await api(`/api/liabilities/${id}`, { method: "DELETE" });
          modal.close(); toast("Liability deleted"); await refresh();
        }
      } catch (e) { toast("Error: " + e.message); }
    });
  });
}
$("#btn-add-liab").addEventListener("click", () => liabilityModal(null));

function outstandingModal(id) {
  const l = state.liabilities.find((x) => x.id === id);
  openModal(`
    <h3>Update outstanding balance</h3>
    <p class="muted">${esc(l.name)} · currently ${fmt(l.outstanding)}</p>
    <div class="row">
      <label>As of date<input type="date" name="date" value="${todayISO()}" max="${todayISO()}" required></label>
      <label>Outstanding (₹)<input type="number" name="outstanding" min="0" step="any" required value="${l.outstanding}"></label>
    </div>
    <div class="hint">Enter 0 when the loan is fully repaid.</div>
    ${footer("Save balance")}`,
  async (d) => {
    await api(`/api/liabilities/${id}/updates`, { method: "POST", body: { date: d.date, outstanding: Number(d.outstanding) } });
    toast("Balance updated");
    await refresh();
  }, (form) => $("input[name=outstanding]", form).select());
}

// ===================================================================
// INSIGHTS
// ===================================================================
function renderInsights() {
  const r = state.recs;
  const age = r.profile.age ? `age ${Math.round(r.profile.age)}` : `assumed age ${r.profile.assumed_age} (set yours in Settings)`;
  $("#target-sub").textContent =
    `Target for a ${r.profile.risk_profile} investor, ${age}. Based on financial assets of ${fmt(r.financial_total)} ` +
    `(real estate and other assets excluded${r.real_estate_pct != null ? `; real estate is ${r.real_estate_pct.toFixed(1)}% of total assets` : ""}).`;

  const rows = r.targets;
  const max = Math.min(100, Math.ceil((Math.max(...rows.map((x) => Math.max(x.current_pct, x.target_pct + x.tolerance))) + 5) / 10) * 10);
  const X = (v) => `${(v / max) * 100}%`;
  $("#target-chart").innerHTML = `
    <div class="tc">
      ${rows.map((x) => {
        const lo = Math.max(0, x.target_pct - x.tolerance), hi = x.target_pct + x.tolerance;
        const off = Math.abs(x.current_pct - x.target_pct) > x.tolerance;
        return `<div class="tc-row" data-tip="${esc(x.label)}<br>Current <b>${x.current_pct.toFixed(1)}%</b> (${fmtShort(x.current_value)})<br>Target <b>${x.target_pct}%</b> ±${x.tolerance} (${fmtShort(x.target_value)})">
          <div class="tc-label"><span class="dot" style="background:${catColor(x.key)}"></span>${esc(x.label)}</div>
          <div class="tc-track">
            <div class="tc-band" style="left:${X(lo)};width:calc(${X(hi)} - ${X(lo)})"></div>
            <div class="tc-bar" style="width:${X(Math.min(x.current_pct, max))};background:${catColor(x.key)}"></div>
            <div class="tc-target" style="left:${X(x.target_pct)}"></div>
          </div>
          <div class="tc-val"><b>${x.current_pct.toFixed(1)}%</b> <span class="muted">/ ${x.target_pct}%</span> ${off ? "⚠" : "✓"}</div>
        </div>`;
      }).join("")}
      <div class="tc-legend muted"><span class="tc-key bar"></span>Current <span class="tc-key tick"></span>Target <span class="tc-key band"></span>Comfort band</div>
    </div>`;
  $$(".tc-row").forEach((row) => {
    row.addEventListener("mousemove", (ev) => showTip(row.dataset.tip, ev));
    row.addEventListener("mouseleave", hideTip);
  });

  $("#target-table").innerHTML = `
    <thead><tr><th>Segment</th><th class="num">Current</th><th class="num">Current %</th><th class="num">Target %</th><th class="num">Target value</th><th class="num">Action</th></tr></thead>
    <tbody>${rows.map((x) => {
      const off = Math.abs(x.current_pct - x.target_pct) > x.tolerance;
      const act = !off ? `<span class="muted">On track</span>` : x.diff_value > 0 ? `Add ${fmtShort(x.diff_value)}` : `Reduce ${fmtShort(-x.diff_value)}`;
      return `<tr><td>${esc(x.label)}</td><td class="num">${fmt(x.current_value)}</td><td class="num">${pct(x.current_pct)}</td>
        <td class="num">${x.target_pct}%</td><td class="num">${fmt(x.target_value)}</td><td class="num">${act}</td></tr>`;
    }).join("")}</tbody>`;

  renderRecs($("#all-recs"), r.items);
  $("#notes").innerHTML = r.notes.map((n) => `<dt>${esc(n.title)}</dt><dd>${esc(n.detail)}</dd>`).join("");
  $("#disclaimer").textContent = r.disclaimer;
}

// ===================================================================
// SETTINGS
// ===================================================================
async function loadSettings() {
  state.settings = await api("/api/settings");
  const f = $("#settings-form");
  Object.entries(state.settings).forEach(([k, v]) => { if (f.elements[k]) f.elements[k].value = v ?? ""; });
}
$("#settings-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const d = Object.fromEntries(new FormData(ev.target));
  try {
    await api("/api/settings", {
      method: "PUT",
      body: {
        name: d.name, risk_profile: d.risk_profile, tax_regime: d.tax_regime,
        age: num(d.age), monthly_expenses: num(d.monthly_expenses), annual_income: num(d.annual_income), dependents: num(d.dependents),
      },
    });
    toast("Profile saved — recommendations updated");
    await refresh();
  } catch (e) { toast("Error: " + e.message); }
});
$("#import-file").addEventListener("change", async (ev) => {
  const file = ev.target.files[0];
  if (!file) return;
  if (!confirm("Importing replaces ALL current data with the backup. Continue?")) { ev.target.value = ""; return; }
  try {
    await api("/api/import", { method: "POST", body: JSON.parse(await file.text()) });
    toast("Backup restored");
    await loadSettings();
    loadAccount();
    wireSort("#tab-assets table.data", "assets", renderAssets);
    wireSort("#tab-liabilities table.data", "liabs", renderLiabilities);
    await refresh();
  } catch (e) { toast("Import failed: " + e.message); }
  ev.target.value = "";
});

// ===================================================================
// ACCOUNT
// ===================================================================
async function loadAccount() {
  try {
    const st = await api("/api/auth/status");
    $("#who").textContent = st.username || "";
    $("#account-sub").textContent = `Signed in as ${st.username}. Your portfolio is private to this account. You're signed out automatically after ${st.idle_minutes} minutes without activity, and when you close the browser.`;
  } catch (_) { /* ignore */ }
}
$("#btn-logout").addEventListener("click", async () => {
  try { await api("/api/auth/logout", { method: "POST" }); } catch (_) { /* ignore */ }
  location.replace("/login");
});
$("#password-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const f = ev.target;
  if (f.elements.new.value !== f.elements.confirm.value) return toast("The new passwords don't match");
  try {
    await api("/api/auth/password", { method: "POST", body: { current: f.elements.current.value, new: f.elements.new.value } });
    f.reset();
    toast("Password changed. Other sessions were signed out.");
  } catch (e) { toast("Error: " + e.message); }
});

// ===================================================================
// EXCEL SYNC
// ===================================================================
async function refreshExcelStatus() {
  try {
    const st = await api("/api/excel/status");
    if (st.host_path) $("#excel-path").textContent = st.host_path;
    const when = (iso) => (iso ? new Date(iso).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "never");
    $("#excel-status").innerHTML = !st.exists
      ? `No Excel file yet. Click <b>Create / refresh Excel file</b> to make one.`
      : (st.pending ? `<b class="down">Excel file was edited (${when(st.modified)}) and not loaded yet.</b> ` : `In sync. `) +
        `Last written by app: ${when(st.last_export)} · last loaded: ${when(st.last_import)}`;
    $("#excel-load").disabled = !st.exists;
    $("#excel-banner").hidden = !st.pending;
  } catch (_) { /* status is optional */ }
}

async function excelPreview(base64 = null) {
  let p;
  try {
    p = await api("/api/excel/preview", { method: "POST", body: base64 ? { data_base64: base64 } : {} });
  } catch (e) { return toast("Error: " + e.message); }
  const label = { add: "Add", update: "Change", value: "New value", balance: "New balance", delete: "Delete" };
  const rows = p.changes.map((c) => `<tr><td>${esc(c.sheet)}</td><td><b>${label[c.action] || c.action}</b></td><td>${esc(c.what)}</td><td class="muted">${esc(c.detail)}</td></tr>`).join("");
  modal.classList.add("wide");
  openModal(`
    <h3>Changes from Excel</h3>
    ${p.changes.length ? `<p class="muted">${p.changes.length} change${p.changes.length > 1 ? "s" : ""} will be applied. A backup is taken first.</p>
      <div class="history-list" style="max-height:340px"><table class="data"><thead><tr><th>Sheet</th><th>Action</th><th>Item</th><th>Details</th></tr></thead><tbody>${rows}</tbody></table></div>`
      : `<p>No changes found: the Excel file matches the app.</p>`}
    ${p.warnings.length ? `<div class="preview"><b>Skipped rows (fix in Excel and load again):</b><br>${p.warnings.map(esc).join("<br>")}</div>` : ""}
    <div class="actions"><button type="submit" value="cancel" formnovalidate>Close</button>
      ${p.changes.length ? `<button type="submit" class="primary">Apply ${p.changes.length} change${p.changes.length > 1 ? "s" : ""}</button>` : ""}</div>`,
  async () => {
    const r = await api("/api/excel/apply", { method: "POST", body: base64 ? { data_base64: base64 } : {} });
    toast(`Applied ${r.applied} change${r.applied === 1 ? "" : "s"} from Excel`);
    await refresh();
    refreshExcelStatus();
  });
}

$("#excel-load").addEventListener("click", () => excelPreview());
$("#excel-banner-load").addEventListener("click", () => excelPreview());
$("#btn-excel").addEventListener("click", () => { showTab("settings"); $("#excel-card").scrollIntoView({ behavior: "smooth" }); });
$("#excel-create").addEventListener("click", async () => {
  try {
    await api("/api/excel/export", { method: "POST" });
    toast("Excel file written: " + $("#excel-path").textContent);
  } catch (e) {
    if (!/haven't been loaded/.test(e.message)) return toast("Error: " + e.message);
    if (!confirm("The Excel file has edits that haven't been loaded into the app.\n\nOK = overwrite the file and DISCARD those edits.\nCancel = keep them (then use 'Load changes from Excel').")) return;
    await api("/api/excel/export?force=true", { method: "POST" });
    toast("Excel file overwritten");
  }
  refreshExcelStatus();
});
$("#excel-upload").addEventListener("change", async (ev) => {
  const f = ev.target.files[0];
  ev.target.value = "";
  if (!f) return;
  const b64 = await new Promise((res) => { const r = new FileReader(); r.onload = () => res(r.result); r.readAsDataURL(f); });
  excelPreview(b64);
});

// ===================================================================
(async function init() {
  try {
    state.meta = await api("/api/meta");
    $("#asset-filter").innerHTML += state.meta.categories.map((c) => `<option value="${c.key}">${esc(c.label)}</option>`).join("");
    await loadSettings();
    wireSort("#tab-assets table.data", "assets", renderAssets);
    wireSort("#tab-liabilities table.data", "liabs", renderLiabilities);
    await refresh();
    const h = location.hash.slice(1);
    showTab(["dashboard", "assets", "liabilities", "insights", "settings"].includes(h) ? h : "dashboard");
  } catch (e) {
    document.querySelector("main").innerHTML = `<div class="card">Could not reach the server: ${esc(e.message)}</div>`;
  }
})();
