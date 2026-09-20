#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""陈旧连接测试：第一趟假装被隧道掐了（既不回也不关），看会不会换新连接立刻救回来。

对照的是看门狗抓到的真实情况：
  决策 4104ms，换新连接重试同一请求只要 341ms —— 也就是说那 4 秒纯粹是白等。
"""
import http.server
import json
import socket
import sys
import threading
import time

sys.path.insert(0, ".")
import server

fails = 0
def ck(name, cond, ev=""):
    global fails
    print(("PASS  " if cond else "FAIL  ") + name + ("   [" + ev + "]" if ev else ""))
    if not cond:
        fails += 1

hits = {"n": 0}
lock = threading.Lock()

class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *a):
        pass
    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(n)
        with lock:
            hits["n"] += 1
            first = hits["n"] == 1
        if first:
            # 不回应、也不关闭：模拟 keep-alive 连接被隧道悄悄掐掉（客户端只会干等）
            time.sleep(30)
            return
        body = json.dumps({
            "model": "jev-test", "usage": {"input_tokens": 918, "output_tokens": 3},
            "answers": {"place": {"type": "choice", "choice": "p3", "confidence": 0.5,
                                  "probabilities": {"p3": 1.0}}},
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()

server.CFG["endpoint"] = "http://127.0.0.1:%d/v1/systemone" % port
server.CFG["timeout"] = 30
for _s in server._slots:      # 连接池：把每条残留连接都清掉
    _s["c"] = None

q = {"place": {"type": "choice", "instructions": "x", "criteria": {"p3": "y"}}}
t0 = time.time()
answers, usage, model = server.call_jev("state", q)
ms = (time.time() - t0) * 1000
tim = dict(server.LAST_CALL_TIMING)

ck("第一趟被掐住时不会一直干等（1.2s 就判断为陈旧连接）", ms < 2600,
   "整体 %.0fms（对照：不修的话这里会等 30s）" % ms)
ck("换新连接后拿到了正常答案", answers.get("place", {}).get("choice") == "p3",
   "choice=%s" % answers.get("place", {}).get("choice"))
ck("记录里标出了「重试过」", tim.get("retried") is True,
   "retried=%s · attempt=%s" % (tim.get("retried"), tim.get("attempt")))
ck("服务端确实收到了两次请求", hits["n"] == 2, "收到 %d 次" % hits["n"])

# 第二趟：连接已经用过了且是好的，应该一次就成、不再重试
t0 = time.time()
oa, _, _ = server.call_jev("state", q)
ms2 = (time.time() - t0) * 1000
tim2 = dict(server.LAST_CALL_TIMING)
ck("连接正常时一次就成，不触发重试", tim2.get("retried") is False and ms2 < 1200,
   "%.0fms · retried=%s" % (ms2, tim2.get("retried")))

srv.shutdown()
print("")
print("STALE-CONNECTION RETRY: ALL PASS" if fails == 0 else "%d CHECK(S) FAILED" % fails)
sys.exit(1 if fails else 0)
