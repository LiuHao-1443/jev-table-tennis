/* JEV 决策日志测试：验证每一次决策都被留档、内容完整、一键可见、事后能核对对错 */
var BALL_R = 10;
var els = {}, listeners = {}, arcLog = [], hudText = [];
var clock = 0, rafCb = null, pending = [], calls = [];
var modelCfg = { latencyMs: 260, errorPx: 0, speed: 900, mode: 'play', fail: false };

function mkEl(id) {
  var set = {};
  return {
    id: id, style: {}, textContent: '', title: '', innerHTML: '', width: 0, height: 0, onclick: null, value: '',
    dataset: {}, parentNode: null,
    classList: { toggle: function (c, on) { if (on === undefined) set[c] = !set[c]; else set[c] = !!on; },
      add: function (c) { set[c] = true; }, remove: function (c) { set[c] = false; }, contains: function (c) { return !!set[c]; } },
    addEventListener: function (t, f) { (listeners[id + ':' + t] = listeners[id + ':' + t] || []).push(f); },
    getBoundingClientRect: function () { return { top: 0, left: 0, width: 1000, height: 625, right: 1000, bottom: 625 }; },
    appendChild: function () {}, blur: function () {}, focus: function () {}, getContext: function () { return ctxStub; }
  };
}
var ctxStub = {
  arc: function (x, y, r) { if (Math.abs(r - BALL_R) < 1e-6) arcLog.push({ x: x, y: y }); },
  moveTo: function () {}, fillText: function (t) { hudText.push(String(t)); },
  measureText: function (t) { return { width: String(t).length * 7 }; },
  createLinearGradient: function () { return { addColorStop: function () {} }; },
  createRadialGradient: function () { return { addColorStop: function () {} }; }
};
['clearRect','fillRect','beginPath','moveTo','lineTo','ellipse','arcTo','closePath','fill','stroke',
 'save','restore','translate','setTransform','setLineDash','scale','rotate'].forEach(function (m) {
  if (!ctxStub[m]) ctxStub[m] = function () { return { width: 10 }; };
});
var document = {
  getElementById: function (id) { return els[id] || (els[id] = mkEl(id)); },
  createElement: function () { return mkEl('n' + Math.random()); }
};
var window = {
  devicePixelRatio: 2,
  addEventListener: function (t, f) { (listeners['window:' + t] = listeners['window:' + t] || []).push(f); },
  AudioContext: undefined, webkitAudioContext: undefined
};
var location = { protocol: 'http:', origin: 'http://127.0.0.1:8760' };
var localStorage = { getItem: function () { return null; }, setItem: function () {} };
function requestAnimationFrame(cb) { rafCb = cb; }
var performance = { now: function () { return clock; } };
function AbortController() { this.signal = { aborted: false }; this.abort = function () {}; }
var setTimeout = function () { return 0; }, clearTimeout = function () {};

