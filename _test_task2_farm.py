# -*- coding: utf-8 -*-
"""任务2【东东农场】离线回归：不连手机，用 FakeUI + 真机采集的 XML。

用例：
  A 浏览循环正常收敛（3 个逛一逛 -> 全变继续逛）
  B 点击被吞：不执行 7 秒等待、不 back（任务1 踩过的坑）
  C 当前屏没有可见按钮 -> 滚动后继续
  D 连续无进展刹车
  E 抽奖到剩余 0 次
  F 剩余已为 0 时不点击
  G 抽奖无进展刹车
  H/I/J 入口：第一页命中 / 第二页命中 / 两页都没有走兜底
  K 气泡尝试顺序：第二个气泡是【抽10京豆】，点错会自动换
  L 真机 XML 回归：剩余次数、逛一逛/继续逛计数、可见按钮、气泡枚举
"""
import io
import os
import sys
import threading

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from modules.task2_farm import Task2Farm, FarmUI, POINTS, BROWSE_SECONDS

PASSED = []
FAILED = []


def check(name, cond, detail=""):
    if cond:
        PASSED.append(name)
        print("PASS %s %s" % (name, detail))
    else:
        FAILED.append(name)
        print("FAIL %s %s" % (name, detail))


class Log(object):
    def __init__(self):
        self.lines = []

    def write_log(self, msg, level="INFO"):
        self.lines.append((level, msg))


