"use strict";
const $ = (s) => document.querySelector(s);
const state = { market: "", view: "overview", account: "", symbol: "", range: 30, flag: "", settings: null, status: null };
const THEMES = [["firoozeh", "فیروزه"], ["shab", "شب"], ["zar", "زر"], ["kavir", "کویر"], ["abr", "ابر"], ["exs", "EXS"], ["matrix", "Matrix"], ["ai", "AI"]];
const SIDE = { buy: "خرید", sell: "فروش" };
const ZONES = ["Asia/Tehran", "UTC", "Europe/London", "America/New_York", "Asia/Dubai"];

const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const money = (v) => v == null ? "–" : `<span class="num ${v > 0 ? "up" : v < 0 ? "down" : ""}">${v > 0 ? "+" : ""}${Number(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>`;
const plain = (v, d = 2) => v == null ? "–" : `<span class="num">${Number(v).toLocaleString("en-US", { maximumFractionDigits: d })}</span>`;
const unit = (v, u, d = 2) => v == null ? "–" : `<span class="num">${Number(v).toLocaleString("en-US", { maximumFractionDigits: d })}${u}</span>`;
const price = (v) => v == null ? "–" : `<span class="num">${Number(v.toFixed(5))}</span>`;
const when = (t, opts) => {
  const zone = state.settings?.timezone || "Asia/Tehran";
  return new Intl.DateTimeFormat("fa-IR-u-ca-persian-nu-latn", { timeZone: zone, ...opts }).format(new Date(t * 1000));
};
const stamp = (t) => t ? when(t, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false }) : "باز";

async function api(path, opts) {
  const res = await fetch(path, opts);
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json();
}
const put = (path, body) => api(path, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

function toast(text) {
  const el = $("#toast");
  el.textContent = text;
  el.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (el.hidden = true), 2200);
}

function query() {
  const p = new URLSearchParams();
  if (state.account) p.set("account", state.account);
  if (state.symbol) p.set("symbol", state.symbol);
  if (state.range) p.set("start", Math.floor(Date.now() / 1000) - state.range * 86400);
  return p;
}

function applyTheme(theme) {
  const root = document.documentElement;
  root.dataset.theme = theme.preset;
  root.dataset.density = theme.density;
  root.style.setProperty("--scale", theme.font_scale);
  if (theme.accent) root.style.setProperty("--accent", theme.accent);
  else root.style.removeProperty("--accent");
  try { localStorage.setItem("theme", JSON.stringify(theme)); } catch {}
}
try { const t = JSON.parse(localStorage.getItem("theme")); if (t) applyTheme(t); } catch {}

function renderLink() {
  const list = state.status?.accounts || [];
  const online = list.filter((a) => a.online).length;
  $("#demo").hidden = !state.status?.demo;
  $("#link").innerHTML = list.length
    ? `<span class="dot ${online ? "on" : ""}"></span>${online ? "اکسپرت وصل است" : "اکسپرت وصل نیست"}`
    : `<span class="dot"></span>هنوز حسابی وصل نشده`;
}

function renderFilters(symbols) {
  const accounts = state.status?.accounts || [];
  const options = accounts.map((a) => `<option value="${esc(a.id)}" ${a.id === state.account ? "selected" : ""}>${esc(a.login)} (${esc(a.platform)})</option>`).join("");
  const ranges = [[7, "۷ روز"], [30, "۳۰ روز"], [90, "۹۰ روز"], [0, "همه"]];
  $("#filters").innerHTML = `
    ${accounts.length > 1 ? `<select id="f-account" aria-label="حساب"><option value="">همه حساب‌ها</option>${options}</select>` : ""}
    <select id="f-symbol" aria-label="نماد"><option value="">همه نمادها</option>${(symbols || []).map((s) => `<option dir="ltr" ${s === state.symbol ? "selected" : ""}>${esc(s)}</option>`).join("")}</select>
    <div class="chips" role="group" aria-label="بازه زمانی">${ranges.map(([d, t]) => `<button data-range="${d}" aria-pressed="${state.range === d}">${t}</button>`).join("")}</div>
    <a class="btn quiet" href="/api/export.csv?${query()}" style="text-decoration:none">خروجی CSV</a>`;
  $("#f-account")?.addEventListener("change", (e) => { state.account = e.target.value; state.symbol = ""; render(); });
  $("#f-symbol").addEventListener("change", (e) => { state.symbol = e.target.value; render(); });
  document.querySelectorAll("[data-range]").forEach((b) => b.addEventListener("click", () => { state.range = +b.dataset.range; render(); }));
}

function heroEffect() {
  const host = document.querySelector(".hero-head");
  const theme = document.documentElement.dataset.theme;
  if (!host || !["matrix", "ai"].includes(theme)) return;
  const canvas = document.createElement("canvas");
  host.prepend(canvas);
  const box = canvas.getBoundingClientRect(), ctx = canvas.getContext("2d");
  const scale = Math.min(devicePixelRatio || 1, 2), W = box.width, H = box.height;
  canvas.width = W * scale; canvas.height = H * scale; ctx.scale(scale, scale);
  const calm = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const live = () => canvas.isConnected && document.documentElement.dataset.theme === theme;
  if (theme === "matrix") {
    const size = 15, drops = Array.from({ length: Math.ceil(W / size) }, () => Math.random() * H / size);
    const glyphs = "01$€£¥XAUUSDアカサタナ";
    ctx.font = `${size}px Menlo,Consolas,monospace`;
    const frame = () => {
      ctx.globalCompositeOperation = "destination-out";
      ctx.fillStyle = "rgba(0,0,0,.12)"; ctx.fillRect(0, 0, W, H);
      ctx.globalCompositeOperation = "source-over";
      ctx.fillStyle = "#39ff88";
      drops.forEach((y, i) => {
        ctx.fillText(glyphs[Math.floor(Math.random() * glyphs.length)], i * size, y * size);
        drops[i] = y * size > H && Math.random() > .97 ? 0 : y + 1;
      });
    };
    if (calm) { for (let i = 0; i < 40; i++) frame(); return; }
    const timer = setInterval(() => (live() ? frame() : clearInterval(timer)), 70);
    return;
  }
  const dots = Array.from({ length: Math.round(W / 24) }, () => ({ x: Math.random() * W, y: Math.random() * H, a: (Math.random() - .5) * .35, b: (Math.random() - .5) * .35 }));
  const frame = () => {
    ctx.clearRect(0, 0, W, H);
    dots.forEach((d, i) => {
      d.x = (d.x + d.a + W) % W; d.y = (d.y + d.b + H) % H;
      for (let k = i + 1; k < dots.length; k++) {
        const o = dots[k], dist = Math.hypot(d.x - o.x, d.y - o.y);
        if (dist < 120) { ctx.strokeStyle = `rgba(167,139,250,${.4 * (1 - dist / 120)})`; ctx.beginPath(); ctx.moveTo(d.x, d.y); ctx.lineTo(o.x, o.y); ctx.stroke(); }
      }
      ctx.fillStyle = "#c4b5fd"; ctx.beginPath(); ctx.arc(d.x, d.y, 1.6, 0, 7); ctx.fill();
    });
    if (!calm && live()) requestAnimationFrame(frame);
  };
  frame();
}

