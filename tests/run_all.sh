#!/usr/bin/env bash
# 跑全套测试。全部离线：模型调用一律被桩替换，不会花 token、不碰网络。
#
#   ./tests/run_all.sh
#
# 需要 JavaScriptCore（macOS 自带，用来跑没有 node 的纯 JS 测试）。
set -u
cd "$(dirname "$0")/.."

JSC="/System/Library/Frameworks/JavaScriptCore.framework/Versions/A/Helpers/jsc"
if [ ! -x "$JSC" ]; then
  JSC="$(command -v jsc 2>/dev/null || true)"
fi
if [ -z "${JSC:-}" ] || [ ! -x "$JSC" ]; then
  echo "找不到 jsc（JavaScriptCore）。装了 node 的话，把下面的 \$JSC 换成 node 也可以。"
  exit 1
fi

python3 tests/make_probe.py >/dev/null || exit 1
python3 - <<'PY'
import re
src = open('index.html', encoding='utf-8').read()
body = re.search(r'<script>(.*)</script>', src, re.S).group(1)
open('tests/.build_plain.js', 'w', encoding='utf-8').write(body)
PY

fails=0
run() {                       # run <显示名> <命令...>
  local name="$1"; shift
  local out
  out="$("$@" 2>&1 | tail -1)"
  if echo "$out" | grep -qiE "ALL PASS|SYNTAX OK"; then
    printf '  \033[32m✓\033[0m %-22s %s\n' "$name" "$out"
  else
    printf '  \033[31m✗\033[0m %-22s %s\n' "$name" "$out"; fails=$((fails+1))
  fi
}
echo "跑全套测试（全部离线，不花 token）："
run "语法"       "$JSC" tests/check2.js
run "界面"       "$JSC" tests/jev_ui_test.js
run "决策日志"   "$JSC" tests/jev_log_test.js
run "球速爬坡"   "$JSC" tests/jev_speed_test.js
run "闭环多判"   "$JSC" tests/jev_multiround.js
run "待命位"     "$JSC" tests/jev_ready_test.js
run "超时≠掉线"  "$JSC" tests/jev_timeout_test.js
run "归因审计"   "$JSC" tests/jev_attribution.js
run "纯模式"     python3 tests/jev_pure_test.py
run "陈旧连接"   python3 tests/jev_stale_test.py

echo
if [ "$fails" -eq 0 ]; then echo "全部通过。"; else echo "$fails 项未通过。"; fi
exit "$fails"
