"use strict";
/* AutoCert Studio — dashboard front-end */

const $ = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));

const LS_KEY = "autocert.project.v1";
const LS_SEEN = "autocert.welcome.seen";

const S = {
  config: null,
  selected: null,   // selected field object
  mode: null,       // "text" | "photo" | null (add-mode)
  fonts: [],
  counter: 0,
  drag: null,
  metrics: {},      // field.id -> {w, h, sig} rendered text-block size
  fontFilter: "",
};

let prevURL = null;
let prevTimer = null;
let prevSeq = 0;
let pollT = null;
let generating = false;

/* ------------------------------------------------------------------ util */

function newId() { return "f" + (++S.counter) + "_" + Math.random().toString(36).slice(2, 7); }

function esc(v) {
  return String(v == null ? "" : v).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function humanSize(bytes) {
  const b = Number(bytes) || 0;
  if (b >= 1024 * 1024) return (b / 1024 / 1024).toFixed(1) + " MB";
  if (b >= 1024) return Math.round(b / 1024) + " kB";
  return b + " B";
}

function freshConfig() {
  return {
    name: "",
    photos_folder: "",
    filename_column: "",
    file_prefix: "",
    pdf_mode: "fit",
    template: null,   // {path,name,width,height}
    excel: null,      // {path,name,columns,row_count}
    fields: [],
  };
}

function saveLocal() {
  try { localStorage.setItem(LS_KEY, JSON.stringify(S.config)); } catch (_) {}
}

let toastT = null;
function toast(msg, kind = "info", ms = 4200) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "show " + kind;
  clearTimeout(toastT);
  toastT = setTimeout(() => { t.className = ""; }, ms);
}

function tpl() { return S.config && S.config.template; }
function xcl() { return S.config && S.config.excel; }
function columns() { return (xcl() && xcl().columns) || []; }

/* -------------------------------------------------------- field model ---- */

function defaultField(type, x, y) {
  const st = tpl();
  const w = st ? st.width : 1200;
  const base = { id: newId(), column: "", x, y };
  if (type === "photo") {
    const bw = Math.max(80, Math.min(600, Math.round(w * 0.2)));
    return { ...base, type: "photo", fit: "fill",
             shape: "rect", radius: 0, bg_remove: false, bg_tol: 30,
             width: bw, height: Math.round(bw * 1.33), border: 0, border_color: "#20306E" };
  }
  return {
    ...base, type: "text",
    font: "Arial",
    size: Math.max(18, Math.min(320, Math.round(w * 0.045))),
    color: "#16233F",
    align: "left", valign: "center",
    wrap_width: 0, uppercase: false,
    datefmt: "", prefix: "", suffix: "",
  };
}

function guessColumn(type) {
  const cols = columns();
  if (type === "photo") {
    const pref = ["photo", "image", "pic", "img", "snapshot", "avatar"];
    for (const p of pref) {
      const c = cols.find((c) => c.toLowerCase().includes(p));
      if (c) return c;
    }
    return "";
  }
  return cols[0] || "";
}

function fieldLabel(f) {
  if (f.type === "photo") {
    return f.column ? f.column : "photo — no column";
  }
  if (f.column) return f.column;
  const custom = (f.prefix || "") + (f.suffix || "");
  return custom ? ("“" + custom.slice(0, 18) + "”") : "custom text";
}

/* ------------------------------------------------------- dashboard status */

function setStatus(elSel, text, cls) {
  const el = $(elSel);
  if (!el) return;
  el.textContent = text;
  el.className = "status" + (cls ? " " + cls : "");
}

function setCheck(elSel, ok, text) {
  const li = $(elSel);
  if (!li) return;
  li.classList.toggle("ok", ok === true);
  li.classList.toggle("bad", ok === false);
  const st = li.querySelector(".st");
  if (st) st.textContent = ok ? "" : "!";
  if (text != null) {
    const tx = li.querySelector(".tx");
    if (tx) tx.textContent = text;
  }
}

function updateDashboard() {
  const cfg = S.config || freshConfig();
  const st = tpl(); const xl = xcl();
  const fields = cfg.fields || [];
  const anyPhoto = fields.some((f) => f.type === "photo");
  const hasPath = !!(cfg.photos_folder && cfg.photos_folder.trim());

  setStatus("#statusTemplate", st ? "✓ loaded" : "not loaded", st ? "ok" : "");
  setStatus("#statusExcel", xl ? `✓ ${xl.row_count} rows` : "not loaded", xl ? "ok" : "warn");
  setStatus("#statusFields", fields.length ? `✓ ${fields.length} placed` : "0 placed", fields.length ? "ok" : "");
  if (anyPhoto) {
    setStatus("#statusPhotos", hasPath ? "✓ folder set" : "choose folder", hasPath ? "ok" : "warn");
  } else {
    setStatus("#statusPhotos", "optional");
  }

  setCheck("#chkTemplate", !!st, st
    ? `✓ Design uploaded (${st.width}×${st.height}px)`
    : "Design image uploaded");
  setCheck("#chkExcel", !!xl, xl
    ? `✓ Excel uploaded — ${xl.row_count} rows`
    : "Excel list uploaded");
  setCheck("#chkFields", fields.length > 0,
    fields.length ? `✓ Fields placed` : "At least one field placed");

  const genLbl = xl && xl.row_count
    ? `⚡ Generate ${xl.row_count} card${xl.row_count === 1 ? "" : "s"}`
    : "⚡ Generate all cards";
  $("#btnGenerate2").textContent = genLbl;
  $("#btnGenerate").textContent = genLbl;
}

/* ------------------------------------------------------------ location ---
   Every field has a visual bounding box. Photos use x/y/w/h directly;
   text fields use the exact rendered size fetched from /api/text-metrics,
   so on-canvas boxes and alignment targets match the printed output. */

function metricsSignature(f, row) {
  return JSON.stringify([f.column, f.font, f.size, f.wrap_width, f.datefmt,
                         f.prefix, f.suffix, f.uppercase, row]);
}

async function fetchMetrics(f, row) {
  const sig = metricsSignature(f, row);
  const cached = S.metrics[f.id];
  if (cached && cached.sig === sig) return cached;
  const token = sig;
  try {
    const res = await fetch("/api/text-metrics?row=" + row, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...S.config, field: f }),
    });
    if (!res.ok) return null;
    const j = await res.json();
    // only apply if the field still asks for these metrics
    if (metricsSignature(f, row) !== token) return null;
    S.metrics[f.id] = { w: Math.round(j.width || 0), h: Math.round(j.height || 0), sig };
    syncOverlays();
    return S.metrics[f.id];
  } catch (_) {
    return null;
  }
}

function queueMetrics(f) {
  if (!f || f.type !== "text") return;
  clearTimeout(f.__mTimer);
  f.__mTimer = setTimeout(() => fetchMetrics(f, currentRow() - 1), 250);
}

function fieldBox(f) {
  if (f.type === "photo") {
    return { left: f.x, top: f.y, right: f.x + f.width, bottom: f.y + f.height };
  }
  const m = S.metrics[f.id] || { w: 0, h: 0 };
  const align = f.align || "left", valign = f.valign || "top";
  const left = align === "left" ? f.x : align === "right" ? f.x - m.w : f.x - m.w / 2;
  const top = valign === "top" ? f.y : valign === "bottom" ? f.y - m.h : f.y - m.h / 2;
  return { left, top, right: left + m.w, bottom: top + m.h };
}

