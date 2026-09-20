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
  var target = real;
  var best = 0, bd = 1e9;
  for (var j = 0; j < ps.length; j++) { var d = Math.abs(ps[j] - target); if (d < bd) { bd = d; best = j; } }
  return { ok: true, move_to: ps[best], recover_to: ps[best], speed: you.max_speed, place: 'p' + best,
    place_y: ps[best], band_confidence: 0.3, usage: { input_tokens: 905 }, cost_usd: 0.000038, trace: {},
    _askedAtBallX: b.x, _truth: real, _err: Math.abs(ps[best] - real) };
}
var fetch = function (url, opts) {
  return new Promise(function (res) {
    if (url.indexOf('/health') >= 0) { res({ json: function () { return Promise.resolve({ ok: true, model: 'jev-latest', mode: 'pure', pure_speed_cap_px_s: 551 }); } }); return; }
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
for (var w = 0; w < 60; w++) step();        // 只跳过一点点：采样必须覆盖到第一个发球

PROBE = window.__probe();
print('# 球速 ' + Math.round(PROBE.ballVx || 0) + ' px/s · 延迟 ' + latencyMs + 'ms');


/* 一板球里的球速轨迹：发球起步 → 每被击一次 ×SPEEDUP → 顶到上限 */
var cap = window.__probe().cap;
var serveSpeeds = [], speeds = [], steps = [];
var prevPhase = null, maxSpeed = 0, over = 0;
for (var f = 0; f < 6000; f++) {
  var b = ball(); if (b) fire('game', 'mousemove', { clientY: b.y });
  step();
  var p = window.__probe();
  if (prevPhase === 'serve' && p.phase === 'rally') serveSpeeds.push(p.ballSpeed);   // 刚发球那一帧
  prevPhase = p.phase;
  if (p.phase === 'rally' && p.ballSpeed > 0) {
    if (speeds.length === 0 || Math.abs(p.ballSpeed - speeds[speeds.length - 1]) > 1e-6) {
      if (steps.indexOf(p.ballSpeed) < 0) steps.push(p.ballSpeed);
      speeds.push(p.ballSpeed);
    }
    maxSpeed = Math.max(maxSpeed, p.ballSpeed);
    if (p.ballSpeed > cap + 1e-6) over++;
  }
}
var frac = window.__probe().rallyStartFrac;
print('# 上限 ' + cap.toFixed(0) + ' px/s · 起步比例 ' + frac + ' ⇒ 应当 ' + (cap * frac).toFixed(0) + ' px/s · SPEEDUP=1.10');
print('# 观测到 ' + serveSpeeds.length + ' 次发球 · ' + steps.length + ' 个球速档位');

/* 判据用「serve→rally 那一帧」的球速，也就是真正的发球速度。
   不能用 steps 的最小值：热身结束点会随球速变化，球变快后热身就盖过了第一个发球。 */
var servMin = serveSpeeds.length ? Math.min.apply(null, serveSpeeds) : null;
pass('发球起步 = 上限的 ' + (frac * 100).toFixed(0) + '%（不是一上来就顶到上限）',
  servMin !== null && Math.abs(servMin - cap * frac) < 3,
  '观测到 ' + serveSpeeds.length + ' 次发球，球速 ' + serveSpeeds.map(function (x) { return x.toFixed(0); }).join('/') +
  ' · 理论上限的 ' + (frac * 100).toFixed(0) + '% = ' + (cap * frac).toFixed(0) + ' px/s');

var mono = true;
for (var i = 1; i < steps.length; i++) if (steps[i] < steps[i - 1] - 1e-6) mono = false;
pass('球速只往上走，从不回退', mono, '档位序列 ' + steps.map(function (x) { return x.toFixed(0); }).join(' → '));
pass('球速从不超过上限', over === 0 && maxSpeed <= cap + 1e-6,
  '最高 ' + maxSpeed.toFixed(1) + ' ≤ ' + cap.toFixed(0) + '（超限帧数 ' + over + '）');
pass('出现了多级台阶（确实是「逐渐加速」）', steps.length >= 4,
  steps.length + ' 个档位');
if (steps.length >= 2) pass('相邻档位之比 = SPEEDUP(1.10)',
  Math.abs(steps[1] / steps[0] - 1.10) < 0.02, '实测 ' + (steps[1] / steps[0]).toFixed(3));
pass('加速会停在上限上（不是无限涨）',
  steps.length > 1 && Math.abs(steps[steps.length - 1] - cap) < 2,
  '最高一档 ' + steps[steps.length - 1].toFixed(0) + ' = 上限 ' + cap.toFixed(0));

print('');
print(fails === 0 ? 'BALL SPEED RAMP: ALL PASS' : fails + ' CHECK(S) FAILED');
