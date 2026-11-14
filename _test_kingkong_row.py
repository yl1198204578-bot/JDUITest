# -*- coding: utf-8 -*-
"""金刚区动态定位离线回归：不连手机，用真机 XML + 合成 XML。

用例：
  A 真机第一页 XML：kingkong_row 定出 y=440~601，含【秒杀】锚点
  B 顶部 tab 行（y=331~440，高度 109）不被误当成金刚区
  C 真机第二页 XML（展开成 4 行）：仍定出金刚区主行
  D 金刚区整体下移 460px 的改版场景：仍定出新 y，不用固定 520
  E swipe_kingkong 用 kingkong_row 算出的 y，且是短距离 ADB 滑动
  F page_state 不再写死 400~700，金刚区下移后仍判 home
  G to_all_channels 必须「左滑 -> 按节点点」，不按固定坐标盲点
  H 滑满上限仍找不到【全部频道】时明确报错，而不是静默坐标兜底
"""
import io
import os
import re
import sys
import types
import struct
import xml.etree.ElementTree as ET

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

# mock 掉 appium 依赖
mock_driver = types.ModuleType("utils.driver")
mock_driver.get_driver = lambda: None
sys.modules["utils.driver"] = mock_driver

from utils.jd_ui import JDUI, KINGKONG_ANCHOR_DESCS

PASSED = []
FAILED = []


def check(name, cond, detail=""):
    if cond:
        PASSED.append(name)
        print("PASS %s %s" % (name, detail))
    else:
        FAILED.append(name)
        print("FAIL %s %s" % (name, detail))


class StubDriver(object):
    def __init__(self, xml=""):
        self.page_source = xml

    def update_settings(self, s):
        pass

    def get_screenshot_as_png(self):
        return (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
                + struct.pack(">II", 1080, 2340))

    def press_keycode(self, k):
        pass


class Log(object):
    def __init__(self):
        self.lines = []

    def write_log(self, msg, level="INFO"):
        self.lines.append((level, msg))


def make_ui(xml):
    ui = JDUI(StubDriver(xml), Log())
    ui.sleep = lambda s: True
    ui._restarted = True
    ui.swipes = []
    ui.taps = []
    ui.adb_swipe = lambda *a, **kw: ui.swipes.append(a)
    ui.tap = lambda *a, **kw: ui.taps.append(a)
    return ui


