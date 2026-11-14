# -*- coding: utf-8 -*-
"""任务11【国家补贴x超级补贴】离线回归（不连手机、不连 Appium）。

覆盖：
  A. 模块元信息 / 需求常量
  B. 动态 X 解析（20秒/10秒/10s/15 S）与 X+4 停留
  C. task_key 去掉 (N/M) 进度
  D. 真机夹具页面判定（含「弹窗与原页节点混叠」陷阱）
  E. find_entry 首页入口卡片
  F. 真机夹具任务行配对（每个页面精确断言）
  G. 合成排除逻辑（分享得红包/立即邀请/已完成/领取奖励/背景页商品卡）
  H. parse_claim_buttons / find_happy
  I. pick_target 安全区与黑名单 / panel_sig
  J. SimUI 状态机跑完整 run()（做任务 -> 领奖 -> 循环 -> 无可做任务结束）
  K. 动态 X 的 X+4 停留与 back 次数
  L. 领完后任务重新可做时的上限保护（不死循环）
  M. _recover / _dismiss_float / _tap_reward 轮询
  N. stop_event

夹具（真机 1080x2340，2026-11-12 抓的）：
  _fixture_bt_home.xml       京东首页（desc='国家补贴×超级补贴,' 卡片）
  _fixture_bt_page.xml       补贴页（无弹窗，H5 埋点文案）
  _fixture_bt_panel.xml      弹窗初始（3 个【去看看】，2 个带浏览Xs）
  _fixture_bt_panel2.xml     弹窗初始另一帧（进度 1/2）
  _fixture_bt_claimable.xml  做完 1 个任务（1 个【领取奖励】+ 1 个可做）
  _fixture_bt_happy.xml      点【领取奖励】后（【开心收下】）
  _fixture_bt_scroll1.xml    滚动 1 屏（出现【去完成】）
  _fixture_bt_scroll2.xml    滚动 2 屏（出现【浏览页面10s】小写 s）
  _fixture_bt_scroll3.xml    滚动 3 屏（出现【已完成】+ 无进度标题任务）
  _fixture_bt_landing.xml    任务落地页（无弹窗标题）
"""
import io
import re
import sys
import threading
import xml.etree.ElementTree as ET

sys.path.insert(0, ".")

