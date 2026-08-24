/* AI 大战 前端逻辑：WebSocket 实时渲染地图 / 血条 / 日志 / 控制 / 排行榜 / 关系图 / 回放。
   图标一律走 icons.js 的 SVG 库（icon() 用于 DOM、drawIcon() 用于 canvas），不再使用 emoji。 */

const $ = id => document.getElementById(id);
const state = { snapshot: null, filter: "all", running: false, lines: [] };
let ws = null;
let speechOn = false;
let speechVoice = null;
const synth = window.speechSynthesis || null;

function connect() {
  if (ws && ws.readyState < 2) return; // 已有连接或正在连接，避免重连竞态建双连接
  const sock = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
  ws = sock;
  sock.onopen = () => console.log("[ws] 已连接");
  sock.onmessage = e => {
    try { handle(JSON.parse(e.data)); }
    catch (err) { console.error("[ws] 消息处理失败", err); }
  };
  sock.onclose = () => {
    if (ws === sock) ws = null; // 只清自己的引用，别误清新连接
    setTimeout(connect, 1500);
  };
}
function send(o) { if (ws && ws.readyState === 1) ws.send(JSON.stringify(o)); }

/* 标签页从后台切回时立刻重连（浏览器会节流后台标签页的定时器） */
function ensureConnected() {
  if (!ws || ws.readyState > 1) connect();
}
document.addEventListener("visibilitychange", () => { if (!document.hidden) ensureConnected(); });
window.addEventListener("focus", ensureConnected);

function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

/* 应用一条消息（实时和回放共用） */
function applyMsg(m) {
  if (m.type === "snapshot") {
    // 世界网格增量推送：没带 grid 时沿用上一份缓存
    if (m.world && !m.world.grid && state.snapshot && state.snapshot.world) {
      m.world.grid = state.snapshot.world.grid;
      m.world.deposits = state.snapshot.world.deposits;
    }
    state.snapshot = m;
    // 自然结束只广播 snapshot 不发 status，这里同步运行状态与胜负横幅
    state.running = !!m.running;
    if (m.winner && !state.running) showVictory(m.winner);
    else if (state.running) hideBanner();
    render();
  }
  else if (m.type === "log") { addLog(m); }
  else if (m.type === "review") {
    onReview(m.text);
    addLog({ kind: "review", text: m.text, turn: m.turn || (state.snapshot ? state.snapshot.turn : 0) });
  }
  else if (m.type === "status") {
    state.running = !!m.running;
    if (m.running) hideBanner();
    else if (m.winner) showVictory(m.winner);
    updateStatus();
  }
}

function handle(m) {
  if (rp.active) return; // 回放模式下忽略实时消息
  if (m.type === "setup_result") { onSetupResult(m); return; }
  applyMsg(m);
}

/* ---------------- 地图（离屏地形缓存 + rAF 动画层） ---------------- */
let CELL = 28;

/* 按可用空间自适应格子尺寸：地图尽量填满 #mapwrap， clamp 在 20~56 之间 */
function fitCell(w) {
  const wrap = $("mapwrap");
  if (!wrap) return;
  const availW = wrap.clientWidth - 48;   // padding 与边框余量
  const availH = wrap.clientHeight - 84;  // 再减去图例行高度
  const c = Math.floor(Math.min(availW / w.w, availH / w.h));
  CELL = Math.max(20, Math.min(56, c));
}
const TERRAIN = {
  ".": { c: "#161d2a" },                              // 平地
  "F": { c: "#12301d", ic: "tree", tc: "#2f7a4e" },    // 森林
  "~": { c: "#0d2a40", ic: "droplet", tc: "#2a6f96" }, // 水域
  "M": { c: "#262b34", ic: "mountain", tc: "#5b6b7d" },// 山地
  "f": { c: "#2f270e", ic: "wheat", tc: "#a8873a" },   // 食物矿
  "o": { c: "#2c2013", ic: "pickaxe", tc: "#9a6b3a" }, // 矿石矿
};
const terrainCv = document.createElement("canvas"); // 地形离屏缓存，按 world_version 重建
let terrainVer = -1;
const anim = { agents: {}, night: 0 }; // 名字 -> {x,y 显示坐标, tx,ty 目标, hp, flashUntil, deadSince}
const lerp = (a, b, t) => a + (b - a) * t;

/* 将 canvas 按当前 devicePixelRatio 适配：内部像素 = 逻辑尺寸 × DPR，
   CSS 尺寸 = 逻辑尺寸 px，后续所有绘制直接按逻辑坐标调用。
   窗口拖到不同 DPR 的屏幕时，尺寸变化会触发重建缓存并重绘。 */
function setupDPR(cv, logicalW, logicalH) {
  const dpr = window.devicePixelRatio || 1;
  cv.width = Math.floor(logicalW * dpr);
  cv.height = Math.floor(logicalH * dpr);
  cv.style.width = logicalW + "px";
  cv.style.height = logicalH + "px";
  const ctx = cv.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return ctx;
}

window.addEventListener("resize", () => { terrainVer = -1; render(); });

function rr(ctx, x, y, w, h, r) {
  ctx.beginPath();
  if (ctx.roundRect) ctx.roundRect(x, y, w, h, r); else ctx.rect(x, y, w, h);
}

/* 快照到达：只更新地形缓存版本与动画目标，真正绘制在 rAF 里 */
function renderMap() {
  const s = state.snapshot;
  if (!s) return;
  const w = s.world;
  fitCell(w);
  const cv = $("map");
  const logicalW = w.w * CELL;
  const logicalH = w.h * CELL;
  const dpr = window.devicePixelRatio || 1;
  const needResize = cv.width !== Math.floor(logicalW * dpr) || cv.height !== Math.floor(logicalH * dpr);
  if (needResize) {
    setupDPR(cv, logicalW, logicalH);
    terrainVer = -1; // DPR/尺寸变化后离屏缓存分辨率也得重建
  }
  if (s.world_version !== terrainVer) { buildTerrain(s); terrainVer = s.world_version; }
  const now = performance.now();
  const seen = new Set();
  for (const a of s.agents) {
    seen.add(a.name);
    const [x, y] = a.pos;
    let st = anim.agents[a.name];
    if (!st) st = anim.agents[a.name] = { x, y, tx: x, ty: y, hp: a.hp, flashUntil: 0, deadSince: 0 };
    st.tx = x; st.ty = y;
    if (a.hp < st.hp) st.flashUntil = now + 500; // 掉血受击闪红
    st.hp = a.hp;
    if (!a.alive && !st.deadSince) st.deadSince = now; // 死亡动画起点
    if (a.alive) st.deadSince = 0;
  }
  for (const k of Object.keys(anim.agents)) if (!seen.has(k)) delete anim.agents[k];
}

