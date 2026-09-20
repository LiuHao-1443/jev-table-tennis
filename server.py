#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
JEV 大脑中继（TypeSafe SystemOne 协议）
=====================================
让 TypeSafe 的 Jev（System One 决策模型）真正驱动乒乓球游戏右侧的 JEV。

协议不是 chat：Jev 只回答**类型化问题**（choice / noul），所以这里做三件事：
  1. 把台面数值状态翻译成它读得懂的英文情境描述（含「球到你还有几秒」——实测这一句把命中率从 50% 拉到 88%）
  2. 一次调用问完整套问题：落点区间 / 回球方向 / 发力 / 待命位 / 垃圾话
  3. 把它的答案解码成机械臂指令（move_to / speed / recover_to）；解码只是把区间标签换算成像素，不做任何决策

Jev 实测：命中率 88%、延迟中位 1.9s、输入约 700 tok/次（$0.042/Mtok ⇒ 约 $0.00003/次）

配置（环境变量优先，其次同目录 jev.config.json）：
  JEV_API_KEY    TypeSafe key（只留在服务端，不进网页）
  JEV_ENDPOINT   默认 https://api.typesafe.ai/v1/systemone
  JEV_MODEL      默认 jev-latest
  JEV_PORT       默认 8760
  JEV_TIMEOUT    单次调用超时秒数，默认 30

用法：
  python3 server.py                 # 真实模型
  python3 server.py --mock-brain    # 测试替身（不调用模型，仅验证链路）
