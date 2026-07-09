/* CodeBread interactive graph UI — vanilla JS + SVG, no dependencies. */
(function () {
"use strict";

const LAYER_COLOR = {
  frontend: "#0284c7", backend: "#0d9488", database: "#8b5cf6",
  config: "#d97706", unknown: "#6678d0",
};
const LAYER_LABEL = {
  frontend: "Frontend", backend: "Backend", database: "Database",
  config: "Config", unknown: "Unclassified",
};
const SVGNS = "http://www.w3.org/2000/svg";

/* ---------------- state ---------------- */
const S = {
  data: null,
  nodesById: new Map(),
  outEdges: new Map(),     // id -> [edge]
  inEdges: new Map(),      // id -> [edge]
  fileFns: new Map(),      // file path -> [fn node ids]
  visible: new Set(),      // node ids currently on canvas
  expanded: new Set(),     // file ids whose functions are shown
  pos: new Map(),          // id -> {x,y,vx,vy,fx,fy}
  selected: null,
  litNodes: new Set(),
  litEdges: new Set(),
  filter: "all",
  mode: "orbit",           // "orbit" (files float, functions ring around them) |
                            // "free" (plain force layout)
  view: "chart",           // "chart" (graph) | "ide" (full code editor)
  ideFile: null,           // file currently open in IDE mode
  tf: { x: 0, y: 0, k: 1 },
  alpha: 0,
  elNodes: new Map(),      // id -> <g>
  elEdges: new Map(),      // edge key -> {vis, hit}
  drawnEdges: [],          // [{edge, key}] currently in DOM
  drag: null,
  searchSel: -1,
  crumbs: [],               // navigation history (node ids)
  crumbIdx: -1,
  navList: [],              // neighbor cycle list for ArrowLeft/ArrowRight
  navIdx: -1,
  mmT: null,                // minimap world->minimap transform
  mmDots: new Map(),
  mmViewportEl: null,
  focusMode: false,         // when on, picking a file in the Explorer
                             // spotlights just that file instead of adding to the view
};

const $ = (id) => document.getElementById(id);
const svg = $("graph"), viewport = $("viewport");
const edgesG = $("edges-g"), nodesG = $("nodes-g");

/* ---------------- boot ---------------- */
function boot(data) {
  S.data = data;
  indexData();
  renderHeader();
  renderLegend();
  renderTree();
  initialVisible();
  layoutInitial();
  rebuild();
  runTicks(260);
  fitView(0.82);
  startLoop();
  bindUI();
  bindMinimap();
  maybeShowOnboarding();
  setTimeout(() => $("hint").classList.add("faded"), 6000);
}

if (window.CODEBREAD_DATA) {
  boot(window.CODEBREAD_DATA);
} else {
  fetch("data.json").then(r => r.json()).then(boot)
    .catch(err => {
      document.body.innerHTML =
        "<p style='padding:40px;font-family:monospace'>Failed to load " +
        "data.json — " + err + "</p>";
    });
}

/* ---------------- indexing ---------------- */
function indexData() {
  for (const n of S.data.nodes) {
    S.nodesById.set(n.id, n);
    if ((n.kind === "function" || n.kind === "method") && n.file) {
      if (!S.fileFns.has(n.file)) S.fileFns.set(n.file, []);
      S.fileFns.get(n.file).push(n.id);
    }
  }
  for (const e of S.data.edges) {
    if (!S.nodesById.has(e.source) || !S.nodesById.has(e.target)) continue;
    if (!S.outEdges.has(e.source)) S.outEdges.set(e.source, []);
    if (!S.inEdges.has(e.target)) S.inEdges.set(e.target, []);
    S.outEdges.get(e.source).push(e);
    S.inEdges.get(e.target).push(e);
  }
}
const edgeKey = (e) => e.source + "→" + e.target + "·" + e.kind;

function nodeLayer(n) {
  return n.kind === "table" ? "database" : (n.layer || "unknown");
}
function passesFilter(n) {
  return S.filter === "all" || nodeLayer(n) === S.filter;
}

/* ---------------- header / legend / warnings ---------------- */
function renderHeader() {
  $("project-name").textContent = "· " + (S.data.meta?.name || "");
  document.title = "CodeBread — " + (S.data.meta?.name || "codebase map");
  const st = S.data.stats || {};
  const stat = (label, v) => `<span class="stat"><b>${v ?? 0}</b> ${label}</span>`;
  let html = stat("files", st.files) + stat("functions", st.functions) +
             stat("tables", st.tables) + stat("connections", st.connections);
  $("stats").innerHTML = html;
  if (st.warnings) {
    const b = document.createElement("button");
    b.className = "stat warn-btn";
    b.innerHTML = `⚠ <b>${st.warnings}</b> warnings`;
    b.onclick = toggleWarnings;
    $("stats").appendChild(b);
  }
  if (st.orphans || st.cycles) {
    const bits = [];
    if (st.orphans) bits.push(`${st.orphans} orphan${st.orphans === 1 ? "" : "s"}`);
    if (st.cycles) bits.push(`${st.cycles} cycle${st.cycles === 1 ? "" : "s"}`);
    const b = document.createElement("button");
    b.className = "stat warn-btn insight-btn";
    b.innerHTML = `◎ <b>${bits.join(" · ")}</b>`;
    b.onclick = toggleInsights;
    $("stats").appendChild(b);
  }
}

function toggleInsights() {
  const p = $("insights-panel");
  if (!p.classList.contains("hidden")) { p.classList.add("hidden"); return; }
  const st = S.data.stats || {};
  $("ip-orphan-count").textContent = `(${st.orphans || 0})`;
  $("ip-cycle-count").textContent = `(${st.cycles || 0})`;

  const orphanList = $("ip-orphans-list");
  orphanList.innerHTML = "";
  const orphans = S.data.nodes.filter(n => n.orphan);
  if (!orphans.length) orphanList.innerHTML = "<div class='wp-item'>None detected.</div>";
  for (const n of orphans.slice(0, 300)) {
    const d = document.createElement("div");
    d.className = "wp-item ip-clickable";
    d.innerHTML = `<div class="wp-path">${esc(n.file || "")}</div>` +
                  `<div class="wp-msg">${esc(n.label)}() — no detected callers</div>`;
    d.onclick = () => { p.classList.add("hidden"); jumpTo(n.id); };
    orphanList.appendChild(d);
  }

  const cycleList = $("ip-cycles-list");
  cycleList.innerHTML = "";
  const cycles = S.data.cycles || [];
  if (!cycles.length) cycleList.innerHTML = "<div class='wp-item'>None detected.</div>";
  for (const c of cycles.slice(0, 100)) {
    const d = document.createElement("div");
    d.className = "wp-item ip-clickable";
    const chain = [...c.labels, c.labels[0]].map(esc).join(" → ");
    d.innerHTML = `<div class="wp-msg">${chain}</div>`;
    d.onclick = () => { p.classList.add("hidden"); jumpTo(c.nodes[0]); };
    cycleList.appendChild(d);
  }
  p.classList.remove("hidden");
}

function toggleWarnings() {
  const p = $("warnings-panel");
  if (!p.classList.contains("hidden")) { p.classList.add("hidden"); return; }
  const list = $("warnings-list");
  list.innerHTML = "";
  const all = [...(S.data.warnings || [])];
  for (const n of S.data.nodes) {
    if (n.kind === "file" && n.warnings)
      for (const w of n.warnings) all.push({ path: n.file, message: w });
  }
  if (!all.length) list.innerHTML = "<div class='wp-item'>No warnings.</div>";
  for (const w of all.slice(0, 400)) {
    const d = document.createElement("div");
    d.className = "wp-item";
    d.innerHTML = `<div class="wp-path">${esc(w.path)}</div>` +
                  `<div class="wp-msg">${esc(w.message)}</div>`;
    list.appendChild(d);
  }
  p.classList.remove("hidden");
}

function renderLegend() {
  const rows = [
    ["frontend", "Frontend"], ["backend", "Backend"],
    ["database", "Database / tables"], ["config", "Config"],
    ["unknown", "Unclassified"],
  ].map(([k, label]) =>
    `<div class="lg-row"><span class="lg-dot" style="background:${LAYER_COLOR[k]}"></span>${label}</div>`);
  rows.push(`<div class="lg-row" style="margin-top:3px;color:var(--ink-3)">─ call · api · db · include · page</div>`);
  $("legend").innerHTML = rows.join("");
}

/* ---------------- sidebar tree ---------------- */
function renderTree() {
  const root = S.data.tree;
  const el = buildTreeNode(root, 0);
  el.classList.add("open");
  $("tree").innerHTML = "";
  $("tree").appendChild(el);
}

function buildTreeNode(node, depth) {
  const isDir = node.type === "dir";
  const wrap = document.createElement("div");
  wrap.className = "tnode " + (isDir ? "dir" : "file");
  const row = document.createElement("div");
  row.className = "trow";
  row.dataset.path = node.path || "";

  const caret = document.createElement("span");
  caret.className = "tcaret";
  caret.textContent = isDir ? "▶" : "";
  row.appendChild(caret);

  const dot = document.createElement("span");
  dot.className = "tdot";
  dot.style.background = LAYER_COLOR[node.layer] || "rgba(103,232,249,0.18)";
  row.appendChild(dot);

  const name = document.createElement("span");
  name.className = "tname";
  name.textContent = node.name;
  row.appendChild(name);

  if (node.warning) {
    const w = document.createElement("span");
    w.className = "twarn";
    w.title = "This entry has a warning — see ⚠ in the header.";
    w.textContent = "⚠";
    row.appendChild(w);
  }
  if (!isDir && node.nFunctions) {
    const c = document.createElement("span");
    c.className = "tcount";
    c.textContent = node.nFunctions;
    row.appendChild(c);
  }
  wrap.appendChild(row);

  if (isDir) {
    const kids = document.createElement("div");
    kids.className = "tchildren";
    for (const ch of node.children || []) kids.appendChild(buildTreeNode(ch, depth + 1));
    wrap.appendChild(kids);
    row.onclick = () => wrap.classList.toggle("open");
    if (depth < 1) wrap.classList.add("open");
  } else {
    row.onclick = () => {
      document.querySelectorAll(".trow.selected").forEach(x => x.classList.remove("selected"));
      row.classList.add("selected");
      if (!S.nodesById.has(node.path)) return;
      if (S.view === "ide" && S.nodesById.get(node.path)?.source) {
        openIde(node.path);        // IDE mode: open the file like an editor
      } else if (S.focusMode) {
        spotlightFile(node.path);  // focus mode: show just this file
      } else {
        jumpTo(node.path);         // overview mode: add to what's shown
      }
    };
  }
  return wrap;
}

/* ---------------- initial visibility & layout ---------------- */
function initialVisible() {
  const files = S.data.nodes.filter(n => n.kind === "file");
  const tables = S.data.nodes.filter(n => n.kind === "table");
  // dense codebases: start with files that actually contain code
  const interesting = files.filter(f =>
    (f.nFunctions || 0) > 0 || S.outEdges.has(f.id) || S.inEdges.has(f.id) ||
    (f.dbConfig || []).length);
  const show = (interesting.length ? interesting : files).slice(0, 400);
  for (const f of show) S.visible.add(f.id);
  for (const t of tables) S.visible.add(t.id);
}

const BAND = { frontend: 0.16, unknown: 0.38, backend: 0.55, config: 0.5, database: 0.84 };

function layoutInitial() {
  const W = 1600, H = 1100;
  let i = 0;
  for (const id of S.visible) {
    const n = S.nodesById.get(id);
    const bx = BAND[nodeLayer(n)] ?? 0.5;
    const by = nodeLayer(n) === "config" ? 0.88 : 0.18 + 0.64 * hash01(id);
    S.pos.set(id, {
      x: bx * W + (hash01(id + "x") - 0.5) * 260,
      y: by * H + (hash01(id + "y") - 0.5) * 120,
      vx: 0, vy: 0,
    });
    i++;
  }
}

function hash01(s) {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); }
  return ((h >>> 0) % 10000) / 10000;
}

