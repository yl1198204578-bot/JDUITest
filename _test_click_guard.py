# -*- coding: utf-8 -*-
"""针对本次健壮性修复的回归用例：点击【去浏览】未生效时不得等待 + back。

复现场景（Web 实跑第 4 轮）：adb input tap 超时 -> 点击没注入 -> 旧代码
仍按「已进入浏览页」停 16 秒并 back，把任务弹窗关掉，导致后续无法收敛。
修复后应重试一次点击，仍不生效就跳过该任务，back 调用次数必须为 0。
"""
import sys
import threading
import unittest.mock as mock

sys.stdout.reconfigure(encoding="utf-8")

import modules.task1_seckill as t1

LINES = []


class Log(object):
    def write_log(self, m, level="INFO"):
        LINES.append("[%s] %s" % (level, m))

    def done(self, m="完成"):
        LINES.append("[DONE] " + m)

    def error(self, m="出错"):
        LINES.append("[ERROR] " + m)


class GuardUI(object):
    """永远停在弹窗，模拟【去浏览】点击没被注入。"""

    def __init__(self):
        self.taps = 0
        self.back_calls = 0
        self.swipes = 0

    def open_task_dialog(self):
        return True

    def ensure_task_dialog(self):
        return True

    def browse_buttons(self):
        return [{"bounds": (819, 1408, 1025, 1493)}]

    def nodes(self):
        return []

    def task_key(self, btn, ns):
        return "task-1"

    def swipe(self, *a, **kw):
        self.swipes += 1

    def center(self, n):
        return (0, 0)

    def tap(self, *a, **kw):
        self.taps += 1

    def page_state(self):
        return "dialog"

    def back(self, *a, **kw):
        self.back_calls += 1

    def snapshot(self, *a, **kw):
        return None


ui = GuardUI()
log = Log()
with mock.patch.object(t1, "BROWSE_SECONDS", 0):
    done = t1.Task1Seckill()._browse_round(ui, log, threading.Event())

print("=== D 点击不生效守卫 ===", flush=True)
for l in LINES:
    print("  " + l, flush=True)
print("  >> taps=%d back=%d swipes=%d done=%d" %
      (ui.taps, ui.back_calls, ui.swipes, done), flush=True)

assert done == 0, "不该把未生效的任务计入完成数"
assert ui.taps == 2, "应重试一次点击（共 2 次）"
assert ui.back_calls == 0, "点击未生效时绝不能 back，否则会关掉任务弹窗"
assert not any("停留" in l for l in LINES), "不该进入 16 秒等待"
assert any("跳过该任务" in l for l in LINES), "应明确记录跳过"
print("\n=== 用例 D 通过 ===", flush=True)

with open("_test_click_guard_result.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(LINES + [
        ">> taps=%d back=%d swipes=%d done=%d" %
        (ui.taps, ui.back_calls, ui.swipes, done),
        "=== 用例 D 通过 ===",
    ]))