function emptyConnect() {
  return `<div class="empty"><h2>هنوز معامله‌ای ثبت نشده</h2><p>اکسپرت را روی متاتریدر نصب کن تا معامله‌هایت اینجا بیایند.</p><p style="margin-top:12px"><button class="btn" onclick="go('connect')">راه‌اندازی اتصال</button></p></div>`;
}

function equityChart(points) {
  if (!points.length) return "";
  chartPoints = points;
  const W = Math.max($("#view").clientWidth, 280), H = W < 600 ? 220 : 300, L = 52, R = 8, T = 12, B = 4;
  const data = [{ t: points[0].t, v: 0 }, ...points];
  const vs = data.map((p) => p.v);
  let lo = Math.min(0, ...vs), hi = Math.max(0, ...vs);
  const pad = (hi - lo || 1) * 0.08; lo -= pad; hi += pad;
  const n = data.length - 1 || 1;
  const x = (i) => L + (W - L - R) * (i / n);
  const y = (v) => T + (H - T - B) * (1 - (v - lo) / (hi - lo));
  const path = data.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(p.v).toFixed(1)}`).join("");
  const step = niceStep((hi - lo) / 4);
  let grid = "";
  for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) {
    grid += `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" stroke="var(${Math.abs(v) < step / 2 ? "--line" : "--grid"})" vector-effect="non-scaling-stroke"/><text x="${L - 8}" y="${y(v) + 4}" text-anchor="end" fill="var(--muted)" font-size="12">${(Math.round(v) || 0).toLocaleString("en-US")}</text>`;
  }
  const dates = [0, Math.floor(n / 2), n].map((i) => `<span>${when(data[i].t, { month: "short", day: "numeric" })}</span>`).join("");
  chartData = { data, x, y, W, H };
  return `<div class="chart" id="eq"><svg dir="ltr" viewBox="0 0 ${W} ${H}" style="height:${H}px" role="img" aria-label="منحنی سود و زیان تجمعی">${grid}
    <path d="${path}" fill="none" stroke="var(--accent)" stroke-width="2" vector-effect="non-scaling-stroke" stroke-linejoin="round"/>
    <line id="eq-x" y1="${T}" y2="${H - B}" stroke="var(--muted)" stroke-dasharray="3 3" vector-effect="non-scaling-stroke" visibility="hidden"/></svg><div class="tip" id="eq-tip" hidden></div><div class="xaxis" dir="ltr" style="padding-left:${L}px">${dates}</div></div>`;
}
let chartData = null, chartPoints = null;
const niceStep = (r) => { const m = 10 ** Math.floor(Math.log10(r || 1)); const f = r / m; return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * m; };

function bindChart() {
  const box = $("#eq");
  if (!box || !chartData) return;
  const { data, x, y, W, H } = chartData;
  const tip = $("#eq-tip"), line = $("#eq-x");
  box.addEventListener("pointermove", (e) => {
    const r = box.getBoundingClientRect();
    const sx = ((e.clientX - r.left) / r.width) * W;
    let i = 0, best = Infinity;
    data.forEach((_, k) => { const d = Math.abs(x(k) - sx); if (d < best) { best = d; i = k; } });
    const p = data[i];
    line.setAttribute("x1", x(i)); line.setAttribute("x2", x(i)); line.setAttribute("visibility", "visible");
    tip.hidden = false;
    tip.style.left = `${Math.min(Math.max((x(i) / W) * r.width, 90), r.width - 90)}px`;
    tip.style.top = `${(y(p.v) / H) * r.height}px`;
    tip.innerHTML = `${when(p.t, { month: "short", day: "numeric" })}${p.symbol ? ` ${esc(p.symbol)}` : ""}: ${money(p.v)}`;
  });
  box.addEventListener("pointerleave", () => { tip.hidden = true; line.setAttribute("visibility", "hidden"); });
}

addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  const old = $("#eq");
  if (!old || !chartPoints) return;
  resizeTimer = setTimeout(() => { old.outerHTML = equityChart(chartPoints); bindChart(); }, 150);
});
let resizeTimer;

function calendar(daily) {
  const map = Object.fromEntries(daily.map((d) => [d.date, d]));
  const maxAbs = Math.max(1, ...daily.map((d) => Math.abs(d.net)));
  const today = new Date();
  const start = new Date(today); start.setDate(today.getDate() - 34 - ((today.getDay() + 1) % 7));
  const head = ["ش", "ی", "د", "س", "چ", "پ", "ج"].map((d) => `<i>${d}</i>`).join("");
  let cells = "";
  for (let i = 0; i < 42; i++) {
    const d = new Date(start); d.setDate(start.getDate() + i);
    if (d > today) { cells += `<div class="day off"></div>`; continue; }
    const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    const row = map[key];
    const label = when(d.getTime() / 1000, { day: "numeric" });
    if (!row) { cells += `<div class="day muted">${label}</div>`; continue; }
    const pct = Math.round(18 + 62 * Math.sqrt(Math.abs(row.net) / maxAbs));
    cells += `<div class="day" style="background:color-mix(in srgb,var(${row.net >= 0 ? "--up" : "--down"}) ${pct}%,var(--surface));${pct > 55 ? "color:var(--bg)" : ""}" title="${when(d.getTime() / 1000, { month: "long", day: "numeric" })}: ${row.count} معامله، ${row.net}">${label}<b>${row.net > 0 ? "+" : ""}${Math.round(row.net)}</b></div>`;
  }
  return `<div class="cal">${head}${cells}</div><div class="legend"><span style="--c:var(--up)">روز سودده</span><span style="--c:var(--down)">روز ضررده</span></div>`;
}