function ensurePos(id, nearId) {
  if (S.pos.has(id)) return;
  const near = nearId && S.pos.get(nearId);
  const n = S.nodesById.get(id);
  const bx = BAND[nodeLayer(n)] ?? 0.5;
  const base = near || { x: bx * 1600, y: 550 };
  const a = hash01(id) * Math.PI * 2;
  S.pos.set(id, {
    x: base.x + Math.cos(a) * (60 + hash01(id + "r") * 70),
    y: base.y + Math.sin(a) * (60 + hash01(id + "r") * 70),
    vx: 0, vy: 0,
  });
}

/* ---------------- visible edge computation ---------------- */
function visibleEdges() {
  const out = [];
  for (const e of S.data.edges) {
    if (S.visible.has(e.source) && S.visible.has(e.target)) {
      const sn = S.nodesById.get(e.source), tn = S.nodesById.get(e.target);
      if (passesFilter(sn) && passesFilter(tn)) out.push(e);
    }
  }
  // synthetic containment edges: file -> its expanded functions
  for (const fid of S.expanded) {
    if (!S.visible.has(fid)) continue;
    const fnode = S.nodesById.get(fid);
    if (!passesFilter(fnode)) continue;
    for (const fnId of S.fileFns.get(fid) || []) {
      if (S.visible.has(fnId) && passesFilter(S.nodesById.get(fnId)))
        out.push({ source: fid, target: fnId, kind: "contains", label: "" });
    }
  }
  return out;
}

/* ---------------- DOM (re)build ---------------- */
function rebuild() {
  nodesG.innerHTML = ""; edgesG.innerHTML = "";
  S.elNodes.clear(); S.elEdges.clear();
  S.drawnEdges = [];

  for (const e of visibleEdges()) {
    const key = edgeKey(e);
    const vis = document.createElementNS(SVGNS, "path");
    vis.setAttribute("class", "edge k-" + e.kind + (e.cycle ? " cycle" : ""));
    const hit = document.createElementNS(SVGNS, "path");
    hit.setAttribute("class", "edge-hit");
    hit.addEventListener("mousemove", (ev) => showEdgeTooltip(e, ev));
    hit.addEventListener("mouseleave", hideTooltip);
    hit.addEventListener("contextmenu", (ev) => {
      ev.preventDefault(); ev.stopPropagation();
      onEdgeContextMenu(e, ev);
    });
    edgesG.appendChild(vis); edgesG.appendChild(hit);
    S.elEdges.set(key, { vis, hit });
    S.drawnEdges.push({ edge: e, key });
  }

  for (const id of S.visible) {
    const n = S.nodesById.get(id);
    if (!n || !passesFilter(n)) continue;
    ensurePos(id);
    const g = makeNodeEl(n);
    nodesG.appendChild(g);
    S.elNodes.set(id, g);
  }
  applyHighlight();
  updatePositions();
  renderMinimap();
  updateEmptyState();
}

function updateEmptyState() {
  const empty = $("empty-state");
  if (S.elNodes.size > 0) { empty.classList.add("hidden"); return; }
  const totalFiles = S.data.nodes.filter(n => n.kind === "file").length;
  if (totalFiles === 0) {
    $("empty-title").textContent = "Nothing to show";
    $("empty-msg").textContent = "CodeBread didn't find any scannable files in this folder.";
  } else if (S.visible.size === 0) {
    $("empty-title").textContent = "Pick a file to begin";
    $("empty-msg").textContent = "Select a file in the Explorer on the left to see its " +
      "functions and how it connects to the rest of the codebase.";
  } else {
    $("empty-title").textContent = "Nothing to show";
    $("empty-msg").textContent = "No nodes match the current layer filter — try “All”.";
  }
  empty.classList.remove("hidden");
}

function nodeSize(n) {
  const label = n.label || "?";
  if (n.kind === "file") {
    return { w: Math.max(74, label.length * 7.4 + 34), h: 30, r: 9 };
  }
  if (n.kind === "table") {
    return { w: Math.max(66, label.length * 7.2 + 40), h: 30, r: 15 };
  }
  return { w: Math.max(56, label.length * 6.6 + 26), h: 22, r: 11 };
}

function makeNodeEl(n) {
  const g = document.createElementNS(SVGNS, "g");
  g.setAttribute("class", "node k-" + n.kind);
  g.dataset.id = n.id;
  const { w, h, r } = nodeSize(n);
  const color = LAYER_COLOR[nodeLayer(n)];

  const rect = document.createElementNS(SVGNS, "rect");
  rect.setAttribute("class", "shape");
  rect.setAttribute("x", -w / 2); rect.setAttribute("y", -h / 2);
  rect.setAttribute("width", w); rect.setAttribute("height", h);
  rect.setAttribute("rx", r);
  rect.setAttribute("stroke", color);
  if (n.kind === "table") rect.setAttribute("fill", "rgba(139,92,246,0.14)");
  g.appendChild(rect);

  const dot = document.createElementNS(SVGNS, "circle");
  dot.setAttribute("class", "ldot");
  dot.setAttribute("cx", -w / 2 + 12); dot.setAttribute("cy", 0);
  dot.setAttribute("r", n.kind === "file" ? 4 : 3);
  dot.setAttribute("fill", color);
  g.appendChild(dot);

  const label = document.createElementNS(SVGNS, "text");
  label.setAttribute("x", -w / 2 + 21);
  label.setAttribute("font-size", n.kind === "file" ? "11.5" : "10.5");
  label.textContent = n.kind === "table" ? "🗃 " + n.label : n.label;
  g.appendChild(label);

  if (n.kind === "file" && n.nFunctions) {
    const c = document.createElementNS(SVGNS, "text");
    c.setAttribute("class", "badge");
    c.setAttribute("x", w / 2 - 8); c.setAttribute("text-anchor", "end");
    c.setAttribute("y", 0.5);
    c.textContent = n.nFunctions;
    g.appendChild(c);
  }
  if (n.routes && n.routes.length) {
    const rb = document.createElementNS(SVGNS, "text");
    rb.setAttribute("class", "routeb");
    rb.setAttribute("x", -w / 2 + 2); rb.setAttribute("y", -h / 2 - 6);
    rb.textContent = n.routes[0].method + " " + n.routes[0].path;
    g.appendChild(rb);
  }
  if (n.kind === "file" && n.warnings && n.warnings.length) {
    const wb = document.createElementNS(SVGNS, "text");
    wb.setAttribute("class", "warnb");
    wb.setAttribute("x", w / 2 - 2); wb.setAttribute("y", -h / 2 - 5);
    wb.setAttribute("text-anchor", "end");
    wb.textContent = "⚠";
    g.appendChild(wb);
  }
  if ((n.kind === "function" || n.kind === "method") && n.cycle) {
    const cb = document.createElementNS(SVGNS, "text");
    cb.setAttribute("class", "cycleb");
    cb.setAttribute("x", w / 2 - 2); cb.setAttribute("y", -h / 2 - 5);
    cb.setAttribute("text-anchor", "end");
    cb.textContent = "↻";
    g.appendChild(cb);
  }

  g.addEventListener("mousedown", (ev) => startDragNode(ev, n.id));
  g.addEventListener("click", (ev) => { ev.stopPropagation(); onNodeClick(n.id); });
  g.addEventListener("dblclick", (ev) => { ev.stopPropagation(); collapseFile(n.id); });
  g.addEventListener("mousemove", (ev) => showNodeTooltip(n, ev));
  g.addEventListener("mouseleave", hideTooltip);
  g.addEventListener("contextmenu", (ev) => {
    ev.preventDefault(); ev.stopPropagation();
    onNodeContextMenu(n, ev);
  });
  return g;
}