class FakeUI(object):
    """只实现 _browse_all / _draw_all 用到的接口。"""

    def __init__(self, left=3, remaining=3, swallow=False, no_progress=False,
                 visible_script=None, left_script=None):
        self.W, self.H = 1080, 2340
        self.left_script = list(left_script or [])
        self.left = left
        self.continued = 0
        self.remain = remaining
        self.on_wheel_page = True
        self.swallow = swallow
        self.no_progress = no_progress
        self.visible_script = list(visible_script or [])
        self.taps = []
        self.backs = 0
        self.sleeps = []
        self.scrolls = 0
        self.btn_seq = 0

    def sx(self, x):
        return x

    def sy(self, y):
        return y

    def say(self, *a, **kw):
        pass

    def invalidate(self):
        pass

    def source(self, fresh=False):
        return "<fake/>"

    def on_wheel(self, xml=None):
        return self.on_wheel_page

    def ensure_wheel(self, max_attempts=5):
        self.on_wheel_page = True
        return True

    def count_button(self, text, xml=None):
        if text == "逛一逛" and self.left_script:
            self.left, self.continued = self.left_script.pop(0)
        if text == "逛一逛":
            return self.left
        if text == "继续逛":
            return self.continued
        return 0

    def browse_buttons(self, xml=None):
        if self.visible_script:
            n = self.visible_script.pop(0)
        else:
            n = 1
        out = []
        for i in range(n):
            self.btn_seq += 1
            out.append({"text": "逛一逛",
                        "bounds": (816, 1485 + i * 226, 1003, 1570 + i * 226),
                        "pos": (909, 1527 + i * 226)})
        return out

    def center(self, n):
        return n.get("pos") or ((n["bounds"][0] + n["bounds"][2]) // 2,
                                (n["bounds"][1] + n["bounds"][3]) // 2)

    def tap(self, pos, pause=1.5):
        self.taps.append(("tap", pos))
        if not self.swallow:
            self.on_wheel_page = False

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        return True

    def back(self, pause=2):
        self.backs += 1
        self.on_wheel_page = True
        if not self.no_progress:
            self.left = max(0, self.left - 1)
            self.continued += 1
            self.remain += 1

    def wheel_scroll(self, up=True):
        self.scrolls += 1

    def prize_dialog_open(self, xml=None):
        return False

    def dismiss_prize_dialog(self):
        return True

    def ensure_wheel_top(self, max_swipes=5):
        return True

    def remaining(self, xml=None):
        return self.remain


class FakeDrawUI(FakeUI):
    """抽奖阶段：点击【开始抽奖】让剩余次数 -1。"""

    def tap(self, pos, pause=1.5):
        self.taps.append(("draw", pos))
        if not self.no_progress:
            self.remain = max(0, self.remain - 1)


def new_stop():
    return threading.Event()


# ---------- A~D 浏览循环 ----------
mod = Task2Farm()
check("A0 停留常量=15s", BROWSE_SECONDS == 15,
      "BROWSE_SECONDS=%r" % BROWSE_SECONDS)

ui = FakeUI(left=3)
log = Log()
n = mod._browse_all(ui, log, new_stop())
check("A 浏览收敛", n == 3 and ui.left == 0 and ui.backs == 3,
      "done=%d left=%d backs=%d" % (n, ui.left, ui.backs))
check("A 每次停留15秒", ui.sleeps.count(15) == 3 and 10 not in ui.sleeps,
      "sleeps=%r" % ui.sleeps)

ui = FakeUI(left=3, swallow=True)
log = Log()
n = mod._browse_all(ui, log, new_stop())
check("B 点击被吞不空等", n == 0 and ui.backs == 0 and 7 not in ui.sleeps,
      "done=%d backs=%d sleeps=%r" % (n, ui.backs, ui.sleeps))
check("B 有界退出", ui.scrolls > 0 and ui.scrolls <= 20,
      "scrolls=%d" % ui.scrolls)

ui = FakeUI(left=1, visible_script=[0, 0, 1])
log = Log()
n = mod._browse_all(ui, log, new_stop())
check("C 滚动后找到按钮", n == 1 and ui.scrolls == 2,
      "done=%d scrolls=%d" % (n, ui.scrolls))

ui = FakeUI(left=9, no_progress=True)
log = Log()
n = mod._browse_all(ui, log, new_stop())
check("D 无进展刹车", n == 0 and ui.backs == 3 and ui.left == 9,
      "done=%d backs=%d" % (n, ui.backs))

# M/N 列表尚未渲染的边界（真机复跑时出现 0/0）
ui = FakeUI(left=0, left_script=[(0, 0), (0, 0), (3, 0)])
log = Log()
n = mod._browse_all(ui, log, new_stop())
check("M 列表未渲染不误判完成", n == 3 and ui.left == 0,
      "done=%d left=%d sleeps=%r" % (n, ui.left, ui.sleeps))

ui = FakeUI(left=0, left_script=[(0, 0)] * 10)
log = Log()
n = mod._browse_all(ui, log, new_stop())
check("N 空列表有界退出", n == 0 and ui.sleeps.count(2) == 3,
      "done=%d sleeps=%r" % (n, ui.sleeps))

# ---------- E~G 抽奖 ----------
ui = FakeDrawUI(remaining=3)
log = Log()
n = mod._draw_all(ui, log, new_stop())
check("E 抽到剩余0次", n == 3 and ui.remain == 0,
      "draws=%d remain=%d" % (n, ui.remain))

ui = FakeDrawUI(remaining=0)
log = Log()
n = mod._draw_all(ui, log, new_stop())
check("F 剩余0次不点击", n == 0 and len(ui.taps) == 0, "taps=%r" % ui.taps)

ui = FakeDrawUI(remaining=5, no_progress=True)
log = Log()
n = mod._draw_all(ui, log, new_stop())
check("G 抽奖无进展刹车", n == 0 and len(ui.taps) == 3,
      "taps=%d" % len(ui.taps))


# ---------- H~K 入口 / 气泡 ----------
def node(x1, y1, x2, y2, desc=""):
    return {"desc": desc, "text": "", "bounds": (x1, y1, x2, y2),
            "clickable": True, "class": "FrameLayout"}


class FakeFarm(FarmUI):
    def __init__(self, pages=None, farm_ready=True, wheel_hits=(2,)):
        self.W, self.H = 1080, 2340
        self.stop = None
        self._restarted = False
        self.pages = list(pages or [None])
        self.farm_ready = farm_ready
        self.wheel_hits = set(wheel_hits)
        self.logs = []
        self.taps = []
        self.swipes = []
        self.bubble_try = 0
        self.via_channels = 0
        self.back_count = 0

    def say(self, msg, level="INFO"):
        self.logs.append(msg)

    def restart_to_home(self, wait=6):
        return True

    def farm_kingkong_node(self):
        if self.pages:
            return self.pages.pop(0)
        return None

    def swipe(self, key, pause=1.5):
        self.swipes.append(key)

    def _raw_swipe(self, key, pause=1.2):
        self.swipes.append(key)

    def wait_farm_ready(self, timeout=18):
        return self.farm_ready

    def open_farm_via_channels(self):
        self.via_channels += 1
        return True

    def to_all_channels(self):
        return True

    def center(self, n):
        return ((n["bounds"][0] + n["bounds"][2]) // 2,
                (n["bounds"][1] + n["bounds"][3]) // 2)

    def tap(self, pos, pause=1.5):
        self.taps.append(pos)

    def sx(self, x):
        return x

    def sy(self, y):
        return y

    def sleep(self, seconds):
        return True

    def back(self, pause=2):
        self.back_count += 1

    def invalidate(self):
        pass

    def is_farm_page(self, xml=None):
        return True

    def source(self, fresh=False):
        return "<fake/>"

    def nodes(self, xml=None, contains=None):
        return []

    def remaining(self, xml=None):
        return 2

    # 气泡相关
    def farm_bubbles(self, xml=None):
        return [{"text": "图片", "bounds": b, "clickable": True}
                for b in [(913, 404, 1061, 552), (913, 605, 1061, 751),
                          (913, 803, 1061, 951)]]

    def wait_wheel(self, timeout=15):
        self.bubble_try += 1
        return self.bubble_try in self.wheel_hits


# H: 第一页就是完整格子
f = FakeFarm(pages=[node(3, 440, 219, 601, "东东农场")])
f.open_farm()
check("H 第一页直接命中", len(f.taps) == 1 and f.swipes == [] and f.via_channels == 0,
      "taps=%r swipes=%r" % (f.taps, f.swipes))

# I: 第一页半露 -> 第二页完整
f = FakeFarm(pages=[node(959, 440, 1080, 601, "东东农场"),
                    node(3, 440, 219, 601, "东东农场")])
f.open_farm()
check("I 第二页命中完整格子", len(f.taps) == 1 and "kingkong" in f.swipes
      and f.taps[0] == (111, 520), "taps=%r swipes=%r" % (f.taps, f.swipes))

# J: 两页都没有 -> 兜底
f = FakeFarm(pages=[None, None])
f.open_farm()
check("J 两页未命中走兜底", f.via_channels == 1 and len(f.taps) == 0,
      "via=%d taps=%r swipes=%r" % (f.via_channels, f.taps, f.swipes))

# K: 第 2 个气泡命中转盘页
f = FakeFarm(wheel_hits=(1,))
ok = f.enter_wheel()
def near(pos, ref):
    return abs(pos[0] - ref[0]) <= 2 and abs(pos[1] - ref[1]) <= 2


check("K 优先点第2个气泡", ok and near(f.taps[0], POINTS["bubble_draw"]),
      "taps=%r" % f.taps)

# K2: 第 2 个气泡没进 -> 自动换其它气泡
f = FakeFarm(wheel_hits=(3,))
ok = f.enter_wheel()
check("K2 点错气泡自动换",
      ok and len(f.taps) >= 2 and near(f.taps[0], POINTS["bubble_draw"]),
      "taps=%r" % f.taps)

# ---------- L 真机 XML 回归 ----------
def load(name):
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), name)
    if not os.path.exists(p):
        return None
    return open(p, encoding="utf-8").read()


