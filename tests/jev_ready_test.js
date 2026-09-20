/* 闭环测试：一板球到底问了几次？多次决策能不能修正落点？ */
var els = {}, listeners = {}, pending = [], calls = [], arcLog = [];
var clock = 0, rafCb = null, frameNo = 0;
var latencyMs = 380, MODEL_ERR_PX = 260;   // 球还很远时的判断误差（会随球靠近而缩小）
function mkEl(id) { var set = {};
  return { id: id, style: {}, textContent: '', title: '', innerHTML: '', width: 0, height: 0, onclick: null, value: '',
    dataset: {}, classList: { toggle: function (c, on) { if (on === undefined) set[c] = !set[c]; else set[c] = !!on; },
      add: function (c) { set[c] = true; }, remove: function (c) { set[c] = false; }, contains: function (c) { return !!set[c]; } },
    addEventListener: function (t, f) { (listeners[id + ':' + t] = listeners[id + ':' + t] || []).push(f); },
    getBoundingClientRect: function () { return { top: 0, left: 0, width: 1000, height: 625 }; },
    appendChild: function () {}, blur: function () {}, focus: function () {}, getContext: function () { return ctx; } }; }
var ctx = { measureText: function (t) { return { width: String(t).length * 7 }; },
  createLinearGradient: function () { return { addColorStop: function () {} }; },
  createRadialGradient: function () { return { addColorStop: function () {} }; } };
['clearRect','fillRect','beginPath','moveTo','lineTo','arcTo','closePath','fill','stroke','save','restore',
 'translate','setTransform','setLineDash','scale','rotate','ellipse','fillText'].forEach(function (m) { if (!ctx[m]) ctx[m] = function () {}; });
ctx.arc = function (x, y, r) { if (Math.abs(r - 10) < 1e-6) arcLog.push({ x: x, y: y, f: frameNo }); };
var document = { getElementById: function (id) { return els[id] || (els[id] = mkEl(id)); }, createElement: function () { return mkEl('n'); } };
var window = { devicePixelRatio: 2, addEventListener: function (t, f) { (listeners['window:' + t] = listeners['window:' + t] || []).push(f); } };
var location = { protocol: 'http:', origin: 'http://127.0.0.1:8760' };
var localStorage = { getItem: function () { return null; }, setItem: function () {} };
var performance = { now: function () { return clock; } };
function requestAnimationFrame(cb) { rafCb = cb; }
function AbortController() { this.signal = { aborted: false }; this.abort = function () {}; }
var setTimeout = function () { return 0; }, clearTimeout = function () {};
var PROBE = null;
function fold(y, lo, hi) { var s = hi - lo; var t = (y - lo) % (2 * s); if (t < 0) t += 2 * s; return t <= s ? lo + t : lo + (2 * s - t); }
function decide(st) {
  var tb = st.table, b = st.ball, you = st.you;
  var lo = tb.y_top + b.r, hi = tb.y_bottom - b.r;
  var ps = []; var step = (hi - you.paddle_half * 2) / 7;   // 与服务器同构：7 个可达拍位
  for (var i = 0; i < 7; i++) ps.push(lo + you.paddle_half + step * (i + 0.5) - you.paddle_half);
  var real = fold(b.y + b.vy * ((you.paddle_x - b.r - b.x) / b.vx), lo, hi);
  // 每次决策故意换一个位置：如果拍子最后停在最后一次决策说的位置，说明修正生效了。
  var target = ps[calls.length % ps.length];
  var best = 0, bd = 1e9;
  for (var j = 0; j < ps.length; j++) { var d = Math.abs(ps[j] - target); if (d < bd) { bd = d; best = j; } }
  if (st.kind === 'ready') {   // 待命位问法：桩模型永远答「正中心」
    return { ok: true, move_to: you.paddle_center, recover_to: 338.5, ready: 'p3', speed: you.max_speed,
      place: null, place_y: null, band_confidence: 0.4, usage: { input_tokens: 905 }, cost_usd: 0.000038, trace: {} };
  }
  return { ok: true, move_to: ps[best], recover_to: ps[best], speed: you.max_speed, place: 'p' + best,
    place_y: ps[best], band_confidence: 0.3, usage: { input_tokens: 905 }, cost_usd: 0.000038, trace: {},
    _askedAtBallX: b.x, _truth: real, _err: Math.abs(ps[best] - real) };
}
var fetch = function (url, opts) {
  return new Promise(function (res) {
    if (url.indexOf('/health') >= 0) { res({ json: function () { return Promise.resolve({ ok: true, model: 'jev-latest', mode: 'pure', pure_speed_cap_px_s: 332 }); } }); return; }
    var st = JSON.parse(opts.body);
    pending.push({ t: 0, due: latencyMs, st: st, res: res });
  });
};
function settle() {
  for (var i = pending.length - 1; i >= 0; i--) { var p = pending[i]; p.t += 1000 / 60; if (p.t < p.due) continue;
    pending.splice(i, 1); var d = decide(p.st); calls.push(d); p.res({ json: function () { return Promise.resolve(d); } }); }
  drainMicrotasks();
}
function step() { clock += 1000 / 60; frameNo++; var cb = rafCb; rafCb = null; cb(clock); settle(); }
function fire(tg, ty, ev) { var ls = listeners[tg + ':' + ty] || []; for (var i = 0; i < ls.length; i++) ls[i](ev); }
function ball() { return arcLog.length ? arcLog[arcLog.length - 1] : null; }
var fails = 0;
function pass(n, c, e) { print((c ? 'PASS  ' : 'FAIL  ') + n + (e ? '   [' + e + ']' : '')); if (!c) fails++; }