/* ---------------- interaction: reveal / select ---------------- */
function onNodeClick(id) {
  if (S.drag && S.drag.moved) return;
  const n = S.nodesById.get(id);
  if (n.kind === "file") expandFile(id);
  else revealNeighbors(id);
  select(id);
}

function expandFile(fileId) {
  const fns = S.fileFns.get(fileId) || [];
  const wasExpanded = S.expanded.has(fileId);
  if (!wasExpanded && fns.length) {
    S.expanded.add(fileId);
    for (const fnId of fns) { S.visible.add(fnId); ensurePos(fnId, fileId); }
  }
  revealNeighbors(fileId);
  rebuild(); reheat();
  if (S.mode === "orbit" && !wasExpanded && fns.length) {
    // orbit rings can be large — reframe once the ring has been laid out
    // (deterministic, so one simulation frame is enough to know its size)
    requestAnimationFrame(() => requestAnimationFrame(() => fitView(0.82)));
  }
}

function collapseFile(fileId) {
  const n = S.nodesById.get(fileId);
  if (!n || n.kind !== "file" || !S.expanded.has(fileId)) return;
  S.expanded.delete(fileId);
  for (const fnId of S.fileFns.get(fileId) || []) S.visible.delete(fnId);
  if (S.selected && !S.visible.has(S.selected)) select(null);
  rebuild(); reheat();
}

/* ---------------- spotlight: pick one file, see just its world --------- */
/* Clears the canvas down to a single file — its functions plus everything
   one hop away — so picking a file from the Explorer answers "does this
   thing connect to anything else, or not" without other clutter. */
function spotlightFile(fid) {
  const n = S.nodesById.get(fid);
  if (!n) return;

  S.visible = new Set();
  S.expanded = new Set();
  S.visible.add(fid); ensurePos(fid);
  const fns = S.fileFns.get(fid) || [];
  for (const fnId of fns) { S.visible.add(fnId); ensurePos(fnId, fid); }
  if (fns.length) S.expanded.add(fid);

  const revealFor = (id) => {
    for (const e of S.outEdges.get(id) || [])
      if (!S.visible.has(e.target)) { S.visible.add(e.target); ensurePos(e.target, id); }
    for (const e of S.inEdges.get(id) || [])
      if (!S.visible.has(e.source)) { S.visible.add(e.source); ensurePos(e.source, id); }
  };
  revealFor(fid);
  for (const fnId of fns) revealFor(fnId);

  if (!passesFilter(n)) setFilter("all");
  rebuild(); reheat();
  select(fid);
  fitView(0.82);
}

/* ---------------- focus mode toggle ------------------------------------ */
/* Off (default): the full "interesting files" overview, click-to-explore
   cumulatively. On: canvas clears and picking a file in the Explorer
   spotlights just that file instead of adding to what's already shown. */
function toggleFocusMode() {
  S.focusMode = !S.focusMode;
  $("focus-toggle").classList.toggle("active", S.focusMode);
  if (S.focusMode) {
    S.visible = new Set(); S.expanded = new Set();
    select(null);
    rebuild(); reheat();
  } else {
    S.visible = new Set(); S.expanded = new Set();
    initialVisible(); layoutInitial();
    select(null);
    rebuild(); reheat();
    fitView(0.82);
  }
}

function revealNeighbors(id) {
  let added = false;
  for (const e of S.outEdges.get(id) || []) {
    if (!S.visible.has(e.target)) { S.visible.add(e.target); ensurePos(e.target, id); added = true; }
  }
  for (const e of S.inEdges.get(id) || []) {
    if (!S.visible.has(e.source)) { S.visible.add(e.source); ensurePos(e.source, id); added = true; }
  }
  if (added) { rebuild(); reheat(); }
}

function select(id, opts) {
  opts = opts || {};
  S.selected = id;
  computeChain();
  applyHighlight();
  renderDetail();
  if (!opts.fromNav) computeNavList(id);
  if (!opts.fromHistory) pushHistory(id);
  renderBreadcrumb();
}

/* ---------------- navigation: neighbor cycling + history --------------- */
function computeNavList(id) {
  if (id == null) { S.navList = []; S.navIdx = -1; return; }
  const outs = (S.outEdges.get(id) || []).filter(e => e.kind !== "contains").map(e => e.target);
  const ins = (S.inEdges.get(id) || []).filter(e => e.kind !== "contains").map(e => e.source);
  const seen = new Set([id]);
  S.navList = [...outs, ...ins].filter(nid => {
    if (seen.has(nid)) return false;
    seen.add(nid); return true;
  });
  S.navIdx = -1;
}

function pushHistory(id) {
  if (id == null) return;
  if (S.crumbs[S.crumbIdx] === id) return;
  S.crumbs = S.crumbs.slice(0, S.crumbIdx + 1);
  S.crumbs.push(id);
  if (S.crumbs.length > 40) S.crumbs.shift();
  S.crumbIdx = S.crumbs.length - 1;
}

function historyBack() {
  if (S.crumbIdx <= 0) return;
  S.crumbIdx--;
  jumpTo(S.crumbs[S.crumbIdx], { fromHistory: true });
}
function historyForward() {
  if (S.crumbIdx >= S.crumbs.length - 1) return;
  S.crumbIdx++;
  jumpTo(S.crumbs[S.crumbIdx], { fromHistory: true });
}
function navStep(dir) {
  if (!S.navList.length) return;
  S.navIdx = ((S.navIdx + dir) % S.navList.length + S.navList.length) % S.navList.length;
  jumpTo(S.navList[S.navIdx], { fromNav: true });
}

/* shows WHERE the current selection lives — folder / file / function —
   not a history of past clicks (arrow-key history still works via
   historyBack/historyForward, it's just not what's drawn here) */
function renderBreadcrumb() {
  const el = $("breadcrumb");
  const n = S.selected && S.nodesById.get(S.selected);
  if (!n) { el.classList.add("hidden"); el.innerHTML = ""; return; }

  const segs = [];
  if (n.kind === "table") {
    segs.push({ label: "Database", id: null });
    segs.push({ label: n.label, id: n.id });
  } else {
    const parts = (n.file || "").split("/").filter(Boolean);
    parts.forEach((part, i) => {
      const isFileSeg = i === parts.length - 1;
      segs.push({ label: part, id: isFileSeg ? n.file : null });
    });
    if (n.kind === "function" || n.kind === "method") {
      segs.push({ label: n.label + "()", id: n.id });
    }
  }

  el.innerHTML = segs.map((s, i) => {
    const isLast = i === segs.length - 1;
    const cls = "bc-item" + (isLast ? " current" : "") + (s.id ? "" : " bc-dir");
    return `<span class="${cls}"${s.id ? ` data-id="${esc(s.id)}"` : ""}>${esc(s.label)}</span>`;
  }).join('<span class="bc-sep">›</span>');
  el.classList.remove("hidden");
  el.querySelectorAll(".bc-item[data-id]").forEach(elm => elm.addEventListener("click", () => {
    jumpTo(elm.dataset.id, { fromHistory: true });
  }));
}

/* full call chain: everything reachable upstream + downstream */
function computeChain() {
  S.litNodes.clear(); S.litEdges.clear();
  if (!S.selected) return;
  S.litNodes.add(S.selected);
  const walk = (start, dir) => {
    const stack = [start], seen = new Set([start]);
    while (stack.length) {
      const cur = stack.pop();
      const edges = (dir === "out" ? S.outEdges : S.inEdges).get(cur) || [];
      for (const e of edges) {
        if (e.kind === "contains") continue;
        const next = dir === "out" ? e.target : e.source;
        if (!S.visible.has(next)) continue;
        S.litEdges.add(edgeKey(e));
        if (!seen.has(next)) {
          seen.add(next); S.litNodes.add(next); stack.push(next);
        }
      }
    }
  };
  walk(S.selected, "out");
  walk(S.selected, "in");
}

function applyHighlight() {
  const hasSel = !!S.selected;
  for (const [id, el] of S.elNodes) {
    el.classList.toggle("selected", id === S.selected);
    el.classList.toggle("lit", hasSel && S.litNodes.has(id));
    el.classList.toggle("dim", hasSel && !S.litNodes.has(id));
  }
  for (const { edge, key } of S.drawnEdges) {
    const els = S.elEdges.get(key);
    const lit = hasSel && (S.litEdges.has(key) ||
      (edge.kind === "contains" && S.litNodes.has(edge.target)));
    els.vis.classList.toggle("lit", lit);
    els.vis.classList.toggle("dim", hasSel && !lit);
    els.hit.classList.toggle("dim", hasSel && !lit);
  }
}

