# -*- coding: utf-8 -*-
"""拍拍二手 模块离线回归（不连手机、不连 Appium）。

覆盖：
  A. X+4 停留换算
  B. 真机夹具 _fixture_pp_panel.xml / _fixture_pp_claim.xml 上的任务行配对
  C. 合成节点配对（含「分享好友助力」必须排除、标题与按钮边缘重叠）
  D. 页面判定 is_pp_page / is_self_page / has_task_panel
  E. pick_target 安全区
  F. find_self_tab / find_more_bean / clickable_ancestor
  G. _reveal_tab（二级 tab 横向滑进屏幕）
  H. _tap_label / _tap_node
  I. 入口链路 _open_pp（金刚区第1页 / 第2页 / 全部频道兜底）
  J. _open_self（点【自营】tab 且等 5s）
  K. _open_panel（点【赚更多京豆】开弹层）
  L. 任务循环（完成判定、失败重试、滑到底确认、重进重置台账）
  M. 领取阶段（_claim_once 间隔 1s / _claim_all 逐屏）
  N. _recover_panel / _light_reopen
  O. stop_event
  P. run() 整体

夹具（真机 1080x2340，2026-11-12 抓的）：
  _fixture_pp_home.xml      首页金刚区第1页（没有拍拍二手）
  _fixture_pp_kk2.xml       金刚区第2页（desc='拍拍二手' (867,763,1080,924) + 全部频道）
  _fixture_pp_page.xml      拍拍二手页（【自营】tab (836,378,975,432)）
  _fixture_pp_self.xml      自营 tab 页（【赚更多京豆】(46,1343,500,1423)）
  _fixture_pp_panel.xml     做任务领京豆弹层（4 个【浏览10s可领】+ 1 个【领取】）
  _fixture_pp_claim.xml     同一个弹层领取完之后（3 个可做 + 0 待领）
  _fixture_pp_allchan0.xml  全部频道首屏（【发现好物】(849,396,1025,536)）
  _fixture_pp_allchan1.xml  发现好物 tab（【二手】(1828,368,1977,470) 在屏外）
  _fixture_pp_allchan2.xml  横滑 2 次后（【二手】(921,368,1067,470) 在屏内）
  _fixture_pp_allchan3.xml  点完【二手】后（【拍拍二手】(77,2169,231,2216) 在列表底部）
"""
import io
import re
import sys
import threading
import xml.etree.ElementTree as ET

sys.path.insert(0, ".")

