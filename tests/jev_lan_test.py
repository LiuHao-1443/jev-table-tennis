#!/usr/bin/env python3
"""局域网地址那一行不能骗人。

踩过的坑：lan_ip() 原来用「连一下 10.255.255.255 看内核挑哪张网卡」，
开了代理时默认路由走 utun，拿回来的是 198.18.x.x（Clash fake-ip 段）——
横幅上照样打印出来，但发给别人是打不开的。
"""
import importlib.util
import os
import re
import sys

spec = importlib.util.spec_from_file_location("jevserver", os.path.join(os.path.dirname(__file__), "..", "server.py"))
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)

FAILS = []


def check(name, cond, extra=""):
    print(("PASS  " if cond else "FAIL  ") + name + (("   [" + extra + "]") if extra else ""))
    if not cond:
        FAILS.append(name)


ip = server.lan_ip()
check("lan_ip() 给出的地址是合法 IPv4", bool(re.match(r"^\d+\.\d+\.\d+\.\d+$", ip)), "拿到 " + ip)
check("不是环回地址", not ip.startswith("127."), ip)
check("不是 fake-ip 段（代理假地址，发给别人打不开）",
      not ip.startswith(("198.18.", "198.19.")), ip)
check("不是链路本地地址", not ip.startswith("169.254."), ip)
check("筛子本身：fake-ip 与环回都判为不可用",
      (not server._usable_lan_ip("198.18.0.1"))
      and (not server._usable_lan_ip("127.0.0.1"))
      and (not server._usable_lan_ip("169.254.1.2"))
      and server._usable_lan_ip("10.5.2.233")
      and server._usable_lan_ip("192.168.1.9"))
check("私有段优先于其它段",
      server._ip_score("192.168.1.9") < server._ip_score("10.5.2.233") < server._ip_score("8.8.8.8"))

print("")
print("LAN ADDRESS: ALL PASS" if not FAILS else "%d CHECK(S) FAILED" % len(FAILS))
sys.exit(1 if FAILS else 0)
