# -*- coding: utf-8 -*-
"""task4_beans 离线回归：截图驱动版，不连真机。

分层：
  A 组用真机 PNG 夹具测像素识别（detect_buttons / detect_earn_button /
      template_diff / classify / 等比缩放）。
  B 组 patch screencap+classify 测流程逻辑（打开弹窗 / 主循环 / 返回链 / 刹车）。
  C 组测原生页入口（金刚区 / 全部频道兜底）与 run() 异常分支。
  D 组测模板资产缺失时的失败关闭（不误点、不假完成）。

真机夹具来自 2026-11-11 22:00 实跑现场。
"""
import io
import os
import sys
import threading
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils.jd_ui import JDUI
import modules.task4_beans as t4
from modules.task4_beans import Task4Beans

ROOT = os.path.dirname(os.path.abspath(__file__))
ACT = os.path.join(ROOT, "debug_shots", "task4_beans_page_215228.png")
DIALOG = os.path.join(ROOT, "debug_shots", "task4_dialog_probe.png")
BROWSE = os.path.join(ROOT, "debug_shots", "_probe_in_browse.png")


# ---------------- 假对象 ----------------
class FakeLog(object):
    def __init__(self):
        self.logs = []
        self.steps = []
        self.done_msg = None
        self.error_msg = None

    def write_log(self, msg, level="INFO"):
        self.logs.append((level, msg))

    def write_step(self, cur, total, label):
        self.steps.append((cur, total, label))

    def done(self, msg="完成"):
        self.done_msg = msg

    def error(self, msg="出错"):
        self.error_msg = msg


