#!/usr/bin/env python3
"""本地 System One（laya-mlx）后端：接线对不对。

不测「模型答得好不好」——那是评测仪的事，不是单元测试的事。
这里只保证：开关解析正确、缺环境时给得出人话、接上以后返回的形状能被 decode_pure 吃下。
"""
import importlib.util
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
VENV = os.path.join(ROOT, ".venv-laya", "bin", "python")
FAILS = []


def check(name, cond, extra=""):
    print(("PASS  " if cond else "FAIL  ") + name + (("   [" + extra + "]") if extra else ""))
    if not cond:
        FAILS.append(name)


def load_server():
    spec = importlib.util.spec_from_file_location("jevserver", os.path.join(ROOT, "server.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# 1) 开关解析：--brain / --port / --cap / --laya-model
probe = (
    "import sys, importlib.util;"
    "sys.argv = ['server.py','--brain','laya','--port','8761','--cap','700',"
    "'--laya-model','some/model'];"
    "spec = importlib.util.spec_from_file_location('m', r'%s');"
    "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m);"
    "print(m.BRAIN, m.PORT_OVERRIDE, m.CAP_OVERRIDE, m.LAYA_MODEL)" % os.path.join(ROOT, "server.py")
)
out = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, cwd=ROOT).stdout.strip()
check("--brain laya --port 8761 --cap 700 --laya-model 都解析对了",
      out == "laya 8761 700.0 some/model", "解析结果：" + out)

# 2) 默认还是云端：不显式指定时不许偷偷换大脑
check("默认大脑仍是云端 JEV（不显式指定就不会变）", load_server().BRAIN == "jev",
      "默认 brain = " + load_server().BRAIN)

# 3) 缺环境时报错要说人话（这里用的是系统 python，本来就没装 laya_mlx）
srv = load_server()
try:
    srv.call_laya("state", {"q": {"type": "choice", "instructions": "x", "criteria": ["a"]}})
    check("缺 laya-mlx 时抛出可读的错误", False, "居然没抛错")
except RuntimeError as exc:
    msg = str(exc)
    check("缺 laya-mlx 时给出安装指引（而不是一句 ImportError）",
          "venv-laya" in msg and "brain laya" in msg, msg.splitlines()[0][:60])
except Exception as exc:  # noqa: BLE001
    check("缺 laya-mlx 时抛出可读的错误", False, "抛的是 " + type(exc).__name__)

# 4) 真跑一次（有 venv 才跑）：返回的标签必须落在选项里，且形状能被 decode_pure 吃下
if os.path.exists(VENV):
    run = subprocess.run([VENV, "-c", """
import json, time, importlib.util
spec = importlib.util.spec_from_file_location("s", r"%(root)s/server.py")
S = importlib.util.module_from_spec(spec); spec.loader.exec_module(S)
S.BRAIN = "laya"; S.LAYA_MODEL = "aac6fef/laya-typed-decisions-mlx"
st = json.load(open(r"%(root)s/sample_state.json"))
st["kind"] = "incoming"; st["you"]["paddle_half"] = 56.0
st.setdefault("physics", {}).update({"max_bounce_angle_rad": 0.55})
txt = S.describe_pure(st); qs = S.build_questions_pure(st, False)
t0 = time.time(); ans, usage, model = S.call_laya(txt, qs); cold = (time.time() - t0) * 1000
t0 = time.time(); ans, usage, model = S.call_laya(txt, qs); dt = (time.time() - t0) * 1000
out = S.decode_pure(ans, st, False)
crit = qs["place"]["criteria"]
ok_label = (ans.get("place") or {}).get("choice") in crit
ok_move = abs(out["move_to"] - float(crit[(ans.get("place") or {}).get("choice")].split("y=")[1])) < 1e-6
print(json.dumps({"label_ok": ok_label, "move_ok": ok_move, "ms": dt, "cold_ms": cold,
                  "tok": (usage or {}).get("input_tokens"), "model": model, "move": out["move_to"]}))
""" % {"root": ROOT}], capture_output=True, text=True, timeout=900)
    try:
        r = json.loads(run.stdout.strip().splitlines()[-1])
    except Exception:  # noqa: BLE001
        r = None
    check("本地模型能从 venv 里跑起来", r is not None, (run.stderr or run.stdout)[-160:] if r is None else "")
    if r:
        check("它选的标签是 7 个选项之一", r["label_ok"], "模型 " + str(r["model"]))
        check("它的答案走的是同一条解码路径（标签→像素值，本地不换算）",
              r["move_ok"], "move_to=%.1f" % r["move"])
        # 冷启动含 0.9s 加载 + 首问预热，不算稳态；要比就比第二次
        check("稳态一次决策 < 500ms（云端实测中位 ~350ms）",
              r["ms"] < 500, "稳态 %.0fms · 冷启动 %.0fms · %s tok" % (r["ms"], r["cold_ms"], r["tok"]))
else:
    print("SKIP  没找到 .venv-laya，跳过真跑那一项")
    print("      （要跑：/opt/homebrew/bin/python3.13 -m venv .venv-laya && ./.venv-laya/bin/pip install laya-mlx）")

print("")
print("LOCAL BRAIN: ALL PASS" if not FAILS else "%d CHECK(S) FAILED" % len(FAILS))
sys.exit(1 if FAILS else 0)