/* 跑一板球：从球转向 JEV 到它到达拍面，数这期间问了几次 */
function approach(maxFrames) {
  var asked = [], prevVx = null, started = false, contact = null;
  for (var i = 0; i < maxFrames; i++) {
    var b = ball(); if (b) fire('game', 'mousemove', { clientY: b.y });
    var nBefore = calls.length;
    step();
    var p = window.__probe();
    if (!started && p && p.ballVx > 0 && p.ballX < p.jevX - 200) started = true;
    if (started && calls.length > nBefore) asked.push(calls[calls.length - 1]);
    // 一直刷新，取「球被弹回之前的最后一帧」拍心，就是接触瞬间它站的位置
    if (started && p && p.ballVx > 0 && p.ballX + 10 >= p.jevX - 40) contact = p.jevCenter;
    if (started && p && p.ballVx < 0) return { asked: asked, hit: true, contact: contact };
    if (started && p && p.ballX > p.jevX + 40) return { asked: asked, hit: false, contact: contact };
  }
  return { asked: asked, hit: false };
}

new Function(readFile('tests/.build_probe.js'))();
document.getElementById('btnStart').onclick({ target: { blur: function () {} } });
for (var w = 0; w < 240; w++) step();       // 跳过开局倒计时

PROBE = window.__probe();
print('# 球速 ' + Math.round(PROBE.ballVx || 0) + ' px/s · 延迟 ' + latencyMs + 'ms');


var askedKinds = {};
var origFetch = fetch;
fetch = function (url, opts) {
  if (url.indexOf('/jev/decide') >= 0) { var s2 = JSON.parse(opts.body); askedKinds[s2.kind] = (askedKinds[s2.kind] || 0) + 1; }
  return origFetch(url, opts);
};
for (var k in askedKinds) delete askedKinds[k];

/* 打完一板：球转向人类那侧。从这一帧起一直采样到问出待命位为止 */
var r = approach(1400);
print('# 这一板它问了 ' + r.asked.length + ' 次拦截决策');

var land = null, tBefore = null, rBefore = null, settled = null, opp = 0;
for (var i = 0; i < 1200; i++) {
  var a = window.__probe();
  var tb = a.target, rb = a.recoverTo, wasVx = a.ballVx;
  var bb = ball(); if (bb) fire('game', 'mousemove', { clientY: bb.y });   // 人类继续打
  step();
  var b = window.__probe();
  if (wasVx < 0 && b.ballVx > 0) opp++;
  if (!land && Math.abs(b.recoverTo - 338.5) < 0.6 && Math.abs(rb - 338.5) > 0.6) {
    land = b; tBefore = tb; rBefore = rb;      // 待命答案就在这一帧落地
  }
  if (b.ballVx < 0 && b.ballX < 620) settled = b.jevCenter;   // 球还在飞离它时，它站在哪
}

pass('球飞离它时会问「待命位」（kind=ready）', (askedKinds.ready || 0) >= 1,
  '各类决策 ' + JSON.stringify(askedKinds) + ' · 完整周期里球来回 ' + opp + ' 次');
pass('待命答案落地：recoverTo 变成它选的正中心 338.5',
  land !== null, land === null ? '没等到' : 'recoverTo ' + rBefore.toFixed(1) + ' → ' + land.recoverTo.toFixed(1));
pass('待命决策只改 recoverTo，不覆盖拦截目标 target',
  land !== null && Math.abs(land.target - tBefore) < 0.6,
  land === null ? '—' : 'target ' + tBefore.toFixed(1) + ' → ' + land.target.toFixed(1));
pass('球飞离期间它真的走到 338.5 等下一板（不再是停在上次击球处）',
  settled !== null && Math.abs(settled - 338.5) < 6,
  '实际拍心 y=' + (settled === null ? '?' : settled.toFixed(1)));

print('');
print(fails === 0 ? 'READY POSITION: ALL PASS' : fails + ' CHECK(S) FAILED');
