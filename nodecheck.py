#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""节点体检：换一个代理节点后跑一次，量出「这个节点对 JEV 到底好不好」。

为什么不能看代理客户端里的延迟数字：
    那个数字通常是打 Google/Cloudflare 之类【边缘就近】的测试地址，
    只能反映「你 → 节点」。而 JEV 真正要连的 api.typesafe.ai 在
    AWS 美西俄勒冈，决定手感的是「节点 → 俄勒冈」这一段，
    客户端那个数字基本量不到它。

这个脚本量三件跟手感直接相关的事：
    1. 出口到底落在哪（cloudflare trace 的 colo）
    2. 热连接上跑 N 次真实决策 → 中位 / p90 / 最慢（这才是游戏里的每步耗时）
    3. 新建连接的代价 → 掉线重连那一下要多久

用法：
    python3 nodecheck.py --label "洛杉矶01"     # 换完节点跑一次
    python3 nodecheck.py --summary             # 把测过的节点排个序

结果追加在 nodecheck.tsv，可以在多个节点之间反复比较。
"""
import argparse
import json
import os
import statistics
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import server  # noqa: E402  只借用它的配置读取（API key 不会打印出来）

TSV = os.path.join(HERE, "nodecheck.tsv")


def bannered(s):
    print(s, flush=True)


def curl_trace():
    """出口位置。cloudflare 的 trace 会告诉我们是哪个机房接的。"""
    try:
        with urllib.request.urlopen("https://www.cloudflare.com/cdn-cgi/trace", timeout=25) as r:
            txt = r.read().decode("utf-8", "replace")
        d = dict(ln.split("=", 1) for ln in txt.strip().split("\n") if "=" in ln)
        return d.get("colo", "?"), d.get("loc", "?"), d.get("ip", "?")
    except Exception as exc:
        return "?", "?", "(%s)" % type(exc).__name__


def connect_cost(reps=3):
    """新建连接要多久：TCP + TLS 握手 + 第一个字节。掉线重连就付这个钱。"""
    scheme, host, port, path = server._endpoint_parts()
    out = []
    for _ in range(reps):
        t0 = time.time()
        conn = server._new_conn()
        try:
            conn.connect()
            t_tls = (time.time() - t0) * 1000
            conn.close()
            out.append(t_tls)
        except Exception:
            try:
                conn.close()
            except Exception:
                pass
    return out


def net_probe(n=12, gap=0.35):
    """最灵敏的一把尺子：发一个「合法 JSON 但模型不接受」的请求。

    它会在校验阶段就被拒（400 Invalid request.），【完全不进模型】，
    所以量到的就是「本机 → 代理出口 → 俄勒冈」这一趟的净成本。
    同一个 host、同一条路径、同一个端口，跟真实决策没有路由差异，
    而噪声只有完整决策的一半左右 —— 节点之间那几十毫秒的差别就看它。
    而且它不消耗 token。
    """
    scheme, host, port, path = server._endpoint_parts()
    bad = json.dumps({
        "model": server.CFG["model"], "state": "x",
        "questions": {"p": {"type": "number", "instructions": "nope"}},
    }).encode()
    headers = {"Authorization": "Bearer " + server.CFG["api_key"], "Content-Type": "application/json"}

    conn = server._new_conn()
    conn.connect()
    lat = []
    for i in range(n):
        t0 = time.time()
        try:
            conn.request("POST", path, body=bad, headers=headers)
            r = conn.getresponse()
            r.read()
            lat.append((time.time() - t0) * 1000)
        except Exception:
            try:
                conn.close()
            except Exception:
                pass
            conn = server._new_conn()
            conn.connect()
        if i < n - 1:
            time.sleep(gap)
    conn.close()
    return lat


def warm_calls(n, gap=0.6):
    """热连接上的真实决策耗时——这就是游戏里每隔一步等的时间。"""
    st = json.load(open(os.path.join(HERE, "sample_state.json"))) if \
        os.path.exists(os.path.join(HERE, "sample_state.json")) else json.load(open("/tmp/st1.json"))
    scheme, host, port, path = server._endpoint_parts()
    payload = json.dumps({
        "model": server.CFG["model"],
        "state": server.describe_pure(st),
        "questions": server.build_questions(st, False),
    }).encode()
    headers = {"Authorization": "Bearer " + server.CFG["api_key"], "Content-Type": "application/json"}

    conn = server._new_conn()
    conn.connect()
    lat = []
    for i in range(n):
        t0 = time.time()
        try:
            conn.request("POST", path, body=payload, headers=headers)
            r = conn.getresponse()
            r.read()
            lat.append((time.time() - t0) * 1000)
        except Exception as exc:
            bannered("  第 %d 次出错(%s)，重连" % (i + 1, type(exc).__name__))
            try:
                conn.close()
            except Exception:
                pass
            conn = server._new_conn()
            conn.connect()
        if i < n - 1:
            time.sleep(gap)
    conn.close()
    return lat


def pct(sorted_vals, p):
    if not sorted_vals:
        return 0
    return sorted_vals[min(len(sorted_vals) - 1, int(len(sorted_vals) * p))]


def do_check(label, n):
    bannered("=" * 62)
    bannered("节点体检：%s" % label)
    bannered("=" * 62)

    colo, loc, ip = curl_trace()
    bannered("  出口        : colo=%s · loc=%s · ip=%s" % (colo, loc, ip))

    cc = connect_cost()
    bannered("  新建连接    : %s" % " / ".join("%.0fms" % x for x in cc) +
             "   ← 掉线重连要付这个钱")

    bannered("  探测纯网络那一趟（不进模型）…")
    net = net_probe()
    ns = sorted(net)
    nmed, np90, nmx = statistics.median(ns), pct(ns, 0.9), ns[-1]
    bannered("  纯网络一趟  : 中位 %.0fms · p90 %.0fms · 最慢 %.0fms   ← 排节点主要看这行"
             % (nmed, np90, nmx))

    bannered("  跑 %d 次真实决策…" % n)
    lat = warm_calls(n)
    s = sorted(lat)
    med, p90, mx = statistics.median(s), pct(s, 0.9), s[-1]
    slow = sum(1 for x in s if x > 1000)
    bannered("  每步决策    : 中位 %.0fms · p90 %.0fms · 最慢 %.0fms · 慢(>1s) %d/%d"
             % (med, p90, mx, slow, len(s)))
    bannered("  拆开        : 网络 %.0f + 服务端 %.0f + 模型 ~24 = %.0f"
             % (nmed, med - nmed - 24, med))
    bannered("")

    with open(TSV, "a", encoding="utf-8") as f:
        f.write("%s\t%s\t%s\t%s\t%.0f\t%.0f\t%.0f\t%d\t%d\t%.0f\t%.0f\n" % (
            time.strftime("%m-%d %H:%M"), label, colo, loc,
            med, p90, mx, slow, len(s), statistics.median(cc) if cc else 0, nmed))
    bannered("  已记入 %s" % TSV)
    bannered("")


def summary():
    if not os.path.exists(TSV):
        bannered("还没有记录。换个节点跑一次：python3 nodecheck.py --label \"洛杉矶01\"")
        return
    rows = []
    with open(TSV, encoding="utf-8") as f:
        for ln in f:
            p = ln.rstrip("\n").split("\t")
            if len(p) == 10:                      # 老格式：补一个空的网络列
                p.append("0")
            if len(p) >= 11:
                rows.append(p)
    rows.sort(key=lambda r: float(r[10]) or float(r[4]))     # 先按更灵敏的网络那趟排
    bannered("%-12s %-14s %-5s %8s %6s %7s %7s %8s %7s" % (
        "时间", "节点", "出口", "纯网络", "中位", "p90", "最慢", "慢(>1s)", "重连"))
    bannered("-" * 82)
    for r in rows:
        bannered("%-12s %-14s %-5s %7sms %5sms %6sms %6sms %5s/%-3s %6sms" % (
            r[0], r[1], r[2], r[10], r[4], r[5], r[6], r[7], r[8], r[9]))
    bannered("")
    bannered("  按【纯网络那趟】排序：节点之间真正的差别就在这一列。")
    bannered("  但对游戏体验，【最慢】和【慢次数】比中位更重要 ——")
    bannered("  一次 9 秒的决策等于这一板直接没救，而中位差 30ms 根本感觉不到。")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="当前节点", help="给这次测试起个名字，比如 洛杉矶01")
    ap.add_argument("--n", type=int, default=30, help="跑多少次决策（默认 30）")
    ap.add_argument("--summary", action="store_true", help="打印所有测过的节点对比表")
    a = ap.parse_args()
    if a.summary:
        summary()
    else:
        do_check(a.label, a.n)