/* ---------------- detail panel ---------------- */
function renderDetail() {
  const panel = $("detail"), body = $("detail-body");
  if (!S.selected) { panel.classList.add("hidden"); return; }
  const n = S.nodesById.get(S.selected);
  const color = LAYER_COLOR[nodeLayer(n)];
  let html = `<span class="d-kind" style="color:${color};border-color:${color}55">` +
             `${esc(n.kind)} · ${esc(LAYER_LABEL[nodeLayer(n)])}</span>`;
  html += `<div class="d-name">${esc(n.label)}${n.kind === "function" || n.kind === "method" ? "()" : ""}</div>`;

  const subBits = [];
  if (n.kind === "function" || n.kind === "method") {
    subBits.push(`Function ${n.index}`);
    if (n.parentClass) subBits.push("in class " + n.parentClass);
  }
  if (n.file) subBits.push(`<span class="d-file" data-file="${esc(n.file)}">${esc(n.file)}</span>` +
                           (n.line ? `:${n.line}` : ""));
  if (n.kind === "file") subBits.push(`${n.language} · ${n.loc} lines`);
  html += `<div class="d-sub">${subBits.join(" · ")}</div>`;

  if (n.description) html += `<div class="d-desc">${esc(n.description)}</div>`;
  if (n.orphan) html += `<div class="d-warn">⚠ Orphaned — no detected callers.</div>`;
  if (n.cycle) html += `<div class="d-warn d-cycle">↻ Part of a circular call chain.</div>`;

  if (n.params && n.params.length)
    html += section("Parameters", n.params.map(p => `<span class="d-chip">${esc(p)}</span>`).join(""));
  if (n.returns) html += section("Returns", `<span class="d-chip">${esc(n.returns)}</span>`);
  if (n.routes && n.routes.length)
    html += section("Handles routes", n.routes.map(r =>
      `<div class="d-route">⇢ ${esc(r.method)} ${esc(r.path)}</div>`).join(""));
  {
    const srcFileId = n.kind === "file" ? n.id : n.file;
    const srcFile = srcFileId && S.nodesById.get(srcFileId);
    let src = "";
    if (n.code) {
      const lineInfo = n.line ? ` (lines ${n.line}–${n.endLine || n.line})` : "";
      src += `<button class="d-code-toggle" data-lines="${esc(lineInfo)}">▸ View code${esc(lineInfo)}</button>` +
             `<pre class="d-code hidden"><code>${highlightCode(n.code, n.line || 1)}</code></pre>`;
    }
    if (srcFile && srcFile.source) {
      src += `<button class="d-code-toggle d-ide-open" data-idefile="${esc(srcFileId)}"` +
             ` data-idefocus="${n.kind === "file" ? "" : esc(n.id)}"` +
             ` style="margin-top:6px">⛶ Open full file (IDE view)</button>`;
    }
    if (src) html += section("Source", src);
  }
  if (n.kind === "table") {
    if (n.model) html += section("ORM model", `<span class="d-chip">${esc(n.model)}</span>`);
    if (n.fields && n.fields.length)
      html += section("Fields / columns", `<div class="d-fields">${n.fields.map(esc).join("<br>")}</div>`);
  }
  if (n.dbConfig && n.dbConfig.length)
    html += section("DB config (masked)", `<div class="d-fields">${n.dbConfig.map(esc).join("<br>")}</div>`);

  const outs = (S.outEdges.get(n.id) || []);
  const ins = (S.inEdges.get(n.id) || []);
  if (outs.length) html += section(`Calls into (${outs.length})`,
    outs.slice(0, 40).map(e => linkRow(e.target, e)).join(""));
  if (ins.length) html += section(`Called from (${ins.length})`,
    ins.slice(0, 40).map(e => linkRow(e.source, e)).join(""));
  if (!outs.length && !ins.length) {
    const msg = n.kind === "file"
      ? "No detected connections — this file doesn't appear to link to anything else in the scan."
      : "No detected connections — possibly unused (orphaned).";
    html += section("Connections", `<div class="d-empty">${msg}</div>`);
  }

  if (n.kind === "file" && n.nFunctions)
    html += section(`Functions (${n.nFunctions})`,
      (S.fileFns.get(n.id) || []).map(fid => {
        const f = S.nodesById.get(fid);
        return `<div class="d-link" data-jump="${esc(fid)}">` +
               `<span class="dl-kind">${f.index}.</span>` +
               `<span class="dl-label">${esc(f.label)}()</span></div>`;
      }).join(""));

  if (n.warnings && n.warnings.length)
    html += section("Warnings", n.warnings.map(w => `<div class="d-warn">⚠ ${esc(w)}</div>`).join(""));

  body.innerHTML = html;
  body.querySelectorAll("[data-jump]").forEach(el =>
    el.addEventListener("click", () => jumpTo(el.dataset.jump)));
  body.querySelectorAll(".d-file").forEach(el =>
    el.addEventListener("click", () => jumpTo(el.dataset.file)));
  body.querySelectorAll(".d-code-toggle:not(.d-ide-open)").forEach(el =>
    el.addEventListener("click", () => {
      const pre = el.nextElementSibling;
      const hidden = pre.classList.toggle("hidden");
      el.textContent = (hidden ? "▸ View code" : "▾ Hide code") + el.dataset.lines;
    }));
  body.querySelectorAll(".d-ide-open").forEach(el =>
    el.addEventListener("click", () =>
      openIde(el.dataset.idefile, el.dataset.idefocus || null)));
  if (S.view !== "ide") panel.classList.remove("hidden");
}

function section(title, inner) {
  return `<div class="d-section"><h4>${esc(title)}</h4>${inner}</div>`;
}
function linkRow(id, e) {
  const t = S.nodesById.get(id);
  if (!t) return "";
  const kindTag = { call: "call", api: "API", db: "DB", include: "incl",
                    link: "page", contains: "" }[e.kind] || e.kind;
  return `<div class="d-link" data-jump="${esc(id)}" title="${esc(e.label || "")}">` +
         `<span class="dl-kind">${kindTag}</span>` +
         `<span class="dl-label">${esc(t.label)}${t.kind === "table" ? " 🗃" : ""}</span></div>`;
}

/* ---------------- jump / center ---------------- */
function jumpTo(id, opts) {
  const n = S.nodesById.get(id);
  if (!n) return;
  if (S.view === "ide") {
    const fileId = n.kind === "file" ? n.id : n.file;
    if (fileId && S.nodesById.get(fileId)?.source) {
      openIde(fileId, n.kind === "file" ? null : id);
      return;
    }
    setView("chart");   // no source to show (e.g. a table) — use the chart
  }
  if ((n.kind === "function" || n.kind === "method") && !S.visible.has(id)) {
    if (n.file && S.nodesById.has(n.file)) {
      S.visible.add(n.file); ensurePos(n.file);
      S.expanded.add(n.file);
      for (const fid of S.fileFns.get(n.file) || []) {
        S.visible.add(fid); ensurePos(fid, n.file);
      }
    } else { S.visible.add(id); ensurePos(id); }
  } else if (!S.visible.has(id)) {
    S.visible.add(id); ensurePos(id);
  }
  if (!passesFilter(n)) setFilter("all");
  rebuild(); reheat();
  select(id, opts);
  centerOn(id);
}

function centerOn(id) {
  const p = S.pos.get(id);
  if (!p) return;
  const x = p.x, y = p.y;
  const r = svg.getBoundingClientRect();
  animateTf({ x: r.width / 2 - x * S.tf.k, y: r.height / 2 - y * S.tf.k, k: S.tf.k });
}

function fitView(pad) {
  const ids = [...S.visible].filter(id => S.elNodes.has(id));
  if (!ids.length) return;
  let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
  for (const id of ids) {
    const p = S.pos.get(id); if (!p) continue;
    x0 = Math.min(x0, p.x); y0 = Math.min(y0, p.y);
    x1 = Math.max(x1, p.x); y1 = Math.max(y1, p.y);
  }
  const r = svg.getBoundingClientRect();
  const w = Math.max(x1 - x0, 60), h = Math.max(y1 - y0, 60);
  const k = Math.min(2, Math.min(r.width / w, r.height / h) * (pad || 0.85));
  animateTf({
    x: r.width / 2 - (x0 + x1) / 2 * k,
    y: r.height / 2 - (y0 + y1) / 2 * k, k,
  });
}

let tfAnim = null;
function animateTf(target) {
  const from = { ...S.tf }, t0 = performance.now();
  cancelAnimationFrame(tfAnim);
  const step = (t) => {
    const u = Math.min(1, (t - t0) / 350), e = 1 - Math.pow(1 - u, 3);
    S.tf.x = from.x + (target.x - from.x) * e;
    S.tf.y = from.y + (target.y - from.y) * e;
    S.tf.k = from.k + (target.k - from.k) * e;
    applyTf();
    if (u < 1) tfAnim = requestAnimationFrame(step);
  };
  tfAnim = requestAnimationFrame(step);
}
function applyTf() {
  viewport.setAttribute("transform",
    `translate(${S.tf.x},${S.tf.y}) scale(${S.tf.k})`);
  updateMinimapViewport();
}

