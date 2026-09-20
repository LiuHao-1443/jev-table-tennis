import os
import re
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
src = open(os.path.join(ROOT, 'index.html'), encoding='utf-8').read()
body = re.search(r'<script>(.*)</script>', src, re.S).group(1)
tail = "\n})();\n"
assert body.endswith(tail), repr(body[-40:])
probe = """window.__probe = function () {
  return { sentState: function (kind) { return buildState(kind || 'incoming'); },
           maxBounce: MAX_BOUNCE,
           jevTop: jev.y, jevCenter: jev.y + PH / 2, jevX: jev.x, jevVy: jev.vy,
           paddleHalf: PH / 2, centerTop: WALL_T + PH / 2, centerBottom: WALL_B - PH / 2,
           target: brain.target, recoverTo: brain.recoverTo, speed: brain.speed,
           online: brain.online, phase: phase, paused: paused,
           ballX: ball.x, ballY: ball.y, ballVx: ball.vx, ballVy: ball.vy,
           scoreJ: scoreJ, scoreH: scoreH, seq: brain.seq,
           multi: brain.multi, round: brain.round, askedKey: brain.askedKey,
           target: brain.target, recoverTo: brain.recoverTo, ready: brain.ready, online: brain.online, phase: phase,
           cap: ballSpeedCap(), rallyStartFrac: RALLY_START_FRAC, ballSpeed: ball.speed, rally: rally, late: brain.late,
           inflightKind: brain.inflightKind, latency: brain.latency };
};
"""
# 探针必须放进 IIFE 内部（jev/brain 都在里面的作用域）
inject = '/* 测试用确定性随机：人类发球角度本来用 Math.random()，会让测试偶发失败。\n   固定种子后每次跑都一样，失败可复现。 */\n(function () {\n  var _seed = 20240101;\n  Math.random = function () { _seed = (_seed * 1103515245 + 12345) % 2147483648; return _seed / 2147483648; };\n})();\n\n'
out = inject + body[:-len(tail)] + probe + tail
open(os.path.join(HERE, '.build_probe.js'), 'w', encoding='utf-8').write(out)
print('生成 tests/.build_probe.js: %d 字节' % len(out))