function canvasExtent() {
  const st = tpl();
  return { W: st ? st.width : 1200, H: st ? st.height : 750 };
}

function alignField(f, which) {
  const { W, H } = canvasExtent();
  if (f.type !== "photo") queueMetrics(f);       // make sure we have a box
  const b = fieldBox(f);
  let dx = 0, dy = 0;
  if (which === "left") dx = 0 - b.left;
  else if (which === "hcenter") dx = W / 2 - (b.left + b.right) / 2;
  else if (which === "right") dx = W - b.right;
  else if (which === "top") dy = 0 - b.top;
  else if (which === "vcenter") dy = H / 2 - (b.top + b.bottom) / 2;
  else if (which === "bottom") dy = H - b.bottom;
  if (!dx && !dy) return;
  f.x += Math.round(dx);
  f.y += Math.round(dy);
  fillPropsXY(f);
  syncOverlays();
  saveLocal();
  schedulePreview(300);
}

/* --------------------------------------------------------------- add-mode */

function setMode(m) {
  S.mode = (S.mode === m ? null : m);
  $$(".modeBtn").forEach((b) => {
    b.classList.toggle("active", !!S.mode && b.id === (m === "text" ? "btnAddText" : "btnAddPhoto"));
  });
  const bar = $("#hintBar");
  if (S.mode) {
    bar.hidden = false;
    bar.innerHTML = m === "text"
      ? `<span>👆 Now click on the design where the text should go — the point is aligned according to the field’s properties on the left. <b>Tune font, size & column afterwards.</b> <button id="cancelMode">cancel</button></span>`
      : `<span>👆 Now click on the design at the top-left corner of where the photo box should go. <b>Set the photo column afterwards.</b> <button id="cancelMode">cancel</button></span>`;
    bar.scrollIntoView({ block: "nearest", behavior: "smooth" });
    $("#cancelMode").onclick = () => setMode(null);
  } else {
    bar.hidden = true;
  }
  $("#imgBox").classList.toggle("placing", !!S.mode);
}

function addField(type, x, y) {
  const f = defaultField(type, Math.round(x), Math.round(y));
  f.column = guessColumn(type);
  S.config.fields.push(f);
  setMode(null);
  select(f);
  updateDashboard();
  saveLocal();
  schedulePreview(300);
}

/* -------------------------------------------------------------- selection */

function select(f) {
  S.selected = f;
  if (f && f.type === "text") queueMetrics(f);
  syncOverlays();
  renderFieldList();
  buildProps();
  if (f) {
    const card = $("#propsCard");
    if (card) card.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }
}

function deleteField(f) {
  const i = S.config.fields.indexOf(f);
  if (i >= 0) S.config.fields.splice(i, 1);
  S.selected = null;
  syncOverlays();
  renderFieldList();
  buildProps();
  updateDashboard();
  saveLocal();
  schedulePreview(200);
}

function moveField(f, dir) {
  const a = S.config.fields;
  const i = a.indexOf(f);
  const j = i + dir;
  if (i < 0 || j < 0 || j >= a.length) return;
  a.splice(i, 1);
  a.splice(j, 0, f);
  renderFieldList();
  syncOverlays();
  saveLocal();
  schedulePreview(200);
}

/* ----------------------------------------------------------------- canvas */

function canvasScale() {
  const st = tpl();
  if (!st) return 1;
  const rect = $("#imgBox").getBoundingClientRect();
  return rect.width / st.width;
}

function showCanvas(on) {
  $("#canvasWrap").hidden = !on;
  $("#emptyState").hidden = on;
}

async function setCanvasImage() {
  const st = tpl();
  if (!st) { showCanvas(false); return; }
  const img = $("#tplImg");
  await new Promise((res) => {
    img.onload = res; img.onerror = res;
    img.src = "/api/template-image?path=" + encodeURIComponent(st.path) + "&v=" + Date.now();
  });
  if (!img.naturalWidth) {
    showCanvas(false);
    toast("Design file is missing on disk — please re-upload it.", "error", 6500);
    return;
  }
  showCanvas(true);
  $("#imgBox").style.aspectRatio = st.width + " / " + st.height;
  $("#canvasInfo").textContent = `${st.name} · ${st.width}×${st.height}px`;
  syncOverlays();
}

function syncOverlays() {
  const wrap = $("#overlays");
  wrap.innerHTML = "";
  const st = tpl();
  if (!st) return;
  const scale = canvasScale();

  /* true bounding box behind the selected text field */
  const f = S.selected;
  if (f && f.type === "text") {
    const m = S.metrics[f.id];
    if (m && (m.w > 0 || m.h > 0)) {
      const b = fieldBox(f);
      const el = document.createElement("div");
      el.className = "vText sel";
      el.style.left = (b.left * scale) + "px";
      el.style.top = (b.top * scale) + "px";
      el.style.width = (m.w * scale) + "px";
      el.style.height = (m.h * scale) + "px";
      wrap.appendChild(el);
    }
  }

  for (const f of S.config.fields) {
    let el;
    const sel = S.selected === f ? " sel" : "";
    if (f.type === "photo") {
      el = document.createElement("div");
      el.className = "photoBox" + sel;
      el.style.left = (f.x * scale) + "px";
      el.style.top = (f.y * scale) + "px";
      el.style.width = (f.width * scale) + "px";
      el.style.height = (f.height * scale) + "px";
      el.innerHTML = `<span class="pip">📷 ${esc(fieldLabel(f))}</span>`;
      if (f.shape === "circle") el.style.borderRadius = "50%";
      else if (f.shape === "round") el.style.borderRadius = Math.min(f.radius, Math.min(f.width, f.height) / 2) * scale + "px";
    } else {
      el = document.createElement("div");
      el.className = "mark" + sel;
      el.style.left = (f.x * scale) + "px";
      el.style.top = (f.y * scale) + "px";
      el.innerHTML = `<span class="dot"></span><span class="lbl">🔤 ${esc(fieldLabel(f))}</span>`;
    }
    el.dataset.fid = f.id;
    el.addEventListener("pointerdown", (e) => beginDrag(f, e));
    wrap.appendChild(el);
  }
}

function clearGuides() {
  $$("#overlays .snapGuide").forEach((g) => g.remove());
}

function updateOverlayEl(f) {
  const el = $(`#overlays [data-fid="${f.id}"]`);
  if (!el) { syncOverlays(); return; }
  const scale = canvasScale();
  if (el.classList.contains("mark")) {
    el.style.left = (f.x * scale) + "px";
    el.style.top = (f.y * scale) + "px";
  } else {
    el.style.left = (f.x * scale) + "px";
    el.style.top = (f.y * scale) + "px";
    el.style.width = (f.width * scale) + "px";
    el.style.height = (f.height * scale) + "px";
  }
}

/* ---------------------------------------------------------------- dragging */

function beginDrag(f, e) {
  e.stopPropagation(); e.preventDefault();
  select(f);
  const scale = canvasScale();
  S.drag = { f, dx: e.clientX - f.x * scale, dy: e.clientY - f.y * scale, moved: false };
  window.addEventListener("pointermove", dragMove);
  window.addEventListener("pointerup", dragEnd, { once: true });
  document.body.classList.add("grabbing");
}