function buildTerrain(s) {
  const w = s.world;
  const logicalW = w.w * CELL;
  const logicalH = w.h * CELL;
  const ctx = setupDPR(terrainCv, logicalW, logicalH);
  ctx.fillStyle = "#0a0d13";
  ctx.fillRect(0, 0, logicalW, logicalH);
  for (let y = 0; y < w.h; y++) {
    for (let x = 0; x < w.w; x++) {
      const ch = w.grid[y][x];
      const t = TERRAIN[ch] || TERRAIN["."];
      const px = x * CELL, py = y * CELL;
      ctx.fillStyle = t.c;
      rr(ctx, px + 1, py + 1, CELL - 2, CELL - 2, 5);
      ctx.fill();
      if (t.ic) drawIcon(ctx, t.ic, px + CELL / 2, py + CELL / 2 + 1, CELL * 0.5, t.tc, 0.55);
      if (ch === "f" || ch === "o") {
        const d = w.deposits[`${x},${y}`];
        if (d != null) {
          ctx.fillStyle = "rgba(240, 180, 41, .9)";
          ctx.font = `bold ${Math.max(9, Math.round(CELL * 0.34))}px Consolas, monospace`;
          ctx.textAlign = "left";
          ctx.textBaseline = "top";
          ctx.fillText(String(d), px + 4, py + 3);
        }
      }
    }
  }
}

