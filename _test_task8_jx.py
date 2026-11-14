# -*- coding: utf-8 -*-
"""京喜自营 模块离线回归（不连手机、不连 Appium）。

覆盖：
  A. X+4 停留换算
  B. 真机夹具上的任务行配对（标题 / 浏览Ns可领 / 按钮 / 可做判定）
  C. 合成节点上的配对细节（已完成/无描述/屏外退化/标题优先带进度）
  D. 【领取】按钮识别（必须同行有 (N/M) 标题，排除【领 121 京豆】浮层）
  E. pick_target 安全区判定
  F. has_task_panel
  G. find_bean_entry（【领 N 京豆】文案带空格）
  H. find_wp_bean_text + clickable_ancestor（【去领取】不是文本节点）
  I. _tap_label（全部频道 -> 优惠权益 -> 京喜自营）
  J. 入口链路 _open_jx（金刚区第1页 / 第2页 / 全部频道兜底）
  K. _open_wp（点【去领取】进王牌秒杀页）
  L. _open_panel（【领N京豆】要等 2~3 秒才出现）
  M. 任务循环（做完变领取、回不来先轻量重开、滚动、读失败收尾）
  N. 领取阶段（点一个等 1 秒、原地不跳页、全表扫）
  O. _recover_panel / _reenter
  P. stop_event

夹具（真机 1080x2340，2026-11-12 抓的）：
  _fixture_jx_home.xml     京东首页金刚区第1页（desc='京喜自营' 在 (581,440,775,601)）
  _fixture_jx_kk2.xml      金刚区第2页（含【全部频道】）
  _fixture_jx_allchan.xml  全部频道页（点完【优惠权益】tab 后，京喜自营在 y≈585）
  _fixture_jx_page.xml     京喜自营页（王牌秒杀 + 最高121京豆）
  _fixture_jx_wp.xml       王牌秒杀页（右侧【领 121 京豆】浮层按钮）
  _fixture_jx_panel.xml    做任务领京豆 任务弹层（含 1 个【领取】）
"""
import io
import re
import sys
import threading
import xml.etree.ElementTree as ET

sys.path.insert(0, ".")

