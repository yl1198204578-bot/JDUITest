# -*- coding: utf-8 -*-
"""看病买药 模块离线回归（不连手机、不连 Appium）。

覆盖：
  A. X+4 停留换算
  B. 真机夹具 _fixture_med_panel.xml 上的任务行配对
  C. 合成节点配对细节（含「背后秒杀页文案撞车」回归）
  D. 页面判定 is_medical_page / is_wp_page / has_task_panel
  E. pick_target 安全区（含【领红包】浮层下界）
  F. find_sign_in / find_more_bean（【领更多京豆】必须完全相等）
  G. clickable_ancestor（【领更多京豆】【看病买药】都不是可点文字）
  H. _reveal_tab（子 tab 横向滑进屏幕）
  I. _tap_label / _tap_node
  J. 入口链路 _open_medical（金刚区第1页 / 第2页 / 全部频道兜底 / 点歪）
  K. _open_wp（点【签到领京豆】进秒杀页）
  L. _open_panel（点【领更多京豆】开弹层）
  M. 任务循环（完成判定、滚动、读失败、弹层丢失轻量重开）
  N. _recover_panel
  O. stop_event
  P. run() 整体

夹具（真机 1080x2340，2026-11-12 抓的）：
  _fixture_med_home.xml      首页金刚区第1页（desc='看病买药' 在 (194,440,388,601)）
  _fixture_med_kk2.xml       金刚区第2页（看病买药 (435,440,651,601) + 全部频道）
  _fixture_med_allchan0.xml  全部频道-发现好物（医疗保健子 tab 未渲染）
  _fixture_med_allchan1.xml  全部频道-发现好物（医疗保健滑进屏幕 (533,368,753,470)）
  _fixture_med_page.xml      看病买药页（【签到领京豆】(73,1523,233,1567)）
  _fixture_med_wp.xml        全场秒杀·天天低价页（【领更多京豆】(712,434,946,492)）
  _fixture_med_panel.xml     做任务赚更多京豆弹层（5 个【浏览5s】可做任务）
  _fixture_med_done.xml      同一个弹层，任务全做完（只剩 已领取 + 去领取 行）
"""
import io
import re
import sys
import threading
import xml.etree.ElementTree as ET

sys.path.insert(0, ".")