const SNAP_PX = 6;

function computeSnap(f) {
  /* Snap the field's box against the canvas edges/centre and against every
     other field. Returns {dx, dy, guides} or null. */
  const { W, H } = canvasExtent();
  const b = fieldBox(f);
  const candsX = [[b.left, "left"], [(b.left + b.right) / 2, "cx"], [b.right, "right"]];
  const candsY = [[b.top, "top"], [(b.top + b.bottom) / 2, "cy"], [b.bottom, "bottom"]];
  const targetsX = [0, W / 2, W];
  const targetsY = [0, H / 2, H];
  for (const o of S.config.fields) {
    if (o === f) continue;
    const ob = fieldBox(o);
    targetsX.push(ob.left, (ob.left + ob.right) / 2, ob.right);
    targetsY.push(ob.top, (ob.top + ob.bottom) / 2, ob.bottom);
  }
  let bestX = null, bestY = null;
  for (const [pos, kind] of candsX) {
    for (const t of targetsX) {
      const d = t - pos;
      if (Math.abs(d) <= SNAP_PX && (!bestX || Math.abs(d) < Math.abs(bestX.d)))
        bestX = { d, t, kind };
    }
  }
  for (const [pos, kind] of candsY) {
    for (const t of targetsY) {
      const d = t - pos;
      if (Math.abs(d) <= SNAP_PX && (!bestY || Math.abs(d) < Math.abs(bestY.d)))
        bestY = { d, t, kind };
    }
  }
  if (!bestX && !bestY) return null;
  const guides = [];
  if (bestX) guides.push({ dir: "v", pos: bestX.t });
  if (bestY) guides.push({ dir: "h", pos: bestY.t });
  return { dx: bestX ? Math.round(bestX.d) : 0, dy: bestY ? Math.round(bestY.d) : 0, guides };
}

function drawGuides(guides) {
  clearGuides();
  if (!guides) return;
  const wrap = $("#overlays");
  const scale = canvasScale();
  for (const g of guides) {
    const el = document.createElement("div");
    el.className = "snapGuide " + g.dir;
    if (g.dir === "v") el.style.left = (g.pos * scale) + "px";
    else el.style.top = (g.pos * scale) + "px";
    wrap.appendChild(el);
  }
}

function dragMove(e) {
  if (!S.drag) return;
  const st = tpl(); if (!st) return;
  const scale = canvasScale();
  const f = S.drag.f;
  const nx = Math.round(Math.max(0, Math.min(st.width, (e.clientX - S.drag.dx) / scale)));
  const ny = Math.round(Math.max(0, Math.min(st.height, (e.clientY - S.drag.dy) / scale)));
  if (nx !== f.x || ny !== f.y) { S.drag.moved = true; }
  f.x = nx; f.y = ny;
  const snap = computeSnap(f);
  if (snap && (snap.dx || snap.dy)) {
    f.x = Math.max(0, Math.min(st.width, f.x + snap.dx));
    f.y = Math.max(0, Math.min(st.height, f.y + snap.dy));
  }
  drawGuides(snap && (snap.dx || snap.dy) ? snap.guides : null);
  updateOverlayEl(f);
  if (S.selected === f) fillPropsXY(f);
}

function dragEnd() {
  window.removeEventListener("pointermove", dragMove);
  document.body.classList.remove("grabbing");
  clearGuides();
  const d = S.drag; S.drag = null;
  if (d && d.moved) { saveLocal(); schedulePreview(400); }
}

/* -------------------------------------------------------------- field list */

function renderFieldList() {
  const ul = $("#fieldList");
  ul.innerHTML = "";
  const fields = S.config.fields;
  $("#fieldsHint").style.display = fields.length ? "none" : "block";
  fields.forEach((f) => {
    const li = document.createElement("li");
    li.dataset.type = f.type;
    if (S.selected === f) li.classList.add("sel");
    li.innerHTML = `<span class="ficon">${f.type === "photo" ? "📷" : "Aa"}</span>` +
      `<span class="flabel">${esc(fieldLabel(f))}</span>` +
      `<span class="fctl">
        <button title="Move earlier">▲</button>
        <button title="Move later">▼</button>
        <button title="Delete">✕</button>
      </span>`;
    li.addEventListener("click", () => select(f));
    const [up, down, del] = li.querySelectorAll("button");
    up.addEventListener("click", (e) => { e.stopPropagation(); moveField(f, -1); });
    down.addEventListener("click", (e) => { e.stopPropagation(); moveField(f, +1); });
    del.addEventListener("click", (e) => { e.stopPropagation(); deleteField(f); });
    ul.appendChild(li);
  });
}

/* -------------------------------------------------------------------- props */

function colOptionsHTML(forType, cur) {
  const cols = columns();
  const opts = cols.map((c) =>
    `<option value="${esc(c)}"${c === cur ? " selected" : ""}>${esc(c)}</option>`).join("");
  if (!cols.length) return `<option value="${esc(cur || "")}">${esc(cur || "— upload Excel first —")}</option>`;
  if (forType === "photo") {
    return `<option value=""${!cur ? " selected" : ""}>— choose column —</option>` + opts;
  }
  return `<option value=""${!cur ? " selected" : ""}>— custom text —</option>` + opts;
}

function datefmtOptionsHTML(cur) {
  const opts = [
    ["", "as in Excel (no re-format)"],
    ["%d/%m/%Y", "DD/MM/YYYY"],
    ["%d-%m-%Y", "DD-MM-YYYY"],
    ["%d %b %Y", "05 Nov 2026"],
    ["%d %B %Y", "05 November 2026"],
    ["%Y-%m-%d", "YYYY-MM-DD"],
  ];
  return opts.map(([v, l]) =>
    `<option value="${v}"${v === cur ? " selected" : ""}>${l}</option>`).join("");
}

function seg(pairs, cur) {
  return pairs.map(([v, l]) =>
    `<button type="button" data-v="${v}" class="${v === cur ? "on" : ""}">${l}</button>`).join("");
}

/* ── font picker: searchable list with live text previews ──
   Each font is loaded through @font-face from /api/font-file, so the
   preview is real text: glyphs the font lacks fall back to the system
   font automatically — no more □■ tofu boxes. Items render lazily
   (chunks at the bottom sentinel) so hundreds of files stay fast. */

const _fontFaces = new Set();

function _fontHash(s) {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
  return h.toString(36);
}

function fontFamilyName(label) {
  return "acf-" + label.toLowerCase().replace(/[^a-z0-9]+/g, "-")
                        .replace(/^-+|-+$/g, "") + "-" + _fontHash(label);
}

function ensureFontFace(label) {
  const fam = fontFamilyName(label);
  if (_fontFaces.has(fam)) return fam;
  _fontFaces.add(fam);
  try {
    const face = new FontFace(fam,
      `url(/api/font-file?label=${encodeURIComponent(label)})`,
      { display: "swap" });
    document.fonts.add(face);     // loads when first used by rendered text
  } catch (_) { /* very old runtime → previews stay system-styled */ }
  return fam;
}

