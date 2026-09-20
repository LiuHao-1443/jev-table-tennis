#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
纯驱动模式的机械检查：把「零本地算法」这句话变成可执行的断言。
每一项都对应一条具体承诺，任何一条不成立就等于仪器被污染了。
"""
import json
import os
import sys

sys.path.insert(0, ".")
import server  # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    print(("PASS  " if cond else "FAIL  ") + name + (("   [" + str(extra) + "]") if extra != "" else ""))
    if not cond:
        FAILS.append(name)


STATE = {
    "kind": "incoming",
    "table": {"y_top": 96, "y_bottom": 581, "x_left": 78, "x_right": 1042},
    "ball": {"x": 600, "y": 300, "vx": 780, "vy": 260, "r": 10, "speed": 430},
    "you": {"side": "right", "paddle_x": 900, "paddle_half": 56, "paddle_center": 338,
            "max_speed": 900, "machine_heat": 1},
    "opponent": {"paddle_x": 100, "paddle_center": 200},
    "score": {"you": 3, "opponent": 5}, "games": {"you": 0, "opponent": 1}, "rally": 7,
    "physics": {"max_bounce_angle_rad": 0.92, "speedup_per_hit": 1.045,
                "max_ball_speed": 1180, "min_vy_ratio": 0.13},
}


def arrival_y(st):
    """本地算的真实到达点——只用于【检查有没有泄漏】和打分，绝不发给模型。"""
    b, you = st["ball"], st["you"]
    lo = st["table"]["y_top"] + b["r"]
    hi = st["table"]["y_bottom"] - b["r"]
    t = (you["paddle_x"] - b["r"] - b["x"]) / b["vx"]
    y = b["y"] + b["vy"] * t
    span = hi - lo
    m = (y - lo) % (2 * span)
    return lo + m if m <= span else lo + (2 * span - m)


print("=" * 74)
print("pure 模式：纯驱动承诺的机械检查")
print("=" * 74)

server.MODE = "pure"
text = server.describe_pure(STATE)
q = server.build_questions_pure(STATE, serving=False)
y_true = arrival_y(STATE)

# 承诺 1：不给到达时间，不管它以什么写法出现
hint_words = ["seconds", "reach you", "will arrive", "eta", "time to"]
check("提示词里没有任何『还剩几秒』的推算", not any(w in text.lower() for w in hint_words),
      "扫描 " + ", ".join(hint_words))

# 承诺 2：真相不许出现在提示词里（不管哪种模式都必须成立）
nums = {str(int(round(y_true))), "%.1f" % y_true, "%.2f" % y_true}
leaked = [n for n in nums if n in text]
check("真实到达点没有泄漏进提示词", not leaked, "真实 y=%.1f，泄漏检查 %s" % (y_true, sorted(nums)))

# 承诺 3：只问一个问题，且选项就是真实可执行的拍位
check("一次决策只问一个问题", len(q) == 1 and "place" in q, "问题集 = " + str(list(q)))
cal = q.get("place", {}).get("criteria", {})
check("选项数量 = 7 档", len(cal) == 7, "%d 个选项" % len(cal))
ps = server.placements_of(STATE)
check("每个选项的文字里写的就是那个真实 y",
      all(("y=%.1f" % ps[i]) in cal["p%d" % i] for i in range(7)),
      "例：" + cal["p3"])

# 承诺 4：解码是纯查表——它选什么就是什么，一位小数都不许动
bad = []
for i in range(7):
    out = server.decode_pure({"place": {"choice": "p%d" % i}}, STATE, False)
    if abs(out["move_to"] - ps[i]) > 1e-9:
        bad.append((i, out["move_to"], ps[i]))
check("它选的标签 → 指令位置，是恒等映射（没有换算）", not bad, "7 个标签全部逐位相等")

# 承诺 5：永远不会被前端的安全钳位改掉（否则它的决定会被本地悄悄修改）
half = STATE["you"]["paddle_half"]
c_lo = STATE["table"]["y_top"] + half
c_hi = STATE["table"]["y_bottom"] - half
clamped = [p for p in ps if not (c_lo - 1e-9 <= p <= c_hi + 1e-9)]
check("所有可选位置都落在物理可达区间内（前端钳位永不生效）", not clamped,
      "可达 [%.0f, %.0f]，选项 [%.1f, %.1f]" % (c_lo, c_hi, min(ps), max(ps)))

# 承诺 6：没有 aim / power 的本地换算
out = server.decode_pure({"place": {"choice": "p2"}}, STATE, False)
check("不再有 aim 换算（方向由它选的位置经物理自然决定）", "aim" not in out, str(sorted(out.keys())))
check("不再有 power 换算（速度就是机械臂上限）", "power" not in out and out["speed"] == 900,
      "speed=%.0f" % out["speed"])

# 承诺 7：球速上限固定，不随实测延迟变化
#   要点是「它没有任何入口能收到实测延迟」，而不是「改常数它也不变」——后者是我上一版写错的断言。
import inspect  # noqa: E402
sig = list(inspect.signature(server.pure_speed_cap).parameters)
rep = [server.pure_speed_cap(964.0) for _ in range(3)]
check("球速上限的函数签名叫不进任何延迟量（只有台面宽度）",
      sig == ["table_w"], "参数 = %s，值 = %.0f px/s" % (sig, rep[0]))
check("同一输入永远同一输出（无隐藏状态、无自适应）", len(set(rep)) == 1, "%.0f px/s" % rep[0])

# 承诺 8：发球也是直接选真实可执行的量
qs = server.build_questions_pure(STATE, serving=True)
out_s = server.decode_pure({"serve": {"choice": "s0"}}, STATE, True)
check("发球选项写明了真实弧度系数", "vy factor -0.55" in qs["serve"]["criteria"]["s0"],
      qs["serve"]["criteria"]["s0"])
check("发球解码也是查表（s0→-0.55, s1→0, s2→+0.55）",
      (out_s["serve_vy"] == -0.55
       and server.decode_pure({"serve": {"choice": "s1"}}, STATE, True)["serve_vy"] == 0.0
       and server.decode_pure({"serve": {"choice": "s2"}}, STATE, True)["serve_vy"] == 0.55))

# 承诺 9：中继自带的测试替身在 pure 下也产出 place，走同一条解码路径
ans, _u, _m = server.mock_answers(STATE, False)
check("测试替身在 pure 下产出 place 标签", "place" in ans, str(list(ans)))

# 承诺 10：assisted 仍然可用（对照基线没坏）
server.MODE = "assisted"
ta = server.describe(STATE)
qa = server.build_questions_assisted(STATE, False)
check("assisted 模式仍然保留对照能力（3 问 + 到达时间）",
      len(qa) == 3 and "reach you in about" in ta, "问题 = " + str(sorted(qa)))
server.MODE = "pure"

# 承诺 11：提示词里说的角度必须是状态里那个角度（曾写死 0.45×，差 2.2 倍）
import re as _re
_ST2 = json.loads(json.dumps(STATE))
_ST2["physics"]["max_bounce_angle_rad"] = 0.55
_txt = server.describe_pure(_ST2)
_m = _re.search(r"up to ([0-9.]+) rad at the very edge", _txt)
check("提示词里的边缘角度 = 状态里的真实角度（0.55）",
      _m is not None and abs(float(_m.group(1)) - 0.55) < 1e-6,
      ("提示词说 " + (_m.group(1) if _m else "?") + " rad") if _m else "没找到那句")
_ST2["physics"]["max_bounce_angle_rad"] = 0.92
_txt2 = server.describe_pure(_ST2)
_m2 = _re.search(r"up to ([0-9.]+) rad at the very edge", _txt2)
check("换成 0.92 时提示词也跟着变（不是写死的常数）",
      _m2 is not None and abs(float(_m2.group(1)) - 0.92) < 1e-6,
      "提示词说 " + (_m2.group(1) if _m2 else "?") + " rad")


print("")
print("PURE-MODE CHECKS: ALL PASS" if not FAILS else "%d CHECK(S) FAILED" % len(FAILS))
sys.exit(1 if FAILS else 0)