/* ---------------- minimap ---------------- */
const MM_W = 168, MM_H = 112;

function computeMinimapTransform() {
  const ids = [...S.visible].filter(id => S.elNodes.has(id));
  if (!ids.length) return null;
  let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
  for (const id of ids) {
    const p = S.pos.get(id); if (!p) continue;
    x0 = Math.min(x0, p.x); y0 = Math.min(y0, p.y);
    x1 = Math.max(x1, p.x); y1 = Math.max(y1, p.y);
  }
  const w = Math.max(x1 - x0, 60), h = Math.max(y1 - y0, 60);
  const pad = 18;
  const scale = Math.min((MM_W - pad) / w, (MM_H - pad) / h);
  return { x0, y0, scale, ox: (MM_W - w * scale) / 2, oy: (MM_H - h * scale) / 2 };
}
const mmX = (t, x) => t.ox + (x - t.x0) * t.scale;
const mmY = (t, y) => t.oy + (y - t.y0) * t.scale;

function renderMinimap() {
  const svgEl = $("minimap-svg");
  svgEl.innerHTML = "";
  svgEl.setAttribute("viewBox", `0 0 ${MM_W} ${MM_H}`);
  S.mmDots = new Map();
  S.mmT = computeMinimapTransform();
  if (!S.mmT) { S.mmViewportEl = null; return; }
  for (const id of S.visible) {
    if (!S.elNodes.has(id)) continue;
    const n = S.nodesById.get(id);
    if (!n) continue;
    const c = document.createElementNS(SVGNS, "circle");
    c.setAttribute("r", n.kind === "file" ? 1.6 : 1);
    c.setAttribute("fill", LAYER_COLOR[nodeLayer(n)]);
    c.setAttribute("opacity", n.kind === "file" ? 0.9 : 0.55);
    svgEl.appendChild(c);
    S.mmDots.set(id, c);
  }
  const rect = document.createElementNS(SVGNS, "rect");
  rect.id = "mm-viewport";
  svgEl.appendChild(rect);
  S.mmViewportEl = rect;
  updateMinimapPositions();
}

function updateMinimapPositions() {
  const t = S.mmT;
  if (!t) return;
  for (const [id, c] of S.mmDots) {
    const p = S.pos.get(id);
    if (!p) continue;
    c.setAttribute("cx", mmX(t, p.x));
    c.setAttribute("cy", mmY(t, p.y));
  }
  updateMinimapViewport();
}

function updateMinimapViewport() {
  const t = S.mmT, rectEl = S.mmViewportEl;
  if (!t || !rectEl) return;
  const r = svg.getBoundingClientRect();
  if (!r.width || !r.height) return;
  const wx0 = -S.tf.x / S.tf.k, wy0 = -S.tf.y / S.tf.k;
  const wx1 = (r.width - S.tf.x) / S.tf.k, wy1 = (r.height - S.tf.y) / S.tf.k;
  rectEl.setAttribute("x", mmX(t, wx0));
  rectEl.setAttribute("y", mmY(t, wy0));
  rectEl.setAttribute("width", Math.max(4, (wx1 - wx0) * t.scale));
  rectEl.setAttribute("height", Math.max(4, (wy1 - wy0) * t.scale));
}

function bindMinimap() {
  const svgEl = $("minimap-svg");
  let dragging = false;
  const panTo = (ev) => {
    const t = S.mmT; if (!t) return;
    const rect = svgEl.getBoundingClientRect();
    const mx = (ev.clientX - rect.left) * (MM_W / rect.width);
    const my = (ev.clientY - rect.top) * (MM_H / rect.height);
    const wx = t.x0 + (mx - t.ox) / t.scale;
    const wy = t.y0 + (my - t.oy) / t.scale;
    const r = svg.getBoundingClientRect();
    animateTf({ x: r.width / 2 - wx * S.tf.k, y: r.height / 2 - wy * S.tf.k, k: S.tf.k });
  };
  svgEl.addEventListener("mousedown", (ev) => { dragging = true; panTo(ev); ev.stopPropagation(); });
  window.addEventListener("mousemove", (ev) => { if (dragging) panTo(ev); });
  window.addEventListener("mouseup", () => { dragging = false; });
}

const MODE_CYCLE = ["orbit", "free"];
const MODE_ICON = { orbit: "◎", free: "✺" };
const MODE_TITLE = {
  orbit: "Orbit layout — files float, functions ring around them (click to switch)",
  free: "Free layout — everything force-directed (click to switch)",
};

/* ---------------- orbit layout (files float, functions ring them) ------ */
/* A file's functions sit on a circle around it, spoked by straight
   "contains" lines. Only files/tables/unanchored functions take part in
   the physics (repulsion + spring + light layer grouping); a file's own
   functions are placed deterministically each frame so the ring never
   drifts out of shape or overlaps a neighboring file's ring. */
function isOrbitHub(id) {
  const n = S.nodesById.get(id);
  if (!n) return true;
  if (n.kind !== "function" && n.kind !== "method") return true;
  return !(n.file && S.expanded.has(n.file) && S.visible.has(n.file));
}

function hubOf(id) {
  const n = S.nodesById.get(id);
  if (n && (n.kind === "function" || n.kind === "method") &&
      n.file && S.expanded.has(n.file) && S.visible.has(n.file)) {
    return n.file;
  }
  return id;
}

function fileOrbitFns(fid) {
  if (!S.expanded.has(fid)) return [];
  return (S.fileFns.get(fid) || []).filter(fnId => S.visible.has(fnId));
}

/* radius grows with function count so the ring's circumference always
   has enough room per function — dense files never look like a jam */
function orbitRadius(fid) {
  const n = fileOrbitFns(fid).length;
  return n ? Math.max(70, 6.5 * n + 40) : 0;
}

function hubFootprint(id) {
  const n = S.nodesById.get(id);
  return (n ? nodeSize(n).w / 2 : 40) + 16 + orbitRadius(id);
}

function layoutSatellites() {
  for (const fid of S.expanded) {
    if (!S.visible.has(fid)) continue;
    const fp = S.pos.get(fid);
    if (!fp) continue;
    const fns = fileOrbitFns(fid);
    const n = fns.length;
    if (!n) continue;
    const r = orbitRadius(fid);
    fns.forEach((fnId, i) => {
      let p = S.pos.get(fnId);
      if (!p) { p = { x: fp.x, y: fp.y, vx: 0, vy: 0 }; S.pos.set(fnId, p); }
      if (p.fx !== undefined) { p.x = p.fx; p.y = p.fy; return; }  // being dragged — follow the pointer
      const angle = (2 * Math.PI * i / n) - Math.PI / 2;
      p.x = fp.x + r * Math.cos(angle);
      p.y = fp.y + r * Math.sin(angle);
    });
  }
}

function simTickOrbit() {
  const alpha = S.alpha;
  if (alpha < 0.005) return false;

  const hubIds = [...S.elNodes.keys()].filter(isOrbitHub);

  // repulsion, orbit-radius aware so rings never overlap each other
  const cell = 260, grid = new Map();
  for (const id of hubIds) {
    const p = S.pos.get(id);
    const key = (p.x / cell | 0) + ":" + (p.y / cell | 0);
    if (!grid.has(key)) grid.set(key, []);
    grid.get(key).push(id);
  }
  for (const id of hubIds) {
    const p = S.pos.get(id), ri = hubFootprint(id);
    const cx = p.x / cell | 0, cy = p.y / cell | 0;
    for (let gx = cx - 2; gx <= cx + 2; gx++)
      for (let gy = cy - 2; gy <= cy + 2; gy++) {
        for (const oid of grid.get(gx + ":" + gy) || []) {
          if (oid === id) continue;
          const q = S.pos.get(oid), rj = hubFootprint(oid);
          let dx = p.x - q.x, dy = p.y - q.y;
          let d2 = dx * dx + dy * dy;
          if (d2 < 1) { dx = hash01(id) - 0.5; dy = hash01(oid) - 0.5; d2 = 1; }
          const d = Math.sqrt(d2);
          const minSep = ri + rj + 60;
          let f;
          if (d < minSep) f = (minSep - d) * 0.11 * alpha;
          else { if (d2 > 810000) continue; f = 4200 / d2 * alpha; }
          p.vx += dx / d * f; p.vy += dy / d * f;
        }
      }
  }

  // hub-to-hub springs, derived from edges between their satellite functions
  const hubSprings = new Map();
  for (const { edge } of S.drawnEdges) {
    if (edge.kind === "contains") continue;
    const hs = hubOf(edge.source), ht = hubOf(edge.target);
    if (hs === ht) continue;
    const key = hs < ht ? hs + "→" + ht : ht + "→" + hs;
    const rec = hubSprings.get(key);
    if (rec) rec.count++;
    else hubSprings.set(key, { a: hs, b: ht, count: 1 });
  }
  for (const { a, b, count } of hubSprings.values()) {
    const p = S.pos.get(a), q = S.pos.get(b);
    if (!p || !q) continue;
    const idealLen = 130 + hubFootprint(a) + hubFootprint(b);
    const dx = q.x - p.x, dy = q.y - p.y;
    const d = Math.max(1, Math.hypot(dx, dy));
    const strength = Math.min(2.2, 1 + Math.log2(count));
    const f = (d - idealLen) * 0.05 * alpha * strength;
    p.vx += dx / d * f; p.vy += dy / d * f;
    q.vx -= dx / d * f; q.vy -= dy / d * f;
  }

  // light layer grouping + centering — floaty, not rigid columns
  for (const id of hubIds) {
    const n = S.nodesById.get(id), p = S.pos.get(id);
    const bx = (BAND[nodeLayer(n)] ?? 0.5) * 1600;
    p.vx += (bx - p.x) * 0.006 * alpha;
    p.vy += (550 - p.y) * 0.003 * alpha;
  }

  // integrate
  for (const id of hubIds) {
    const p = S.pos.get(id);
    if (p.fx !== undefined) { p.x = p.fx; p.y = p.fy; p.vx = p.vy = 0; continue; }
    p.vx *= 0.58; p.vy *= 0.58;
    p.x += Math.max(-26, Math.min(26, p.vx));
    p.y += Math.max(-26, Math.min(26, p.vy));
  }

  layoutSatellites();
  S.alpha *= 0.985;
  return true;
}