function fontItemHTML(f, cur) {
  const fam = ensureFontFace(f);
  return `
    <div class="fItem${f === cur ? " sel" : ""}" data-label="${esc(f)}">
      <div class="fSample" style="font-family:'${fam}',system-ui,-apple-system,'Helvetica Neue',Arial,sans-serif">Abc 123</div>
      <div class="fCaption">${esc(f)}</div>
    </div>`;
}

const _FONT_CHUNK = 40;
let _fontListCursor = 0;          // list entries consumed so far

function fontCandidates() {
  const q = S.fontFilter.trim().toLowerCase();
  return S.fonts.filter((f) => !q || f.toLowerCase().includes(q));
}

function _fontChunkHTML(list, from, to, cur) {
  let acc = "";
  for (let i = from; i < to; i++) {
    if (list[i] === cur) continue;
    acc += fontItemHTML(list[i], cur);
  }
  return acc;
}

/* Keep the selected font's row pinned at the top, then the first chunk. */
function fontListStartHTML(cur) {
  const def = `
    <div class="fItem fDefault${!cur ? " sel" : ""}" data-label="">
      <div class="fSample sysDefault">— system default —</div>
      <div class="fCaption">the app's fallback font</div>
    </div>`;
  const list = fontCandidates();
  _fontListCursor = Math.min(list.length, _FONT_CHUNK);
  const head = cur && list.includes(cur) ? fontItemHTML(cur, cur) : "";
  const more = _fontListCursor < list.length ? `<div id="fontSentinel"></div>` : "";
  return (cur ? "" : def) + head + _fontChunkHTML(list, 0, _fontListCursor, cur)
       + more + (cur ? def : "");
}

/* Append the next chunk once the sentinel gets close to view. */
function fontListMore(cur) {
  const list = fontCandidates();
  if (_fontListCursor >= list.length) { $("#fontSentinel")?.remove(); return; }
  const end = Math.min(list.length, _fontListCursor + _FONT_CHUNK);
  const acc = _fontChunkHTML(list, _fontListCursor, end, cur);
  _fontListCursor = end;
  const sn = $("#fontSentinel");
  if (sn) {
    sn.insertAdjacentHTML("beforebegin", acc);
    if (_fontListCursor >= list.length) sn.remove();
  }
}

function fontPickerHTML(cur) {
  return `
    <div class="fontPick">
      <div class="fpTop">
        <input type="text" id="pFontSearch" placeholder="Search ${S.fonts.length} fonts…" value="${esc(S.fontFilter)}" spellcheck="false">
        <button class="btn mini primary fpImport" id="pFontImport" title="Import more fonts from a link or files">⤓ Import</button>
      </div>
      <div class="fontList" id="pFontList">${fontListStartHTML(cur)}</div>
    </div>`;
}

function bindFontListScroll(cur) {
  const sn = $("#fontSentinel");
  if (!sn) return;
  const holder = sn.closest(".fontList");
  if ("IntersectionObserver" in window) {
    const io = new IntersectionObserver((ents) => {
      if (ents.some((e) => e.isIntersecting)) fontListMore(cur);
    }, { root: holder, rootMargin: "160px" });
    io.observe(sn);
  } else {
    holder?.addEventListener("scroll", () => {
      if (!$("#fontSentinel")) return;
      if (sn.getBoundingClientRect().bottom < holder.getBoundingClientRect().bottom + 160)
        fontListMore(cur);
    }, { passive: true });
  }
}

function rerenderFontList(cur) {
  const holder = $("#pFontList");
  if (!holder) return;
  holder.innerHTML = fontListStartHTML(cur);
  bindFontListScroll(cur);
}

/* ── shared props scaffolding ── */

const ALIGN_BUTTONS = [
  ["left", "⇤"], ["hcenter", "⇔"], ["right", "⇥"],
  ["top", "⤒"], ["vcenter", "⥮"], ["bottom", "⤓"],
];

