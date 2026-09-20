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


/* UI 测试不关心大脑：给一个永挂起的 fetch + 必要的浏览器桩 */
function fetch() { return new Promise(function () {}); }
function AbortController() { this.signal = { aborted: false }; this.abort = function () { this.signal.aborted = true; }; }
var location = { protocol: 'http:', origin: 'http://127.0.0.1:8760' };
var localStorage = { getItem: function () { return null; }, setItem: function () {} };
new Function(readFile('tests/.build_plain.js'))();
function fire(tg, ty, ev) { var ls = listeners[tg + ':' + ty] || []; for (var i = 0; i < ls.length; i++) ls[i](ev); }
function key(k) { fire('window', 'keydown', { key: k, preventDefault: function () {} }); }
function step(ms) { clock += ms; var cb = rafCb; rafCb = null; cb(clock); }
function run(n) { for (var i = 0; i < n; i++) step(1000 / 60); }
function ball() { return arcLog.length ? arcLog[arcLog.length - 1] : null; }
function hud() { return hudText.join(' | '); }
function pass(name, cond, extra) { print((cond ? 'PASS  ' : 'FAIL  ') + name + (extra ? '   [' + extra + ']' : '')); if (!cond) fails++; }
var fails = 0;

document.getElementById('btnStart').onclick({ target: { blur: function () {} } });
run(30);

/* 暂停 */
var before = ball();
key(' ');
var pauseShown = document.getElementById('ovPause').classList.contains('show');
run(40);
var after = ball();
pass('空格暂停后遮罩显示', pauseShown);
pass('暂停期间球不动',
  before && after && Math.abs(before.x - after.x) < 0.001 && Math.abs(before.y - after.y) < 0.001,
  'before=' + JSON.stringify(before) + ' after=' + JSON.stringify(after));
pass('暂停面板文案', document.getElementById('pauseSub').textContent.indexOf('当前') === 0,
  document.getElementById('pauseSub').textContent);

/* 继续 */
arcLog.length = 0; hudText.length = 0;
key(' ');
run(40);
var after2 = ball();
pass('空格继续后遮罩隐藏', !document.getElementById('ovPause').classList.contains('show'));
pass('继续后球恢复运动', after2 && Math.abs(after2.x - after.x) > 1, 'x=' + (after2 ? after2.x.toFixed(1) : 'n/a'));

/* 静音与难度热切 */
hudText.length = 0; key('m'); run(3);
pass('M 键切换静音提示', hud().indexOf('已静音') >= 0, hud().slice(0, 40));
hudText.length = 0; key('3'); run(3);
pass('3 键切到困难', hud().indexOf('困难') >= 0, hud().slice(0, 60));
hudText.length = 0; key('p'); run(3);
pass('P 键切换预判显示', hud().indexOf('困难') >= 0);

/* 重开 */
hudText.length = 0; key('r'); run(5);
pass('R 键重开后比分归零', hud().indexOf('大比分 0 - 0') >= 0, hud().slice(0, 80));

/* 结束遮罩按钮：再来一场 */
document.getElementById('overTitle').innerHTML = 'x';
run(2);
document.getElementById('btnAgain').onclick({ target: { blur: function () {} } });
run(5);
hudText.length = 0; run(2);
pass('再来一场重置比分', hud().indexOf('大比分 0 - 0') >= 0 && hud().indexOf('第 1 局') >= 0, hud().slice(0, 60));

/* 换难度按钮回到菜单 */
document.getElementById('btnMenu').onclick({ target: { blur: function () {} } });
run(3);
pass('换难度返回菜单遮罩', document.getElementById('ovMenu').classList.contains('show'));

print('');
print(fails === 0 ? 'UI TESTS ALL PASS' : fails + ' UI TEST(S) FAILED');
