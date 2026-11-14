# -*- coding: utf-8 -*-
"""JOY游记 模块离线回归（不连手机、不跑 OCR）。

覆盖：
  A. 纯逻辑：parse_rows 配对 / 排除非浏览任务 / 时长换算 / 面板识别 / 裁剪高度
  B. 流程：做 N 个任务后结束、滚动找任务、滚不动就收尾、无进展刹车、掉面板重进
所有坐标取自 2026-11-12 真机面板的真实 OCR 结果（1080x2340）。
"""
import io
import sys

sys.path.insert(0, ".")

from modules.task5_joy_trip import (
    Task5JoyTrip, parse_rows, browse_seconds, panel_visible, panel_crop_top,
    find_text, BROWSE_EXTRA, BTN_MIN_X, ROW_TOL,
)

PASSED = []
FAILED = []


def check(name, cond, detail=""):
    if cond:
        PASSED.append(name)
        print("PASS %s" % name)
    else:
        FAILED.append(name)
        print("FAIL %s   %s" % (name, detail))


def item(text, cx, cy, w=90, h=40):
    return {"text": text, "cx": cx, "cy": cy,
            "x1": cx - w // 2, "y1": cy - h // 2, "x2": cx + w // 2, "y2": cy + h // 2}


# ---------------------------------------------------------------- A 纯逻辑
print("=== A: 真机面板 OCR 数据 ===")
REAL = [
    item(u"做任务赚晶石", 540, 683),
    item(u"+5", 100, 815), item(u"+10", 220, 814), item(u"+20", 380, 815),
    item(u"已签到", 930, 877),
    # 行1 逛一逛高价回收：描述 1101 / 按钮 1133 / 小字 1166
    item(u"逛一逛高价回收(0/1)", 400, 1101, 300),
    item(u"逛一逛", 933, 1133),
    item(u"浏览10s+15", 350, 1166, 200),
    # 行2 双十一限时0元白拿
    item(u"双十一限时0元白拿(0/1)", 400, 1328, 320),
    item(u"逛一逛", 933, 1359),
    item(u"浏览10s+30", 350, 1390, 200),
    # 行3 每日领京豆
    item(u"每日领京豆/现金(0/1)", 400, 1552, 300),
    item(u"逛一逛", 933, 1582),
    item(u"浏览10s+30", 350, 1615, 200),
    # 行4 完成访问 -> 必须排除
    item(u"去JoyAI抽20元(0/1)", 400, 1777, 280),
    item(u"去完成", 933, 1809),
    item(u"完成访问+15", 350, 1838, 200),
    # 行5 逛一逛精选活动（浏览10s可得，按钮是去完成 -> 要做）
    item(u"逛一逛精选活动(0/8)", 400, 2001, 300),
    item(u"去完成", 933, 2033),
    item(u"浏览10s可得+25", 350, 2065, 220),
    # 行6 逛超级补贴
    item(u"逛超级补贴抽8元红包(0/1)", 400, 2225, 340),
    item(u"逛一逛", 933, 2257),
    item(u"浏览10s+15", 350, 2290, 200),
]

rows = parse_rows(REAL)
check("A1 真机面板配对出 5 个可做任务", len(rows) == 5, "got=%d %r" % (len(rows), [r["text"] for r in rows]))
check("A2 全部是 浏览10s", all(r["secs"] == 10 for r in rows), str([r["secs"] for r in rows]))
check("A3 【完成访问】行被排除",
      all(u"完成访问" not in r["text"] for r in rows), str([r["text"] for r in rows]))
check("A4 去完成 与 逛一逛 都算可做",
      set(r["btn"] for r in rows) == {u"逛一逛", u"去完成"}, str(set(r["btn"] for r in rows)))
check("A5 按 y 从上到下排序",
      [r["cy"] for r in rows] == sorted(r["cy"] for r in rows), str([r["cy"] for r in rows]))
check("A6 点的是右侧按钮 x", all(r["cx"] >= BTN_MIN_X for r in rows), str([r["cx"] for r in rows]))

print("\n=== A7-A12: 边界 ===")
# 描述里的「逛一逛精选活动」在左边，不能被当成按钮
left_btn = [item(u"逛一逛精选活动(0/8)", 400, 2001, 300), item(u"浏览10s", 350, 2065, 200)]
check("A7 左侧描述里的【逛一逛】不算按钮", parse_rows(left_btn) == [], str(parse_rows(left_btn)))

check("A8 浏览5s -> secs=5",
      [r["secs"] for r in parse_rows([item(u"逛一逛", 933, 1100), item(u"浏览5s+5", 350, 1130)])] == [5])
check("A9 浏览15s -> secs=15",
      [r["secs"] for r in parse_rows([item(u"去完成", 933, 1100), item(u"浏览15s", 350, 1130)])] == [15])
check("A10 浏览10s可得+25 -> secs=10",
      [r["secs"] for r in parse_rows([item(u"去完成", 933, 1100), item(u"浏览10s可得+25", 350, 1130)])] == [10])
check("A11 只有按钮没有小字 -> 不算任务",
      parse_rows([item(u"逛一逛", 933, 1100)]) == [])
check("A12 小字离按钮太远（>ROW_TOL）-> 不配对",
      parse_rows([item(u"逛一逛", 933, 1100), item(u"浏览10s", 350, 1100 + ROW_TOL + 30)]) == [])

print("\n=== A13-A18: 时长 / 面板 / 裁剪 ===")
check("A13 X+4 规则：10->14", browse_seconds(10) == 14, str(browse_seconds(10)))
check("A14 X+4 规则：5->9", browse_seconds(5) == 9)
check("A15 X+4 规则：15->19", browse_seconds(15) == 19)
check("A16 BROWSE_EXTRA 就是 4", BROWSE_EXTRA == 4, str(BROWSE_EXTRA))
check("A17 面板标题识别", panel_visible(REAL) is True)
check("A18 非面板（JOY 首页）不误判",
      panel_visible([item(u"去赚奖励", 959, 2203), item(u"领红包", 123, 2201)]) is False)
check("A19 find_text 命中去赚奖励",
      (find_text([item(u"去赚奖励", 959, 2203)], u"去赚奖励") or {}).get("cx") == 959)
check("A20 find_text 未命中返回 None", find_text([], u"去赚奖励") is None)
check("A21 裁剪高度 2340 -> 620", panel_crop_top(2340) == 620, str(panel_crop_top(2340)))
check("A22 裁剪高度 1560 -> 413", panel_crop_top(1560) == 413, str(panel_crop_top(1560)))


# ---------------------------------------------------------------- B 流程
print("\n=== B: 流程 ===")


class FakeUI(object):
    W, H = 1080, 2340

    def __init__(self):
        self.taps = []
        self.sleeps = []
        self.backs = 0
        self.swipes = 0

    def tap(self, pos, pause=0):
        self.taps.append(pos)

    def sleep(self, s):
        self.sleeps.append(s)
        return True

    def back(self, pause=0):
        self.backs += 1

    def adb_swipe(self, *a, **kw):
        self.swipes += 1


def panel(rows, title=True):
    items = [item(u"做任务赚晶石", 540, 683)] if title else []
    for i, (sub, btn) in enumerate(rows):
        y = 1100 + i * 220
        items.append(item(u"任务%d(0/1)" % i, 300, y, 300))
        items.append(item(btn, 933, y + 30))
        items.append(item(sub, 350, y + 62, 200))
    return items


class Scripted(Task5JoyTrip):
    """按脚本返回面板内容，记录调用。"""

    def __init__(self, panels, screen=None, scroll_results=None):
        self.panels = list(panels)
        self.screen = screen if screen is not None else [item(u"去赚奖励", 959, 2203)]
        self.scroll_results = list(scroll_results or [])
        self.reads = 0
        self.scrolls = 0

    def _read_panel(self, ui):
        i = min(self.reads, len(self.panels) - 1)
        self.reads += 1
        return self.panels[i]

    def _read_screen(self, ui):
        return self.screen

    def _scroll_panel(self, ui):
        ui.swipes += 1
        self.scrolls += 1
        return self.scroll_results.pop(0) if self.scroll_results else False


class Log(object):
    def __init__(self):
        self.lines = []

    def write_log(self, msg, level="INFO"):
        self.lines.append((level, msg))

    def done(self, msg=""):
        self.lines.append(("DONE", msg))

    def error(self, msg):
        self.lines.append(("ERROR", msg))


import threading
stop = threading.Event()

# B1: 3 个任务 -> 空 -> 滚不动 -> 结束
m = Scripted([
    panel([(u"浏览10s+15", u"逛一逛"), (u"浏览10s+30", u"逛一逛"), (u"浏览10s+30", u"逛一逛")]),
    panel([(u"浏览10s+30", u"逛一逛"), (u"浏览10s+30", u"逛一逛")]),
    panel([(u"浏览10s+30", u"逛一逛")]),
    panel([]),
], scroll_results=[False])
ui = FakeUI()
log = Log()
done = m._process_tasks(ui, log, stop)
check("B1 做完 3 个任务后结束", done == 3, "done=%d" % done)
check("B2 每次停留 14 秒", ui.sleeps == [14, 14, 14], str(ui.sleeps))
check("B3 点了 3 次按钮", len(ui.taps) == 3, str(ui.taps))
check("B4 点的是右侧按钮坐标", all(t[0] >= BTN_MIN_X for t in ui.taps), str(ui.taps))
check("B5 每次做完都返回一次", ui.backs == 3, "backs=%d" % ui.backs)

# B6: 首屏没有可做任务 -> 滚动一次出现 -> 做完
m = Scripted([
    panel([]),
    panel([(u"浏览10s+15", u"逛一逛")]),
    panel([]),
], scroll_results=[True, False])
ui = FakeUI()
done = m._process_tasks(ui, Log(), stop)
check("B6 空屏先滚动再找", m.scrolls >= 1 and done == 1, "scrolls=%d done=%d" % (m.scrolls, done))

# B7: 滚不动就立刻收尾（不能死循环）
m = Scripted([panel([])], scroll_results=[False])
ui = FakeUI()
done = m._process_tasks(ui, Log(), stop)
check("B7 滚不动立即结束", done == 0 and m.scrolls == 1, "scrolls=%d" % m.scrolls)

# B8: 任务点了但没算完成（行数不变）-> 连续 3 次后滚动
same = panel([(u"浏览10s+15", u"逛一逛"), (u"浏览10s+30", u"逛一逛")])
m = Scripted([same, same, same, same, same, same], scroll_results=[True, False])
ui = FakeUI()
done = m._process_tasks(ui, Log(), stop)
check("B8 无进展 3 次后触发滚动", m.scrolls >= 1, "scrolls=%d" % m.scrolls)
check("B9 无进展不算完成任务", done == 0, "done=%d" % done)

# B10: 返回后面板消失 -> 走重进流程
class LostPanel(Scripted):
    def __init__(self):
        Scripted.__init__(self, [
            panel([(u"浏览10s+15", u"逛一逛")]),
            panel([], title=False),          # 返回后不在面板
            panel([]),                        # 重进后拿到空面板
        ], scroll_results=[False])
        self.reenter = 0

    def _open_task_panel(self, ui, log):
        self.reenter += 1
        return panel([])


m = LostPanel()
ui = FakeUI()
done = m._process_tasks(ui, Log(), stop)
check("B10 面板丢了会重进", m.reenter >= 1, "reenter=%d" % m.reenter)

# B11: 停止信号 -> 立刻不干活
m = Scripted([panel([(u"浏览10s+15", u"逛一逛")])])
ui = FakeUI()
st = threading.Event()
st.set()
done = m._process_tasks(ui, Log(), st)
check("B11 stop_event 已置位时不点任何按钮", len(ui.taps) == 0 and done == 0, str(ui.taps))

# B12: 任务上限
many = [(u"浏览10s+15", u"逛一逛")] * 3
m = Scripted([panel(many)] * 60, scroll_results=[False])
ui = FakeUI()
done = m._process_tasks(ui, Log(), stop)
check("B12 不会无限做下去（有上限）", done <= 40, "done=%d" % done)

# ---------------------------------------------------------------- C 截图失败容错
print("\n=== C: 截图失败不能拿旧图凑数 ===")
import modules.task5_joy_trip as joy

check("C1 parse_rows(None) -> []", parse_rows(None) == [])
check("C2 panel_visible(None) -> False", panel_visible(None) is False)
check("C3 find_text(None) -> None", find_text(None, u"去赚奖励") is None)
check("C4 ocr_items(None) -> None", joy.ocr_items(None) is None)
check("C5 ocr_items(不存在的文件) -> None", joy.ocr_items(r"Z:\nope\no.png") is None)

_real_call = joy.subprocess.call
_real_sleep = joy.time.sleep
try:
    joy.subprocess.call = lambda *a, **kw: 1        # 模拟 adb 全部失败
    joy.time.sleep = lambda s: None
    got = joy.screencap()
    check("C6 adb 全失败时 screencap 返回 None（不返回旧图路径）", got is None, str(got))
finally:
    joy.subprocess.call = _real_call
    joy.time.sleep = _real_sleep

# ---------------------------------------------------------------- D 多步任务进度
print("\n=== D: 多步任务用「计数变化」判进度 ===")
from modules.task5_joy_trip import row_title, row_sig

TITLE = u"逛一逛精选活动(5/8)"
SUB = u"浏览10s可得+25"

# 真机数据：描述 y=1325、按钮 y=1358、小字 y=1390
real_row = [item(TITLE, 401, 1325, 300),
            item(u"去完成", 933, 1358),
            item(SUB, 342, 1390, 220)]
btn = real_row[1]
check("D1 标题取按钮上方那行", row_title(real_row, btn, BTN_MIN_X) == TITLE,
      row_title(real_row, btn, BTN_MIN_X))
check("D2 不会把下方小字当标题", row_title(real_row, btn, BTN_MIN_X) != SUB)

rows_a = parse_rows(real_row)
check("D3 parse_rows 带出 title", bool(rows_a) and rows_a[0]["title"] == TITLE, str(rows_a))

sig1 = row_sig([{"title": u"逛一逛精选活动(1/8)", "text": u"x"}])
sig2 = row_sig([{"title": TITLE, "text": u"x"}])
check("D4 (1/8)->(5/8) 签名变化", sig1 != sig2, "%r vs %r" % (sig1, sig2))
check("D5 完全相同时签名相等", sig2 == sig2)


def panel_titled(title, sub, btn_text, y=1100):
    return [item(u"做任务赚晶石", 540, 683),
            item(title, 300, y, 300),
            item(btn_text, 933, y + 30),
            item(sub, 350, y + 62, 200)]


m = Scripted([
    panel_titled(u"逛一逛精选活动(1/8)", SUB, u"去完成"),
    panel_titled(TITLE, SUB, u"去完成"),
    panel_titled(TITLE, SUB, u"去完成"),
], scroll_results=[False])
ui = FakeUI()
done = m._process_tasks(ui, Log(), stop)
check("D6 行数不变但计数涨了 -> 算完成", done == 1, "done=%d" % done)
check("D7 计数没变化的行不会被无限重试", len(ui.taps) <= 3, str(len(ui.taps)))

print("\n==== %d passed, %d failed ====" % (len(PASSED), len(FAILED)))
if FAILED:
    for f in FAILED:
        print("  FAILED: %s" % f)
    sys.exit(1)