/* ---------- 假中继：返回带 trace 的完整 Jev 响应 ---------- */
function fold(y, lo, hi) {
  var span = hi - lo; var t = (y - lo) % (2 * span); if (t < 0) t += 2 * span;
  return t <= span ? lo + t : lo + (2 * span - t);
}
function decide(state) {
  var tb = state.table, b = state.ball, you = state.you;
  var lo = tb.y_top + b.r, hi = tb.y_bottom - b.r, mid = (lo + hi) / 2;
  if (state.kind === 'serve') {
    return { ok: true, move_to: mid, speed: you.max_speed, recover_to: mid, serve_vy: -0.55,
      note: '这球我算过了', model: 'jev-test', band_confidence: 0,
      usage: { input_tokens: 930, output_tokens: 20 }, cost_usd: 0.00003906,
      trace: { state_text: 'Table tennis, top-down view. (发球决策的原始描述)',
               questions: { serve: { type: 'choice', criteria: { flat: 1, rise: 1, dip: 1 } } },
               answers: { serve: { type: 'choice', choice: 'dip', confidence: 0.6 } },
               prompt_chars: 900, question_count: 2 } };
  }
  var arrival = fold(b.y + b.vy * ((you.paddle_x - b.r - b.x) / b.vx), lo, hi);
  var idx = 3;
  var bands = ['b0','b1','b2','b3','b4','b5','b6'];
  for (var i = 0; i < 7; i++) { var a = lo + (hi - lo) / 7 * i; if (arrival >= a && arrival < a + (hi - lo) / 7) idx = i; }
  var probs = {}; bands.forEach(function (k, j) { probs[k] = j === idx ? 0.37 : 0.105; });
  var center = lo + (hi - lo) / 7 * (idx + 0.5);
  return { ok: true, move_to: center - 0.45 * you.paddle_half, speed: 588, recover_to: center,
    note: '压你反手', model: 'jev-test',
    band: bands[idx], band_center: center, band_confidence: 0.26, band_probabilities: probs,
    aim: 'down', power: 0.36,
    usage: { input_tokens: 996, output_tokens: 42 }, cost_usd: 0.00004183,
    trace: { state_text: 'Table tennis, top-down view. Ball at x=' + Math.round(b.x) + ', y=' + Math.round(b.y) +
             '. It will reach you in about 0.41 seconds. (完整的原始情境描述)',
             questions: { band: { type: 'choice', instructions: 'Which y range?', criteria: { b0: 'y 152-206' } },
                          aim: { type: 'choice', criteria: { up: 1, flat: 1, down: 1 } },
                          power: { type: 'noul', instructions: 'Hit harder?' } },
             answers: { band: { type: 'choice', choice: bands[idx], confidence: 0.26, probabilities: probs },
                        aim: { type: 'choice', choice: 'down', confidence: 0.48 },
                        power: { type: 'noul', noul: 0.36 } },
             prompt_chars: 1296, question_count: 3 } };
}
function fetchStub(url, opts) {
  return new Promise(function (resolve, reject) {
    var body = null; try { body = JSON.parse(opts.body); } catch (e) {}
    pending.push({ url: url, body: body, t: 0, due: url.indexOf('/health') >= 0 ? 20 : modelCfg.latencyMs,
      resolve: resolve, reject: reject });
  });
}
var fetch = fetchStub;
function settle() {
  for (var i = pending.length - 1; i >= 0; i--) {
    var p = pending[i]; p.t += 1000 / 60; if (p.t < p.due) continue;
    pending.splice(i, 1);
    if (p.url.indexOf('/health') >= 0) {
      p.resolve({ json: function () { return Promise.resolve({ ok: true, model: 'jev-test', configured: true }); } });
    } else {
      calls.push(p.body);
      if (modelCfg.fail) { p.resolve({ json: function () { return Promise.resolve({ ok: false, error: 'Jev HTTP 429：rate limited' }); } }); continue; }
      p.resolve({ json: function () { return Promise.resolve(decide(p.body)); } });
    }
  }
  drainMicrotasks();
}
function fresh() {
  els = {}; listeners = {}; arcLog = []; hudText = []; clock = 0; rafCb = null; pending = []; calls = [];
  new Function(readFile('tests/.build_plain.js'))();
}
function fire(tg, ty, ev) { var ls = listeners[tg + ':' + ty] || []; for (var i = 0; i < ls.length; i++) ls[i](ev); }
function step() { clock += 1000 / 60; var cb = rafCb; rafCb = null; cb(clock); settle(); }
function ballNow() { return arcLog.length ? arcLog[arcLog.length - 1] : null; }
function log() { return els.logList ? String(els.logList.innerHTML || '') : ''; }
var fails = 0;
function pass(name, cond, extra) { print((cond ? 'PASS  ' : 'FAIL  ') + name + (extra ? '   [' + extra + ']' : '')); if (!cond) fails++; }

/* ============ 场景 1：打完一段比赛，日志应当逐条记录 ============ */
modelCfg = { latencyMs: 260, errorPx: 0, speed: 900, mode: 'play', fail: false };
fresh();
document.getElementById('btnStart').onclick({ target: { blur: function () {} } });
for (var i = 0; i < 60 * 60 * 3; i++) {
  var pb = ballNow();
  if (pb) fire('game', 'mousemove', { clientY: pb.y });
  step();
}
var badge = String(document.getElementById('logCount').textContent);
pass('每问一次模型就记一条日志', calls.length > 0 && Number(badge) === Math.min(calls.length, 60),
  'decide ' + calls.length + ' 次 / 角标 ' + badge);

/* 打开面板 = 一次点击 */
document.getElementById('btnLog').onclick({ target: { blur: function () {} } });
pass('点一下按钮就打开日志面板', els.ovLog.classList.contains('show'), 'ovLog show=' + els.ovLog.classList.contains('show'));
var html = log();
pass('日志里能看到每条决策的耗时与 token', html.indexOf('ms') > 0 && html.indexOf('tok') > 0,
  html.slice(0, 120).replace(/\s+/g, ' '));