u = FarmUI.__new__(FarmUI)
u.W, u.H = 1080, 2340

xml = load("_farm_wheel2.xml")
if xml:
    check("L1 转盘页剩余次数", u.remaining(xml) == 2, "got=%r" % u.remaining(xml))
    check("L2 全文统计逛一逛/继续逛",
          u.count_button("逛一逛", xml) == 15 and u.count_button("继续逛", xml) == 1,
          "逛=%d 继续=%d" % (u.count_button("逛一逛", xml),
                             u.count_button("继续逛", xml)))
    check("L3 仅可见按钮可点", len(u.browse_buttons(xml)) == 4,
          "got=%d" % len(u.browse_buttons(xml)))
xml2 = load("_farm_after_back.xml")
if xml2:
    check("L4 完成1个后计数变化",
          u.remaining(xml2) == 3 and u.count_button("逛一逛", xml2) == 14
          and u.count_button("继续逛", xml2) == 2,
          "剩余=%r 逛=%d 继续=%d" % (u.remaining(xml2),
                                    u.count_button("逛一逛", xml2),
                                    u.count_button("继续逛", xml2)))
xml3 = load("_farm_wheel_scroll.xml")
if xml3:
    check("L5 滚动后底部半截按钮被排除", len(u.browse_buttons(xml3)) == 7,
          "got=%d" % len(u.browse_buttons(xml3)))
xml4 = load("_farm_farm_home2.xml")
if xml4:
    check("L6 农场页识别", u.is_farm_page(xml4), "")
    bubbles = u.farm_bubbles(xml4)
    check("L7 气泡枚举与抽10京豆顺序",
          len(bubbles) >= 2 and u.center(bubbles[1]) == (987, 677),
          "centers=%r" % [u.center(b) for b in bubbles])

print("\n===== %d passed, %d failed =====" % (len(PASSED), len(FAILED)))
if FAILED:
    print("FAILED:", ", ".join(FAILED))
    sys.exit(1)