const insightList = (items) => items.map((i) => `<div class="note ${esc(i.level)}"><h3><span class="mark"></span>${esc(i.title)}</h3><p>${esc(i.evidence)}</p><p class="do">${esc(i.advice)}</p></div>`).join("");

function tradeRows(rows, labels) {
  return rows.map((t) => `<tr class="row" tabindex="0" data-a="${esc(t.account_id)}" data-p="${esc(t.position_id)}">
    <td>${stamp(t.open_time)}</td><td><bdi>${esc(t.symbol)}</bdi></td><td>${SIDE[t.side]}</td><td>${plain(t.volume)}</td>
    <td>${price(t.entry_price)}</td><td>${price(t.exit_price)}</td><td>${t.closed ? money(t.net) : '<span class="muted">باز</span>'}</td>
    <td>${t.r_multiple == null ? "–" : `<span class="num">${t.r_multiple > 0 ? "+" : ""}${t.r_multiple}R</span>`}</td>
    <td>${t.flags.map((f) => `<span class="tag">${esc(labels[f])}</span>`).join("")}</td></tr>`).join("");
}
const tradeHead = `<tr><th>ورود</th><th>نماد</th><th>جهت</th><th>لات</th><th>قیمت ورود</th><th>قیمت خروج</th><th>خالص</th><th>R</th><th>نکته‌ها</th></tr>`;

function bindRows() {
  document.querySelectorAll("tr.row").forEach((tr) => {
    const open = () => openTrade(tr.dataset.a, tr.dataset.p);
    tr.addEventListener("click", open);
    tr.addEventListener("keydown", (e) => { if (e.key === "Enter") open(); });
  });
}

async function viewOverview() {
  const o = await api(`/api/overview?${query()}`);
  renderFilters(o.symbols);
  const s = o.summary;
  if (!s.count && !o.positions.length) { $("#view").innerHTML = state.status.accounts.length ? `<div class="empty"><h2>در این بازه معامله‌ای نیست</h2><p>بازه زمانی را بزرگ‌تر کن.</p></div>` : emptyConnect(); return; }
  const cur = o.currency ? ` ${esc(o.currency)}` : "";
  const open = o.positions.length ? `<section class="block" style="margin-bottom:24px"><h2>پوزیشن‌های باز</h2><div class="scroll"><table><thead><tr><th>نماد</th><th>جهت</th><th>لات</th><th>ورود</th><th>حد ضرر</th><th>حد سود</th><th>سود شناور</th></tr></thead><tbody>${o.positions.map((p) => `<tr><td><bdi>${esc(p.symbol)}</bdi></td><td>${SIDE[p.side]}</td><td>${plain(p.volume)}</td><td>${price(p.open_price)}</td><td>${p.sl ? price(p.sl) : '<span class="down">ندارد</span>'}</td><td>${p.tp ? price(p.tp) : "–"}</td><td>${money(p.profit)}</td></tr>`).join("")}</tbody></table></div></section>` : "";
  const profile = o.profile ? `<div class="profile"><span class="muted">سبک فعلی تو</span><br><b>${esc(o.profile.style)}</b><p class="muted">${esc(o.profile.text)}. میانگین نگهداری ${esc(o.profile.avg_duration)}.</p></div>` : "";
  $("#view").innerHTML = `
    <section class="hero">
      <div class="hero-head">
        <div><div class="hero-sub">سود و زیان خالص${cur}</div><div class="hero-net">${money(s.net)}</div></div>
        <div class="facts">
          <div class="fact"><b>${plain(s.count)}</b><span>معامله بسته</span></div>
          <div class="fact"><b>${unit(s.win_rate, "%", 1)}</b><span>نرخ برد</span></div>
          <div class="fact"><b>${plain(s.profit_factor)}</b><span>ضریب سود</span></div>
          <div class="fact"><b>${unit(s.avg_r, "R")}</b><span>میانگین R</span></div>
          <div class="fact"><b>${plain(s.max_drawdown)}</b><span>بیشترین افت</span></div>
        </div>
      </div>
      ${equityChart(o.equity)}
    </section>
    ${open}
    <div class="cols">
      <section class="block"><h2>چه کار می‌کنی و چه کار کنی</h2>${profile}${insightList(o.insights)}</section>
      <section class="block"><h2>تقویم نتیجه</h2>${calendar(o.daily)}</section>
    </div>`;
  bindChart();
  heroEffect();
}

async function viewTrades() {
  const [t, o] = await Promise.all([api(`/api/trades?${query()}${state.flag ? `&flag=${state.flag}` : ""}`), api(`/api/overview?${query()}`)]);
  renderFilters(o.symbols);
  const flags = Object.entries(t.labels).map(([k, v]) => `<option value="${k}" ${k === state.flag ? "selected" : ""}>${esc(v)}</option>`).join("");
  $("#filters").insertAdjacentHTML("beforeend", `<select id="f-flag" aria-label="نکته رفتاری"><option value="">همه معامله‌ها</option>${flags}</select>`);
  $("#f-flag").addEventListener("change", (e) => { state.flag = e.target.value; render(); });
  $("#view").innerHTML = t.trades.length
    ? `<div class="scroll"><table><thead>${tradeHead}</thead><tbody>${tradeRows(t.trades, t.labels)}</tbody></table></div>${t.total > t.trades.length ? `<p class="muted">${t.trades.length} از ${t.total} معامله نمایش داده شده.</p>` : ""}`
    : (state.status.accounts.length ? `<div class="empty"><h2>معامله‌ای با این فیلترها نیست</h2><p>فیلترها را تغییر بده.</p></div>` : emptyConnect());
  bindRows();
}

