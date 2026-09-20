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
  // 假模型故意模仿「球越近，算得越准」：起步时偏 160px，到拍面时几乎不偏。
  // 这样就能验证：重复提问有没有真的把落点修正过来。
  var progress = Math.max(0, Math.min(1, (b.x - 100) / (you.paddle_x - 100)));
  var target = real + 160 * (1 - progress);
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

var r1 = approach(1200);
pass('一板球问了多次（不是只问一次）', r1.asked.length >= 3,
  '这板问了 ' + r1.asked.length + ' 次，发起时球在 x = ' + r1.asked.map(function (a) { return Math.round(a._askedAtBallX); }).join(', '));

/* 关键：假模型故意"越近越准"，看后面的决策有没有真的把落点修正过来 */
var r2 = approach(1200);
var first = r2.asked[0], last = r2.asked[r2.asked.length - 1];
print('# 诊断 r2 这一板问了 ' + r2.asked.length + ' 次，依次是 y=' +
  r2.asked.map(function (a) { return a.move_to.toFixed(0); }).join(', ') +
  ' · 发起时球x=' + r2.asked.map(function (a) { return Math.round(a._askedAtBallX); }).join(','));
pass('同一板球里每次决策都不同（确实在更新，不是重复同一个）',
  r2.asked.length >= 3 && first.move_to !== last.move_to,
  '这板问了 ' + r2.asked.length + ' 次：首判 y=' + first.move_to.toFixed(0) +
  ' → 末判 y=' + last.move_to.toFixed(0));
pass('再问一次真的把落点算得更准了（末判比首判更贴近真实到达点）',
  r2.asked.length >= 3 && last._err < first._err - 1,
  '首判误差 ' + first._err.toFixed(0) + 'px → 末判误差 ' + last._err.toFixed(0) + 'px');
pass('拍子最终停在「最后一次决策」说的位置，而不是第一次（修正真的生效）',
  r2.contact !== null &&
  Math.abs(r2.contact - last.move_to) < 25 &&
  Math.abs(r2.contact - first.move_to) > Math.abs(r2.contact - last.move_to),
  '首判 y=' + first.move_to.toFixed(0) + ' · 末判 y=' + last.move_to.toFixed(0) +
  ' · 球到拍面时实际拍心 y=' + (r2.contact === null ? '?' : r2.contact.toFixed(0)));

/* 关掉多判（K 键）之后应该回到「一板一判」 */
fire('window', 'keydown', { key: 'k' });
var r3 = approach(1200);
pass('按 K 关掉多判后，一板只问一次', r3.asked.length === 1, '这板问了 ' + r3.asked.length + ' 次');
fire('window', 'keydown', { key: 'k' });
var r4 = approach(1200);
pass('再按 K 打开，又恢复多次', r4.asked.length >= 3, '这板问了 ' + r4.asked.length + ' 次');

/* 球快到最后一段时不该再发起（问了也来不及） */
var lastAskX = 0;
var r5 = approach(1200);
if (r5.asked.length) lastAskX = r5.asked[r5.asked.length - 1]._askedAtBallX;
pass('最后一次提问留够了往返时间（不会问一个注定迟到的）',
  r5.asked.length >= 1 && lastAskX < PROBE.jevX - 10,
  '最晚一次在 x=' + Math.round(lastAskX) + ' 发起（拍面在 x≈908，延迟 380ms）');

print('');
print(fails === 0 ? 'MULTI-ROUND (闭环): ALL PASS' : fails + ' CHECK(S) FAILED');