"""

import json
import math
import http.client
import queue
import mimetypes
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "jev.config.json")
MOCK = "--mock-brain" in sys.argv
CAP_OVERRIDE = None    # --cap N：手动指定 pure 模式的球速上限（px/s）
HOST = "0.0.0.0"       # --host 127.0.0.1 可以只绑本机（默认让局域网里别人也能玩）

# ---------------------------------------------------------------------------
# 两种模式
#   pure     ：只验证 Jev 的决策能力。零本地算法：不给到达时间、不给区间中点、
#              不做 aim/power 换算。它选的选项**就是**拍子要去的那个 y，本地只查表。
#              球速固定，不随它自己的延迟变化（否则测试条件会被被测对象改动）。
#   assisted ：为了好玩而调过的版本（本地替它算到达时间 + 区间取中点 + aim/power 换算）。
#              留着当对照，两者的差值 = 本地算法值多少分。
# ---------------------------------------------------------------------------
MODE = "pure"
for _i, _a in enumerate(sys.argv):
    if _a == "--mode" and _i + 1 < len(sys.argv):
        MODE = sys.argv[_i + 1]
    elif _a.startswith("--mode="):
        MODE = _a.split("=", 1)[1]
    elif _a == "--host" and _i + 1 < len(sys.argv):
        HOST = sys.argv[_i + 1]
    elif _a.startswith("--host="):
        HOST = _a.split("=", 1)[1]
    elif _a == "--cap" and _i + 1 < len(sys.argv):
        try:
            CAP_OVERRIDE = float(sys.argv[_i + 1])
        except ValueError:
            raise SystemExit("--cap 需要一个数字（px/s）")
    elif _a.startswith("--cap="):
        try:
            CAP_OVERRIDE = float(_a.split("=", 1)[1])
        except ValueError:
            raise SystemExit("--cap 需要一个数字（px/s）")
if MODE not in ("pure", "assisted"):
    raise SystemExit("--mode 只能是 pure 或 assisted")

# pure 模式下的球速上限：固定值，由「假设延迟 2.0s」推出来，与实测延迟无关
MAX_SPEED_CAP = 1180.0          # 球速的物理天花板（与前端 MAX_SPEED 一致）
PURE_ASSUMED_LATENCY_S = 0.55
PURE_TEMPO_MARGIN_S = 1.20


def pure_speed_cap(table_w=964.0):
    """pure 模式的固定球速上限（px/s）。不读任何实测延迟，避免测试条件被被测对象改动。

    这个常数是按【实测】的决策延迟定的，不是拍脑袋：
      实测（长连接修好之后、美国节点）：一次决策中位 0.36s、p90 约 0.5s。
      单程飞行必须容得下：最后一次决策的往返 0.55s
                        + 机械臂横跨全台 0.42s
                        + 至少还有一次修正的机会 0.55s
                        + 安全余量 0.23s
      ⇒ 964 / 1.75 = 551 px/s
    ── 注意：它仍然是【固定常数】，不读运行时的实测延迟。理由同上：
       否则「测试条件」会被被测对象自己的延迟改动，不同场次没法横向比较。
       （早期版本这里写 2.0+0.9=2.9 ⇒ 上限只有 332，那是长连接还没修好时的数。）"""
    if CAP_OVERRIDE:
        return float(CAP_OVERRIDE)
    return table_w / (PURE_ASSUMED_LATENCY_S + PURE_TEMPO_MARGIN_S)


def tempo_report(cap, table_w=964.0, latency_s=0.55, arm_travel_s=0.42):
    """在给定球速上限下，「它还来不来得及算」的算术。

    实测：一次决策中位 ~0.36s、p90 ~0.5s（修好长连接 + 美国节点）。球从它这一侧飞到人类再回来，
    单程飞行 = 台宽/球速。要它来得及，单程必须 > 决策耗时 + 机械臂横跨全台的耗时。
    """
    flight = table_w / cap
    room = flight - latency_s - arm_travel_s
    # 单程里容得下几次「提问→回答」：第 k 次在 (k-1)*L 时发出、k*L 时回来，要求 k*L <= flight
    n_decisions = max(1, int(flight / latency_s))
    return {"cap": cap, "flight_s": flight, "room_s": room, "decisions": n_decisions,
            "ok": room > 0}

SERVE_EXT = {".html", ".css", ".js", ".mjs", ".png", ".jpg", ".jpeg", ".svg",
             ".webp", ".gif", ".ico", ".woff", ".woff2", ".txt"}
SERVE_DENY = {"jev.config.json", "server.py", "README.md"}

# 与前端一致的物理常量（前端把台面参数也发过来了，这里只是默认值）
DEFAULT_ENDPOINT = "https://api.typesafe.ai/v1/systemone"
DEFAULT_MODEL = "jev-latest"
NBANDS = 7
PRICE_PER_INPUT_TOKEN_USD = 0.042 / 1e6

TAUNTS = {
    "t1": "这球我算过了",
    "t2": "你的站位我看得见",
    "t3": "再来",
    "t4": "这板压你反手",
    "t5": "热身而已",
    "t6": "别慌",
}

# 决策留档：每问一次模型就记一条（含完整输入/输出/耗时/用量），供「JEV 决策日志」面板回看。
# 页面自己留最近若干条用于即时展示，这里留全场的，刷新页面也不会丢。
HISTORY = deque(maxlen=400)
HISTORY_SEQ = [0]


def load_config():
    cfg = {
        "api_key": "",
        "endpoint": DEFAULT_ENDPOINT,
        "model": DEFAULT_MODEL,
        "port": 8760,
        "timeout": 30.0,
    }
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                cfg.update({k: v for k, v in json.load(f).items() if v not in (None, "")})
        except Exception as exc:  # noqa: BLE001
            log("配置文件读取失败：%s" % exc)
    for env, key, cast in (
        ("JEV_API_KEY", "api_key", str),
        ("TYPESAFE_API_KEY", "api_key", str),
        ("JEV_ENDPOINT", "endpoint", str),
        ("JEV_MODEL", "model", str),
        ("JEV_PORT", "port", int),
        ("JEV_TIMEOUT", "timeout", float),
    ):
        if os.environ.get(env):
            try:
                cfg[key] = cast(os.environ[env])
            except ValueError:
                log("环境变量 %s 取值非法，已忽略" % env)
    cfg["endpoint"] = (cfg["endpoint"] or DEFAULT_ENDPOINT).rstrip("/")
    return cfg


CFG = load_config()


def log(msg):
    sys.stderr.write("[jev] %s\n" % msg)
    sys.stderr.flush()


# ---------------------------------------------------------------- 台面 → 情境描述

def bands_of(state):
    """把机械臂可及的 y 范围切成 7 个区间。"""
    you = state.get("you", {})
    half = float(you.get("paddle_half", 56))
    lo = float(state.get("table", {}).get("y_top", 96))
    hi = float(state.get("table", {}).get("y_bottom", 581))
    top, bot = lo + half, hi - half
    step = (bot - top) / NBANDS
    return [(top + i * step, top + (i + 1) * step) for i in range(NBANDS)]


def thirds_of(state):
    bs = bands_of(state)
    return {"top": (bs[0][0], bs[2][1]), "mid": (bs[2][0], bs[4][1]), "bottom": (bs[4][0], bs[6][1])}


def describe(state):
    """把数值状态写成 Jev 读得懂的一段话。关键是给出「还剩几秒」——
       实测这一句让命中率从 50% 提到 88%：它擅长一次乘法，不擅长多步推算。"""
    tb = state.get("table", {})
    b = state.get("ball", {})
    you = state.get("you", {})
    opp = state.get("opponent", {})
    half = float(you.get("paddle_half", 56))
    px = float(you.get("paddle_x", 900))
    r = float(b.get("r", 10))
    lo = float(tb.get("y_top", 96)) + r
    hi = float(tb.get("y_bottom", 581)) - r
    face = px - r
    vx = float(b.get("vx", 0))
    eta = (face - float(b.get("x", 0))) / vx if vx > 0 else None
    vy = float(b.get("vy", 0))
    speed = float(b.get("speed", 0))
    maxb = float(state.get("physics", {}).get("max_bounce_angle_rad", 0.92))

    lines = [
        "Table tennis, top-down view. The table runs from y=%d (top edge) to y=%d (bottom edge); "
        "y grows downward, so a larger y means lower on the table." % (tb.get("y_top", 96), tb.get("y_bottom", 581)),
        "The ball is at x=%.0f, y=%.0f. Its radius is %.0f px. It bounces off the top edge (y=%.0f) and the "
        "bottom edge (y=%.0f): when its center reaches that y, vy flips sign and it keeps going."
        % (b.get("x", 0), b.get("y", 0), r, lo, hi),
        "You are the RIGHT paddle. Your face is the vertical line x=%.0f, it is %.0f px tall (half-height %.0f), "
        "and its center may sit anywhere between y=%.0f and y=%.0f. You intercept the ball the moment the ball's "
        "center reaches x=%.0f. You hit the ball with whatever part of your face it touches: if it touches your "
        "center the ball goes straight back; if it touches %.0f px below your center the ball leaves at +%.2f rad "
        "(downward), and %.0f px above your center sends it upward instead. Your face moves at up to %.0f px/s."
        % (px, 2 * half, half, lo + half, hi - half, face, half * 0.45, 0.45 * maxb, half * 0.45,
           you.get("max_speed", 900)),
        "The opponent is the LEFT paddle; its center is currently at y=%.0f." % opp.get("paddle_center", 0),
    ]
    if eta is not None:
        lines.append("The ball is moving rightward at vx=%.0f px/s and vy=%.0f px/s (%s). It is %.0f px away from "
                     "your face, so it will reach you in about %.2f seconds."
                     % (vx, vy, "moving down" if vy > 0 else ("moving up" if vy < 0 else "level"),
                        face - float(b.get("x", 0)), eta))
    else:
        lines.append("The ball is currently moving away from you (vx=%.0f), so this is a positioning decision." % vx)
    lines.append("Ball speed for this rally is about %.0f px/s (it speeds up a little after every hit)." % speed)
    lines.append("Score: you %s, opponent %s. Rally length so far: %s hits. Your machine is at %s%% of its top "
                 "speed on this rally (long rallies make it overheat and slow down)."
                 % (state.get("score", {}).get("you", 0), state.get("score", {}).get("opponent", 0),
                    state.get("rally", 0), round(100 * float(you.get("machine_heat", 1)))))
    return "\n".join(lines)


# ===========================================================================
# pure 模式：只验证 Jev 的决策能力，零本地算法
#   1. 提示词里只有原始读数与台面规则，没有「还有几秒到」（那是本地替它解的物理题）
#   2. 它选的选项就是拍子要去的那个 y，不存在「问区间再取中点」这一步猜测
#   3. 不做 aim/power 换算：往哪打、打多重，由它选的位置经物理自然决定
#   4. 球速固定，不随它自己的延迟变化
# 本地只剩：查表（标签→它自己选的那个数）+ 伺服 + 物理。
# ===========================================================================

def placements_of(state):
    """它能选的拍心位置：就是真实可达的位置本身，不是需要再取中点的区间。"""
    you = state.get("you", {})
    half = float(you.get("paddle_half", 56))
    lo = float(state.get("table", {}).get("y_top", 96))
    hi = float(state.get("table", {}).get("y_bottom", 581))
    top, bot = lo + half, hi - half
    step = (bot - top) / NBANDS
    return [round(top + step * (i + 0.5), 1) for i in range(NBANDS)]


SERVE_CHOICES = [
    ("s0", "launch upward,    angle -0.27 rad (vy factor -0.55)", -0.55),
    ("s1", "launch level,     angle  0.00 rad (vy factor  0.00)", 0.0),
    ("s2", "launch downward,  angle +0.27 rad (vy factor +0.55)", 0.55),
]


def describe_pure(state):
    """只有原始读数与规则。没有任何推算——预测的活全部留给它。"""
    tb = state.get("table", {})
    b = state.get("ball", {})
    you = state.get("you", {})
    opp = state.get("opponent", {})
    half = float(you.get("paddle_half", 56))
    px = float(you.get("paddle_x", 900))
    r = float(b.get("r", 10))
    lo = float(tb.get("y_top", 96)) + r
    hi = float(tb.get("y_bottom", 581)) - r
    face = px - r
    vx = float(b.get("vx", 0))
    vy = float(b.get("vy", 0))
    maxb = float(state.get("physics", {}).get("max_bounce_angle_rad", 0.92))
    speed = float(b.get("speed", 0))
    speedup = float(state.get("physics", {}).get("speedup_per_hit", 1.10))
    lines = [
        "Table tennis, top-down view. The table runs from y=%d (top edge) to y=%d (bottom edge); "
        "y grows downward, so a larger y means lower on the table."
        % (tb.get("y_top", 96), tb.get("y_bottom", 581)),
        "The ball is at x=%.0f, y=%.0f, with velocity vx=%.0f px/s and vy=%.0f px/s. Its radius is %.0f px. "
        "It travels in a straight line at constant speed until something is hit; it never slows down on its own."
        % (b.get("x", 0), b.get("y", 0), vx, vy, r),
        "The ball bounces off the top edge (y=%.0f) and the bottom edge (y=%.0f): when its center reaches that y, "
        "vy flips sign and its y position mirrors back, exactly like a reflection. It can bounce any number of times."
        % (lo, hi),
        "You are the RIGHT paddle. Your face is the vertical line x=%.0f, it is %.0f px tall (half-height %.0f), and "
        "its center may sit anywhere between y=%.0f and y=%.0f. You intercept the ball the moment the ball's center "
        "reaches x=%.0f. You hit the ball with whatever part of your face it touches: touching your exact center "
        "sends it straight back, touching lower sends it upward, touching higher sends it downward, with the angle "
        "growing up to %.2f rad at the very edge. Your face moves at up to %.0f px/s."
        % (px, 2 * half, half, lo + half, hi - half, face, maxb, you.get("max_speed", 900)),
        "The opponent is the LEFT paddle; its center is currently at y=%.0f." % opp.get("paddle_center", 0),
        "The ball's current speed is %.0f px/s, and every hit multiplies the speed by %.3f, up to a maximum "
        "of %.0f px/s." % (speed, speedup, float(state.get("physics", {}).get("max_ball_speed", MAX_SPEED_CAP))),
        "Score: you %s, opponent %s. Rally length so far: %s hits. Your machine is at %s%% of its top speed "
        "on this rally (long rallies make it overheat and slow down)."
        % (state.get("score", {}).get("you", 0), state.get("score", {}).get("opponent", 0),
           state.get("rally", 0), round(100 * float(you.get("machine_heat", 1)))),
    ]
    return "\n".join(lines)


def build_questions_pure(state, serving=False):
    """一次决策一个问题。选项就是真实可执行的量，它选哪个就照做哪个。"""
    if serving:
        return {"serve": {
            "type": "choice",
            "instructions": ("You are serving: the ball starts on your face at x=%.0f and you launch it with "
                             "speed %.0f px/s. Choose the launch angle." % (float(state.get("you", {}).get(
                                 "paddle_x", 900)) - float(state.get("ball", {}).get("r", 10)),
                                 float(state.get("ball", {}).get("speed", 0)))),
            "criteria": {k: txt for k, txt, _ in SERVE_CHOICES},
        }}
    ps = placements_of(state)
    opts = {"p%d" % i: "paddle centre at y=%.1f" % y for i, y in enumerate(ps)}
    if state.get("kind") == "ready":
        # 球不朝它飞来时问的：你要站在哪里等下一板？
        return {"ready": {
            "type": "choice",
            "instructions": ("The ball is not coming toward you right now, and you do not know yet where the next "
                             "one will go. Where should the CENTRE of your paddle wait, so that you can still reach "
                             "either the top edge or the bottom edge in time? You can reach anywhere between y=%.1f "
                             "and y=%.1f."
                             % (float(state.get("table", {}).get("y_top", 96)) + float(state.get("you", {}).get("paddle_half", 56)),
                                float(state.get("table", {}).get("y_bottom", 581)) - float(state.get("you", {}).get("paddle_half", 56)))),
            "criteria": opts,
        }}
    return {"place": {
        "type": "choice",
        "instructions": ("The ball is coming toward your face at x=%.0f. Where should the CENTRE of your paddle be "
                         "when the ball arrives, so that the ball hits your face? Work out where the ball's centre "
                         "will be at x=%.0f, then pick the position closest to it. Your paddle will be exactly "
                         "there when the ball arrives."
                         % (float(state.get("you", {}).get("paddle_x", 900)) - float(state.get("ball", {}).get("r", 10)),
                            float(state.get("you", {}).get("paddle_x", 900)) - float(state.get("ball", {}).get("r", 10)))),
        "criteria": opts,
    }}


def decode_pure(answers, state, serving):
    """纯查表：它选的那个标签，直接对应一个真实可执行的数。没有算术。"""
    you = state.get("you", {})
    limit = float(you.get("max_speed", 900))
    if serving:
        a = answers.get("serve") or {}
        label = a.get("choice") or "s1"
        table = {k: v for k, _, v in SERVE_CHOICES}
        out = {"serve_vy": table.get(label, 0.0), "serve": label,
               "move_to": float(you.get("paddle_center", 0)) or _mid_paddle(state),
               "recover_to": float(you.get("paddle_center", 0)) or _mid_paddle(state),
               "speed": limit, "answers_seen": a}
        return out
    ps = placements_of(state)
    if state.get("kind") == "ready":
        a = answers.get("ready") or {}
        label = a.get("choice") or ""
        idx = len(ps) // 2
        if isinstance(label, str) and label.startswith("p"):
            try:
                idx = max(0, min(len(ps) - 1, int(label[1:])))
            except ValueError:
                idx = len(ps) // 2
        # 待命位只影响「等在哪」，不改变这一板要打的位置
        return {"kind": "ready", "ready": label or ("p%d" % idx), "recover_to": ps[idx],
                "move_to": float(you.get("paddle_center", 0)) or _mid_paddle(state),
                "speed": limit, "answers_seen": a}
    a = answers.get("place") or {}
    label = a.get("choice") or "p%d" % (len(ps) // 2)
    idx = len(ps) // 2
    if isinstance(label, str) and label.startswith("p"):
        try:
            idx = int(clamp(int(label[1:]), 0, len(ps) - 1))
        except ValueError:
            pass
    y = ps[idx]
    return {"move_to": y, "recover_to": y, "speed": limit, "place": "p%d" % idx,
            "place_y": y, "band_confidence": a.get("confidence"),
            "band_probabilities": a.get("probabilities") or {}, "answers_seen": a}


def _mid_paddle(state):
    you = state.get("you", {})
    half = float(you.get("paddle_half", 56))
    lo = float(state.get("table", {}).get("y_top", 96))
    hi = float(state.get("table", {}).get("y_bottom", 581))
    return (lo + hi) / 2.0


def build_questions(state, serving=False):
    """按模式分派：pure 只问一个问题，assisted 是原来为好玩调的那套。"""
    return build_questions_pure(state, serving) if MODE == "pure" else build_questions_assisted(state, serving)


def build_questions_assisted(state, serving=False):
    bs = bands_of(state)
    th = thirds_of(state)
    q = {}
    if serving:
        q["serve"] = {
            "type": "choice",
            "instructions": "You are serving (the ball starts on your face and you launch it). Which serve angle "
                            "gives you the best chance in this rally?",
            "criteria": {
                "flat": "Serve level, straight at the opponent",
                "rise": "Serve with a slight upward angle",
                "dip": "Serve with a slight downward angle",
            },
        }
        q["recover"] = {
            "type": "choice",
            "instructions": "After serving, where should your face wait for the opponent's return?",
            "criteria": {k: "y %.0f-%.0f" % v for k, v in th.items()},
        }
        q["taunt"] = {"type": "choice", "instructions": "Say something short to the opponent.",
                      "criteria": TAUNTS}
        return q

    q["band"] = {
        "type": "choice",
        "instructions": "When the ball's center reaches your face at x=%.0f, which y range will it be in? "
                        "Think it through, then pick one." % (float(state.get("you", {}).get("paddle_x", 900))
                                                             - float(state.get("ball", {}).get("r", 10))),
        "criteria": {"b%d" % i: "y %.0f-%.0f" % ab for i, ab in enumerate(bs)},
    }
    q["aim"] = {
        "type": "choice",
        "instructions": "Where do you want the ball to go after you hit it? Your face is %s px tall, so touching "
                        "the ball slightly below your center sends it downward."
                        % (2 * float(state.get("you", {}).get("paddle_half", 56))),
        "criteria": {
            "up": "Send it upward, toward the opponent's upper side",
            "flat": "Send it straight back",
            "down": "Send it downward, away from where the opponent stands",
        },
    }
    q["power"] = {
        "type": "noul",
        "instructions": "Should you hit this return harder than a normal steady return? (Faster is harder for the "
                        "opponent, but a harder ball is also harder for you to control.)",
    }
    # 注意：只问三个「决定这一板怎么打」的问题。实测每多问一个问题就多 ~0.3s 延迟，
    # 而延迟直接决定球速上限——Jev 迟到就接不到球，所以待命位/垃圾话不进这条关键路径。
    return q


# ---------------------------------------------------------------- Jev 调用
#
# 实测：真正慢的不是模型，是「每次决策都重新做一遍 TLS 握手」。
#   TCP 连本地代理只要几毫秒，TLS 握手却要 1.4~2.4s，而模型本身只花 ~0.35s。
#   新建连接中位 2100ms vs 复用连接稳态 342ms —— 差 6 倍。
# 所以这里维持一条 keep-alive 长连接；连接被对端关掉就自动重连一次。
# 一条 keep-alive 连接一次只能跑一个请求。一个人玩没问题，
# 但多人同时玩就会在锁上排队（每个人的决策要等前一个人的往返）。
# 所以开一个小池子：每个槽位各自持有一条连接，互相不挡。
POOL_SIZE = 4
_slots = [{"c": None, "sig": "", "lock": threading.Lock()} for _ in range(POOL_SIZE)]
_slot_q = queue.Queue()
for _s in _slots:
    _slot_q.put(_s)
LAST_CALL_TIMING = {}     # 最近一次调用（给脚本看）；并发时以线程局部为准
_tl = threading.local()   # 每个请求线程各自一份计时，多人同时玩不会互相覆盖
# 第一趟只等这么久：超过它基本就是「连接被隧道悄悄掐了」，换新连接立刻就好。
# 实测正常一次决策中位 0.35s、p90 0.66s，所以 1.2s 远在正常范围之外。
STALE_TIMEOUT_S = 1.2
LONG_TIMEOUT_S = 9.0      # 换过连接后再等这么久，因为这时可能是 API 自己慢


def _endpoint_parts():
    from urllib.parse import urlsplit
    u = urlsplit(CFG["endpoint"])
    scheme = u.scheme or "https"
    host = u.hostname or "api.typesafe.ai"
    port = u.port or (443 if scheme == "https" else 80)
    path = (u.path or "/v1/systemone") + (("?" + u.query) if u.query else "")
    return scheme, host, port, path


def _new_conn():
    scheme, host, port, _path = _endpoint_parts()
    if scheme == "https":
        return http.client.HTTPSConnection(host, port, timeout=CFG["timeout"])
    return http.client.HTTPConnection(host, port, timeout=CFG["timeout"])


def call_jev(state_text, questions):
    if not CFG["api_key"]:
        raise RuntimeError("未配置 JEV_API_KEY（环境变量或 jev.config.json）")
    scheme, host, port, path = _endpoint_parts()
    payload = json.dumps({"model": CFG["model"], "state": state_text,
                          "questions": questions}).encode("utf-8")
    headers = {"Content-Type": "application/json",
               "Authorization": "Bearer " + CFG["api_key"],
               "Connection": "keep-alive"}
    sig = "%s://%s:%s" % (scheme, host, port)
    last = None
    slot = _slot_q.get()                  # 借一个槽位（各自一条连接，互不阻塞）
    conn = slot
    try:
        for attempt in (0, 1, 2):
            connect_ms = 0.0
            if slot["c"] is None or slot["sig"] != sig:
                _t_conn = time.perf_counter()
                slot["c"] = _new_conn()
                try:
                    slot["c"].connect()           # 真正建连（HTTPSConnection 是懒连接的）
                except Exception:
                    pass
                slot["sig"] = sig
                connect_ms = (time.perf_counter() - _t_conn) * 1000.0
            # 第一趟只等 STALE_TIMEOUT_S：正常一次决策中位 ~0.35s，远超这个数的
            # 基本都是「keep-alive 连接被隧道悄悄掐了」——实测这种情况换条新连接
            # 立刻就能 341ms 回来（看门狗抓到的：傻等会拖 4.1s、5.2s、甚至 12s）。
            # 注意改的是 socket 的读超时：HTTPConnection.timeout 只在建 socket 那刻生效，
            # 而建连（含 TLS 握手，实测 0.8~1s）必须继续用宽松的超时。
            try:
                if slot["c"].sock is not None:
                    slot["c"].sock.settimeout(STALE_TIMEOUT_S if attempt == 0 else LONG_TIMEOUT_S)
            except Exception:
                pass
            _t_call = time.perf_counter()
            try:
                slot["c"].request("POST", path, body=payload, headers=headers)
                resp = slot["c"].getresponse()
                raw = resp.read()
                _timing = {
                    "connect_ms": round(connect_ms),
                    "model_ms": round((time.perf_counter() - _t_call) * 1000.0),
                    "reconnected": connect_ms > 0,
                    "attempt": attempt,
                    "retried": attempt > 0,
                }
                _tl.timing = _timing
                LAST_CALL_TIMING.clear()
                LAST_CALL_TIMING.update(_timing)   # 供脚本读取，best-effort
                if resp.status != 200:
                    raise urllib.error.HTTPError(CFG["endpoint"], resp.status,
                                                 raw.decode("utf-8", "replace")[:300], resp.headers, None)
                body = json.loads(raw.decode("utf-8"))
                return body.get("answers") or {}, body.get("usage") or {}, body.get("model") or CFG["model"]
            except urllib.error.HTTPError:
                raise                     # 真·业务错误（400/401/429），不重试
            except Exception as exc:      # 连接被对端关掉 / 超时 → 关掉重连再来
                last = exc
                try:
                    slot["c"].close()
                except Exception:         # noqa: BLE001
                    pass
                slot["c"] = None
                if attempt == 2:
                    raise
    finally:
        _slot_q.put(slot)                 # 还回去，别人接着用
    raise last if last else RuntimeError("call_jev 失败")


def mock_answers(state, serving):
    """测试替身：只负责产出「一份假的 Jev 答案」，后面走完全相同的解码路径。"""
    bs = bands_of(state)
    b = state["ball"]
    you = state["you"]
    lo = float(state["table"]["y_top"]) + float(b["r"])
    hi = float(state["table"]["y_bottom"]) - float(b["r"])
    span = hi - lo
    t = (float(you["paddle_x"]) - float(b["r"]) - float(b["x"])) / b["vx"] if b["vx"] > 0 else 0
    y = float(b["y"]) + float(b["vy"]) * t
    tt = (y - lo) % (2 * span)
    y = lo + tt if tt <= span else lo + (2 * span - tt)
    band = next((i for i, (a, c) in enumerate(bs) if a <= y < c), 3)
    probs = {("b%d" % i): (0.72 if i == band else round(0.28 / (NBANDS - 1), 3)) for i in range(NBANDS)}
    if MODE == "pure":
        if serving:
            return {"serve": {"type": "choice", "choice": "s2", "confidence": 0.6,
                              "probabilities": {"s0": 0.2, "s1": 0.2, "s2": 0.6}}}, \
                   {"input_tokens": 0, "output_tokens": 0}, "mock-brain"
        ps = placements_of(state)
        best = min(range(len(ps)), key=lambda i: abs(ps[i] - y))
        pp = {("p%d" % i): (0.72 if i == best else round(0.28 / (len(ps) - 1), 3)) for i in range(len(ps))}
        return {"place": {"type": "choice", "choice": "p%d" % best, "confidence": 0.72, "probabilities": pp}}, \
               {"input_tokens": 0, "output_tokens": 0}, "mock-brain"
    if serving:
        return {"serve": {"type": "choice", "choice": "dip", "confidence": 0.6,
                          "probabilities": {"flat": 0.2, "rise": 0.2, "dip": 0.6}},
                "recover": {"type": "choice", "choice": "mid", "confidence": 0.8,
                            "probabilities": {"top": 0.1, "mid": 0.8, "bottom": 0.1}},
                "taunt": {"type": "choice", "choice": "t1", "confidence": 0.5,
                          "probabilities": {k: round(1 / len(TAUNTS), 3) for k in TAUNTS}}}, \
               {"input_tokens": 0, "output_tokens": 0}, "mock-brain"
    return {"band": {"type": "choice", "choice": "b%d" % band, "confidence": 0.72, "probabilities": probs},
            "aim": {"type": "choice", "choice": "down" if state["opponent"]["paddle_center"] < (lo + hi) / 2 else "up",
                    "confidence": 0.55, "probabilities": {"up": 0.3, "flat": 0.15, "down": 0.55}},
            "power": {"type": "noul", "noul": 0.4},
            "recover": {"type": "choice", "choice": "mid", "confidence": 0.7,
                        "probabilities": {"top": 0.15, "mid": 0.7, "bottom": 0.15}},
            "taunt": {"type": "choice", "choice": "t3", "confidence": 0.4,
                      "probabilities": {k: round(1 / len(TAUNTS), 3) for k in TAUNTS}}}, \
           {"input_tokens": 0, "output_tokens": 0}, "mock-brain"


# ---------------------------------------------------------------- 答案 → 机械臂指令

def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def remember(out, state, serving, t_wall, model, in_tok, out_tok, text, questions, answers, peer=""):
    """把这次决策的完整过程存进服务端历史（供 /jev/log 回看，刷新页面也不丢）。"""
    HISTORY_SEQ[0] += 1
    HISTORY.append({
        "id": HISTORY_SEQ[0],
        "ts": round(t_wall, 3),
        "clock": time.strftime("%H:%M:%S", time.localtime(t_wall)),
        "kind": out.get("kind") or ("serve" if serving else "incoming"),
        "peer": peer,
        "rally": state.get("rally"),
        "score": state.get("score"),
        "model": model,
        "latency_ms": out.get("latency_ms"),
        "connect_ms": out.get("connect_ms", 0),
        "retried": out.get("retried", False),
        "model_ms": out.get("model_ms"),
        "input_tokens": in_tok,
        "output_tokens": out_tok,
        "cost_usd": out.get("cost_usd"),
        "prompt_chars": len(text),
        "question_count": len(questions),
        "command": {
            "move_to": out.get("move_to"),
            "speed": out.get("speed"),
            "recover_to": out.get("recover_to"),
            "serve_vy": out.get("serve_vy"),
            "note": out.get("note"),
        },
        "decision": {
            "band": out.get("band"),
            "band_center": out.get("band_center"),
            "band_confidence": out.get("band_confidence"),
            "band_probabilities": out.get("band_probabilities"),
            "aim": out.get("aim"),
            "power": out.get("power"),
        },
        "ball": {k: state.get("ball", {}).get(k) for k in ("x", "y", "vx", "vy", "speed")},
        "state_text": text,
        "questions": questions,
        "answers": answers,
    })


def decode(answers, state, serving):
    """按模式分派。"""
    return decode_pure(answers, state, serving) if MODE == "pure" else decode_assisted(answers, state, serving)


def decode_assisted(answers, state, serving):
    """只做「标签 → 像素」的换算。挑哪个标签完全是 Jev 的决定。"""
    you = state.get("you", {})
    half = float(you.get("paddle_half", 56))
    limit = float(you.get("max_speed", 900))
    bs = bands_of(state)
    th = thirds_of(state)
    out = {}

    def pick(name, default):
        a = answers.get(name) or {}
        return a.get("choice") or default, a

    def band_center(band_id, default_idx):
        try:
            i = int(str(band_id).lstrip("b"))
        except (TypeError, ValueError):
            i = default_idx
        i = int(clamp(i, 0, len(bs) - 1))
        a, b = bs[i]
        return (a + b) / 2, i

    if serving:
        ang, _ = pick("serve", "flat")
        out["serve_vy"] = {"flat": 0.0, "rise": -0.55, "dip": 0.55}.get(ang, 0.0)
        rec, _ = pick("recover", "mid")
        a, b = th.get(rec, th["mid"])
        out["recover_to"] = (a + b) / 2
        out["move_to"] = out["recover_to"]
        out["speed"] = limit
    else:
        band_id, band_ans = pick("band", "b3")
        center, idx = band_center(band_id, 3)
        aim, _ = pick("aim", "flat")
        rel = {"up": -0.45, "flat": 0.0, "down": 0.45}.get(aim, 0.0)
        # 偏移让球打向指定方向：拍心要往球的到达点反方向让开 rel*half
        out["move_to"] = center - rel * half
        out["recover_to"] = out["move_to"]
        pw = answers.get("power") or {}
        p = pw.get("noul")
        if p is None:
            p = pw.get("probability")
        try:
            p = float(p)
        except (TypeError, ValueError):
            p = 0.5
        out["speed"] = limit * (0.45 + 0.55 * clamp(p, 0.0, 1.0))
        out["band"] = "b%d" % idx
        out["band_center"] = round(center, 1)
        out["band_confidence"] = band_ans.get("confidence")
        out["band_probabilities"] = band_ans.get("probabilities") or {}
        out["aim"] = aim
        out["power"] = round(clamp(p, 0.0, 1.0), 3)

    rec2, _ = pick("recover", "mid") if not serving else (None, None)
    if rec2 and not serving:
        # 回球时没多余预算问待命位，就按它自己选的落点待命（区间中心已经在 out["move_to"] 里）
        out["recover_to"] = out["move_to"]
    taunt, _ = pick("taunt", "t3")
    out["note"] = TAUNTS.get(taunt, "")

    # 夹到机械臂物理范围
    lo_c = float(state["table"]["y_top"]) + half
    hi_c = float(state["table"]["y_bottom"]) - half
    out["move_to"] = clamp(float(out["move_to"]), lo_c, hi_c)
    out["recover_to"] = clamp(float(out["recover_to"]), lo_c, hi_c)
    out["speed"] = clamp(float(out["speed"]), 0.0, limit)
    out["serve_vy"] = clamp(float(out.get("serve_vy", 0.0)), -1.0, 1.0)
    return out


# ---------------------------------------------------------------- HTTP


class Handler(BaseHTTPRequestHandler):
    server_version = "JevBrain/2.0"

    def log_message(self, fmt, *args):
        pass

    def _origin_ok(self):
        origin = self.headers.get("Origin")
        if origin is None or origin == "null":
            return True
        host = self.headers.get("Host") or ""
        if origin in ("http://" + host, "https://" + host):
            return True
        return origin.startswith(("http://127.0.0.1", "http://localhost", "https://127.0.0.1", "https://localhost"))

    def _send(self, code, body, ctype="application/json; charset=utf-8", cors=True):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        if cors:
            self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin") or "*")
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        if not self._origin_ok():
            self._send(403, {"ok": False, "error": "origin not allowed"}, cors=False)
            return
        self._send(204, b"")

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/jev/health":
            if not self._origin_ok():
                self._send(403, {"ok": False, "error": "origin not allowed"}, cors=False)
                return
            self._send(200, {
                "ok": bool(CFG["api_key"]) or MOCK,
                "model": "mock-brain" if MOCK else CFG["model"],
                "endpoint": CFG["endpoint"],
                "mock": MOCK,
                "mode": MODE,
                "pure_speed_cap_px_s": pure_speed_cap(),
                "configured": bool(CFG["api_key"]),
                "price_per_input_token_usd": PRICE_PER_INPUT_TOKEN_USD,
            })
            return
        if path == "/jev/log":
            if not self._origin_ok():
                self._send(403, {"ok": False, "error": "origin not allowed"}, cors=False)
                return
            q = self.path.split("?", 1)[1] if "?" in self.path else ""
            n = 60
            for part in q.split("&"):
                if part.startswith("n="):
                    try:
                        n = int(part[2:])
                    except ValueError:
                        pass
            n = max(1, min(400, n))
            recs = list(HISTORY)[-n:]
            self._send(200, {"ok": True, "count": len(HISTORY), "records": recs})
            return
        if path in ("/", "/index.html"):
            self._serve_file("index.html", "text/html; charset=utf-8")
            return
        self._serve_file(path.lstrip("/"), None)

    def do_POST(self):
        path = self.path.split("?")[0]
        if path != "/jev/decide":
            self._send(404, {"ok": False, "error": "未知接口 " + path})
            return
        if not self._origin_ok():
            log("拒绝来自 %s 的跨站调用" % self.headers.get("Origin"))
            self._send(403, {"ok": False, "error": "origin not allowed"}, cors=False)
            return
        try:
            n = int(self.headers.get("Content-Length") or 0)
            state = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
        except Exception as exc:  # noqa: BLE001
            self._send(400, {"ok": False, "error": "请求体不是合法 JSON：%s" % exc})
            return

        serving = state.get("kind") == "serve"
        t0 = time.time()
        t_wall = time.time()
        try:
            text = describe(state) if MODE == "assisted" else describe_pure(state)
            questions = build_questions(state, serving)
            if MOCK:
                answers, usage, model = mock_answers(state, serving)
            else:
                answers, usage, model = call_jev(text, questions)
            out = decode(answers, state, serving)
            in_tok = int(usage.get("input_tokens") or 0)
            out_tok = int(usage.get("output_tokens") or 0)
            timing = dict(getattr(_tl, "timing", None) or {})
            out.update({
                "ok": True,
                "model": model,
                "latency_ms": int((time.time() - t0) * 1000),
                "connect_ms": timing.get("connect_ms", 0),
                "retried": timing.get("retried", False),
                "model_ms": timing.get("model_ms"),
                "usage": {"input_tokens": in_tok, "output_tokens": out_tok},
                "cost_usd": round(in_tok * PRICE_PER_INPUT_TOKEN_USD, 8),
                # 完整过程：它看到了什么、被问了什么、每个问题给出的分布是什么
                "trace": {
                    "state_text": text,
                    "questions": questions,
                    "answers": answers,
                    "prompt_chars": len(text),
                    "question_count": len(questions),
                },
            })
            log("%s → move_to=%.0f%s (共 %.0fms = 建连 %.0f + 模型 %.0f%s%s, %d tok)" % (
                out.get("kind", "incoming"), out["move_to"],
                (" ready=" + str(out.get("ready"))) if out.get("ready") else "",
                out["latency_ms"], out.get("connect_ms") or 0, out.get("model_ms") or 0,
                " ← 重连" if (out.get("connect_ms") or 0) > 0 else "",
                " ← 陈旧连接，已换新连接重试" if out.get("retried") else "", in_tok))
            remember(out, state, serving, t_wall, model, in_tok, out_tok, text, questions, answers,
                     self.client_address[0] if self.client_address else "")
            self._send(200, out)
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8")[:300]
            except Exception:  # noqa: BLE001
                pass
            log("Jev HTTP %s：%s" % (exc.code, detail))
            self._send(200, {"ok": False, "error": "Jev HTTP %s：%s" % (exc.code, detail),
                             "latency_ms": int((time.time() - t0) * 1000)})
        except Exception as exc:  # noqa: BLE001
            log("Jev 调用失败：%s" % exc)
            self._send(200, {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc),
                             "latency_ms": int((time.time() - t0) * 1000)})

    def _serve_file(self, rel, ctype):
        safe = os.path.normpath(os.path.join(HERE, rel))
        inside = (safe == HERE) or safe.startswith(HERE + os.sep)
        name = os.path.basename(safe)
        ext = os.path.splitext(safe)[1].lower()
        if (not inside) or name.startswith(".") or name in SERVE_DENY or ext not in SERVE_EXT \
                or not os.path.isfile(safe):
            if rel.startswith("diag/"):     # 页面诊断信标（开发用）：把状态写进服务端日志
                log("页面诊断：" + rel[5:][:400])
            self._send(404, {"ok": False, "error": "not found"}, cors=False)
            return
        if ctype is None:
            ctype = mimetypes.guess_type(safe)[0] or "application/octet-stream"
        with open(safe, "rb") as f:
            body = f.read()
        self._send(200, body, ctype, cors=False)


def lan_ip():
    """本机的局域网地址（给别人用的那个）。"""
    import socket as _s
    try:
        _t = _s.socket(_s.AF_INET, _s.SOCK_DGRAM)
        _t.connect(("10.255.255.255", 1))      # 不真的发包，只为让内核挑出出口网卡
        ip = _t.getsockname()[0]
        _t.close()
        return ip
    except Exception:
        return "本机局域网IP"


def main():
    port = CFG["port"]
    print("=" * 66)
    print(" JEV 大脑中继（TypeSafe SystemOne）  http://127.0.0.1:%d" % port)
    if MODE == "pure":
        print(" 模式：pure —— 纯驱动，零本地算法（不给到达时间/不取区间中点/无 aim·power 换算）")
        print("         一次决策只问一个问题，它选的选项就是拍子要去的那个 y；本地只查表 + 伺服")
        _t = tempo_report(pure_speed_cap())
        print(" 球速上限：%.0f px/s（固定常数，不随实测延迟变化；--cap N 可改）" % _t["cap"])
        print("         单程飞行 %.2fs · 预期可决策 %d 次 · 最后一次留 %.2fs 余量 → %s"
              % (_t["flight_s"], _t["decisions"], _t["room_s"],
                 "来得及" if _t["ok"] else "来不及（调低 --cap）"))
        print("         一板球从上限的 %d%% 起步，每被击一次 ×%.3f 逐渐加速到上限"
              % (70, 1.10))
    else:
        print(" 模式：assisted —— 带本地辅助（本地替它算到达时间 + 区间取中点 + aim/power 换算）")
        print("         这是为了好玩调过的版本，用来当对照")
    if MOCK:
        print(" 另：--mock-brain（测试替身，不调用模型）")
    else:
        print(" endpoint : %s" % CFG["endpoint"])
        print(" model    : %s" % CFG["model"])
        print(" api_key  : %s" % ("已配置（%d 字符）" % len(CFG["api_key"]) if CFG["api_key"] else "（未配置！）"))
    print(" 本机打开：http://127.0.0.1:%d/" % port)
    if HOST == "0.0.0.0":
        print(" 局域网里别人打开：http://%s:%d/   ← 同一个房间的人都能一起玩" % (lan_ip(), port))
        print(" 注意：JEV 的 API key 只在这个进程里，页面里没有任何凭据；")
        print("       但局域网里谁能打开这个地址，谁就能花你的 token。只想自己玩就 --host 127.0.0.1")
    else:
        print(" 只绑在 %s（局域网里别人访问不到；要开放就 --host 0.0.0.0）" % HOST)
    print("=" * 66)
    ThreadingHTTPServer((HOST, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