function breakdown(title, rows) {
  if (!rows.length) return "";
  const max = Math.max(1, ...rows.map((r) => Math.abs(r.net)));
  return `<section class="block"><h2>${title}</h2><div class="scroll"><table><thead><tr><th></th><th>تعداد</th><th>برد</th><th>میانگین</th><th>جمع</th><th></th></tr></thead><tbody>${rows.map((r) => `<tr>
    <td><bdi>${esc(r.name)}</bdi></td><td>${plain(r.count)}</td><td>${unit(r.win_rate, "%", 0)}</td><td>${money(r.expectancy)}</td><td>${money(r.net)}</td>
    <td style="width:26%"><span class="bar" style="width:${(Math.abs(r.net) / max) * 100}%;background:var(${r.net >= 0 ? "--up" : "--down"})"></span></td></tr>`).join("")}</tbody></table></div></section>`;
}

async function viewPatterns() {
  const o = await api(`/api/overview?${query()}`);
  renderFilters(o.symbols);
  if (!o.summary.count) { $("#view").innerHTML = `<div class="empty"><h2>هنوز الگویی نیست</h2><p>با بسته شدن معامله‌ها، این صفحه پر می‌شود.</p></div>`; return; }
  const s = o.summary;
  const flagRows = o.flags.length ? `<section class="block"><h2>هزینه رفتارها</h2><div class="scroll"><table><thead><tr><th>رفتار</th><th>تعداد</th><th>جمع نتیجه</th></tr></thead><tbody>${o.flags.map((f) => `<tr><td>${esc(f.label)}</td><td>${plain(f.count)}</td><td>${money(f.net)}</td></tr>`).join("")}</tbody></table></div></section>` : "";
  $("#view").innerHTML = `<div class="facts" style="margin-bottom:24px">
      <div class="fact"><b>${money(s.avg_win)}</b><span>میانگین سود</span></div>
      <div class="fact"><b>${money(s.avg_loss)}</b><span>میانگین ضرر</span></div>
      <div class="fact"><b>${money(s.expectancy)}</b><span>امید هر معامله</span></div>
      <div class="fact"><b>${money(s.best)}</b><span>بهترین</span></div>
      <div class="fact"><b>${money(s.worst)}</b><span>بدترین</span></div>
      <div class="fact"><b>${plain(s.win_streak)}</b><span>برد پیاپی</span></div>
      <div class="fact"><b>${plain(s.loss_streak)}</b><span>باخت پیاپی</span></div>
      <div class="fact"><b>${money(s.costs)}</b><span>کارمزد و سواپ</span></div>
    </div>
    <div class="cols">${flagRows}${breakdown("نمادها", o.tables.symbols)}${breakdown("سشن‌ها", o.tables.sessions)}${breakdown("روزهای هفته", o.tables.weekdays)}${breakdown("جهت", o.tables.sides)}</div>`;
}

function field(key, label, help, value, attrs = "") {
  return `<label>${label}<input type="number" name="${key}" value="${value}" min="0" ${attrs}><small>${help}</small></label>`;
}

function viewRules() {
  const r = state.settings.rules;
  $("#filters").innerHTML = "";
  $("#view").innerHTML = `<h1 class="page-title">قوانین و هشدار</h1><p class="page-sub">اکسپرت هر چند ثانیه این قانون‌ها را بررسی می‌کند و هشدار را روی چارت نشان می‌دهد. جلوی معامله را نمی‌گیرد. عدد صفر هر قانون را خاموش می‌کند.</p>
  <form class="form" id="rules">
    ${field("daily_loss_limit", "سقف ضرر روزانه", "به ارز حساب", r.daily_loss_limit, 'step="0.01"')}
    ${field("max_trades_per_day", "سقف معامله در روز", "معامله‌های بعدی علامت می‌خورند", r.max_trades_per_day)}
    ${field("max_consecutive_losses", "سقف باخت پیاپی", "در همان روز", r.max_consecutive_losses)}
    ${field("cooldown_minutes", "استراحت بعد از ضرر", "دقیقه", r.cooldown_minutes)}
    ${field("news_alert_minutes", "هشدار قبل از خبر مهم", "چند دقیقه قبل از خبرهای پراثر بازارهای من", r.news_alert_minutes)}
    <label class="check"><input type="checkbox" name="require_sl" ${r.require_sl ? "checked" : ""}>هشدار برای پوزیشن بدون حد ضرر</label>
    <div style="grid-column:1/-1"><button class="btn">ذخیره قوانین</button></div>
  </form>`;
  $("#rules").addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    const rules = { daily_loss_limit: +f.get("daily_loss_limit"), max_trades_per_day: +f.get("max_trades_per_day"), max_consecutive_losses: +f.get("max_consecutive_losses"), cooldown_minutes: +f.get("cooldown_minutes"), news_alert_minutes: +f.get("news_alert_minutes"), require_sl: f.has("require_sl") };
    await put("/api/settings", { rules });
    state.settings.rules = rules;
    toast("قوانین ذخیره شد");
  });
}

