#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""多人同时玩：三个客户端同时要决策，看会不会互相排队。"""
import json, statistics, sys, threading, time, urllib.request

# 默认测本机；测局域网就传参：./tests/jev_concurrent_test.py http://192.168.1.5:8760
# 跑之前服务得先起着，否则这里连不上。
BASE = (sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://127.0.0.1:8760")
S = BASE + "/jev/decide"
st = json.load(open('./sample_state.json'))
body = json.dumps(st).encode()
results, lock = {}, threading.Lock()

def player(n, rounds=6):
    mine = []
    for i in range(rounds):
        t0 = time.time()
        req = urllib.request.Request(S, data=body, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=60) as r:
            d = json.loads(r.read().decode())
        mine.append(d['latency_ms'])
    with lock:
        results[n] = mine

ts = [threading.Thread(target=player, args=(n,)) for n in (1, 2, 3)]
t0 = time.time()
for t in ts: t.start()
for t in ts: t.join()
wall = (time.time() - t0) * 1000

print("三个玩家各打 6 板，全程同时进行：\n")
allv = []
for n in (1, 2, 3):
    v = results.get(n, [])
    allv += v
    print("  玩家%d  每板耗时 中位 %4.0fms · 最慢 %4.0fms" % (n, statistics.median(v), max(v)))
print()
print("  三个人合计 18 次决策，总墙钟 %.1fs（串行的话会是 %.1fs）" % (
    wall / 1000, sum(allv) / 1000))
print("  全部决策中位 %.0fms · 最慢 %.0fms" % (statistics.median(allv), max(allv)))
print()
# 判据要拿中位和总墙钟比：最慢的那个由 API 自己的抖动决定，跟排队无关。
# 串行的话 18 次决策的墙钟 ≈ 各次耗时之和；并行则接近「最慢那位玩家的总和」。
serial = sum(allv) / 1000
med_ok = statistics.median(allv) < 700
speedup = serial / (wall / 1000)
print("  并行加速比 %.1f×（串行 %.1fs → 实际 %.1fs）" % (speedup, serial, wall / 1000))
print("  结论：%s" % (
    "三个人同时打互不排队（连接池生效，每人中位仍是 %.0fms）" % statistics.median(allv)
    if med_ok and speedup > 1.5 else
    "有人在排队，最慢 %.0fms" % max(allv)))
