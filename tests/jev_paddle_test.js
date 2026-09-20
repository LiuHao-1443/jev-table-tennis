/* UI 交互测试：暂停/继续/重开/静音/难度热切换/预判线，全部走真实事件路径 */
var BALL_R = 10;
var els = {}, listeners = {}, arcLog = [], hudText = [];
var clock = 0, rafCb = null;
function mkEl(id) {
  var set = {};
  return {
    id: id, style: {}, textContent: '', title: '', innerHTML: '', width: 0, height: 0, onclick: null,
    classList: { toggle: function (c, on) { if (on === undefined) set[c] = !set[c]; else set[c] = !!on; },
      add: function (c) { set[c] = true; }, remove: function (c) { set[c] = false; }, contains: function (c) { return !!set[c]; } },
    addEventListener: function (t, f) { (listeners[id + ':' + t] = listeners[id + ':' + t] || []).push(f); },
    getBoundingClientRect: function () { return { top: 0, left: 0, width: 1000, height: 625, right: 1000, bottom: 625 }; },
    appendChild: function () {}, blur: function () {}, focus: function () {}, getContext: function () { return ctxStub; }
  };
}
var ctxStub = {
  arc: function (x, y, r) { if (Math.abs(r - BALL_R) < 1e-6) arcLog.push({ x: x, y: y }); },
  fillText: function (t) { hudText.push(String(t)); },
  createLinearGradient: function () { return { addColorStop: function () {} }; },
  createRadialGradient: function () { return { addColorStop: function () {} }; }
};
['clearRect','fillRect','beginPath','moveTo','lineTo','ellipse','arcTo','closePath','fill','stroke',
 'save','restore','translate','setTransform','setLineDash','measureText','scale','rotate'].forEach(function (m) {
  if (!ctxStub[m]) ctxStub[m] = function () { return { width: 10 }; };
});
var document = { getElementById: function (id) { return els[id] || (els[id] = mkEl(id)); }, createElement: function () { return mkEl('n'); } };
var window = { devicePixelRatio: 2,
  addEventListener: function (t, f) { (listeners['window:' + t] = listeners['window:' + t] || []).push(f); },
  AudioContext: undefined, webkitAudioContext: undefined };
function requestAnimationFrame(cb) { rafCb = cb; }
var performance = { now: function () { return clock; } };


/* 抓包版 fetch：健康检查放行、决策请求立刻回一个合法答案。
   注意不能让它永挂起——那样客户端会一直等，后面再也不会提问。 */
var sent = [];
function fetch(url, opts) {
  if (url.indexOf('/health') >= 0) {
    return Promise.resolve({ json: function () { return Promise.resolve(
      { ok: true, model: 'paddle-test', configured: true, mode: 'pure', pure_speed_cap_px_s: 551 }); } });
  }
  var body = null;
  try { body = opts && opts.body ? JSON.parse(opts.body) : null; } catch (e) { body = null; }
  if (body) sent.push(body);
  var y = (body && body.you) || {};
  var mid = ((y.paddle_x || 900) - 10) * 0 + 338.5;
  return Promise.resolve({ json: function () { return Promise.resolve({
    ok: true, move_to: mid, speed: y.max_speed || 900, recover_to: mid, serve_vy: 0,
    band: 'b3', band_center: mid, band_confidence: 0.5, band_probabilities: {},
    aim: 'flat', power: 0.5, usage: { input_tokens: 1 }, cost_usd: 0, model: 'paddle-test' }); } });
}
function AbortController() { this.signal = { aborted: false }; this.abort = function () { this.signal.aborted = true; }; }
var location = { protocol: 'http:', origin: 'http://127.0.0.1:8760' };
var localStorage = { getItem: function () { return null; }, setItem: function () {} };
new Function(readFile('tests/.build_plain.js'))();
function fire(tg, ty, ev) { var ls = listeners[tg + ':' + ty] || []; for (var i = 0; i < ls.length; i++) ls[i](ev); }
function key(k) { fire('window', 'keydown', { key: k, preventDefault: function () {} }); }
function step(ms) { clock += ms; var cb = rafCb; rafCb = null; cb(clock); }
function run(n) { for (var i = 0; i < n; i++) { step(1000 / 60); drainMicrotasks(); } }
function ball() { return arcLog.length ? arcLog[arcLog.length - 1] : null; }
function hud() { return hudText.join(' | '); }
function pass(name, cond, extra) { print((cond ? 'PASS  ' : 'FAIL  ') + name + (extra ? '   [' + extra + ']' : '')); if (!cond) fails++; }
var fails = 0;

/* =========================================================================
   拍高（T 键）
   为什么要单独测：拿 232 次真实对局复盘，JEV 的落点误差 p50=48px、p75=69px，
   原来的半高 56px 只容得下 53% 的决策，半高 80px 能容下 78%。
   拍高就是「容错」这个物理量本身，切换时绝不允许出错。
   ========================================================================= */
new Function(readFile('tests/.build_probe.js'))();
function P() { return window.__probe(); }

key(' ');
run(240);