function viewTheme() {
  const t = state.settings.theme;
  $("#filters").innerHTML = "";
  const swatch = ([id, name]) => {
    const probe = document.createElement("div"); probe.dataset.theme = id; document.body.append(probe);
    const c = getComputedStyle(probe); const v = (k) => c.getPropertyValue(k); const css = `--s-bg:${v("--bg")};--s-ink:${v("--ink")};--s-line:${v("--line")};--s-accent:${v("--accent")}`;
    probe.remove();
    return `<button class="swatch" data-id="${id}" aria-pressed="${t.preset === id}" style="${css}"><span>${name}</span><em></em></button>`;
  };
  $("#view").innerHTML = `<h1 class="page-title">ظاهر</h1><p class="page-sub">هر تغییر همان لحظه اعمال و ذخیره می‌شود.</p>
    <div class="swatches">${THEMES.map(swatch).join("")}</div>
    <div class="form">
      <label>رنگ تأکید<input type="color" id="accent" value="${t.accent || getComputedStyle(document.documentElement).getPropertyValue("--accent").trim()}" style="width:100%;height:36px;padding:2px"><small><button type="button" class="btn quiet" id="reset-accent" style="margin-top:4px;padding:2px 10px">برگشت به رنگ تم</button></small></label>
      <label>اندازه متن<input type="range" id="scale" min="85" max="125" step="5" value="${t.font_scale}" style="width:100%"><small><span class="num"><span id="scale-v">${t.font_scale}</span>%</span></small></label>
      <label>تراکم<select id="density"><option value="compact">فشرده</option><option value="normal">معمولی</option><option value="comfortable">جادار</option></select></label>
      <label>منطقه زمانی<select id="zone">${ZONES.map((z) => `<option ${z === state.settings.timezone ? "selected" : ""}>${z}</option>`).join("")}</select></label>
    </div>`;
  $("#density").value = t.density;
  const save = async () => { applyTheme(t); await put("/api/settings", { theme: t }); };
  document.querySelectorAll(".swatch").forEach((b) => b.addEventListener("click", async () => { t.preset = b.dataset.id; t.accent = ""; await save(); viewTheme(); }));
  $("#accent").addEventListener("input", (e) => { t.accent = e.target.value; save(); });
  $("#reset-accent").addEventListener("click", () => { t.accent = ""; save(); });
  $("#scale").addEventListener("input", (e) => { t.font_scale = +e.target.value; $("#scale-v").textContent = t.font_scale; save(); });
  $("#density").addEventListener("change", (e) => { t.density = e.target.value; save(); });
  $("#zone").addEventListener("change", async (e) => { state.settings.timezone = e.target.value; await put("/api/settings", { timezone: e.target.value }); toast("منطقه زمانی ذخیره شد"); });
}

function viewConnect() {
  const s = state.settings, url = `http://127.0.0.1:${s.port}`;
  const accounts = state.status.accounts;
  const mac = s.platform === "darwin";
  const macPath = "~/Library/Application Support/net.metaquotes.wine.metatrader5/drive_c/Program Files/MetaTrader 5/MQL5/Experts";
  $("#filters").innerHTML = "";
  $("#view").innerHTML = `<h1 class="page-title">اتصال متاتریدر</h1><p class="page-sub">اکسپرت فقط می‌خواند و هیچ سفارشی ثبت نمی‌کند. داده‌ها فقط روی همین کامپیوتر می‌مانند.</p>
  <ol class="steps">
    ${mac ? `<li><div>متاتریدر را ببند. در Finder کلیدهای Cmd + Shift + G را بزن و این مسیر را باز کن:<div class="copy"><code>${macPath}</code><button class="btn quiet" data-copy="${macPath}">کپی مسیر</button></div>فایل <code>TradeJournalBridge.mq5</code> را از پوشه <code>ea</code> آن‌جا کپی کن. متاتریدر را باز کن و در MetaEditor فایل را با Compile بساز. در MT4 مسیر متفاوت است و اگر پیدا نشد، از File و Open Data Folder کمک بگیر.</div></li>` : `<li><div>فایل <code>TradeJournalBridge.mq5</code> را برای MT5 یا <code>TradeJournalBridge.mq4</code> را برای MT4 در پوشه <code>MQL5/Experts</code> یا <code>MQL4/Experts</code> بگذار. این پوشه از منوی File و گزینه Open Data Folder باز می‌شود. بعد در MetaEditor با F7 کامپایلش کن.</div></li>`}
    <li><div>در متاتریدر به Tools، بعد Options، بعد Expert Advisors برو. Allow WebRequest را روشن کن و این آدرس را اضافه کن:<div class="copy"><code>${url}</code><button class="btn quiet" data-copy="${url}">کپی آدرس</button></div></div></li>
    <li><div>اکسپرت را روی یک چارت بینداز و این کلید را در ورودی Token بگذار:<div class="copy"><code>${esc(s.token)}</code><button class="btn quiet" data-copy="${esc(s.token)}">کپی کلید</button></div></div></li>
    <li><div>در MT4 از پنجره Account History گزینه All History را انتخاب کن تا سابقه کامل بیاید.</div></li>
  </ol>
  <h2 style="margin-bottom:8px">حساب‌های وصل‌شده</h2>
  ${accounts.length ? `<div class="scroll"><table><thead><tr><th>حساب</th><th>بروکر</th><th>پلتفرم</th><th>معامله</th><th>موجودی</th><th>وضعیت</th></tr></thead><tbody>${accounts.map((a) => `<tr><td><span class="num">${esc(a.login)}</span></td><td>${esc(a.broker || a.server)}</td><td>${esc(a.platform)}</td><td>${plain(a.trade_count)}</td><td>${plain(a.balance)}</td><td>${a.online ? "وصل" : `آخرین ارتباط ${stamp(a.last_seen)}`}</td></tr>`).join("")}</tbody></table></div>` : `<p class="muted">هنوز حسابی وصل نشده. بعد از مرحله ۳ این‌جا ظاهر می‌شود.</p>`}`;
  document.querySelectorAll("[data-copy]").forEach((b) => b.addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(b.dataset.copy); toast("کپی شد"); } catch { toast("مرورگر اجازه کپی نداد"); }
  }));
}

function ladder(t) {
  const items = [["حد سود", t.tp_initial], ["بهترین قیمت", t.mfe_price], ["خروج", t.exit_price], ["ورود", t.entry_price], ["حد ضرر", t.sl_initial], ["بدترین قیمت", t.mae_price]].filter((i) => i[1]);
  if (items.length < 2) return "";
  const dir = t.side === "buy" ? 1 : -1;
  items.sort((a, b) => (b[1] - a[1]) * dir);
  const far = Math.max(...items.map((i) => Math.abs(i[1] - t.entry_price))) || 1;
  return `<div class="ladder" role="table" aria-label="سطح‌های قیمت این معامله">${items.map(([n, v]) => {
    const d = (v - t.entry_price) * dir, pct = (Math.abs(d) / far) * 50;
    return `<div class="rung ${n === "ورود" ? "base" : ""}" role="row"><span>${n}</span><span class="num">${Number(v.toFixed(5))}</span><span class="lane"><i style="width:${pct}%;${d >= 0 ? "left:50%" : `left:${50 - pct}%`};background:var(${d >= 0 ? "--up" : "--down"})"></i></span></div>`;
  }).join("")}</div>`;
}

