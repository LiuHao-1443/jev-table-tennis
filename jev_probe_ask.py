#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Jev 问法对比实验：同一个球，用三种问法问同一个模型，看哪种它答得准。

  A 七选一 choice  ：直接问「落在哪个 y 区间」（逼它做多步心算）
  B 七个独立 noul  ：逐区间问「会落在这个区间吗」，取概率最大者（二值判断，不逼它互斥比较）
  C 三段 choice    ：只问「上/中/下」（降低分辨率，换准确率）

结论决定游戏里该用哪种提问方式。
"""
import json
import os
import statistics
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ENDPOINT = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"

Y_TOP, Y_BOTTOM = 96, 581
BALL_R = 10
PADDLE_X, HALF = 900, 56
LO, HI = Y_TOP + BALL_R, Y_BOTTOM - BALL_R
BANDS = [(152, 206), (206, 260), (260, 314), (314, 368), (368, 422), (422, 476), (476, 525)]
THIRDS = {"top": (152, 276), "mid": (276, 400), "bottom": (400, 525)}


def load_key():
    key = os.environ.get("TYPESAFE_API_KEY")
    if key:
        return key.strip()
    cfg = os.path.join(HERE, "jev.config.json")
    if os.path.exists(cfg):
        with open(cfg, encoding="utf-8") as f:
            return (json.load(f).get("api_key") or "").strip()
    raise SystemExit("缺少 TYPESAFE_API_KEY")


def fold(y, lo, hi):
    span = hi - lo
    t = (y - lo) % (2 * span)
    return lo + t if t <= span else lo + (2 * span - t)


def truth(bx, by, vx, vy):
    t = (PADDLE_X - BALL_R - bx) / vx
    y = fold(by + vy * t, LO, HI)
    band = next((i for i, (a, b) in enumerate(BANDS) if a <= y < b), len(BANDS) - 1)
    third = "top" if y < 276 else ("mid" if y < 400 else "bottom")
    return y, band, third


def state_text(bx, by, vx, vy):
    return (
        "Table tennis, top-down view. Table y range %d..%d (y grows downward, so larger y = lower on the table). "
        "Ball is at x=%d, y=%d, moving vx=%d px/s (rightward) and vy=%d px/s (%s). Radius %d. "
        "Balls bounce off the top edge y=%d and the bottom edge y=%d (vy reflects), so a ball moving down will "
        "come back up if it hits the bottom edge. Your paddle is the right paddle: face at x=%d, half-height %d, "
        "its center can be anywhere in y=%d..%d. You intercept the ball when its center reaches x=%d. "
        "Distance from the ball to your paddle: %d px, so the ball travels for about %.2f seconds before it reaches you."
        % (Y_TOP, Y_BOTTOM, bx, by, vx, vy, "downward" if vy > 0 else ("upward" if vy < 0 else "horizontally"),
           BALL_R, LO, HI, PADDLE_X, HALF, LO + HALF, HI - HALF, PADDLE_X - BALL_R,
           PADDLE_X - BALL_R - bx, (PADDLE_X - BALL_R - bx) / vx)
    )


def call(key, state, questions):
    payload = {"model": MODEL, "state": state, "questions": questions}
    req = urllib.request.Request(
        ENDPOINT, data=json.dumps(payload).encode(),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"}, method="POST")
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=120) as r:
        body = json.loads(r.read().decode())
    return body["answers"], time.time() - t0, body.get("usage", {})


def mode_a(key, state):
    q = {"band": {"type": "choice",
                  "instructions": "Which y-band will the ball be in when its center reaches your paddle face?",
                  "criteria": {"b%d" % i: "y %d-%d" % ab for i, ab in enumerate(BANDS)}}}
    ans, dt, u = call(key, state, q)
    a = ans["band"]
    return a.get("choice"), a.get("confidence"), dt, u


def mode_b(key, state):
    q = {}
    for i, (a, b) in enumerate(BANDS):
        q["b%d" % i] = {"type": "noul",
                        "instructions": "When the ball reaches your paddle face, will its y be between %d and %d?" % (a, b)}
    ans, dt, u = call(key, state, q)
    probs = {k: (v.get("noul") or 0.0) for k, v in ans.items()}
    best = max(probs.items(), key=lambda kv: kv[1])
    return best[0], best[1], dt, u


def mode_c(key, state):
    q = {"third": {"type": "choice",
                   "instructions": "When the ball reaches your paddle face, will it be in the top, middle or bottom third of your reachable range?",
                   "criteria": {k: "y %d-%d" % v for k, v in THIRDS.items()}}}
    ans, dt, u = call(key, state, q)
    a = ans["third"]
    return a.get("choice"), a.get("confidence"), dt, u


def main():
    key = load_key()
    rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    cases = [(600, 300, 700, 0), (600, 300, 700, 260), (600, 300, 700, -260), (700, 150, 600, -400),
             (700, 500, 600, 400), (500, 200, 800, 500), (800, 300, 500, -600), (400, 400, 900, -300)]
    cases = (cases * ((rounds // len(cases)) + 1))[:rounds]

    res = {"A 七选一": [0, [], []], "B 七noul": [0, [], []], "C 三段": [0, [], []]}
    detail = []
    for bx, by, vx, vy in cases:
        y, band, third = truth(bx, by, vx, vy)
        st = state_text(bx, by, vx, vy)
        row = {"case": "(%d,%d,%d,%d) 真值y=%.0f b%d %s" % (bx, by, vx, vy, y, band, third)}

        try:
            got, c, dt, u = mode_a(key, st)
            ok = (got == "b%d" % band)
            res["A 七选一"][0] += ok; res["A 七选一"][1].append(dt); res["A 七选一"][2].append(c or 0)
            row["A"] = "%s %s %.2f" % (got, "✅" if ok else "❌", c or 0)
        except Exception as e:  # noqa: BLE001
            row["A"] = "ERR " + str(e)[:30]

        try:
            got, c, dt, u = mode_b(key, st)
            ok = (got == "b%d" % band)
            res["B 七noul"][0] += ok; res["B 七noul"][1].append(dt); res["B 七noul"][2].append(c or 0)
            row["B"] = "%s %s %.2f" % (got, "✅" if ok else "❌", c or 0)
        except Exception as e:  # noqa: BLE001
            row["B"] = "ERR " + str(e)[:30]

        try:
            got, c, dt, u = mode_c(key, st)
            ok = (got == third)
            res["C 三段"][0] += ok; res["C 三段"][1].append(dt); res["C 三段"][2].append(c or 0)
            row["C"] = "%s %s %.2f" % (got, "✅" if ok else "❌", c or 0)
        except Exception as e:  # noqa: BLE001
            row["C"] = "ERR " + str(e)[:30]
        detail.append(row)

    print("%-34s %-16s %-16s %-16s" % ("球状态", "A 七选一", "B 七个独立 noul", "C 三段 choice"))
    print("-" * 88)
    for r in detail:
        print("%-34s %-16s %-16s %-16s" % (r["case"][:34], r["A"], r["B"], r["C"]))
    print("-" * 88)
    n = len(cases)
    for name, (hits, lat, cf) in res.items():
        if not lat:
            continue
        print("%-10s 命中 %d/%d = %3.0f%%   延迟中位 %.2fs   平均置信 %.3f" %
              (name, hits, n, 100.0 * hits / n, statistics.median(lat), sum(cf) / len(cf)))


if __name__ == "__main__":
    main()
