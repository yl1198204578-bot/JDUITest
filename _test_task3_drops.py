# -*- coding: utf-8 -*-
"""任务3【东东农场-领水滴】离线回归：不连手机。

用例（基于真机采集的 XML）：
  A 完全渲染的农场页：能找到【领水滴】按钮(expo_task_icon)
  B 未完全渲染的农场页：找不到领水滴按钮（bounds 无效/displayed=false）
  C 弹窗已打开：_is_drops_dialog 返回 True
  D 弹窗中找浏览任务：「浏览6秒」+「去完成」/「逛一逛」能配对
  E 弹窗中找去领奖按钮：能找到
  F dialog5.xml（9个去完成，2个去领奖）：所有查找正常
  G 农场页不是弹窗：_is_drops_dialog 返回 False
  H 按钮都是 clickable=false 的 TextView：不过滤 clickable
"""
import io
import os
import sys
import types
import xml.etree.ElementTree as ET

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Mock driver to avoid appium dependency
mock_driver = types.ModuleType("utils.driver")
mock_driver.get_driver = lambda: None
sys.modules["utils.driver"] = mock_driver

from modules.task3_farm_drops import Task3FarmDrops, BROWSE_BUTTON_TEXTS

PASSED = []
FAILED = []
ROOT = os.path.dirname(os.path.abspath(__file__))


def check(name, cond, detail=""):
    if cond:
        PASSED.append(name)
        print("PASS %s %s" % (name, detail))
    else:
        FAILED.append(name)
        print("FAIL %s %s" % (name, detail))


class FakeUI:
    """模拟 FarmUI 最小接口，读取静态 XML 文件。"""
    W = 1080
    H = 2340
    stop = None

    def __init__(self, xml_file):
        with open(xml_file, "r", encoding="utf-8") as f:
            self._xml = f.read()

    def source(self, fresh=False):
        return self._xml

    def invalidate(self):
        pass

    @staticmethod
    def parse_bounds(raw):
        import re
        m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", raw or "")
        if not m:
            return None
        x1, y1, x2, y2 = [int(v) for v in m.groups()]
        if x2 <= x1 or y2 <= y1:
            return None
        return (x1, y1, x2, y2)

    @staticmethod
    def center(node):
        x1, y1, x2, y2 = node["bounds"]
        return ((x1 + x2) // 2, (y1 + y2) // 2)


mod = Task3FarmDrops()

# ---------- A: 完全渲染农场页 - 找领水滴按钮 ----------
print("=== A: 完全渲染农场页 ===")
ui = FakeUI(os.path.join(ROOT, "_farm_farm_home2.xml"))
btn = mod._find_drops_button(ui)
check("A 找到领水滴按钮", btn is not None)
if btn:
    check("A text 含'领水滴'", "领水滴" in btn["text"], repr(btn["text"]))
    check("A clickable=true", btn["clickable"])
    check("A class=Button", btn["class"] == "Button")
    b = btn["bounds"]
    check("A bounds 合理", 300 < b[0] < 700 and 1400 < b[1] < 1800, str(b))

# ---------- B: 未完全渲染农场页 ----------
print("=== B: 未完全渲染农场页 ===")
ui = FakeUI(os.path.join(ROOT, "_drops", "01_farm_home.xml"))
btn = mod._find_drops_button(ui)
check("B 找不到按钮(未渲染)", btn is None)

# ---------- C: 弹窗已打开 ----------
print("=== C: 弹窗已打开 ===")
ui = FakeUI(os.path.join(ROOT, "_drops", "dialog.xml"))
check("C _is_drops_dialog=True", mod._is_drops_dialog(ui))

# ---------- D: 弹窗中找浏览任务 ----------
print("=== D: 弹窗中找浏览任务 ===")
ui = FakeUI(os.path.join(ROOT, "_drops", "dialog.xml"))
task_btn = mod._find_next_browse_task(ui)
check("D 找到浏览任务", task_btn is not None)
if task_btn:
    check("D btn_text 正确", task_btn["btn_text"] in BROWSE_BUTTON_TEXTS,
          repr(task_btn["btn_text"]))
    b = task_btn["bounds"]
    check("D 按钮在右侧", b[0] > 700, str(b))

# ---------- E: 找去领奖按钮 ----------
print("=== E: 找去领奖按钮 ===")
ui = FakeUI(os.path.join(ROOT, "_drops", "dialog.xml"))
claim = mod._find_claim_button(ui)
check("E 找到去领奖", claim is not None)
if claim:
    check("E text=去领奖", claim["text"] == "去领奖")
    check("E 在右侧", claim["bounds"][0] > 700)

# ---------- F: dialog5.xml ----------
print("=== F: dialog5.xml ===")
ui = FakeUI(os.path.join(ROOT, "_drops", "dialog5.xml"))
check("F 弹窗打开", mod._is_drops_dialog(ui))
task_btn = mod._find_next_browse_task(ui)
check("F 找到浏览任务", task_btn is not None)
if task_btn:
    check("F btn_text 正确", task_btn["btn_text"] in BROWSE_BUTTON_TEXTS,
          repr(task_btn["btn_text"]))
claim = mod._find_claim_button(ui)
check("F 找到去领奖", claim is not None)

# ---------- G: 农场页不是弹窗 ----------
print("=== G: 农场页不是弹窗 ===")
ui = FakeUI(os.path.join(ROOT, "_farm_farm_home2.xml"))
check("G _is_drops_dialog=False", not mod._is_drops_dialog(ui))

# ---------- H: 按钮不过滤 clickable ----------
print("=== H: 按钮不过滤 clickable ===")
# 在 dialog.xml 里，去完成/去领奖都是 clickable=false 的 TextView
# 我们的查找函数不应该用 clickable 过滤
ui = FakeUI(os.path.join(ROOT, "_drops", "dialog.xml"))
task_btn = mod._find_next_browse_task(ui)
check("H clickable=false 的按钮也能找到", task_btn is not None)
claim = mod._find_claim_button(ui)
check("H clickable=false 的去领奖也能找到", claim is not None)

print("\n==== %d passed, %d failed ====" % (len(PASSED), len(FAILED)))
if FAILED:
    for f in FAILED:
        print("  FAILED: %s" % f)
    sys.exit(1)