async function openTrade(account, position) {
  const d = await api(`/api/trades/${encodeURIComponent(account)}/${encodeURIComponent(position)}`);
  const t = d.trade, n = d.note;
  const drawer = $("#drawer");
  drawer.innerHTML = `<header><div><h2>${SIDE[t.side]} <bdi>${esc(t.symbol)}</bdi></h2><div>${t.closed ? money(t.net) : '<span class="muted">باز</span>'} <span class="muted">${esc(d.currency)}</span></div></div><button class="x" aria-label="بستن">×</button></header>
    <p class="story">${esc(d.story)}</p>${ladder(t)}
    <div class="grid2">
      <div class="fact"><b>${plain(t.volume)}</b><span>لات</span></div>
      <div class="fact"><b>${unit(t.r_multiple, "R")}</b><span>نتیجه نسبت به ریسک</span></div>
      <div class="fact"><b>${unit(t.mfe_r, "R")}</b><span>بیشترین حرکت موافق</span></div>
      <div class="fact"><b>${t.capture == null ? "–" : unit(t.capture * 100, "%", 0)}</b><span>سهم گرفته‌شده از حرکت</span></div>
      <div class="fact"><b>${money(t.costs)}</b><span>کارمزد و سواپ</span></div>
      <div class="fact"><b>${plain(t.exit_count)}</b><span>مرحله خروج</span></div>
    </div>
    ${d.events.length ? `<h3>خبرهای نزدیک این معامله</h3><div style="margin-bottom:16px">${d.events.map((e) => eventRow(e, true)).join("")}</div>` : ""}
    <h3>دقیقاً چه شد</h3><ol class="tl">${d.timeline.map((r) => `<li><small>${esc(r.label)}</small>${esc(r.text)}</li>`).join("")}</ol>
    <h3 style="margin-bottom:8px">یادداشت من</h3>
    <form id="note" class="form" style="grid-template-columns:1fr 1fr">
      <label>ستاپ<input type="text" name="setup" maxlength="120" value="${esc(n.setup)}"></label>
      <label>حس هنگام ورود<input type="text" name="emotion" maxlength="60" value="${esc(n.emotion)}"></label>
      <label style="grid-column:1/-1">امتیاز به اجرای خودم<select name="rating"><option value="">بدون امتیاز</option>${[1, 2, 3, 4, 5].map((v) => `<option ${n.rating === v ? "selected" : ""}>${v}</option>`).join("")}</select></label>
      <label style="grid-column:1/-1">یادداشت<textarea name="note" rows="4" maxlength="5000">${esc(n.note)}</textarea></label>
      <div><button class="btn">ذخیره یادداشت</button></div>
    </form>`;
  drawer.hidden = false; $("#scrim").hidden = false;
  drawer.querySelector(".x").addEventListener("click", closeDrawer);
  drawer.querySelector(".x").focus();
  $("#note").addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    await put(`/api/notes/${encodeURIComponent(account)}/${encodeURIComponent(position)}`, { setup: f.get("setup"), emotion: f.get("emotion"), rating: f.get("rating") ? +f.get("rating") : null, note: f.get("note") });
    toast("یادداشت ذخیره شد");
  });
}
function closeDrawer() { $("#drawer").hidden = true; $("#scrim").hidden = true; }
$("#scrim").addEventListener("click", closeDrawer);
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDrawer(); });

function reportHtml(text) {
  const out = [];
  let list = false;
  for (const raw of String(text).split("\n")) {
    const line = raw.trim();
    const item = line.match(/^[-*•]\s+(.*)/);
    if (list && !item) { out.push("</ul>"); list = false; }
    if (!line) continue;
    const clean = (t) => esc(t.replace(/\*\*/g, ""));
    if (line.startsWith("#")) out.push(`<h3>${clean(line.replace(/^#+\s*/, ""))}</h3>`);
    else if (item) { if (!list) { out.push("<ul>"); list = true; } out.push(`<li>${clean(item[1])}</li>`); }
    else out.push(`<p>${clean(line)}</p>`);
  }
  if (list) out.push("</ul>");
  return out.join("");
}

const EFFECT = { up: ["معمولاً صعودی", "up"], down: ["معمولاً نزولی", "down"], mixed: ["اثر نامشخص", "muted"] };
const countdown = (t) => {
  const m = Math.max(Math.round((t - Date.now() / 1000) / 60), 0);
  if (m < 60) return `${m} دقیقه دیگر`;
  if (m < 1440) return `${Math.floor(m / 60)} ساعت دیگر`;
  return `${Math.floor(m / 1440)} روز دیگر`;
};
function eventRow(e, past) {
  const fx = EFFECT[e.effect];
  const figs = [e.actual != null && `واقعی \u2066${e.actual}\u2069`, e.forecast != null && `پیش‌بینی \u2066${e.forecast}\u2069`, e.previous != null && `قبلی \u2066${e.previous}\u2069`].filter(Boolean).join("، ");
  return `<div class="ev"><span class="when">${past ? stamp(e.time_utc) : countdown(e.time_utc)}</span><span><i class="imp ${esc(e.impact)}" title="${e.impact === "high" ? "اثر زیاد" : "اثر متوسط"}"></i>${esc(e.currency)} ${esc(e.title)}</span><span class="${fx ? fx[1] : "muted"}">${fx ? fx[0] : ""}</span>${figs ? `<span class="fig">${esc(figs)}</span>` : ""}</div>`;
}
function ago(t) {
  const m = Math.round((Date.now() / 1000 - t) / 60);
  return m < 60 ? `${Math.max(m, 0)} دقیقه پیش` : m < 1440 ? `${Math.floor(m / 60)} ساعت پیش` : `${Math.floor(m / 1440)} روز پیش`;
}
function sourceRows(rows) {
  if (!rows.length) return `<p class="muted">منبع‌ها تازه شروع به دریافت می‌کنند.</p>`;
  return rows.map((r) => `<div class="src"><span>${esc(r.name)}</span><span class="${r.error ? "down" : "muted"}">${r.error ? (r.last_ok ? `قطع، آخرین دریافت ${ago(r.last_ok)}` : "در دسترس نیست") : `${ago(r.last_ok)}`}</span></div>`).join("");
}

