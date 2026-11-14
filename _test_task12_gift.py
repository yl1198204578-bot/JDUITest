# -*- coding: utf-8 -*-
"""任务12【京东好礼】离线回归（不连手机、不连 Appium）。

覆盖：
  A. 模块元信息 / 需求常量 / 确认没有领奖逻辑
  B. SUB_RE 动态 X 解析与 X+4 停留
  C. task_key 去掉 (N/M) 进度
  D. 真机夹具页面判定（含「弹窗与原页节点混叠」陷阱）
  E. 入口链路四个定位函数（新品 / 送礼新品 / 抽 / 赚次数）
  F. 真机夹具任务行配对（每屏精确断言 + 排除浏览票数）
  G. 合成排除逻辑与可视区过滤
  H. pick_target / panel_sig
  I. SimUI 状态机跑完整 run()（入口 -> 做任务 -> 无可做任务结束）
  J. 动态 X 单独验证（X+4、一次 back）
  K. 池子补位时的上限保护（不死循环）
  L. 恢复链路（丢弹窗 / 就地重点赚次数 / 整链重进）
  M. stop_event
  N. 真机滚动到底静止与进度补位

夹具（真机 1080x2340，2026-11-13 抓的）：
  _fixture_gift_home.xml        京东首页（顶部【新品】tab）
  _fixture_gift_newtab.xml      新品页（二级 tab【送礼新品】）
  _fixture_gift_gift_tab.xml    送礼新品页（【好礼许愿】下【抽】图片按钮）
  _fixture_gift_wish.xml        好礼许愿机抽奖页（【赚次数】，无弹窗）
  _fixture_gift_panel.xml       任务弹窗初始帧（6 个可做任务）
  _fixture_gift_after_back.xml  浏览后 back 一次回到弹窗
  _fixture_gift_landing.xml     任务落地页（无弹窗标题）
  _fixture_gift_s1/s2/s4/s6/s7.xml  滚动各屏 / 到底静止 / 回顶
  _fixture_gift_cyc1_after.xml  做满一行后补位（进度变化）
"""
import io
import re
import sys
import threading
import xml.etree.ElementTree as ET

sys.path.insert(0, ".")

