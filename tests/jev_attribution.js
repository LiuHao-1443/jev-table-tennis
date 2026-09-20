/* 归因实验（读真实状态变量 jev.y，不猜绘图调用）
   同一个本地代码、同一个物理、同一个球，只改「模型怎么答」，看结果差多少。
   如果本地藏着兜底算法，那么模型故意答反时它照样能接住 —— 那这个测试就会失败。 */
var els = {}, listeners = {}, pending = [], calls = [];
var clock = 0, rafCb = null, frameNo = 0;
var mode = 'fixed';          // fixed | perfect | anti | chaos

function mkEl(id) {
  var set = {};
  return { id: id, style: {}, textContent: '', title: '', innerHTML: '', width: 0, height: 0, onclick: null, value: '',
    dataset: {}, parentNode: null,
    classList: { toggle: function (c, on) { if (on === undefined) set[c] = !set[c]; else set[c] = !!on; },
      add: function (c) { set[c] = true; }, remove: function (c) { set[c] = false; }, contains: function (c) { return !!set[c]; } },
    addEventListener: function (t, f) { (listeners[id + ':' + t] = listeners[id + ':' + t] || []).push(f); },
    getBoundingClientRect: function () { return { top: 0, left: 0, width: 1000, height: 625, right: 1000, bottom: 625 }; },
    appendChild: function () {}, blur: function () {}, focus: function () {},
    getContext: function () { return ctx; } };
}
var ctx = { measureText: function (t) { return { width: String(t).length * 7 }; },
  createLinearGradient: function () { return { addColorStop: function () {} }; },
  createRadialGradient: function () { return { addColorStop: function () {} }; } };
['clearRect','fillRect','beginPath','moveTo','lineTo','arcTo','closePath','fill','stroke','save','restore',
 'translate','setTransform','setLineDash','scale','rotate','arc','ellipse','fillText'].forEach(function (m) { if (!ctx[m]) ctx[m] = function () {}; });
var document = { getElementById: function (id) { return els[id] || (els[id] = mkEl(id)); }, createElement: function () { return mkEl('n'); } };
var window = { devicePixelRatio: 2, addEventListener: function (t, f) { (listeners['window:' + t] = listeners['window:' + t] || []).push(f); } };
var location = { protocol: 'http:', origin: 'http://127.0.0.1:8760' };
var localStorage = { getItem: function () { return null; }, setItem: function () {} };
var performance = { now: function () { return clock; } };
function requestAnimationFrame(cb) { rafCb = cb; }
function AbortController() { this.signal = { aborted: false }; this.abort = function () {}; }
var setTimeout = function () { return 0; }, clearTimeout = function () {};
var dead = false;

function fold(y, lo, hi) { var s = hi - lo; var t = (y - lo) % (2 * s); if (t < 0) t += 2 * s; return t <= s ? lo + t : lo + (2 * s - t); }

function P() { return window.__probe(); }   // 惰性取：__probe 是后面才挂上的
function decide(state) {
  var tb = state.table, b = state.ball, you = state.you;
  var lo = tb.y_top + b.r, hi = tb.y_bottom - b.r, mid = (lo + hi) / 2;
  if (state.kind === 'serve') {
    var sv = (mode === 'fixed') ? P().centerTop : mid;   // 用可达范围的最上端，别写死
    return { ok: true, move_to: sv, speed: you.max_speed, recover_to: sv, serve_vy: 0, model: 'audit', usage: { input_tokens: 1 }, cost_usd: 0 };
  }
  var arrival = mid;
  if (b.vx > 0 && you.paddle_x > b.x) arrival = fold(b.y + b.vy * ((you.paddle_x - b.r - b.x) / b.vx), lo, hi);
  var want = arrival;
  if (mode === 'fixed') { want = P().centerTop; }
  else if (mode === 'anti') { want = arrival < mid ? hi : lo; }        // 故意站到球的反方向
  else if (mode === 'chaos') { want = lo + ((calls.length * 41) % 100) / 100 * (hi - lo); }
  var recover = (mode === 'fixed') ? P().centerTop : arrival;
  return { ok: true, move_to: Math.round(want), speed: you.max_speed, recover_to: recover,
    model: 'audit', band: 'b?', band_center: Math.round(want), band_confidence: 0.5, band_probabilities: {},
    aim: 'flat', power: 0.5, usage: { input_tokens: 1 }, cost_usd: 0 };
}
function fetchStub(url, opts) {
  return new Promise(function (res, rej) {
    if (dead) { rej(new Error('ECONNREFUSED')); return; }
    var body = null; try { body = JSON.parse(opts.body); } catch (e) {}
    pending.push({ url: url, body: body, t: 0, due: url.indexOf('/health') >= 0 ? 10 : 100, resolve: res });
  });
}
var fetch = fetchStub;
function settle() {
  for (var i = pending.length - 1; i >= 0; i--) {
    var p = pending[i]; p.t += 1000 / 60; if (p.t < p.due) continue;
    pending.splice(i, 1);
    if (p.url.indexOf('/health') >= 0) p.resolve({ json: function () { return Promise.resolve({ ok: true, model: 'audit', configured: true }); } });
    else { calls.push(p.body); var d = decide(p.body); p.resolve({ json: function () { return Promise.resolve(d); } }); }
  }
  drainMicrotasks();
}
function fresh() { els = {}; listeners = {}; pending = []; calls = []; clock = 0; rafCb = null; frameNo = 0; dead = false;
  new Function(readFile('tests/.build_probe.js'))(); }