import modules.task11_subsidy as MOD
from modules.task11_subsidy import (
    Task11Subsidy, browse_seconds, task_key, parse_task_rows,
    parse_claim_buttons, find_happy, is_bt_page, is_panel, panel_sig,
    pick_target, find_entry, BROWSE_RE, PROGRESS_RE,
    BROWSE_EXTRA, PAGE_WAIT, REWARD_POS, FLOAT_CLOSE_POS,
    BTN_MIN_X, ROW_TOL, SAFE_TOP, SAFE_BOTTOM, MAX_TASKS, MAX_CYCLES,
    PANEL_MARK, HAPPY_MARK, CLAIM_MARK, ENTRY_MARK,
    BROWSE_BUTTON_TEXTS,
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


HOME = load("_fixture_bt_home.xml")
PAGE = load("_fixture_bt_page.xml")
PANEL = load("_fixture_bt_panel.xml")
PANEL2 = load("_fixture_bt_panel2.xml")
CLAIMABLE = load("_fixture_bt_claimable.xml")
HAPPY = load("_fixture_bt_happy.xml")
SCROLL1 = load("_fixture_bt_scroll1.xml")
SCROLL2 = load("_fixture_bt_scroll2.xml")
SCROLL3 = load("_fixture_bt_scroll3.xml")
LANDING = load("_fixture_bt_landing.xml")


# ================================================================ A
print("\n--- A. 元信息与需求常量 ---")
check("A1 模块名", Task11Subsidy.name == u"国家补贴×超级补贴")
check("A2 图标非空", bool(Task11Subsidy.icon))
check("A3 描述提到查看奖励与领取",
      u"查看奖励" in Task11Subsidy.description
      and u"领取奖励" in Task11Subsidy.description)
check("A4 进页面等 3s", PAGE_WAIT == 3.0)
check("A5 停留 X+4", BROWSE_EXTRA == 4)
check("A6 查看奖励坐标", REWARD_POS == (270, 796))
check("A7 按钮贴右阈值/行容差", (BTN_MIN_X, ROW_TOL) == (700, 75))
check("A8 安全区（下界=屏幕高，真机末行 y2=2332 不能被过滤）",
      SAFE_TOP == 600 and SAFE_BOTTOM == 2340)
check("A9 上限保护存在", MAX_TASKS > 0 and MAX_CYCLES > 0)
check("A10 按钮白名单", BROWSE_BUTTON_TEXTS == (u"去看看", u"去完成"),
      "got %s" % (BROWSE_BUTTON_TEXTS,))

# ================================================================ B
print("\n--- B. 动态 X 与 X+4 ---")
for txt, want in [(u"浏览页面20秒", 20), (u"浏览页面10秒", 10),
                  (u"浏览页面10s", 10), (u"浏览页面15S", 15),
                  (u"浏览页面 8 秒", 8), (u"浏览页面5s", 5)]:
    m = BROWSE_RE.search(txt)
    check(u"B 解析 %s -> %d" % (txt, want), m is not None and int(m.group(1)) == want,
          "got %s" % (m.group(1) if m else None))
check("B7 无数字不匹配", BROWSE_RE.search(u"浏览页面") is None)
check("B8 无关文案不匹配", BROWSE_RE.search(u"每晚8点加码") is None)
check("B9 10s -> 14s", browse_seconds(10) == 14)
check("B10 20s -> 24s", browse_seconds(20) == 24)
check("B11 5s -> 9s", browse_seconds(5) == 9)
check("B12 0s -> 4s", browse_seconds(0) == 4)
check("B13 逐行秒数不同", browse_seconds(10) != browse_seconds(20))

# ================================================================ C
print("\n--- C. task_key 去进度 ---")
k0 = task_key(u"点击4个商品可领京豆(0/5)", 10)
k1 = task_key(u"点击4个商品可领京豆(1/5)", 10)
k2 = task_key(u"点击4个商品可领京豆(2/5)", 10)
check("C1 进度变化 key 不变", k0 == k1 == k2, "got %s/%s/%s" % (k0, k1, k2))
check("C2 不同秒数 key 不同", task_key(u"任务A(0/5)", 10) != task_key(u"任务A(0/5)", 20))
check("C3 不同标题 key 不同", task_key(u"任务A(0/5)", 10) != task_key(u"任务B(0/5)", 10))
check("C4 无进度标题也能做 key", bool(task_key(u"厨房卫浴补贴", 10)))
check("C5 PROGRESS_RE 命中", bool(PROGRESS_RE.search(u"点击5个商品可领3京豆(0/2)")))
check("C6 PROGRESS_RE 不误伤", not PROGRESS_RE.search(u"厨房卫浴补贴"))

# ================================================================ D
print("\n--- D. 页面判定（真机夹具） ---")
check("D1 首页不是弹窗", not is_panel(HOME))
check("D2 补贴页不是弹窗", not is_panel(PAGE))
check("D3 落地页不是弹窗", not is_panel(LANDING))
check("D4 弹窗页是弹窗", is_panel(PANEL))
check("D5 领取态仍是弹窗", is_panel(CLAIMABLE))
check("D6 开心收下态仍是弹窗", is_panel(HAPPY))
check("D7 滚动后仍是弹窗", is_panel(SCROLL3))
check("D8 首页不是补贴页", not is_bt_page(HOME))
check("D9 落地页不是补贴页", not is_bt_page(LANDING))
check("D10 补贴页是补贴页", is_bt_page(PAGE))
check("D11 弹窗叠加原页：is_bt_page 也为 True（混叠陷阱）",
      is_bt_page(PANEL),
      "弹层叠在补贴页上，dump 里两页节点混在一起；判弹窗只能用 is_panel")
check("D12 判弹窗不被混叠骗到", is_panel(PANEL) and not is_panel(PAGE))
check("D13 空节点安全", not is_panel([]) and not is_bt_page([]))

# ================================================================ E
print("\n--- E. 首页入口 ---")
e = find_entry(HOME)
check("E1 找到入口卡片", e is not None)
check("E2 入口 bounds 正确", e is not None and e["bounds"] == (23, 639, 530, 973),
      "got %s" % ((e["bounds"] if e else None),))
check("E3 首页节点里 desc 带乘号×",
      e is not None and ENTRY_MARK in e["desc"])
check("E4 补贴页找不到入口", find_entry(PAGE) is None)
check("E5 弹窗页找不到入口", find_entry(PANEL) is None)
check("E6 空节点安全", find_entry([]) is None)

# ================================================================ F
print("\n--- F. 真机夹具任务行配对 ---")
r_panel = parse_task_rows(PANEL)
check("F1 初始弹窗 2 个可做任务（3 个【去看看】里排除分享得红包）",
      len(r_panel) == 2, "got %d" % len(r_panel))
check("F2 初始弹窗标题正确",
      [r["title"] for r in r_panel] ==
      [u"点击5个商品可领3京豆(0/2)", u"点击4个商品可领京豆(0/5)"],
      "got %s" % [r["title"] for r in r_panel])
check("F3 初始弹窗都是 20s", [r["secs"] for r in r_panel] == [20, 20])
check("F4 按钮都是去看看", all(r["btn"] == u"去看看" for r in r_panel))
check("F5 按钮都贴右", all(r["btn_bounds"][0] >= 800 for r in r_panel))

r_claim = parse_task_rows(CLAIMABLE)
check("F6 领取态只剩 1 个可做（【领取奖励】不算可做）",
      len(r_claim) == 1, "got %d" % len(r_claim))

r_s1 = parse_task_rows(SCROLL1)
check("F7 滚动1屏配出 2 行", len(r_s1) == 2, "got %d" % len(r_s1))
check("F8 【去完成】那行没有浏览Xs -> 被排除",
      all(r["btn"] != u"去完成" for r in r_s1),
      "got %s" % [r["btn"] for r in r_s1])
check("F9 滚动1屏出现 10s 动态值", any(r["secs"] == 10 for r in r_s1))

r_s2 = parse_task_rows(SCROLL2)
check("F10 滚动2屏配出 5 行", len(r_s2) == 5, "got %d" % len(r_s2))
check("F11 小写 s 的 10s 被识别", [r["secs"] for r in r_s2] == [20, 10, 10, 10, 10],
      "got %s" % [r["secs"] for r in r_s2])
check("F12 滚动2屏标题正确",
      [r["title"] for r in r_s2] ==
      [u"点击4个商品可领京豆(2/5)", u"每日签到最高88京豆(0/11)",
       u"抽彩票券和手机(0/11)", u"上JOY游记抽千元礼(0/10)",
       u"逛更多优选会场(0/7)"],
      "got %s" % [r["title"] for r in r_s2])

r_s3 = parse_task_rows(SCROLL3)
check("F13 滚动3屏配出 6 行", len(r_s3) == 6, "got %d" % len(r_s3))
check("F14 【已完成】被排除", all(r["btn"] != u"已完成" for r in r_s3))
check("F15 无进度标题任务不被背景页商品卡抢走",
      [r["title"] for r in r_s3][-2:] ==
      [u"超级明星抽8888红包", u"厨房卫浴补贴"],
      "got %s" % [r["title"] for r in r_s3][-2:])
check("F16 不出现背景页商品名",
      not any(u"价格" in r["title"] or u"沐浴露" in r["title"] for r in r_s3),
      "got %s" % [r["title"] for r in r_s3])
check("F17 首页/补贴页/落地页无任务",
      parse_task_rows(HOME) == [] and parse_task_rows(PAGE) == []
      and parse_task_rows(LANDING) == [])
check("F18 空节点安全", parse_task_rows([]) == [])

# ================================================================ G
print("\n--- G. 合成排除逻辑 ---")
def synth(title, sub, btn, y=1200, sub_x1=192, title_x1=192):
    return [
        nd(title, title_x1, y, 770, y + 50),
        nd(sub, sub_x1, y + 71, 409, y + 123),
        nd(u"+3京豆", 407, y + 71, 517, y + 123),
        nd(btn, 869, y + 44, 984, y + 90),
    ]

excluded = [
    (u"分享得红包 最高8.8元", u"每晚8点加码", u"去看看"),
    (u"邀请5人助力 可得50京豆", u"再拉5人", u"立即邀请"),
    (u"点击5个商品可领3京豆(0/2)", u"浏览页面20秒", u"已完成"),
    (u"点击5个商品可领3京豆(0/2)", u"浏览页面20秒", u"领取奖励"),
    (u"点击5个商品可领3京豆(0/2)", u"浏览页面X秒", u"去看看"),
]
for i, (t, s, b) in enumerate(excluded):
    rows = parse_task_rows(synth(t, s, b))
    check("G%d 排除 %s/%s" % (i + 1, b, s), rows == [],
          "got %s" % rows)

ok_rows = parse_task_rows(synth(u"任务(0/3)", u"浏览页面20秒", u"去完成"))
check("G6 【去完成】+浏览Xs 可做", len(ok_rows) == 1 and ok_rows[0]["secs"] == 20,
      "got %s" % ok_rows)
check("G7 无进度标题但左对齐可做",
      len(parse_task_rows(synth(u"厨房卫浴补贴", u"浏览页面10秒", u"去看看"))) == 1)
check("G8 标题被背景页商品卡顶掉（不对齐）-> 标题留空",
      parse_task_rows(synth(u"厨房卫浴补贴", u"浏览页面10秒", u"去看看",
                            title_x1=22))[0]["title"] == u"")
check("G9 退化 bounds 被忽略",
      parse_task_rows([nd(u"浏览页面10秒", 100, 100, 50, 50),
                       nd(u"去看看", 869, 120, 984, 160)]) == [])
check("G10 按钮不在右侧被忽略",
      parse_task_rows(synth(u"任务(0/3)", u"浏览页面20秒", u"去看看")[:3]
                      + [nd(u"去看看", 300, 1244, 400, 1290)]) == [])
# 容差：行距约 195px，副标题不能串到隔壁行
two = (synth(u"任务A(0/3)", u"浏览页面10秒", u"去看看", y=1000)
       + synth(u"任务B(0/3)", u"浏览页面20秒", u"去完成", y=1195))
r2 = parse_task_rows(two)
check("G11 两行不串档", len(r2) == 2 and [r["secs"] for r in r2] == [10, 20],
      "got %s" % [(r["title"], r["secs"]) for r in r2])

# ================================================================ H
print("\n--- H. 领取与开心收下 ---")
check("H1 领取态找到 1 个【领取奖励】", len(parse_claim_buttons(CLAIMABLE)) == 1)
check("H2 初始弹窗没有【领取奖励】", parse_claim_buttons(PANEL) == [])
check("H3 开心收下态没有【领取奖励】", parse_claim_buttons(HAPPY) == [])
check("H4 领取按钮贴右",
      parse_claim_buttons(CLAIMABLE)[0]["cx"] >= BTN_MIN_X)
hb = find_happy(HAPPY)
check("H5 找到【开心收下】", hb is not None)
check("H6 开心收下 bounds 正确",
      hb is not None and hb["bounds"] == (222, 1265, 858, 1389),
      "got %s" % ((hb["bounds"] if hb else None),))
check("H7 其它页面没有【开心收下】",
      all(find_happy(x) is None for x in (PANEL, CLAIMABLE, HOME, PAGE, LANDING)))
check("H8 空节点安全", parse_claim_buttons([]) == [] and find_happy([]) is None)

# ================================================================ I
print("\n--- I. pick_target / panel_sig ---")
rows = parse_task_rows(PANEL)
check("I1 无黑名单挑第一行", pick_target(rows, set())["title"] == rows[0]["title"])
check("I2 黑名单跳过", pick_target(rows, {rows[0]["key"]})["title"] == rows[1]["title"])
check("I3 全拉黑返回 None", pick_target(rows, {r["key"] for r in rows}) is None)
check("I4 安全区外不选中",
      pick_target([{"key": "x", "btn_bounds": (800, 100, 980, 200)}], set()) is None)
check("I5 下边界外不选中",
      pick_target([{"key": "x", "btn_bounds": (800, 2330, 980, 2400)}], set()) is None)
check("I6 panel_sig 稳定", panel_sig(PANEL) == panel_sig(PANEL))
check("I7 不同页面签名不同", panel_sig(PANEL) != panel_sig(SCROLL2))
check("I8 空节点签名为 None", panel_sig([]) is None)


# ================================================================ 状态机
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
        return u"\n".join(u"[%s] %s" % (lv, m) for lv, m in self.lines)


def task_nodes(tasks, claims, extra=()):
    """按真机行结构造弹窗节点：标题 x1=192、副标题 x1=192、按钮 x1=869。"""
    out = [nd(PANEL_MARK, 288, 866, 706, 932),
           nd(u"补贴超市", 640, 481, 780, 528),
           nd(u"超补惊喜权益", 115, 874, 343, 921),
           nd(u"商品卡文案 价格: 9.9元", 22, 1911, 1061, 2260),
           nd(u"去抢购", 918, 1760, 1056, 1884)]
    for i, t in enumerate(tasks):
        y = 1000 + i * 195
        out += [
            nd(t["title"], 192, y, 770, y + 50),
            nd(u"浏览页面%d秒" % t["secs"], 192, y + 71, 409, y + 123),
            nd(u"+3京豆", 407, y + 71, 517, y + 123),
            nd(t["btn"], 869, y + 44, 984, y + 90),
        ]
        t["pos"] = (926, y + 67)
    for i, c in enumerate(claims):
        y = 1000 + (len(tasks) + i) * 195
        out += [
            nd(c["title"], 192, y, 770, y + 50),
            nd(u"浏览页面%d秒" % c["secs"], 192, y + 71, 409, y + 123),
            nd(CLAIM_MARK, 849, y + 44, 1001, y + 90),
        ]
        c["pos"] = (925, y + 67)
    out += list(extra)
    return out


class SimUI(object):
    """状态机替身：home -> page -> panel -> landing -> panel(claimable) -> happy。"""
    W = 1080
    H = 2340

    def __init__(self, specs, reappear=False, lost_on_back=False,
                 float_visible=True, stop=None):
        # specs: [(title, secs, btn)]
        self.tasks = [{"title": t, "secs": s, "btn": b} for t, s, b in specs]
        self.claims = []
        self.reappear = reappear
        self.lost_on_back = lost_on_back
        self.float_visible = float_visible
        self.stop = stop
        self.state = "home"
        self.pending = None
        self.pending_claim = None
        self.taps = []
        self.swipes = []
        self.backs = 0
        self.sleeps = []
        self.invalidated = 0
        self.browses = 0
        self.claimed = 0
        self.reward_taps = 0

    def sx(self, x):
        return x

    def sy(self, y):
        return y

    def invalidate(self):
        self.invalidated += 1

    def sleep(self, s):
        self.sleeps.append(s)
        return True

    def restart_to_home(self, wait=6):
        self.state = "home"
        return True

    def goto_home(self, max_back=10):
        self.state = "home"
        return True

    def back(self, pause=2.0):
        self.backs += 1
        if self.state == "landing":
            if self.lost_on_back:
                self.state = "lost"
            else:
                self.state = "panel"
            if self.pending is not None:
                # 真机：做完后该行按钮变【领取奖励】，从可做列表消失
                if self.pending in self.tasks:
                    self.tasks.remove(self.pending)
                self.claims.append(dict(self.pending))
                self.pending = None
            self.browses += 1
        elif self.state in ("lost", "happy"):
            self.state = "page"

    def adb_swipe(self, x1, y1, x2, y2, duration=300):
        self.swipes.append((x1, y1, x2, y2))

    def adb_tap(self, pos, pause=1.5):
        p = (int(pos[0]), int(pos[1]))
        self.taps.append(p)
        x, y = p
        if self.state == "home":
            if abs(y - 683) < 40:
                self.state = "page"
            return
        if self.state in ("page", "lost"):
            if p == (270, 796):
                self.state = "panel"
                self.reward_taps += 1
            return
        if self.state == "panel":
            if p == FLOAT_CLOSE_POS:
                return
            for t in self.tasks:
                if p == t.get("pos"):
                    self.state = "landing"
                    self.pending = t
                    return
            for c in self.claims:
                if p == c.get("pos"):
                    self.state = "happy"
                    self.pending_claim = c
                    return
            return
        if self.state == "happy":
            if p == (540, 1327):
                c = self.pending_claim
                self.state = "panel"
                self.claimed += 1
                if c is not None:
                    if c in self.claims:
                        self.claims.remove(c)
                    if self.reappear:
                        self.tasks.append({"title": c["title"], "secs": c["secs"],
                                           "btn": c.get("btn", u"去看看")})
                self.pending_claim = None
            return

    def nodes(self):
        if self.state == "home":
            return [nd(u"", 23, 639, 530, 973, desc=ENTRY_MARK + u","),
                    nd(u"秒杀", 62, 544, 132, 601)]
        if self.state in ("page", "lost"):
            out = [nd(u"补贴超市", 640, 481, 780, 528),
                   nd(u"推荐", 35, 475, 174, 533),
                   nd(u"手动点击翻转测试", 22, 564, 517, 839, clickable=True)]
            if self.float_visible:
                out.append(nd(u"", 1019, 1300, 1053, 1334, desc=u"关闭"))
            return out
        if self.state == "landing":
            return [nd(u"商品详情", 100, 300, 900, 400),
                    nd(u"去看看", 300, 500, 400, 550)]
        extra = []
        if self.state == "happy":
            extra = [nd(HAPPY_MARK, 222, 1265, 858, 1389, clickable=True)]
        return task_nodes(self.tasks, self.claims, extra)


def run_sim(sim, stop=None, max_tasks=None):
    """用替身跑完整 run()，不连设备。"""
    old_driver = MOD.driver
    old_jdui = MOD.JDUI
    old_max = MOD.MAX_TASKS
    old_cycles = MOD.MAX_CYCLES

    class FakeDriver(object):
        @staticmethod
        def get_driver():
            return object()

    MOD.driver = FakeDriver()
    MOD.JDUI = lambda *a, **kw: sim
    if max_tasks is not None:
        MOD.MAX_TASKS = max_tasks
    log = Log()
    try:
        Task11Subsidy().run(log, stop or threading.Event())
    finally:
        MOD.driver = old_driver
        MOD.JDUI = old_jdui
        MOD.MAX_TASKS = old_max
        MOD.MAX_CYCLES = old_cycles
    return log


# ================================================================ J
print("\n--- J. 完整 run() 状态机 ---")
specs = [(u"点击5个商品可领3京豆(0/2)", 20, u"去看看"),
         (u"点击4个商品可领京豆(0/5)", 10, u"去看看"),
         (u"每日签到最高88京豆(0/11)", 10, u"去完成")]
sim = SimUI(specs)
log = run_sim(sim)
check("J1 run 正常结束（log.done 被调用）",
      any(lv == "DONE" for lv, _ in log.lines), log.text()[-300:])
check("J2 3 个任务都做了", sim.browses == 3, "got %d" % sim.browses)
check("J3 3 次奖励都领了", sim.claimed == 3, "got %d" % sim.claimed)
check("J4 每个任务 back 一次", sim.backs == 3, "got %d" % sim.backs)
check("J5 进补贴页等了 3s", PAGE_WAIT in sim.sleeps)
check("J6 三种秒数都按 X+4 停留",
      24 in sim.sleeps and 14 in sim.sleeps,
      "sleeps=%s" % sorted(set(round(s, 1) for s in sim.sleeps))[:20])
check("J7 20s 任务停 24s、10s 任务停 14s",
      sim.sleeps.count(24) == 1 and sim.sleeps.count(14) == 2,
      "got 24=%d 14=%d" % (sim.sleeps.count(24), sim.sleeps.count(14)))
check("J8 点了【查看奖励】", sim.reward_taps >= 1)
check("J9 关过右侧悬浮红包", FLOAT_CLOSE_POS in sim.taps)
check("J10 点了【开心收下】3 次", sim.taps.count((540, 1327)) == 3)
check("J11 循环在无可做任务时结束（有结束日志）",
      any(u"没有可做任务" in m for _, m in log.lines), log.text()[-300:])
check("J12 完成日志含次数",
      any(u"完成 3 次浏览任务，领取 3 次奖励" in m for lv, m in log.lines
          if lv == "DONE"), log.text()[-200:])
check("J13 没有把 20s 写成常量（10s 也按 14s 停）",
      sim.sleeps.count(24) == 1 and sim.sleeps.count(14) == 2)

# ================================================================ K
print("\n--- K. 动态 X 单独验证 ---")
for x in (5, 10, 15, 20, 30):
    s2 = SimUI([(u"任务(0/1)", x, u"去看看")])
    l2 = run_sim(s2)
    check("K X=%d -> 停留 %ds" % (x, x + 4),
          (x + 4) in s2.sleeps and s2.browses == 1 and s2.claimed == 1,
          "sleeps=%s" % s2.sleeps[:8])

# ================================================================ L
print("\n--- L. 领完后任务重新可做：上限保护 ---")
sim3 = SimUI([(u"点击4个商品可领京豆(0/5)", 10, u"去看看")], reappear=True)
log3 = run_sim(sim3, max_tasks=3)
check("L1 不死循环，按 MAX_TASKS 收尾", sim3.browses <= 3,
      "got %d" % sim3.browses)
check("L2 达到上限有 WARN", any(u"上限" in m for _, m in log3.lines))
check("L3 领取次数与浏览次数一致", sim3.claimed == sim3.browses,
      "browses=%d claimed=%d" % (sim3.browses, sim3.claimed))
check("L4 run 正常收尾", any(lv == "DONE" for lv, _ in log3.lines))

# ================================================================ M
print("\n--- M. 恢复与轮询 ---")
sim4 = SimUI([(u"任务(0/1)", 10, u"去看看")], lost_on_back=True)
log4 = run_sim(sim4)
check("M1 back 丢弹窗后能恢复并完成", sim4.browses >= 1 and sim4.claimed >= 1,
      "browses=%d claimed=%d" % (sim4.browses, sim4.claimed))
check("M2 恢复时重开过弹窗", sim4.reward_taps >= 2,
      "reward_taps=%d" % sim4.reward_taps)
check("M3 恢复后 run 正常结束", any(lv == "DONE" for lv, _ in log4.lines))

# 浮层不在时不应多点关闭
sim5 = SimUI([(u"任务(0/1)", 10, u"去看看")], float_visible=False)
run_sim(sim5)
check("M4 浮层不在时不多余点关闭", FLOAT_CLOSE_POS not in sim5.taps)

# _recover 在弹窗本来就在时应直接 True
sim6 = SimUI([(u"任务(0/1)", 10, u"去看看")])
sim6.state = "panel"
check("M5 弹窗在场 _recover 直接返回 True",
      Task11Subsidy()._recover(sim6, Log()) is True)

# ================================================================ N
print("\n--- N. stop_event ---")
ev = threading.Event()
ev.set()
sim7 = SimUI([(u"任务(0/1)", 10, u"去看看")])
log7 = run_sim(sim7, stop=ev)
check("N1 预先 stop 不会做任务", sim7.browses == 0, "got %d" % sim7.browses)
check("N2 预先 stop 不会领奖", sim7.claimed == 0)

# ================================================================ 汇总
print("\n================ 汇总 ================")
print("PASS %d, FAIL %d" % (len(PASSED), len(FAILED)))
if FAILED:
    for f in FAILED:
        print("  FAILED: %s" % f)
    sys.exit(1)
print("ALL PASS")