/* ---------------- force simulation (free layout) ------------------------ */
function reheat() {
  S.alpha = Math.max(S.alpha, 0.9);
}

function simTick() {
  return S.mode === "orbit" ? simTickOrbit() : simTickFree();
}

function simTickFree() {
  const nodes = [...S.elNodes.keys()];
  const a = S.alpha;
  if (a < 0.005) return false;
  const REP = 5200, SPRING = 0.06,
        LEN = { contains: 80, call: 130, api: 190, db: 150,
                include: 200, link: 220 };

  // repulsion (grid-bucketed to stay fast)
  const cell = 170, grid = new Map();
  for (const id of nodes) {
    const p = S.pos.get(id);
    const key = (p.x / cell | 0) + ":" + (p.y / cell | 0);
    if (!grid.has(key)) grid.set(key, []);
    grid.get(key).push(id);
  }
  for (const id of nodes) {
    const p = S.pos.get(id);
    const cx = p.x / cell | 0, cy = p.y / cell | 0;
    for (let gx = cx - 1; gx <= cx + 1; gx++)
      for (let gy = cy - 1; gy <= cy + 1; gy++) {
        for (const oid of grid.get(gx + ":" + gy) || []) {
          if (oid === id) continue;
          const q = S.pos.get(oid);
          let dx = p.x - q.x, dy = p.y - q.y;
          let d2 = dx * dx + dy * dy;
          if (d2 < 1) { dx = hash01(id) - 0.5; dy = hash01(oid) - 0.5; d2 = 1; }
          if (d2 > cell * cell * 2.6) continue;
          const f = REP / d2 * a;
          const d = Math.sqrt(d2);
          p.vx += dx / d * f; p.vy += dy / d * f;
        }
      }
  }
  // springs
  for (const { edge } of S.drawnEdges) {
    const p = S.pos.get(edge.source), q = S.pos.get(edge.target);
    if (!p || !q) continue;
    const dx = q.x - p.x, dy = q.y - p.y;
    const d = Math.max(1, Math.hypot(dx, dy));
    const f = (d - (LEN[edge.kind] || 140)) * SPRING * a;
    p.vx += dx / d * f; p.vy += dy / d * f;
    q.vx -= dx / d * f; q.vy -= dy / d * f;
  }
  // layer-band gravity + centering
  for (const id of nodes) {
    const n = S.nodesById.get(id), p = S.pos.get(id);
    const bx = (BAND[nodeLayer(n)] ?? 0.5) * 1600;
    p.vx += (bx - p.x) * 0.012 * a;
    p.vy += (550 - p.y) * 0.006 * a;
  }
  // integrate
  for (const id of nodes) {
    const p = S.pos.get(id);
    if (p.fx !== undefined) { p.x = p.fx; p.y = p.fy; p.vx = p.vy = 0; continue; }
    p.vx *= 0.55; p.vy *= 0.55;
    p.x += Math.max(-28, Math.min(28, p.vx));
    p.y += Math.max(-28, Math.min(28, p.vy));
  }
  S.alpha *= 0.985;
  return true;
}

function runTicks(n) { for (let i = 0; i < n; i++) { S.alpha = 0.9; simTick(); } S.alpha = 0.25; }

function startLoop() {
  const loop = () => {
    if (simTick()) updatePositions();
    requestAnimationFrame(loop);
  };
  requestAnimationFrame(loop);
  applyTf();
}

function updatePositions() {
  for (const [id, el] of S.elNodes) {
    const p = S.pos.get(id);
    el.setAttribute("transform", `translate(${p.x},${p.y})`);
  }
  updateMinimapPositions();
  for (const { edge, key } of S.drawnEdges) {
    const p = S.pos.get(edge.source), q = S.pos.get(edge.target);
    if (!p || !q) continue;
    const els = S.elEdges.get(key);
    const mx = (p.x + q.x) / 2, my = (p.y + q.y) / 2;
    const dx = q.x - p.x, dy = q.y - p.y;
    const d = Math.max(1, Math.hypot(dx, dy));
    const bend = edge.kind === "contains" ? 0 : Math.min(34, d * 0.14);
    const cx = mx - dy / d * bend, cy = my + dx / d * bend;
    const path = `M${p.x},${p.y} Q${cx},${cy} ${q.x},${q.y}`;
    els.vis.setAttribute("d", path);
    els.hit.setAttribute("d", path);
  }
}

/* ---------------- pan / zoom / drag ---------------- */
function bindUI() {
  let pan = null;
  svg.addEventListener("mousedown", (ev) => {
    if (ev.target.closest(".node")) return;
    pan = { x: ev.clientX, y: ev.clientY, tx: S.tf.x, ty: S.tf.y };
    svg.classList.add("panning");
  });
  window.addEventListener("mousemove", (ev) => {
    if (S.drag) { dragNodeMove(ev); return; }
    if (!pan) return;
    S.tf.x = pan.tx + ev.clientX - pan.x;
    S.tf.y = pan.ty + ev.clientY - pan.y;
    applyTf();
  });
  window.addEventListener("mouseup", () => {
    if (S.drag) endDragNode();
    pan = null; svg.classList.remove("panning");
  });
  svg.addEventListener("click", (ev) => {
    if (!ev.target.closest(".node") && !ev.target.closest(".edge-hit")) select(null);
  });
  svg.addEventListener("contextmenu", (ev) => {
    if (ev.target.closest(".node") || ev.target.closest(".edge-hit")) return;
    ev.preventDefault();
    onCanvasContextMenu(ev);
  });
  svg.addEventListener("wheel", (ev) => {
    ev.preventDefault();
    const r = svg.getBoundingClientRect();
    const mx = ev.clientX - r.left, my = ev.clientY - r.top;
    const k2 = Math.max(0.12, Math.min(3.2, S.tf.k * (ev.deltaY < 0 ? 1.13 : 0.885)));
    S.tf.x = mx - (mx - S.tf.x) * (k2 / S.tf.k);
    S.tf.y = my - (my - S.tf.y) * (k2 / S.tf.k);
    S.tf.k = k2;
    applyTf();
  }, { passive: false });

  $("zoom-in").onclick = () => animateTf({ ...S.tf, k: Math.min(3.2, S.tf.k * 1.3) });
  $("zoom-out").onclick = () => animateTf({ ...S.tf, k: Math.max(0.12, S.tf.k / 1.3) });
  $("zoom-fit").onclick = () => fitView(0.82);
  $("layout-toggle").onclick = () => {
    const i = MODE_CYCLE.indexOf(S.mode);
    S.mode = MODE_CYCLE[(i + 1) % MODE_CYCLE.length];
    const btn = $("layout-toggle");
    btn.textContent = MODE_ICON[S.mode];
    btn.title = MODE_TITLE[S.mode];
    btn.classList.toggle("active", S.mode === "orbit");
    S.alpha = 0.9;
  };
  $("detail-close").onclick = () => select(null);
  $("warnings-close").onclick = () => $("warnings-panel").classList.add("hidden");
  $("insights-close").onclick = () => $("insights-panel").classList.add("hidden");
  $("onboarding-dismiss").onclick = dismissOnboarding;
  $("focus-toggle").onclick = toggleFocusMode;
  $("onboarding").addEventListener("click", (ev) => {
    if (ev.target.id === "onboarding") dismissOnboarding();
  });

  document.querySelectorAll("#layer-filter button").forEach(b =>
    b.addEventListener("click", () => setFilter(b.dataset.layer)));

  const search = $("search");
  search.addEventListener("input", () => renderSearch(search.value));
  search.addEventListener("keydown", (ev) => {
    const items = [...document.querySelectorAll(".sr-item")];
    if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
      ev.preventDefault();
      S.searchSel = ev.key === "ArrowDown"
        ? Math.min(items.length - 1, S.searchSel + 1)
        : Math.max(0, S.searchSel - 1);
      items.forEach((el, i) => el.classList.toggle("sel", i === S.searchSel));
      items[S.searchSel]?.scrollIntoView({ block: "nearest" });
    } else if (ev.key === "Enter") {
      (items[S.searchSel] || items[0])?.click();
    } else if (ev.key === "Escape") {
      closeSearch(); search.blur();
    }
  });
  $("ide-close").onclick = closeIde;
  document.querySelectorAll("#view-mode button").forEach(b =>
    b.addEventListener("click", () => setView(b.dataset.view)));
  document.addEventListener("keydown", (ev) => {
    const typing = document.activeElement === search ||
      document.activeElement?.tagName === "INPUT";
    if (ev.key === "/" && !typing && $("ide").classList.contains("hidden")) {
      ev.preventDefault(); search.focus(); search.select();
    }
    if (ev.key === "Escape") {
      if (!$("context-menu").classList.contains("hidden")) { hideContextMenu(); return; }
      if (!$("onboarding").classList.contains("hidden")) { dismissOnboarding(); return; }
      if (!$("ide").classList.contains("hidden")) { closeIde(); return; }
      select(null); closeSearch();
    }
    if (typing || !$("ide").classList.contains("hidden")) return;
    if (ev.key === "ArrowRight") { if (S.selected) { ev.preventDefault(); navStep(1); } }
    else if (ev.key === "ArrowLeft") { if (S.selected) { ev.preventDefault(); navStep(-1); } }
    else if (ev.key === "ArrowUp") { if (S.crumbIdx > 0) { ev.preventDefault(); historyBack(); } }
    else if (ev.key === "ArrowDown") { if (S.crumbIdx < S.crumbs.length - 1) { ev.preventDefault(); historyForward(); } }
  });
  document.addEventListener("click", (ev) => {
    if (!ev.target.closest("#search-wrap")) closeSearch();
  });
  // capture phase: fires before node/edge click handlers can stopPropagation()
  // and swallow the bubble-phase event this would otherwise rely on
  document.addEventListener("mousedown", (ev) => {
    if (!ev.target.closest("#context-menu")) hideContextMenu();
  }, true);
  window.addEventListener("blur", hideContextMenu);
  window.addEventListener("resize", hideContextMenu);
  svg.addEventListener("wheel", hideContextMenu, { passive: true });
}