function step() { clock += 1000 / 60; frameNo++; var cb = rafCb; rafCb = null; cb(clock); settle(); }
function probe() { return window.__probe(); }
function fire(tg, ty, ev) { var ls = listeners[tg + ':' + ty] || []; for (var i = 0; i < ls.length; i++) ls[i](ev); }
var fails = 0;
function pass(n, c, e) { print((c ? 'PASS  ' : 'FAIL  ') + n + (e ? '   [' + e + ']' : '')); if (!c) fails++; }

/* 跑一段：人类陪练完美跟球；统计 JEV 接回几个球（右侧由 + 变 − 即接到） */
function run(frames, skip) {
  var returns = 0, prevVx = null, placeErr = [], opps = 0;
  for (var i = 0; i < frames; i++) {
    var p0 = probe();
    if (p0 && p0.ballVx !== 0) fire('game', 'mousemove', { clientY: p0.ballY });
    step();
    var p = probe(); if (!p) continue;
    if (skip && i < skip) { prevVx = p.ballVx; continue; }
    if (prevVx !== null && prevVx > 0 && p.ballVx < 0) returns++;
    if (prevVx !== null && prevVx < 0 && p.ballVx > 0) opps++;   // 人类把球打向它 = 一次机会
    if (p.ballVx > 0 && prevVx !== null && prevVx > 0 && p.ballX + 10 >= p.jevX - 45) {
      placeErr.push(Math.abs(p.jevCenter - p.ballY));
    }
    prevVx = p.ballVx;
  }
  var avg = placeErr.length ? placeErr.reduce(function (a, b) { return a + b; }, 0) / placeErr.length : null;
  return { returns: returns, placeErr: avg, samples: placeErr.length, opps: opps };
}

/* ---------- 实验 1：模型说「就待在 y=152」，本地会不会自己跑去追球？ ---------- */
mode = 'fixed'; fresh();
document.getElementById('btnStart').onclick({ target: { blur: function () {} } });
var seen = { min: 1e9, max: -1e9 }, n = 0;
for (var i = 0; i < 60 * 40; i++) {
  var p0 = probe();
  if (p0 && p0.ballVx > 0) fire('game', 'mousemove', { clientY: p0.ballY });
  step();
  var p = probe();
  if (p && i > 240 && typeof p.jevCenter === 'number') { seen.min = Math.min(seen.min, p.jevCenter); seen.max = Math.max(seen.max, p.jevCenter); n++; }
}
print('# 探针实测：拍心范围 ' + seen.min.toFixed(1) + '~' + seen.max.toFixed(1) + '，采样 ' + n + ' 帧');
pass('模型说「钉在可达范围最上端」→ 拍心真的不动（没有本地追球）',
  n > 100 && Math.abs(seen.max - P().centerTop) <= 2 && Math.abs(seen.min - P().centerTop) <= 2,
  '拍心 ' + seen.min.toFixed(1) + '~' + seen.max.toFixed(1) +
  '（指令 ' + P().centerTop.toFixed(1) + '，可达范围 ' + P().centerTop.toFixed(0) +
  '~' + P().centerBottom.toFixed(0) + '）');

/* ---------- 实验 2：模型说「去球的到达点」→ 接得住 ---------- */
mode = 'perfect'; fresh();
document.getElementById('btnStart').onclick({ target: { blur: function () {} } });
var rPerfect = run(60 * 90, 180);
pass('模型说对了 → JEV 接得住（拍心贴住球）',
  rPerfect.opps >= 4 && rPerfect.returns >= rPerfect.opps - 1 && rPerfect.placeErr !== null && rPerfect.placeErr < 30,
  '机会 ' + rPerfect.opps + ' 次接回 ' + rPerfect.returns + ' 次 · 到拍面时平均偏差 ' +
  (rPerfect.placeErr === null ? 'n/a' : rPerfect.placeErr.toFixed(1) + 'px'));

/* ---------- 实验 3（关键）：模型故意站反方向 → 本地绝不救场 ---------- */
mode = 'anti'; fresh();
document.getElementById('btnStart').onclick({ target: { blur: function () {} } });
var rAnti = run(60 * 90, 180);
pass('模型故意站到球的反方向 → JEV 几乎全接不到（本地无兜底）',
  rAnti.opps >= 4 && rAnti.returns <= Math.max(1, Math.floor(rAnti.opps * 0.1)),
  '机会 ' + rAnti.opps + ' 次只接回 ' + rAnti.returns + ' 次（对照：答对时 ' + rPerfect.returns + '/' + rPerfect.opps + '）');

/* ---------- 实验 4：掉线 → 一拍都不动 ---------- */
mode = 'perfect'; fresh();
document.getElementById('btnStart').onclick({ target: { blur: function () {} } });
for (var z = 0; z < 300; z++) { var q = probe(); if (q && q.ballVx > 0) fire('game', 'mousemove', { clientY: q.ballY }); step(); }
dead = true;
var waited = 0;
while (waited < 60 * 20 && probe().online !== false) { step(); waited++; }   // 等失败登记
print('# 掉线登记耗时 ' + (waited / 60).toFixed(1) + 's，online=' + probe().online);
var base = probe().jevCenter, moved = 0;
for (var v = 0; v < 900; v++) { var s = probe(); if (s && s.ballVx > 0) fire('game', 'mousemove', { clientY: s.ballY }); step(); if (Math.abs(probe().jevCenter - base) > 0.01) moved++; }
pass('掉线后拍心一格不动（无任何本地代打）', moved === 0, '维持在 ' + base.toFixed(1) + ' · 移动帧数 ' + moved);

print('');
print(fails === 0 ? 'ATTRIBUTION AUDIT: ALL PASS' : fails + ' CHECK(S) FAILED');