import modules.task9_medical as MOD
from modules.task9_medical import (
    Task9Medical, browse_seconds, parse_task_rows, pick_target, has_task_panel,
    is_medical_page, is_wp_page, find_sign_in, find_more_bean, clickable_ancestor,
    row_sig, BROWSE_EXTRA, SAFE_TOP, SAFE_BOTTOM, MAX_REENTER, PANEL_MARK,
    MED_DESC, MED_TAB, FIND_GOODS, ALL_CHANNEL, MORE_BEAN, SIGN_IN, WP_MARK,
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


# ---------------------------------------------------------------- 夹具工具
_BOUNDS_RE = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")


def load(path):
    """解析成 jd_ui.nodes() 同样的结构（保留退化 bounds，交给业务过滤）。"""
    s = io.open(path, encoding="utf-8", errors="replace").read()
    root = ET.fromstring(s.encode("utf-8"))
    out = []
    for n in root.iter():
        m = _BOUNDS_RE.match(n.get("bounds") or "")
        if not m:
            continue
        out.append({
            "text": (n.get("text") or "").strip(),
            "desc": (n.get("content-desc") or "").strip(),
            "bounds": tuple(int(x) for x in m.groups()),
            "clickable": n.get("clickable") == "true",
            "class": (n.get("class") or "").rsplit(".", 1)[-1],
        })
    return out


def nd(text, x1, y1, x2, y2, clickable=False, desc=""):
    return {"text": text, "desc": desc, "bounds": (x1, y1, x2, y2),
            "clickable": clickable, "class": "TextView"}


def row(title, secs=5, btn=u"去完成", y=874):
    """按真机行结构造一行（看病买药弹层）。

    真机：标题 [181,874][599,935]，副标题【浏览5s】[181,935][291,979]，
    奖励「1」[341,935][363,979] + 「京豆」[360,935][434,979]，
    按钮 [863,882][1036,973]。
    """
    return [
        nd(title, 181, y, 599, y + 61),
        nd(u"浏览%ds" % secs, 181, y + 61, 291, y + 105),
        nd(u"1", 341, y + 61, 363, y + 105),
        nd(u"京豆", 360, y + 61, 434, y + 105),
        nd(btn, 863, y + 8, 1036, y + 99, clickable=True),
    ]


def screen(*rows):
    out = []
    for r in rows:
        out.extend(r)
    return out


MARK = [nd(PANEL_MARK, 33, 734, 451, 800),
        nd(u"关闭弹窗", 998, 695, 1047, 745, clickable=True)]
# 「页面在、但弹层没了」的真实样子（秒杀页）
NO_PANEL = [nd(u"我的签到日历", 794, 321, 1006, 365),
            nd(u"领更多京豆", 712, 434, 946, 492),
            nd(u"领更多京豆", 822, 401, 965, 530, clickable=True)]


class Log(object):
    def __init__(self):
        self.lines = []

    def write_log(self, msg, level="INFO"):
        self.lines.append((level, msg))

    def done(self, msg=""):
        self.lines.append(("DONE", msg))

    def error(self, msg):
        self.lines.append(("ERROR", msg))

    def text(self):
        return "\n".join("[%s] %s" % (lv, m) for lv, m in self.lines)


class FakeUI(object):
    W = 1080
    H = 2340

    def __init__(self):
        self.taps = []
        self.swipes = []
        self.backs = 0
        self.sleeps = []
        self.invalidated = 0
        self.home_calls = 0
        self.restart_calls = 0
        self.kk_swipes = []

    def sx(self, x):
        return x

    def sy(self, y):
        return y

    def nodes(self):
        return []

    def invalidate(self):
        self.invalidated += 1

    def sleep(self, s):
        self.sleeps.append(s)
        return True

    def back(self, pause=2.0):
        self.backs += 1

    def adb_tap(self, pos, pause=1.5):
        self.taps.append(pos)

    def tap(self, pos, pause=1.5):
        self.taps.append(pos)

    def adb_swipe(self, x1, y1, x2, y2, duration=300):
        self.swipes.append((x1, y1, x2, y2))

    def center(self, n):
        b = n["bounds"]
        return ((b[0] + b[2]) // 2, (b[1] + b[3]) // 2)

    def goto_home(self):
        self.home_calls += 1
        return True

    def restart_to_home(self, wait=6):
        self.restart_calls += 1
        return True

    def ensure_kingkong_visible(self, max_swipes=3):
        return True

    def swipe_kingkong(self, direction="left", pause=1.5):
        self.kk_swipes.append(direction)

    def _stable_kingkong_icon(self, desc, tries=4):
        return None, False


# ================================================================ A
print("\n--- A. X+4 停留 ---")
check("A1 5s -> 9s", browse_seconds(5) == 9)
check("A2 10s -> 14s", browse_seconds(10) == 14)
check("A3 0s -> 4s", browse_seconds(0) == 4)
check("A4 BROWSE_EXTRA=4", BROWSE_EXTRA == 4)

# ================================================================ B
print("\n--- B. 真机夹具 _fixture_med_panel.xml ---")
PN = load("_fixture_med_panel.xml")
rows = parse_task_rows(PN)
check("B1 弹层识别", has_task_panel(PN))
check("B2 配出 5 行可做任务", len(rows) == 5, "got %d" % len(rows))
titles = [r["title"] for r in rows]
check("B3 标题正确",
      titles == [u"天天逛特价2元也包邮", u"去京喜自营频道签到", u"看视频赚现金",
                 u"加营养师得200京豆", u"逛外卖频道"],
      "got %s" % titles)
check("B4 secs 都是 5", all(r["secs"] == 5 for r in rows))
check("B5 按钮都是去完成", all(r["btn"] == u"去完成" for r in rows))
check("B6 按 y 升序", [r["cy"] for r in rows] == sorted(r["cy"] for r in rows))
check("B7 【去领取】行不算任务", all(u"去领5元无门槛券" not in t for t in titles)
      and all(u"东东农场" not in t for t in titles), "got %s" % titles)
check("B8 【已领取】行不算任务", all(u"首页来访奖励" not in t for t in titles))
check("B9 背后秒杀页文案没串进标题",
      all(u"条评价" not in t and u"已售" not in t and u"京豆最多抵" not in t
          for t in titles), "got %s" % titles)
check("B10 row_sig 稳定",
      row_sig(rows) == row_sig(parse_task_rows(load("_fixture_med_panel.xml"))))
check("B11 按钮都在 x>=700",
      all(r["cx"] >= 700 for r in rows), "got %s" % [r["cx"] for r in rows])

# ================================================================ C
print("\n--- C. 合成节点配对 ---")
r1 = parse_task_rows(screen(row(u"天天逛特价2元也包邮", y=874)))
check("C1 单行配出", len(r1) == 1)
check("C2 标题", r1 and r1[0]["title"] == u"天天逛特价2元也包邮")
check("C3 按钮中心 (949,927)",
      r1 and (r1[0]["cx"], r1[0]["cy"]) == (949, 927),
      "got %s" % ((r1[0]["cx"], r1[0]["cy"]) if r1 else None,))

only_btn = [nd(u"去完成", 863, 882, 1036, 973, clickable=True)]
check("C4 没有【浏览Ns】不算任务行", parse_task_rows(only_btn) == [])

qu_ling = [nd(u"去东东农场免费领水果", 181, 1432, 618, 1496),
           nd(u"去领取", 181, 1496, 291, 1537),
           nd(u"去完成", 863, 1443, 1036, 1534, clickable=True)]
check("C5 【去领取】行不算", parse_task_rows(qu_ling) == [])

degen = [nd(u"天天逛特价2元也包邮", 181, 2431, 599, 2341),
         nd(u"浏览5s", 181, 2431, 291, 2341),
         nd(u"去完成", 863, 2431, 1036, 2341, clickable=True)]
check("C6 退化 bounds 被过滤", parse_task_rows(degen) == [])

left_btn = screen(row(u"逛外卖频道", y=1993))
left_btn.append(nd(u"去完成", 200, 2001, 380, 2092, clickable=True))
r2 = parse_task_rows(left_btn)
check("C7 左侧【去完成】不算", len(r2) == 1 and r2[0]["cx"] == 949)

# 真机回归：弹层背后秒杀页的商品文案 y 正好撞在任务行上
crash = [
    nd(u"天天逛特价2元也包邮", 181, 874, 599, 935),        # 标题 x1=181 cy=904
    nd(u"浏览5s", 181, 935, 291, 979),
    nd(u"1", 341, 935, 363, 979),
    nd(u"京豆", 360, 935, 434, 979),
    nd(u"500+条评价", 489, 904, 676, 968),                 # 背后商品文案 cy=936
    nd(u"京豆最多抵1.18元", 407, 900, 654, 944),
    nd(u"去完成", 863, 882, 1036, 973, clickable=True),    # cy=927
]
r3 = parse_task_rows(crash)
check("C8 背后商品文案不抢标题", r3 and r3[0]["title"] == u"天天逛特价2元也包邮",
      "got %s" % ([r["title"] for r in r3],))
check("C8b 撞车时仍然只配出 1 行", len(r3) == 1, "got %d" % len(r3))

prog = [nd(u"去领5元无门槛券(1/2)", 181, 1061, 610, 1122),
        nd(u"去领取", 181, 1122, 291, 1163),
        nd(u"500健康能量", 338, 1122, 560, 1163),
        nd(u"去完成", 863, 1069, 1036, 1160, clickable=True)]
check("C9 带 (N/M) 的行标题优先", parse_task_rows(prog) == [])

check("C10 半角括号也能识别",
      len(parse_task_rows([nd(u"某任务(0/1)", 181, 874, 599, 935),
                           nd(u"浏览5s", 181, 935, 291, 979),
                           nd(u"去完成", 863, 882, 1036, 973, clickable=True)])) == 1)

g1 = parse_task_rows(screen(row(u"逛一逛某频道", btn=u"逛一逛", y=874)))
check("C11 【逛一逛】按钮也算", len(g1) == 1 and g1[0]["btn"] == u"逛一逛")

done_row = screen(row(u"逛外卖频道", btn=u"已领取", y=874))
check("C12 【已领取】不算可做", parse_task_rows(done_row) == [])

multi = screen(row(u"任务甲", y=874), row(u"任务乙", y=1061), row(u"任务丙", y=1248))
r4 = parse_task_rows(multi)
check("C13 多行按 y 排序", [r["title"] for r in r4] == [u"任务甲", u"任务乙", u"任务丙"],
      "got %s" % [r["title"] for r in r4])

# ================================================================ D
print("\n--- D. 页面判定 ---")
HOME = load("_fixture_med_home.xml")
PAGE = load("_fixture_med_page.xml")
WP = load("_fixture_med_wp.xml")
DONE_F = load("_fixture_med_done.xml")

check("D1 看病买药页 is_medical_page", is_medical_page(PAGE))
check("D2 首页不是看病买药页", not is_medical_page(HOME))
check("D3 秒杀页 is_wp_page", is_wp_page(WP))
check("D4 首页不是秒杀页", not is_wp_page(HOME))
check("D5 看病买药页不是秒杀页", not is_wp_page(PAGE))
check("D6 弹层 has_task_panel", has_task_panel(PN))
check("D7 弹层全做完仍算弹层（还有去领取行）", has_task_panel(DONE_F))
check("D8 看病买药页不是弹层", not has_task_panel(PAGE))
check("D9 秒杀页不是弹层", not has_task_panel(WP))
check("D10 首页不是弹层", not has_task_panel(HOME))
check("D11 空节点", not has_task_panel([]) and not is_medical_page([])
      and not is_wp_page([]))
check("D12 弹层标题常量", PANEL_MARK == u"做任务赚更多京豆")

# ================================================================ E
print("\n--- E. pick_target 安全区 ---")
check("E1 安全区常量", SAFE_TOP < SAFE_BOTTOM < 2340,
      "SAFE_TOP=%d SAFE_BOTTOM=%d" % (SAFE_TOP, SAFE_BOTTOM))
check("E2 下界避开【领红包】浮层(y>=2040)", SAFE_BOTTOM <= 2040,
      "SAFE_BOTTOM=%d" % SAFE_BOTTOM)

t, why = pick_target(rows, set())
check("E3 夹具第一行在安全区被选中",
      t is not None and t["title"] == u"天天逛特价2元也包邮", "why=%s" % why)

only_bottom = [r for r in parse_task_rows(PN) if r["title"] == u"逛外卖频道"]
check("E4 逛外卖频道按钮 y=2002 越过下界",
      only_bottom and only_bottom[0]["btn_bounds"] == (863, 2002, 1036, 2092),
      "got %s" % (only_bottom and only_bottom[0]["btn_bounds"],))
t, why = pick_target(only_bottom, set())
check("E5 只有越界行 -> 上滑", t is None and why == "below", "why=%s" % why)

above = parse_task_rows(screen(row(u"上方任务", y=700)))
t, why = pick_target(above, set())
check("E6 全在上方 -> 下滑", t is None and why == "above", "why=%s" % why)

check("E7 没可做 -> none", pick_target([], set()) == (None, "none"))
t, why = pick_target(rows, set(titles))
check("E8 都试过 -> none", t is None and why == "none", "why=%s" % why)
t, _ = pick_target(rows, set([titles[0]]))
check("E9 跳过试过的", t is not None and t["title"] == titles[1])

# ================================================================ F
print("\n--- F. find_sign_in / find_more_bean ---")
si = find_sign_in(PAGE)
check("F1 看病买药页找到【签到领京豆】", si is not None)
check("F2 位置 (73,1523,233,1567)", si and si["bounds"] == (73, 1523, 233, 1567),
      "got %s" % (si and si["bounds"],))
check("F3 秒杀页没有【签到领京豆】", find_sign_in(WP) is None)
check("F4 首页没有【签到领京豆】", find_sign_in(HOME) is None)

mb = find_more_bean(WP)
check("F5 秒杀页找到【领更多京豆】", mb is not None)
check("F6 位置 (712,434,946,492)", mb and mb["bounds"] == (712, 434, 946, 492),
      "got %s" % (mb and mb["bounds"],))
TITLE_NODES = [n for n in WP if n["text"] == u"做任务 领更多京豆"]
check("F7 页面标题「做任务 领更多京豆」确实存在（所以必须完全相等）",
      len(TITLE_NODES) == 1 and TITLE_NODES[0]["bounds"] == (49, 264, 409, 324),
      "got %s" % [(n["text"], n["bounds"]) for n in TITLE_NODES])
check("F8 不会返回标题节点", mb is not None and mb["bounds"][1] != 264)
check("F9 首页没有【领更多京豆】", find_more_bean(HOME) is None)
check("F10 空节点返回 None", find_sign_in([]) is None and find_more_bean([]) is None)

# ================================================================ G
print("\n--- G. clickable_ancestor ---")
box = clickable_ancestor(WP, mb)
check("G1 【领更多京豆】可点祖先 (822,401,965,530)", box == (822, 401, 965, 530),
      "got %s" % (box,))
# 可点祖先只保证「包住文字中心」（真机最小可点框 (822,401,965,530)
# 比文字框 (712,434,946,492) 窄，但中心 (829,463) 在里面，点它有效）
_cx, _cy = (712 + 946) // 2, (434 + 492) // 2
check("G2 祖先包住文字中心", box and box[0] <= _cx <= box[2] and box[1] <= _cy <= box[3],
      "center=(%d,%d) box=%s" % (_cx, _cy, box))
check("G3 祖先高度比文字高（按钮区更宽）", box and (box[3] - box[1]) > (492 - 434),
      "got %s" % (box,))

AC1 = load("_fixture_med_allchan1.xml")
mc = None
for n in AC1:
    if n["text"] == MED_DESC and n["bounds"][3] > n["bounds"][1]:
        mc = n
        break
check("G4 全部频道页找到【看病买药】图标文字", mc is not None,
      "got %s" % (mc and mc["bounds"],))
check("G5 图标文字在 (77,1300,231,1347)", mc and mc["bounds"] == (77, 1300, 231, 1347),
      "got %s" % (mc and mc["bounds"],))
box2 = clickable_ancestor(AC1, mc)
check("G6 可点祖先 (55,1199,253,1347)", box2 == (55, 1199, 253, 1347), "got %s" % (box2,))
check("G7 空节点返回 None", clickable_ancestor([], nd(u"x", 0, 0, 10, 10)) is None)
check("G8 自己就可点时也返回自己",
      clickable_ancestor([nd(u"x", 10, 10, 100, 100, clickable=True)],
                         nd(u"x", 10, 10, 100, 100)) == (10, 10, 100, 100))

# ================================================================ H
print("\n--- H. _reveal_tab ---")


class SwipeUI(FakeUI):
    """按滑动次数切屏：第 n 次左滑后换成 screens[n]。"""

    def __init__(self, screens):
        FakeUI.__init__(self)
        self.screens = screens
        self.idx = 0

    def nodes(self):
        return self.screens[min(self.idx, len(self.screens) - 1)]

    def adb_swipe(self, x1, y1, x2, y2, duration=300):
        self.swipes.append((x1, y1, x2, y2))
        self.idx += 1


AC0 = load("_fixture_med_allchan0.xml")
m = Task9Medical()

# 已经进屏：不该滑
ui = SwipeUI([AC1, AC1])
log = Log()
node, ns = m._reveal_tab(ui, log, AC1, MED_TAB)
check("H1 已进屏直接返回", node is not None and node["bounds"] == (533, 368, 753, 470),
      "got %s" % (node and node["bounds"],))
check("H2 已进屏不滑动", ui.swipes == [], "got %s" % (ui.swipes,))

# 完全没渲染：滑一次就出来
ui = SwipeUI([AC1, AC1])
log = Log()
node, ns = m._reveal_tab(ui, log, AC0, MED_TAB)
check("H3 子 tab 没渲染时会滑", len(ui.swipes) >= 1, "swipes=%d" % len(ui.swipes))
check("H4 滑动后拿到节点", node is not None and node["bounds"] == (533, 368, 753, 470),
      "got %s" % (node and node["bounds"],))
check("H5 滑动行 y 用锚点 + 120（发现好物 cy=466 -> 586）",
      ui.swipes and ui.swipes[0][1] == 586, "got %s" % (ui.swipes[:1],))
check("H6 滑动写在日志里", u"左滑" in log.text(), log.text()[-200:])

# 一直不出现
ui = SwipeUI([AC0, AC0, AC0, AC0, AC0, AC0, AC0, AC0])
log = Log()
node, ns = m._reveal_tab(ui, log, AC0, MED_TAB, max_swipes=3)
check("H7 一直不出现返回 None", node is None)
check("H8 滑动次数有上限", len(ui.swipes) == 3, "swipes=%d" % len(ui.swipes))
check("H9 会写 WARN 日志", u"仍没出现" in log.text(), log.text()[-200:])

# ================================================================ I
print("\n--- I. _tap_label / _tap_node ---")


class TapUI(FakeUI):
    def nodes(self):
        return AC1


ui = TapUI()
log = Log()
check("I1 点【医疗保健】成功", m._tap_label(ui, log, AC1, MED_TAB, u"全部频道页") is True)
check("I2 点的是 (643,419)", ui.taps and ui.taps[0] == (643, 419), "got %s" % (ui.taps[:1],))

ui2 = TapUI()
log2 = Log()
check("I3 点【看病买药】成功", m._tap_label(ui2, log2, AC1, MED_DESC, u"全部频道页") is True)
check("I4 点的是可点祖先中心 (154,1273)", ui2.taps and ui2.taps[0] == (154, 1273),
      "got %s" % (ui2.taps[:1],))

log3 = Log()
check("I5 找不到标签返回 False",
      m._tap_label(FakeUI(), log3, AC1, u"不存在的标签", u"全部频道页") is False)
check("I6 找不到会写日志", u"没找到" in log3.text())

ui4 = TapUI()
log4 = Log()
check("I7 点【发现好物】用的是自己的 bounds 中心 (937,466)",
      m._tap_label(ui4, log4, AC1, FIND_GOODS, u"全部频道页") is True
      and ui4.taps[0] == (937, 301),
      "got %s" % (ui4.taps[:1],))

# ================================================================ J
print("\n--- J. 入口链路 _open_medical ---")


class EntryUI(FakeUI):
    """首页/金刚区/全部频道/看病买药页 的可控替身。"""

    def __init__(self, home, kk2, allchan0, allchan1, medpage,
                 kk1_has_med=True, kk2_has_med=False, kk1_tap_bad=False):
        FakeUI.__init__(self)
        self.home = home
        self.kk2 = kk2
        self.allchan0 = allchan0
        self.allchan1 = allchan1
        self.medpage = medpage
        self.kk1_has_med = kk1_has_med
        self.kk2_has_med = kk2_has_med
        self.kk1_tap_bad = kk1_tap_bad
        self.page = "home"
        self.kk_page = 1
        self.in_allchan = 0          # 0=全部频道首页 1=发现好物已选

    def nodes(self):
        if self.page == "home":
            return self.kk2 if self.kk_page == 2 else self.home
        if self.page == "allchan":
            return self.allchan1 if self.in_allchan else self.allchan0
        if self.page == "med":
            return self.medpage
        return self.home

    def _stable_kingkong_icon(self, desc, tries=4):
        if self.page != "home":
            return None, False
        if self.kk_page == 1 and self.kk1_has_med:
            return {"desc": desc, "bounds": (194, 440, 388, 601), "clickable": True,
                    "cy": 520}, True
        if self.kk_page == 2 and self.kk2_has_med:
            return {"desc": desc, "bounds": (435, 440, 651, 601), "clickable": True,
                    "cy": 520}, True
        return None, False

    def swipe_kingkong(self, direction="left", pause=1.5):
        self.kk_swipes.append(direction)
        self.kk_page = 2 if direction == "left" else 1

    def adb_tap(self, pos, pause=1.5):
        self.taps.append(pos)
        if self.page == "home":
            if self.kk_page == 1 and pos == (291, 520) and not self.kk1_tap_bad:
                self.page = "med"
            elif self.kk_page == 2 and pos == (543, 520):
                self.page = "med"
            elif pos == (973, 1004):
                self.page = "allchan"
                self.in_allchan = 0
        elif self.page == "allchan":
            if pos == (937, 466):
                self.in_allchan = 1
            elif pos == (154, 1273):
                self.page = "med"
        elif self.page == "med":
            pass

    def tap(self, pos, pause=1.5):
        # 真 jd_ui.tap 会真点下去，_open_medical 用的就是 ui.tap，别只记 adb_tap
        self.adb_tap(pos, pause)

    def goto_home(self):
        FakeUI.goto_home(self)
        self.page = "home"
        self.kk_page = 1
        return True


KK2 = load("_fixture_med_kk2.xml")

m = Task9Medical()
ui = EntryUI(HOME, KK2, AC0, AC1, PAGE)
log = Log()
check("J1 金刚区第1页直接进", m._open_medical(ui, log, cold=True) is True, log.text()[-300:])
check("J2 冷启动了一次", ui.restart_calls == 1)
check("J3 点的是看病买药图标中心 (291,520)", ui.taps and ui.taps[0] == (291, 520),
      "got %s" % (ui.taps[:1],))
check("J4 没去翻第2页", "left" not in ui.kk_swipes, "got %s" % ui.kk_swipes)

m2 = Task9Medical()
ui2 = EntryUI(HOME, KK2, AC0, AC1, PAGE, kk1_has_med=False, kk2_has_med=True)
log2 = Log()
check("J5 第1页没有就翻第2页", m2._open_medical(ui2, log2, cold=True) is True,
      log2.text()[-300:])
check("J6 确实左滑了一次", "left" in ui2.kk_swipes)
check("J7 第2页点的是 (543,520)", (543, 520) in ui2.taps, "got %s" % (ui2.taps,))

m3 = Task9Medical()
ui3 = EntryUI(HOME, KK2, AC0, AC1, PAGE, kk1_has_med=False, kk2_has_med=False)
log3 = Log()
check("J8 两页都没有走全部频道兜底", m3._open_medical(ui3, log3, cold=True) is True,
      log3.text()[-500:])
check("J9 走了全部频道", u"全部频道" in log3.text())
check("J10 点了发现好物 (937,466) 和看病买药 (154,1273)",
      (937, 466) in ui3.taps and (154, 1273) in ui3.taps, "taps=%s" % (ui3.taps,))

m4 = Task9Medical()
ui4 = EntryUI(HOME, KK2, AC0, AC1, PAGE, kk1_has_med=True, kk1_tap_bad=True,
              kk2_has_med=False)
log4 = Log()
check("J11 第1页点歪了会继续下一级", m4._open_medical(ui4, log4, cold=True) is True,
      log4.text()[-500:])

m5 = Task9Medical()
ui5 = FakeUI()
ui5.nodes = lambda: list(HOME)
ui5._stable_kingkong_icon = lambda desc, tries=4: (None, False)
ui5.adb_tap = lambda pos, pause=1.5: ui5.taps.append(pos)
log5 = Log()
check("J12 全都进不去返回 False", m5._open_medical(ui5, log5, cold=True) is False)

# ================================================================ K
print("\n--- K. _open_wp 点【签到领京豆】 ---")


class SignUI(FakeUI):
    def __init__(self, page, wp, first_tap_bad=False):
        FakeUI.__init__(self)
        self.page = page
        self.wp = wp
        self.on_wp = False
        self.first_tap_bad = first_tap_bad

    def nodes(self):
        return self.wp if self.on_wp else self.page

    def adb_tap(self, pos, pause=1.5):
        self.taps.append(pos)
        if self.on_wp:
            return
        # 文字 (73,1523,233,1567) 和它上方图标都算命中
        if 73 <= pos[0] <= 233 and 1400 <= pos[1] <= 1567:
            if self.first_tap_bad:
                self.first_tap_bad = False
                return
            self.on_wp = True


m = Task9Medical()
ui = SignUI(PAGE, WP)
log = Log()
check("K1 点【签到领京豆】进秒杀页", m._open_wp(ui, log) is True, log.text()[-300:])
check("K2 点的是文字中心 (153,1545)", ui.taps and ui.taps[0] == (153, 1545),
      "got %s" % (ui.taps[:2],))

ui2 = SignUI(PAGE, WP, first_tap_bad=True)
log2 = Log()
check("K3 第一次没反应会兜底往上 60px", m._open_wp(ui2, log2) is True, log2.text()[-300:])
check("K4 兜底点了 (153,1485)", (153, 1485) in ui2.taps, "got %s" % (ui2.taps,))

log3 = Log()
check("K5 找不到【签到领京豆】返回 False",
      m._open_wp(SignUI(HOME, WP), log3) is False)
check("K6 会写日志", u"没找到" in log3.text())

# ================================================================ L
print("\n--- L. _open_panel 点【领更多京豆】 ---")


class PanelOpenUI(FakeUI):
    def __init__(self, wp, panel, fail_times=0):
        FakeUI.__init__(self)
        self.wp = wp
        self.panel = panel
        self.fail_times = fail_times
        self.opened = False
        self.clicks = 0

    def nodes(self):
        return self.panel if self.opened else self.wp

    def adb_tap(self, pos, pause=1.5):
        self.taps.append(pos)
        if self.opened:
            return
        if 822 <= pos[0] <= 965 and 401 <= pos[1] <= 530:
            self.clicks += 1
            if self.clicks > self.fail_times:
                self.opened = True


m = Task9Medical()
ui = PanelOpenUI(WP, PN)
log = Log()
check("L1 点【领更多京豆】开弹层", m._open_panel(ui, log) is True, log.text()[-300:])
check("L2 点的是可点祖先中心 (893,465)", ui.taps and ui.taps[0] == (893, 465),
      "got %s" % (ui.taps[:1],))

ui2 = PanelOpenUI(WP, PN, fail_times=1)
log2 = Log()
check("L3 第一次没弹会再点一次", m._open_panel(ui2, log2) is True, log2.text()[-300:])
check("L4 点了两次", len(ui2.taps) == 2, "got %s" % (ui2.taps,))

ui3 = PanelOpenUI(WP, PN, fail_times=99)
log3 = Log()
check("L5 两次都不弹返回 False", m._open_panel(ui3, log3) is False)
check("L6 最多点两次", len(ui3.taps) == 2, "got %d" % len(ui3.taps))

log4 = Log()
check("L7 秒杀页找不到按钮返回 False", m._open_panel(PanelOpenUI(PAGE, PN), log4) is False)

# ================================================================ M
print("\n--- M. 任务循环 ---")


class TaskPanelUI(FakeUI):
    """模拟【做任务赚更多京豆】弹层 + 浏览落地页。

    state: 'todo'（去完成）-> 点下去 away=True -> back 后变 'done'（已领取）
    """

    def __init__(self, tasks, completes=True, stay_away=False, fail_reads=0,
                 scrollable=False):
        FakeUI.__init__(self)
        self.tasks = [dict(t) for t in tasks]
        self.completes = completes
        self.stay_away = stay_away
        self.fail_reads = fail_reads
        self.reads = 0
        self.away = False
        self.offset = 0
        self.scrollable = scrollable

    def _btn_text(self, t):
        return {u"todo": u"去完成", u"done": u"已领取"}[t["state"]]

    def _rows(self):
        out = list(MARK)
        for t in self.tasks:
            y = t["y"] - self.offset
            out.append(nd(t["title"], 181, y, 599, y + 61))
            out.append(nd(u"浏览%ds" % t["secs"], 181, y + 61, 291, y + 105))
            out.append(nd(u"1", 341, y + 61, 363, y + 105))
            out.append(nd(u"京豆", 360, y + 61, 434, y + 105))
            out.append(nd(self._btn_text(t), 863, y + 8, 1036, y + 99, clickable=True))
        return out

    def nodes(self):
        self.reads += 1
        if self.reads <= self.fail_reads:
            return []
        if self.away:
            return [nd(u"天天低价", 170, 129, 382, 192)]
        return self._rows()

    def adb_tap(self, pos, pause=1.5):
        self.taps.append(pos)
        if self.away:
            return
        for t in self.tasks:
            x1, y1 = 863, t["y"] - self.offset + 8
            x2, y2 = 1036, t["y"] - self.offset + 99
            if not (x1 <= pos[0] <= x2 and y1 <= pos[1] <= y2):
                continue
            if t["state"] == u"todo":
                self.away = True
                if self.completes:
                    t["state"] = u"done"
                return

    def back(self, pause=2.0):
        self.backs += 1
        if not self.stay_away:
            self.away = False

    def adb_swipe(self, x1, y1, x2, y2, duration=300):
        self.swipes.append((x1, y1, x2, y2))
        if not self.scrollable:
            return
        if y1 > y2:
            self.offset += 300
        else:
            self.offset = max(0, self.offset - 300)


T = [dict(title=u"天天逛特价2元也包邮", secs=5, state=u"todo", y=874),
     dict(title=u"去京喜自营频道签到", secs=5, state=u"todo", y=1061)]

ui = TaskPanelUI([dict(t) for t in T])
log = Log()
done = Task9Medical()._process_tasks(ui, log, threading.Event())
check("M1 两个任务都做完", done == 2, "done=%d" % done)
check("M2 每个任务都停 9s", ui.sleeps.count(9.0) >= 2, "sleeps=%s" % sorted(set(ui.sleeps)))
check("M3 每个任务都按过返回", ui.backs >= 2, "backs=%d" % ui.backs)
check("M4 日志说没有可做任务", u"没有可做任务" in log.text())
check("M5 全程没有领取动作（需求要求不领）",
      all(u"领取" not in m for lv, m in log.lines if lv == "INFO") or
      not any(u"领取" in m and u"已" not in m for lv, m in log.lines),
      log.text()[-400:])

ui = TaskPanelUI([dict(T[0])])
log = Log()
done = Task9Medical()._process_tasks(ui, log, threading.Event())
check("M6 只有 1 个任务就做 1 个", done == 1)

ui = TaskPanelUI([dict(T[0])], completes=False)
log = Log()
done = Task9Medical()._process_tasks(ui, log, threading.Event())
check("M7 按钮没变只做一次", done == 0)
check("M8 只点了一次去完成", len([p for p in ui.taps if p[0] >= 863]) == 1,
      "taps=%s" % (ui.taps,))

ui = TaskPanelUI([dict(T[0])], stay_away=True)
log = Log()
done = Task9Medical()._process_tasks(ui, log, threading.Event())
check("M9 回不来会尝试轻量重开", u"轻量重开" in log.text(), log.text()[-400:])
check("M10 重进有上限", log.text().count(u"整链重进") <= MAX_REENTER + 1,
      log.text()[-400:])

ui = TaskPanelUI([dict(T[0])], fail_reads=2)
log = Log()
done = Task9Medical()._process_tasks(ui, log, threading.Event())
check("M11 读失败会重读", done == 1, "done=%d" % done)

ui = TaskPanelUI([dict(T[0])], fail_reads=1000)
log = Log()
done = Task9Medical()._process_tasks(ui, log, threading.Event())
check("M12 连续读失败会收尾", done == 0 and u"读不到页面" in log.text(),
      log.text()[-200:])

ui = TaskPanelUI([dict(title=u"逛外卖频道", secs=5, state=u"todo", y=1993)],
                 scrollable=True)
log = Log()
done = Task9Medical()._process_tasks(ui, log, threading.Event())
check("M13 需要滚动时会滚动", len(ui.swipes) >= 1, "swipes=%d" % len(ui.swipes))
check("M14 滚动用的是屏幕中线 x=540",
      ui.swipes and ui.swipes[0][0] == 540, "got %s" % (ui.swipes[:1],))
check("M15 滚动后完成任务", done == 1, "done=%d log=%s" % (done, log.text()[-300:]))

ui = TaskPanelUI([])
log = Log()
check("M16 没有任务立即收尾",
      Task9Medical()._process_tasks(ui, log, threading.Event()) == 0)

# 夹具级：全做完的弹层不应再产生任何任务
check("M17 全做完的夹具解析出 0 行", parse_task_rows(DONE_F) == [],
      "got %s" % [r["title"] for r in parse_task_rows(DONE_F)])

# ================================================================ N
print("\n--- N. _recover_panel ---")


class RecoverUI(FakeUI):
    def __init__(self, screens, back_until=None):
        FakeUI.__init__(self)
        self.screens = screens
        self.idx = 0
        self.back_until = back_until

    def nodes(self):
        return self.screens[min(self.idx, len(self.screens) - 1)]

    def adb_tap(self, pos, pause=1.5):
        self.taps.append(pos)
        if 822 <= pos[0] <= 965 and 401 <= pos[1] <= 530:
            self.idx = len(self.screens) - 1

    def back(self, pause=2.0):
        self.backs += 1
        if self.back_until is not None:
            self.idx = min(self.idx + 1, len(self.screens) - 1)


m = Task9Medical()
ui = RecoverUI([PN])
log = Log()
check("N1 弹层还在直接 True", m._recover_panel(ui, log) is True)
check("N2 弹层还在不点不返回", ui.taps == [] and ui.backs == 0)

ui = RecoverUI([WP, PN])
log = Log()
check("N3 弹层没了但能看到【领更多京豆】就点它", m._recover_panel(ui, log) is True,
      log.text()[-300:])
check("N4 点的是 (893,465)", ui.taps and ui.taps[0] == (893, 465),
      "got %s" % (ui.taps[:1],))

ui = RecoverUI([NO_PANEL, NO_PANEL, NO_PANEL], back_until=True)
ui.screens = [[nd(u"某频道页", 0, 0, 1080, 2340)],
              [nd(u"某频道页", 0, 0, 1080, 2340)],
              PN]
log = Log()
check("N5 back 两次后弹层出现也算恢复", m._recover_panel(ui, log) is True,
      log.text()[-300:])

ui = RecoverUI([[nd(u"某频道页", 0, 0, 1080, 2340)]], back_until=False)
log = Log()
check("N6 什么都没有返回 False", m._recover_panel(ui, log) is False)
check("N7 会写 WARN", u"轻量重开失败" in log.text())
check("N8 back 次数有上限", ui.backs <= 2, "backs=%d" % ui.backs)

# ================================================================ O
print("\n--- O. stop_event ---")
ev = threading.Event()
ev.set()
ui = TaskPanelUI([dict(T[0])])
log = Log()
check("O1 一开始就 stop -> 0 个任务",
      Task9Medical()._process_tasks(ui, log, ev) == 0)
check("O2 stop 后不点任何按钮", ui.taps == [], "taps=%s" % (ui.taps,))

# ================================================================ P
print("\n--- P. run() 整体 ---")


class RunUI(FakeUI):
    """完整链路替身：首页 -> 看病买药 -> 秒杀页 -> 弹层 -> 1 个任务。"""

    def __init__(self, entry_ok=True, tasks=None):
        FakeUI.__init__(self)
        self.entry_ok = entry_ok
        self.page = "home"
        self.away = False
        # 注意不能用 `tasks or [T[0]]`：空列表会被 or 吃掉，测不到「0 个任务」
        self.tasks = [dict(t) for t in (tasks if tasks is not None else [T[0]])]

    def nodes(self):
        if self.away:
            return [nd(u"天天低价", 170, 129, 382, 192)]
        if self.page == "home":
            return HOME
        if self.page == "med":
            return PAGE
        if self.page == "wp":
            return WP
        if self.page == "panel":
            out = list(MARK)
            for t in self.tasks:
                out.extend(row(t["title"], t["secs"],
                               u"去完成" if t["state"] == u"todo" else u"已领取",
                               t["y"]))
            return out
        return HOME

    def _stable_kingkong_icon(self, desc, tries=4):
        if not self.entry_ok or self.page != "home":
            return None, False
        return {"desc": desc, "bounds": (194, 440, 388, 601), "clickable": True,
                "cy": 520}, True

    def adb_tap(self, pos, pause=1.5):
        self.taps.append(pos)
        if self.away:
            return
        if self.page == "home" and pos == (291, 520):
            self.page = "med"
        elif self.page == "med" and pos == (153, 1545):
            self.page = "wp"
        elif self.page == "wp" and pos == (893, 465):
            self.page = "panel"
        elif self.page == "panel":
            for t in self.tasks:
                if 863 <= pos[0] <= 1036 and t["y"] + 8 <= pos[1] <= t["y"] + 99:
                    if t["state"] == u"todo":
                        self.away = True
                        t["state"] = u"done"
                    return

    def tap(self, pos, pause=1.5):
        self.adb_tap(pos, pause)

    def back(self, pause=2.0):
        self.backs += 1
        self.away = False


# 离线回归契约：run() 里 driver.get_driver() 会真建 Appium session，
# 设备掉线时 P 组会误报失败；一并替身掉，保证整套回归不连手机。
import utils.driver as _drv
_orig_get_driver = _drv.get_driver
_drv.get_driver = lambda: None

_orig = MOD.JDUI
MOD.JDUI = lambda d, l, s: RunUI()
log = Log()
try:
    Task9Medical().run(log, threading.Event())
    ok = True
except Exception as e:
    ok = False
    log.write_log("异常 %s" % e, "ERROR")
check("P1 全链路跑通", ok, log.text()[-400:])
check("P2 有 DONE 日志", any(lv == "DONE" for lv, _ in log.lines), log.text()[-300:])
check("P3 DONE 里说完成 1 个", any(lv == "DONE" and u"完成 1 个" in m
                                  for lv, m in log.lines), log.text()[-300:])

MOD.JDUI = lambda d, l, s: RunUI(entry_ok=False)
log2 = Log()
raised = False
try:
    Task9Medical().run(log2, threading.Event())
except RuntimeError:
    raised = True
except Exception:
    raised = False
check("P4 进不去会抛 RuntimeError", raised, log2.text()[-300:])
check("P5 异常信息提到看病买药", raised and u"看病买药" in log2.text() + "看病买药")

MOD.JDUI = lambda d, l, s: RunUI(tasks=[])
log3 = Log()
ok3 = True
try:
    Task9Medical().run(log3, threading.Event())
except Exception as e:
    ok3 = False
    log3.write_log("异常 %s" % e, "ERROR")
check("P6 没有可做任务也能正常收尾", ok3, log3.text()[-300:])
check("P7 没有任务时完成 0 个",
      any(lv == "DONE" and u"完成 0 个" in m for lv, m in log3.lines),
      log3.text()[-300:])
MOD.JDUI = _orig
_drv.get_driver = _orig_get_driver

# ================================================================
print("\n" + "=" * 60)
print("通过 %d / %d" % (len(PASSED), len(PASSED) + len(FAILED)))
if FAILED:
    print("失败用例：")
    for f in FAILED:
        print("   -", f)
    sys.exit(1)
print("全部通过")
