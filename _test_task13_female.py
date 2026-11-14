# -*- coding: utf-8 -*-
"""任务13【女性专区】离线回归（不连手机、不连 Appium）。

覆盖：
  A. 模块元信息 / 需求常量 / 确认没有放大镜与中文输入逻辑
  B. dwell_seconds 随机 15~18
  C. classify 真机夹具页面判定（含 18 节点骨架、混叠、风控页）
  D. in_list / is_task_button / is_claim_button 严格过滤
  E. row_title 左对齐判据（排除背景页商品价格抢标题）
  F. parse_rows 真机夹具逐屏任务 / 领奖行精确断言
  G. panel_sig 到底判界
  H. task_key 去进度 / pick_target 台账
  I. _find_icon 稳定性与 _clickable_container
  J. SimUI 跑完整 run()：三条入口、做任务、领奖、恢复、上限、stop_event
  K. 需求合规：只做白名单按钮、15~18s、back 一次、逐个领取、无搜索输入

夹具（真机 1080x2340，2026-11-13 抓的，由 _probe_female_*.xml 整理）：
  _fixture_female_home.xml          首页金刚区第一屏
  _fixture_female_home2.xml         首页另一帧
  _fixture_female_kk2.xml           金刚区第二屏
  _fixture_female_channels.xml      全部频道页首帧（18 节点骨架）
  _fixture_female_channels2.xml     全部频道页完整帧
  _fixture_female_quanyi.xml        优惠权益 tab（粉色女性专区图标）
  _fixture_female_female.xml        女性专区活动页
  _fixture_female_female_fallback.xml 兜底路径进入的活动页
  _fixture_female_panel*.xml        任务弹窗 / 滚动帧 / 做完一行的帧
  _fixture_female_reward.xml        领奖后的奖励弹窗
  _fixture_female_closed.xml        奖励弹窗关闭后回活动主页
  _fixture_female_scroll0..4.xml    列表滚动各屏（到底静止）
  _fixture_female_countdown*.xml    落地页倒计时（继续浏览10秒 / 3秒）
  _fixture_female_panel_price_trap.xml 商品价格文案混进任务列表的帧
"""
import io
import re
import sys
import threading
import xml.etree.ElementTree as ET

sys.path.insert(0, ".")

