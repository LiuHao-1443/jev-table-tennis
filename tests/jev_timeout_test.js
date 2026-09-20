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
/* 这个测试需要真的定时器和真的 AbortController，否则「超时」这条路径根本走不到 */
function AbortController() {
  var ls = [];
  this.signal = { aborted: false, addEventListener: function (t, f) { if (t === 'abort') ls.push(f); } };
  this.abort = function () { this.signal.aborted = true; for (var i = 0; i < ls.length; i++) ls[i](); };
}
var timers = [], timerSeq = 0;
var setTimeout = function (fn, ms) { var id = ++timerSeq; timers.push({ id: id, fn: fn, due: clock + (ms || 0) }); return id; };
var clearTimeout = function (id) { for (var i = 0; i < timers.length; i++) if (timers[i].id === id) timers[i].fn = null; };
function fireTimers() {
  for (var i = 0; i < timers.length; i++) {
    if (timers[i].fn && timers[i].due <= clock) { var f = timers[i].fn; timers[i].fn = null; f(); }
  }
}
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
function step() { clock += 1000 / 60; frameNo++; var cb = rafCb; rafCb = null; cb(clock); fireTimers(); settle(); }
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


/* 超时 ≠ 掉线：故意让模型这次永远不返回，看拍子会不会被冻住 */
var hangNext = false, kinds = {};
var origFetch = fetch;
fetch = function (url, opts) {
  if (url.indexOf('/jev/decide') >= 0) {
    var s2 = JSON.parse(opts.body);
    kinds[s2.kind] = (kinds[s2.kind] || 0) + 1;
    if (hangNext) {   // 卡住一切决策，这样窗口里不会有别的指令来改动 target
      return new Promise(function (res, rej) {           // 永不 resolve，模拟对方卡住
        if (opts.signal) opts.signal.addEventListener('abort', function () {
          var e = new Error('aborted'); e.name = 'AbortError'; rej(e);
        });
      });
    }
  }
  return origFetch(url, opts);
};

var lateBefore = window.__probe().late;
hangNext = true;

/* 先跑到「第一次超时」真正发生（挂起之前发出的请求可能稍后才落地，必须等它们过去） */
var waited = 0;
while (waited < 60 * 14 && window.__probe().late === lateBefore) {
  var b1 = ball(); if (b1) fire('game', 'mousemove', { clientY: b1.y });
  step(); waited++;
}
var tBefore = window.__probe().target, jBefore = window.__probe().jevCenter;

/* 超时之后再跑 2 秒：这期间没有任何决策能落地，target 必须纹丝不动 */
for (var i = 0; i < 120; i++) {
  var b2 = ball(); if (b2) fire('game', 'mousemove', { clientY: b2.y });
  step();
}
var after = window.__probe();
print('# 第 ' + (waited / 60).toFixed(1) + 's 时第一次超时 · online=' + after.online +
      ' · late=' + lateBefore + '→' + after.late + ' · target ' + tBefore.toFixed(1) + '→' + after.target.toFixed(1) +
      ' · 拍心 ' + jBefore.toFixed(1) + '→' + after.jevCenter.toFixed(1));

pass('超时不会清掉或改掉上一个指令（target 纹丝不动）',
  Math.abs(after.target - tBefore) < 0.01,
  'target ' + tBefore.toFixed(1) + ' → ' + after.target.toFixed(1));
pass('超时后伺服的门仍然开着（拍子继续执行那个指令，不会冻在半路）',
  after.online !== false && Math.abs(after.jevCenter - after.target) < 6,
  'online=' + after.online + ' · 拍心 ' + after.jevCenter.toFixed(1) + ' vs 指令 ' + after.target.toFixed(1));
pass('卡住不会被误判为「掉线」', after.online !== false,
  'online=' + after.online + '（true 或 null=还在连，false 才是掉线）');
pass('被作废的慢决策会计数（超时 ≠ 掉线）', after.late > lateBefore,
  'late ' + lateBefore + ' → ' + after.late);
print('');
print(fails === 0 ? 'TIMEOUT != OFFLINE: ALL PASS' : fails + ' CHECK(S) FAILED');