/* rAF 绘制：地形 + 夜晚渐变蒙版 + 选手插值/受击/死亡动画 */
function drawFrame(now) {
  const s = state.snapshot;
  if (!s) return;
  const cv = $("map");
  if (!cv.width) return;
  const ctx = cv.getContext("2d");
  const dpr = window.devicePixelRatio || 1;
  const logicalW = s.world.w * CELL;
  const logicalH = s.world.h * CELL;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, logicalW, logicalH);
  // 离屏地形是物理像素分辨率（logical×dpr），drawImage 必须指定逻辑目标尺寸，否则 dpr>1 时会放大 dpr 倍
  if (terrainCv.width) ctx.drawImage(terrainCv, 0, 0, logicalW, logicalH);
  // 夜晚蒙版：透明度渐变过渡而非瞬变
  const target = s.day_night === "night" ? 0.45 : 0;
  anim.night = lerp(anim.night, target, 0.06);
  if (anim.night > 0.005) {
    ctx.fillStyle = `rgba(7, 10, 26, ${anim.night.toFixed(3)})`;
    ctx.fillRect(0, 0, logicalW, logicalH);
  }
  const nameTags = []; // 名字第二遍统一绘制，避免被相邻头像遮盖
  const circles = [];  // 所有头像位置，用于判断名字是否会压住下面的头像
  for (const a of s.agents) {
    const st = anim.agents[a.name];
    if (!st) continue;
    st.x = lerp(st.x, st.tx, 0.22); // ~200ms 平滑移动
    st.y = lerp(st.y, st.ty, 0.22);
    if (Math.abs(st.x - st.tx) < 0.01) st.x = st.tx;
    if (Math.abs(st.y - st.ty) < 0.01) st.y = st.ty;
    // 边缘格子的头像/名字会被画布边界裁掉，钳制在画布内
    const rr_ = CELL * 0.56;
    const cx = Math.min(Math.max(st.x * CELL + CELL / 2, rr_), logicalW - rr_);
    const cy = Math.min(Math.max(st.y * CELL + CELL / 2, rr_), logicalH - rr_);
    if (now < st.flashUntil && a.alive) { // 受击闪红
      const p = (st.flashUntil - now) / 500;
      ctx.beginPath();
      ctx.arc(cx, cy, CELL * 0.54, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(255, 45, 70, ${(0.55 * p).toFixed(3)})`;
      ctx.fill();
    }
    let scale = 1, alpha = 1;
    if (!a.alive && st.deadSince) { // 死亡：skull 从放大回落并淡入
      const t = Math.min(1, (now - st.deadSince) / 450);
      scale = 1.7 - 0.7 * t;
      alpha = 0.35 + 0.65 * t;
    }
    ctx.save();
    ctx.translate(cx, cy);
    ctx.scale(scale, scale);
    ctx.globalAlpha = alpha;
    ctx.beginPath();
    ctx.arc(0, 0, CELL * 0.42, 0, Math.PI * 2);
    ctx.fillStyle = a.alive ? "#f4f7ff" : "#3a414e";
    ctx.fill();
    ctx.strokeStyle = a.alive ? "#f0b429" : "#525b69";
    ctx.lineWidth = 2;
    ctx.stroke();
    drawIcon(ctx, a.alive ? avatarIconName(a.emoji) : "skull", 0, 0, CELL * 0.58,
      a.alive ? "#22293a" : "#9aa5b3");
    ctx.restore();
    circles.push({ cx, cy });
    if (a.alive) nameTags.push({ name: a.name, cx, cy });
  }
  // 第二遍：统一画名字（在最上层，不会被其他头像盖住）
  if (nameTags.length) {
    ctx.font = `${Math.max(9, Math.round(CELL * 0.36))}px sans-serif`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.shadowColor = "rgba(0, 0, 0, .85)";
    ctx.shadowBlur = 3;
    ctx.fillStyle = "#eef2fa";
    for (const t of nameTags) {
      // 下方有其他头像时名字改画到上方，避免压住别人；底部空间不够时也画到上方
      const belowBlocked = circles.some(c =>
        !(c.cx === t.cx && c.cy === t.cy) &&
        Math.abs(c.cx - t.cx) < CELL * 0.9 && c.cy > t.cy && c.cy - t.cy < CELL * 1.6);
      const below = t.cy + CELL * 0.62 + 7;
      const above = t.cy - CELL * 0.62 - 7;
      const ny = (belowBlocked || below + 6 > logicalH) ? above : below;
      const halfW = ctx.measureText(t.name).width / 2 + 2;
      const nx = Math.min(Math.max(t.cx, halfW), logicalW - halfW);
      ctx.fillText(t.name, nx, ny);
    }
    ctx.shadowBlur = 0;
  }
}
(function mapLoop() { drawFrame(performance.now()); requestAnimationFrame(mapLoop); })();

/* ---------------- 选手面板 ---------------- */
function fmtTok(n) {
  if (n >= 1000000) return (n / 1000000).toFixed(2) + "M";
  if (n >= 1000) return (n / 1000).toFixed(1) + "k";
  return String(n);
}

/* ---------------- 选手面板 ---------------- */
const prevBars = {}; // 名字 -> {hp, energy}，数值变化时对应条形闪烁

function renderAgents() {
  const s = state.snapshot;
  if (!s) return;
  const box = $("agents");
  box.innerHTML = "";
  for (const a of s.agents) {
    const u = a.usage || { prompt: 0, completion: 0, cost: null, cache_rate: null };
    const costTxt = u.cost == null ? "费用未知" : "¥" + u.cost.toFixed(4);
    const cacheTxt = u.cache_rate == null ? "" : `缓存 ${u.cache_est ? "~" : ""}${Math.round(u.cache_rate * 100)}%`;
    const weaponTxt = a.weapon ? `${icon("sword", 10)}${a.weapon_durability}` : "·";
    const prev = prevBars[a.name] || {};
    const hpFlux = prev.hp != null && prev.hp !== a.hp ? " flux" : "";
    const enFlux = prev.energy != null && prev.energy !== a.energy ? " flux" : "";
    prevBars[a.name] = { hp: a.hp, energy: a.energy };
    const d = document.createElement("div");
    d.className = "card" + (a.alive ? "" : " dead");
    const t = a.thought || "正在思考…";
    const preview = t.length > 12 ? t.slice(0, 12) + "…" : t;
    d.innerHTML = `
      <div class="c-head"><span class="c-emoji">${icon(avatarIconName(a.emoji), 19)}</span><span class="c-name" title="${esc(a.provider)} · ${esc(a.model)}">${esc(a.name)}</span>
        <span class="c-state ${a.alive ? "" : "dead"}">${a.alive ? "活" : "死"}</span></div>
      <div class="c-bars">
        <div class="bar${hpFlux}"><span class="b-ic b-hp">${icon("heart", 11)}</span><div class="bar-track"><div class="bar-fill hp${a.hp <= 30 ? " low" : ""}" style="width:${Math.max(0, a.hp)}%"></div></div><span>${a.hp}</span></div>
        <div class="bar${enFlux}"><span class="b-ic b-en">${icon("bolt", 11)}</span><div class="bar-track"><div class="bar-fill en" style="width:${Math.max(0, a.energy)}%"></div></div><span>${a.energy}</span></div>
      </div>
      <div class="c-meta"><span>${icon("bread", 10)} ${a.items.food} ${icon("ore", 10)} ${a.items.ore} ${weaponTxt}${a.kills ? " " + icon("skull", 10) + a.kills : ""}</span><span>${esc(a.model)}</span></div>
      <div class="c-meta" title="累计费用 ${costTxt}${u.cache_est ? "；命中率为本地估算（该 provider 不返回缓存字段）" : ""}"><span>${icon("hash", 10)} ${fmtTok(u.prompt + u.completion)}</span><span>${cacheTxt || "—"}</span></div>
      <details class="c-thought" title="点击展开/收起想法"><summary>${icon("thought", 10)} ${esc(preview)}</summary><div>${esc(t)}</div></details>`;
    box.appendChild(d);
  }
  $("alive").textContent = `存活 ${s.agents.filter(x => x.alive).length}/${s.agents.length}`;
  const mt = s.max_turns || 0;
  $("turn").textContent = mt > 0 ? `回合 ${s.turn}/${mt}` : `回合 ${s.turn}`;
  const night = s.day_night === "night";
  $("daynight").innerHTML = `${icon(night ? "moon" : "sun", 12)} ${night ? "夜晚" : "白天"}` +
    (s.cycle_turn ? ` ${esc(s.cycle_turn)}/24` : "");
  $("speed").value = s.speed;
  $("speed-val").textContent = s.speed + "x";
  $("demo-note").classList.toggle("hidden", !s.demo);
}

function updateStatus() {
  $("runstate").innerHTML = state.running ? `${icon("play", 11)} 运行中` : `${icon("pause", 11)} 已暂停`;
  $("btn-play").innerHTML = state.running ? `${icon("pause", 13)} 暂停` : `${icon("play", 13)} 开始`;
  if (state.snapshot && state.snapshot.winner && !state.running) {
    showVictory(state.snapshot.winner);
  }
}
function render() {
  renderMap(); renderAgents(); updateStatus();
  if (!$("rel-panel").classList.contains("hidden")) drawRelations();
  if (!$("god-panel").classList.contains("hidden")) fillGodTargets();
}

/* ---------------- 日志 ---------------- */
const KIND_FILTER = {
  all: null,
  talk: ["talk"],
  think: ["think"],
  fight: ["fight", "death"],
  trade: ["trade"],
  sys: ["sys", "move", "item", "god", "event", "commentary", "review"],
};

/* 日志 kind -> 行首 SVG 小图标 */
const KIND_ICONS = {
  talk: "chat", think: "thought", fight: "swords", death: "skull", trade: "trade",
  sys: "gear", move: "move", item: "box", god: "eye", event: "spark", commentary: "broadcast",
  review: "broadcast",
};

/* 后端日志字符串行首内嵌的 UI emoji（💀💭⚔️…）在前端渲染时剥掉，换成 kind 图标；
   正文中间模型发言内容里的 emoji 原样保留 */
const LEAD_EMOJI_RE = /^(?:(?:[\u{1F000}-\u{1FAFF}\u{2600}-\u{27BF}\u{2B00}-\u{2BFF}]\uFE0F?(?:\u200D[\u{1F000}-\u{1FAFF}\u{2600}-\u{27BF}]\uFE0F?)*)+\s*)+/u;
const stripLeadEmoji = text => String(text == null ? "" : text).replace(LEAD_EMOJI_RE, "");

function addLog(m) {
  if (!state.lines) state.lines = [];
  state.lines.push({ kind: m.kind, text: m.text, turn: m.turn });
  if (state.lines.length > 800) state.lines.shift();
  appendLine(state.lines[state.lines.length - 1]);
  if (m.kind === "death") showKillBanner(m.text); // 击杀/死亡全屏播报
  if (m.kind === "commentary") onCommentaryLog(m.text);
}
function appendLine(line) {
  const el = document.createElement("div");
  el.className = "l " + line.kind;
  el.dataset.kind = line.kind;
  const ic = KIND_ICONS[line.kind] || "gear";
  el.innerHTML = `<span class="l-turn">T${esc(line.turn)}</span><span class="l-ic">${icon(ic, 12)}</span>`;
  el.appendChild(document.createTextNode(stripLeadEmoji(line.text)));
  $("log").appendChild(el);
  const wrap = $("log");
  const nearBottom = wrap.scrollTop + wrap.clientHeight > wrap.scrollHeight - 60;
  if (nearBottom) wrap.scrollTop = wrap.scrollHeight;
  applyFilterLine(el);
}
function applyFilterLine(el) {
  const f = KIND_FILTER[state.filter];
  el.style.display = (f === null || f.includes(el.dataset.kind)) ? "" : "none";
}
function applyFilter() { document.querySelectorAll("#log .l").forEach(applyFilterLine); }

/* ---------------- 解说员与语音 ---------------- */
function updateCommentary(text) {
  if (!text) return;
  const el = $("commentary-text");
  el.textContent = text;
  $("commentary").classList.remove("hidden");
}

function stripCommentaryPrefix(text) {
  return String(text == null ? "" : text).replace(/^📣\s*解说[：:]?\s*/, "");
}

function initSpeechVoices() {
  if (!synth) return;
  const pick = () => {
    const voices = synth.getVoices() || [];
    speechVoice = voices.find(v => v.lang && v.lang.toLowerCase().startsWith("zh")) || voices[0] || null;
  };
  pick();
  if (synth.onvoiceschanged !== undefined) {
    synth.onvoiceschanged = pick;
  }
}
initSpeechVoices();

function speakCommentary(text) {
  if (!speechOn || !synth || !text) return;
  try {
    synth.cancel();
    const u = new SpeechSynthesisUtterance(text);
    if (speechVoice) u.voice = speechVoice;
    u.lang = speechVoice ? speechVoice.lang : "zh-CN";
    u.rate = 1.05;
    u.pitch = 1.0;
    synth.speak(u);
  } catch (e) {
    console.error("[speech]", e);
  }
}

/* 解说日志也更新滚动条并朗读 */
function onCommentaryLog(text) {
  const clean = stripCommentaryPrefix(text);
  updateCommentary(clean);
  speakCommentary(clean);
}

$("btn-sound").onclick = () => {
  speechOn = !speechOn;
  $("btn-sound").classList.toggle("on", speechOn);
  if (!speechOn && synth) synth.cancel();
};

/* ---------------- 控制 ---------------- */
function showBanner(text, icName = "warning") {
  const b = $("banner");
  b.innerHTML = `${icon(icName, 20)}<span>${esc(text)}</span>`;
  b.classList.remove("hidden");
}
function hideBanner() { $("banner").classList.add("hidden"); }

/* 胜利/结算横幅：胜者 + 称号；点击打开结算面板 */
function showVictory(name) {
  const s = state.snapshot;
  const a = s && s.agents.find(x => x.name === name);
  const icn = a ? avatarIconName(a.emoji) : "trophy";
  const titles = (s && s.game_over && s.game_over.titles) || {};
  const titleEm = { "生存冠军": "🏆", "霸主": "⚔️", "富翁": "💰", "外交家": "🤝" };
  const titleParts = Object.entries(titles).map(([t, n]) => `${titleEm[t] || ""}${esc(t)} ${esc(n)}`);
  $("banner").innerHTML = `<span class="v-emoji">${icon(icn, 44)}</span>
    <span class="v-text"><span class="v-title">${icon("trophy", 12)} WINNER</span><span class="v-name">${esc(name)}</span>${titleParts.length ? `<span class="v-titles">${titleParts.join(" · ")}</span>` : ""}</span>`;
  $("banner").classList.remove("hidden");
  renderSettlement();
  // 自动弹出结算面板（延迟让用户先看到横幅）
  if (!$("settle-panel").classList.contains("hidden")) return;
  setTimeout(() => {
    if (state.snapshot && state.snapshot.winner && !state.running) {
      $("settle-panel").classList.remove("hidden");
    }
  }, 900);
}

function renderSettlement() {
  const s = state.snapshot;
  if (!s || !s.game_over) return;
  const go = s.game_over;
  const w = go.titles && go.titles["生存冠军"];
  const a = s.agents.find(x => x.name === w);
  const icn = a ? avatarIconName(a.emoji) : "trophy";
  $("settle-winner").innerHTML = `${icon(icn, 32)} <b>${esc(w || "—")}</b> ${go.reason === "max_turns" ? "（回合上限评分结算）" : "（最后幸存者）"}`;
  const titleEls = Object.entries(go.titles || {}).map(([t, n]) => {
    const em = { "生存冠军": "🏆", "霸主": "⚔️", "富翁": "💰", "外交家": "🤝" }[t] || "";
    return `<span class="st-tag">${em} ${esc(t)}：${esc(n)}</span>`;
  }).join("");
  $("settle-titles").innerHTML = titleEls || "<span class=\"st-tag\">—</span>";
  const rows = go.rankings || [];
  let html = "<tr><th>名次</th><th>选手</th><th>存活</th><th>击杀</th><th>资源</th><th>关系</th></tr>";
  if (!rows.length) {
    html += `<tr><td colspan="6" style="color:#8b98a5">暂无数据</td></tr>`;
  } else {
    rows.forEach((r, i) => {
      html += `<tr><td>${i + 1}</td><td>${esc(r.name)}</td><td>${r.alive ? "是" : "否"}</td><td>${r.kills}</td><td>${r.resources}</td><td>${r.relation_total}</td></tr>`;
    });
  }
  $("settle-table").innerHTML = html;
  const review = s.match_review;
  $("settle-review").innerHTML = review
    ? `<div class="st-review-label">${icon("broadcast", 12)} AI 复盘</div><div class="st-review-text">${esc(review)}</div>`
    : `<div class="st-review-placeholder">AI 复盘中…</div>`;
}

function onReview(text) {
  if (!text) return;
  const box = $("settle-review");
  if (!box) return;
  box.innerHTML = `<div class="st-review-label">${icon("broadcast", 12)} AI 复盘</div><div class="st-review-text">${esc(text)}</div>`;
  // 如果复盘在游戏结束后才到达，且结算面板未打开，自动弹出
  if (state.snapshot && state.snapshot.game_over && !state.running && $("settle-panel").classList.contains("hidden")) {
    $("settle-panel").classList.remove("hidden");
  }
}

$("banner").onclick = () => {
  if (state.snapshot && state.snapshot.game_over) {
    renderSettlement();
    $("settle-panel").classList.remove("hidden");
  }
};

/* 击杀/死亡顶部全屏播报（2 秒淡出） */
let killTimer = null;
function showKillBanner(text) {
  const b = $("killbanner");
  b.innerHTML = `${icon("skull", 26)}<span>${esc(text)}</span>`;
  b.classList.remove("hidden", "pop");
  void b.offsetWidth; // 重启动画
  b.classList.add("pop");
  clearTimeout(killTimer);
  killTimer = setTimeout(() => b.classList.add("hidden"), 2100);
}

$("btn-play").onclick = () => send({ type: "cmd", action: state.running ? "pause" : "start" });
$("btn-step").onclick = () => send({ type: "cmd", action: "step" });
$("btn-reset").onclick = () => {
  send({ type: "cmd", action: "reset" });
  state.lines = [];
  $("log").innerHTML = "";
  hideBanner();
  $("settle-panel").classList.add("hidden");
};
$("speed").oninput = e => {
  $("speed-val").textContent = e.target.value + "x";
  send({ type: "cmd", action: "speed", value: parseFloat(e.target.value) });
};
/* ---------------- 上帝面板（传话：单人/多人/全体，可附带挑拨） ---------------- */
$("btn-god").onclick = () => {
  $("god-panel").classList.toggle("hidden");
  fillGodTargets();
};

function fillGodTargets() {
  const s = state.snapshot;
  if (!s) return;
  const box = $("gm-targets");
  const checked = new Set([...box.querySelectorAll("input:checked")].map(c => c.value));
  const alive = s.agents.filter(a => a.alive);
  let html = `<label><input type="checkbox" value="__all__" ${checked.has("__all__") ? "checked" : ""}> ${icon("broadcast", 12)} 全体</label>`;
  for (const a of alive) {
    html += `<label><input type="checkbox" value="${esc(a.name)}" ${checked.has(a.name) ? "checked" : ""}> ${icon(avatarIconName(a.emoji), 13)} ${esc(a.name)}</label>`;
  }
  box.innerHTML = html;
  box.querySelectorAll("input").forEach(cb => { cb.onchange = onGodTargetChange; });
  updateSowState();
}

/* 全体与具体人选互斥；刷新挑拨勾选可用性 */
function onGodTargetChange(e) {
  const box = $("gm-targets");
  if (e.target.value === "__all__" && e.target.checked) {
    box.querySelectorAll("input").forEach(c => { if (c.value !== "__all__") c.checked = false; });
  } else if (e.target.checked) {
    box.querySelector('input[value="__all__"]').checked = false;
  }
  updateSowState();
}

function godRecipients() {
  const box = $("gm-targets");
  if (box.querySelector('input[value="__all__"]')?.checked) return "all";
  return [...box.querySelectorAll("input:checked")].map(c => c.value);
}

function updateSowState() {
  const s = state.snapshot;
  const r = godRecipients();
  const n = r === "all" ? (s ? s.agents.filter(a => a.alive).length : 0) : r.length;
  const sow = $("gm-sow");
  sow.disabled = n < 2;
  if (n < 2) sow.checked = false;
}

function godMsgSend() {
  const text = $("gm-text").value.trim();
  const targets = godRecipients();
  if (!text || (targets !== "all" && !targets.length)) return;
  send({ type: "god_msg", targets, text, sow: $("gm-sow").checked && !$("gm-sow").disabled });
  $("gm-text").value = "";
}
$("gm-btn").onclick = godMsgSend;
$("gm-text").onkeydown = e => { if (e.key === "Enter") godMsgSend(); };

/* ---------------- 一键导出 ---------------- */
$("btn-export").onclick = async () => {
  let data;
  try { data = await (await fetch("/api/export")).json(); }
  catch (e) { showBanner("导出失败"); setTimeout(hideBanner, 2000); return; }
  const ts = new Date();
  const p = n => String(n).padStart(2, "0");
  const name = `ai大战_${ts.getFullYear()}${p(ts.getMonth() + 1)}${p(ts.getDate())}_${p(ts.getHours())}${p(ts.getMinutes())}${p(ts.getSeconds())}.json`;
  const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
};

/* ---------------- 开局设置面板 ---------------- */
const TRAIT_LABELS = { aggression: "攻击性", sociability: "社交性", greed: "贪婪", paranoia: "多疑" };
const DIFF_DEFS = [
  ["energy_drain", "能量每回合消耗", 0, 5, 1],
  ["hp_drain", "能量归零后生命损耗", 0, 10, 1],
  ["damage_mult", "攻击伤害倍率", 0.5, 2.0, 0.1],
  ["event_prob", "世界事件概率", 0, 0.3, 0.01],
  ["gather_mult", "采集成功率倍率", 0.5, 2.0, 0.1],
];
let setupData = null; // {agents, providers, world}

$("btn-setup").onclick = async () => {
  $("setup-panel").classList.remove("hidden");
  $("setup-msg").textContent = "";
  try { setupData = await (await fetch("/api/setup")).json(); }
  catch (e) { setupData = null; $("setup-msg").textContent = "读取配置失败"; return; }
  const ro = state.running;
  $("setup-ro").classList.toggle("hidden", !ro);
  $("setup-apply").disabled = ro;
  $("setup-save").disabled = ro;
  renderSetup();
};

function renderSetup() {
  if (!setupData) return;
  const ro = state.running;
  const box = $("setup-agents");
  box.innerHTML = "";
  setupData.agents.forEach((a, i) => box.appendChild(renderAgentCard(a, i, ro)));
  // 难度区
  const diff = $("setup-diff");
  diff.innerHTML = "";
  for (const [key, label, min, max, step] of DIFF_DEFS) {
    const v = setupData.world[key];
    const row = document.createElement("div");
    row.className = "d-row";
    row.innerHTML = `<span>${label}</span>
      <input type="range" min="${min}" max="${max}" step="${step}" value="${v}" data-k="${key}" ${ro ? "disabled" : ""}>
      <span class="d-val">${v}</span>`;
    const slider = row.querySelector("input");
    slider.oninput = () => {
      row.querySelector(".d-val").textContent = slider.value;
      setupData.world[key] = parseFloat(slider.value);
    };
    diff.appendChild(row);
  }
}

function renderAgentCard(a, i, ro) {
  const d = document.createElement("div");
  d.className = "setup-agent";
  const provOpts = Object.entries(setupData.providers)
    .map(([k, p]) => `<option value="${esc(k)}" ${k === a.provider ? "selected" : ""}>${esc(p.name)} (${esc(k)})</option>`).join("");
  const traits = Object.entries(TRAIT_LABELS).map(([k, label]) => `
    <label class="sa-trait">${label}
      <input type="range" min="0" max="1" step="0.05" value="${a.traits[k] ?? 0.5}" data-trait="${k}" ${ro ? "disabled" : ""}>
      <span class="tv">${(a.traits[k] ?? 0.5).toFixed(2)}</span></label>`).join("");
  const avatarButtons = AVATAR_CHOICES.map(({ emoji, iconName }) =>
    `<button type="button" class="sa-avatar-btn ${a.emoji === emoji ? "selected" : ""}" data-emoji="${esc(emoji)}" title="${esc(emoji)}" ${ro ? "disabled" : ""}>${icon(iconName, 18)}</button>`
  ).join("");
  d.innerHTML = `
    <div class="sa-head">
      <div class="sa-avatar-picker">
        ${avatarButtons}
        <input type="text" class="sa-emoji" value="${esc(a.emoji)}" maxlength="4" title="自定义 emoji" ${ro ? "disabled" : ""}>
      </div>
      <input type="text" class="sa-name" value="${esc(a.name)}" placeholder="名字" ${ro ? "disabled" : ""}>
      <input type="text" class="sa-role" value="${esc(a.role)}" placeholder="角色" ${ro ? "disabled" : ""}>
      <button class="sa-del" ${ro ? "disabled" : ""}>删除</button>
    </div>
    <div class="sa-provs">
      <select class="sa-provider" ${ro ? "disabled" : ""}>${provOpts}</select>
      <select class="sa-model" ${ro ? "disabled" : ""}></select>
    </div>
    <div class="sa-traits">${traits}</div>
    <label class="sa-field"><span>背景</span><textarea data-f="backstory" ${ro ? "disabled" : ""}>${esc(a.backstory)}</textarea></label>
    <label class="sa-field"><span>性格</span><textarea data-f="personality" ${ro ? "disabled" : ""}>${esc(a.personality)}</textarea></label>
    <label class="sa-field"><span>策略</span><textarea data-f="strategy" ${ro ? "disabled" : ""}>${esc(a.strategy)}</textarea></label>`;
  /* 头像选择器交互 */
  const picker = d.querySelector(".sa-avatar-picker");
  const emojiInput = picker.querySelector(".sa-emoji");
  const updateAvatarSelection = () => {
    const val = emojiInput.value.trim();
    picker.querySelectorAll(".sa-avatar-btn").forEach(b => b.classList.toggle("selected", b.dataset.emoji === val));
  };
  picker.querySelectorAll(".sa-avatar-btn").forEach(btn => {
    btn.onclick = () => {
      emojiInput.value = btn.dataset.emoji;
      updateAvatarSelection();
    };
  });
  emojiInput.addEventListener("input", updateAvatarSelection);
  /* 文本框随内容自动撑高 */
  d.querySelectorAll("textarea").forEach(ta => {
    const grow = () => { ta.style.height = "auto"; ta.style.height = ta.scrollHeight + "px"; };
    ta.addEventListener("input", grow);
    requestAnimationFrame(grow);
  });
  const provSel = d.querySelector(".sa-provider");
  const modelSel = d.querySelector(".sa-model");
  const fillModels = keep => {
    const models = (setupData.providers[provSel.value] || {}).models || [];
    modelSel.innerHTML = models.map(m => `<option value="${esc(m)}" ${m === keep ? "selected" : ""}>${esc(m)}</option>`).join("");
    if (keep && !models.includes(keep)) {
      modelSel.innerHTML += `<option value="${esc(keep)}" selected>${esc(keep)}</option>`;
    }
  };
  fillModels(a.model);
  provSel.onchange = () => fillModels(null);
  d.querySelectorAll("input[data-trait]").forEach(sl => {
    sl.oninput = () => { sl.parentElement.querySelector(".tv").textContent = parseFloat(sl.value).toFixed(2); };
  });
  d.querySelector(".sa-del").onclick = () => {
    if (setupData.agents.length <= 2) { $("setup-msg").textContent = "至少保留 2 名选手"; return; }
    setupData.agents.splice(i, 1);
    renderSetup();
  };
  return d;
}

$("setup-add").onclick = () => {
  if (!setupData || state.running) return;
  const pk = Object.keys(setupData.providers)[0] || "deepseek";
  setupData.agents.push({
    name: "新人" + (setupData.agents.length + 1), emoji: "🤖", role: "幸存者",
    provider: pk, model: (setupData.providers[pk] || {}).models?.[0] || "",
    backstory: "", personality: "", strategy: "",
    traits: { aggression: 0.5, sociability: 0.5, greed: 0.5, paranoia: 0.5 },
  });
  renderSetup();
};

function collectSetup() {
  const cards = document.querySelectorAll("#setup-agents .setup-agent");
  const agents = [];
  for (const d of cards) {
    const traits = {};
    d.querySelectorAll("input[data-trait]").forEach(sl => { traits[sl.dataset.trait] = parseFloat(sl.value); });
    agents.push({
      name: d.querySelector(".sa-name").value.trim(),
      emoji: d.querySelector(".sa-emoji").value.trim() || "🤖",
      role: d.querySelector(".sa-role").value.trim() || "幸存者",
      provider: d.querySelector(".sa-provider").value,
      model: d.querySelector(".sa-model").value,
      backstory: d.querySelector('textarea[data-f="backstory"]').value,
      personality: d.querySelector('textarea[data-f="personality"]').value,
      strategy: d.querySelector('textarea[data-f="strategy"]').value,
      traits,
    });
  }
  return { agents, world: setupData.world };
}

$("setup-apply").onclick = () => {
  if (!setupData || state.running) return;
  send({ type: "setup", ...collectSetup() });
};
$("setup-save").onclick = () => {
  if (!setupData || state.running) return;
  send({ type: "setup_save", ...collectSetup() });
};

function onSetupResult(m) {
  if (m.ok) {
    $("setup-panel").classList.add("hidden");
    // 应用后后端已 reset，清掉旧日志等全量快照
    state.lines = [];
    $("log").innerHTML = "";
    hideBanner();
    if (m.saved) showBanner("已保存到 config.json", "save"), setTimeout(hideBanner, 2000);
  } else {
    const msg = m.error || "操作失败";
    if ($("setup-panel").classList.contains("hidden")) showBanner(msg), setTimeout(hideBanner, 2500);
    else $("setup-msg").textContent = msg;
  }
}
document.querySelectorAll("#logtabs .tab").forEach(btn => {
  btn.onclick = () => {
    document.querySelectorAll("#logtabs .tab").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    state.filter = btn.dataset.f;
    applyFilter();
  };
});

/* ---------------- 排行榜 ---------------- */
$("btn-lb").onclick = async () => {
  $("lb-panel").classList.remove("hidden");
  let data = {};
  try { data = await (await fetch("/api/stats")).json(); } catch (e) {}
  const rows = Object.values(data).sort((x, y) => y.elo - x.elo);
  let html = "<tr><th>选手</th><th>模型</th><th>场次</th><th>胜</th><th>杀</th><th>ELO</th><th>称号</th></tr>";
  if (!rows.length) html += `<tr><td colspan="7" style="color:#8b98a5">还没有打过完整的一局</td></tr>`;
  for (const r of rows) {
    const tmap = r.titles || {};
    const tstr = Object.entries(tmap).map(([k, v]) => `${esc(k)}${v > 1 ? "×" + v : ""}`).join(" ") || "—";
    html += `<tr><td>${esc(r.name)}</td><td>${esc(r.model)}</td><td>${r.games}</td><td>${r.wins}</td><td>${r.kills}</td><td>${r.elo}</td><td>${tstr}</td></tr>`;
  }
  $("lb-table").innerHTML = html;
};

/* ---------------- 关系图谱 ---------------- */
$("btn-rel").onclick = () => {
  $("rel-panel").classList.toggle("hidden");
  drawRelations();
};

function drawRelations() {
  const s = state.snapshot;
  if (!s || $("rel-panel").classList.contains("hidden")) return;
  const cv = $("rel-canvas");
  const logicalW = 420, logicalH = 420;
  setupDPR(cv, logicalW, logicalH);
  const ctx = cv.getContext("2d");
  const W = logicalW, H = logicalH, cx = W / 2, cy = H / 2;
  const R = Math.min(W, H) / 2 - 52;
  ctx.clearRect(0, 0, W, H);
  const agents = s.agents;
  const n = agents.length;
  const pos = agents.map((a, i) => {
    const ang = -Math.PI / 2 + (i * 2 * Math.PI) / n;
    return [cx + R * Math.cos(ang), cy + R * Math.sin(ang)];
  });
  // 连线：|score|>=3 才画，取双向中绝对值较大的一边
  for (let i = 0; i < n; i++) {
    for (let j = i + 1; j < n; j++) {
      const a = agents[i], b = agents[j];
      const s1 = (a.relations || {})[b.name] || 0;
      const s2 = (b.relations || {})[a.name] || 0;
      const sc = Math.abs(s1) >= Math.abs(s2) ? s1 : s2;
      if (Math.abs(sc) < 3) continue;
      const color = sc >= 3 ? "#7bb661" : "#e05b5b";
      ctx.strokeStyle = color;
      ctx.lineWidth = Math.min(5, 1 + Math.abs(sc) / 3);
      ctx.beginPath();
      ctx.moveTo(pos[i][0], pos[i][1]);
      ctx.lineTo(pos[j][0], pos[j][1]);
      ctx.stroke();
      ctx.fillStyle = color;
      ctx.font = "bold 12px sans-serif";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(sc > 0 ? "+" + sc : String(sc), (pos[i][0] + pos[j][0]) / 2, (pos[i][1] + pos[j][1]) / 2);
    }
  }
  // 节点：头像图标 + 名字，死者置灰
  agents.forEach((a, i) => {
    const [x, y] = pos[i];
    ctx.beginPath();
    ctx.arc(x, y, 20, 0, Math.PI * 2);
    ctx.fillStyle = a.alive ? "#202834" : "#151a20";
    ctx.fill();
    ctx.strokeStyle = a.alive ? "#e8b13a" : "#4b5563";
    ctx.lineWidth = 2;
    ctx.stroke();
    ctx.globalAlpha = a.alive ? 1 : 0.4;
    drawIcon(ctx, a.alive ? avatarIconName(a.emoji) : "skull", x, y, 19, a.alive ? "#dbe3ec" : "#8b98a5");
    ctx.font = "11px sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillStyle = "#dbe3ec";
    ctx.fillText(a.name, x, y + 32);
    ctx.globalAlpha = 1;
  });
}

/* ---------------- 回放 ---------------- */
const rp = { active: false, msgs: [], idx: 0, playing: false, timer: null };

$("btn-replay").onclick = async () => {
  $("rp-list").classList.remove("hidden");
  let list = [];
  try { list = await (await fetch("/api/replays")).json(); } catch (e) {}
  const box = $("rp-items");
  box.innerHTML = list.length
    ? ""
    : `<div style="color:#8b98a5;padding:12px">还没有回放文件，先打一局吧</div>`;
  for (const r of list) {
    const d = document.createElement("div");
    d.className = "rp-item";
    const kb = (r.size / 1024).toFixed(1);
    const dt = new Date(r.mtime * 1000).toLocaleString();
    d.innerHTML = `<span>${esc(r.name)}</span><span class="meta">${dt} · ${kb} KB</span>`;
    d.onclick = () => startReplay(r.name);
    box.appendChild(d);
  }
};

document.querySelectorAll(".panel-close").forEach(btn => {
  btn.onclick = () => $(btn.dataset.close).classList.add("hidden");
});

async function startReplay(name) {
  let text = "";
  try { text = await (await fetch("/api/replays/" + encodeURIComponent(name))).text(); }
  catch (e) { return; }
  const msgs = text.split("\n").filter(Boolean)
    .map(l => { try { return JSON.parse(l); } catch (e) { return null; } })
    .filter(m => m && m.type !== "meta");
  if (!msgs.length) return;
  $("rp-list").classList.add("hidden");
  rp.active = true;
  rp.msgs = msgs;
  rp.idx = 0;
  $("replaybar").classList.remove("hidden");
  $("controls").classList.add("hidden");
  $("godbox").classList.add("hidden");
  $("rp-slider").max = Math.max(0, msgs.length - 1);
  resetView();
  seekReplay(0);
  setRpPlaying(true);
}

function resetView() {
  state.lines = [];
  $("log").innerHTML = "";
  state.snapshot = null;
  state.running = false;
  hideBanner();
  $("killbanner").classList.add("hidden");
  terrainVer = -1; // 强制重建地形缓存
  for (const k of Object.keys(anim.agents)) delete anim.agents[k];
}

/* 跳到第 i 条消息：从头快放到 i（保证增量地图缓存正确） */
function seekReplay(i) {
  resetView();
  for (let k = 0; k <= i && k < rp.msgs.length; k++) applyMsg(rp.msgs[k]);
  rp.idx = i;
  updateRpUI();
}

/* 前进到下一条 snapshot（中间的 log/status 一并应用） */
function stepReplay() {
  if (rp.idx >= rp.msgs.length - 1) { setRpPlaying(false); return; }
  let j = rp.idx + 1;
  while (j < rp.msgs.length - 1 && rp.msgs[j].type !== "snapshot") j++;
  for (let k = rp.idx + 1; k <= j; k++) applyMsg(rp.msgs[k]);
  rp.idx = j;
  updateRpUI();
}

function updateRpUI() {
  $("rp-slider").value = rp.idx;
  $("rp-pos").textContent = `${rp.idx + 1}/${rp.msgs.length}`;
}

function scheduleRp() {
  clearTimeout(rp.timer);
  if (rp.playing) {
    rp.timer = setTimeout(() => { stepReplay(); scheduleRp(); }, 600 / parseFloat($("rp-speed").value));
  }
}
function setRpPlaying(p) {
  rp.playing = p;
  $("rp-play").innerHTML = icon(p ? "pause" : "play", 13);
  scheduleRp();
}

$("rp-play").onclick = () => setRpPlaying(!rp.playing);
$("rp-speed").onchange = scheduleRp;
$("rp-slider").oninput = e => seekReplay(parseInt(e.target.value, 10));
$("rp-exit").onclick = () => {
  rp.active = false;
  rp.playing = false;
  clearTimeout(rp.timer);
  $("replaybar").classList.add("hidden");
  $("controls").classList.remove("hidden");
  $("godbox").classList.remove("hidden");
  resetView();
  if (ws) ws.close(); // onclose 自动重连，服务端会补发全量快照和历史
};

/* ---------------- 侧栏分隔条：拖拽调整卡片区/日志区高度 ---------------- */
(function sideSplitter() {
  const bar = $("sidesplit"), agentsBox = $("agents"), side = $("side");
  if (!bar || !agentsBox || !side) return;
  bar.addEventListener("mousedown", e => {
    e.preventDefault();
    const startY = e.clientY;
    const startH = agentsBox.getBoundingClientRect().height;
    const sideH = side.getBoundingClientRect().height;
    bar.classList.add("drag");
    document.body.classList.add("row-resize");
    const onMove = ev => {
      let h = startH + ev.clientY - startY;
      h = Math.max(110, Math.min(sideH - 180, h)); // 卡片区最小 110，日志区至少留 180
      agentsBox.style.height = h + "px";
    };
    const onUp = () => {
      bar.classList.remove("drag");
      document.body.classList.remove("row-resize");
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
    };
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  });
})();

connect();