async function viewNews() {
  const list = state.settings.markets.length ? state.settings.markets : Object.keys(state.settings.catalog);
  if (!list.includes(state.market)) state.market = list[0];
  const d = await api(`/api/news/${state.market}`);
  $("#filters").innerHTML = "";
  const chips = Object.entries(state.settings.catalog).filter(([k]) => list.includes(k)).map(([k, n]) => `<button data-m="${k}" aria-pressed="${k === state.market}">${esc(n)}</button>`).join("");
  $("#view").innerHTML = `
    <div class="bar-row"><div class="chips" role="group" aria-label="بازار">${chips}</div><button class="btn quiet" id="refresh">دریافت دوباره خبرها</button></div>
    <section class="hero">
      <div class="lean"><b>${esc(d.lean)}</b><span class="muted">جمع‌بندی ${esc(d.name)} از شگفتی‌های ۷ روز اخیر: ${d.ups} صعودی و ${d.downs} نزولی</span></div>
      <p class="caution">این جمع‌بندی از واکنش معمول بازار به داده‌ها می‌آید و پیش‌بینی قیمت نیست.</p>
    </section>
    <div class="cols">
      <section class="block"><h2>جمع‌بندی هوش مصنوعی</h2>
        ${d.ai ? `<div class="report">${reportHtml(d.ai.body)}</div><p class="caution">${stamp(d.ai.created_at)}، مدل ${esc(d.ai.model)}</p>` : `<p class="muted">${d.ai_ready ? "هنوز جمع‌بندی‌ای ساخته نشده." : "برای جمع‌بندی فارسی، سرویس هوش مصنوعی را تنظیم کن."}</p>`}
        <p style="margin-top:10px">${d.ai_ready ? `<button class="btn" id="brief">ساخت جمع‌بندی ${esc(d.name)}</button>` : `<button class="btn quiet" onclick="go('sources')">تنظیم هوش مصنوعی</button>`}</p>
      </section>
      <section class="block"><h2>رویدادهای پیش رو</h2>${d.upcoming.map((e) => eventRow(e, false)).join("") || `<p class="muted">رویداد مهمی ثبت نشده.</p>`}</section>
    </div>
    <div class="cols">
      <section class="block"><h2>سرخط‌ها</h2>${d.news.map((n) => `<div class="head"><a href="${esc(n.link)}" target="_blank" rel="noopener noreferrer">${esc(n.title)}</a><small>${esc(n.source)}، ${ago(n.published_utc)}</small></div>`).join("") || `<p class="muted">سرخطی برای این بازار نیامده.</p>`}</section>
      <section class="block"><h2>منتشرشده</h2>${d.released.map((e) => eventRow(e, true)).join("") || `<p class="muted">رویدادی در ۷ روز اخیر نیست.</p>`}
        <h2 style="margin-top:20px;margin-bottom:6px">وضعیت منبع‌ها</h2>${sourceRows(d.sources)}</section>
    </div>`;
  document.querySelectorAll("[data-m]").forEach((b) => b.addEventListener("click", () => { state.market = b.dataset.m; render(); }));
  $("#refresh").addEventListener("click", async () => {
    const r = await api("/api/news/refresh", jsonPost());
    toast(r.started ? "دریافت شروع شد" : "در حالت نمونه خبری دریافت نمی‌شود");
  });
  $("#brief")?.addEventListener("click", (e) => runAi(e.target, `/api/news/${state.market}/brief`));
}