function alignRowHTML() {
  return `
    <div class="secLabel">Position &amp; align</div>
    <div class="row2">
      <label>X (px)<input type="number" id="pX" value="${S.selected.x}"></label>
      <label>Y (px)<input type="number" id="pY" value="${S.selected.y}"></label>
    </div>
    <label>Align on the design
      <div class="alignGrid" id="pAlignGrid">
        ${ALIGN_BUTTONS.map(([v, ic]) =>
          `<button type="button" data-v="${v}" title="${{
             left:"Left edge", hcenter:"Horizontal centre", right:"Right edge",
             top:"Top edge", vcenter:"Vertical centre", bottom:"Bottom edge"
           }[v]}">${ic}</button>`).join("")}
      </div>
    </label>
    <div class="alignHint">Drag near centres to snap · arrows nudge (Shift = 10 px)</div>`;
}

function buildProps() {
  const box = $("#props");
  const f = S.selected;
  if (!f) { box.innerHTML = `<p class="none">Select a field on the design (or in the list above) to edit it here.</p>`; return; }

  if (f.type === "photo") {
    box.innerHTML = `
      <div class="secLabel">Data</div>
      <label>Excel column with the photo file name
        <select id="pColumn">${colOptionsHTML("photo", f.column)}</select>
      </label>
      <div class="secLabel">Size &amp; fit</div>
      <div class="row2">
        <label>Width (px)<input type="number" id="pW" min="4" value="${f.width}"></label>
        <label>Height (px)<input type="number" id="pH" min="4" value="${f.height}"></label>
      </div>
      <label>How the photo fills the box
        <select id="pFit">
          <option value="fill"${f.fit === "fill" ? " selected" : ""}>Fill — cover the box, crop edges</option>
          <option value="contain"${f.fit === "contain" ? " selected" : ""}>Fit — show whole photo</option>
        </select>
      </label>
      <div class="secLabel">Shape &amp; background</div>
      <div class="shapeRow" id="pShape">
        ${seg([["rect", "▭ Rect"], ["round", "▢ Rounded"], ["circle", "◯ Circle"]], f.shape || "rect")}
      </div>
      <div class="row2" id="pRadiusRow" ${f.shape === "round" ? "" : "hidden"}>
        <label>Radius (px)<input type="number" id="pRadius" min="0" max="${Math.floor(Math.min(f.width, f.height) / 2)}" value="${f.radius || 0}"></label>
      </div>
      <label class="chk"><input type="checkbox" id="pBgRemove" ${f.bg_remove ? "checked" : ""}> ✂ Remove photo background (makes white/solid backdrops transparent)</label>
      <div id="pTolRow" ${f.bg_remove ? "" : "hidden"}>
        <label>Removal strength: <b id="pTolVal">${f.bg_tol != null ? f.bg_tol : 30}</b>
          <input type="range" id="pTol" min="5" max="110" value="${f.bg_tol != null ? f.bg_tol : 30}">
        </label>
        <div class="alignHint">Low = strict, keeps even faint colours. High = aggressive, may eat similar subject colours.</div>
      </div>
      <div class="secLabel">Frame</div>
      <div class="row2">
        <label>Border (px)<input type="number" id="pBorder" min="0" value="${f.border}"></label>
        <label>Border colour<input type="color" id="pBColor" value="${esc(f.border_color)}"></label>
      </div>
      ${alignRowHTML()}
      <div class="delRow"><button class="btn danger" id="pDelete">🗑 Delete photo box</button></div>`;
  } else {
    box.innerHTML = `
      <div class="secLabel">Data</div>
      <label>Excel column (or “custom text”)
        <select id="pColumn">${colOptionsHTML("text", f.column)}</select>
      </label>
      <div class="secLabel">Font</div>
      ${fontPickerHTML(f.font || "")}
      <div class="row2" style="margin-top:9px">
        <label>Size (px)<input type="number" id="pSize" min="6" value="${f.size}"></label>
        <label>Colour<input type="color" id="pColor" value="${esc(f.color)}"></label>
      </div>
      <div class="secLabel">Text</div>
      <label>How the text sits on its X point
        <div class="segRow" id="pAlign">${seg([["left", "◀ grows right"], ["center", "◀— centered"], ["right", "grows left ▶"]], f.align)}</div>
      </label>
      <label>How the text sits on its Y point
        <div class="segRow" id="pVAlign">${seg([["top", "▲ above"], ["center", "centered"], ["bottom", "▼ below"]], f.valign)}</div>
      </label>
      <div class="secLabel">Position &amp; align</div>
      <div class="row2">
        <label>X (px)<input type="number" id="pX" value="${f.x}"></label>
        <label>Y (px)<input type="number" id="pY" value="${f.y}"></label>
      </div>
      <label>Align on the design
        <div class="alignGrid" id="pAlignGrid">
          ${ALIGN_BUTTONS.map(([v, ic]) =>
            `<button type="button" data-v="${v}" title="${{
               left:"Left edge", hcenter:"Horizontal centre", right:"Right edge",
               top:"Top edge", vcenter:"Vertical centre", bottom:"Bottom edge"
             }[v]}">${ic}</button>`).join("")}
        </div>
      </label>
      <div class="alignHint">Boxes in dashed outline = exactly where text will print · snap while dragging</div>
      <div class="secLabel">Text options</div>
      <label>Wrap width (px · 0 = single line)<input type="number" id="pWrap" min="0" value="${f.wrap_width}"></label>
      <label>If the column is a date, show it as
        <select id="pDate">${datefmtOptionsHTML(f.datefmt)}</select>
      </label>
      <label>Fixed text before the value<input type="text" id="pPrefix" placeholder="e.g. This is to certify that " value="${esc(f.prefix)}"></label>
      <label>Fixed text after the value<input type="text" id="pSuffix" placeholder="e.g. ." value="${esc(f.suffix)}"></label>
      <div class="chk"><input type="checkbox" id="pUpper" ${f.uppercase ? "checked" : ""}> Write everything in CAPITALS</div>
      <div class="delRow"><button class="btn danger" id="pDelete">🗑 Delete text field</button></div>`;
  }

  const bind = (id, ev, fn) => {
    const el = box.querySelector(id);
    if (el) el.addEventListener(ev, fn);
  };
  const touch = (after, opts = {}) => {
    if (after) after();
    syncOverlays();
    renderFieldList();
    updateDashboard();
    saveLocal();
    schedulePreview(300);
    if (f.type === "text" && !opts.noMetrics) queueMetrics(f);
  };

  bind("#pColumn", "change", (e) => { f.column = e.target.value; touch(); });
  bind("#pDelete", "click", () => deleteField(f));

  /* alignment buttons (both field types) */
  const grid = box.querySelector("#pAlignGrid");
  if (grid) grid.addEventListener("click", (e) => {
    const v = e.target.dataset && e.target.dataset.v;
    if (!v) return;
    alignField(f, v);
  });

  if (f.type === "photo") {
    bind("#pW", "input", (e) => touch(() => { f.width = Math.max(4, +e.target.value || 4); sanitizeRadiusUI(f); }));
    bind("#pH", "input", (e) => touch(() => { f.height = Math.max(4, +e.target.value || 4); sanitizeRadiusUI(f); }));
    bind("#pFit", "change", (e) => touch(() => { f.fit = e.target.value; }));
    bind("#pBorder", "input", (e) => touch(() => { f.border = Math.max(0, +e.target.value || 0); }));
    bind("#pBColor", "input", (e) => touch(() => { f.border_color = e.target.value; }));

    const shapeRow = box.querySelector("#pShape");
    shapeRow.addEventListener("click", (e) => {
      const v = e.target.dataset && e.target.dataset.v; if (!v) return;
      f.shape = v;
      box.querySelectorAll("#pShape button").forEach((b) =>
        b.classList.toggle("on", b.dataset.v === v));
      const rr = box.querySelector("#pRadiusRow");
      if (rr) rr.hidden = v !== "round";
      shapeRow.querySelectorAll("button").forEach((b) => b.classList.toggle("on", b.dataset.v === v));
      touch();
    });
    const radiusRow = box.querySelector("#pRadiusRow");
    if (radiusRow) radiusRow.hidden = f.shape !== "round";
    bind("#pRadius", "input", (e) => touch(() => { f.radius = Math.max(0, +e.target.value || 0); }));
    bind("#pBgRemove", "change", (e) => {
      f.bg_remove = e.target.checked;
      const tr = box.querySelector("#pTolRow");
      if (tr) tr.hidden = !f.bg_remove;
      touch();
    });
    bind("#pTol", "input", (e) => {
      f.bg_tol = +e.target.value;
      const lbl = box.querySelector("#pTolVal");
      if (lbl) lbl.textContent = f.bg_tol;
      touch();
    });
  } else {
    bind("#pSize", "input", (e) => touch(() => { f.size = Math.max(6, +e.target.value || 6); }));
    bind("#pColor", "input", (e) => touch(() => { f.color = e.target.value; }));
    box.querySelector("#pAlign").addEventListener("click", (e) => {
      const v = e.target.dataset && e.target.dataset.v; if (!v) return;
      f.align = v; touch(); buildProps();
    });
    box.querySelector("#pVAlign").addEventListener("click", (e) => {
      const v = e.target.dataset && e.target.dataset.v; if (!v) return;
      f.valign = v; touch(); buildProps();
    });
    bind("#pWrap", "input", (e) => touch(() => { f.wrap_width = Math.max(0, +e.target.value || 0); }));
    bind("#pDate", "change", (e) => touch(() => { f.datefmt = e.target.value; }));
    bind("#pPrefix", "input", (e) => touch(() => { f.prefix = e.target.value; }));
    bind("#pSuffix", "input", (e) => touch(() => { f.suffix = e.target.value; }));
    bind("#pUpper", "change", (e) => touch(() => { f.uppercase = e.target.checked; }));

    /* font picker wiring */
    const search = box.querySelector("#pFontSearch");
    if (search) {
      search.addEventListener("input", (e) => {
        S.fontFilter = e.target.value;
        rerenderFontList(f.font || "");
        // keep focus in the search box after re-render
        const s2 = box.querySelector("#pFontSearch");
        if (s2) { s2.focus(); s2.setSelectionRange(s2.value.length, s2.value.length); }
      });
    }
    const list = box.querySelector("#pFontList");
    if (list) list.addEventListener("click", (e) => {
      const item = e.target.closest(".fItem");
      if (!item) return;
      f.font = item.dataset.label || "";
      touch();
      // re-mark selection without rebuilding (keeps scroll position)
      list.querySelectorAll(".fItem").forEach((i2) =>
        i2.classList.toggle("sel", i2.dataset.label === f.font));
    });
    bindFontListScroll(f.font || "");
    const imp = box.querySelector("#pFontImport");
    if (imp) imp.addEventListener("click", () => openFontImport());
  }
  bind("#pX", "change", (e) => touch(() => { f.x = Math.round(+e.target.value || 0); }));
  bind("#pY", "change", (e) => touch(() => { f.y = Math.round(+e.target.value || 0); }));

  if (f.type === "text") queueMetrics(f);
}

function sanitizeRadiusUI(f) {
  const inp = $("#pRadius");
  if (inp) inp.max = Math.floor(Math.min(f.width, f.height) / 2);
}

let fontImportInput = null;

async function pickFontFiles() {
  if (!fontImportInput) {
    fontImportInput = document.createElement("input");
    fontImportInput.type = "file";
    fontImportInput.accept = ".ttf,.otf,.ttc";
    fontImportInput.multiple = true;
    fontImportInput.hidden = true;
    document.body.appendChild(fontImportInput);
    fontImportInput.addEventListener("change", () => uploadFonts(fontImportInput.files));
  }
  fontImportInput.click();
}

async function uploadFonts(fileList) {
  const files = [...fileList].filter((x) => /\.(ttf|otf|ttc)$/i.test(x.name));
  if (!files.length) { toast("Choose .ttf, .otf or .ttc files.", "warn"); return; }
  const fd = new FormData();
  for (const file of files) fd.append("file", file);
  const res = await fetch("/api/import-fonts", { method: "POST", body: fd });
  const j = await res.json().catch(() => ({ error: "Import failed" }));
  if (j.error) { toast(j.error, "error", 6000); return; }
  afterFontImport(j);
}

async function importFontFromUrl() {
  const urlEl = $("#fontUrl");
  const btn = $("#btnFontUrlFetch");
  const url = (urlEl && urlEl.value || "").trim();
  if (!url) { toast("Paste a Google Fonts link or a direct .ttf link first.", "warn"); return; }
  if (btn) { btn.disabled = true; btn.textContent = "⤓ Importing…"; }
  try {
    const res = await fetch("/api/import-font-url", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });
    const j = await res.json().catch(() => ({ error: "Import failed" }));
    if (j.error) { toast(j.error, "error", 7000); return; }
    afterFontImport(j);
    closeFontImport();
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = "⤓ Download font"; }
  }
}

function afterFontImport(j) {
  S.fonts = j.fonts || S.fonts;
  toast(`Installed ${j.added.length} font${j.added.length === 1 ? "" : "s"}: ${j.added.join(", ")}`, "ok", 7000);
  if (S.selected && S.selected.type === "text") buildProps();   // refresh previews
}

function openFontImport() {
  const m = $("#fontModal");
  if (!m) { pickFontFiles(); return; }
  m.classList.remove("hidden");
  const u = $("#fontUrl");
  if (u) { u.value = ""; setTimeout(() => u.focus(), 60); }
}

function closeFontImport() {
  $("#fontModal")?.classList.add("hidden");
}

function fillPropsXY(f) {
  const x = $("#pX"), y = $("#pY");
  if (x && S.selected === f && document.activeElement !== x) x.value = f.x;
  if (y && S.selected === f && document.activeElement !== y) y.value = f.y;
}

/* ------------------------------------------------------------------ uploads */

function bindDrop(zoneSel, inputSel, cb) {
  const zone = $(zoneSel); const input = $(inputSel);
  zone.addEventListener("click", () => input.click());
  zone.addEventListener("dragover", (e) => { e.preventDefault(); zone.classList.add("over"); });
  zone.addEventListener("dragleave", () => zone.classList.remove("over"));
  zone.addEventListener("drop", (e) => {
    e.preventDefault(); zone.classList.remove("over");
    if (e.dataTransfer.files[0]) cb(e.dataTransfer.files[0]);
  });
  input.addEventListener("change", () => {
    if (input.files[0]) { cb(input.files[0]); input.value = ""; }
  });
}

async function uploadFile(url, file) {
  const fd = new FormData();
  fd.append("file", file);
  const res = await fetch(url, { method: "POST", body: fd });
  const j = await res.json().catch(() => ({ error: "Upload failed" }));
  if (j.error) { toast(j.error, "error", 6000); return null; }
  return j;
}

async function onTemplate(file) {
  const res = await uploadFile("/api/upload-template", file);
  if (!res) return;
  S.config.template = res;
  S.config.fields = [];        // new design → old positions make no sense
  S.selected = null;
  S.metrics = {};
  toast("Design loaded — now add fields for the changing data (step 3).", "ok");
  await afterConfigChange();
}

async function onExcel(file) {
  const res = await uploadFile("/api/upload-excel", file);
  if (!res) return;
  S.config.excel = res;
  S.metrics = {};              // sample values change → re-measure
  autoPickFilenameColumn();
  toast(`${res.row_count} rows loaded · columns: ${res.columns.slice(0, 4).join(", ")}${res.columns.length > 4 ? " …" : ""}`, "ok");
  await afterConfigChange();
}

function autoPickFilenameColumn() {
  if (!S.config.excel) return;
  if (!S.config.filename_column || !columns().includes(S.config.filename_column)) {
    const guess = columns().find((c) => /name|roll|id|reg/i.test(c));
    S.config.filename_column = guess || columns()[0] || "";
  }
}

async function afterConfigChange() {
  renderFieldList();
  buildProps();
  populateExport();
  updateExcelInfo();
  updateDashboard();
  await setCanvasImage();
  saveLocal();
  schedulePreview(300);
}

/* --------------------------------------------------------------- export UI */

function populateExport() {
  const sel = $("#selFname");
  const cur = S.config.filename_column || "";
  sel.innerHTML = `<option value=""${!cur ? " selected" : ""}>row number (auto)</option>` +
    columns().map((c) => `<option value="${esc(c)}"${c === cur ? " selected" : ""}>${esc(c)}</option>`).join("");
  $("#inPrefix").value = S.config.file_prefix || "";
  $("#selPdf").value = S.config.pdf_mode || "fit";
  $("#photosFolder").value = S.config.photos_folder || "";
}

function updateExcelInfo() {
  const x = xcl();
  $("#previewRow").max = x ? x.row_count : 1;
  $("#rowCountText").textContent = x ? x.row_count : "–";
  const info = $("#excelInfo");
  if (x) {
    info.innerHTML = `<b>${esc(x.name)}</b> — ${x.row_count} rows.<br>Columns: ${x.columns.map(esc).join(", ")}.<br><a href="/api/sample-excel">⬇ Get a sample Excel</a>`;
  }
}

/* ---------------------------------------------------------------- preview */

function schedulePreview(delay = 500) {
  if (!$("#autoPrev").checked) return;
  clearTimeout(prevTimer);
  prevTimer = setTimeout(refreshPreview, delay);
}

function currentRow() {
  const max = (xcl() && xcl().row_count) || 1;
  return Math.min(Math.max(1, Math.round(+$("#previewRow").value || 1)), max);
}

async function refreshPreview() {
  if (!tpl() || !xcl()) return;
  const token = ++prevSeq;
  $("#previewRow").value = currentRow();
  const row = currentRow() - 1;
  try {
    const res = await fetch("/api/preview?row=" + row, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(S.config),
    });
    if (token !== prevSeq) return;
    if (!res.ok) {
      const j = await res.json().catch(() => null);
      $("#prevImg").hidden = true;
      $("#prevEmpty").hidden = false;
      $("#prevEmpty").innerHTML = esc((j && j.error) || "Preview failed.");
      return;
    }
    const warn = res.headers.get("x-generation-warnings");
    if (warn) toast("Preview note: " + warn, "warn", 8000);
    const blob = await res.blob();
    if (token !== prevSeq) return;
    if (prevURL) URL.revokeObjectURL(prevURL);
    prevURL = URL.createObjectURL(blob);
    const img = $("#prevImg");
    img.src = prevURL; img.hidden = false;
    $("#prevEmpty").hidden = true;
  } catch (e) {
    /* transient network error — ignore */
  }
}

function rowShift(delta) {
  if (!xcl()) return;
  const v = Math.min(
    Math.max(1, currentRow() + delta),
    (xcl() && xcl().row_count) || 1,
  );
  $("#previewRow").value = v;
  if (S.selected && S.selected.type === "text") queueMetrics(S.selected);
  refreshPreview();
}

/* --------------------------------------------------------------- generate */

async function generate() {
  if (generating) { toast("Already generating… watch the bar at the bottom.", "warn"); return; }
  if (!tpl()) { toast("Step missing: upload a design image first.", "warn", 6000); scrollStep("#cardTemplate"); return; }
  if (!xcl()) { toast("Step missing: upload the Excel list first.", "warn", 6000); scrollStep("#cardExcel"); return; }
  if (!S.config.fields.length) { toast("Step missing: place at least one field on the design.", "warn", 6000); scrollStep("#cardFields"); return; }
  const res = await fetch("/api/generate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(S.config),
  });
  const j = await res.json().catch(() => ({ error: "Request failed" }));
  if (j.error) { toast(j.error, "error", 6000); return; }
  startPoll(j.job);
}

function scrollStep(sel) {
  const el = $(sel);
  if (el) el.scrollIntoView({ block: "center", behavior: "smooth" });
}

function startPoll(id) {
  generating = true;
  $("#progWrap").hidden = false;
  $("#progLabel").textContent = "⏳ Generating…";
  $("#progBar").style.width = "0%";
  $("#progResult").innerHTML = "";
  const bar = $("#progBar"); const text = $("#progText"); const label = $("#progLabel");
  text.className = ""; text.textContent = "starting…";
  pollT = setInterval(async () => {
    let st;
    try { st = await (await fetch("/api/status/" + id)).json(); }
    catch (_) { return; }
    const pct = st.total ? Math.round((st.done / st.total) * 100) : 0;
    bar.style.width = pct + "%";
    text.textContent = st.total ? `${st.done} / ${st.total}  ·  ${st.current || ""}` : "preparing…";
    if (st.status && st.status !== "running") {
      clearInterval(pollT); generating = false;
      finishPoll(st, id, label, text);
    }
  }, 700);
}

function finishPoll(st, id, label, text) {
  const res = $("#progResult");
  if (st.status === "done") {
    label.textContent = "✅ Done!";
    text.className = "done";
    let msg = `All ${st.done} file${st.done === 1 ? "" : "s"} generated`;
    if (st.errors && st.errors.length) msg += ` · ${st.errors.length} warning${st.errors.length === 1 ? "" : "s"}`;
    text.textContent = msg;
    const zipBtn = st.zip ? `<a class="btn primary" href="/api/download/${esc(id)}">⬇ Download ZIP</a>` : "";
    const owner = (st.output || "").split("/").filter(Boolean).pop();
    const errBtn = (st.errors && st.errors.length)
      ? `<button class="btn mini" id="btnErrList">see warnings</button>` : "";
    res.innerHTML = `folder: <b>${esc(owner)}</b> ${zipBtn} ${errBtn}`;
    const eb = $("#btnErrList");
    if (eb) {
      eb.onclick = () => showWarnings(st.errors);
      if (st.errors.length) showWarnings(st.errors);
    }
  } else {
    label.textContent = "❌ Generation failed";
    text.className = "err";
    text.textContent = st.error || "unknown error";
  }
}

/* ------------------------------------------------------------ warnings UI */

function showWarnings(errors) {
  const modal = $("#errModal");
  const list = $("#errListBody");
  if (!modal || !list) { alert((errors || []).map((e) => `Row ${e.row}: ${e.message}`).join("\n")); return; }
  list.innerHTML = (errors && errors.length)
    ? errors.map((e) => `<div class="eRow"><b>Row ${esc(e.row)}</b><span>${esc(e.message)}</span></div>`).join("")
    : `<div class="eRow"><span>No warnings — every row rendered cleanly.</span></div>`;
  modal.classList.remove("hidden");
}

/* ---------------------------------------------------------------- Projects */

async function openProjectsModal() {
  $("#modal").classList.remove("hidden");
  const box = $("#projectList");
  box.innerHTML = "<p style='color:var(--muted);font-size:12.5px'>Loading…</p>";
  const j = await (await fetch("/api/projects")).json();
  if (!j.projects.length) {
    box.innerHTML = "<p style='color:var(--muted);font-size:12.5px'>No saved projects yet.<br>Use 💾 Save to keep your layout for next time.</p>";
    return;
  }
  box.innerHTML = "";
  for (const p of j.projects) {
    const row = document.createElement("div");
    row.className = "projRow";
    row.innerHTML = `<b>${esc(p.name)}</b><span class="meta">${humanSize(p.size)}</span>
      <button class="btn mini primary" data-load>Open</button>
      <button class="btn mini ghost" data-del>✕</button>`;
    row.querySelector("[data-load]").onclick = () => loadProject(p.name);
    row.querySelector("[data-del]").onclick = async () => {
      if (!confirm("Delete project “" + p.name + "”?")) return;
      await fetch("/api/projects/delete", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: p.name }),
      });
      openProjectsModal();
    };
    box.appendChild(row);
  }
}

async function loadProject(name) {
  const res = await fetch("/api/projects/load?name=" + encodeURIComponent(name));
  const cfg = await res.json().catch(() => ({ error: "Not found" }));
  if (cfg.error) { toast(cfg.error, "error"); return; }
  $("#modal").classList.add("hidden");
  await applyConfig(cfg);
  toast("Project “" + name + "” opened.", "ok");
}

async function saveProject() {
  const name = S.config.name || window.prompt("Name this project (e.g. IEEE Membership Cards 2026):", "My project");
  if (!name) return;
  S.config.name = name;
  saveLocal();
  const res = await fetch("/api/projects/save", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, config: S.config }),
  });
  const j = await res.json().catch(() => ({ error: "save failed" }));
  if (j.error) { toast(j.error, "error"); return; }
  toast("Project saved: " + j.name, "ok");
}

async function applyConfig(cfg) {
  S.config = { ...freshConfig(), ...cfg };
  S.selected = null;
  S.metrics = {};
  clearPreview();
  await afterConfigChange();
}

function clearPreview() {
  const img = $("#prevImg");
  img.hidden = true; img.removeAttribute("src");
  $("#prevEmpty").hidden = false;
}

/* ------------------------------------------------------------ new / demo */

function newProject() {
  if (!confirm("Start a new empty project? Save your current work first if needed.")) return;
  localStorage.removeItem(LS_KEY);
  applyConfig(freshConfig());
  toast("New project started. Upload your design to begin.", "ok");
}

async function loadDemo() {
  const cfg = await (await fetch("/api/demo")).json();
  await applyConfig(cfg);
  saveLocal();
  toast("Demo loaded — the preview shows row 1. Press ⚡ Generate all to see the full output!", "ok", 7000);
}

/* ----------------------------------------------------------- welcome/help */

function openWelcome() { $("#welcome").classList.remove("hidden"); }

function closeWelcome(markSeen) {
  $("#welcome").classList.add("hidden");
  if (markSeen) {
    try { localStorage.setItem(LS_SEEN, "1"); } catch (_) {}
  }
}

function maybeShowWelcome() {
  let seen = false;
  try { seen = localStorage.getItem(LS_SEEN) === "1"; } catch (_) {}
  if (!seen) openWelcome();
}

/* ------------------------------------------------------------ global init */

function bindStatic() {
  bindDrop("#dropTemplate", "#fileTemplate", onTemplate);
  bindDrop("#dropExcel", "#fileExcel", onExcel);

  $("#btnAddText").addEventListener("click", () => setMode("text"));
  $("#btnAddPhoto").addEventListener("click", () => setMode("photo"));

  $("#imgBox").addEventListener("pointerdown", (e) => {
    if (S.mode) {
      const rect = $("#imgBox").getBoundingClientRect();
      const st = tpl();
      const x = ((e.clientX - rect.left) / rect.width) * st.width;
      const y = ((e.clientY - rect.top) / rect.height) * st.height;
      addField(S.mode, x, y);
      e.preventDefault(); e.stopPropagation();
      return;
    }
    select(null);
  });

  $("#btnGenerate").addEventListener("click", generate);
  $("#btnGenerate2").addEventListener("click", generate);
  $("#btnDemo").addEventListener("click", loadDemo);
  $("#btnHelp").addEventListener("click", openWelcome);
  $("#btnNew").addEventListener("click", newProject);
  $("#btnSave").addEventListener("click", saveProject);
  $("#btnProjects").addEventListener("click", openProjectsModal);
  $("#btnCloseModal").addEventListener("click", () => $("#modal").classList.add("hidden"));
  $("#modal").addEventListener("click", (e) => { if (e.target.id === "modal") $("#modal").classList.add("hidden"); });
  $("#btnCloseErr").addEventListener("click", () => $("#errModal").classList.add("hidden"));
  $("#errModal").addEventListener("click", (e) => { if (e.target.id === "errModal") $("#errModal").classList.add("hidden"); });
  $("#btnCloseFont").addEventListener("click", closeFontImport);
  $("#fontModal").addEventListener("click", (e) => { if (e.target.id === "fontModal") closeFontImport(); });
  $("#btnFontUrlFetch").addEventListener("click", importFontFromUrl);
  $("#fontUrl").addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); importFontFromUrl(); }
  });
  $("#btnFontFiles").addEventListener("click", () => { closeFontImport(); pickFontFiles(); });
  $$("#fontModal .chip").forEach((c) => c.addEventListener("click", () => {
    const u = $("#fontUrl");
    u.value = c.dataset.url;
    u.focus();
  }));
  $("#heroUploadDesign").addEventListener("click", () => $("#fileTemplate").click());
  $("#heroDemo").addEventListener("click", () => { loadDemo(); closeWelcome(true); });

  $("#btnWelcomeDemo").addEventListener("click", async () => {
    closeWelcome(true);
    await loadDemo();
  });
  $("#btnWelcomeStart").addEventListener("click", () => { closeWelcome(true); $("#fileTemplate").click(); });
  $("#welcome").addEventListener("click", (e) => { if (e.target.id === "welcome") closeWelcome(false); });

  $("#photosFolder").addEventListener("input", (e) => {
    S.config.photos_folder = e.target.value.trim();
    updateDashboard();
    saveLocal();
  });
  $("#btnBrowsePhotos").addEventListener("click", async () => {
    if (window.autoCert && window.autoCert.pickPhotosFolder) {
      const dir = await window.autoCert.pickPhotosFolder();
      if (dir) {
        $("#photosFolder").value = dir;
        S.config.photos_folder = dir;
        updateDashboard();
        saveLocal();
      }
    } else {
      toast("Folder picking needs the desktop app. In browser mode, paste the path (Finder → ⌥Option → “Copy as Pathname”).", "info", 7000);
    }
  });

  $("#selFname").addEventListener("change", (e) => { S.config.filename_column = e.target.value; saveLocal(); });
  $("#inPrefix").addEventListener("input", (e) => { S.config.file_prefix = e.target.value; saveLocal(); });
  $("#selPdf").addEventListener("change", (e) => { S.config.pdf_mode = e.target.value; saveLocal(); });

  $("#previewRow").addEventListener("change", () => refreshPreview());
  $("#rowPrev").addEventListener("click", () => rowShift(-1));
  $("#rowNext").addEventListener("click", () => rowShift(1));
  $("#btnRefreshPrev").addEventListener("click", refreshPreview);
  $("#autoPrev").addEventListener("change", () => { if ($("#autoPrev").checked) refreshPreview(); });

  window.addEventListener("resize", () => { syncOverlays(); });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      if (!$("#fontModal").classList.contains("hidden")) { $("#fontModal").classList.add("hidden"); return; }
      if (!$("#errModal").classList.contains("hidden")) { $("#errModal").classList.add("hidden"); return; }
      if (!$("#modal").classList.contains("hidden")) { $("#modal").classList.add("hidden"); return; }
      if (!$("#welcome").classList.contains("hidden")) { closeWelcome(false); return; }
      if (!(document.activeElement &&
            ["INPUT", "SELECT", "TEXTAREA"].includes(document.activeElement.tagName))) {
        setMode(null); select(null);
      }
      return;
    }
    const tag = document.activeElement && document.activeElement.tagName;
    if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA" || e.metaKey || e.ctrlKey) return;
    const f = S.selected;
    if (!f) return;
    if (e.key === "Delete" || e.key === "Backspace") { e.preventDefault(); deleteField(f); return; }
    const step = e.shiftKey ? 10 : 1;
    const maxX = tpl() ? tpl().width : Infinity;
    const maxY = tpl() ? tpl().height : Infinity;
    let moved = false;
    switch (e.key) {
      case "ArrowLeft": f.x = Math.max(0, f.x - step); moved = true; break;
      case "ArrowRight": f.x = Math.min(maxX, f.x + step); moved = true; break;
      case "ArrowUp": f.y = Math.max(0, f.y - step); moved = true; break;
      case "ArrowDown": f.y = Math.min(maxY, f.y + step); moved = true; break;
    }
    if (moved) {
      e.preventDefault();
      fillPropsXY(f);
      syncOverlays();
      saveLocal();
      schedulePreview(400);
    }
  });
}

window.addEventListener("DOMContentLoaded", async () => {
  bindStatic();
  try {
    const j = await (await fetch("/api/fonts")).json();
    S.fonts = j.fonts || [];
  } catch (_) { S.fonts = []; }

  S.config = freshConfig();
  const raw = localStorage.getItem(LS_KEY);
  if (raw) {
    try { await applyConfig(JSON.parse(raw)); }
    catch (_) { await afterConfigChange(); }
  } else {
    await afterConfigChange();
  }
  maybeShowWelcome();
});