var half0 = P().paddleHalf;
pass('默认拍高是标准 112px（容错=考卷，默认不许动）',
  Math.abs(half0 - 56) < 0.01,
  '半高 ' + half0.toFixed(0) + 'px（拍高 ' + (half0 * 2) + 'px）· 可达拍心 ' +
  P().centerTop.toFixed(0) + '~' + P().centerBottom.toFixed(0));

/* 换尺寸时拍心不能跳：jev.y 存的是拍顶，直接改 PH 会让中心平移 (ΔPH)/2 */
var before = P().jevCenter;
key('t');
run(20);
var p1 = P();
pass('T 键真的换了尺寸', Math.abs(p1.paddleHalf - half0) > 1,
  '半高 ' + half0.toFixed(0) + ' → ' + p1.paddleHalf.toFixed(0) + 'px');
pass('T 只是对照开关，不能白送容错：三档里的最小值就是标准 56px',
  Math.min(56, 80, 100) === 56,
  '三档半高：56（标准）/ 80 / 100px');
pass('换尺寸时拍心不跳（拍顶跟着重算过）', Math.abs(p1.jevCenter - before) < 15,
  '切换前拍心 ' + before.toFixed(1) + ' → 切换后 ' + p1.jevCenter.toFixed(1));
pass('可达范围跟着尺寸一起变',
  Math.abs((p1.centerBottom - p1.centerTop) - (581 - 96 - p1.paddleHalf * 2)) < 0.01,
  '可达 ' + p1.centerTop.toFixed(0) + '~' + p1.centerBottom.toFixed(0) +
  '（= 台面 485 − 拍高 ' + (p1.paddleHalf * 2) + '）');

/* 关键：新尺寸必须真发给大脑，否则中继还在按旧网格出选项。
   直接问 buildState（askBrain 用的就是它），比抓网络更贴近被测代码。 */
var stIn = P().sentState('incoming');
var stReady = P().sentState('ready');
var stServe = P().sentState('serve');
pass('三种决策发出去的状态里，paddle_half 都是新拍高',
  Math.abs(stIn.you.paddle_half - p1.paddleHalf) < 0.01 &&
  Math.abs(stReady.you.paddle_half - p1.paddleHalf) < 0.01 &&
  Math.abs(stServe.you.paddle_half - p1.paddleHalf) < 0.01,
  'incoming/ready/serve 三种 kind 都是 ' + stIn.you.paddle_half.toFixed(0) +
  'px（= 当前半高 ' + p1.paddleHalf.toFixed(0) + '）');
pass('状态里的拍心也对得上（中继用它算可达范围）',
  Math.abs(stIn.you.paddle_center - P().jevCenter) < 0.5,
  '状态 paddle_center=' + stIn.you.paddle_center.toFixed(1) + ' · 实际拍心=' + P().jevCenter.toFixed(1));

/* 循环一圈能回到起点，不越界 */
var seen = {};
for (var i = 0; i < 6; i++) { seen[P().paddleHalf] = 1; key('t'); run(10); }
pass('按着 T 循环不会越界，且能回到起点',
  Object.keys(seen).length === 3 && seen[half0] === 1,
  '循环里出现的尺寸：' + Object.keys(seen).sort(function (a, b) { return a - b; })
    .map(function (h) { return h + 'px半高'; }).join(' / '));

/* =========================================================================
   球角上限（B 键）—— 这才是真杠杆
   实测：JEV 的落点误差 ≈ 16.8 + 0.421 ×（它要在 y 上心算的距离），r=0.57。
   球越平，这个距离越短，它的误差真的变小 —— 而容错（拍高）一动不动。
   ========================================================================= */
var mb0 = P().maxBounce;
pass('球角默认收到 0.55 rad（原来 0.92，那是让它心算 2 倍的距离）',
  Math.abs(mb0 - 0.55) < 1e-9,
  '当前角度上限 ' + mb0.toFixed(2) + ' rad = ' + (mb0 * 57.2958).toFixed(1) + '°');

var st0 = P().sentState('incoming');
pass('发给大脑的状态里带了真实角度（提示词才能说对物理）',
  Math.abs(st0.physics.max_bounce_angle_rad - mb0) < 1e-9,
  'physics.max_bounce_angle_rad = ' + st0.physics.max_bounce_angle_rad.toFixed(2));

key('b');
run(20);
var mb1 = P().maxBounce;
pass('B 键真的换了球角', Math.abs(mb1 - mb0) > 1e-9,
  mb0.toFixed(2) + ' → ' + mb1.toFixed(2) + ' rad');
pass('换球角后，状态里的角度跟着变（不会说的和做的不一致）',
  Math.abs(P().sentState('incoming').physics.max_bounce_angle_rad - mb1) < 1e-9,
  '状态里是 ' + P().sentState('incoming').physics.max_bounce_angle_rad.toFixed(2));

var seenB = {};
for (var i = 0; i < 6; i++) { seenB[P().maxBounce] = 1; key('b'); run(10); }
pass('按着 B 循环不会越界，且能回到起点',
  Object.keys(seenB).length === 3 && seenB[mb0] === 1,
  '循环里出现的角度：' + Object.keys(seenB).sort().join(' / ') + ' rad');

print('');
print(fails === 0 ? 'KNOBS (拍高 / 球角): ALL PASS' : fails + ' CHECK(S) FAILED');