import modules.task13_female as MOD
from modules.task13_female import (
    Task13Female, classify, row_title, parse_rows, panel_sig,
    task_key, pick_target, dwell_seconds, in_list, valid, center, norm,
    is_task_button, is_claim_button,
    FEMALE_ICON, ALL_CHANNELS, QUANYI_TAB, TASK_ENTRY, PANEL_MARK,
    BTN_TEXTS, CLAIM_TEXT, HAPPY_TEXT, REWARD_CLOSE, REWARD_MARK,
    SAFE_TOP, SAFE_BOTTOM, BTN_MIN_X, BTN_MAX_X,
    TITLE_ANCHOR_X, TITLE_X_TOL, TITLE_MIN_X, TITLE_MAX_X, TITLE_MAX_DY,
    DWELL_MIN, DWELL_MAX, PROGRESS_RE, PRICE_RE, NOISE_TEXTS,
    SWIPE_UP, SWIPE_DOWN, MAX_TASKS, MAX_CYCLES, MAX_STEPS,
    MAX_SCROLLS, MAX_PER_TASK, MAX_RETRY, MAX_CLAIMS, MAX_READ_FAILS,
    MAX_TO_TOP,
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


HOME = load("_fixture_female_home.xml")
HOME2 = load("_fixture_female_home2.xml")
KK2 = load("_fixture_female_kk2.xml")
KK2C = load("_fixture_female_kk2c.xml")
CHAN_SKEL = load("_fixture_female_chan_skeleton.xml")
CHANNELS = load("_fixture_female_channels2.xml")
QUANYI = load("_fixture_female_quanyi.xml")
FEMALE = load("_fixture_female_female.xml")
FEMALE_FB = load("_fixture_female_female_fallback.xml")
FEMALE_PAGE2 = load("_fixture_female_female_page2.xml")
PANEL = load("_fixture_female_panel.xml")
PANEL_TOP = load("_fixture_female_panel_top.xml")
PANEL_SCROLLED = load("_fixture_female_panel_scrolled.xml")
PANEL_AFTER_BACK = load("_fixture_female_panel_after_back.xml")
REWARD = load("_fixture_female_reward.xml")
CLOSED = load("_fixture_female_closed.xml")
SCROLL0 = load("_fixture_female_scroll0.xml")
SCROLL1 = load("_fixture_female_scroll1.xml")
SCROLL2 = load("_fixture_female_scroll2.xml")
SCROLL3 = load("_fixture_female_scroll3.xml")
SCROLL4 = load("_fixture_female_scroll4.xml")
LANDING_FRAME = load("_fixture_female_landing_frame.xml")
COUNTDOWN10 = load("_fixture_female_countdown10.xml")
COUNTDOWN3 = load("_fixture_female_countdown3.xml")
PRICE_TRAP = load("_fixture_female_panel_price_trap.xml")
SEARCHPAGE = load("_fixture_female_searchpage.xml")

SRC = io.open("modules/task13_female.py", encoding="utf-8").read()


# ================================================================ A
print("\n--- A. 元信息、常量、确认没有放大镜/中文输入 ---")
check("A1 模块名", Task13Female.name == u"女性专区")
check("A2 图标是【连衣裙】emoji", Task13Female.icon == u"👗")
import modules as _mods
_ICON_BY_NAME = dict((m.name, m.icon) for m in _mods.get_modules())
check("A2b 4 个汉字图标已全部换成 emoji",
      _ICON_BY_NAME.get(u"国家补贴×超级补贴") == u"💰" and
      _ICON_BY_NAME.get(u"京东好礼") == u"🧧" and
      _ICON_BY_NAME.get(u"女性专区") == u"👗" and
      _ICON_BY_NAME.get(u"东东农场-领水滴") == u"💧",
      "%s" % (_ICON_BY_NAME,))
check("A2c 平台不再有汉字卡片图标",
      not any(m.icon in (u"补", u"礼", u"女", u"水滴")
              for m in _mods.get_modules()))
check("A3 描述含金刚区入口", u"金刚区" in Task13Female.description)
check("A4 描述含全部频道兜底", u"全部频道" in Task13Female.description)
check("A5 描述含优惠权益", u"优惠权益" in Task13Female.description)
check("A6 描述含 15~18 秒", u"15~18" in Task13Female.description)
check("A7 描述含领取奖励", u"领取奖励" in Task13Female.description)
check("A8 弹窗独有标题", PANEL_MARK == u"做任务赚惊喜值")
check("A9 按钮白名单", BTN_TEXTS == (u"去浏览", u"逛一逛", u"去完成"))
check("A10 领奖/收下/关闭常量",
      (CLAIM_TEXT, HAPPY_TEXT, REWARD_CLOSE, REWARD_MARK) ==
      (u"领取奖励", u"开心收下", u"关闭", u"恭喜获得奖励"))
check("A11 活动页入口按钮", TASK_ENTRY == u"做任务 赚更多惊喜值")
check("A12 页面关键字",
      (FEMALE_ICON, ALL_CHANNELS, QUANYI_TAB) ==
      (u"女性专区", u"全部频道", u"优惠权益"))
check("A13 任务列表安全区", (SAFE_TOP, SAFE_BOTTOM) == (1150, 2340))
check("A14 按钮贴右区间", (BTN_MIN_X, BTN_MAX_X) == (800, 1060))
check("A15 标题左对齐判据", (TITLE_ANCHOR_X, TITLE_X_TOL) == (217, 70))
check("A16 标题搜索范围",
      (TITLE_MIN_X, TITLE_MAX_X, TITLE_MAX_DY) == (100, 700, 220))
check("A17 停留 15~18s 随机", (DWELL_MIN, DWELL_MAX) == (15, 18))
check("A18 上限保护齐全",
      (MAX_TASKS, MAX_CYCLES, MAX_STEPS, MAX_SCROLLS, MAX_PER_TASK,
       MAX_RETRY, MAX_CLAIMS, MAX_READ_FAILS, MAX_TO_TOP) ==
      (40, 8, 180, 12, 3, 2, 20, 4, 8))
check("A19 列表滑动方向",
      SWIPE_UP == (540, 2100, 540, 1250) and
      SWIPE_DOWN == (540, 1250, 540, 2100))
check("A20 排除表含完成态", u"已领取" in NOISE_TEXTS and u"惊喜值" in NOISE_TEXTS)
check("A21 有价格文案排除正则", bool(PRICE_RE.search(u"¥269.00")) and
      bool(PRICE_RE.search(u"到手价")) and not PRICE_RE.search(u"逛京东服务10s(0/1)"))

_FORBIDDEN = ("send_keys", "mobile: type", "unicodeKeyboard", "By.ID",
              "By.CLASS_NAME", "find_element", "channel-search-content",
              "switch_to", "-android uiautomator", "adb shell input text",
              "set_clipboard", "SEARCH_ICON")
for i, tok in enumerate(_FORBIDDEN, 1):
    check("A22.%d 源码无 %s" % (i, tok), tok not in SRC)
check("A23 源码无搜索框调用", u"搜索频道" not in SRC)
check("A24 源码复用公共金刚区方法", "kingkong_icons" in SRC and
      "swipe_kingkong" in SRC and "kingkong_row" in SRC)
check("A25 源码有领奖方法", "_claim_all" in SRC and "_clear_reward" in SRC)
check("A26 源码有随机停留", "randint" in SRC)


# ================================================================ B
print("\n--- B. dwell_seconds 随机 15~18 ---")
class FixedRnd(object):
    def __init__(self, v):
        self.v = v

    def randint(self, a, b):
        self.args = (a, b)
        return self.v


for v in (15, 16, 17, 18):
    r = FixedRnd(v)
    check("B%d 固定 %d 返回 %d" % (v - 14, v, v),
          dwell_seconds(r) == v and r.args == (15, 18))
samples = [dwell_seconds() for _ in range(300)]
check("B5 全部落在 15~18", all(15 <= x <= 18 for x in samples))
check("B6 覆盖多个取值（不是常量）", len(set(samples)) >= 3,
      "got %s" % (sorted(set(samples)),))
check("B7 norm 压空白", norm(u"做任务 赚更多\n惊喜值") == u"做任务赚更多惊喜值")
check("B8 valid 正确", valid((1, 2, 3, 4)) and not valid((1, 2, 3, 2))
      and not valid(None) and not valid((1, 2, 3)))
check("B9 center 取整", center((871, 1222, 1025, 1308)) == (948, 1265))


# ================================================================ C
print("\n--- C. classify 真机页面判定 ---")
check("C1 首页不是任何任务页", classify(HOME) == "other")
check("C2 首页另一帧不是任务页", classify(HOME2) == "other")
check("C3 金刚区第二屏不是任务页",
      classify(KK2) == "other" and classify(KK2C) == "other")
check("C4 全部频道首帧骨架判 other", classify(CHAN_SKEL) == "other",
      "got %s" % classify(CHAN_SKEL))
check("C5 全部频道完整帧判 channels", classify(CHANNELS) == "channels",
      "got %s" % classify(CHANNELS))
check("C6 优惠权益页判 quanyi", classify(QUANYI) == "quanyi",
      "got %s" % classify(QUANYI))
check("C7 活动页判 female", classify(FEMALE) == "female",
      "got %s" % classify(FEMALE))
check("C8 兜底路径活动页也判 female", classify(FEMALE_FB) == "female",
      "got %s" % classify(FEMALE_FB))
check("C9 活动页滚下去后仍不误判", classify(FEMALE_PAGE2) == "other",
      "got %s" % classify(FEMALE_PAGE2))
check("C10 弹窗判 panel", classify(PANEL) == "panel")
check("C11 弹窗顶部帧判 panel", classify(PANEL_TOP) == "panel")
check("C12 弹窗滚动帧判 panel", classify(PANEL_SCROLLED) == "panel")
check("C13 做完任务回弹窗判 panel", classify(PANEL_AFTER_BACK) == "panel")
check("C14 奖励弹窗判 reward", classify(REWARD) == "reward")
check("C15 奖励关闭后回活动主页", classify(CLOSED) == "female",
      "got %s" % classify(CLOSED))
for i, ns in enumerate((SCROLL0, SCROLL1, SCROLL2, SCROLL3, SCROLL4)):
    check("C16.%d 滚动屏 %d 仍是 panel" % (i + 1, i), classify(ns) == "panel",
          "got %s" % classify(ns))
check("C17 点击被吞那一帧仍是 panel（需重试）",
      classify(LANDING_FRAME) == "panel")
check("C18 落地页倒计时 10s 非弹窗", classify(COUNTDOWN10) == "other",
      "got %s" % classify(COUNTDOWN10))
check("C19 落地页倒计时 3s 非弹窗", classify(COUNTDOWN3) == "other",
      "got %s" % classify(COUNTDOWN3))
check("C20 商品价格陷阱帧仍是 panel", classify(PRICE_TRAP) == "panel")
check("C21 旧搜索页不会误判成弹窗", classify(SEARCHPAGE) != "panel")
check("C22 空节点", classify([]) == "other")
check("C23 京东验证风控页", classify([nd(u"验证一下，购物无忧", 10, 10, 500, 100),
                                   nd(u"京东验证", 10, 120, 500, 200)]) == "verify")
check("C24 弹窗标志优先于活动页按钮",
      classify([nd(PANEL_MARK, 376, 771, 704, 829),
                nd(TASK_ENTRY, 55, 931, 671, 1038, clickable=True)]) == "panel")
check("C25 reward 优先于 panel 标志",
      classify([nd(PANEL_MARK, 376, 771, 704, 829),
                nd(HAPPY_TEXT, 159, 1574, 921, 1704, clickable=True)]) == "reward")


# ================================================================ D
print("\n--- D. in_list / 按钮谓词严格过滤 ---")
def btn_node(text, x1=871, y1=1222, x2=1025, y2=1308,
             clickable=True, cls="Button"):
    return nd(text, x1, y1, x2, y2, clickable=clickable, cls=cls)


check("D1 标准任务按钮", in_list((871, 1222, 1025, 1308)))
check("D2 y1 差 1 被裁", not in_list((871, 1149, 1025, 1308)))
check("D3 下界外被裁", not in_list((871, 2200, 1025, 2341)))
check("D4 x1 太靠左被裁", not in_list((799, 1222, 1025, 1308)))
check("D5 x2 太靠右被裁", not in_list((871, 1222, 1061, 1308)))
check("D6 退化 bounds 被裁", not in_list((871, 2380, 1025, 2342)))
check("D7 空 bounds 安全", not in_list(None) and not in_list(()))
for i, t in enumerate(BTN_TEXTS, 1):
    check("D8.%d 【%s】可做" % (i, t), is_task_button(btn_node(t)))
check("D9 非白名单按钮不可做",
      not is_task_button(btn_node(u"已完成")) and
      not is_task_button(btn_node(u"去看看")))
check("D10 落地页【去完成】TextView 不可点不算任务",
      not is_task_button(btn_node(u"去完成", clickable=False, cls="TextView")))
check("D11 不可点 Button 不算任务",
      not is_task_button(btn_node(u"去浏览", clickable=False)))
check("D12 屏幕外【去浏览】不算任务",
      not is_task_button(btn_node(u"去浏览", y1=329, y2=406)))
check("D13 【领取奖励】是领奖按钮",
      is_claim_button(btn_node(CLAIM_TEXT)))
check("D14 【领取奖励】不是可做任务",
      not is_task_button(btn_node(CLAIM_TEXT)))
check("D15 屏幕外【领取奖励】不算",
      not is_claim_button(btn_node(CLAIM_TEXT, y1=2380, y2=2342)))
check("D16 已完成不是领奖按钮",
      not is_claim_button(btn_node(u"已完成")))
check("D17 开心收下不是任务按钮",
      not is_task_button(btn_node(HAPPY_TEXT, 159, 1574, 921, 1704)))


# ================================================================ E
print("\n--- E. row_title 左对齐 / 排除商品价格 ---")
PANEL_TITLES = (u"逛500补贴金会场(0/1)", u"逛包邮会场10s(0/1)",
                u"逛京东服务10s(0/1)", u"0.01元抢三重好礼(0/1)",
                u"逛超级补贴10s(0/1)", u"逛省钱频道领京豆(0/1)")
for i, r in enumerate(parse_rows(PANEL, "task"), 1):
    check("E1.%d 第 %d 行标题" % (i, i), r["title"] == PANEL_TITLES[i - 1],
          "got %r" % r["title"])
check("E2 scroll0 末行标题不会被 ¥269.00 抢走",
      parse_rows(SCROLL0, "task")[-1]["title"] == u"最高抢20元金券",
      "got %r" % parse_rows(SCROLL0, "task")[-1]["title"])
check("E3 价格陷阱帧末行标题不会被【到手价】抢走",
      parse_rows(PRICE_TRAP, "task")[-1]["title"] == u"最高抢20元金券",
      "got %r" % parse_rows(PRICE_TRAP, "task")[-1]["title"])
check("E4 合成：价格节点更近也抢不走标题",
      row_title([nd(u"逛会场领京豆(0/1)", 217, 1138, 640, 1193),
                 nd(u"¥269.00", 574, 1185, 745, 1254),
                 nd(u"到手价", 687, 1188, 794, 1254)],
                (871, 1222, 1025, 1308)) == u"逛会场领京豆(0/1)")
check("E5 合成：无进度但左对齐优先于右侧文案",
      row_title([nd(u"最高抢20元金券", 217, 1138, 511, 1193),
                 nd(u"官方直降15%", 574, 1182, 847, 1229)],
                (871, 1222, 1025, 1308)) == u"最高抢20元金券")
check("E6 无候选返回空串", row_title([], (871, 1222, 1025, 1308)) == u"")
check("E7 日期/噪声不作标题",
      row_title([nd(u"2026.10.14 00:00-2026.12.31 23:59", 217, 1100, 720, 1142),
                 nd(u"惊喜值", 217, 1207, 324, 1251)],
                (871, 1222, 1025, 1308)) == u"")
check("E8 上一行标题不串到本行",
      row_title([nd(u"上一行任务(0/1)", 217, 929, 640, 984)],
                (871, 1222, 1025, 1308)) == u"")


# ================================================================ F
print("\n--- F. parse_rows 真机夹具逐屏 ---")
r_panel = parse_rows(PANEL, "task")
r_top = parse_rows(PANEL_TOP, "task")
r_scroll = parse_rows(PANEL_SCROLLED, "task")
r_back = parse_rows(PANEL_AFTER_BACK, "task")
c_back = parse_rows(PANEL_AFTER_BACK, "claim")
check("F1 初始弹窗 6 个可做任务", len(r_panel) == 6, "got %d" % len(r_panel))
check("F2 顶部帧也是 6 个", len(r_top) == 6)
check("F3 滚动过的弹窗 3 个可做任务", len(r_scroll) == 3,
      "got %d" % len(r_scroll))
check("F4 做完一行后剩 5 个可做", len(r_back) == 5, "got %d" % len(r_back))
check("F5 做完一行后有 1 个待领奖励", len(c_back) == 1, "got %d" % len(c_back))
check("F6 待领奖励标题带完成进度",
      c_back and c_back[0]["title"] == u"逛省钱频道领京豆(1/1)",
      "got %r" % (c_back[0]["title"] if c_back else None))
check("F7 所有任务按钮贴右",
      all(r["bounds"][0] >= BTN_MIN_X and r["bounds"][2] <= BTN_MAX_X
          for r in r_panel))
check("F8 所有任务都在可视区内",
      all(in_list(r["bounds"]) for r in r_panel))
check("F9 行按 y 升序", [r["bounds"][1] for r in r_panel] ==
      sorted(r["bounds"][1] for r in r_panel))
check("F10 按钮文案全是白名单",
      all(r["text"] in BTN_TEXTS for r in r_panel))
check("F11 每行 key 唯一", len(set(r["key"] for r in r_panel)) == 6)
check("F12 key 去掉 (N/M) 进度",
      all(not PROGRESS_RE.search(r["key"]) for r in r_panel))
check("F13 滚动 1 屏没有可做任务（屏幕外行被过滤）",
      len(parse_rows(SCROLL1, "task")) == 0)
check("F14 滚动 2 屏没有可做任务", len(parse_rows(SCROLL2, "task")) == 0)
check("F15 到底两屏都没有可做任务",
      len(parse_rows(SCROLL3, "task")) == 0 and
      len(parse_rows(SCROLL4, "task")) == 0)
check("F16 奖励弹窗不解析任务/领奖",
      parse_rows(REWARD, "task") == [] and parse_rows(REWARD, "claim") == [])
check("F17 活动主页不解析任务",
      parse_rows(FEMALE, "task") == [] and parse_rows(CLOSED, "task") == [])
check("F18 首页/金刚区/频道页不解析任务",
      all(parse_rows(ns, "task") == []
          for ns in (HOME, HOME2, KK2, CHANNELS, QUANYI)))
check("F19 落地页倒计时不解析任务",
      parse_rows(COUNTDOWN10, "task") == [] and
      parse_rows(COUNTDOWN3, "task") == [])
check("F20 空节点安全", parse_rows([], "task") == [])
check("F21 商品价格陷阱帧仍有 6 个可做任务",
      len(parse_rows(PRICE_TRAP, "task")) == 6)


# ================================================================ G
print("\n--- G. panel_sig 到底判界 ---")
check("G1 同屏签名稳定", panel_sig(PANEL) == panel_sig(PANEL_TOP))
check("G2 r3 == r4（已到底）", panel_sig(SCROLL3) == panel_sig(SCROLL4))
check("G3 r0 != r1（滑动有效）", panel_sig(SCROLL0) != panel_sig(SCROLL1))
check("G4 不同弹窗帧签名不同", panel_sig(PANEL) != panel_sig(PANEL_AFTER_BACK))
check("G5 空节点签名为空", panel_sig([]) == ())
check("G6 签名只数可视区按钮", len(panel_sig(SCROLL0)) == 6)


# ================================================================ H
print("\n--- H. task_key / pick_target ---")
k1 = task_key(u"逛500补贴金会场(0/1)", u"去浏览")
k2 = task_key(u"逛500补贴金会场(1/1)", u"去浏览")
k3 = task_key(u"逛500补贴金会场(2/4)", u"去浏览")
check("H1 进度变化 key 不变", k1 == k2 == k3, "got %r %r %r" % (k1, k2, k3))
check("H2 不同标题 key 不同", k1 != task_key(u"逛包邮会场10s(0/1)", u"去浏览"))
check("H3 不同按钮 key 不同", k1 != task_key(u"逛500补贴金会场(0/1)", u"逛一逛"))
check("H4 空标题也能成 key", bool(task_key(u"", u"去浏览")))
check("H5 PROGRESS_RE 命中中文括号",
      bool(PROGRESS_RE.search(u"逛会场（1/4）")))
check("H6 PROGRESS_RE 不误伤价格", not PROGRESS_RE.search(u"¥269.00"))
_rows = [{"key": x} for x in ("a", "b", "c")]
check("H7 无黑名单挑第一行", pick_target(_rows, set(), {})["key"] == "a")
check("H8 黑名单跳过", pick_target(_rows, {"a"}, {})["key"] == "b")
check("H9 全拉黑返回 None",
      pick_target(_rows, {"a", "b", "c"}, {}) is None)
check("H10 单任务次数达上限跳过",
      pick_target(_rows, set(), {"a": MAX_PER_TASK})["key"] == "b")
check("H11 自定义上限生效",
      pick_target(_rows, set(), {"a": 1}, max_per_task=1)["key"] == "b")
check("H12 空 rows 返回 None", pick_target([], set(), {}) is None)


# ================================================================ I / J 的替身
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


# 真机标定坐标
F_ICON1 = (651, 440, 867, 601)       # 金刚区第一/第二屏【女性专区】
F_ICON2 = (867, 601, 1080, 762)
ALL_ICON = (867, 924, 1080, 1085)    # 第二屏【全部频道】
QY_TAB_CHANNELS = (321, 690, 495, 830)  # 全部频道页【优惠权益】tab
QY_TAB = (321, 231, 495, 371)            # 优惠权益页顶部的【优惠权益】
F_ENT_TEXT = (269, 585, 423, 629)    # 优惠权益页【女性专区】文字
F_ENT_BOX = (247, 484, 445, 629)     # 包住文字的最小可点父容器
ENTRY_BTN = (55, 931, 671, 1038)     # 【做任务 赚更多惊喜值】
HAPPY_BTN = (159, 1574, 921, 1704)   # 【开心收下】
CLOSE_BTN = (503, 1841, 577, 1913)   # 奖励弹窗 X


def ctr(b):
    return ((b[0] + b[2]) // 2, (b[1] + b[3]) // 2)


def panel_nodes(tasks, claims, price_trap=False, mark=True):
    """按真机弹窗行结构造节点：标题 x1=217，按钮 x1=871。"""
    out = []
    if mark:
        out.append(nd(PANEL_MARK, 376, 771, 704, 829))
    out += [nd(u"全部", 44, 1013, 376, 1121),
            nd(u"惊喜任务", 374, 1013, 706, 1121),
            nd(u"下单任务", 704, 1013, 1036, 1121)]
    rows = [(t, u"去浏览") for t in tasks] + [(t, CLAIM_TEXT) for t in claims]
    for i, (title, btn) in enumerate(rows):
        y = 1222 + i * 193
        out += [
            nd(title, 217, y - 84, 640, y - 29),
            nd(u"惊喜值", 217, y + 7, 324, y + 51),
            nd(btn, 871, y, 1025, y + 86, clickable=True, cls="Button"),
        ]
        if price_trap and i == len(rows) - 1:
            out.append(nd(u"¥269.00", 574, y - 3, 745, y + 66))
            out.append(nd(u"到手价", 687, y + 6, 794, y + 66))
    return out


class SimUI(object):
    """状态机替身：home -> (home2) -> channels/quanyi/female -> panel -> landing -> panel。"""
    W = 1080
    H = 2340

    def __init__(self, mode="first", bases=None, lost_on_back=False,
                 verify_on_tap=False, refill=False, unstable_icon=False,
                 stop=None, stop_after=0):
        self.mode = mode
        self.bases = (list(bases) if bases is not None else
                      [u"逛500补贴金会场", u"逛包邮会场10s", u"逛京东服务10s"])
        self.tasks = list(self.bases)
        self.claims = []
        self.lost_on_back = lost_on_back
        self.verify_on_tap = verify_on_tap
        self.refill = refill
        self.unstable_icon = unstable_icon
        self.stop = stop
        self.stop_after = stop_after
        self.state = "home"
        self.pending = None
        self.taps = []
        self.events = []
        self.swipes = []
        self.sleeps = []
        self.backs = 0
        self.kk_left = 0
        self.icon_reads = 0
        self.browses = 0
        self.claimed = 0
        self.happy_taps = 0
        self.panel_opens = 0
        self.all_taps = 0
        self.qy_taps = 0
        self.ent_taps = 0
        self.female_taps = 0
        self.invalidated = 0

    # -- 基础
    def sx(self, x):
        return x

    def sy(self, y):
        return y

    def invalidate(self):
        self.invalidated += 1

    def source(self, fresh=False):
        return u"<dummy/>"

    def sleep(self, s):
        self.sleeps.append(s)
        return True

    def restart_to_home(self, wait=6):
        self.state = "home"
        return True

    def goto_home(self, max_back=10):
        self.state = "home"
        return True

    def ensure_kingkong_visible(self, max_swipes=3):
        return True

    def kingkong_row(self, xml=None):
        if self.state in ("home", "home2"):
            return (440, 601, [])
        return None

    def kingkong_icons(self, xml=None):
        self.icon_reads += 1
        out = []
        if self.state == "home":
            out.append({"desc": u"秒杀", "bounds": (0, 440, 194, 601),
                        "y1": 440, "y2": 601, "cy": 520})
            if self.mode == "first":
                b = F_ICON1
                if self.unstable_icon and self.icon_reads % 2 == 1:
                    b = (651, 500, 867, 661)
                out.append({"desc": FEMALE_ICON, "bounds": b,
                            "y1": b[1], "y2": b[3], "cy": (b[1] + b[3]) // 2})
        elif self.state == "home2":
            if self.mode == "second":
                out.append({"desc": FEMALE_ICON, "bounds": F_ICON2,
                            "y1": F_ICON2[1], "y2": F_ICON2[3],
                            "cy": (F_ICON2[1] + F_ICON2[3]) // 2})
            out.append({"desc": ALL_CHANNELS, "bounds": ALL_ICON,
                        "y1": ALL_ICON[1], "y2": ALL_ICON[3],
                        "cy": (ALL_ICON[1] + ALL_ICON[3]) // 2})
        return out

    def swipe_kingkong(self, direction="left", pause=1.5):
        if direction == "left":
            self.kk_left += 1
            if self.state == "home":
                self.state = "home2"
        else:
            if self.state == "home2":
                self.state = "home"

    def adb_swipe(self, x1, y1, x2, y2, duration=300):
        self.swipes.append((x1, y1, x2, y2))

    def back(self, pause=2.0):
        self.backs += 1
        if self.state == "landing":
            self.state = "verify" if self.verify_on_tap else (
                "lost" if self.lost_on_back else "panel")
            self._finish_pending()
        elif self.state == "lost":
            self.state = "female"
        elif self.state in ("panel", "verify"):
            self.state = "female"
        elif self.state == "reward":
            self.state = "female"
        elif self.state == "female":
            self.state = "home"

    def _finish_pending(self):
        t = self.pending
        self.pending = None
        if t is None:
            return
        self.browses += 1
        self.events.append("browse")
        if t in self.tasks:
            self.tasks.remove(t)
        if not self.verify_on_tap:
            self.claims.append(t)
        if self.refill:
            self.tasks.append(t)
        if self.stop_after and self.browses >= self.stop_after and self.stop:
            self.stop.set()

    def adb_tap(self, pos, pause=1.5):
        p = (int(pos[0]), int(pos[1]))
        self.taps.append(p)
        if self.state == "home":
            if self.mode == "first" and p == ctr(F_ICON1):
                self.state = "female"
                self.female_taps += 1
                self.events.append("entry")
            return
        if self.state == "home2":
            if self.mode == "second" and p == ctr(F_ICON2):
                self.state = "female"
                self.female_taps += 1
                self.events.append("entry")
            elif p == ctr(ALL_ICON):
                self.state = "channels"
                self.all_taps += 1
                self.events.append("channels")
            return
        if self.state == "channels":
            if p == ctr(QY_TAB_CHANNELS):
                self.state = "quanyi"
                self.qy_taps += 1
                self.events.append("quanyi")
            return
        if self.state == "quanyi":
            if p == ctr(F_ENT_BOX) or p == ctr(F_ENT_TEXT):
                self.state = "female"
                self.ent_taps += 1
                self.female_taps += 1
                self.events.append("entry")
            return
        if self.state in ("female", "lost"):
            if p == ctr(ENTRY_BTN):
                self.state = "panel"
                self.panel_opens += 1
                self.events.append("open_panel")
            return
        if self.state == "reward":
            if p == ctr(HAPPY_BTN) or p == ctr(CLOSE_BTN):
                self.state = "female"      # 真机：奖励弹窗关闭后任务弹窗消失
                self.happy_taps += 1
                self.events.append("clear_reward")
            return
        if self.state == "panel":
            for i, t in enumerate(self.tasks):
                if p == (948, 1222 + i * 193 + 43):
                    self.state = "landing"
                    self.pending = t
                    self.events.append("tap_task")
                    return
            for i, t in enumerate(self.claims):
                y = 1222 + (len(self.tasks) + i) * 193
                if p == (948, y + 43):
                    self.state = "reward"
                    self.claims.pop(i)      # 领完就不该再出现
                    self.claimed += 1
                    self.events.append("claim")
                    return

    def nodes(self, xml=None):
        if self.state in ("home", "home2"):
            return [nd(u"首页", 100, 99, 200, 226), nd(u"秒杀", 0, 440, 194, 601,
                                                     clickable=True, desc=u"秒杀")]
        if self.state == "channels":
            return [nd(ALL_CHANNELS, 434, 126, 646, 206),
                    nd(QUANYI_TAB, 321, 690, 495, 830, clickable=True),
                    nd(u"image", 858, 134, 918, 195, clickable=True, cls="Image")]
        if self.state == "quanyi":
            return [nd(QUANYI_TAB, 321, 231, 495, 371, clickable=True),
                    nd(FEMALE_ICON, 269, 585, 423, 629),
                    nd(u"", 247, 484, 445, 629, clickable=True, cls="View")]
        if self.state in ("female", "lost"):
            return [nd(FEMALE_ICON, 0, 329, 1080, 2340, cls="WebView"),
                    nd(TASK_ENTRY, 55, 931, 671, 1038,
                       clickable=True, cls="Button")]
        if self.state == "reward":
            return [nd(REWARD_MARK, 300, 900, 780, 980),
                    nd(HAPPY_TEXT, 159, 1574, 921, 1704,
                       clickable=True, cls="Button"),
                    nd(REWARD_CLOSE, 503, 1841, 577, 1913,
                       clickable=True, cls="Image")]
        if self.state == "landing":
            return [nd(u"商品详情", 100, 300, 900, 400),
                    nd(u"继续浏览10秒", 400, 1800, 700, 1860),
                    nd(u"去完成", 907, 1867, 1042, 1936, cls="TextView")]
        if self.state == "verify":
            return [nd(u"京东验证", 100, 300, 900, 400),
                    nd(u"快速验证", 100, 500, 900, 600)]
        if self.state == "panel":
            return panel_nodes(self.tasks, self.claims, price_trap=True)
        return [nd(u"未知页面", 100, 300, 900, 400)]


def run_sim(sim, stop=None, max_tasks=None):
    """用替身跑完整 run()，不连设备（同时 mock JDUI 与 utils.driver）。"""
    old_driver = MOD.driver
    old_jdui = MOD.JDUI
    old_max = MOD.MAX_TASKS
    import utils.driver as _drv
    old_get_driver = _drv.get_driver
    guard = {"calls": 0}

    def _guard_get_driver():
        guard["calls"] += 1
        raise AssertionError("回归里不该真建 Appium session")

    class FakeDriver(object):
        @staticmethod
        def get_driver():
            return None

    MOD.driver = FakeDriver()
    MOD.JDUI = lambda *a, **kw: sim
    _drv.get_driver = _guard_get_driver
    if max_tasks is not None:
        MOD.MAX_TASKS = max_tasks
    log = Log()
    try:
        Task13Female().run(log, stop or threading.Event())
    finally:
        MOD.driver = old_driver
        MOD.JDUI = old_jdui
        _drv.get_driver = old_get_driver
        MOD.MAX_TASKS = old_max
    return log, guard


# ================================================================ I
print("\n--- I. _find_icon 稳定性 / _clickable_container ---")
m = Task13Female()
m.ui = SimUI(mode="first")
m.log = Log()
m.stop = threading.Event()
check("I1 第一屏动态找到【女性专区】", m._find_icon(FEMALE_ICON) == F_ICON1,
      "got %s" % (m._find_icon(FEMALE_ICON),))
check("I2 连续两次 dump 稳定才返回", m.ui.icon_reads >= 2,
      "got %d" % m.ui.icon_reads)
check("I3 没有的图标返回 None", m._find_icon(ALL_CHANNELS) is None)
m2 = Task13Female()
m2.ui = SimUI(mode="first", unstable_icon=True)
m2.log = Log()
m2.stop = threading.Event()
check("I4 位置漂移时最多读 3 次后按最后一次", m2.ui.icon_reads == 0
      and m2._find_icon(FEMALE_ICON) is not None
      and m2.ui.icon_reads == 3, "got %d" % m2.ui.icon_reads)
qtext = [n for n in QUANYI if n["text"] == FEMALE_ICON][0]
check("I5 优惠权益页取到可点父容器",
      m._clickable_container(qtext["bounds"], QUANYI) == F_ENT_BOX,
      "got %s" % (m._clickable_container(qtext["bounds"], QUANYI),))
check("I6 没有可点父容器时返回 None",
      m._clickable_container((10, 10, 20, 20), [nd(u"x", 10, 10, 20, 20)]) is None)


# ================================================================ J
print("\n--- J. 完整 run() 状态机 ---")
sim = SimUI(mode="first")
log, guard = run_sim(sim)
check("J1 run 正常结束（log.done 被调用）",
      any(lv == "DONE" for lv, _ in log.lines), log.text()[-500:])
check("J2 没有真建 Appium session", guard["calls"] == 0)
check("J3 第一屏【女性专区】直达", sim.female_taps == 1 and sim.all_taps == 0)
check("J4 没有滑动金刚区", sim.kk_left == 0, "got %d" % sim.kk_left)
check("J5 做满 3 个任务", sim.browses == 3, "got %d" % sim.browses)
check("J6 每个任务 back 一次", sim.backs == 3, "got %d" % sim.backs)
check("J7 恰好有 3 次 15~18s 停留",
      len([s for s in sim.sleeps if 15 <= s <= 18]) == 3,
      "got %s" % ([s for s in sim.sleeps if 15 <= s <= 18],))
check("J8 领取 3 个奖励", sim.claimed == 3, "got %d" % sim.claimed)
check("J9 每个奖励弹窗都清掉", sim.happy_taps == 3,
      "got %d" % sim.happy_taps)
check("J10 领完奖后重新打开弹窗继续领",
      sim.panel_opens >= 4, "got %d" % sim.panel_opens)
check("J11 做任务全部结束后才领奖",
      max(i for i, e in enumerate(sim.events) if e == "browse") <
      min(i for i, e in enumerate(sim.events) if e == "claim"))
check("J12 完成日志写明浏览与领取次数",
      any(lv == "DONE" and u"3 次浏览任务" in msg and u"领取 3 个奖励" in msg
          for lv, msg in log.lines), log.text()[-400:])
check("J13 日志明确写了没有可做任务",
      u"任务列表已没有可做任务" in log.text())
check("J14 全程没有点击放大镜/搜索图标",
      (888, 164) not in sim.taps and (976, 166) not in sim.taps)
check("J15 商品价格节点没让台账发散", sim.browses == 3)

sim2 = SimUI(mode="second")
log2, _ = run_sim(sim2)
check("J16 第二屏找到【女性专区】也能完成",
      any(lv == "DONE" for lv, _ in log2.lines) and sim2.browses == 3,
      log2.text()[-400:])
check("J17 第二屏路径左滑金刚区一次",
      sim2.kk_left == 1, "got %d" % sim2.kk_left)
check("J18 第二屏路径不走全部频道", sim2.all_taps == 0)

sim3 = SimUI(mode="fallback")
log3, _ = run_sim(sim3)
check("J19 兜底路径正常完成",
      any(lv == "DONE" for lv, _ in log3.lines) and sim3.browses == 3,
      log3.text()[-500:])
check("J20 兜底路径点了【全部频道】", sim3.all_taps == 1)
check("J21 全部频道页停留 3s", 3 in sim3.sleeps,
      "got %s" % (sim3.sleeps[:12],))
check("J22 点了【优惠权益】tab", sim3.qy_taps == 1)
check("J23 点的是【女性专区】可点父容器", ctr(F_ENT_BOX) in sim3.taps,
      "got %s" % (sim3.taps[:8],))
check("J24 兜底路径最终进活动页", sim3.female_taps == 1)
check("J25 兜底路径没有放大镜点击",
      (888, 164) not in sim3.taps and (976, 166) not in sim3.taps)

sim4 = SimUI(mode="first", lost_on_back=True)
log4, _ = run_sim(sim4)
check("J26 back 后丢弹窗能就地恢复并做完",
      sim4.browses == 3 and sim4.claimed == 3,
      "browses=%d claimed=%d" % (sim4.browses, sim4.claimed))
check("J27 恢复时会重新点【做任务 赚更多惊喜值】",
      sim4.panel_opens >= 4, "got %d" % sim4.panel_opens)

sim5 = SimUI(mode="first", verify_on_tap=True)
log5, _ = run_sim(sim5)
check("J28 风控页会停下来", u"京东验证" in log5.text())
check("J29 风控页不做完 3 个任务", sim5.browses <= 1,
      "got %d" % sim5.browses)

stop = threading.Event()
sim6 = SimUI(mode="first", stop=stop, stop_after=2)
log6, _ = run_sim(sim6, stop=stop)
check("J30 stop_event 提前停止",
      sim6.browses <= 3 and any(lv == "DONE" for lv, _ in log6.lines),
      "browses=%d" % sim6.browses)
check("J31 stop 后没有继续领奖", sim6.claimed <= 1,
      "got %d" % sim6.claimed)

sim7 = SimUI(mode="first", refill=True)
log7, _ = run_sim(sim7, max_tasks=5)
check("J32 任务池补位时有上限保护、不死循环",
      sim7.browses <= 5 and sim7.browses >= 1,
      "got %d" % sim7.browses)
check("J33 上限收尾仍调用 done", any(lv == "DONE" for lv, _ in log7.lines))

sim8 = SimUI(mode="first", bases=[u"只有一行任务"])
log8, _ = run_sim(sim8)
check("J34 单行任务也能做完并领奖",
      sim8.browses == 1 and sim8.claimed == 1,
      "browses=%d claimed=%d" % (sim8.browses, sim8.claimed))

sim9 = SimUI(mode="first", bases=[])
log9, _ = run_sim(sim9)
check("J35 一开始就没有可做任务也能正常收尾",
      any(lv == "DONE" for lv, _ in log9.lines) and
      sim9.browses == 0 and sim9.claimed == 0, log9.text()[-400:])
check("J36 无可做任务时不点领取奖励",
      not any(e == "claim" for e in sim9.events))


# ================================================================ K
print("\n--- K. 需求合规复核 ---")
check("K1 只做白名单按钮（源码常量）",
      BTN_TEXTS == (u"去浏览", u"逛一逛", u"去完成"))
check("K2 不解析 X 秒动态值（本次固定随机停留）",
      u"browse_seconds" not in SRC and u"BROWSE_RE" not in SRC)
check("K3 停留是随机整数", "random" in SRC and "randint" in SRC)
check("K4 每个任务恰好一次 back", "self.ui.back(" in SRC and
      SRC.count("self.ui.back(") == 2)  # _do_one 一次 / _ensure_panel 恢复链一次
check("K5 领取奖励链路存在",
      "_claim_all" in SRC and "_clear_reward" in SRC and
      "_open_panel" in SRC)
check("K6 奖励弹窗后重新打开任务弹窗", "_ensure_panel" in SRC)
check("K7 判弹窗用独有标题", "PANEL_MARK" in SRC)
check("K8 安全区过滤屏幕外行", "SAFE_TOP" in SRC and "SAFE_BOTTOM" in SRC)
check("K9 有总次数/轮次/步数上限",
      "MAX_TASKS" in SRC and "MAX_CYCLES" in SRC and "MAX_STEPS" in SRC)
check("K10 入口复用公共金刚区方法",
      "kingkong_icons" in SRC and "swipe_kingkong" in SRC and
      "ensure_kingkong_visible" in SRC and "restart_to_home" in SRC)
check("K11 全部频道页有 3s 稳定停留", "ui.sleep(3)" in SRC)
check("K12 明确不走放大镜", u"不走放大镜" in SRC)


# ================================================================ 汇总
print("\n================ 汇总 ================")
print("passed=%d failed=%d total=%d" %
      (len(PASSED), len(FAILED), len(PASSED) + len(FAILED)))
if FAILED:
    for n in FAILED:
        print("  FAILED: %s" % n)
    print("RESULT: FAILED")
    sys.exit(1)
print("RESULT: ALL PASS")