from modules.task8_jx_self import (
    Task8JxSelf, browse_seconds, parse_task_rows, parse_claim_buttons, pick_target,
    has_task_panel, find_bean_entry, find_wp_bean_text, clickable_ancestor, row_sig,
    BROWSE_EXTRA, SAFE_TOP, SAFE_BOTTOM, CLAIM_WAIT, BEAN_ENTRY_TRIES, MAX_REENTER,
    PANEL_MARK, JX_DESC, BENEFIT_TAB, ALL_CHANNEL,
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


def row(title, secs=10, btn=u"去完成", y=1690):
    """按真机行结构造一行（京喜自营弹层）。

    真机：标题 [203,1884][737,1933]，描述 [203,1950][431,1991]，
    「，浏览10s可领」[429,1950][643,1991]，按钮 [814,1900][1031,1980]。
    """
    return [
        nd(title, 203, y, 737, y + 49),
        nd(u"最高抽30元红包", 203, y + 66, 431, y + 107),
        nd(u"，浏览%ds可领" % secs, 429, y + 66, 643, y + 107),
        nd(btn, 814, y + 16, 1031, y + 96, clickable=True),
    ]


def screen(*rows):
    out = []
    for r in rows:
        out.extend(r)
    return out


MARK = [nd(PANEL_MARK, 330, 916, 750, 990)]
# 「页面在、但弹层没了」的真实样子
NO_PANEL = [nd(u"王牌秒杀", 0, 234, 1080, 2340),
            nd(u"领 121 京豆", 918, 1603, 1058, 1746, clickable=True)]


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


class PanelUI(FakeUI):
    """模拟【做任务领京豆】弹层 + 浏览落地页。

    state: 'todo'（去完成）-> 点下去 away=True -> back 后变 'claim'（领取）
           -> 点【领取】变 'done'（已完成）
    """

    def __init__(self, tasks, completes=True, stay_away=False, fail_reads=0,
                 scrollable=False, claim_sticks=False):
        FakeUI.__init__(self)
        self.tasks = [dict(t) for t in tasks]
        self.completes = completes
        self.stay_away = stay_away
        self.fail_reads = fail_reads
        self.reads = 0
        self.away = False
        self.offset = 0
        self.scrollable = scrollable
        self.claim_sticks = claim_sticks      # True = 点【领取】没反应（测防死循环）

    def _btn_text(self, t):
        return {u"todo": u"去完成", u"claim": u"领取", u"done": u"已完成"}[t["state"]]

    def _rows(self):
        out = list(MARK)
        for t in self.tasks:
            y = t["y"] - self.offset
            out.append(nd(t["title"], 203, y, 737, y + 49))
            out.append(nd(u"最高抽30元红包", 203, y + 66, 431, y + 107))
            out.append(nd(u"，浏览%ds可领" % t["secs"], 429, y + 66, 643, y + 107))
            out.append(nd(self._btn_text(t), 814, y + 16, 1031, y + 96, clickable=True))
        return out

    def nodes(self):
        self.reads += 1
        if self.reads <= self.fail_reads:
            return []
        if self.away:
            return [nd(u"东东农场", 100, 200, 600, 300)]
        return self._rows()

    def adb_tap(self, pos, pause=1.5):
        self.taps.append(pos)
        if self.away:
            return
        for t in self.tasks:
            x1, y1 = 814, t["y"] - self.offset + 16
            x2, y2 = 1031, t["y"] - self.offset + 96
            if not (x1 <= pos[0] <= x2 and y1 <= pos[1] <= y2):
                continue
            if t["state"] == u"todo":
                self.away = True
                if self.completes:
                    t["state"] = u"claim"
                return
            if t["state"] == u"claim":
                if not self.claim_sticks:
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


# ================================================================ A
print("\n--- A. X+4 停留 ---")
check("A1 10s -> 14s", browse_seconds(10) == 14)
check("A2 5s -> 9s", browse_seconds(5) == 9)
check("A3 0s -> 4s", browse_seconds(0) == 4)
check("A4 BROWSE_EXTRA=4", BROWSE_EXTRA == 4)

# ================================================================ B
print("\n--- B. 真机夹具 _fixture_jx_panel.xml ---")
PN = load("_fixture_jx_panel.xml")
rows = parse_task_rows(PN)
check("B1 弹层识别", has_task_panel(PN))
check("B2 配出 2 行可做任务", len(rows) == 2, "got %d" % len(rows))
titles = [r["title"] for r in rows]
check("B3 标题正确", titles == [u"逛9.9包邮频道（0/1）", u"逛看病买药频道（0/1）"],
      "got %s" % titles)
check("B4 secs=10", all(r["secs"] == 10 for r in rows))
check("B5 按钮都是去完成", all(r["btn"] == u"去完成" for r in rows))
check("B6 按钮贴右", all(r["cx"] >= 800 for r in rows))
check("B7 按 y 升序", [r["cy"] for r in rows] == sorted(r["cy"] for r in rows))
check("B8 全角括号进度能识别", u"（0/1）" in titles[0])

claims = parse_claim_buttons(PN)
check("B9 认出 1 个【领取】", len(claims) == 1, "got %d" % len(claims))
check("B10 领取位置 (922,1738)", claims and (claims[0]["cx"], claims[0]["cy"]) == (922, 1738),
      "got %s" % ([(c["cx"], c["cy"]) for c in claims],))
check("B11 【领 121 京豆】浮层没被当成领取",
      all(c["cx"] != 988 or c["cy"] != 1674 for c in claims))
check("B12 row_sig 稳定",
      row_sig(rows) == row_sig(parse_task_rows(load("_fixture_jx_panel.xml"))))

# ================================================================ C
print("\n--- C. 合成节点配对 ---")
r1 = parse_task_rows(screen(row(u"逛超级补贴（0/1）", y=1690)))
check("C1 单行配出", len(r1) == 1)
check("C2 标题", r1 and r1[0]["title"] == u"逛超级补贴（0/1）")
check("C3 按钮中心", r1 and (r1[0]["cx"], r1[0]["cy"]) == (922, 1746),
      "got %s" % ((r1[0]["cx"], r1[0]["cy"]) if r1 else None,))

only_btn = [nd(u"去完成", 814, 1706, 1031, 1786, clickable=True)]
check("C4 没有【浏览Ns可领】不算任务行", parse_task_rows(only_btn) == [])

no_prog = parse_task_rows([nd(u"每邀一位好友助力领京豆", 203, 1545, 555, 1587),
                           nd(u"去完成", 814, 1496, 1031, 1576, clickable=True)])
check("C5 分享好友助力（无浏览Ns）不算", no_prog == [])

degen = [nd(u"逛超级补贴（0/1）", 203, 2431, 737, 2341),
         nd(u"，浏览10s可领", 429, 2431, 643, 2341),
         nd(u"去完成", 814, 2431, 1031, 2341, clickable=True)]
check("C6 退化节点被过滤", parse_task_rows(degen) == [])

left_btn = screen(row(u"逛超级补贴（0/1）", y=1690))
left_btn.append(nd(u"去完成", 200, 1700, 380, 1780, clickable=True))
r2 = parse_task_rows(left_btn)
check("C7 左侧【去完成】不算", len(r2) == 1 and r2[0]["cx"] == 922)

mixed = screen(row(u"任务甲（1/1）", btn=u"已完成", y=1500),
               row(u"任务乙（0/1）", y=1690),
               row(u"任务丙（0/1）", secs=10, y=1880))
r3 = parse_task_rows(mixed)
check("C8 已完成行不出现（只认逛一逛/去完成）",
      [r["title"] for r in r3] == [u"任务乙（0/1）", u"任务丙（0/1）"],
      "got %s" % [r["title"] for r in r3])
check("C9 丙 secs=10", r3[1]["secs"] == 10)
check("C10 半角括号也能识别",
      len(parse_task_rows(screen(row(u"某任务(0/1)", y=1690)))) == 1)

# ================================================================ D
print("\n--- D. 【领取】识别 ---")
claim_row = screen(row(u"逛9.9包邮频道（1/1）", btn=u"领取", y=1690))
c1 = parse_claim_buttons(claim_row)
check("D1 任务行领取能认出", len(c1) == 1 and (c1[0]["cx"], c1[0]["cy"]) == (922, 1746),
      "got %s" % ([(c["cx"], c["cy"]) for c in c1],))

float_btn = [nd(u"领 121 京豆", 918, 1603, 1058, 1746, clickable=True)]
check("D2 【领 121 京豆】不算领取", parse_claim_buttons(float_btn) == [])

lonely = [nd(u"领取", 814, 1706, 1031, 1786, clickable=True)]
check("D3 没有 (N/M) 标题的领取不算", parse_claim_buttons(lonely) == [])

left_claim = [nd(u"逛9.9包邮频道（1/1）", 203, 1690, 737, 1739),
              nd(u"领取", 200, 1706, 380, 1786, clickable=True)]
check("D4 左侧领取不算", parse_claim_buttons(left_claim) == [])

not_click = [nd(u"逛9.9包邮频道（1/1）", 203, 1690, 737, 1739),
             nd(u"领取", 814, 1706, 1031, 1786, clickable=False)]
check("D5 不可点的领取不算", parse_claim_buttons(not_click) == [])

two = screen(row(u"甲（1/1）", btn=u"领取", y=1500),
             row(u"乙（1/1）", btn=u"领取", y=1690))
c2 = parse_claim_buttons(two)
check("D6 多个领取按 y 升序", [c["cy"] for c in c2] == [1556, 1746],
      "got %s" % [c["cy"] for c in c2])
check("D7 立即领取不算",
      parse_claim_buttons([nd(u"逛9.9包邮频道（1/1）", 203, 1690, 737, 1739),
                           nd(u"立即领取", 814, 1706, 1031, 1786, clickable=True)]) == [])

# ================================================================ E
print("\n--- E. pick_target 安全区 ---")
check("E1 安全区常量", SAFE_TOP < SAFE_BOTTOM <= 2340,
      "SAFE_TOP=%d SAFE_BOTTOM=%d" % (SAFE_TOP, SAFE_BOTTOM))

two_rows = parse_task_rows(screen(row(u"任务甲（0/1）", y=1500),
                                  row(u"任务乙（0/1）", y=1690)))
t, why = pick_target(two_rows, set())
check("E2 安全区内的行被选中", t is not None and t["title"] == u"任务甲（0/1）", "why=%s" % why)

below = parse_task_rows(screen(row(u"任务下（0/1）", y=2260)))
t, why = pick_target(below, set())
check("E3 全在下方 -> 上滑", t is None and why == "below", "why=%s" % why)

above = parse_task_rows(screen(row(u"任务上（0/1）", y=1200)))
t, why = pick_target(above, set())
check("E4 全在上方 -> 下滑", t is None and why == "above", "why=%s" % why)

check("E5 没可做 -> none", pick_target([], set()) == (None, "none"))
t, why = pick_target(two_rows, set([u"任务甲（0/1）", u"任务乙（0/1）"]))
check("E6 都试过 -> none", t is None and why == "none")
t, _ = pick_target(two_rows, set([u"任务甲（0/1）"]))
check("E7 跳过试过的", t is not None and t["title"] == u"任务乙（0/1）")

# ================================================================ F/G
print("\n--- F. has_task_panel / G. find_bean_entry ---")
check("F1 有弹层标题 -> True", has_task_panel(MARK))
check("F2 有任务行 -> True", has_task_panel(screen(row(u"甲（0/1）", y=1690))))
check("F3 别的页面 -> False", not has_task_panel([nd(u"东东农场", 0, 0, 500, 500)]))
check("F4 空 -> False", not has_task_panel([]))
check("F5 王牌秒杀页不算弹层", not has_task_panel(load("_fixture_jx_wp.xml")))

WP = load("_fixture_jx_wp.xml")
e1 = find_bean_entry(WP)
check("G1 王牌秒杀页找到【领 121 京豆】", e1 is not None)
check("G2 文案带空格", e1 and e1["text"] == u"领 121 京豆", "got %r" % (e1 and e1["text"],))
check("G3 位置 (918,1603,1058,1746)", e1 and e1["bounds"] == (918, 1603, 1058, 1746),
      "got %s" % (e1 and e1["bounds"],))
check("G4 是可点 Button", e1 and e1["clickable"] and e1["class"] == "Button")
check("G5 首页没有这个按钮", find_bean_entry(load("_fixture_jx_home.xml")) is None)
check("G6 弹层里也没有（被盖住时不影响）",
      find_bean_entry(PN) is None or find_bean_entry(PN)["bounds"][1] > 0)

# ================================================================ H
print("\n--- H. 京喜自营页【去领取】 ---")
JXP = load("_fixture_jx_page.xml")
bt = find_wp_bean_text(JXP)
check("H1 找到「最高121京豆」", bt is not None)
check("H2 文案", bt and bt["text"] == u"最高121京豆", "got %r" % (bt and bt["text"],))
check("H3 位置", bt and bt["bounds"] == (79, 599, 231, 632), "got %s" % (bt and bt["bounds"],))
box = clickable_ancestor(JXP, bt)
check("H4 可点祖先是 (68,500,244,704)", box == (68, 500, 244, 704), "got %s" % (box,))
check("H5 可点祖先包住文字", box and box[0] <= 79 and box[1] <= 599
      and box[2] >= 231 and box[3] >= 632)
check("H6 祖先比自己大（说明去领取在它下半部分）",
      box and (box[3] - box[1]) > (bt["bounds"][3] - bt["bounds"][1]))
check("H7 王牌秒杀页没有「最高N京豆」", find_wp_bean_text(WP) is None)
HOME_TXT = [n["text"] for n in load("_fixture_jx_home.xml")
            if u"最高" in (n["text"] or "") and u"京豆" in (n["text"] or "")]
check("H8 首页确实也有「最高N京豆」广告（所以才要取最上面的）",
      any(u"最高" in t for t in HOME_TXT), "got %s" % HOME_TXT[:3])
check("H8b 京喜自营页取到的是最上面那个（y=599 而不是下方广告位）",
      find_wp_bean_text(JXP)["bounds"][1] == 599,
      "got %s" % (find_wp_bean_text(JXP)["bounds"],))
check("H9 空节点返回 None", clickable_ancestor([], nd(u"x", 0, 0, 10, 10)) is None)

# ================================================================ I
print("\n--- I. 全部频道 -> 优惠权益 -> 京喜自营 ---")


class LabelUI(FakeUI):
    def __init__(self, screens):
        FakeUI.__init__(self)
        self.screens = screens
        self.idx = 0

    def nodes(self):
        s = self.screens[min(self.idx, len(self.screens) - 1)]
        return s

    def adb_tap(self, pos, pause=1.5):
        self.taps.append(pos)
        self.idx += 1


ALLCHAN = load("_fixture_jx_allchan.xml")
m = Task8JxSelf()
ui = LabelUI([ALLCHAN, ALLCHAN, ALLCHAN])
log = Log()
check("I1 点【优惠权益】成功", m._tap_label(ui, log, ALLCHAN, BENEFIT_TAB, u"全部频道页") is True)
check("I2 点的是 tab 自己的中心 (408,301)", ui.taps and ui.taps[0] == (408, 301),
      "got %s" % (ui.taps[:1],))

ui2 = LabelUI([ALLCHAN, ALLCHAN, ALLCHAN])
log2 = Log()
check("I3 点【京喜自营】成功", m._tap_label(ui2, log2, ALLCHAN, JX_DESC, u"全部频道页") is True)
check("I4 点的是图标可点区中心 (734,558)", ui2.taps and ui2.taps[0] == (734, 558),
      "got %s" % (ui2.taps[:1],))

log3 = Log()
check("I5 找不到标签返回 False",
      m._tap_label(FakeUI(), log3, ALLCHAN, u"不存在的标签", u"全部频道页") is False)
check("I6 找不到会写日志", u"没找到" in log3.text())

KK2 = load("_fixture_jx_kk2.xml")
check("I7 金刚区第2页夹具里有【全部频道】",
      any((n["desc"] or n["text"]) == ALL_CHANNEL for n in KK2))

# ================================================================ J
print("\n--- J. 入口链路 _open_jx ---")


class EntryUI(FakeUI):
    """首页/金刚区/全部频道/京喜自营页 的可控替身。"""

    def __init__(self, home, kk2, allchan, jxpage, kk1_has_jx=True,
                 kk2_has_jx=False, kk1_tap_bad=False):
        FakeUI.__init__(self)
        self.home = home
        self.kk2 = kk2
        self.allchan = allchan
        self.jxpage = jxpage
        self.kk1_has_jx = kk1_has_jx
        self.kk2_has_jx = kk2_has_jx
        self.kk1_tap_bad = kk1_tap_bad
        self.page = "home"
        self.kk_page = 1

    def nodes(self):
        if self.page == "home":
            return self.kk2 if self.kk_page == 2 else self.home
        if self.page == "allchan":
            return self.allchan
        if self.page == "jx":
            return self.jxpage
        return self.home

    def _stable_kingkong_icon(self, desc, tries=4):
        if self.page != "home":
            return None, False
        if self.kk_page == 1 and self.kk1_has_jx:
            return {"desc": desc, "bounds": (581, 440, 775, 601), "clickable": True,
                    "cy": 520}, True
        if self.kk_page == 2 and self.kk2_has_jx:
            return {"desc": desc, "bounds": (581, 440, 775, 601), "clickable": True,
                    "cy": 520}, True
        return None, False

    def swipe_kingkong(self, direction="left", pause=1.5):
        self.kk_swipes.append(direction)
        self.kk_page = 2 if direction == "left" else 1

    def adb_tap(self, pos, pause=1.5):
        self.taps.append(pos)
        if self.page == "home":
            if self.kk_page == 1 and pos == (678, 520) and not self.kk1_tap_bad:
                self.page = "jx"
            elif self.kk_page == 2 and pos == (973, 1004):
                self.page = "allchan"
        elif self.page == "allchan":
            if pos == (734, 558):
                self.page = "jx"
        elif self.page == "jx":
            pass

    def goto_home(self):
        FakeUI.goto_home(self)
        self.page = "home"
        self.kk_page = 1
        return True


HOME = load("_fixture_jx_home.xml")
m = Task8JxSelf()
ui = EntryUI(HOME, KK2, ALLCHAN, JXP)
log = Log()
check("J1 金刚区第1页直接进", m._open_jx(ui, log, cold=True) is True, log.text()[-300:])
check("J2 冷启动了一次", ui.restart_calls == 1)
check("J3 点的是京喜自营图标中心 (678,520)", ui.taps and ui.taps[0] == (678, 520),
      "got %s" % (ui.taps[:1],))
check("J4 没去翻第2页", "left" not in ui.kk_swipes, "got %s" % ui.kk_swipes)

m2 = Task8JxSelf()
ui2 = EntryUI(HOME, KK2, ALLCHAN, JXP, kk1_has_jx=False, kk2_has_jx=True)
log2 = Log()
check("J5 第1页没有就翻第2页", m2._open_jx(ui2, log2, cold=True) is True, log2.text()[-300:])
check("J6 确实左滑了一次", "left" in ui2.kk_swipes)

m3 = Task8JxSelf()
ui3 = EntryUI(HOME, KK2, ALLCHAN, JXP, kk1_has_jx=False, kk2_has_jx=False)
log3 = Log()
check("J7 两页都没有走全部频道兜底", m3._open_jx(ui3, log3, cold=True) is True,
      log3.text()[-400:])
check("J8 走了全部频道", u"全部频道" in log3.text())
check("J9 点了优惠权益和京喜自营",
      any(p == (408, 301) for p in ui3.taps) and any(p == (734, 558) for p in ui3.taps),
      "taps=%s" % ui3.taps)

m4 = Task8JxSelf()
ui4 = EntryUI(HOME, KK2, ALLCHAN, JXP, kk1_has_jx=True, kk1_tap_bad=True,
              kk2_has_jx=False)
log4 = Log()
check("J10 第1页点歪了会继续下一级", m4._open_jx(ui4, log4, cold=True) is True,
      log4.text()[-400:])

m5 = Task8JxSelf()
ui5 = FakeUI()
ui5.nodes = lambda: list(HOME)
ui5._stable_kingkong_icon = lambda desc, tries=4: (None, False)
ui5.adb_tap = lambda pos, pause=1.5: ui5.taps.append(pos)
log5 = Log()
check("J11 全都进不去返回 False", m5._open_jx(ui5, log5, cold=True) is False)

# ================================================================ K
print("\n--- K. _open_wp 点【去领取】 ---")


class WpUI(FakeUI):
    def __init__(self, jxpage, wppage, first_tap_bad=False):
        FakeUI.__init__(self)
        self.jxpage = jxpage
        self.wppage = wppage
        self.on_wp = False
        self.first_tap_bad = first_tap_bad

    def nodes(self):
        return self.wppage if self.on_wp else self.jxpage

    def adb_tap(self, pos, pause=1.5):
        self.taps.append(pos)
        if self.on_wp:
            return
        if 68 <= pos[0] <= 244 and 500 <= pos[1] <= 704:
            if self.first_tap_bad:
                self.first_tap_bad = False
                return
            self.on_wp = True


m = Task8JxSelf()
ui = WpUI(JXP, WP)
log = Log()
check("K1 点【去领取】进王牌秒杀页", m._open_wp(ui, log) is True, log.text()[-300:])
check("K2 点的是可点区下半部分 (156,663)", ui.taps and ui.taps[0] == (156, 663),
      "got %s" % (ui.taps[:2],))

ui2 = WpUI(JXP, WP, first_tap_bad=True)
log2 = Log()
check("K3 第一次点没反应会兜底再点中心", m._open_wp(ui2, log2) is True, log2.text()[-300:])
check("K4 兜底点了区域中心 (156,602)", (156, 602) in ui2.taps, "got %s" % (ui2.taps,))

log3 = Log()
check("K5 找不到「最高N京豆」返回 False",
      m._open_wp(WpUI(load("_fixture_jx_home.xml"), WP), log3) is False)

# ================================================================ L
print("\n--- L. _open_panel（领N京豆要等） ---")


class BeanUI(FakeUI):
    def __init__(self, wppage, panel, bean_after=0, never=False):
        FakeUI.__init__(self)
        self.wppage = wppage
        self.panel = panel
        self.bean_after = bean_after
        self.never = never
        self.reads = 0
        self.opened = False

    def nodes(self):
        self.reads += 1
        if self.opened:
            return self.panel
        if self.never or self.reads <= self.bean_after:
            return [n for n in self.wppage if n["text"] != u"领 121 京豆"]
        return self.wppage

    def adb_tap(self, pos, pause=1.5):
        self.taps.append(pos)
        if 918 <= pos[0] <= 1058 and 1603 <= pos[1] <= 1746:
            self.opened = True


m = Task8JxSelf()
ui = BeanUI(WP, PN)
log = Log()
check("L1 按钮一开始就有能直接点", m._open_panel(ui, log) is True, log.text()[-300:])
check("L2 点的是 (988,1674)", ui.taps and ui.taps[0] == (988, 1674), "got %s" % (ui.taps[:1],))

ui2 = BeanUI(WP, PN, bean_after=6)
log2 = Log()
check("L3 按钮晚 6 次读才出现也能等到", m2._open_panel(ui2, log2) is True, log2.text()[-300:])
check("L4 等到了会写日志", u"才出现" in log2.text(), log2.text()[-300:])

ui3 = BeanUI(WP, PN, never=True)
log3 = Log()
check("L5 一直不出现返回 False", m._open_panel(ui3, log3) is False)
check("L6 尝试次数有上限", ui3.reads <= BEAN_ENTRY_TRIES + 4, "reads=%d" % ui3.reads)
check("L7 会写日志", u"始终没出现" in log3.text())

# ================================================================ M
print("\n--- M. 任务循环 ---")
T = [dict(title=u"逛9.9包邮频道（0/1）", secs=10, state=u"todo", y=1690),
     dict(title=u"逛看病买药频道（0/1）", secs=10, state=u"todo", y=1880)]

ui = PanelUI([dict(t) for t in T])
log = Log()
done = Task8JxSelf()._process_tasks(ui, log, threading.Event())
check("M1 两个任务都做完", done == 2, "done=%d" % done)
check("M2 每个任务都停 14s", ui.sleeps.count(14.0) >= 2, "sleeps=%s" % sorted(set(ui.sleeps)))
check("M3 每个任务都按过返回", ui.backs >= 2, "backs=%d" % ui.backs)
check("M4 日志说没可做任务", u"没有可做任务" in log.text())

ui = PanelUI([dict(T[0])])
log = Log()
done = Task8JxSelf()._process_tasks(ui, log, threading.Event())
check("M5 只有 1 个任务就做 1 个", done == 1)

# 浏览后按钮没变（服务端没算完成）-> 不能死循环
ui = PanelUI([dict(T[0])], completes=False)
log = Log()
done = Task8JxSelf()._process_tasks(ui, log, threading.Event())
check("M6 按钮没变只做一次", done == 0)
check("M7 只点了一次去完成", len([p for p in ui.taps if p[0] >= 814]) == 1,
      "taps=%s" % ui.taps)

# 回不到弹层 -> 先轻量重开
ui = PanelUI([dict(T[0])], stay_away=True)
log = Log()
done = Task8JxSelf()._process_tasks(ui, log, threading.Event())
check("M8 回不来会尝试轻量重开", u"轻量重开" in log.text(), log.text()[-400:])
check("M9 轻量重开失败会整链重进", u"整链重进" in log.text() or u"重进次数用尽" in log.text())
check("M10 重进有上限", log.text().count(u"整链重进") <= MAX_REENTER + 1)

# 读失败 -> 重读；一直失败 -> 收尾
ui = PanelUI([dict(T[0])], fail_reads=2)
log = Log()
done = Task8JxSelf()._process_tasks(ui, log, threading.Event())
check("M11 读失败会重读", done == 1, "done=%d" % done)

ui = PanelUI([dict(T[0])], fail_reads=1000)
log = Log()
done = Task8JxSelf()._process_tasks(ui, log, threading.Event())
check("M12 连续读失败会收尾", done == 0 and u"读不到页面" in log.text(), log.text()[-200:])

# 需要滚动
ui = PanelUI([dict(title=u"下方任务（0/1）", secs=10, state=u"todo", y=2300)],
             scrollable=True)
log = Log()
done = Task8JxSelf()._process_tasks(ui, log, threading.Event())
check("M13 需要滚动时会滚动", len(ui.swipes) >= 1, "swipes=%d" % len(ui.swipes))
check("M14 滚动后完成任务", done == 1, "done=%d log=%s" % (done, log.text()[-300:]))

# 空列表
ui = PanelUI([])
log = Log()
check("M15 没有任务立即收尾", Task8JxSelf()._process_tasks(ui, log, threading.Event()) == 0)

# ================================================================ N
print("\n--- N. 领取阶段 ---")


class ClaimUI(FakeUI):
    """只有任务行和领取按钮，点一下领取就变已完成。"""

    def __init__(self, claims, stick=False):
        FakeUI.__init__(self)
        self.claims = list(claims)          # [(title, y)]
        self.stick = stick

    def nodes(self):
        out = list(MARK)
        for title, y in self.claims:
            out.append(nd(title, 203, y, 737, y + 49))
            out.append(nd(u"，浏览10s可领", 429, y + 66, 643, y + 107))
            out.append(nd(u"领取", 814, y + 16, 1031, y + 96, clickable=True))
        return out

    def adb_tap(self, pos, pause=1.5):
        self.taps.append(pos)
        if pause:
            self.sleeps.append(pause)
        for i, (title, y) in enumerate(self.claims):
            if 814 <= pos[0] <= 1031 and y + 16 <= pos[1] <= y + 96:
                if not self.stick:
                    self.claims.pop(i)
                return


m = Task8JxSelf()
ui = ClaimUI([(u"甲（1/1）", 1500), (u"乙（1/1）", 1690)])
log = Log()
n = m._claim_once(ui, log, threading.Event())
check("N1 原地领两个", n == 2, "got %d" % n)
check("N2 每次都等 1 秒", ui.sleeps == [CLAIM_WAIT, CLAIM_WAIT], "sleeps=%s" % ui.sleeps)
check("N3 点的是领取按钮", all(p[0] == 922 for p in ui.taps), "taps=%s" % ui.taps)
check("N4 不滚动", ui.swipes == [])
check("N5 不按返回", ui.backs == 0)

ui2 = ClaimUI([(u"甲（1/1）", 1500)])
log2 = Log()
n2 = m._claim_once(ui2, log2, threading.Event(), max_clicks=1)
check("N6 max_clicks 生效", n2 == 1)

ui3 = ClaimUI([(u"甲（1/1）", 1500)], stick=True)
log3 = Log()
n3 = m._claim_once(ui3, log3, threading.Event(), max_clicks=10)
check("N7 点不动的领取最多试 2 次", n3 == 2, "got %d" % n3)

ui4 = ClaimUI([])
log4 = Log()
check("N8 没有领取返回 0", m._claim_once(ui4, log4, threading.Event()) == 0)

# 全表领取：先回顶部再往下扫
ui5 = ClaimUI([(u"甲（1/1）", 1500)])
log5 = Log()
n5 = m._claim_all(ui5, log5, threading.Event())
check("N9 _claim_all 能领到", n5 == 1, "got %d" % n5)
check("N10 _claim_all 会回列表顶部", len(ui5.swipes) >= 3, "swipes=%d" % len(ui5.swipes))

# ================================================================ O
print("\n--- O. _recover_panel / _reenter ---")


class RecoverUI(FakeUI):
    """在「弹层」和「王牌秒杀页」之间切换。"""

    def __init__(self, start_panel=True, back_restores=False):
        FakeUI.__init__(self)
        self.panel = start_panel
        self.back_restores = back_restores
        self.on_wp = not start_panel

    def nodes(self):
        return list(PN) if self.panel else list(NO_PANEL)

    def adb_tap(self, pos, pause=1.5):
        self.taps.append(pos)
        if not self.panel and 918 <= pos[0] <= 1058 and 1603 <= pos[1] <= 1746:
            self.panel = True

    def back(self, pause=2.0):
        self.backs += 1
        if self.back_restores:
            self.panel = True


m = Task8JxSelf()
ui = RecoverUI(start_panel=True)
log = Log()
check("O1 弹层在时直接 True", m._recover_panel(ui, log) is True and ui.taps == [])

ui2 = RecoverUI(start_panel=False)
log2 = Log()
check("O2 不在弹层但能看到【领N京豆】-> 点它重开", m._recover_panel(ui2, log2) is True,
      log2.text()[-300:])
check("O3 点的是 (988,1674)", ui2.taps and ui2.taps[0] == (988, 1674),
      "got %s" % (ui2.taps[:1],))
check("O4 写日志说还在王牌秒杀页", u"还在王牌秒杀页" in log2.text())

ui3 = FakeUI()
ui3.nodes = lambda: [nd(u"东东农场", 0, 0, 500, 500)]
log3 = Log()
check("O5 完全不在王牌秒杀页 -> False", m._recover_panel(ui3, log3) is False)
check("O6 会按返回试两次", ui3.backs == 2, "backs=%d" % ui3.backs)

# ================================================================ P
print("\n--- P. stop_event ---")
ev = threading.Event()
ev.set()
ui = PanelUI([dict(t) for t in T])
log = Log()
check("P1 stop 立即生效",
      Task8JxSelf()._process_tasks(ui, log, ev) == 0 and not ui.taps)
check("P2 stop 后不按返回", ui.backs == 0)
check("P3 stop 后不领取",
      Task8JxSelf()._claim_once(ClaimUI([(u"甲（1/1）", 1500)]), Log(), ev) == 0)

# ================================================================ 汇总
print("\n" + "=" * 60)
print("通过 %d / %d" % (len(PASSED), len(PASSED) + len(FAILED)))
if FAILED:
    print("失败用例：")
    for f in FAILED:
        print("  -", f)
    sys.exit(1)
print("全部通过")