function setFilter(layer) {
  S.filter = layer;
  document.querySelectorAll("#layer-filter button").forEach(b =>
    b.classList.toggle("active", b.dataset.layer === layer));
  if (S.selected && !passesFilter(S.nodesById.get(S.selected))) select(null);
  rebuild(); reheat();
}

function startDragNode(ev, id) {
  ev.stopPropagation();
  const drag = { id, moved: false, sx: ev.clientX, sy: ev.clientY, kids: [] };
  // dragging a file carries its expanded functions along, keeping offsets
  const n = S.nodesById.get(id);
  const p0 = S.pos.get(id);
  if (n && p0 && n.kind === "file" && S.expanded.has(id)) {
    for (const fnId of S.fileFns.get(id) || []) {
      if (!S.visible.has(fnId) || !S.elNodes.has(fnId)) continue;
      const cp = S.pos.get(fnId);
      if (cp) drag.kids.push({ id: fnId, dx: cp.x - p0.x, dy: cp.y - p0.y });
    }
  }
  S.drag = drag;
}
function dragNodeMove(ev) {
  const d = S.drag;
  if (Math.abs(ev.clientX - d.sx) + Math.abs(ev.clientY - d.sy) > 3) d.moved = true;
  if (!d.moved) return;
  const r = svg.getBoundingClientRect();
  const p = S.pos.get(d.id);
  p.fx = (ev.clientX - r.left - S.tf.x) / S.tf.k;
  p.fy = (ev.clientY - r.top - S.tf.y) / S.tf.k;
  for (const k of d.kids) {
    const cp = S.pos.get(k.id);
    if (cp) { cp.fx = p.fx + k.dx; cp.fy = p.fy + k.dy; }
  }
  reheat();
}
function endDragNode() {
  const ids = [S.drag.id, ...S.drag.kids.map(k => k.id)];
  for (const id of ids) {
    const p = S.pos.get(id);
    if (!p) continue;
    if (p.fx !== undefined) { p.x = p.fx; p.y = p.fy; delete p.fx; delete p.fy; }
  }
  const moved = S.drag.moved;
  setTimeout(() => { S.drag = null; }, moved ? 50 : 0);
  if (!moved) S.drag = null;
}

/* ---------------- context menu ---------------- */
function showContextMenu(x, y, items) {
  hideTooltip();
  const menu = $("context-menu");
  menu.innerHTML = items.map((it, i) => it.separator
    ? `<div class="cm-sep"></div>`
    : `<button class="cm-item${it.disabled ? " disabled" : ""}" data-i="${i}">${esc(it.label)}</button>`
  ).join("");
  menu.style.left = x + "px";
  menu.style.top = y + "px";
  menu.classList.remove("hidden");

  // clamp on-screen after layout so it never renders off the edge
  requestAnimationFrame(() => {
    const mw = menu.offsetWidth, mh = menu.offsetHeight;
    const left = Math.min(x, window.innerWidth - mw - 8);
    const top = Math.min(y, window.innerHeight - mh - 8);
    menu.style.left = Math.max(8, left) + "px";
    menu.style.top = Math.max(8, top) + "px";
  });

  menu.querySelectorAll(".cm-item").forEach((el) => {
    const it = items[parseInt(el.dataset.i, 10)];
    if (it.disabled) return;
    el.addEventListener("click", () => { hideContextMenu(); it.onClick(); });
  });
}

function hideContextMenu() {
  $("context-menu").classList.add("hidden");
}

function copyToClipboard(text) {
  if (navigator.clipboard?.writeText) {
    navigator.clipboard.writeText(text).catch(() => {});
    return;
  }
  const ta = document.createElement("textarea");
  ta.value = text; ta.style.position = "fixed"; ta.style.opacity = "0";
  document.body.appendChild(ta); ta.select();
  try { document.execCommand("copy"); } catch (e) { /* clipboard unavailable */ }
  document.body.removeChild(ta);
}

function onNodeContextMenu(n, ev) {
  select(n.id);
  const items = [];
  const srcFileId = n.kind === "file" ? n.id : n.file;
  const srcFile = srcFileId && S.nodesById.get(srcFileId);

  if (n.kind === "file") {
    if (n.nFunctions) {
      const isExpanded = S.expanded.has(n.id);
      items.push({ label: isExpanded ? "Collapse functions" : "Expand functions",
        onClick: () => isExpanded ? collapseFile(n.id) : expandFile(n.id) });
    }
    items.push({ label: "Reveal connections", onClick: () => revealNeighbors(n.id) });
    items.push({ label: "Focus only this file", onClick: () => {
      if (!S.focusMode) toggleFocusMode();
      spotlightFile(n.id);
    } });
    if (n.source) items.push({ label: "Open full file (IDE view)", onClick: () => openIde(n.id) });
    items.push({ separator: true });
  } else if (n.kind === "function" || n.kind === "method") {
    items.push({ label: "Reveal connections", onClick: () => revealNeighbors(n.id) });
    if (n.code) items.push({ label: "View code", onClick: () => {
      select(n.id);
      setTimeout(() => document.querySelector(".d-code-toggle:not(.d-ide-open)")?.click(), 30);
    } });
    if (srcFile?.source) items.push({ label: "Open in IDE view", onClick: () => openIde(srcFileId, n.id) });
    items.push({ separator: true });
  } else if (n.kind === "table") {
    items.push({ label: "Reveal connections", onClick: () => revealNeighbors(n.id) });
    if (n.file) items.push({ label: "Go to defining file", onClick: () => jumpTo(n.file) });
    items.push({ separator: true });
  }

  items.push({ label: "Center view here", onClick: () => centerOn(n.id) });
  items.push({ label: "Copy name", onClick: () => copyToClipboard(n.label) });
  if (n.file) items.push({ label: "Copy file path", onClick: () => copyToClipboard(n.file) });

  showContextMenu(ev.clientX, ev.clientY, items);
}

function onEdgeContextMenu(e, ev) {
  const items = [
    { label: "Go to source", onClick: () => jumpTo(e.source) },
    { label: "Go to target", onClick: () => jumpTo(e.target) },
  ];
  if (e.label) {
    items.push({ separator: true });
    items.push({ label: "Copy connection label", onClick: () => copyToClipboard(e.label) });
  }
  showContextMenu(ev.clientX, ev.clientY, items);
}

function onCanvasContextMenu(ev) {
  const items = [
    { label: "Fit view", onClick: () => fitView(0.82) },
    { label: "Zoom in", onClick: () => $("zoom-in").click() },
    { label: "Zoom out", onClick: () => $("zoom-out").click() },
    { separator: true },
    { label: S.mode === "orbit" ? "Switch to Free layout" : "Switch to Orbit layout",
      onClick: () => $("layout-toggle").click() },
    { label: S.focusMode ? "Exit Focus mode" : "Enter Focus mode",
      onClick: () => toggleFocusMode() },
    { separator: true },
    { label: "Deselect", disabled: !S.selected, onClick: () => select(null) },
  ];
  showContextMenu(ev.clientX, ev.clientY, items);
}