pass('日志里能看到模型判断的落点区间与置信度', /b[0-6] \d+%/.test(html));
pass('日志里能看到解码后的机械臂指令', html.indexOf('x→y=') > 0 && html.indexOf('发力') > 0);
pass('日志里能看到这条的原始输入规模', html.indexOf('输入') > 0 && html.indexOf('问') > 0);
pass('面板顶部有汇总统计', /平均 \d+ms/.test(String(document.getElementById('logStat').textContent)),
  String(document.getElementById('logStat').textContent));

/* 点开一条，应当展开完整过程（原始描述 + 问题集 + 概率分布 + 成本） */
var listEl = document.getElementById('logList');
var fakeTarget = { dataset: { i: '0' }, classList: { _s: {}, toggle: function (c, on) { this._s[c] = on; },
  add: function () {}, remove: function () {}, contains: function (c) { return !!this._s[c]; } } };
listEl.onclick({ target: fakeTarget, currentTarget: listEl });
pass('点开一条能展开（细节写在展开区里）', fakeTarget.classList.contains('open'));
pass('展开后包含发给模型的原始情境描述', html.indexOf('Table tennis, top-down view') > 0);
pass('展开后包含问题集与概率分布', html.indexOf('Which y range?') > 0 && html.indexOf('类型化') >= 0 || html.indexOf('noul') > 0);
pass('展开后包含成本换算', html.indexOf('$42/Btok') > 0 || html.indexOf('token ×') > 0);

/* 暂停语义：打开面板不该让比赛继续跑掉分 */
pass('打开日志会自动暂停比赛', els.ovPause.classList.contains('show'),
  '暂停遮罩=' + els.ovPause.classList.contains('show'));
var frz = ballNow();
for (var pz = 0; pz < 120; pz++) step();
pass('暂停期间球确实不动（真的停住了）',
  frz && ballNow() && Math.abs(ballNow().x - frz.x) < 0.01 && Math.abs(ballNow().y - frz.y) < 0.01,
  frz && ballNow() ? ('x ' + frz.x.toFixed(1) + '→' + ballNow().x.toFixed(1)) : 'n/a');

/* 关闭后继续 */
document.getElementById('btnLogClose').onclick({ target: { blur: function () {} } });
pass('点关闭能收起面板', !els.ovLog.classList.contains('show'));
pass('关闭后自动继续比赛', !els.ovPause.classList.contains('show'),
  '暂停遮罩=' + els.ovPause.classList.contains('show'));

/* ============ 场景 2：事后核对——它猜的落点 vs 真实到达点 ============ */
fresh();
modelCfg = { latencyMs: 200, errorPx: 0, speed: 900, mode: 'play', fail: false };
document.getElementById('btnStart').onclick({ target: { blur: function () {} } });
for (var j = 0; j < 60 * 60 * 3; j++) {
  var pb2 = ballNow();
  if (pb2) fire('game', 'mousemove', { clientY: pb2.y });
  step();
}
document.getElementById('btnLog').onclick({ target: { blur: function () {} } });
var h2 = log();
pass('日志里回填了真实到达点与对错', h2.indexOf('实际 y=') > 0 && (h2.indexOf('✅') > 0 || h2.indexOf('❌') > 0),
  (h2.match(/实际 y=\d+ [✅❌][^<]*/) || ['(无)'])[0]);
pass('汇总里给出落点判断命中率', /落点判断 \d+\/\d+/.test(String(document.getElementById('logStat').textContent)),
  String(document.getElementById('logStat').textContent));

/* ============ 场景 3：模型报错也要留档 ============ */
fresh();
modelCfg = { latencyMs: 200, errorPx: 0, speed: 900, mode: 'play', fail: true };
document.getElementById('btnStart').onclick({ target: { blur: function () {} } });
for (var k = 0; k < 600; k++) { var pb3 = ballNow(); if (pb3) fire('game', 'mousemove', { clientY: pb3.y }); step(); }
var n3 = Number(String(document.getElementById('logCount').textContent));
document.getElementById('btnLog').onclick({ target: { blur: function () {} } });
pass('调用失败也记一条（红条 + 错误原因）', n3 > 0 && log().indexOf('rate limited') > 0, '记录 ' + n3 + ' 条');
pass('失败条目带 bad 样式便于区分', log().indexOf('entry bad') > 0);

print('');
print(fails === 0 ? 'DECISION LOG: ALL PASS' : fails + ' CHECK(S) FAILED');
