#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
方案对比：把「问球会落在哪个区间，本地再取中点」换成「直接问拍子该放哪」。

  A 现状   ：提示到达时间 + 问球落在哪个 y 区间（本地取中点当落点）
  E 纯驱动 ：不给任何提示 + 直接问「拍子中心放在哪个位置」，选项就是真实可达的拍子位置

判分标准用同一个物理标准：拍心与真实到达点之差 ≤ 拍高/4（=28px）算接住。
另外报告它自报的置信度，用于看校准。
"""
import json
import os
import statistics
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from jev_eval_compare import (LO, HI, HALF, PADDLE_X, BALL_R, MODEL,   # noqa: E402
                              load_key, post, truth, raw_state, assert_no_leak, bins, bin_of)

N = 7
PLACE = [round(LO + (HI - LO) * (i + 0.5) / N, 1) for i in range(N)]   # 7 个真实可达的拍心位置
TOL = HALF / 2.0                                                        # 28px：接住标准

states = [
    (560, 300, 780, 260), (640, 480, 700, -420), (700, 220, 850, 520),
    (520, 400, 900, -640), (760, 330, 660, 180), (600, 180, 820, -260),
    (680, 520, 750, 300), (540, 260, 880, -520), (720, 380, 790, 640),
    (580, 460, 840, -180),
]


def ask_place(text):
    q = {"place": {
        "type": "choice",
        "instructions": ("The ball is coming toward you. Where should the centre of your paddle be, so that the "
                         "ball hits it? Work out where the ball will be when it reaches x=%d, then choose the "
                         "paddle position closest to that." % (PADDLE_X - BALL_R)),
        "criteria": {"p%d" % i: "paddle centre at y=%.1f" % y for i, y in enumerate(PLACE)},
    }}
    body, secs = post({"model": MODEL, "state": text, "questions": q})
    a = (body.get("answers") or {}).get("place") or {}
    label = a.get("choice")
    idx = None
    if isinstance(label, str) and label.startswith("p"):
        try:
            idx = int(label[1:])
        except ValueError:
            idx = None
    return {"idx": idx, "conf": a.get("confidence"), "secs": secs,
            "tok": (body.get("usage") or {}).get("input_tokens") or 0,
            "raw": a, "probs": a.get("probabilities") or {}}


print("=" * 78)
print("E 纯驱动：不给提示，直接问「拍子放哪」（选项=真实可达位置，本地零换算）")
print("=" * 78)
hits, errs, confs, toks, secs_all, wrong = 0, [], [], [], [], []
for (bx, by, vx, vy) in states:
    y = truth(bx, by, vx, vy)
    text = raw_state(bx, by, vx, vy)
    assert_no_leak(text, y)                       # 铁律自检：真相不许进提示词
    r = ask_place(text)
    if r["idx"] is None:
        print("   解析失败 %s" % json.dumps(r["raw"], ensure_ascii=False)[:80])
        continue
    chosen = PLACE[r["idx"]]
    err = abs(chosen - y)
    ok = err <= TOL
    hits += 1 if ok else 0
    errs.append(err)
    if r["conf"] is not None:
        confs.append(float(r["conf"]))
    toks.append(r["tok"])
    secs_all.append(r["secs"])
    if not ok:
        wrong.append((y, chosen, err))
    print("   真实 y=%6.1f | 它把拍子放到 %6.1f（误差 %5.1fpx）置信 %.2f %s | %d tok %.0fms"
          % (y, chosen, err, r["conf"] or 0, "接住" if ok else "漏球", r["tok"], r["secs"] * 1000))

n = len(errs)
print("\n── 接住 %d/%d（%.0f%%）· 平均误差 %.1fpx · 平均 %d tok · 平均 %.0fms"
      % (hits, n, 100.0 * hits / n, statistics.mean(errs), statistics.mean(toks),
         statistics.mean(secs_all) * 1000))
if confs:
    print("   置信度校准：平均自报 %.0f%%，实际接住 %.0f%%（差值 %+.0f 点）"
          % (statistics.mean(confs) * 100, 100.0 * hits / n, (100.0 * hits / n - statistics.mean(confs) * 100)))
print("\n对照（同一批球，同一判分标准 ≤%.0fpx）：" % TOL)
print("   A 现状（给提示 + 问区间 + 本地取中点）：见 jev_eval_compare.py —— 中点平均误差 53.2px")
print("   E 纯驱动（不给提示 + 直接选拍位）    ：平均误差 %.1fpx" % statistics.mean(errs))