/* ---------------- tooltip ---------------- */
function showNodeTooltip(n, ev) {
  const tt = $("tooltip");
  let html = `<div class="tt-name">${esc(n.label)}${n.kind === "function" || n.kind === "method" ? "()" : ""}</div>`;
  if (n.description) html += `<div class="tt-desc">${esc(n.description)}</div>`;
  const meta = [LAYER_LABEL[nodeLayer(n)], n.kind];
  if (n.file && n.kind !== "file") meta.push(n.file);
  html += `<div class="tt-meta">${meta.map(esc).join(" · ")}</div>`;
  if (n.kind === "file" && S.fileFns.get(n.id)?.length && !S.expanded.has(n.id))
    html += `<div class="tt-meta">click to slice open ${S.fileFns.get(n.id).length} function(s)</div>`;
  tt.innerHTML = html;
  positionTooltip(ev);
}
function showEdgeTooltip(e, ev) {
  const tt = $("tooltip");
  const kind = { call: "function call", api: "API call", db: "database access",
                 include: "file include/import", link: "page navigation",
                 contains: "contains" }[e.kind] || e.kind;
  tt.innerHTML = `<div class="tt-name">${esc(e.label || kind)}</div>` +
                 `<div class="tt-meta">${esc(kind)}</div>`;
  positionTooltip(ev);
}
function positionTooltip(ev) {
  const tt = $("tooltip"), r = $("canvas-wrap").getBoundingClientRect();
  tt.classList.remove("hidden");
  let x = ev.clientX - r.left + 16, y = ev.clientY - r.top + 14;
  if (x + tt.offsetWidth > r.width - 12) x = ev.clientX - r.left - tt.offsetWidth - 12;
  if (y + tt.offsetHeight > r.height - 12) y = ev.clientY - r.top - tt.offsetHeight - 10;
  tt.style.left = x + "px"; tt.style.top = y + "px";
}
function hideTooltip() { $("tooltip").classList.add("hidden"); }

/* ---------------- search ---------------- */
function renderSearch(q) {
  const box = $("search-results");
  S.searchSel = -1;
  q = q.trim().toLowerCase();
  if (!q) { closeSearch(); return; }
  const hits = [];
  for (const n of S.data.nodes) {
    const label = (n.label || "").toLowerCase();
    const file = (n.file || "").toLowerCase();
    let score = -1;
    if (label === q) score = 0;
    else if (label.startsWith(q)) score = 1;
    else if (label.includes(q)) score = 2;
    else if (file.includes(q)) score = 3;
    if (score >= 0) hits.push([score, n]);
    if (hits.length > 300) break;
  }
  hits.sort((a, b) => a[0] - b[0] || a[1].label.length - b[1].label.length);
  box.innerHTML = "";
  if (!hits.length) box.innerHTML = "<div class='sr-empty'>No matches.</div>";
  for (const [, n] of hits.slice(0, 30)) {
    const d = document.createElement("div");
    d.className = "sr-item";
    const color = LAYER_COLOR[nodeLayer(n)];
    d.innerHTML = `<span class="tdot" style="background:${color}"></span>` +
      `<span class="sr-name">${esc(n.label)}${n.kind === "function" || n.kind === "method" ? "()" : ""}</span>` +
      `<span class="sr-path">${esc(n.kind === "file" ? n.language : (n.file || n.kind))}</span>`;
    d.onclick = () => { closeSearch(); $("search").value = ""; jumpTo(n.id); };
    box.appendChild(d);
  }
  box.classList.remove("hidden");
}
function closeSearch() { $("search-results").classList.add("hidden"); S.searchSel = -1; }

/* ---------------- code highlighting ---------------- */
const CODE_KW = new Set(("function def class return if elif else for foreach " +
  "while switch case break continue const let var import from export default " +
  "async await public private protected internal static final void new try " +
  "catch except finally raise throw throws lambda yield global nonlocal pass " +
  "None True False null true false undefined this self func go defer type " +
  "struct interface package use namespace echo require end do then begin " +
  "module when unless until match string int float bool byte long double " +
  "extends implements abstract readonly override virtual sealed with as in " +
  "of is not and or instanceof typeof delete print").split(" "));
const CODE_CTL = new Set(("if elif else for foreach while switch case break " +
  "continue return try catch except finally raise throw yield do then when " +
  "unless until match await default in of not and or is as with " +
  "instanceof typeof delete").split(" "));
const CODE_TOK =
  /(\/\*[\s\S]*?\*\/|\/\/[^\n]*|#[^\n]*|--[^\n]*)|("(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*'|`(?:[^`\\]|\\.)*`)|(\$\w+)|([A-Za-z_][\w$]*)(?=\s*\()|([A-Za-z_$][\w$]*)|(\d[\w.]*)/g;

function hlLine(line) {
  let out = "", last = 0, m;
  CODE_TOK.lastIndex = 0;
  while ((m = CODE_TOK.exec(line))) {
    out += esc(line.slice(last, m.index));
    if (m[1]) out += `<span class="c-com">${esc(m[0])}</span>`;
    else if (m[2]) out += `<span class="c-str">${esc(m[0])}</span>`;
    else if (m[3]) out += `<span class="c-var">${esc(m[0])}</span>`;
    else if (m[4]) out += CODE_CTL.has(m[0])
      ? `<span class="c-ctl">${esc(m[0])}</span>`
      : (CODE_KW.has(m[0])
        ? `<span class="c-kw">${esc(m[0])}</span>`
        : `<span class="c-call">${esc(m[0])}</span>`);
    else if (m[5]) out += CODE_CTL.has(m[0])
      ? `<span class="c-ctl">${esc(m[0])}</span>`
      : (CODE_KW.has(m[0])
        ? `<span class="c-kw">${esc(m[0])}</span>` : esc(m[0]));
    else out += `<span class="c-num">${esc(m[0])}</span>`;
    last = m.index + m[0].length;
  }
  return out + esc(line.slice(last));
}

/* ---------------- view modes: chart / IDE ---------------- */
function setView(view) {
  S.view = view;
  document.querySelectorAll("#view-mode button").forEach(b =>
    b.classList.toggle("active", b.dataset.view === view));
  $("canvas-wrap").classList.toggle("hidden", view === "ide");
  $("ide").classList.toggle("hidden", view !== "ide");
  if (view === "ide") {
    $("detail").classList.add("hidden");   // keep the editor clean
    if (!S.ideFile) {
      // open the selected node's file, else show a hint
      const sel = S.selected && S.nodesById.get(S.selected);
      const fileId = sel && (sel.kind === "file" ? sel.id : sel.file);
      if (fileId && S.nodesById.get(fileId)?.source) {
        openIde(fileId, sel.kind === "file" ? null : sel.id);
        return;
      }
      $("ide-path").textContent = "no file open";
      $("ide-lang").textContent = "";
      $("ide-outline-list").innerHTML = "";
      $("ide-code").innerHTML =
        "<div class='ide-placeholder'>⌗<br>Pick a file in the Explorer" +
        " on the left,<br>or click a node's “Open full file” button.</div>";
    }
  } else if (S.selected) {
    renderDetail();                        // bring the info panel back
  }
}

/* ---------------- IDE full-file viewer ---------------- */
function openIde(fileId, focusId) {
  const f = S.nodesById.get(fileId);
  if (!f || !f.source) return;
  S.ideFile = fileId;
  if (S.view !== "ide") setView("ide");
  $("ide-path").textContent = f.file || f.id;
  $("ide-lang").textContent = f.language || "";

  const list = $("ide-outline-list");
  list.innerHTML = "";
  const fns = (S.fileFns.get(fileId) || []).map(id => S.nodesById.get(id));
  if (!fns.length)
    list.innerHTML = "<div class='ol-empty'>No functions in this file.</div>";
  for (const fn of fns) {
    const d = document.createElement("div");
    d.className = "ol-item";
    d.dataset.id = fn.id;
    d.title = fn.description || "";
    d.innerHTML = `<span class="ol-num">${fn.index}</span>` +
                  `<span class="ol-name">${esc(fn.label)}()</span>` +
                  `<span class="ol-line">:${fn.line}</span>`;
    d.onclick = () => {
      focusIde(fn);
      if (S.visible.has(fn.id)) select(fn.id);  // sync graph selection
    };
    list.appendChild(d);
  }

  $("ide-code").innerHTML = f.source.split("\n").map((line, i) =>
    `<div class="cl" data-l="${i + 1}"><span class="c-ln">${i + 1}</span>` +
    `<span class="c-tx">${hlLine(line)}</span></div>`).join("");

  const focusFn = focusId && S.nodesById.get(focusId);
  if (focusFn) focusIde(focusFn);
  else $("ide-code").scrollTop = 0;
}

function focusIde(fn) {
  const codeEl = $("ide-code");
  codeEl.querySelectorAll(".cl.focus").forEach(e => e.classList.remove("focus"));
  const a = fn.line || 1, b = Math.max(fn.endLine || a, a);
  for (let l = a; l <= b; l++)
    codeEl.querySelector(`.cl[data-l="${l}"]`)?.classList.add("focus");
  codeEl.querySelector(`.cl[data-l="${a}"]`)
    ?.scrollIntoView({ block: "center", behavior: "smooth" });
  $("ide-outline-list").querySelectorAll(".ol-item").forEach(el =>
    el.classList.toggle("active", el.dataset.id === fn.id));
}

function closeIde() { setView("chart"); }

function highlightCode(code, startLine) {
  return code.split("\n").map((line, i) =>
    `<span class="c-ln">${String(startLine + i).padStart(4, " ")}</span>` +
    hlLine(line)).join("\n");
}

/* ---------------- onboarding ---------------- */
function maybeShowOnboarding() {
  let seen = false;
  try { seen = localStorage.getItem("codebread_onboarded") === "1"; } catch (e) { /* no storage */ }
  if (!seen) $("onboarding").classList.remove("hidden");
}
function dismissOnboarding() {
  $("onboarding").classList.add("hidden");
  try { localStorage.setItem("codebread_onboarded", "1"); } catch (e) { /* no storage */ }
}

/* ---------------- util ---------------- */
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g,
    c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

})();
