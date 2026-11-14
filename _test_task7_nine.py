# -*- coding: utf-8 -*-
"""9.9包邮 模块离线回归（不连手机、不连 Appium）。

覆盖：
  A. 三种可做任务文案识别（需求原文的三条）
  B. X+4 停留换算
  C. 真机夹具上的任务行配对（标题 / 副标题 / 按钮 / 可做判定 / 浏览秒数）
  D. 合成节点上的配对细节：已完成排除、无奖励文案排除、屏外退化节点过滤、标题优先带进度
  E. pick_target 安全区判定（底部导航栏重叠问题）
  F. panel_visible / guide_visible
  G. 首页【9.9包邮】卡片定位（content-desc，不是 text）
  H. 9.9包邮 页京豆浮层卡锚点
  I. 入口链路：冷启动 -> 卡片 -> 频道页；候选卡片逐个试
  J. 任务循环：做完就变已完成、引导层任务只试一次、滚动、全表扫描兜底、读失败收尾
  K. 返回链路：back 回弹层、弹层丢失后重进
  L. stop_event 立即生效

夹具（真机 1080x2340，2026-11-12 抓的）：
  _fixture_99_home.xml    京东首页（含 desc='9.9包邮, 买一送一' 卡片）
  _fixture_99_page.xml    9.9包邮 频道页（含「抽3000京豆再签2天」浮层卡）
  _fixture_99_panel.xml   点开京豆卡后的【天天砸蛋】任务弹层
"""
import io
import re
import sys
import threading
import xml.etree.ElementTree as ET

sys.path.insert(0, ".")