def load(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


P1 = load(os.path.join(ROOT, "_farm_home.xml"))
P2 = load(os.path.join(ROOT, "_farm_home_p2.xml"))

# ---------------------------------------------------------------- A/B/C
print("=== A/B/C: 真机 XML 上定位金刚区行 ===")
ui = make_ui(P1)
row = ui.kingkong_row()
check("A 第一页找到金刚区行", row is not None)
if row:
    check("A y 带 = 440~601", (row[0], row[1]) == (440, 601), str((row[0], row[1])))
    descs = [i["desc"] for i in row[2]]
    check("A 含【秒杀】锚点", "秒杀" in descs, str(descs))
    check("A 不误选顶部 tab 行", row[0] != 331, "y_top=%d" % row[0])
    check("A 至少 4 个格子", len(row[2]) >= 4, "n=%d" % len(row[2]))

# B：单看 kingkong_icons，确认顶部 tab 的 7 个矮按钮没进来
icons = ui.kingkong_icons(P1)
tab_row = [i for i in icons if i["y1"] == 331]
check("B 顶部 tab 行被高度过滤", len(tab_row) == 0, "tab_icons=%d" % len(tab_row))

row2 = make_ui(P2).kingkong_row()
check("C 第二页仍找到金刚区行", row2 is not None)
if row2:
    check("C 第二页主行 y=440~601", (row2[0], row2[1]) == (440, 601),
          str((row2[0], row2[1])))

# ---------------------------------------------------------------- D/E/F
print("\n=== D/E/F: 金刚区改版下移 460px ===")


def shifted_xml(xml, dy):
    """只把金刚区那一排（y=440~601）的可点击格子整体下移 dy，模拟首页改版。"""
    out = []
    for line in xml.split("\n"):
        if 'content-desc=' in line and re.search(r'bounds="\[\d+,440\]\[\d+,601\]"', line):
            def bump(m):
                return 'bounds="[%s,%d][%s,%d]"' % (
                    m.group(1), int(m.group(2)) + dy,
                    m.group(3), int(m.group(4)) + dy)
            line = re.sub(r'bounds="\[(\d+),(440)\]\[(\d+),(601)\]"', bump, line)
        out.append(line)
    return "\n".join(out)


SHIFTED = shifted_xml(P1, 460)
ui_s = make_ui(SHIFTED)
row_s = ui_s.kingkong_row()
check("D 改版后仍找到金刚区行", row_s is not None)
if row_s:
    check("D y 带随之变成 900~1061", (row_s[0], row_s[1]) == (900, 1061),
          str((row_s[0], row_s[1])))
    check("D 仍含【秒杀】锚点", "秒杀" in [i["desc"] for i in row_s[2]])

ui_s.swipe_kingkong("left", pause=0)
check("E 滑动用的是算出的 y=980", len(ui_s.swipes) == 1 and ui_s.swipes[0][1] == 980,
      str(ui_s.swipes))
if ui_s.swipes:
    x1, y1, x2, y2, dur = ui_s.swipes[0][:5]
    check("E 是短距离横向滑动", x1 > x2 and (x1 - x2) < 800, "%d->%d" % (x1, x2))
    check("E y1==y2（同一排）", y1 == y2, "%d/%d" % (y1, y2))

# F: 构造只靠「秒杀」判首页的 XML（没有 "首页, 已选中"），且秒杀在 y=900
only_seckill = '''<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node class="android.view.ViewGroup" text="" content-desc="秒杀"
        clickable="true" displayed="true" bounds="[0,900][194,1061]" />
</hierarchy>'''
ui_f = make_ui(only_seckill)
check("F 秒杀小图标下移后仍判 home", ui_f.page_state() == "home",
      ui_f.page_state())

# ---------------------------------------------------------------- G/H
print("\n=== G/H: to_all_channels 必须滑动 + 按节点点 ===")


def make_seq_ui(xmls):
    """第一页 -> 第二页的可切换 UI，记录滑动与点击。"""
    ui = JDUI(StubDriver(xmls[0]), Log())
    ui.sleep = lambda s: True
    ui._restarted = True
    ui.goto_home = lambda *a, **kw: True
    ui.idx = 0
    ui.swipe_calls = []
    ui.tap_calls = []
    ui.tapped = False
    # page_state 跟随点击：点完【全部频道】才算到频道页。
    # to_all_channels 现在必须真验到 channels（假绿灯已取消），
    # 桩把状态写死成 home 就永远过不去。
    ui.page_state = lambda *a, **kw: "channels" if ui.tapped else "home"

    def _source(fresh=False, _ui=ui, _xmls=xmls):
        return _xmls[_ui.idx]
    ui.source = _source
    ui.invalidate = lambda: None

    def _swipe(direction, pause=1.5):
        ui.swipe_calls.append(direction)
        ui.idx = min(ui.idx + 1, len(xmls) - 1)
    ui.swipe_kingkong = _swipe
    def _tap(*a, **kw):
        ui.tap_calls.append(a)
        ui.tapped = True
    ui.tap = _tap
    return ui


# 把第二页【全部频道】的 bounds 从 [867,924,1080,1085] 改成 [867,1200,1080,1361]
# 中心变成 (973,1280)；旧固定坐标 (973,1004) 就点不到了
P2_MOVED = P2.replace('content-desc="全部频道"', 'content-desc="全部频道"', 1)
P2_MOVED = re.sub(
    r'(content-desc="全部频道"[^>]*?)bounds="\[867,924\]\[1080,1085\]"',
    r'\1bounds="[867,1200][1080,1361]"', P2_MOVED)

ui_g = make_seq_ui([P1, P2_MOVED])
ui_g.to_all_channels()
check("G 至少左滑一次", len(ui_g.swipe_calls) >= 1 and ui_g.swipe_calls[0] == "left",
      str(ui_g.swipe_calls))
check("G 点的是【全部频道】节点中心 (973,1280)",
      len(ui_g.tap_calls) == 1 and ui_g.tap_calls[0][0] == (973, 1280),
      str(ui_g.tap_calls))
check("G 没有用固定坐标 (973,1004)",
      all(t[0] != (973, 1004) for t in ui_g.tap_calls), str(ui_g.tap_calls))

# H: 两页都没有【全部频道】 -> 必须明确报错
ui_h = make_seq_ui([P1, P1])
try:
    ui_h.to_all_channels()
    check("H 滑满上限后明确报错", False, "未抛异常")
except RuntimeError as e:
    check("H 滑满上限后明确报错", "全部频道" in str(e), str(e))

# ---------------------------------------------------------------- I
print("\n=== I: swipe('kingkong') 委托到动态滑动 ===")
ui_i = make_ui(P1)
ui_i.swipe("kingkong", pause=0)
check("I swipe('kingkong') 走动态左滑",
      len(ui_i.swipes) == 1 and ui_i.swipes[0][0] > ui_i.swipes[0][2],
      str(ui_i.swipes))
ui_j = make_ui(P1)
ui_j.swipe("kingkong_back", pause=0)
check("I swipe('kingkong_back') 走动态右滑",
      len(ui_j.swipes) == 1 and ui_j.swipes[0][0] < ui_j.swipes[0][2],
      str(ui_j.swipes))

print("\n==== %d passed, %d failed ====" % (len(PASSED), len(FAILED)))
if FAILED:
    for f in FAILED:
        print("  FAILED: %s" % f)
    sys.exit(1)
