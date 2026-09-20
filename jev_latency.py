#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""延迟归因：到底是「状态太长」还是「问题太多」在拖慢 Jev？

同一个球，三种问法各打 N 次，比中位延迟：
  full5  ：游戏当前的完整状态描述 + 5 个问题
  full1  ：同样的完整描述，只问 1 个问题（落点区间）
  short1 ：精简描述 + 1 个问题
"""
import json
import os
import statistics
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server as S  # noqa: E402

N = int(sys.argv[1]) if len(sys.argv) > 1 else 4

STATE = {
    "kind": "incoming",
    "persona": "steady",
    "table": {"y_top": 96, "y_bottom": 581, "x_left": 78, "x_right": 1042},
    "ball": {"x": 600, "y": 300, "vx": 700, "vy": 260, "r": 10, "speed": 430},
    "you": {"side": "right", "paddle_x": 900, "paddle_half": 56, "paddle_center": 338,
            "max_speed": 900, "machine_heat": 1, "time_to_arrival_s": 0.414,
            "last_command": {"move_to": 338, "recover_to": 338, "speed": 900}},
    "opponent": {"paddle_x": 100, "paddle_center": 200},
    "score": {"you": 3, "opponent": 5}, "games": {"you": 0, "opponent": 1}, "rally": 7,
    "physics": {"max_bounce_angle_rad": 0.92, "speedup_per_hit": 1.045,
                "max_ball_speed": 1180, "min_vy_ratio": 0.13},
}

SHORT = (
    "Table tennis, top-down. Table y=%d..%d (y grows downward). The ball is at x=%.0f, y=%.0f, "
    "moving vx=%.0f, vy=%.0f px/s; radius %.0f. It bounces off y=%.0f and y=%.0f (vy reflects). "
    "You are the right paddle: face at x=%.0f, half-height %.0f, center can be y=%.0f..%.0f. "
    "You intercept when the ball's center reaches x=%.0f, which is %.0f px away, so it arrives in %.2f s."
)


def short_text(st):
    b, tb, you = st["ball"], st["table"], st["you"]
    r = b["r"]
    face = you["paddle_x"] - r
    return SHORT % (tb["y_top"], tb["y_bottom"], b["x"], b["y"], b["vx"], b["vy"], r,
                    tb["y_top"] + r, tb["y_bottom"] - r, you["paddle_x"], you["paddle_half"],
                    tb["y_top"] + you["paddle_half"], tb["y_bottom"] - you["paddle_half"],
                    face, face - b["x"], (face - b["x"]) / b["vx"])


def one_call(text, questions):
    payload = {"model": S.CFG["model"], "state": text, "questions": questions}
    req = urllib.request.Request(
        S.CFG["endpoint"], data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + S.CFG["api_key"]},
        method="POST")
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=120) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    return time.time() - t0, body.get("usage", {}), body.get("answers", {})


def main():
    full = S.describe(STATE)
    qs = S.build_questions(STATE, serving=False)
    band_only = {"band": qs["band"]}
    short = short_text(STATE)

    print("完整描述 %d 字符 / %d 问题 · 精简描述 %d 字符" % (len(full), len(qs), len(short)))
    print()
    print("%-8s %-8s %-8s %-10s %s" % ("问法", "延迟中位", "延迟范围", "输入 token", "它答了什么"))
    print("-" * 78)
    for name, text, questions in (("full5", full, qs), ("full1", full, band_only), ("short1", short, band_only)):
        lat, tok, answers = [], [], []
        for _ in range(N):
            try:
                dt, usage, ans = one_call(text, questions)
            except Exception as exc:  # noqa: BLE001
                print("%-8s 调用失败 %s" % (name, exc))
                continue
            lat.append(dt)
            tok.append(usage.get("input_tokens") or 0)
            b = ans.get("band") or {}
            answers.append("%s/%s" % (b.get("choice"), round(b.get("confidence") or 0, 2)))
        if lat:
            print("%-8s %-8.2fs %-8s %-10d %s" % (
                name, statistics.median(lat),
                "%.1f~%.1fs" % (min(lat), max(lat)),
                round(statistics.mean(tok)), " ".join(answers)))
    print("-" * 78)
    print("提示：延迟决定球速上限 = 964 / (延迟 + 0.6) px/s")


if __name__ == "__main__":
    main()
