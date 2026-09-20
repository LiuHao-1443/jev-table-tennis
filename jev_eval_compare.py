#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
评测仪设计对比：同一批冻结的球，用四种问法问同一个 Jev，看哪种问法最干净、最准。

  A 现状      ：提示「还有约 X 秒到」+ 7 个粗区间
  B 去提示    ：只给原始读数（位置/速度/规则）+ 7 个粗区间
  C 去提示+细 ：只给原始读数 + 40 个细区间（中点误差从 ±27px 降到 ±4.7px）
  D 数字型    ：探测 API 是否支持直接输出数字（关键：支持的话本地换算彻底消失）

铁律：真实到达点只用于【本地打分】，一个字都不许进发给模型的文本。
      脚本会自我检查这一点（assert_no_leak），检查失败就拒绝出结论。
"""
import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ENDPOINT = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"

Y_TOP, Y_BOTTOM = 96, 581
BALL_R = 10
PADDLE_X, HALF = 900, 56
LO, HI = Y_TOP + BALL_R, Y_BOTTOM - BALL_R          # 152 .. 525
N_BINS_FINE = 40


def load_key():
    key = os.environ.get("TYPESAFE_API_KEY")
    if key:
        return key.strip()
    cfg = os.path.join(HERE, "jev.config.json")
    with open(cfg, encoding="utf-8") as f:
        return (json.load(f).get("api_key") or "").strip()


KEY = load_key()


def post(payload, timeout=60):
    req = urllib.request.Request(
        ENDPOINT, data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": "Bearer " + KEY, "Content-Type": "application/json"},
        method="POST")
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = json.loads(r.read().decode("utf-8"))
    return body, time.time() - t0


def fold(y, lo, hi):
    span = hi - lo
    t = (y - lo) % (2 * span)
    return lo + t if t <= span else lo + (2 * span - t)


def truth(bx, by, vx, vy):
    """真实到达点 + 它落在哪个区间。只用于打分。"""
    if vx <= 0:
        return None
    y = fold(by + vy * ((PADDLE_X - BALL_R - bx) / vx), LO, HI)
    return y


def bins(n):
    w = (HI - LO) / float(n)
    return [("b%d" % i, LO + w * i, LO + w * (i + 1)) for i in range(n)]


def bin_of(y, n):
    w = (HI - LO) / float(n)
    i = int((y - LO) / w)
    return max(0, min(n - 1, i))


def raw_state(bx, by, vx, vy):
    """只包含原始读数与台面规则，不含任何本地推算。"""
    dirn = "down" if vy > 0 else "up"
    return (
        "Table tennis, top-down view. The table runs from y=%d (top edge) to y=%d (bottom edge). "
        "y grows downward, so larger y is lower on the table. "
        "Ball: x=%d, y=%d, radius %d, velocity vx=%d px/s (moving right, toward the right paddle) "
        "and vy=%d px/s (moving %s). The ball's speed is constant until it is hit; it does not slow down. "
        "The ball bounces off the top edge y=%d and the bottom edge y=%d: when it reaches an edge its "
        "vy reverses and its y position reflects back, like a mirror. "
        "The right paddle is a vertical face at x=%d, centred on y, %d px tall (half-height %d). "
        "The ball is returned when the ball's centre reaches x=%d."
        % (Y_TOP, Y_BOTTOM, bx, by, BALL_R, vx, vy, dirn,
           LO, HI, PADDLE_X, 2 * HALF, HALF, PADDLE_X - BALL_R)
    )


def hint_line(bx, by, vx):
    """现状里那一句『还有约 X 秒到』—— 本地替它算好的关键中间量。"""
    eta = (PADDLE_X - BALL_R - bx) / float(vx)
    return " It will reach the paddle in about %.2f seconds." % eta


def question_band(n):
    return {
        "type": "choice",
        "instructions": ("When the ball's centre reaches the paddle at x=%d, which y range will the ball's "
                         "centre be at that moment? Work it out step by step, then choose one."
                         % (PADDLE_X - BALL_R)),
        "criteria": {"b%d" % i: "y %.1f to %.1f" % (a, b) for i, (_id, a, b) in enumerate(bins(n))},
    }


def ask(state_text, n, extra=None):
    q = {"band": question_band(n)}
    if extra:
        q.update(extra)
    payload = {"model": MODEL, "state": state_text, "questions": q}
    body, secs = post(payload)
    ans = (body.get("answers") or {}).get("band") or {}
    label = ans.get("choice")
    idx = None
    if isinstance(label, str) and label.startswith("b"):
        try:
            idx = int(label[1:])
        except ValueError:
            idx = None
    return {"idx": idx, "conf": ans.get("confidence"), "probs": ans.get("probabilities") or {},
            "usage": body.get("usage") or {}, "secs": secs, "model": body.get("model"),
            "raw": ans, "payload": payload}


def assert_no_leak(text, y):
    """自我检查：发给模型的文字里不许出现真实到达点。"""
    bad = []
    for probe in (str(int(round(y))), "%.1f" % y, "%.2f" % y, str(int(round(y)) + 1), str(int(round(y)) - 1)):
        if probe in text:
            bad.append(probe)
    if bad:
        raise SystemExit("泄漏！真实到达点出现在提示词里：%r" % bad)


def main():
    states = [
        (560, 300, 780, 260), (640, 480, 700, -420), (700, 220, 850, 520),
        (520, 400, 900, -640), (760, 330, 660, 180), (600, 180, 820, -260),
        (680, 520, 750, 300), (540, 260, 880, -520), (720, 380, 790, 640),
        (580, 460, 840, -180),
    ]
    rows = []
    print("=" * 78)
    print("评测仪对比：同一批 10 个冻结场景，四种问法")
    print("=" * 78)

    # ---------- D: 先探测 API 支不支持数字型问题 ----------
    print("\n[D] 探测 API 是否支持数字型输出（支持的话本地换算可以彻底消失）")
    shapes = [
        {"type": "number", "instructions": "At what y will the ball be when it reaches the paddle?"},
        {"type": "number", "instructions": "At what y will the ball be?", "criteria": {"min": LO, "max": HI}},
        {"type": "numeric", "instructions": "At what y will the ball be?"},
    ]
    for sh in shapes:
        try:
            body, secs = post({"model": MODEL, "state": raw_state(*states[0]), "questions": {"band": sh}})
            print("   %-92s -> 接受！%s" % (json.dumps(sh, ensure_ascii=False)[:92],
                                             json.dumps((body.get("answers") or {}).get("band"), ensure_ascii=False)))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:160].replace("\n", " ")
            print("   %-92s -> HTTP %s %s" % (json.dumps(sh, ensure_ascii=False)[:92], e.code, detail))
        except Exception as e:                     # noqa
            print("   %-92s -> %s" % (json.dumps(sh, ensure_ascii=False)[:92], e))

    # ---------- A / B / C ----------
    conds = [("A 现状：提示+7粗", 7, True), ("B 去提示：原始+7粗", 7, False), ("C 去提示：原始+40细", N_BINS_FINE, False)]
    for name, n, use_hint in conds:
        print("\n[%s]" % name)
        hits = 0
        errs, confs, toks, secs_all, answers = [], [], [], [], []
        for (bx, by, vx, vy) in states:
            y = truth(bx, by, vx, vy)
            text = raw_state(bx, by, vx, vy) + (hint_line(bx, by, vx) if use_hint else "")
            assert_no_leak(text, y)                # 铁律自检
            r = ask(text, n)
            if r["idx"] is None:
                print("     解析失败：%s" % json.dumps(r["raw"], ensure_ascii=False)[:90])
                continue
            ids, a, b = bins(n)[r["idx"]]
            center = (a + b) / 2.0
            ok = bin_of(y, n) == r["idx"]
            hits += 1 if ok else 0
            errs.append(abs(center - y))
            if r["conf"] is not None:
                confs.append((float(r["conf"]), 1 if ok else 0))
            toks.append((r["usage"] or {}).get("input_tokens") or 0)
            secs_all.append(r["secs"])
            answers.append((r["idx"], ok))
            print("      真实 y=%6.1f 落 %s | 它选 %s 中点 %6.1f 误差 %5.1fpx 置信 %.2f %s | %.0fms"
                  % (y, bin_of(y, n), ids, center, abs(center - y), r["conf"] or 0,
                     "命中" if ok else "偏了", r["secs"] * 1000))
        n_ok = len(errs)
        if n_ok:
            print("   ── 命中 %d/%d（%.0f%%）· 中点平均误差 %.1fpx · 平均 %d tok · 平均 %.0fms"
                  % (hits, n_ok, 100.0 * hits / n_ok, statistics.mean(errs),
                     statistics.mean(toks), statistics.mean(secs_all) * 1000))
            if confs:
                c = statistics.mean(x for x, _ in confs)
                acc = statistics.mean(y for _, y in confs)
                print("      置信度校准：它平均说 %.0f%% 有把握，实际命中 %.0f%%（差值 %+.0f 个点）"
                      % (c * 100, acc * 100, (acc - c) * 100))
        rows.append((name, hits, n_ok, statistics.mean(errs) if errs else None,
                     statistics.mean(toks) if toks else None))

    print("\n" + "=" * 78)
    print("汇总")
    print("=" * 78)
    for name, hits, n_ok, err, tok in rows:
        print("  %-22s 命中 %d/%d  平均误差 %s  平均 %s tok"
              % (name, hits, n_ok, ("%.1fpx" % err) if err else "n/a", ("%.0f" % tok) if tok else "n/a"))


if __name__ == "__main__":
    main()