class FakeUI(object):
    def __init__(self, home_pages=None):
        self.W, self.H = 1080, 2340
        self.home_pages = list(home_pages or [HOME_P1])
        self.page_idx = 0
        self.phase = "home"
        self.taps = []
        self.swipes = []
        self.scrolls = 0
        self.snapshots = []
        self.sleeps = []
        self.invalidates = 0
        self.all_channels_calls = 0
        self.goto_home_calls = 0
        self._restarted = False
        self.parse_bounds = JDUI.parse_bounds

    def say(self, msg, level="INFO"):
        pass

    def restart_to_home(self, wait=6):
        self.phase = "home"; self.page_idx = 0
        return True

    def ensure_kingkong_visible(self, max_swipes=3):
        return True

    def source(self, fresh=False):
        if self.phase == "channels":
            return CHANNELS_XML
        if self.phase == "games":
            return GAMES_XML
        return self.home_pages[min(self.page_idx, len(self.home_pages) - 1)]

    def nodes(self, xml=None):
        src = xml if xml is not None else self.source()
        out = []
        try:
            root = ET.fromstring(src.encode("utf-8"))
        except Exception:
            return out
        for n in root.iter():
            b = self.parse_bounds(n.get("bounds"))
            if not b:
                continue
            out.append({"text": (n.get("text") or "").strip(),
                        "desc": (n.get("content-desc") or "").strip(),
                        "bounds": b,
                        "clickable": n.get("clickable") == "true"})
        return out

    def visible(self, node, top=0, bottom_margin=90):
        x1, y1, x2, y2 = node["bounds"]
        return 0 <= x1 < x2 <= self.W and top <= y1 < y2 <= self.H - bottom_margin

    def center(self, node):
        x1, y1, x2, y2 = node["bounds"]
        return ((x1 + x2) // 2, (y1 + y2) // 2)

    def swipe_kingkong(self, direction="left", pause=1.5):
        self.swipes.append(direction); self.page_idx += 1

    def to_all_channels(self):
        self.all_channels_calls += 1; self.phase = "channels"
        return True

    def tap(self, xy, pause=1.5):
        self.taps.append(tuple(xy))
        if self.phase == "channels":
            self.phase = "games"
        elif self.phase == "games":
            self.phase = "activity"

    def adb_swipe(self, x1, y1, x2, y2, duration=300):
        self.scrolls += 1

    def sx(self, x):
        return int(round(x * self.W / 1080.0))

    def sy(self, y):
        return int(round(y * self.H / 2340.0))

    def invalidate(self):
        self.invalidates += 1

    def goto_home(self):
        self.goto_home_calls += 1; self.phase = "home"; self.page_idx = 0
        return True

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        return True

    def snapshot(self, label="state"):
        self.snapshots.append(label)


class FakeJDUI(object):
    made = None
    last = None

    def __init__(self, drv, log, stop):
        self.ui = FakeUI(FakeJDUI.made)
        self.W, self.H = 1080, 2340
        self.log = log; self.stop = stop
        FakeJDUI.last = self
        for name in ("say", "restart_to_home", "ensure_kingkong_visible", "source",
                     "nodes", "visible", "center", "swipe_kingkong", "to_all_channels",
                     "tap", "adb_swipe", "sx", "sy", "invalidate", "goto_home",
                     "sleep", "snapshot", "parse_bounds"):
            setattr(self, name, getattr(self.ui, name))


# ---------------- XML 夹具（原生页入口） ----------------
HOME_P1 = """<?xml version="1.0" encoding="UTF-8"?>
<hierarchy rotation="0">
  <node content-desc="秒杀" clickable="true" bounds="[0,892][190,1055]"/>
  <node content-desc="外卖" clickable="true" bounds="[760,892][950,1055]"/>
</hierarchy>"""
HOME_P2 = """<?xml version="1.0" encoding="UTF-8"?>
<hierarchy rotation="0">
  <node text="种豆得豆" bounds="[554,970][744,1010]"/>
  <node content-desc="种豆得豆" clickable="true" bounds="[554,892][744,1055]"/>
</hierarchy>"""
CHANNELS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<hierarchy rotation="0">
  <node text="全部频道" bounds="[434,126][646,206]"/>
  <node text="互动游戏" clickable="true" bounds="[585,690][759,830]"/>
</hierarchy>"""
GAMES_XML = """<?xml version="1.0" encoding="UTF-8"?>
<hierarchy rotation="0">
  <node text="互动游戏" clickable="true" bounds="[585,231][759,371]"/>
  <node clickable="true" bounds="[60,500][250,700]"/>
  <node text="种豆得豆" clickable="false" bounds="[77,583][231,629]"/>
</hierarchy>"""
CHANNELS_NO_TAB = """<hierarchy><node text="全部频道" bounds="[434,126][646,206]"/></hierarchy>"""
GAMES_NO_BEAN = """<hierarchy><node text="互动游戏" clickable="true" bounds="[585,231][759,371]"/></hierarchy>"""

# 假 bbox：与真机弹窗一致（第 3 行 y=1542 是【去完成】，故意不在 browse 列表里）
B1 = (840, 1092, 1024, 1170)
B2 = (840, 1316, 1024, 1394)
B3 = (840, 1766, 1024, 1844)
B4 = (840, 1990, 1024, 2070)
B5 = (840, 2216, 1024, 2294)
OTHER_BTN = (840, 1542, 1024, 1620)   # 【去完成】
EARN_BBOX = (885, 1481, 1056, 1631)


# ---------------- 用例框架 ----------------
CASES = []


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn
    return deco


_PATCHED = ("screencap", "adb_back", "classify", "load_template", "MAX_SCROLLS",
            "MAX_BROWSE_TASKS", "RETURN_MAX_STEPS", "MAX_NO_PROGRESS",
            "MAX_REENTERS", "BROWSE_SECONDS")
ORIG = dict((n, getattr(t4, n)) for n in _PATCHED)
ORIG["JDUI"] = t4.JDUI
ORIG["_execute"] = Task4Beans._execute
ORIG["_return_to_dialog"] = Task4Beans._return_to_dialog


def reset():
    for n, v in ORIG.items():
        if n in ("_execute", "_return_to_dialog"):
            setattr(Task4Beans, n, v)
        else:
            setattr(t4, n, v)


def fake_screencap(seq):
    it = iter(seq)
    return lambda tag=None: next(it, "")


def fake_classify(seq):
    it = iter(seq)
    return lambda path, tpl=None: next(it, ("other", [], None))


# ================= A 组：真实 PNG 像素识别 =================
@case("A1 detect_buttons 弹窗检出 6 个橙色按钮")
def t_a1():
    bs = t4.detect_buttons(DIALOG)
    assert len(bs) == 6, bs
    assert bs[0][1] >= 1080 and bs[-1][1] >= 2200, bs


@case("A2 detect_buttons 活动页 0 个（不误判）")
def t_a2():
    assert t4.detect_buttons(ACT) == []


@case("A3 detect_earn_button 活动页命中【赚收获值】")
def t_a3():
    b = t4.detect_earn_button(ACT)
    assert b is not None
    assert abs(b[0] - 885) <= 6 and abs(b[1] - 1481) <= 6, b
    assert abs(b[2] - 1056) <= 6 and abs(b[3] - 1631) <= 6, b


@case("A4 detect_earn_button 弹窗返回 None")
def t_a4():
    assert t4.detect_earn_button(DIALOG) is None


@case("A5 template_diff 区分【逛一逛】与【去完成】")
def t_a5():
    from PIL import Image
    tpl = t4.load_template()
    assert tpl is not None
    g = Image.open(DIALOG).convert("L")
    good = [t4.template_diff(g, b, tpl) for b in (B1, B2, B3, B4, B5)]
    bad = t4.template_diff(g, OTHER_BTN, tpl)
    assert max(good) <= t4.TEMPLATE_MAX_DIFF, good
    assert bad > t4.TEMPLATE_MAX_DIFF, (bad, good)
    assert bad - max(good) > 3.5, (bad, good)


@case("A6 classify 活动页 -> activity + earn")
def t_a6():
    state, browse, earn = t4.classify(ACT)
    assert state == "activity", state
    assert browse == [] and earn is not None


@case("A7 classify 弹窗 -> dialog + 5 逛一逛")
def t_a7():
    state, browse, earn = t4.classify(DIALOG)
    assert state == "dialog", state
    assert len(browse) == 5, browse
    ys = [b[1] for b in browse]
    assert 1542 not in ys and 1541 not in ys, ys   # 【去完成】被排除
    assert earn is None


@case("A8 classify 浏览页 -> other")
def t_a8():
    state, browse, earn = t4.classify(BROWSE)
    assert state == "other", state
    assert browse == []


@case("A9 classify 空路径 / 坏文件不炸")
def t_a9():
    assert t4.classify("")[0] == "other"
    assert t4.classify("no_such_file.png")[0] == "other"
    assert t4.detect_buttons("no_such_file.png") == []
    assert t4.detect_earn_button("no_such_file.png") is None


@case("A10 模板缺失时仍靠 >=2 按钮判 dialog，不点任何东西")
def t_a10():
    t4.load_template = lambda: None
    state, browse, earn = t4.classify(DIALOG, tpl=None)
    assert state == "dialog" and browse == [], (state, browse)


@case("A11 非基准分辨率等比缩放后仍检出按钮")
def t_a11():
    from PIL import Image
    tmp = os.path.join(ROOT, "_test_scaled.png")
    im = Image.open(DIALOG).resize((720, 1560))
    im.save(tmp)
    try:
        bs = t4.detect_buttons(tmp)
        assert len(bs) == 6, bs
        # 原 y=1092 -> 缩放后 728（乘 2/3）
        assert abs(bs[0][1] - 728) <= 12, bs[0]
        state, browse, earn = t4.classify(tmp)
        assert state == "dialog" and len(browse) == 5, (state, len(browse))
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


@case("A12 _key 位置指纹 10px 容差")
def t_a12():
    assert t4._key((840, 1092, 1024, 1170)) == t4._key((843, 1095, 1024, 1170))
    assert t4._key((840, 1092, 1024, 1170)) != t4._key((840, 1316, 1024, 1394))


@case("A13 _center 取 bbox 中心")
def t_a13():
    assert t4._center((840, 1092, 1024, 1170)) == (932, 1131)


# ================= B 组：流程逻辑 =================
@case("B1 活动页 -> 点黄色【赚收获值】-> 打开弹窗")
def t_b1():
    t4.screencap = fake_screencap([ACT, DIALOG])
    ui = FakeUI(); log = FakeLog(); ev = threading.Event()
    assert Task4Beans()._open_task_dialog(ui, log, ev) is True
    assert ui.taps and len(ui.taps) == 1, ui.taps
    x, y = ui.taps[0]
    assert abs(x - 970) <= 6 and abs(y - 1556) <= 6, (x, y)


@case("B2 黄色按钮识别失败 -> 标定坐标兜底")
def t_b2():
    t4.screencap = fake_screencap([BROWSE, BROWSE, DIALOG])
    ui = FakeUI(); log = FakeLog(); ev = threading.Event()
    assert Task4Beans()._open_task_dialog(ui, log, ev) is True
    x, y = ui.taps[-1]
    assert (x, y) == (ui.sx(971), ui.sy(1556)), (x, y)
    assert any("标定坐标" in m for _, m in log.logs)


@case("B3 已在任务弹窗 -> 直接返回，不点任何按钮")
def t_b3():
    t4.screencap = fake_screencap([DIALOG])
    ui = FakeUI(); log = FakeLog()
    assert Task4Beans()._open_task_dialog(ui, log, threading.Event()) is True
    assert ui.taps == [], ui.taps


@case("B4 三次都打不开弹窗 -> False")
def t_b4():
    t4.screencap = fake_screencap([BROWSE] * 8)
    ui = FakeUI(); log = FakeLog()
    assert Task4Beans()._open_task_dialog(ui, log, threading.Event()) is False


@case("B5 主循环做完 2 个任务，无未做任务后终止")
def t_b5():
    t4.MAX_SCROLLS = 0
    t4.screencap = lambda tag=None: "fake.png"
    t4.classify = fake_classify([
        ("dialog", [B1, B2], None),
        ("dialog", [B2], None),
        ("dialog", [], None),
    ])
    Task4Beans._return_to_dialog = lambda self, ui, log, stop, tpl: "ok"
    ui = FakeUI(); log = FakeLog()
    summary, done = Task4Beans()._browse_loop(ui, log, threading.Event())
    assert done == 2, (done, summary)
    assert len(ui.taps) == 2, ui.taps
    assert "浏览任务 2 个" in summary, summary


@case("B6 只点【逛一逛】，不点【去完成】所在行")
def t_b6():
    t4.MAX_SCROLLS = 0
    t4.screencap = lambda tag=None: "fake.png"
    t4.classify = fake_classify([("dialog", [B1, B2, B3, B4, B5], None)] * 8)
    Task4Beans._return_to_dialog = lambda self, ui, log, stop, tpl: "ok"
    ui = FakeUI(); log = FakeLog()
    Task4Beans()._browse_loop(ui, log, threading.Event())
    for (x, y) in ui.taps:
        assert abs(y - t4._center(OTHER_BTN)[1]) > 20, (x, y)


@case("B7 没有逛一逛时下滑，超过上限后结束")
def t_b7():
    t4.MAX_SCROLLS = 2
    t4.screencap = lambda tag=None: "fake.png"
    t4.classify = lambda path, tpl=None: ("dialog", [], None)
    ui = FakeUI(); log = FakeLog()
    summary, done = Task4Beans()._browse_loop(ui, log, threading.Event())
    assert done == 0 and ui.scrolls == 2, (done, ui.scrolls)


@case("B8 stop_event 在主循环立即中断")
def t_b8():
    t4.screencap = lambda tag=None: "fake.png"
    t4.classify = lambda path, tpl=None: ("dialog", [B1], None)
    ui = FakeUI(); log = FakeLog(); ev = threading.Event(); ev.set()
    summary, done = Task4Beans()._browse_loop(ui, log, ev)
    assert summary == "已停止" and done == 0 and ui.taps == []


@case("B9 达到 MAX_BROWSE_TASKS 刹车")
def t_b9():
    t4.MAX_BROWSE_TASKS = 2
    t4.MAX_SCROLLS = 0
    t4.MAX_NO_PROGRESS = 99
    t4.screencap = lambda tag=None: "fake.png"
    boxes = [B1, B2, B3, B4, B5]
    t4.classify = fake_classify([("dialog", [b], None) for b in boxes])
    Task4Beans._return_to_dialog = lambda self, ui, log, stop, tpl: "ok"
    ui = FakeUI(); log = FakeLog()
    summary, done = Task4Beans()._browse_loop(ui, log, threading.Event())
    assert done == 2 and "上限" in summary, (done, summary)


@case("B10 返回链：多步 back 后回到弹窗")
def t_b10():
    t4.screencap = lambda tag=None: "fake.png"
    t4.classify = fake_classify([("other", [], None)] * 3 + [("dialog", [], None)])
    backs = []
    t4.adb_back = lambda: backs.append(1) or True
    ui = FakeUI(); log = FakeLog()
    res = Task4Beans()._return_to_dialog(ui, log, threading.Event(), None)
    assert res == "ok", res
    assert len(backs) == 3, len(backs)


@case("B11 返回链超限 -> fail")
def t_b11():
    t4.RETURN_MAX_STEPS = 3
    t4.screencap = lambda tag=None: "fake.png"
    t4.classify = lambda path, tpl=None: ("other", [], None)
    backs = []
    t4.adb_back = lambda: backs.append(1) or True
    ui = FakeLog()
    res = Task4Beans()._return_to_dialog(FakeUI(), ui, threading.Event(), None)
    assert res == "fail" and len(backs) == 3, (res, len(backs))


@case("B12 面板丢失（activity）触发重进")
def t_b12():
    t4.screencap = lambda tag=None: "fake.png"
    t4.classify = lambda path, tpl=None: ("activity", [], EARN_BBOX)
    t4.MAX_SCROLLS = 0
    t4.MAX_BROWSE_TASKS = 1
    calls = []
    Task4Beans._return_to_dialog = lambda self, ui, log, stop, tpl: "fail"
    Task4Beans._reenter = lambda self, ui, log, stop: calls.append(1) or False
    ui = FakeUI(); log = FakeLog()
    Task4Beans()._browse_loop(ui, log, threading.Event())
    assert len(calls) == 1, calls


# ================= C 组：原生页入口 =================
@case("C1 金刚区第一页未命中")
def t_c1():
    assert t4.find_bean_icon(FakeUI([HOME_P1]), HOME_P1) is None


@case("C2 左滑后第二页命中 (554,892)-(744,1055)")
def t_c2():
    assert t4.find_bean_icon(FakeUI([HOME_P1, HOME_P2]), HOME_P2) == (554, 892, 744, 1055)


@case("C3 纯文字标签高度不足不算格子")
def t_c3():
    xml = '<hierarchy><node content-desc="种豆得豆" bounds="[554,970][744,1000]"/></hierarchy>'
    assert t4.find_bean_icon(FakeUI(), xml) is None


@case("C4 祖先带有效 bounds 时向上取值")
def t_c4():
    xml = ('<hierarchy><node content-desc="种豆得豆" bounds="[554,892][744,1055]">'
           '<node content-desc="种豆得豆" bounds="[0,0][0,0]"/></node></hierarchy>')
    assert t4.find_bean_icon(FakeUI(), xml) == (554, 892, 744, 1055)


@case("C5 屏外/无效 bounds 被排除")
def t_c5():
    xml = '<hierarchy><node content-desc="种豆得豆" bounds="[77,3418][231,2341]"/></hierarchy>'
    assert t4.find_bean_icon(FakeUI(), xml) is None


@case("C6 金刚区直达命中后不走【全部频道】")
def t_c6():
    ui = FakeUI([HOME_P2]); log = FakeLog()
    assert Task4Beans()._open_activity(ui, log, threading.Event()) is True
    assert ui.all_channels_calls == 0
    assert (649, 973) in ui.taps, ui.taps


@case("C7 金刚区找不到 -> 全部频道-互动游戏-种豆得豆")
def t_c7():
    ui = FakeUI([HOME_P1, HOME_P1, HOME_P1]); log = FakeLog()
    assert Task4Beans()._open_activity(ui, log, threading.Event()) is True
    assert ui.all_channels_calls == 1, ui.all_channels_calls
    assert (672, 760) in ui.taps and (155, 600) in ui.taps, ui.taps


@case("C8 频道页缺【互动游戏】tab -> 明确报错")
def t_c8():
    ui = FakeUI([HOME_P1]); log = FakeLog()
    ui.phase = "channels"
    ui.nodes = lambda xml=None: []
    try:
        Task4Beans()._open_via_channels(ui, log)
        assert False, "should raise"
    except RuntimeError as e:
        assert "互动游戏" in str(e)


@case("C9 互动游戏分区缺【种豆得豆】-> 明确报错")
def t_c9():
    ui = FakeUI([HOME_P1]); log = FakeLog()
    seq = [[{"text": "互动游戏", "clickable": True, "bounds": (585, 690, 759, 830)}], [], []]
    it = iter(seq)
    ui.nodes = lambda xml=None: next(it, [])
    try:
        Task4Beans()._open_via_channels(ui, log)
        assert False, "should raise"
    except RuntimeError as e:
        assert "种豆得豆" in str(e)


@case("C10 run() 异常分支写 error 且截图")
def t_c10():
    FakeJDUI.made = [HOME_P1]
    t4.JDUI = FakeJDUI
    t4.driver.get_driver = lambda: object()

    def boom(self, ui, log, stop):
        raise RuntimeError("boom-for-test")

    Task4Beans._execute = boom
    try:
        log = FakeLog()
        Task4Beans().run(log, threading.Event())
        assert log.error_msg and "boom-for-test" in log.error_msg, log.error_msg
        assert "task4_beans_error" in FakeJDUI.last.ui.snapshots
        assert any(lv == "ERROR" for lv, _ in log.logs)
        assert log.done_msg is None
    finally:
        t4.JDUI = ORIG["JDUI"]
        Task4Beans._execute = ORIG["_execute"]


@case('D1 模板缺失时 _execute 明确报错，不产生假完成')
def t_d1():
    t4.load_template = lambda: None
    try:
        Task4Beans()._execute(FakeUI(), FakeLog(), threading.Event())
    except RuntimeError as e:
        assert '模板' in str(e), str(e)
    else:
        raise AssertionError('missing template should raise')


@case('D2 模板缺失时 _browse_loop 不点任何按钮')
def t_d2():
    t4.load_template = lambda: None
    ui = FakeUI()
    try:
        Task4Beans()._browse_loop(ui, FakeLog(), threading.Event())
    except RuntimeError:
        pass
    else:
        raise AssertionError('missing template should raise')
    assert ui.taps == [], ui.taps


@case("B13 浏览停留统一 X+4 秒（X=5 -> 9s）")
def t_b13():
    assert t4.BROWSE_EXTRA == 4, t4.BROWSE_EXTRA
    assert t4.BROWSE_SECONDS == t4.BROWSE_X + t4.BROWSE_EXTRA, t4.BROWSE_SECONDS
    assert t4.BROWSE_SECONDS == 9, t4.BROWSE_SECONDS
    t4.MAX_SCROLLS = 0
    t4.MAX_NO_PROGRESS = 99
    t4.MAX_BROWSE_TASKS = 1
    t4.screencap = lambda tag=None: "fake.png"
    t4.classify = fake_classify([("dialog", [B1], None), ("dialog", [], None)])
    Task4Beans._return_to_dialog = lambda self, ui, log, stop, tpl: "ok"
    ui = FakeUI()
    log = FakeLog()
    summary, done = Task4Beans()._browse_loop(ui, log, threading.Event())
    assert done == 1, (done, summary)
    assert t4.BROWSE_SECONDS in ui.sleeps, ui.sleeps
    joined = u"\n".join(m for _lv, m in log.logs)
    assert u"停留 9 秒" in joined, joined


# 真机 _t4_dialog.xml（2026-11-12）里的副标题行，按钮 cy 见 B1..B5
ROWS_X = [
    {"text": u"去完成", "bounds": (838, 1540, 1025, 1622)},
    {"text": u"浏览页面15s可得+10", "bounds": (189, 1589, 770, 1639)},   # 按钮 cy 1581
    {"text": u"逛一逛", "bounds": (838, 1762, 1025, 1848)},
    {"text": u"浏览页面15s可得+10", "bounds": (189, 1815, 770, 1864)},   # 按钮 cy 1805
    {"text": u"去完成", "bounds": (838, 2213, 1025, 2296)},
    {"text": u"浏览页面5s可得+20", "bounds": (189, 2263, 770, 2312)},    # 按钮 cy 2255
]


@case("B14 逐行读 X：逛一逛那行要求 15s -> 停留 19s")
def t_b14():
    assert t4.browse_seconds(5) == 9
    assert t4.browse_seconds(15) == 19
    # 按按钮 cy 配对，三行各自读到自己的 X
    assert t4.read_row_seconds(ROWS_X, 1580) == 15
    assert t4.read_row_seconds(ROWS_X, 1805) == 15
    assert t4.read_row_seconds(ROWS_X, 2255) == 5
    # 没写浏览文案的行（去邀请 / 去下单）读不到，不能串到隔壁行
    assert t4.read_row_seconds(ROWS_X, 1131) is None
    assert t4.read_row_seconds(ROWS_X, 1355) is None
    assert t4.read_row_seconds(ROWS_X, 2030) is None

    t4.MAX_SCROLLS = 0
    t4.MAX_NO_PROGRESS = 99
    t4.MAX_BROWSE_TASKS = 1
    t4.screencap = lambda tag=None: "fake.png"
    t4.classify = fake_classify([("dialog", [B3], None), ("dialog", [], None)])
    Task4Beans._return_to_dialog = lambda self, ui, log, stop, tpl: "ok"
    ui = FakeUI()
    ui.nodes = lambda xml=None: ROWS_X
    log = FakeLog()
    summary, done = Task4Beans()._browse_loop(ui, log, threading.Event())
    assert done == 1, (done, summary)
    assert 19 in ui.sleeps, ui.sleeps
    assert 9 not in ui.sleeps, ui.sleeps          # 绝不能只停 9s
    joined = u"\n".join(m for _lv, m in log.logs)
    assert u"浏览 15s" in joined, joined
    assert u"停留 19 秒" in joined, joined


@case("B15 读不到 X 时退回默认 5s（停留 9s）")
def t_b15():
    t4.MAX_SCROLLS = 0
    t4.MAX_NO_PROGRESS = 99
    t4.MAX_BROWSE_TASKS = 1
    t4.screencap = lambda tag=None: "fake.png"
    t4.classify = fake_classify([("dialog", [B3], None), ("dialog", [], None)])
    Task4Beans._return_to_dialog = lambda self, ui, log, stop, tpl: "ok"
    ui = FakeUI()
    ui.nodes = lambda xml=None: []                # XML 空
    log = FakeLog()
    summary, done = Task4Beans()._browse_loop(ui, log, threading.Event())
    assert done == 1 and 9 in ui.sleeps, (done, ui.sleeps)
    joined = u"\n".join(m for _lv, m in log.logs)
    assert u"默认 X=5" in joined, joined


@case("B16 截图判非弹窗但 XML 弹窗还在 -> 一次 back 都不打")
def t_b16():
    assert t4.looks_like_dialog_xml(ROWS_X) is True
    assert t4.looks_like_dialog_xml([]) is False
    assert t4.looks_like_dialog_xml([{"text": u"去完成", "bounds": (1, 1, 2, 2)}]) is False

    t4.MAX_SCROLLS = 0
    t4.screencap = lambda tag=None: "fake.png"
    t4.classify = lambda path, tpl=None: ("other", [], None)
    backs = []
    t4.adb_back = lambda: backs.append(1) or True
    Task4Beans._reenter = lambda self, ui, log, stop: False
    ui = FakeUI()
    ui.nodes = lambda xml=None: ROWS_X
    log = FakeLog()
    summary, done = Task4Beans()._browse_loop(ui, log, threading.Event())
    assert backs == [], backs
    assert done == 0, done
    joined = u"\n".join(m for _lv, m in log.logs)
    assert u"XML 里弹窗还在" in joined, joined


def main():
    passed = failed = 0
    for name, fn in CASES:
        reset()
        try:
            fn()
            print("  PASS  %s" % name)
            passed += 1
        except Exception as e:
            import traceback
            print("  FAIL  %s -> %s: %s" % (name, type(e).__name__, e))
            traceback.print_exc()
            failed += 1
    print("\n%d passed, %d failed, %d total" % (passed, failed, len(CASES)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