import modules.task12_gift as MOD
from modules.task12_gift import (
    Task12Gift, browse_seconds, task_key, parse_task_rows,
    pick_target, panel_sig, is_panel, is_wish_page, is_new_page,
    is_gift_page, find_new_tab, find_gift_tab, find_chou_button,
    find_earn_button, SUB_RE, PROGRESS_RE, BTN_TEXTS, DONE_TEXTS,
    BROWSE_EXTRA, PANEL_MARK, WISH_PAGE_MARK, NEW_PAGE_MARK,
    GIFT_PAGE_MARK, EARN_TEXT, CHOU_POS, EARN_POS, GIFT_TAB_DY,
    BTN_MIN_X, SUB_MAX_X, ROW_TOL, SAFE_TOP, SAFE_BOTTOM,
    MAX_TASKS, MAX_CYCLES, MAX_STEPS, MAX_SCROLLS, MAX_PER_TASK,
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
    """解析成 jd_ui.nodes() 同样的结构（退化 bounds 直接丢掉）。"""
    s = io.open(path, encoding="utf-8", errors="replace").read()
    root = ET.fromstring(s.encode("utf-8"))
    out = []
    for n in root.iter():
        m = _BOUNDS_RE.match(n.get("bounds") or "")
        if not m:
            continue
        b = tuple(int(x) for x in m.groups())
        if b[2] <= b[0] or b[3] <= b[1]:
            continue
        out.append({
            "text": (n.get("text") or "").strip(),
            "desc": (n.get("content-desc") or "").strip(),
            "bounds": b,
            "clickable": n.get("clickable") == "true",
            "class": (n.get("class") or "").rsplit(".", 1)[-1],
        })
    return out


def nd(text, x1, y1, x2, y2, clickable=False, desc="", cls="TextView"):
    return {"text": text, "desc": desc, "bounds": (x1, y1, x2, y2),
            "clickable": clickable, "class": cls}


HOME = load("_fixture_gift_home.xml")
NEWTAB = load("_fixture_gift_newtab.xml")
GIFTTAB = load("_fixture_gift_gift_tab.xml")
WISH = load("_fixture_gift_wish.xml")
PANEL = load("_fixture_gift_panel.xml")
AFTER_BACK = load("_fixture_gift_after_back.xml")
LANDING = load("_fixture_gift_landing.xml")
S1 = load("_fixture_gift_s1.xml")
S2 = load("_fixture_gift_s2.xml")
S4 = load("_fixture_gift_s4.xml")
S6 = load("_fixture_gift_s6.xml")
S7 = load("_fixture_gift_s7.xml")
CYC1 = load("_fixture_gift_cyc1_after.xml")


# ================================================================ A
print("\n--- A. 元信息、常量、确认没有领奖逻辑 ---")
check("A1 模块名", Task12Gift.name == u"京东好礼")
check("A2 图标非空", bool(Task12Gift.icon))
check("A3 描述含完整入口链路",
      all(k in Task12Gift.description
          for k in (u"新品", u"送礼新品", u"赚次数", u"弹窗")),
      Task12Gift.description)
check("A4 描述明确无需领取奖励", u"无需领取奖励" in Task12Gift.description)
check("A5 停留 X+4", BROWSE_EXTRA == 4)
check("A6 按钮白名单", BTN_TEXTS == (u"逛一逛", u"去完成"),
      "got %s" % (BTN_TEXTS,))
check("A7 弹窗独有标题", PANEL_MARK == u"做任务获得许愿次数")
check("A8 页面标记常量",
      (WISH_PAGE_MARK, NEW_PAGE_MARK, GIFT_PAGE_MARK, EARN_TEXT)
      == (u"好礼许愿机", u"京东新品", u"品质好礼逛京东", u"赚次数"))
check("A9 安全区上界=790（tab 区 y<=778）", SAFE_TOP == 790)
check("A10 安全区下界=2320", SAFE_BOTTOM == 2320)
check("A11 按钮贴右/行容差", (BTN_MIN_X, SUB_MAX_X, ROW_TOL) == (700, 700, 90))
check("A12 参考坐标", CHOU_POS == (994, 739) and EARN_POS == (927, 1685)
      and GIFT_TAB_DY == -10)
check("A13 上限保护齐全",
      all(x > 0 for x in (MAX_TASKS, MAX_CYCLES, MAX_STEPS,
                          MAX_SCROLLS, MAX_PER_TASK)))
_methods = [m for m in dir(Task12Gift) if m.startswith("_")]
check("A14 模块无领奖/开心收下方法",
      not any(("claim" in m or "happy" in m or "reward" in m)
              for m in _methods),
      "got %s" % _methods)
check("A15 模块无领取按钮解析函数",
      not hasattr(MOD, "parse_claim_buttons")
      and not hasattr(MOD, "find_happy")
      and not hasattr(MOD, "CLAIM_MARK")
      and not hasattr(MOD, "HAPPY_MARK"))
check("A16 完成态文案在排除表内",
      all(k in DONE_TEXTS for k in (u"已完成", u"去助力", u"去下单", u"领取奖励")))

# ================================================================ B
print("\n--- B. 动态 X 与 X+4 ---")
for txt, want in [(u"浏览25s得许愿次数+2", 25), (u"浏览5s得许愿次数+1", 5),
                  (u"浏览10秒得许愿次数", 10), (u"浏览 15 S 得 许愿次数", 15),
                  (u"浏览30s得许愿次数+3", 30), (u"浏览20s得许愿次数", 20)]:
    m = SUB_RE.search(txt)
    check(u"B 解析 %s -> %d" % (txt, want),
          m is not None and int(m.group(1)) == want,
          "got %s" % (m.group(1) if m else None))
for txt in (u"浏览5s得浏览票数+1", u"浏览5s得许愿机会+1",
            u"助力成功得许愿次数+1", u"下单可得许愿次数+1",
            u"浏览页面20秒", u"浏览", u"每晚8点加码", u"浏览5s得许愿票数+1"):
    check(u"B 排除 %s" % txt, SUB_RE.search(txt) is None)
check("B 25s -> 29s", browse_seconds(25) == 29)
check("B 5s -> 9s", browse_seconds(5) == 9)
check("B 10s -> 14s", browse_seconds(10) == 14)
check("B 20s -> 24s", browse_seconds(20) == 24)
check("B 0s -> 4s", browse_seconds(0) == 4)
check("B 逐行秒数不同", browse_seconds(25) != browse_seconds(5))

# ================================================================ C
print("\n--- C. task_key 去进度 ---")
k1 = task_key(u"浏览精选会场(1/4)", 5)
k2 = task_key(u"浏览精选会场(2/4)", 5)
k3 = task_key(u"浏览精选会场(3/4)", 5)
check("C1 进度变化 key 不变", k1 == k2 == k3,
      "got %s/%s/%s" % (k1, k2, k3))
check("C2 不同秒数 key 不同",
      task_key(u"浏览会场(0/4)", 5) != task_key(u"浏览会场(0/4)", 25))
check("C3 不同标题 key 不同",
      task_key(u"逛逛好礼频道(0/1)", 5) != task_key(u"逛逛精选频道(0/1)", 5))
check("C4 无进度标题也能做 key", bool(task_key(u"逛家电家居领京豆", 5)))
check("C5 PROGRESS_RE 命中", bool(PROGRESS_RE.search(u"浏览精选会场(1/4)")))
check("C6 PROGRESS_RE 不误伤", not PROGRESS_RE.search(u"来农场浇水免费领水果"))

# ================================================================ D
print("\n--- D. 页面判定（真机夹具） ---")
check("D1 首页不是弹窗", not is_panel(HOME))
check("D2 新品页不是弹窗", not is_panel(NEWTAB))
check("D3 送礼新品页不是弹窗", not is_panel(GIFTTAB))
check("D4 抽奖页不是弹窗", not is_panel(WISH))
check("D5 落地页不是弹窗", not is_panel(LANDING))
check("D6 初始帧是弹窗", is_panel(PANEL))
check("D7 back 一次回来仍是弹窗", is_panel(AFTER_BACK))
check("D8 滚动后仍是弹窗", is_panel(S1) and is_panel(S6) and is_panel(S7))
check("D9 弹窗叠加原页：is_wish_page 也为 True（混叠陷阱）",
      is_wish_page(PANEL),
      "弹层叠在抽奖页上，dump 里两页节点混在一起；判弹窗只能用 is_panel")
check("D10 判弹窗不被混叠骗到", is_panel(PANEL) and not is_panel(WISH))
check("D11 首页不是新品页", not is_new_page(HOME))
check("D12 新品页是新品页", is_new_page(NEWTAB))
check("D13 送礼新品页同时含两种页标记",
      is_gift_page(GIFTTAB) and is_new_page(GIFTTAB))
check("D14 首页不是送礼新品页", not is_gift_page(HOME))
check("D15 抽奖页是好礼许愿机", is_wish_page(WISH))
check("D16 落地页无抽奖页标记", not is_wish_page(LANDING))
check("D17 空节点安全",
      all(not f([]) for f in (is_panel, is_wish_page, is_new_page,
                              is_gift_page)))

# ================================================================ E
print("\n--- E. 入口链路定位 ---")
check("E1 首页【新品】tab", find_new_tab(HOME) == (637, 162),
      "got %s" % (find_new_tab(HOME),))
check("E2 新品页仍可见顶部【新品】tab", find_new_tab(NEWTAB) == (637, 162))
check("E3 弹窗页找不到首页 tab", find_new_tab(PANEL) is None)
check("E4 底部同名【新品】文案不当作 tab",
      find_new_tab([nd(u"新品", 562, 1600, 712, 1700)]) is None)
check("E5 新品页【送礼新品】tab", find_gift_tab(NEWTAB) == (514, 436),
      "got %s" % (find_gift_tab(NEWTAB),))
check("E6 选中态的【送礼新品】也能定位", find_gift_tab(GIFTTAB) == (502, 448),
      "got %s" % (find_gift_tab(GIFTTAB),))
check("E7 首页没有二级 tab", find_gift_tab(HOME) is None)
check("E8 送礼新品页找到【抽】", find_chou_button(GIFTTAB) == (994, 739),
      "got %s" % (find_chou_button(GIFTTAB),))
check("E9 其它页面没有【抽】",
      all(find_chou_button(x) is None for x in (HOME, NEWTAB, WISH, PANEL)))
check("E10 【抽】必须是 clickable Image",
      find_chou_button([nd(u"image", 954, 706, 1034, 772, cls="Image")]) is None
      and find_chou_button([nd(u"image", 954, 706, 1034, 772,
                               clickable=True)]) is None)
_chou_node = nd(u"image", 954, 706, 1034, 772, clickable=True, cls="Image")
check("E11 合成 clickable Image 能定位",
      find_chou_button([_chou_node]) == (994, 739))
check("E12 【抽】区域外不要（x1<900）",
      find_chou_button([nd(u"image", 800, 706, 880, 772,
                           clickable=True, cls="Image")]) is None)
check("E13 【抽】区域外不要（y 不在 650~820）",
      find_chou_button([nd(u"image", 954, 900, 1034, 966,
                           clickable=True, cls="Image")]) is None)
check("E14 多个候选挑最窄的那个",
      find_chou_button([nd(u"image", 950, 706, 1050, 772,
                           clickable=True, cls="Image"), _chou_node]) == (994, 739))
check("E15 抽奖页找到【赚次数】", find_earn_button(WISH) == (927, 1685),
      "got %s" % (find_earn_button(WISH),))
check("E16 弹窗页仍能找到【赚次数】（混叠节点）",
      find_earn_button(PANEL) == (927, 1685))
check("E17 首页/新品页没有【赚次数】",
      find_earn_button(HOME) is None and find_earn_button(NEWTAB) is None)
check("E18 空节点安全",
      all(f([]) is None for f in (find_new_tab, find_gift_tab,
                                  find_chou_button, find_earn_button)))

# ================================================================ F
print("\n--- F. 真机夹具任务行配对 ---")
r_panel = parse_task_rows(PANEL)
check("F1 初始弹窗 6 个可做任务", len(r_panel) == 6,
      "got %d" % len(r_panel))
check("F2 初始弹窗动态秒数 [25,5,5,5,5,5]",
      [r["secs"] for r in r_panel] == [25, 5, 5, 5, 5, 5],
      "got %s" % [r["secs"] for r in r_panel])
check("F3 初始弹窗按钮序列",
      [r["btn"] for r in r_panel]
      == [u"逛一逛", u"去完成", u"去完成", u"逛一逛", u"逛一逛", u"逛一逛"],
      "got %s" % [r["btn"] for r in r_panel])
check("F4 初始弹窗标题（去掉进度后）",
      [r["key"] for r in r_panel]
      == [u"逛逛好礼频道|25", u"浏览精选会场|5", u"浏览会场|5",
          u"逛逛精选频道|5", u"逛家电家居领京豆|5", u"逛京东服务抽888豆|5"],
      "got %s" % [r["key"] for r in r_panel])
check("F5 按钮都贴右", all(r["btn_bounds"][0] >= BTN_MIN_X for r in r_panel))
check("F6 所有行都在可视区内",
      all(SAFE_TOP <= r["cy"] <= SAFE_BOTTOM for r in r_panel),
      "got %s" % [r["cy"] for r in r_panel])
check("F7 【浏览5s得浏览票数+1】那行被排除（cy=1576）",
      all(abs(r["cy"] - 1576) > 5 for r in r_panel),
      "got %s" % [r["cy"] for r in r_panel])
check("F8 副标题都严格是得许愿次数",
      all(SUB_RE.search(r["sub"]) for r in r_panel))

check("F9 back 回来仍是弹窗且有 6 个可做任务",
      len(parse_task_rows(AFTER_BACK)) == 6)
check("F10 滚动 1 屏 5 行", len(parse_task_rows(S1)) == 5,
      "got %d" % len(parse_task_rows(S1)))
check("F11 滚动 2 屏 3 行", len(parse_task_rows(S2)) == 3)
check("F12 到底只剩 1 行", len(parse_task_rows(S4)) == 1)
check("F13 回顶又出现 3 行", len(parse_task_rows(S7)) == 3)
check("F14 补位帧 6 行但任务集合已变化",
      len(parse_task_rows(CYC1)) == 6
      and {r["key"] for r in parse_task_rows(CYC1)}
      != {r["key"] for r in r_panel},
      "got %s" % [r["key"] for r in parse_task_rows(CYC1)])
check("F15 首页/新品页/送礼新品页/抽奖页/落地页都没有任务",
      all(parse_task_rows(x) == [] for x in (HOME, NEWTAB, GIFTTAB,
                                             WISH, LANDING)))
check("F16 空节点安全", parse_task_rows([]) == [])

# ================================================================ G
print("\n--- G. 合成排除逻辑 ---")
def synth(title, sub, btn, y=1200, sub_x1=189, title_x1=189,
          btn_x1=838, extra=()):
    out = [
        nd(title, title_x1, y - 16, 808, y + 45),
        nd(sub, sub_x1, y + 50, 770, y + 99),
        nd(btn, btn_x1, y, 1025, y + 83),
    ]
    out += list(extra)
    return out


GOOD = u"浏览5s得许愿次数+1"
excluded = [
    (u"逛京东指数领京豆(0/1)", u"浏览5s得浏览票数+1", u"逛一逛"),
    (u"逛京东指数领京豆(0/1)", u"浏览5s得许愿机会+1", u"逛一逛"),
    (u"邀请好友助力(0/1)", u"助力成功得许愿次数+1", u"去助力"),
    (u"下单任意商品(0/1)", u"下单可得许愿次数+1", u"去下单"),
    (u"浏览会场(0/4)", GOOD, u"已完成"),
    (u"浏览会场(0/4)", GOOD, u"去领取"),
    (u"浏览会场(0/4)", GOOD, u"领取奖励"),
    (u"浏览会场(0/4)", GOOD, u"去逛逛"),
    (u"浏览会场(0/4)", GOOD, u"去看看"),
    (u"浏览会场(0/4)", u"浏览页面20秒", u"逛一逛"),
]
for i, (t, s, b) in enumerate(excluded):
    rows = parse_task_rows(synth(t, s, b))
    check("G%d 排除 %s / %s" % (i + 1, b, s), rows == [],
          "got %s" % [(r["btn"], r["secs"]) for r in rows])

check("G11 【逛一逛】+浏览Xs得许愿次数 可做",
      len(parse_task_rows(synth(u"逛会场(0/4)", GOOD, u"逛一逛"))) == 1)
check("G12 【去完成】+浏览Xs得许愿次数 可做",
      len(parse_task_rows(synth(u"浏览会场(0/4)", u"浏览25s得许愿次数+2",
                                u"去完成"))) == 1)
check("G13 大写 S / 中文秒 也可做",
      len(parse_task_rows(synth(u"任务(0/1)", u"浏览10秒得许愿次数",
                                u"逛一逛"))) == 1)
check("G14 无进度标题但左对齐可做",
      len(parse_task_rows(synth(u"逛家电家居领京豆", GOOD, u"逛一逛"))) == 1)
check("G15 标题不对齐也不带进度 -> 标题留空",
      parse_task_rows(synth(u"厨房卫浴补贴", GOOD, u"逛一逛",
                            title_x1=22))[0]["title"] == u"")
check("G16 背景页商品卡抢不走标题",
      parse_task_rows(synth(u"逛会场(0/4)", GOOD, u"逛一逛",
                            extra=[nd(u"樱花玫瑰沐浴露2瓶装", 22, 1180, 1061, 1240)]))[0]["title"]
      == u"逛会场(0/4)")
check("G17 退化 bounds 被忽略",
      parse_task_rows([nd(GOOD, 189, 1250, 100, 1200),
                       nd(u"逛一逛", 838, 1200, 1025, 1283)]) == [])
check("G18 按钮不贴右被忽略",
      parse_task_rows(synth(u"任务(0/1)", GOOD, u"逛一逛", btn_x1=300)) == [])
check("G19 副标题不在左列被忽略",
      parse_task_rows(synth(u"任务(0/1)", GOOD, u"逛一逛", sub_x1=750)) == [])
check("G20 可视区上界外（被弹窗裁掉的顶部行）被忽略",
      parse_task_rows(synth(u"任务(0/1)", GOOD, u"逛一逛", y=700)) == [])
check("G21 可视区下界外被忽略",
      parse_task_rows(synth(u"任务(0/1)", GOOD, u"逛一逛", y=2300)) == [])
check("G22 自定义 safe_bottom 生效",
      parse_task_rows(synth(u"任务(0/1)", GOOD, u"逛一逛"),
                      safe_bottom=1100) == [])
check("G23 自定义 btn_min_x 生效",
      parse_task_rows(synth(u"任务(0/1)", GOOD, u"逛一逛"),
                      btn_min_x=900) == [])
# 行距 225px，容差 90：不能串到隔壁行
two = (synth(u"任务A(0/3)", u"浏览10秒得许愿次数", u"逛一逛", y=1000)
       + synth(u"任务B(0/3)", u"浏览20秒得许愿次数", u"去完成", y=1225))
r2 = parse_task_rows(two)
check("G24 两行不串档", len(r2) == 2
      and [r["secs"] for r in r2] == [10, 20],
      "got %s" % [(r["title"], r["secs"]) for r in r2])
check("G25 自定义 row_tol 过小则配不上",
      parse_task_rows(synth(u"任务(0/1)", GOOD, u"逛一逛"), row_tol=5) == [])

# ================================================================ H
print("\n--- H. pick_target / panel_sig ---")
rows = parse_task_rows(PANEL)
check("H1 无黑名单挑第一行", pick_target(rows, set(), {})["key"] == rows[0]["key"])
check("H2 黑名单跳过", pick_target(rows, {rows[0]["key"]}, {})["key"]
      == rows[1]["key"])
check("H3 全拉黑返回 None",
      pick_target(rows, {r["key"] for r in rows}, {}) is None)
check("H4 单任务次数达上限跳过",
      pick_target(rows, set(), {rows[0]["key"]: MAX_PER_TASK})["key"]
      == rows[1]["key"])
check("H5 自定义上限生效",
      pick_target(rows[:1], set(), {rows[0]["key"]: 1}, max_per_task=1) is None)
check("H6 空 rows 返回 None", pick_target([], set(), {}) is None)
check("H7 panel_sig 稳定", panel_sig(PANEL) == panel_sig(PANEL))
check("H8 不同屏签名不同", panel_sig(PANEL) != panel_sig(S1))
check("H9 空节点签名为 None", panel_sig([]) is None)

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


def task_nodes(tasks):
    """按真机弹窗行结构造节点：标题/副标题 x1=189，按钮 x1=838。"""
    out = [
        nd(PANEL_MARK, 332, 613, 748, 671),
        nd(u"好礼许愿机", 387, 104, 693, 228, clickable=True),
        nd(u"今日任务", 187, 698, 415, 778),
        nd(u"中奖记录", 665, 698, 893, 778),
        nd(u"赚次数", 819, 1614, 1036, 1757, clickable=True),
        nd(u"商品卡文案 价格9.9元", 22, 1200, 1061, 1300),
    ]
    for i, t in enumerate(tasks):
        y = 860 + i * 225
        title = u"%s(%d/%d)" % (t["base"], t["cur"], t["mx"])
        out += [
            nd(title, 189, y - 16, 808, y + 45),
            nd(u"浏览%ds得许愿次数+1" % t["secs"], 189, y + 50, 770, y + 99),
            nd(t["btn"], 838, y, 1025, y + 83),
        ]
        t["pos"] = (931, y + 41)
    return out


class SimUI(object):
    """状态机替身：home -> newtab -> gift -> wish -> panel -> landing -> panel。"""
    W = 1080
    H = 2340

    def __init__(self, specs, refill=False, lost_on_back=False, stop=None):
        # specs: [(base_title, secs, btn, 需要做几次)]
        self.tasks = [{"base": b, "secs": s, "btn": btn, "cur": 0, "mx": mx,
                       "pos": None} for b, s, btn, mx in specs]
        self.refill = refill
        self.lost_on_back = lost_on_back
        self.stop = stop
        self.state = "home"
        self.pending = None
        self.taps = []
        self.swipes = []
        self.backs = 0
        self.sleeps = []
        self.invalidated = 0
        self.browses = 0
        self.earn_taps = 0
        self.claims = 0

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

    def adb_swipe(self, x1, y1, x2, y2, duration=300):
        self.swipes.append((x1, y1, x2, y2))

    def _finish_pending(self):
        t = self.pending
        self.pending = None
        if t is None:
            return
        self.browses += 1
        if t["cur"] + 1 >= t["mx"]:
            if t in self.tasks:
                self.tasks.remove(t)
            if self.refill:
                self.tasks.append({"base": t["base"], "secs": t["secs"],
                                   "btn": t["btn"], "cur": 0,
                                   "mx": t["mx"], "pos": t["pos"]})
        else:
            t["cur"] += 1

    def back(self, pause=2.0):
        self.backs += 1
        if self.state == "landing":
            self.state = "lost" if self.lost_on_back else "panel"
            self._finish_pending()
        elif self.state == "lost":
            self.state = "wish"
        elif self.state == "lost_deep":
            self.state = "home"
        elif self.state == "panel":
            self.state = "wish"
        elif self.state == "wish":
            self.state = "gift"
        elif self.state == "gift":
            self.state = "newtab"
        elif self.state == "newtab":
            self.state = "home"

    def adb_tap(self, pos, pause=1.5):
        p = (int(pos[0]), int(pos[1]))
        self.taps.append(p)
        if self.state == "home":
            if p == (637, 162):
                self.state = "newtab"
            return
        if self.state == "newtab":
            if p == (514, 436):
                self.state = "gift"
            return
        if self.state == "gift":
            if p == CHOU_POS:
                self.state = "wish"
            return
        if self.state in ("wish", "lost"):
            if p == EARN_POS:
                self.state = "panel"
                self.earn_taps += 1
            return
        if self.state == "panel":
            for t in self.tasks:
                if p == t["pos"]:
                    self.state = "landing"
                    self.pending = t
                    return

    def nodes(self):
        if self.state == "home":
            return [nd(u"首页", 100, 99, 200, 226),
                    nd(u"新品", 562, 99, 712, 226)]
        if self.state == "newtab":
            return [nd(u"新品", 562, 99, 712, 226),
                    nd(u"京东新品", 0, 530, 1080, 2340),
                    nd(u"送礼新品", 432, 446, 596, 504)]
        if self.state == "gift":
            return [nd(u"新品", 562, 99, 712, 226),
                    nd(u"品质好礼逛京东", 0, 530, 1080, 2340),
                    nd(u"送礼新品", 415, 458, 589, 510),
                    nd(u"image", 954, 706, 1034, 772,
                       clickable=True, cls="Image")]
        if self.state in ("wish", "lost"):
            return [nd(u"好礼许愿机", 0, 0, 1080, 2340),
                    nd(u"赚次数", 819, 1614, 1036, 1757, clickable=True)]
        if self.state == "landing":
            return [nd(u"商品详情", 100, 300, 900, 400),
                    nd(u"去逛逛", 907, 1867, 1042, 1936, clickable=True)]
        if self.state == "lost_deep":
            return [nd(u"未知页面", 100, 300, 900, 400)]
        return task_nodes(self.tasks)


def run_sim(sim, stop=None, max_tasks=None):
    """用替身跑完整 run()，不连设备。"""
    old_driver = MOD.driver
    old_jdui = MOD.JDUI
    old_max = MOD.MAX_TASKS
    import utils.driver as _drv
    old_get_driver = _drv.get_driver

    class FakeDriver(object):
        @staticmethod
        def get_driver():
            return None

    MOD.driver = FakeDriver()
    MOD.JDUI = lambda *a, **kw: sim
    _drv.get_driver = lambda: None
    if max_tasks is not None:
        MOD.MAX_TASKS = max_tasks
    log = Log()
    try:
        Task12Gift().run(log, stop or threading.Event())
    finally:
        MOD.driver = old_driver
        MOD.JDUI = old_jdui
        _drv.get_driver = old_get_driver
        MOD.MAX_TASKS = old_max
    return log


# ================================================================ I
print("\n--- I. 完整 run() 状态机 ---")
specs = [(u"逛逛好礼频道", 25, u"逛一逛", 1),
         (u"浏览精选会场", 5, u"去完成", 3),
         (u"逛京东服务抽888豆", 5, u"逛一逛", 2)]
sim = SimUI(specs)
log = run_sim(sim)
check("I1 run 正常结束（log.done 被调用）",
      any(lv == "DONE" for lv, _ in log.lines), log.text()[-400:])
check("I2 共做 6 次浏览（含进度任务重复做）", sim.browses == 6,
      "got %d" % sim.browses)
check("I3 每个任务 back 一次", sim.backs == 6, "got %d" % sim.backs)
check("I4 入口链路四个点都点过",
      all(p in sim.taps for p in ((637, 162), (514, 436),
                                  CHOU_POS, EARN_POS)),
      "got %s" % sim.taps[:8])
check("I5 【赚次数】点过", sim.earn_taps >= 1)
check("I6 25s 停 29s、5s 停 9s",
      sim.sleeps.count(29) == 1 and sim.sleeps.count(9) == 5,
      "got 29=%d 9=%d" % (sim.sleeps.count(29), sim.sleeps.count(9)))
check("I7 完成日志含次数且写明无需领取",
      any(u"完成 6 次浏览任务" in m and u"无需领取奖励" in m
          for lv, m in log.lines if lv == "DONE"),
      log.text()[-300:])
check("I8 结束时明确写了没有可做任务",
      any(u"没有可做任务" in m for _, m in log.lines))
check("I9 全程没有任何领取奖励动作",
      u"开心收下" not in log.text()
      and not any(u"领取奖励" in m for lv, m in log.lines if lv != "DONE")
      and sim.claims == 0,
      "got %s" % [m for lv, m in log.lines if u"领取" in m][:4])
check("I10 进度任务跨轮重复做没有死循环", sim.browses <= MAX_TASKS)
check("I11 滚动次数受控", len(sim.swipes) <= MAX_SCROLLS * MAX_CYCLES + 20,
      "got %d" % len(sim.swipes))
check("I12 落地页的【去逛逛】没有被当成任务按钮",
      all(p != (974, 1901) for p in sim.taps))

# ================================================================ J
print("\n--- J. 动态 X 单独验证 ---")
for x in (5, 10, 15, 20, 25, 30):
    s2 = SimUI([(u"任务", x, u"逛一逛", 1)])
    l2 = run_sim(s2)
    check("J X=%d -> 停留 %ds / back 1 次" % (x, x + 4),
          (x + 4) in s2.sleeps and s2.browses == 1 and s2.backs == 1
          and any(lv == "DONE" for lv, _ in l2.lines),
          "sleeps=%s browses=%d backs=%d" % (s2.sleeps[:8],
                                             s2.browses, s2.backs))

# ================================================================ K
print("\n--- K. 池子补位：上限保护 ---")
sim3 = SimUI([(u"逛会场", 5, u"逛一逛", 1)], refill=True)
log3 = run_sim(sim3, max_tasks=3)
check("K1 不死循环，按 MAX_TASKS 收尾", sim3.browses <= 3,
      "got %d" % sim3.browses)
check("K2 达到上限有 WARN", any(u"上限" in m for _, m in log3.lines))
check("K3 run 正常收尾", any(lv == "DONE" for lv, _ in log3.lines))
check("K4 没有领取动作", sim3.claims == 0)

# ================================================================ L
print("\n--- L. 恢复链路 ---")
sim4 = SimUI([(u"逛会场", 5, u"逛一逛", 1)], lost_on_back=True)
log4 = run_sim(sim4)
check("L1 back 丢弹窗后能就地重点【赚次数】恢复",
      sim4.browses >= 1 and sim4.earn_taps >= 2,
      "browses=%d earn_taps=%d" % (sim4.browses, sim4.earn_taps))
check("L2 恢复后 run 正常结束", any(lv == "DONE" for lv, _ in log4.lines))
check("L3 恢复日志可读", any(u"恢复" in m for _, m in log4.lines))

sim5 = SimUI([(u"逛会场", 5, u"逛一逛", 1)])
sim5.state = "panel"
check("L4 弹窗在场 _recover 直接返回 True",
      Task12Gift()._recover(sim5, Log()) is True and sim5.backs == 0)

sim6 = SimUI([(u"逛会场", 5, u"逛一逛", 1)])
sim6.state = "lost_deep"
ok6 = Task12Gift()._recover(sim6, Log())
check("L5 完全迷路时重走整条入口链路",
      ok6 is True and sim6.state == "panel" and sim6.earn_taps >= 1,
      "ok=%s state=%s earn=%d" % (ok6, sim6.state, sim6.earn_taps))
check("L6 恢复重进点过完整链路",
      all(p in sim6.taps for p in ((637, 162), (514, 436),
                                   CHOU_POS, EARN_POS)))

# ================================================================ M
print("\n--- M. stop_event ---")
ev = threading.Event()
ev.set()
sim7 = SimUI([(u"逛会场", 5, u"逛一逛", 1)])
log7 = run_sim(sim7, stop=ev)
check("M1 预先 stop 不会做任务", sim7.browses == 0,
      "got %d" % sim7.browses)
check("M2 预先 stop 不会调用 done",
      not any(lv == "DONE" for lv, _ in log7.lines))

# ================================================================ N
print("\n--- N. 真机滚动到底静止与进度补位 ---")
check("N1 到底连续 3 屏指纹一致", panel_sig(S4) == panel_sig(S6))
check("N2 到底后只剩 1 个可做任务",
      len(parse_task_rows(S4)) == 1 and len(parse_task_rows(S6)) == 1)
check("N3 到底那行是【来农场浇水免费领水果】",
      parse_task_rows(S4)[0]["key"] == u"来农场浇水免费领水果|5",
      "got %s" % parse_task_rows(S4)[0]["key"])
check("N4 回顶后指纹变化", panel_sig(S7) != panel_sig(S6))
check("N5 做满后【浏览精选会场】消失、补进新任务",
      u"浏览精选会场|5" in {r["key"] for r in r_panel}
      and u"浏览精选会场|5" not in {r["key"] for r in parse_task_rows(CYC1)}
      and u"逛京东特价抽888豆|5" in {r["key"] for r in parse_task_rows(CYC1)})
check("N6 补位后仍按 X+4（都是 5s/25s）",
      all(browse_seconds(r["secs"]) in (9, 29)
          for r in parse_task_rows(CYC1)))

# ================================================================ 汇总
print("\n================ 汇总 ================")
print("PASS %d, FAIL %d" % (len(PASSED), len(FAILED)))
if FAILED:
    for f in FAILED:
        print("  FAILED: %s" % f)
    sys.exit(1)
print("ALL PASS")