from modules.task7_nine_nine import (
    Task7NineNine, is_reward_text, browse_seconds, parse_task_rows, pick_target,
    panel_visible, guide_visible, row_signature,
    BROWSE_EXTRA, SAFE_TOP, SAFE_BOTTOM, DEFAULT_BROWSE, MAX_REENTER, MAX_SWEEPS,
    GUIDE_CLOSE_PT, HOME_CARD_DESC, SWEEP_SCROLLS,
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


def row(title, reward, btn=u"去完成", y=1690):
    """按真机行结构造一行：标题在上、副标题在下一行、按钮贴右。

    真机实测：标题 [203,1855][825,1916]，副标题 [203,1916][783,1968]，
    按钮 [827,1872][1012,1954]，按钮中心比标题中心低 28、比副标题中心高 29。
    """
    return [
        nd(title, 203, y, 825, y + 61),
        nd(reward, 203, y + 61, 783, y + 113),
        nd(btn, 827, y + 17, 1012, y + 99, clickable=True),
    ]


def screen(*rows):
    out = []
    for r in rows:
        out.extend(r)
    return out


PANEL_MARK = [nd(u"继续下一个任务", 195, 1465, 885, 1586, clickable=True)]
# 「页面在、但没有任务行」的真实样子，不能用 []（[] 代表 page_source 读失败）
EMPTY_PANEL = PANEL_MARK + [nd(u"抽3000京豆再签2天", 671, 1168, 825, 1242)]
AWAY_PAGE = [nd(u"天天赚京豆", 100, 100, 500, 200),
             nd(u"我的京豆", 30, 300, 300, 360),
             nd(u"去完成", 814, 700, 990, 780, clickable=True)]
GUIDE_NODES = [nd(u"引导安装", 0, 702, 1080, 2340),
               nd(u"添加", 291, 740, 393, 801),
               nd(u"小组件", 390, 740, 541, 801),
               nd(u"到手机桌面", 539, 740, 789, 801),
               nd(u"常见问题", 451, 1972, 632, 2074, clickable=True),
               nd(u"去添加", 19, 2121, 1061, 2233, clickable=True)]


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
    """最小 JDUI 替身。"""
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


class FakeUIWithScreens(FakeUI):
    """按顺序吐屏幕，吐完就停在最后一屏。"""

    def __init__(self, screens):
        FakeUI.__init__(self)
        self.screens = list(screens)
        self.idx = 0

    def nodes(self):
        if not self.screens:
            return []
        s = self.screens[min(self.idx, len(self.screens) - 1)]
        self.idx += 1
        return s


class PanelUI(FakeUI):
    """模拟【天天砸蛋】弹层 + 任务落地页。

    点【去完成】-> away=True（跳到别的页）；back() -> away=False（弹层还在）。
    点【添加桌面组件】这类 -> guide=True（弹「添加小组件到手机桌面」引导层）。
    """

    def __init__(self, tasks, completes=True, guide_tasks=(), stay_away=False,
                 fail_reads=0, scrollable=False):
        FakeUI.__init__(self)
        self.tasks = [dict(t) for t in tasks]
        self.completes = completes
        self.guide_tasks = set(guide_tasks)
        self.stay_away = stay_away
        self.fail_reads = fail_reads
        self.reads = 0
        self.away = False
        self.guide = False
        self.offset = 0
        self.scrollable = scrollable

    def _rows(self):
        out = list(PANEL_MARK)
        for t in self.tasks:
            out.extend(row(t["title"], t["reward"], t["btn"], t["y"] - self.offset))
        return out

    def nodes(self):
        self.reads += 1
        if self.reads <= self.fail_reads:
            return []
        if self.guide:
            return list(GUIDE_NODES)
        if self.away:
            return list(AWAY_PAGE)
        return self._rows()

    def adb_tap(self, pos, pause=1.5):
        self.taps.append(pos)
        if self.guide:
            if abs(pos[0] - GUIDE_CLOSE_PT[0]) <= 60 and abs(pos[1] - GUIDE_CLOSE_PT[1]) <= 60:
                self.guide = False
            return
        for t in self.tasks:
            x1, y1 = 827, t["y"] - self.offset + 17
            x2, y2 = 1012, t["y"] - self.offset + 99
            if x1 <= pos[0] <= x2 and y1 <= pos[1] <= y2:
                if t["title"] in self.guide_tasks:
                    self.guide = True
                else:
                    self.away = True
                    if self.completes:
                        t["btn"] = u"已完成"
                return

    def back(self, pause=2.0):
        self.backs += 1
        self.guide = False
        if not self.stay_away:
            self.away = False

    def adb_swipe(self, x1, y1, x2, y2, duration=300):
        self.swipes.append((x1, y1, x2, y2))
        if not self.scrollable:
            return
        if y1 > y2:            # 手指上滑 -> 内容上移
            self.offset += 300
        else:
            self.offset = max(0, self.offset - 300)


# ================================================================ A 文案识别
print("\n--- A. 三种可做任务文案 ---")
check("A1 完成任务最高得1个京豆", is_reward_text(u"完成任务最高得1个京豆+1"))
check("A2 完成任务最高得5个京豆", is_reward_text(u"完成任务最高得5个京豆+5"))
check("A3 点击3个商品且浏览10s可得京豆", is_reward_text(u"点击3个商品且浏览10s可得京豆+2"))
check("A4 点击2个商品且浏览10s可得京豆", is_reward_text(u"点击2个商品且浏览10s可得京豆+1"))
check("A5 完成任务可得1个京豆", is_reward_text(u"完成任务可得1个京豆+1"))
check("A6 完成任务可得1京豆(无「个」)", is_reward_text(u"完成任务可得1京豆"))
check("A7 浏览Ns可领 不算", not is_reward_text(u"，浏览10s可领"))
check("A8 分享好友助力 不算", not is_reward_text(u"分享好友助力，得更多京豆"))
check("A9 空串不算", not is_reward_text(u""))
check("A10 第三方App任务文案不算", not is_reward_text(u"看直播赚零花钱，今日可得京豆+1个"))
check("A11 None 不算", not is_reward_text(None))

print("\n--- B. X+4 停留 ---")
check("B1 10s -> 14s", browse_seconds(10) == 10 + BROWSE_EXTRA == 14)
check("B2 5s -> 9s", browse_seconds(5) == 9)
check("B3 0s -> 4s", browse_seconds(0) == 4)
check("B4 BROWSE_EXTRA 就是 4", BROWSE_EXTRA == 4)

# ================================================================ C 真机夹具
print("\n--- C. 真机夹具 _fixture_99_panel.xml ---")
PN = load("_fixture_99_panel.xml")
rows = parse_task_rows(PN)
check("C1 弹层识别为可见", panel_visible(PN))
check("C2 弹层不是引导层", not guide_visible(PN))
check("C3 配出 4 行", len(rows) == 4, "got %d" % len(rows))
by_title = dict((r["title"], r) for r in rows)
check("C4 第一行是已完成", by_title.get(u"点击3个商品领6京豆(3/3)", {}).get("btn") == u"已完成")
check("C5 已完成行不算可做", not by_title.get(u"点击3个商品领6京豆(3/3)", {}).get("doable"))
check("C6 桌面组件行可做", by_title.get(u"添加“9.9包邮”桌面组件(0/1)", {}).get("doable") is True)
check("C7 桌面组件副标题对", by_title.get(u"添加“9.9包邮”桌面组件(0/1)", {}).get("reward")
      == u"完成任务最高得5个京豆+5")
check("C8 看视频行可做", by_title.get(u"看视频领红包(0/1)", {}).get("doable") is True)
check("C9 浏览10s 的行 secs=10", by_title.get(u"点击3个商品领6京豆(3/3)", {}).get("secs") == 10)
check("C10 没有浏览Ns 的行用默认值", by_title.get(u"看视频领红包(0/1)", {}).get("secs") == DEFAULT_BROWSE)
check("C11 按钮 x 贴右", all(r["btn_bounds"][0] >= 800 for r in rows))
check("C12 行按 y 升序", [r["cy"] for r in rows] == sorted(r["cy"] for r in rows))
check("C13 key 去掉了 (N/M)", by_title.get(u"看视频领红包(0/1)", {}).get("key") == u"看视频领红包")
check("C14 桌面组件的 key 也去掉进度",
      by_title.get(u"添加“9.9包邮”桌面组件(0/1)", {}).get("key") == u"添加“9.9包邮”桌面组件")

# ================================================================ D 合成配对
print("\n--- D. 合成节点配对细节 ---")
r1 = parse_task_rows(screen(row(u"逛省钱频道领京豆(0/1)", u"完成任务最高得1个京豆+1", y=1690)))
check("D1 单行配出 1 行", len(r1) == 1, "got %d" % len(r1))
check("D2 标题正确", r1 and r1[0]["title"] == u"逛省钱频道领京豆(0/1)")
check("D3 副标题正确", r1 and r1[0]["reward"] == u"完成任务最高得1个京豆+1")
check("D4 可做", r1 and r1[0]["doable"])
check("D5 按钮中心", r1 and (r1[0]["cx"], r1[0]["cy"]) == (919, 1748),
      "got %s" % (((r1[0]["cx"], r1[0]["cy"]) if r1 else None),))

# 只有按钮、没有京豆副标题 -> 不是任务行（比如天天赚京豆页的第三方任务）
only_btn = [nd(u"去完成", 827, 1707, 1012, 1789, clickable=True)]
check("D6 没有副标题不算任务行", parse_task_rows(only_btn) == [])

# 副标题在、按钮是【已完成】-> 行在但不可做
done_row = parse_task_rows(screen(row(u"看视频领红包(1/1)", u"完成任务最高得1个京豆+1",
                                     btn=u"已完成", y=1690)))
check("D7 已完成行仍能配出", len(done_row) == 1)
check("D8 已完成行 doable=False", done_row and not done_row[0]["doable"])

# 屏外退化节点（y2<=y1）必须过滤掉
degen = [nd(u"点击3个商品领6京豆(3/3)", 203, 2431, 825, 2341),
         nd(u"点击3个商品且浏览10s可得京豆+2", 203, 2431, 783, 2341),
         nd(u"去完成", 827, 2431, 1012, 2341, clickable=True)]
check("D9 退化节点被过滤", parse_task_rows(degen) == [])

# 按钮在左边（不是任务行按钮列）
left_btn = screen(row(u"逛省钱频道领京豆(0/1)", u"完成任务最高得1个京豆+1", y=1690))
left_btn.append(nd(u"去完成", 200, 1700, 380, 1780, clickable=True))
r2 = parse_task_rows(left_btn)
check("D10 左侧的【去完成】不算任务按钮", len(r2) == 1 and r2[0]["cx"] == 919,
      "got %s" % [r["cx"] for r in r2])

# 没有标题（真机部分行 dump 里没标题）-> 退化用副标题当 key
no_title = [nd(u"完成任务最高得1个京豆+1", 203, 1751, 783, 1803),
            nd(u"去完成", 827, 1707, 1012, 1789, clickable=True)]
r3 = parse_task_rows(no_title)
check("D11 无标题也能配出", len(r3) == 1)
check("D12 无标题时 key 用副标题", r3 and r3[0]["key"] == u"完成任务最高得1个京豆+1")

# 多行 + 已完成混排，行顺序按 y
mixed = screen(
    row(u"A(1/1)", u"完成任务可得1个京豆+1", btn=u"已完成", y=1640),
    row(u"B(0/1)", u"完成任务最高得1个京豆+1", y=1760),
    row(u"C(0/1)", u"点击2个商品且浏览10s可得京豆+1", y=1880),
)
r4 = parse_task_rows(mixed)
check("D13 三行都配出", [r["title"] for r in r4] == [u"A(1/1)", u"B(0/1)", u"C(0/1)"],
      "got %s" % [r["title"] for r in r4])
check("D14 只有 B/C 可做", [r["doable"] for r in r4] == [False, True, True])
check("D15 C 行 secs=10", r4[2]["secs"] == 10)
check("D16 row_signature 随按钮变化",
      row_signature(r4) != row_signature(parse_task_rows(screen(
          row(u"A(1/1)", u"完成任务可得1个京豆+1", btn=u"已完成", y=1640),
          row(u"B(1/1)", u"完成任务最高得1个京豆+1", btn=u"已完成", y=1760),
          row(u"C(0/1)", u"点击2个商品且浏览10s可得京豆+1", y=1880)))))

# ================================================================ E 安全区
print("\n--- E. pick_target 安全区 ---")
base = parse_task_rows(screen(
    row(u"上(0/1)", u"完成任务最高得1个京豆+1", y=1640),
    row(u"下(0/1)", u"完成任务最高得1个京豆+1", y=2200),   # 按钮 y2 = 2299，压到导航栏
))
t, why = pick_target(base, set())
check("E1 安全区内的行被选中", t is not None and t["title"] == u"上(0/1)", "why=%s" % why)

below = parse_task_rows(screen(row(u"下(0/1)", u"完成任务最高得1个京豆+1", y=2200)))
t, why = pick_target(below, set())
check("E2 全在下方 -> 要求上滑", t is None and why == "below", "why=%s" % why)

above = parse_task_rows(screen(row(u"上(0/1)", u"完成任务最高得1个京豆+1", y=1200)))
t, why = pick_target(above, set())
check("E3 全在上方 -> 要求下滑", t is None and why == "above", "why=%s" % why)

check("E4 没可做 -> none", pick_target(parse_task_rows(EMPTY_PANEL), set()) == (None, "none"))
check("E5 全是已完成 -> none",
      pick_target(parse_task_rows(screen(
          row(u"A(1/1)", u"完成任务可得1个京豆+1", btn=u"已完成", y=1690))), set())
      == (None, "none"))

two = parse_task_rows(screen(
    row(u"甲(0/1)", u"完成任务最高得1个京豆+1", y=1640),
    row(u"乙(0/1)", u"完成任务最高得1个京豆+1", y=1760),
))
t, _ = pick_target(two, set([u"甲"]))
check("E6 已尝试的行被跳过", t is not None and t["title"] == u"乙(0/1)",
      "got %s" % (t["title"] if t else None))
t, why = pick_target(two, set([u"甲", u"乙"]))
check("E7 全部尝试过 -> none", t is None and why == "none")

check("E8 安全区常量合理", SAFE_TOP < SAFE_BOTTOM < 2169,
      "SAFE_TOP=%d SAFE_BOTTOM=%d" % (SAFE_TOP, SAFE_BOTTOM))

# ================================================================ F 弹层/引导层
print("\n--- F. panel_visible / guide_visible ---")
check("F1 有任务行 -> 弹层在", panel_visible(parse_task_rows and PN))
check("F2 只有【继续下一个任务】也算弹层在", panel_visible(EMPTY_PANEL))
check("F3 别的页面不是弹层", not panel_visible(AWAY_PAGE))
check("F4 引导层识别", guide_visible(GUIDE_NODES))
check("F5 弹层不是引导层", not guide_visible(PN))
check("F6 空列表都不算", not panel_visible([]) and not guide_visible([]))

# ================================================================ G 首页卡片
print("\n--- G. 首页【9.9包邮】卡片 ---")
HOME = load("_fixture_99_home.xml")
cards = Task7NineNine()._home_cards(FakeUIWithScreens([HOME]))
check("G1 首页找到卡片", len(cards) >= 1, "got %d" % len(cards))
if cards:
    b = cards[0]["bounds"]
    check("G2 第一张就是正文大卡", b == (23, 993, 530, 1327), "got %s" % (b,))
    check("G3 靠 content-desc 命中", HOME_CARD_DESC in (cards[0]["desc"] or cards[0]["text"]))
    check("G4 宽度 >= 400", b[2] - b[0] >= 400)
    check("G5 顶部频道 tab 被排除", all(c["bounds"][1] >= 700 for c in cards))
    check("G6 秒送窄卡被排除", all((c["bounds"][2] - c["bounds"][0]) >= 400 for c in cards))
else:
    for nm in ("G2", "G3", "G4", "G5", "G6"):
        check(nm, False, "no card")

# ================================================================ H 京豆卡锚点
print("\n--- H. 京豆浮层卡锚点 ---")
PAGE = load("_fixture_99_page.xml")
anchor = Task7NineNine()._bean_anchor(PAGE)
check("H1 找到京豆卡锚点", anchor is not None)
if anchor:
    check("H2 锚点文案含京豆", u"京豆" in (anchor["text"] or anchor["desc"]),
          "got %r" % (anchor["text"],))
    check("H3 锚点在右侧", anchor["bounds"][0] >= 400)
    check("H4 锚点在 y 950~1450", 950 <= anchor["bounds"][1] <= 1450)
    check("H5 中心点落在浮层卡内",
          600 <= (anchor["bounds"][0] + anchor["bounds"][2]) // 2 <= 910)
else:
    for nm in ("H2", "H3", "H4", "H5"):
        check(nm, False, "no anchor")
check("H6 首页上没有京豆卡锚点", Task7NineNine()._bean_anchor(HOME) is None)

# ================================================================ I 入口链路
print("\n--- I. 入口链路 ---")


class EntryUI(FakeUI):
    """restart_to_home -> 首页；点卡片 -> 9.9包邮 页（除非 land_bad）。"""

    def __init__(self, home, page, land_bad=0):
        FakeUI.__init__(self)
        self.home = home
        self.page = page
        self.land_bad = land_bad
        self.on_page = False

    def nodes(self):
        return self.page if self.on_page else self.home

    def adb_tap(self, pos, pause=1.5):
        FakeUI.adb_tap(self, pos, pause)
        if self.on_page:
            return
        if 23 <= pos[0] <= 530 and 993 <= pos[1] <= 1327:
            if self.land_bad > 0:
                self.land_bad -= 1
                return                     # 点歪了，还在首页
            self.on_page = True

    def goto_home(self):
        FakeUI.goto_home(self)
        self.on_page = False
        return True


m = Task7NineNine()
ui = EntryUI(HOME, PAGE)
log = Log()
check("I1 入口成功", m._open_nine_nine(ui, log) is True, log.text()[-300:])
check("I2 冷启动了一次", ui.restart_calls == 1)
check("I3 点的是卡片中心 (276,1160)", ui.taps and ui.taps[0] == (276, 1160),
      "got %s" % ui.taps[:2])
check("I4 日志里有卡片坐标", u"9.9包邮" in log.text() and u"(23, 993, 530, 1327)" in log.text())

m2 = Task7NineNine()
ui2 = EntryUI(HOME, PAGE, land_bad=1)
log2 = Log()
check("I5 第一张点歪了也能靠第二轮成功", m2._open_nine_nine(ui2, log2) is True, log2.text()[-300:])
check("I6 点歪后回过首页", ui2.home_calls >= 1)

m3 = Task7NineNine()
ui3 = FakeUI()
ui3.nodes = lambda: list(HOME)         # 永远在首页，卡片点了也不动
ui3.adb_tap = lambda pos, pause=1.5: ui3.taps.append(pos)
log3 = Log()
check("I7 进不去时返回 False", m3._open_nine_nine(ui3, log3) is False)
check("I8 会尝试冷启动两轮", ui3.restart_calls >= 2, "got %d" % ui3.restart_calls)

m4 = Task7NineNine()
check("I9 9.9包邮 频道页判定为真", m4._is_nine_page(PAGE) is True)
check("I10 京东首页判定为假（首页正文也有「领券中心」）", m4._is_nine_page(HOME) is False)
check("I11 弹层页不算频道页", m4._is_nine_page(PN) is True)   # 弹层压在 9.9 页上，锚点还在
check("I12 空白页判定为假", m4._is_nine_page([]) is False)


# ================================================================ J 任务循环
print("\n--- J. 任务循环 ---")
T = [
    dict(title=u"点击3个商品领6京豆(3/3)", reward=u"点击3个商品且浏览10s可得京豆+2",
         btn=u"已完成", y=1640),
    dict(title=u"看视频领红包(0/1)", reward=u"完成任务最高得1个京豆+1", btn=u"去完成", y=1760),
    dict(title=u"点击2个商品领3京豆(0/3)", reward=u"点击2个商品且浏览10s可得京豆+1",
         btn=u"去完成", y=1880),
]
ui = PanelUI([dict(t) for t in T])
log = Log()
done, tried = Task7NineNine()._process_tasks(ui, log, threading.Event())
check("J1 两个可做任务都做了", done == 2, "done=%d tried=%d" % (done, tried))
check("J2 尝试数 2", tried == 2, "got %d" % tried)
check("J3 已完成行没被点", all(abs(p[1] - 1707) > 50 for p in ui.taps),
      "taps=%s" % ui.taps)
check("J4 点完都按过返回", ui.backs >= 2, "backs=%d" % ui.backs)
check("J5 每个任务都停够 X+4（默认10s / 浏览10s->14s）",
      14.0 in ui.sleeps and ui.sleeps.count(10.0) >= 1,
      "sleeps=%s" % sorted(set(ui.sleeps)))
check("J6 日志里有「没有可做任务」", u"没有可做任务" in log.text())

# 引导层任务：只试一次，不重复点
ui = PanelUI([dict(T[1])], guide_tasks=[u"看视频领红包(0/1)"])
log = Log()
done, tried = Task7NineNine()._process_tasks(ui, log, threading.Event())
check("J7 引导层任务不算完成", done == 0, "done=%d" % done)
check("J8 引导层任务只尝试一次", tried == 1, "tried=%d" % tried)
check("J9 日志提到引导层", u"添加小组件到手机桌面" in log.text())
check("J10 点过 X 关闭", any(abs(p[0] - GUIDE_CLOSE_PT[0]) <= 60
                             and abs(p[1] - GUIDE_CLOSE_PT[1]) <= 60 for p in ui.taps),
      "taps=%s" % ui.taps)

# 任务做完但按钮不变（服务端没算完成）-> 不能死循环
ui = PanelUI([dict(T[1])], completes=False)
log = Log()
done, tried = Task7NineNine()._process_tasks(ui, log, threading.Event())
check("J11 按钮不变也只点一次", tried == 1, "tried=%d" % tried)
check("J12 不会重复点同一个按钮", len([p for p in ui.taps if p[0] >= 827]) == 1,
      "taps=%s" % ui.taps)

# 空列表 -> 直接收尾
ui = PanelUI([])
log = Log()
done, tried = Task7NineNine()._process_tasks(ui, log, threading.Event())
check("J13 没有任务立即收尾", (done, tried) == (0, 0))

# 读失败重试：前两次空，第三次读到
ui = PanelUI([dict(T[1])], fail_reads=2)
log = Log()
done, tried = Task7NineNine()._process_tasks(ui, log, threading.Event())
check("J14 读失败会重读", done == 1, "done=%d" % done)

# 一直读失败 -> 收尾而不是抛错
ui = PanelUI([dict(T[1])], fail_reads=1000)
log = Log()
done, tried = Task7NineNine()._process_tasks(ui, log, threading.Event())
check("J15 连续读失败会收尾", done == 0 and u"读不到页面" in log.text(), log.text()[-200:])

# 可滚动：任务在下方，滚上来才点
ui = PanelUI([dict(title=u"下方任务(0/1)", reward=u"完成任务最高得1个京豆+1",
                   btn=u"去完成", y=2300)], scrollable=True)
log = Log()
done, tried = Task7NineNine()._process_tasks(ui, log, threading.Event())
check("J16 需要滚动时会滚动", len(ui.swipes) >= 1, "swipes=%d" % len(ui.swipes))
check("J17 滚动后完成任务", done == 1, "done=%d log=%s" % (done, log.text()[-300:]))

# ================================================================ K 返回链路
print("\n--- K. 返回链路 ---")
ui = PanelUI([dict(T[1])], stay_away=True)
log = Log()
done, tried = Task7NineNine()._process_tasks(ui, log, threading.Event())
check("K1 回不到弹层会重进", u"重进" in log.text(), log.text()[-300:])
check("K2 重进次数有上限", log.text().count(u"重进") <= MAX_REENTER + 2)
check("K3 回不去不会崩", done == 0)

ui = PanelUI([dict(T[1])])
log = Log()
r = Task7NineNine()._return_to_panel(ui, log)
check("K4 弹层在时不用返回", r is True and ui.backs == 0)

ui = PanelUI([dict(T[1])])
ui.away = True
log = Log()
r = Task7NineNine()._return_to_panel(ui, log)
check("K5 在落地页按一次返回就回弹层", r is True and ui.backs == 1, "backs=%d" % ui.backs)

# ================================================================ L stop_event
print("\n--- L. stop_event ---")
ev = threading.Event()
ev.set()
ui = PanelUI([dict(t) for t in T])
log = Log()
done, tried = Task7NineNine()._process_tasks(ui, log, ev)
check("L1 stop 立即生效", (done, tried) == (0, 0) and not ui.taps)
check("L2 stop 后不按返回", ui.backs == 0)

# ================================================================ M 完成判定 / 扫描成本
print("\n--- M. _row_completed 与收尾扫描 ---")
m5 = Task7NineNine()

ui = PanelUI([dict(T[1])])
r = parse_task_rows(ui.nodes())[0]
ui.tasks[0]["btn"] = u"已完成"
check("M1 按钮变【已完成】才算完成", m5._row_completed(ui, r) is True)

ui = PanelUI([dict(T[1])])
r = parse_task_rows(ui.nodes())[0]
check("M2 按钮还是【去完成】不算完成", m5._row_completed(ui, r) is False)

ui = PanelUI([])
check("M3 行不在屏内时不冤枉它", m5._row_completed(ui, {"key": u"不存在"}) is True)

# 收尾扫描：没有可做任务时返回 False，且滑动次数受控
ui = PanelUI([dict(T[0])])                 # 只有已完成行
log = Log()
found = m5._sweep_for_target(ui, log, set())
check("M4 没漏任务时扫描返回 False", found is False)
check("M5 扫描滑动次数受控（<= 2*SWEEP_SCROLLS）",
      len(ui.swipes) <= 2 * SWEEP_SCROLLS, "swipes=%d" % len(ui.swipes))
check("M6 扫描只回顶部+下扫，不点任何东西", ui.taps == [])

# 全部尝试过的行不算「漏掉」
ui = PanelUI([dict(T[1])])
log = Log()
check("M7 已尝试过的行不算漏",
      m5._sweep_for_target(ui, log, set([u"看视频领红包"])) is False)

# 没尝试过的可做行 -> 扫到
ui = PanelUI([dict(T[1])])
log = Log()
check("M8 扫到没做过的任务", m5._sweep_for_target(ui, log, set()) is True)
check("M9 扫到会写日志", u"全表扫描发现" in log.text())


# ================================================================ 汇总
print("\n" + "=" * 60)
print("通过 %d / %d" % (len(PASSED), len(PASSED) + len(FAILED)))
if FAILED:
    print("失败用例：")
    for f in FAILED:
        print("  -", f)
    sys.exit(1)
print("全部通过")