const jsonPost = () => ({ method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
async function runAi(button, path) {
  button.disabled = true;
  const label = button.textContent;
  button.textContent = "در حال ساخت، تا یک دقیقه طول می‌کشد";
  const res = await fetch(path, jsonPost());
  button.disabled = false;
  button.textContent = label;
  if (!res.ok) { const b = await res.json().catch(() => ({})); toast(b.detail || "ساخت گزارش انجام نشد"); return; }
  render();
}

async function viewCoach() {
  const d = await api("/api/coach");
  $("#filters").innerHTML = "";
  const [last, ...old] = d.reports;
  $("#view").innerHTML = `<h1 class="page-title">مربی</h1><p class="page-sub">مربی آمار، نکته‌های رفتاری، ۴۰ معامله آخر و یادداشت‌هایت را می‌خواند و گزارش قبلی را هم می‌بیند، پس پیشرفتت را دنبال می‌کند. شماره حساب و نام بروکر ارسال نمی‌شود.</p>
    <p style="margin-bottom:18px">${d.ready ? `<button class="btn" id="coach">ساخت گزارش تازه</button>` : `<button class="btn" onclick="go('sources')">تنظیم هوش مصنوعی</button>`}</p>
    ${last ? `<div class="report">${reportHtml(last.body)}</div><p class="caution">${stamp(last.created_at)}، بر اساس ${last.closed_trades} معامله بسته. مربی جایگزین مشاور مالی نیست.</p>` : `<div class="empty"><h2>هنوز گزارشی نیست</h2><p>${d.ready ? "با دست‌کم ۱۰ معامله بسته، اولین گزارش را بساز." : "اول سرویس هوش مصنوعی را وصل کن. پیشنهادهای آماری در نمای کلی بدون آن هم کار می‌کنند."}</p></div>`}
    ${old.length ? `<h2 style="margin:26px 0 8px">گزارش‌های قبلی</h2>${old.map((r) => `<details class="head"><summary>${stamp(r.created_at)}، ${r.closed_trades} معامله</summary><div class="report">${reportHtml(r.body)}</div></details>`).join("")}` : ""}`;
  $("#coach")?.addEventListener("click", (e) => runAi(e.target, "/api/coach"));
}

function viewSources() {
  const s = state.settings, a = s.ai;
  $("#filters").innerHTML = "";
  $("#view").innerHTML = `<h1 class="page-title">هوش مصنوعی و منبع‌ها</h1>
  <p class="page-sub">هر سرویس سازگار با OpenAI یا Anthropic کار می‌کند، از جمله سرویس‌های واسطی که از ایران در دسترس‌اند. سرویس واسط متن گزارش‌ها را می‌بیند، پس به آن اعتماد داشته باش.</p>
  <form class="form" id="ai">
    <label>نوع سرویس<select name="format"><option value="openai">سازگار با OpenAI</option><option value="anthropic">Anthropic</option></select></label>
    <label>آدرس سرویس<input class="ltr" type="text" name="base_url" value="${esc(a.base_url)}" placeholder="https://api.openai.com/v1"></label>
    <label>نام مدل<input class="ltr" type="text" name="model" value="${esc(a.model)}"></label>
    <label>کلید API<input class="ltr" type="password" name="api_key" autocomplete="off" placeholder="${a.has_key ? "ذخیره شده است" : ""}" style="background:var(--surface);border:1px solid var(--line);border-radius:var(--r);padding:5px 10px;width:100%"><small>فقط روی همین کامپیوتر ذخیره می‌شود.</small></label>
    <label>گزارش خودکار مربی${""}<input type="number" name="auto_every" min="0" value="${a.auto_every}"><small>بعد از هر چند معامله بسته. صفر یعنی فقط با دکمه. هر گزارش هزینه مصرف دارد.</small></label>
    <div style="grid-column:1/-1"><button class="btn">ذخیره تنظیمات هوش مصنوعی</button></div>
  </form>
  <h2 style="margin:28px 0 8px">بازارهای من</h2>
  <div class="chips" role="group" aria-label="بازارها" style="display:inline-flex;flex-wrap:wrap;margin-bottom:6px">${Object.entries(s.catalog).map(([k, n]) => `<button data-pick="${k}" aria-pressed="${s.markets.includes(k)}">${esc(n)}</button>`).join("")}</div>
  <p class="muted" style="margin-bottom:24px">در صفحه خبر و هشدار خبر فقط همین بازارها می‌آیند.</p>
  <form class="form" id="net">
    <label style="grid-column:1/-1">منبع‌های اضافه<textarea class="feeds" name="feeds" rows="3" placeholder="https://example.com/rss.xml">${esc(s.feeds.join("\n"))}</textarea><small>هر خط یک آدرس RSS.</small></label>
    <label>پراکسی<input class="ltr" type="text" name="proxy" value="${esc(s.proxy)}" placeholder="http://127.0.0.1:10809"><small>اگر بعضی منبع‌ها در دسترس نبودند. فقط نوع http کار می‌کند.</small></label>
    <div style="grid-column:1/-1"><button class="btn">ذخیره منبع‌ها</button></div>
  </form>`;
  $("#ai [name=format]").value = a.format;
  $("#ai").addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    const body = { format: f.get("format"), base_url: f.get("base_url").trim(), model: f.get("model").trim(), auto_every: +f.get("auto_every") };
    if (f.get("api_key")) body.api_key = f.get("api_key").trim();
    try { await put("/api/settings", { ai: body }); state.settings = await api("/api/settings"); toast("تنظیمات ذخیره شد"); viewSources(); }
    catch { toast("آدرس سرویس باید با http شروع شود"); }
  });
  document.querySelectorAll("[data-pick]").forEach((b) => b.addEventListener("click", async () => {
    const k = b.dataset.pick;
    s.markets = s.markets.includes(k) ? s.markets.filter((m) => m !== k) : [...s.markets, k];
    await put("/api/settings", { markets: s.markets });
    b.setAttribute("aria-pressed", s.markets.includes(k));
  }));
  $("#net").addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    const list = f.get("feeds").split("\n").map((x) => x.trim()).filter(Boolean);
    try { await put("/api/settings", { feeds: list, proxy: f.get("proxy").trim() }); s.feeds = list; s.proxy = f.get("proxy").trim(); toast("منبع‌ها ذخیره شد"); }
    catch { toast("آدرس‌ها باید با http یا https شروع شوند"); }
  });
}

const VIEWS = { overview: viewOverview, news: viewNews, coach: viewCoach, sources: viewSources, trades: viewTrades, patterns: viewPatterns, rules: viewRules, theme: viewTheme, connect: viewConnect };

async function render() {
  document.querySelectorAll("#nav button").forEach((b) => b.toggleAttribute("aria-current", false));
  document.querySelector(`#nav [data-view=${state.view}]`).setAttribute("aria-current", "page");
  try { await VIEWS[state.view](); }
  catch { $("#view").innerHTML = `<div class="empty"><h2>سرور جواب نمی‌دهد</h2><p>برنامه را دوباره با start.bat اجرا کن.</p></div>`; }
}
function go(view) { state.view = view; try { location.hash = view; } catch {} render(); }
window.go = go;
document.querySelectorAll("#nav button").forEach((b) => b.addEventListener("click", () => go(b.dataset.view)));

async function poll() {
  try {
    const before = state.status?.accounts?.map((a) => `${a.id}:${a.trade_count}`).join();
    state.status = await api("/api/status");
    renderLink();
    const after = state.status.accounts.map((a) => `${a.id}:${a.trade_count}`).join();
    if (before !== undefined && before !== after && ["overview", "trades", "patterns"].includes(state.view) && $("#drawer").hidden) render();
  } catch { $("#link").innerHTML = `<span class="dot"></span>سرور قطع است`; }
}

(async () => {
  state.settings = await api("/api/settings");
  applyTheme(state.settings.theme);
  await poll();
  const hash = location.hash.slice(1);
  if (VIEWS[hash]) state.view = hash;
  await render();
  setInterval(poll, 5000);
})();
