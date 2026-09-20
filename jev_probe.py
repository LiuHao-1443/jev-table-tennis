#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Jev 能力探针：用已知标准答案的台面状态去考 Jev，量化它的「准度 + 延迟 + 置信度」。

用法：
  export TYPESAFE_API_KEY=...      # 或写进 jev.config.json
  python3 jev_probe.py [轮数]

结论直接决定游戏怎么设计：模型准不准 → 决定它能不能真的接住球。
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

# 与游戏完全一致的物理参数
Y_TOP, Y_BOTTOM = 96, 581
BALL_R = 10
PADDLE_X, HALF = 900, 56
LO, HI = Y_TOP + BALL_R, Y_BOTTOM - BALL_R          # 球的可用 y 范围 106..571
BANDS = [(152, 206), (206, 260), (260, 314), (314, 368), (368, 422), (422, 476), (476, 525)]


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
    """标准答案：球到达拍面时的 y，以及所属区间。"""
    t = (PADDLE_X - BALL_R - bx) / vx
    y = fold(by + vy * t, LO, HI)
    for i, (a, b) in enumerate(BANDS):
        if a <= y < b:
            return y, "b%d" % i, t
    return y, "b%d" % (len(BANDS) - 1), t


def ask(key, bx, by, vx, vy):
    state = (
        "Table tennis, top-down view. Table y range %d..%d (y grows downward). "
        "Ball at x=%d, y=%d, velocity vx=%d, vy=%d px/s, radius %d. "
        "Balls bounce off y=%d and y=%d: when the ball's center reaches those bounds its vy is reflected "
        "(vy = -vy) and it keeps moving. Your paddle is the right paddle: face at x=%d, half-height %d. "
        "You intercept the ball when its center reaches x=%d."
        % (Y_TOP, Y_BOTTOM, bx, by, vx, vy, BALL_R, LO, HI, PADDLE_X, HALF, PADDLE_X - BALL_R)
    )
    payload = {
        "model": MODEL,
        "state": state,
        "questions": {
            "band": {
                "type": "choice",
                "instructions": "Which y-band will the ball be in when its center reaches your paddle face at x=%d?"
                                % (PADDLE_X - BALL_R),
                "criteria": {"b%d" % i: "y %d-%d" % (a, b) for i, (a, b) in enumerate(BANDS)},
            }
        },
    }
    req = urllib.request.Request(
        ENDPOINT, data=json.dumps(payload).encode(),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"}, method="POST")
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=120) as r:
        body = json.loads(r.read().decode())
    dt = time.time() - t0
    ans = body["answers"]["band"]
    return ans["choice"], ans.get("confidence"), ans.get("probabilities", {}), dt, body.get("usage", {})


def main():
    rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    key = load_key()
    # 覆盖：平飞、下坠、上飘、需要撞上下沿反弹的各一种
    cases = [
        (600, 300, 700, 0), (600, 300, 700, 260), (600, 300, 700, -260),
        (700, 150, 600, -400), (700, 500, 600, 400), (500, 200, 800, 500),
        (800, 300, 500, -600), (400, 400, 900, -300),
    ]
    cases = (cases * ((rounds // len(cases)) + 1))[:rounds]

    hits = 0
    lat, conf = [], []
    print("%-28s %-6s %-6s %-8s %-8s %s" % ("球状态(x,y,vx,vy)", "真值", "Jev", "命中", "置信度", "分布(前3)"))
    print("-" * 96)
    for bx, by, vx, vy in cases:
        y, want, t = truth(bx, by, vx, vy)
        try:
            got, c, probs, dt, usage = ask(key, bx, by, vx, vy)
        except Exception as exc:  # noqa: BLE001
            print("调用失败：%s" % exc)
            continue
        ok = (got == want)
        hits += ok
        lat.append(dt)
        if c is not None:
            conf.append(c)
        top = sorted(probs.items(), key=lambda kv: -kv[1])[:3]
        print("%-28s %-6s %-6s %-8s %-8.2f %s" %
              ("(%d,%d,%d,%d) 真值y=%.0f" % (bx, by, vx, vy, y), want, got,
               "✅" if ok else "❌", c or 0, ", ".join("%s:%.2f" % kv for kv in top)))

    n = len(lat)
    print("-" * 96)
    print("命中率    : %d/%d = %.0f%%" % (hits, n, 100.0 * hits / max(1, n)))
    print("延迟      : 中位 %.2fs · 最小 %.2fs · 最大 %.2fs" %
          (statistics.median(lat), min(lat), max(lat)))
    if conf:
        print("平均置信度: %.3f（越低说明模型越不确定）" % (sum(conf) / len(conf)))
    print("结论      : %s" % ("可以真打——按命中率调时间基准" if hits >= n * 0.6 else
                              "物理推算不可靠，需要把问题切成更简单的判断"))


if __name__ == "__main__":
    main()