import modules.task10_paipai as MOD
from modules.task10_paipai import (
    Task10Paipai, browse_seconds, parse_task_rows, parse_claim_buttons,
    pick_target, has_task_panel, is_pp_page, is_self_page, find_self_tab,
    find_more_bean, clickable_ancestor, row_sig,
    BROWSE_EXTRA, SAFE_TOP, SAFE_BOTTOM, MAX_RETRY, MAX_REENTER,
    PANEL_MARK, PP_DESC, FIND_GOODS, ALL_CHANNEL, USED_TAB, SELF_TAB,
    SELF_MARK, MORE_BEAN, CLAIM_WAIT, SELF_TAB_WAIT, PP_PAGE_WAIT,
    LIVE_FLOAT_CENTER, LIVE_FLOAT_TOP, LIVE_FLOAT_DURATION,
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
    """解析成 jd_ui.nodes() 同样的结构（退化 bounds 也保留，交给业务过滤）。"""
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


ROW_H = 203


def row(title, secs=10, btn=u"去完成", idx=0):
    """按真机行结构造一行（拍拍二手弹层）。

    真机第 2 行：标题 [203,1426][739,1475]，副标题【，浏览10s可领】[431,1492][646,1533]，
    按钮 [814,1442][1031,1525]。
    """
    y = 1225 + idx * ROW_H
    return [
        nd(title, 203, y, 816, y + 50),
        nd(u"，浏览%ds可领" % secs, 203, y + 50, 701, y + 90),
        nd(u"+1", 698, y + 68, 739, y + 104),
        nd(btn, 814, y + 17, 1031, y + 106, clickable=True),
    ]


def screen(*rows):
    out = []
    for r in rows:
        out.extend(r)
    return out


MARK = [nd(PANEL_MARK, 330, 1052, 750, 1123)]
# 「自营页在、弹层没了」的真实样子
NO_PANEL = [nd(u"每日领京豆", 46, 1156, 253, 1206),
            nd(u"赚更多京豆", 46, 1343, 500, 1423, clickable=True),
            nd(u"自营", 471, 372, 610, 430)]


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
        self.drags = []

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

    def adb_drag(self, x1, y1, x2, y2, duration=1500):
        """真机走 input draganddrop，这里只记录。"""
        self.drags.append((x1, y1, x2, y2, duration))
        return True

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
check("A1 10s -> 14s", browse_seconds(10) == 14)
check("A2 5s -> 9s", browse_seconds(5) == 9)
check("A3 0s -> 4s", browse_seconds(0) == 4)
check("A4 BROWSE_EXTRA=4", BROWSE_EXTRA == 4)
check("A5 模块元信息", Task10Paipai.name == u"拍拍二手"
      and Task10Paipai.icon == u"♻")
check("A6 需求常量", (PP_PAGE_WAIT, SELF_TAB_WAIT, CLAIM_WAIT) == (3.0, 5.0, 1.0),
      "got %s" % ((PP_PAGE_WAIT, SELF_TAB_WAIT, CLAIM_WAIT),))
check("A7 直播小窗常量",
      (LIVE_FLOAT_CENTER, LIVE_FLOAT_TOP) == ((952, 1418), (952, 210)),
      "got %s" % ((LIVE_FLOAT_CENTER, LIVE_FLOAT_TOP),))
check("A8 draganddrop 时长 >=1000ms（太短会被当 fling）",
      LIVE_FLOAT_DURATION >= 1000, "got %d" % LIVE_FLOAT_DURATION)

# ================================================================ B
print("\n--- B. 真机夹具 ---")
PN = load("_fixture_pp_panel.xml")
rows = parse_task_rows(PN)
check("B1 弹层识别", has_task_panel(PN))
check("B2 配出 4 行可做任务", len(rows) == 4, "got %d" % len(rows))
titles = [r["title"] for r in rows]
check("B3 标题正确",
      titles == [u"逛便宜包邮频道（0/1）", u"1元抢手机（0/1）", u"看视频赚钱（0/1）",
                 u"上领券中心领全品类券（0/1）"], "got %s" % titles)
check("B4 secs 都是 10", all(r["secs"] == 10 for r in rows))
check("B5 按钮都是去完成", all(r["btn"] == u"去完成" for r in rows))
check("B6 按 y 升序", [r["cy"] for r in rows] == sorted(r["cy"] for r in rows))
check("B7 【分享好友助力】被排除（副标题没有浏览Ns）",
      all(u"分享好友助力" not in t for t in titles), "got %s" % titles)
check("B8 标题没被背后自营页文案抢走",
      all(u"手机" != t and u"官方榜单" not in t and u"堪比新品" not in t
          for t in titles), "got %s" % titles)
check("B9 row_sig 稳定",
      row_sig(rows) == row_sig(parse_task_rows(load("_fixture_pp_panel.xml"))))
check("B10 按钮都在 x>=700", all(r["cx"] >= 700 for r in rows))

claims = parse_claim_buttons(PN)
check("B11 弹层里有 1 个待领取", len(claims) == 1, "got %d" % len(claims))
check("B12 待领取是【每日签到领现金】那一行 (814,2248,1031,2331)",
      claims and claims[0]["bounds"] == (814, 2248, 1031, 2331),
      "got %s" % (claims and claims[0]["bounds"],))
check("B13 待领取按钮 cy=2289", claims and claims[0]["cy"] == 2289)

CL = load("_fixture_pp_claim.xml")
rows2 = parse_task_rows(CL)
check("B14 领取后只剩 3 个可做任务", len(rows2) == 3, "got %d" % len(rows2))
check("B15 领取后【逛便宜包邮频道】不在可做列表",
      all(u"逛便宜包邮" not in r["title"] for r in rows2))
check("B16 领取后没有待领取", parse_claim_buttons(CL) == [])
check("B17 领取后仍算弹层", has_task_panel(CL))

# ================================================================ C
print("\n--- C. 合成节点配对 ---")
r1 = parse_task_rows(screen(row(u"逛便宜包邮频道（0/1）", idx=0)))
check("C1 单行配出", len(r1) == 1)
check("C2 标题", r1 and r1[0]["title"] == u"逛便宜包邮频道（0/1）")
check("C3 按钮中心 (922,1286)",
      r1 and (r1[0]["cx"], r1[0]["cy"]) == (922, 1286),
      "got %s" % ((r1[0]["cx"], r1[0]["cy"]) if r1 else None,))

only_btn = [nd(u"去完成", 814, 1242, 1031, 1321, clickable=True)]
check("C4 没有【浏览Ns可领】不算任务行", parse_task_rows(only_btn) == [])

share = [nd(u"分享好友助力（0/11）", 203, 1225, 657, 1275),
         nd(u"每邀一位好友助力领京豆", 203, 1291, 555, 1330),
         nd(u"+5", 605, 1294, 657, 1330),
         nd(u"去完成", 814, 1242, 1031, 1321, clickable=True)]
check("C5 真机【分享好友助力】行不算可做任务", parse_task_rows(share) == [])

degen = [nd(u"逛京东校园（0/1）", 203, 2435, 668, 2342),
         nd(u"，浏览10s可领", 203, 2501, 365, 2342),
         nd(u"去完成", 814, 2452, 1031, 2342, clickable=True)]
check("C6 屏外退化 bounds 被过滤", parse_task_rows(degen) == [])

left_btn = screen(row(u"逛便宜包邮频道（0/1）", idx=0))
left_btn.append(nd(u"去完成", 200, 1259, 380, 1350, clickable=True))
r2 = parse_task_rows(left_btn)
check("C7 左侧【去完成】不算", len(r2) == 1 and r2[0]["cx"] == 922)

g1 = parse_task_rows(screen(row(u"逛一逛某频道（0/1）", btn=u"逛一逛", idx=0)))
check("C8 【逛一逛】按钮也算", len(g1) == 1 and g1[0]["btn"] == u"逛一逛")

done_row = screen(row(u"逛外卖频道（1/1）", btn=u"已完成", idx=0))
check("C9 【已完成】不算可做", parse_task_rows(done_row) == [])

multi = screen(row(u"任务甲（0/1）", idx=0), row(u"任务乙（0/1）", idx=1),
               row(u"任务丙（0/1）", idx=2))
r3 = parse_task_rows(multi)
check("C10 多行按 y 排序",
      [r["title"] for r in r3] == [u"任务甲（0/1）", u"任务乙（0/1）", u"任务丙（0/1）"],
      "got %s" % [r["title"] for r in r3])

check("C11 半角括号也能识别",
      len(parse_task_rows([nd(u"某任务(0/1)", 203, 1225, 816, 1275),
                           nd(u"，浏览10s可领", 203, 1275, 701, 1315),
                           nd(u"去完成", 814, 1242, 1031, 1321,
                              clickable=True)])) == 1)

# 真机回归：标题右边缘 816 比按钮左边缘 814 还大 2px
overlap = [nd(u"每日签到领现金（1/1）", 203, 2212, 816, 2262),
           nd(u"，浏览10s可领", 203, 2276, 701, 2340),
           nd(u"领取", 814, 2248, 1031, 2331, clickable=True)]
c_over = parse_claim_buttons(overlap)
check("C12 标题右边缘与按钮左边缘重叠 2px 仍能识别【领取】", len(c_over) == 1,
      "got %d" % len(c_over))
check("C13 重叠时按钮中心 (922,2289)", c_over and (c_over[0]["cx"], c_over[0]["cy"]) == (922, 2289),
      "got %s" % ((c_over[0]["cx"], c_over[0]["cy"]) if c_over else None,))

no_prog = [nd(u"随便一行字", 203, 2212, 700, 2262),
           nd(u"，浏览10s可领", 203, 2276, 701, 2340),
           nd(u"领取", 814, 2248, 1031, 2331, clickable=True)]
check("C14 同行没有 (N/M) 的【领取】不算", parse_claim_buttons(no_prog) == [])

left_claim = [nd(u"任务甲（1/1）", 203, 1225, 816, 1275),
              nd(u"领取", 200, 1242, 380, 1321, clickable=True)]
check("C15 左侧【领取】不算", parse_claim_buttons(left_claim) == [])

not_click = [nd(u"任务甲（1/1）", 203, 1225, 816, 1275),
             nd(u"领取", 814, 1242, 1031, 1321, clickable=False)]
check("C16 不可点的【领取】不算", parse_claim_buttons(not_click) == [])

two = screen(row(u"任务甲（1/1）", btn=u"领取", idx=0),
             row(u"任务乙（1/1）", btn=u"领取", idx=1))
check("C17 多个【领取】按 y 升序",
      [c["cy"] for c in parse_claim_buttons(two)] == [1286, 1489],
      "got %s" % [c["cy"] for c in parse_claim_buttons(two)])

# ================================================================ D
print("\n--- D. 页面判定 ---")
HOME = load("_fixture_pp_home.xml")
KK2 = load("_fixture_pp_kk2.xml")
PAGE = load("_fixture_pp_page.xml")
SELF = load("_fixture_pp_self.xml")
AC0 = load("_fixture_pp_allchan0.xml")
AC1 = load("_fixture_pp_allchan1.xml")
AC2 = load("_fixture_pp_allchan2.xml")
AC3 = load("_fixture_pp_allchan3.xml")

check("D1 拍拍二手页 is_pp_page", is_pp_page(PAGE))
check("D2 自营页也是拍拍二手页", is_pp_page(SELF))
check("D3 首页不是拍拍二手页", not is_pp_page(HOME))
check("D4 全部频道页不是拍拍二手页", not is_pp_page(AC1))
check("D5 自营页 is_self_page", is_self_page(SELF))
check("D6 拍拍二手推荐页不是自营页", not is_self_page(PAGE))
check("D7 首页不是自营页", not is_self_page(HOME))
check("D8 弹层 has_task_panel", has_task_panel(PN))
check("D9 自营页不是弹层（背后有【赚更多京豆】也不算）", not has_task_panel(SELF))
check("D10 拍拍二手页不是弹层", not has_task_panel(PAGE))
check("D11 首页不是弹层", not has_task_panel(HOME))
check("D12 空节点全 False",
      not has_task_panel([]) and not is_pp_page([]) and not is_self_page([]))
check("D13 弹层标题常量", PANEL_MARK == u"做任务领京豆")
check("D14 【赚更多京豆】不算弹层标记",
      not has_task_panel([nd(MORE_BEAN, 46, 1343, 500, 1423, clickable=True)]))

# ================================================================ E
print("\n--- E. pick_target 安全区 ---")
check("E1 安全区常量", 1000 < SAFE_TOP < SAFE_BOTTOM <= 2340,
      "SAFE_TOP=%d SAFE_BOTTOM=%d" % (SAFE_TOP, SAFE_BOTTOM))
check("E2 上界在弹层标题栏（y≈1005~1156）之下", SAFE_TOP >= 1160,
      "SAFE_TOP=%d" % SAFE_TOP)
check("E3 下界容得下最后一行 (y2=2331)", SAFE_BOTTOM >= 2331,
      "SAFE_BOTTOM=%d" % SAFE_BOTTOM)

t, why = pick_target(rows, set())
check("E4 夹具第一行被选中", t is not None and t["title"] == u"逛便宜包邮频道（0/1）",
      "why=%s" % why)
t, why = pick_target(rows, set(titles))
check("E5 都试过 -> none", t is None and why == "none", "why=%s" % why)
t, _ = pick_target(rows, set([titles[0]]))
check("E6 跳过试过的", t is not None and t["title"] == titles[1])

below = parse_task_rows(screen(row(u"下方任务（0/1）", idx=6)))
t, why = pick_target(below, set())
check("E7 越下界 -> below", t is None and why == "below", "why=%s" % why)
above = parse_task_rows(screen(row(u"上方任务（0/1）", idx=-2)))
t, why = pick_target(above, set())
check("E8 越上界 -> above", t is None and why == "above", "why=%s" % why)
check("E9 空列表 -> none", pick_target([], set()) == (None, "none"))

# ================================================================ F
print("\n--- F. find_self_tab / find_more_bean / clickable_ancestor ---")
st = find_self_tab(PAGE)
check("F1 拍拍二手页找到【自营】tab", st is not None)
check("F2 位置 (836,378,975,432)", st and st["bounds"] == (836, 378, 975, 432),
      "got %s" % (st and st["bounds"],))
check("F3 【自营】文字不可点", st is not None and not st["clickable"])
box = clickable_ancestor(PAGE, st)
check("F4 可点祖先 (807,225,1003,439)", box == (807, 225, 1003, 439), "got %s" % (box,))
check("F5 点文字中心 (905,405)",
      ((st["bounds"][0] + st["bounds"][2]) // 2,
       (st["bounds"][1] + st["bounds"][3]) // 2) == (905, 405))
check("F6 自营页【自营】tab 已重排到 (471,372,610,430)",
      find_self_tab(SELF)["bounds"] == (471, 372, 610, 430),
      "got %s" % (find_self_tab(SELF)["bounds"],))
check("F7 首页没有【自营】tab", find_self_tab(HOME) is None)
check("F8 全部频道页没有【自营】tab", find_self_tab(AC1) is None)

mb = find_more_bean(SELF)
check("F9 自营页找到【赚更多京豆】", mb is not None)
check("F10 位置 (46,1343,500,1423)", mb and mb["bounds"] == (46, 1343, 500, 1423),
      "got %s" % (mb and mb["bounds"],))
check("F11 【赚更多京豆】自己就可点", mb and mb["clickable"])
check("F12 拍拍二手推荐页没有【赚更多京豆】", find_more_bean(PAGE) is None)
check("F13 首页没有【赚更多京豆】", find_more_bean(HOME) is None)
check("F14 空节点返回 None", find_self_tab([]) is None and find_more_bean([]) is None)
check("F15 弹层打开时背后【赚更多京豆】仍在 dump 里（所以不能拿它判弹层）",
      find_more_bean(PN) is not None)

pp = [n for n in AC3 if n["text"] == PP_DESC]
check("F16 全部频道底部找到【拍拍二手】文字", len(pp) == 1)
check("F17 位置 (77,2169,231,2216)", pp and pp[0]["bounds"] == (77, 2169, 231, 2216),
      "got %s" % (pp and pp[0]["bounds"],))
box2 = clickable_ancestor(AC3, pp[0])
check("F18 可点祖先 (55,2070,253,2216)", box2 == (55, 2070, 253, 2216), "got %s" % (box2,))
check("F19 祖先中心 (154,2143) 在底部导航(y>=2169)之上",
      ((box2[0] + box2[2]) // 2, (box2[1] + box2[3]) // 2) == (154, 2143))
check("F20 空节点返回 None", clickable_ancestor([], nd(u"x", 0, 0, 10, 10)) is None)

# ================================================================ G
print("\n--- G. _reveal_tab ---")


class SwipeUI(FakeUI):
    def __init__(self, screens):
        FakeUI.__init__(self)
        self.screens = screens
        self.idx = 0

    def nodes(self):
        return self.screens[min(self.idx, len(self.screens) - 1)]

    def adb_swipe(self, x1, y1, x2, y2, duration=300):
        self.swipes.append((x1, y1, x2, y2))
        self.idx += 1


m = Task10Paipai()
ui = SwipeUI([AC2, AC2])
log = Log()
node, ns = m._reveal_tab(ui, log, AC2, USED_TAB)
check("G1 已进屏直接返回", node is not None and node["bounds"] == (921, 368, 1067, 470),
      "got %s" % (node and node["bounds"],))
check("G2 已进屏不滑动", ui.swipes == [], "got %s" % (ui.swipes,))

ui = SwipeUI([AC2, AC2])
log = Log()
node, ns = m._reveal_tab(ui, log, AC1, USED_TAB)
check("G3 屏外会横滑", len(ui.swipes) >= 1, "swipes=%d" % len(ui.swipes))
check("G4 滑一次就拿到节点", node is not None and node["bounds"] == (921, 368, 1067, 470))
check("G5 滑动行 y=419（【二手】自己的 cy）",
      ui.swipes and ui.swipes[0][1] == 419, "got %s" % (ui.swipes[:1],))
check("G6 滑动写进日志", u"左滑" in log.text(), log.text()[-200:])

ui = SwipeUI([AC1] * 8)
log = Log()
node, ns = m._reveal_tab(ui, log, AC1, USED_TAB, max_swipes=3)
check("G7 一直滑不出来返回 None", node is None)
check("G8 滑动次数有上限", len(ui.swipes) == 3, "swipes=%d" % len(ui.swipes))
check("G9 会写 WARN", u"仍在屏外" in log.text(), log.text()[-200:])

# ================================================================ H
print("\n--- H. _tap_label / _tap_node ---")


class TapUI(FakeUI):
    def __init__(self, ns):
        FakeUI.__init__(self)
        self.ns = ns

    def nodes(self):
        return self.ns


ui = TapUI(AC0)
log = Log()
check("H1 点【发现好物】成功", m._tap_label(ui, log, AC0, FIND_GOODS, u"全部频道页") is True)
check("H2 点的是 (937,466)", ui.taps and ui.taps[0] == (937, 466),
      "got %s" % (ui.taps[:1],))

ui = TapUI(AC2)
log = Log()
check("H3 点【二手】成功", m._tap_label(ui, log, AC2, USED_TAB, u"全部频道页") is True)
check("H4 点的是 (994,419)", ui.taps and ui.taps[0] == (994, 419),
      "got %s" % (ui.taps[:1],))

ui = TapUI(AC3)
log = Log()
check("H5 点【拍拍二手】成功", m._tap_label(ui, log, AC3, PP_DESC, u"全部频道页") is True)
check("H6 点的是可点祖先中心 (154,2143)", ui.taps and ui.taps[0] == (154, 2143),
      "got %s" % (ui.taps[:1],))

log = Log()
check("H7 找不到标签返回 False",
      m._tap_label(FakeUI(), log, AC3, u"不存在的标签", u"全部频道页") is False)
check("H8 找不到会写日志", u"没找到" in log.text())

# _find_label 取 y 最小的那个（【发现好物】有 tab 和区块标题两处）
fg_nodes = m._find_label(AC1, FIND_GOODS)
check("H9 _find_label 取最上面那个【发现好物】(849,231,1025,371)",
      fg_nodes is not None and fg_nodes["bounds"] == (849, 231, 1025, 371),
      "got %s" % (fg_nodes and fg_nodes["bounds"],))

# ================================================================ I
print("\n--- I. 入口链路 _open_pp ---")


class EntryUI(FakeUI):
    """首页 / 金刚区 / 全部频道三级 / 拍拍二手页 的可控替身。"""

    def __init__(self, home, kk2, ac0, ac1, ac2, ac3, ppage,
                 kk1_has=False, kk2_has=True, kk1_tap_bad=False):
        FakeUI.__init__(self)
        self.home = home
        self.kk2 = kk2
        self.ac0 = ac0
        self.ac1 = ac1
        self.ac2 = ac2
        self.ac3 = ac3
        self.ppage = ppage
        self.kk1_has = kk1_has
        self.kk2_has = kk2_has
        self.kk1_tap_bad = kk1_tap_bad
        self.page = "home"
        self.kk_page = 1

    def nodes(self):
        return {"home": self.kk2 if self.kk_page == 2 else self.home,
                "allchan0": self.ac0, "allchan1": self.ac1,
                "allchan2": self.ac2, "allchan3": self.ac3,
                "pp": self.ppage}.get(self.page, [])

    def _stable_kingkong_icon(self, desc, tries=4):
        if self.page != "home":
            return None, False
        if self.kk_page == 1 and self.kk1_has:
            return {"desc": desc, "bounds": (435, 440, 651, 601),
                    "clickable": True, "cy": 520}, True
        if self.kk_page == 2 and self.kk2_has:
            return {"desc": desc, "bounds": (867, 763, 1080, 924),
                    "clickable": True, "cy": 843}, True
        return None, False

    def swipe_kingkong(self, direction="left", pause=1.5):
        self.kk_swipes.append(direction)
        self.kk_page = 2 if direction == "left" else 1

    def adb_swipe(self, x1, y1, x2, y2, duration=300):
        self.swipes.append((x1, y1, x2, y2))
        if self.page == "allchan1" and abs(y1 - y2) < 20:
            self.page = "allchan2"      # 二级 tab 横滑一次就露出来

    def adb_tap(self, pos, pause=1.5):
        self.taps.append(pos)
        if self.page == "home":
            if self.kk_page == 1 and pos == (543, 520) and not self.kk1_tap_bad:
                self.page = "pp"
            elif self.kk_page == 2 and pos == (973, 843):
                self.page = "pp"
            elif pos == (973, 1004):
                self.page = "allchan0"
        elif self.page == "allchan0":
            if pos == (937, 466):
                self.page = "allchan1"
        elif self.page == "allchan1":
            pass
        elif self.page == "allchan2":
            if pos == (994, 419):
                self.page = "allchan3"
        elif self.page == "allchan3":
            if pos == (154, 2143):
                self.page = "pp"

    def tap(self, pos, pause=1.5):
        self.adb_tap(pos, pause)

    def goto_home(self):
        FakeUI.goto_home(self)
        self.page = "home"
        self.kk_page = 1
        return True


ui = EntryUI(HOME, KK2, AC0, AC1, AC2, AC3, PAGE, kk1_has=True)
log = Log()
check("I1 金刚区第1页直接进", m._open_pp(ui, log, cold=True) is True, log.text()[-300:])
check("I2 冷启动了一次", ui.restart_calls == 1)
check("I3 点的是第1页图标中心 (543,520)", ui.taps and ui.taps[0] == (543, 520),
      "got %s" % (ui.taps[:1],))
check("I4 进页面等了 3s", PP_PAGE_WAIT in ui.sleeps, "sleeps=%s" % (ui.sleeps[:6],))
check("I5 没翻第2页", "left" not in ui.kk_swipes, "got %s" % ui.kk_swipes)

ui = EntryUI(HOME, KK2, AC0, AC1, AC2, AC3, PAGE, kk1_has=False)
log = Log()
check("I6 第1页没有就翻第2页", m._open_pp(ui, log, cold=True) is True, log.text()[-300:])
check("I7 确实左滑了一次", "left" in ui.kk_swipes)
check("I8 第2页点的是 (973,843)", (973, 843) in ui.taps, "got %s" % (ui.taps,))
check("I9 日志写明第 2 页",
      any(u"金刚区第 2 页命中" in t for _, t in log.lines), log.text()[-300:])

ui = EntryUI(HOME, KK2, AC0, AC1, AC2, AC3, PAGE, kk1_has=False, kk2_has=False)
log = Log()
check("I10 两页都没有走全部频道兜底", m._open_pp(ui, log, cold=True) is True,
      log.text()[-500:])
check("I11 点了【全部频道】(973,1004)", (973, 1004) in ui.taps, "got %s" % (ui.taps,))
check("I12 点了【发现好物】(937,466)", (937, 466) in ui.taps, "got %s" % (ui.taps,))
check("I13 二级 tab 横滑过", len(ui.swipes) >= 1, "swipes=%s" % (ui.swipes,))
check("I14 点了【二手】(994,419)", (994, 419) in ui.taps, "got %s" % (ui.taps,))
check("I15 点了【拍拍二手】(154,2143)", (154, 2143) in ui.taps, "got %s" % (ui.taps,))
check("I16 日志提示走了兜底",
      any(u"全部频道" in t and u"WARN" == lv for lv, t in log.lines), log.text()[-400:])

# 点歪了：第1页点了没进，继续走第2页
ui = EntryUI(HOME, KK2, AC0, AC1, AC2, AC3, PAGE, kk1_has=True, kk1_tap_bad=True)
log = Log()
check("I17 第1页点歪后继续下一级", m._open_pp(ui, log, cold=True) is True,
      log.text()[-400:])
check("I18 第1页点歪会写 WARN",
      any(u"没进拍拍二手页" in t for _, t in log.lines), log.text()[-400:])

# 非冷启动：先右滑回第 1 页
ui = EntryUI(HOME, KK2, AC0, AC1, AC2, AC3, PAGE, kk1_has=True)
log = Log()
check("I19 非冷启动走 goto_home", m._open_pp(ui, log, cold=False) is True)
check("I20 非冷启动先右滑回第1页", ui.kk_swipes and ui.kk_swipes[0] == "right",
      "got %s" % (ui.kk_swipes,))

# ================================================================ J
print("\n--- J. _open_self ---")


class SelfUI(FakeUI):
    def __init__(self, before, after, tap_ok=True, need_scroll=False):
        FakeUI.__init__(self)
        self.before = before
        self.after = after
        self.tap_ok = tap_ok
        self.need_scroll = need_scroll
        self.switched = False
        self.scrolled = 0

    def nodes(self):
        return self.after if self.switched else self.before

    def adb_swipe(self, x1, y1, x2, y2, duration=300):
        self.swipes.append((x1, y1, x2, y2))
        self.scrolled += 1
        if self.need_scroll and self.scrolled >= 2:
            self.before = self.after

    def adb_tap(self, pos, pause=1.5):
        self.taps.append(pos)
        if self.tap_ok and pos == (905, 405):
            self.switched = True


ui = SelfUI(PAGE, SELF)
log = Log()
check("J1 点【自营】tab 成功", m._open_self(ui, log) is True, log.text()[-300:])
check("J2 点的是文字中心 (905,405)", ui.taps and ui.taps[0] == (905, 405),
      "got %s" % (ui.taps[:1],))
check("J3 切完等 5s", SELF_TAB_WAIT in ui.sleeps, "sleeps=%s" % (ui.sleeps,))
check("J4 日志写了 tab 位置",
      any(u"命中【自营】tab" in t for _, t in log.lines), log.text()[-300:])

ui = SelfUI(PAGE, SELF, tap_ok=False)
log = Log()
check("J5 第一次点不动会重试一次", m._open_self(ui, log) is False)
check("J6 一共点了两次", len(ui.taps) == 2, "got %d" % len(ui.taps))
check("J7 会写 WARN", any(u"再点一次" in t for _, t in log.lines), log.text()[-300:])

# 已在自营页（tab 重排到 471..610）
ui = SelfUI(SELF, SELF)
log = Log()
check("J8 自营页里再点一次也能过",
      m._open_self(ui, log) is True and ui.taps[0] == (540, 401),
      "taps=%s" % (ui.taps[:1],))

# tab 行里找不到【自营】：横滑找
class SelfScrollUI(SelfUI):
    def nodes(self):
        if self.switched:
            return self.after
        if self.scrolled >= 1:
            return PAGE       # 滑一下【自营】就露出来了（同一份夹具）
        return [nd(u"推荐", 29, 378, 168, 432), nd(u"手机", 252, 378, 391, 432)]


ui = SelfScrollUI(PAGE, SELF)
log = Log()
check("J9 找不到【自营】会横滑 tab 行", m._open_self(ui, log) is True, log.text()[-300:])
check("J10 横滑过", len(ui.swipes) >= 1)

# ================================================================ K
print("\n--- K. _open_panel ---")


class PanelOpenUI(FakeUI):
    def __init__(self, before, after, tap_ok=True, scroll_to_find=False):
        FakeUI.__init__(self)
        self.before = before
        self.after = after
        self.tap_ok = tap_ok
        self.scroll_to_find = scroll_to_find
        self.opened = False
        self.scrolled = 0

    def nodes(self):
        if self.opened:
            return self.after
        if self.scroll_to_find and self.scrolled >= 2:
            return self.after
        return self.before

    def adb_swipe(self, x1, y1, x2, y2, duration=300):
        self.swipes.append((x1, y1, x2, y2))
        self.scrolled += 1

    def adb_tap(self, pos, pause=1.5):
        self.taps.append(pos)
        if self.tap_ok and pos == (273, 1383):
            self.opened = True


ui = PanelOpenUI(SELF, PN)
log = Log()
check("K1 点【赚更多京豆】打开弹层", m._open_panel(ui, log) is True, log.text()[-300:])
check("K2 点的是 (273,1383)", ui.taps and ui.taps[0] == (273, 1383),
      "got %s" % (ui.taps[:1],))
check("K3 日志写了弹层标题",
      any(PANEL_MARK in t for _, t in log.lines), log.text()[-300:])
check("K3b 弹层打开后把【直播回放】小窗拖到顶部",
      (952, 1418, 952, 210, 1500) in ui.drags, "drags=%s" % (ui.drags,))
check("K3c 小窗用 draganddrop 拖（不是 swipe）",
      ui.drags and not any(d[1] == 1418 and d[3] == 210 for d in ui.swipes),
      "swipes=%s" % (ui.swipes,))
check("K3d 日志写了拖小窗",
      any(u"直播回放" in t for _, t in log.lines), log.text()[-400:])

ui = PanelOpenUI(SELF, PN, tap_ok=False)
log = Log()
check("K4 第一次没弹出来会再点一次", m._open_panel(ui, log) is False)
check("K5 一共点了两次", len(ui.taps) == 2, "got %d" % len(ui.taps))

# 自营页【赚更多京豆】被滚动挪走了：滑动找
ui = PanelOpenUI([nd(u"每日领京豆", 46, 1156, 253, 1206)], PN, scroll_to_find=True)
log = Log()
check("K6 看不到【赚更多京豆】会滑动再找", m._open_panel(ui, log) is True,
      log.text()[-400:])
check("K7 滑动过", len(ui.swipes) >= 2)

ui = PanelOpenUI(PAGE, PN)
log = Log()
check("K8 推荐页没有【赚更多京豆】返回 False", m._open_panel(ui, log) is False)
check("K9 会写 WARN", any(u"始终没找到" in t for _, t in log.lines), log.text()[-300:])

# ================================================================ L
print("\n--- L. 任务循环 ---")


class PanelUI(FakeUI):
    """弹层 + 落地页 的状态机。

    rows: [[title, secs, state]]，state = 'do' / 'claim' / 'done'
    fail_idx: 第 i 行第一次点击不生效（模拟弹层动画吞点击）
    lose_at:  第 n 次 back 后弹层丢失（落到拍拍二手页）
    """

    def __init__(self, rows, fail_idx=(), lose_at=None, read_fail_at=None,
                 fail_always=False):
        FakeUI.__init__(self)
        self.rows = [list(r) for r in rows]
        self.fail_idx = set(fail_idx)
        self.fail_always = fail_always
        self.lose_at = lose_at
        self.read_fail_at = read_fail_at
        self.in_task = False
        self.cur = None
        self.backs_in_task = 0
        self.lost = False
        self.read_fails = 0
        self.tries = {}

    def _panel_nodes(self):
        out = [nd(PANEL_MARK, 330, 1052, 750, 1123)]
        for i, (title, secs, state) in enumerate(self.rows):
            y = 1225 + i * ROW_H
            out.append(nd(title, 203, y, 816, y + 50))
            out.append(nd(u"，浏览%ds可领" % secs, 203, y + 50, 701, y + 90))
            btn = {u"do": u"去完成", u"claim": u"领取", u"done": u"已完成"}[state]
            out.append(nd(btn, 814, y + 17, 1031, y + 106, clickable=True))
        return out

    def nodes(self):
        if self.read_fail_at is not None:
            self.read_fails += 1
            if self.read_fails >= self.read_fail_at:
                return []
        if self.in_task:
            return [nd(u"特价", 100, 100, 300, 200)]
        if self.lost:
            return [nd(u"自营", 471, 372, 610, 430),
                    nd(u"每日领京豆", 46, 1156, 253, 1206),
                    nd(MORE_BEAN, 46, 1343, 500, 1423, clickable=True)]
        return self._panel_nodes()

    def adb_tap(self, pos, pause=1.5):
        self.taps.append(pos)
        if self.lost:
            if pos == (273, 1383):
                self.lost = False        # 点【赚更多京豆】重开
            return
        if self.in_task:
            return
        for i, (title, secs, state) in enumerate(self.rows):
            y = 1225 + i * ROW_H
            if 814 <= pos[0] <= 1031 and y <= pos[1] <= y + 106:
                if state == u"do":
                    self.in_task = True
                    self.cur = i
                elif state == u"claim":
                    self.rows[i][2] = u"done"
                return

    def back(self, pause=2.0):
        self.backs += 1
        if not self.in_task:
            return
        self.in_task = False
        i = self.cur
        self.cur = None
        if i is None:
            return
        title = self.rows[i][0]
        n = self.tries.get(i, 0)
        self.tries[i] = n + 1
        if self.fail_always or (i in self.fail_idx and n == 0):
            self.backs_in_task += 1
            return                        # 点击没生效，进度不变
        self.rows[i][0] = re.sub(u"（0/1）", u"（1/1）", title)
        self.rows[i][2] = u"claim"
        if self.lose_at is not None and self.backs >= self.lose_at:
            self.lost = True


ROWS3 = [[u"任务甲（0/1）", 10, u"do"], [u"任务乙（0/1）", 10, u"do"],
         [u"任务丙（0/1）", 10, u"do"]]

ui = PanelUI([list(r) for r in ROWS3])
log = Log()
done = m._process_tasks(ui, log, __import__("threading").Event())
check("L1 三个任务都做完", done == 3, "got %d" % done)
check("L2 每个都停留 14s", ui.sleeps.count(14.0) == 3, "got %s" % ui.sleeps)
check("L3 每次做完 back 一次", ui.backs == 3, "got %d" % ui.backs)
check("L4 日志写了「已没有可做任务」",
      any(u"已没有可做任务" in t for _, t in log.lines), log.text()[-300:])

ui = PanelUI([list(r) for r in ROWS3])
log = Log()
done = m._process_tasks(ui, log, __import__("threading").Event())
check("L5 空跑（全部已完成）完成 0 个", PanelUI([], []).rows == [])

ui = PanelUI([[u"任务甲（1/1）", 10, u"done"], [u"任务乙（1/1）", 10, u"done"]])
log = Log()
done = m._process_tasks(ui, log, __import__("threading").Event())
check("L6 没有可做任务时完成 0 个", done == 0, "got %d" % done)
check("L7 没有可做任务也会滑到底确认一次", len(ui.swipes) >= 3,
      "swipes=%d" % len(ui.swipes))

# 第一次点击被吞 -> 允许重试一次
ui = PanelUI([[u"任务甲（0/1）", 10, u"do"]], fail_idx=(0,))
log = Log()
done = m._process_tasks(ui, log, __import__("threading").Event())
check("L8 首次点击被吞后重试成功", done == 1, "got %d" % done)
check("L9 重试会写日志",
      any(u"稍后重试" in t for _, t in log.lines), log.text()[-400:])
check("L10 重试时点了两次", len([t for t in ui.taps if t[0] == 922]) == 2,
      "taps=%s" % (ui.taps,))

# 连续两次失败 -> 放弃
ui = PanelUI([[u"任务甲（0/1）", 10, u"do"]], fail_always=True)
log = Log()
done = m._process_tasks(ui, log, __import__("threading").Event())
check("L11 连续失败 2 次会放弃", done == 0, "got %d" % done)
check("L12 放弃会写 WARN",
      any(u"放弃" in t for _, t in log.lines), log.text()[-400:])

# back 后落到拍拍二手页 -> _light_reopen 就地救回
ui = PanelUI([list(r) for r in ROWS3], lose_at=1)
log = Log()
done = m._process_tasks(ui, log, __import__("threading").Event())
check("L13 弹层丢失后能就地重开并做完", done == 3, "got %d" % done)
check("L14 就地重开点了【赚更多京豆】", (273, 1383) in ui.taps, "taps=%s" % (ui.taps,))
check("L15 日志写了就地重开",
      any(u"就地重开" in t for _, t in log.lines), log.text()[-500:])
check("L16 没有整链重进（restart 只发生 0 次）", ui.restart_calls == 0)

# 读不到页面
ui = PanelUI([list(r) for r in ROWS3], read_fail_at=1)
log = Log()
done = m._process_tasks(ui, log, __import__("threading").Event())
check("L17 一直读不到页面会收尾", done == 0, "got %d" % done)
check("L18 会写「读不到页面」",
      any(u"读不到页面" in t for _, t in log.lines), log.text()[-400:])

# ================================================================ M
print("\n--- M. 领取阶段 ---")


class ClaimUI(PanelUI):
    def __init__(self, rows, max_claim=None):
        PanelUI.__init__(self, rows)
        self.max_claim = max_claim
        self.pauses = []

    def adb_tap(self, pos, pause=1.5):
        self.pauses.append(pause)
        PanelUI.adb_tap(self, pos, pause)

    def nodes(self):
        if self.read_fail_at is not None:
            self.read_fails += 1
            if self.read_fails >= self.read_fail_at:
                return []
        return self._panel_nodes()


ui = ClaimUI([[u"任务甲（1/1）", 10, u"claim"], [u"任务乙（1/1）", 10, u"claim"]])
log = Log()
claimed = m._claim_once(ui, log, __import__("threading").Event())
check("M1 一屏领 2 个", claimed == 2, "got %d" % claimed)
check("M2 每次点完等 1s", ui.pauses and all(p == CLAIM_WAIT for p in ui.pauses),
      "pauses=%s" % (ui.pauses,))
check("M3 领完都变已完成",
      [r[2] for r in ui.rows] == [u"done", u"done"], "got %s" % [r[2] for r in ui.rows])
check("M4 领完再调一次返回 0",
      m._claim_once(ui, log, __import__("threading").Event()) == 0)

ui = ClaimUI([[u"任务甲（1/1）", 10, u"claim"]])
log = Log()
claimed = m._claim_all(ui, log, __import__("threading").Event())
check("M5 _claim_all 领到 1 个", claimed == 1, "got %d" % claimed)
check("M6 _claim_all 先回顶部", len(ui.swipes) >= 1, "swipes=%d" % len(ui.swipes))
check("M7 日志写了领取次数",
      any(u"领取阶段共领取 1 次" in t for _, t in log.lines), log.text()[-300:])

ui = ClaimUI([[u"任务甲（1/1）", 10, u"done"]])
log = Log()
check("M8 没有待领取时领 0 个",
      m._claim_all(ui, log, __import__("threading").Event()) == 0)

ui = ClaimUI([], )
log = Log()
check("M9 空弹层领 0 个",
      m._claim_once(ui, log, __import__("threading").Event()) == 0)

# 点不动：同一坐标连点两次不变就跳过
class StuckUI(ClaimUI):
    def adb_tap(self, pos, pause=1.5):
        self.taps.append(pos)          # 不推进状态


ui = StuckUI([[u"任务甲（1/1）", 10, u"claim"], [u"任务乙（1/1）", 10, u"claim"]])
log = Log()
claimed = m._claim_once(ui, log, __import__("threading").Event(), max_clicks=6)
check("M10 点不动会跳过换下一个", claimed >= 2 and len(set(ui.taps)) >= 2,
      "claimed=%d taps=%s" % (claimed, ui.taps))

# ================================================================ N
print("\n--- N. _recover_panel / _light_reopen ---")


class RecUI(FakeUI):
    """可控恢复场景：panel / self / pp / task 四种页面。"""

    def __init__(self, start="task", back_to="self"):
        FakeUI.__init__(self)
        self.page = start
        self.back_to = back_to

    def nodes(self):
        if self.page == "panel":
            return [nd(PANEL_MARK, 330, 1052, 750, 1123),
                    nd(u"任务甲（0/1）", 203, 1225, 816, 1275),
                    nd(u"，浏览10s可领", 203, 1275, 701, 1315),
                    nd(u"去完成", 814, 1242, 1031, 1321, clickable=True)]
        if self.page == "self":
            return [nd(u"自营", 471, 372, 610, 430),
                    nd(u"每日领京豆", 46, 1156, 253, 1206),
                    nd(MORE_BEAN, 46, 1343, 500, 1423, clickable=True)]
        if self.page == "pp":
            return [nd(u"自营", 836, 378, 975, 432),
                    nd(u"推荐", 29, 378, 168, 432)]
        return [nd(u"特价", 100, 100, 300, 200)]

    def adb_tap(self, pos, pause=1.5):
        self.taps.append(pos)
        if self.page in ("self", "pp") and pos == (273, 1383):
            self.page = "panel"
        if self.page == "pp" and pos == (905, 405):
            self.page = "self"

    def back(self, pause=2.0):
        self.backs += 1
        if self.page == "task":
            self.page = self.back_to


ui = RecUI("panel")
log = Log()
check("N1 弹层在时直接 True", m._recover_panel(ui, log) is True)
check("N2 弹层在时不 back", ui.backs == 0)

ui = RecUI("task", back_to="self")
log = Log()
check("N3 back 落到自营页 -> 点【赚更多京豆】救回", m._recover_panel(ui, log) is True,
      log.text()[-400:])
check("N4 点的是 (273,1383)", (273, 1383) in ui.taps, "taps=%s" % (ui.taps,))

ui = RecUI("task", back_to="pp")
log = Log()
check("N5 back 落到拍拍二手页 -> 先点【自营】再点【赚更多京豆】",
      m._recover_panel(ui, log) is True, log.text()[-500:])
check("N6 点过【自营】tab (905,405)", (905, 405) in ui.taps, "taps=%s" % (ui.taps,))
check("N7 也点过【赚更多京豆】", (273, 1383) in ui.taps, "taps=%s" % (ui.taps,))
check("N8 日志写了退到拍拍二手页",
      any(u"退到拍拍二手页" in t for _, t in log.lines), log.text()[-400:])

ui = RecUI("task", back_to="task")
log = Log()
check("N9 一直回不到弹层返回 False", m._recover_panel(ui, log) is False)
check("N10 会写 WARN", any(u"分级恢复失败" in t for _, t in log.lines))
check("N11 最多 back 两次", ui.backs == 2, "got %d" % ui.backs)

check("N12 _light_reopen 在弹层上直接 True",
      m._light_reopen(RecUI("panel"), Log()) is True)
check("N13 _light_reopen 在落地页返回 False",
      m._light_reopen(RecUI("task"), Log()) is False)

ui = RecUI("self")
log = Log()
check("N14 _light_reopen 成功后也拖小窗",
      m._light_reopen(ui, log) is True
      and (952, 1418, 952, 210, 1500) in ui.drags, "drags=%s" % (ui.drags,))

# ================================================================ O
print("\n--- O. stop_event ---")
stop = threading.Event()
stop.set()
ui = PanelUI([list(r) for r in ROWS3])
log = Log()
check("O1 已停止时不做任务", m._process_tasks(ui, log, stop) == 0)
check("O2 已停止时不点击", ui.taps == [], "taps=%s" % (ui.taps,))

ui = ClaimUI([[u"任务甲（1/1）", 10, u"claim"]])
log = Log()
check("O3 已停止时不领取", m._claim_once(ui, log, stop) == 0)
check("O4 已停止时 _claim_all 也不领",
      m._claim_all(ui, log, stop) == 0)

# ================================================================ P
print("\n--- P. run() 整体 ---")


class FullUI(EntryUI):
    """首页 -> 拍拍二手 -> 自营 -> 弹层 -> 任务 -> 领取 的完整替身。"""

    def __init__(self, rows):
        EntryUI.__init__(self, HOME, KK2, AC0, AC1, AC2, AC3, PAGE, kk1_has=True)
        self.rows = [list(r) for r in rows]
        self.stage = "pp"
        self.in_task = False
        self.cur = None

    def _panel_nodes(self):
        out = [nd(PANEL_MARK, 330, 1052, 750, 1123)]
        for i, (title, secs, state) in enumerate(self.rows):
            y = 1225 + i * ROW_H
            out.append(nd(title, 203, y, 816, y + 50))
            out.append(nd(u"，浏览%ds可领" % secs, 203, y + 50, 701, y + 90))
            btn = {u"do": u"去完成", u"claim": u"领取", u"done": u"已完成"}[state]
            out.append(nd(btn, 814, y + 17, 1031, y + 106, clickable=True))
        return out

    def nodes(self):
        if self.page == "home":
            return self.home
        if self.page == "pp":
            if self.stage == "pp":
                return PAGE
            if self.in_task:
                return [nd(u"特价", 100, 100, 300, 200)]
            return self._panel_nodes()
        return PAGE

    def adb_tap(self, pos, pause=1.5):
        self.taps.append(pos)
        if self.page == "home":
            if pos == (543, 520):
                self.page = "pp"
                self.stage = "pp"
            return
        if self.page != "pp":
            return
        if self.stage == "pp":
            if pos == (905, 405):
                self.stage = "self"
            return
        if self.in_task:
            return
        for i, (title, secs, state) in enumerate(self.rows):
            y = 1225 + i * ROW_H
            if 814 <= pos[0] <= 1031 and y <= pos[1] <= y + 106:
                if state == u"do":
                    self.in_task = True
                    self.cur = i
                elif state == u"claim":
                    self.rows[i][2] = u"done"
                return

    def back(self, pause=2.0):
        self.backs += 1
        if self.in_task:
            self.in_task = False
            i = self.cur
            self.cur = None
            if i is not None:
                self.rows[i][0] = re.sub(u"（0/1）", u"（1/1）", self.rows[i][0])
                self.rows[i][2] = u"claim"

    def _stable_kingkong_icon(self, desc, tries=4):
        if self.page != "home":
            return None, False
        return {"desc": desc, "bounds": (435, 440, 651, 601),
                "clickable": True, "cy": 520}, True

    def restart_to_home(self, wait=6):
        FakeUI.restart_to_home(self)
        self.page = "home"
        return True


# 注意：stage=pp 时 nodes() 返回 PAGE，而 _open_self 之后要看 SELF。
class FullUI2(FullUI):
    def nodes(self):
        if self.page == "home":
            return self.home
        if self.stage == "pp":
            return PAGE
        if self.stage == "self":
            return SELF
        if self.in_task:
            return [nd(u"特价", 100, 100, 300, 200)]
        return self._panel_nodes()

    def adb_tap(self, pos, pause=1.5):
        self.taps.append(pos)
        if self.page == "home":
            if pos == (543, 520):
                self.page = "pp"
            return
        if self.stage == "pp":
            if pos == (905, 405):
                self.stage = "self"
            return
        if self.stage == "self":
            if pos == (273, 1383):
                self.stage = "panel"
            return
        if self.in_task:
            return
        for i, (title, secs, state) in enumerate(self.rows):
            y = 1225 + i * ROW_H
            if 814 <= pos[0] <= 1031 and y <= pos[1] <= y + 106:
                if state == u"do":
                    self.in_task = True
                    self.cur = i
                elif state == u"claim":
                    self.rows[i][2] = u"done"
                return

    def back(self, pause=2.0):
        self.backs += 1
        if self.in_task:
            self.in_task = False
            i = self.cur
            self.cur = None
            if i is not None:
                self.rows[i][0] = re.sub(u"（0/1）", u"（1/1）", self.rows[i][0])
                self.rows[i][2] = u"claim"


ui = FullUI2([[u"任务甲（0/1）", 10, u"do"]])
log = Log()
# run() 里会 new 一个真 JDUI，这里换成我们的替身，彻底离线
_orig_jdui = MOD.JDUI
_orig_drv = MOD.driver.get_driver
MOD.driver.get_driver = lambda: None
MOD.JDUI = lambda d, l, s: ui
try:
    Task10Paipai().run(log, threading.Event())
    ok = True
    err = ""
except Exception as e:
    ok = False
    err = "%s: %s" % (type(e).__name__, e)
check("P1 run() 正常结束", ok, err)
check("P2 日志有 DONE", any(lv == "DONE" for lv, _ in log.lines), log.text()[-400:])
check("P3 DONE 写了完成 1 个任务、领取 1 次",
      any(u"完成 1 个浏览任务" in t and u"领取 1 次奖励" in t for lv, t in log.lines),
      log.text()[-400:])
check("P4 任务行变已完成",
      ui.rows[0][2] == u"done", "got %s" % (ui.rows[0][2],))
check("P5 弹层打开后等过 2s（防动画吞点击）", 2.0 in ui.sleeps, "sleeps=%s" % ui.sleeps[:8])
check("P6 进页面等了 3s、切 tab 等了 5s",
      PP_PAGE_WAIT in ui.sleeps and SELF_TAB_WAIT in ui.sleeps)
check("P6b run() 里也拖了【直播回放】小窗",
      (952, 1418, 952, 210, 1500) in ui.drags, "drags=%s" % (ui.drags,))


# 入口失败要抛 RuntimeError
class NoPPUI(FullUI2):
    def _stable_kingkong_icon(self, desc, tries=4):
        return None, False

    def nodes(self):
        return HOME

    def goto_home(self):
        self.home_calls += 1
        return True


ui = NoPPUI([])
log = Log()
MOD.JDUI = lambda d, l, s: ui
try:
    Task10Paipai().run(log, threading.Event())
    ok2 = False
    err2 = "没有抛异常"
except RuntimeError as e:
    ok2 = u"拍拍二手" in str(e)
    err2 = str(e)
check("P7 进不去拍拍二手要抛 RuntimeError", ok2, err2)

MOD.JDUI = _orig_jdui
MOD.driver.get_driver = _orig_drv


# ================================================================ 汇总
print("\n" + "=" * 60)
print("通过 %d / 失败 %d / 共 %d" % (len(PASSED), len(FAILED), len(PASSED) + len(FAILED)))
if FAILED:
    print("失败用例：")
    for f in FAILED:
        print("   - %s" % f)
    sys.exit(1)
print("全部通过")
