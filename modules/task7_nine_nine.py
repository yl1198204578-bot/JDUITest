# -*- coding: utf-8 -*-
"""任务7【9.9包邮】：京东首页【9.9包邮】卡片 -> 京豆浮层卡 -> 天天砸蛋任务列表 -> 逐个去完成。

入口（与需求一致，**不是金刚区**）：
  京东首页正文里那张「9.9包邮 / 买一送一」卡片，真机 1080x2340 下
  content-desc = "9.9包邮, 买一送一"，bounds = [23,993][530,1327]，中心 (276,1160)。
  注意：这张卡是 ViewGroup，text 为空、content-desc 才有值，且 clickable=false，
  所以必须用 desc 找、直接点中心（点父容器即可进入）。
  页面上还有两个同名节点要排除：
    - 顶部频道 tab "9.9包邮" [229,458][383,510]（高 52，太扁）
    - 价格文案 "2119.9"（不含「包邮」二字，天然不匹配）
  判据：desc 含【9.9包邮】且宽 >= 400、高 >= 150、y >= 700。

进入 9.9包邮 频道页后再点右侧京豆浮层卡（「抽3000京豆 再签2天 / 砸蛋领京豆」），
弹出【天天砸蛋】底部弹层，里面才是京豆任务列表。

任务行结构（真机实测）：
  标题  【逛省钱频道领京豆(0/1)】      <- 带 (N/M) 进度
  副标题【完成任务最高得1个京豆 +1】    <- 奖励描述，需求里的三种可做任务就是它
  按钮  【去完成】/【逛一逛】/【已完成】

可做任务（需求原文的三种，匹配的是副标题）：
  - 完成任务最高得N个京豆
  - 点击Y个商品且浏览Xs可得京豆
  - 完成任务可得N个京豆
且按钮是【逛一逛】或【去完成】。停留 (X+4) 秒，循环到没有可做任务为止，
**做完不需要领取奖励**。

真机踩坑记录（2026-11-12）：
1. 点【去完成】会跳到别的页（省钱频道/京东金融天天赚京豆/视频页…），
   但按一次 back 回到 9.9包邮 页后**弹层还在**，任务自动变 (1/1) 已完成。
   所以返回链路是「back 一次 + 校验弹层」，弹层没了出来就整链重进。
2. 弹层底部几行的【去完成】和 App 底部导航栏（y>=2169 的 首页/消息/购物车/我的）
   重叠，直接点会点成「我的」。所以点之前必须先把该行滚到安全区
   y in [1625, 2120]，否则宁可多滚一次。
3. 【添加"9.9包邮"桌面组件】点去完成会弹全屏「添加小组件到手机桌面」引导层
   （没有文字版关闭按钮，X 在 (1009,762)），这类任务关掉引导层就算尝试过，
   不重复点（否则永远做不完、死循环）。
4. 有些行的标题节点不在 dump 里（只有副标题），所以 key 优先用标题、退化为副标题。
"""
import re
import time

from modules.base import BaseModule
import utils.driver as driver
from utils.jd_ui import JDUI

# ---------- 入口 ----------
HOME_CARD_DESC = u"9.9包邮"
HOME_CARD_MIN_W = 400
HOME_CARD_MIN_H = 150
HOME_CARD_MIN_Y = 700                 # 避开顶部频道 tab 行
NINE_TAB_KEYWORDS = (u"今日半价", u"领券中心")   # 9.9包邮 频道页的 tab 文案
BEAN_ANCHOR_KEYWORDS = (u"京豆",)                # 京豆浮层卡上的文字
BEAN_ANCHOR_Y = (950, 1450)                      # 京豆浮层卡所在纵向区间
BEAN_CARD_FALLBACK = (755, 1215)                 # 兜底固定点（1080x2340 基准）

# ---------- 任务列表 ----------
BTN_TEXTS = (u"逛一逛", u"去完成")
DONE_TEXTS = (u"已完成", u"已领取", u"已结束")
BTN_MIN_X = 700                       # 按钮必须贴右
ROW_TOL = 70                          # 按钮与副标题的 y 容差
PANEL_MARK = u"继续下一个任务"          # 弹层专属文案

# 需求给的三种可做任务（匹配副标题）
REWARD_RES = (
    re.compile(u"完成任务最高得\\s*\\d+\\s*个?京豆"),
    re.compile(u"点击\\s*\\d+\\s*个商品且浏览\\s*\\d+\\s*[sS\u79d2]可得京豆"),
    re.compile(u"完成任务可得\\s*\\d+\\s*个?京豆"),
)
_BROWSE_RE = re.compile(u"浏览\\s*(\\d+)\\s*[sS\u79d2]")
_PROGRESS_RE = re.compile(u"[（(]\\s*\\d+\\s*/\\s*\\d+\\s*[）)]")

BROWSE_EXTRA = 4                      # 停留 = X + 4 秒
DEFAULT_BROWSE = 6                    # 没写浏览Ns的任务，按 6s 浏览（停留 10s）

SAFE_TOP = 1625                       # 弹层可点安全区上界（砸蛋头部以下）
SAFE_BOTTOM = 2120                    # 安全区下界（底部导航栏 y>=2169 以上）

MAX_TASKS = 30
MAX_SCROLLS = 8
MAX_SWEEPS = 1                        # 收尾全表扫描最多做几次（做完一个任务会重置）
SWEEP_SCROLLS = 3                     # 收尾扫描每次最多滑几下（page_source 很慢，别贪多）
MAX_REENTER = 3
MAX_READ_FAILS = 4
GUIDE_CLOSE_PT = (1009, 762)          # 「添加小组件到手机桌面」引导层的 X


# ---------------------------------------------------------------- 纯逻辑
def browse_seconds(x):
    """页面要求 X 秒 -> 实际停留 X + BROWSE_EXTRA。"""
    return int(x) + BROWSE_EXTRA


def is_reward_text(txt):
    """副标题是否是需求里那三种京豆任务描述之一。"""
    txt = (txt or "").strip()
    if not txt:
        return False
    return any(r.search(txt) for r in REWARD_RES)


def _title_key(txt):
    """标题去掉 (N/M) 进度，作为「已尝试」台账的稳定 key。"""
    return _PROGRESS_RE.sub(u"", (txt or "").strip()).strip()


def parse_task_rows(nodes, btn_min_x=BTN_MIN_X, row_tol=ROW_TOL):
    """把弹层节点配对成任务行。

    只有「右侧按钮（逛一逛/去完成/已完成）+ 同一行左侧的京豆奖励描述」才算一行，
    页面上别处零散的【去完成】天然被排除。
    返回 [{'title','reward','btn','btn_bounds','cx','cy','secs','doable','key'}]，按 cy 升序。
    """
    btns, rewards, titles = [], [], []
    for n in nodes or []:
        b = n.get("bounds") or (0, 0, 0, 0)
        if b[3] <= b[1] or b[2] <= b[0]:
            continue                      # 屏外/退化节点
        txt = (n.get("text") or "").strip()
        cx = (b[0] + b[2]) // 2
        cy = (b[1] + b[3]) // 2
        if txt in BTN_TEXTS + DONE_TEXTS and n.get("clickable") and cx >= btn_min_x:
            btns.append({"text": txt, "cx": cx, "cy": cy, "bounds": b})
            continue
        if is_reward_text(txt):
            rewards.append({"text": txt, "cy": cy, "bounds": b})
            continue
        if _PROGRESS_RE.search(txt):
            titles.append({"text": txt, "cy": cy, "bounds": b})

    rows = []
    for b in btns:
        cand = [(abs(r["cy"] - b["cy"]), r) for r in rewards
                if abs(r["cy"] - b["cy"]) <= row_tol and r["bounds"][2] <= b["bounds"][0]]
        if not cand:
            continue
        cand.sort(key=lambda t: t[0])
        reward = cand[0][1]
        title = _row_title(titles, b, reward, row_tol)
        m = _BROWSE_RE.search(reward["text"])
        secs = int(m.group(1)) if m else DEFAULT_BROWSE
        rows.append({
            "title": title,
            "reward": reward["text"],
            "btn": b["text"],
            "btn_bounds": b["bounds"],
            "cx": b["cx"],
            "cy": b["cy"],
            "secs": secs,
            "doable": b["text"] in BTN_TEXTS,
            "key": _title_key(title) or reward["text"],
        })
    rows.sort(key=lambda r: r["cy"])
    return rows


def _row_title(titles, btn, reward, row_tol):
    """标题在副标题上方、按钮左侧，带 (N/M) 进度。

    标题和副标题离按钮一样近（实测都 ~28px），所以不能只比距离：
    已经认出副标题了，标题就取「在副标题上方且离它最近」的那个。
    """
    best = None
    for t in titles:
        b = t["bounds"]
        if b[2] > btn["bounds"][0]:
            continue                      # 必须在按钮左边
        if abs(t["cy"] - btn["cy"]) > row_tol:
            continue
        if t["cy"] > reward["cy"]:
            continue                      # 标题在副标题上方
        score = abs(t["cy"] - reward["cy"])
        if best is None or score < best[0]:
            best = (score, t["text"])
    return best[1] if best else u""


def row_signature(rows):
    """任务行指纹：key + 按钮文案。做完一个任务它就会变。"""
    return tuple(sorted((r.get("key") or u"") + u"|" + (r.get("btn") or u"")
                        for r in (rows or [])))


def pick_target(rows, attempted, safe_top=SAFE_TOP, safe_bottom=SAFE_BOTTOM):
    """挑一个可做、没试过、且在安全区里的行。

    返回 (row, reason)：
      row 不为 None  -> 直接点
      row 为 None, reason='below' -> 目标在安全区下方，向下滚（内容上移）
      row 为 None, reason='above' -> 目标在安全区上方，向上滚
      row 为 None, reason='none'  -> 没有可做任务了
    """
    doable = [r for r in (rows or []) if r.get("doable") and r.get("key") not in attempted]
    if not doable:
        return None, "none"
    for r in doable:
        b = r["btn_bounds"]
        if b[1] >= safe_top and b[3] <= safe_bottom:
            return r, "ok"
    if all(r["btn_bounds"][1] > safe_bottom for r in doable):
        return None, "below"
    if all(r["btn_bounds"][3] < safe_top for r in doable):
        return None, "above"
    # 混在一起（有的太下有的太上）：先往下滚，把下面的带上来
    if any(r["btn_bounds"][1] > safe_bottom for r in doable):
        return None, "below"
    return None, "above"


def panel_visible(nodes):
    """弹层是否在：有任务行，或有【继续下一个任务】。"""
    if parse_task_rows(nodes):
        return True
    for n in nodes or []:
        if (n.get("text") or "").strip() == PANEL_MARK:
            return True
    return False


def guide_visible(nodes):
    """「添加小组件到手机桌面」引导层是否在。"""
    joined = u" ".join([((n.get("text") or "") + (n.get("desc") or "")).strip()
                        for n in nodes or []])
    return (u"小组件" in joined and u"桌面" in joined) or u"去添加" in joined


# ---------------------------------------------------------------- 模块
class Task7NineNine(BaseModule):
    name = "9.9包邮"
    description = ("京东首页【9.9包邮】卡片 → 京豆浮层卡 → 天天砸蛋任务（逛一逛/去完成），"
                   "停留 X+4 秒，做完不领奖")
    icon = "🛍"

    def run(self, log, stop_event):
        ui = JDUI(driver.get_driver(), log, stop_event)
        log.write_log("设备分辨率 %dx%d" % (ui.W, ui.H))

        if not self._open_nine_nine(ui, log):
            raise RuntimeError("未能从京东首页进入【9.9包邮】")
        if stop_event.is_set():
            return
        if not self._open_bean_panel(ui, log):
            raise RuntimeError("【9.9包邮】页未能打开京豆任务弹层")
        if stop_event.is_set():
            return

        done, tried = self._process_tasks(ui, log, stop_event)
        if stop_event.is_set():
            return
        log.done("9.9包邮 完成 %d 个任务（共尝试 %d 个），无需领取奖励" % (done, tried))

    # ---------- 入口 ----------
    def _open_nine_nine(self, ui, log):
        """首页 -> 9.9包邮 频道页。

        真机踩过（2026-11-12 第一次运行）：先 goto_home() 再「滑到顶部」，
        结果首页本来就停在顶部，多余的下滑把页面带偏到秒送/足迹页，
        后面 16 秒都读不到【9.9包邮】卡片。改成和 task6 一样直接冷启动，
        保证从干净的「首页」tab 顶部开始，然后逐个试候选卡片。
        """
        if not ui.restart_to_home():
            log.write_log("冷启动回首页失败", "WARN")
            if not ui.goto_home():
                return False

        for round_ in range(2):
            cards = self._home_cards(ui)
            if not cards:
                log.write_log("首页没找到【9.9包邮】卡片（第 %d 轮）" % (round_ + 1), "WARN")
            for idx, card in enumerate(cards[:3]):
                b = card["bounds"]
                pos = ui.center(card)
                log.write_log("首页命中【9.9包邮】卡片 %s（desc=%r），点击 (%d,%d)"
                              % (b, card.get("desc") or card.get("text"), pos[0], pos[1]))
                ui.adb_tap(pos, pause=3.0)
                ui.invalidate()
                if self._wait_nine_page(ui, log, tries=4):
                    log.write_log("已进入【9.9包邮】频道页")
                    return True
                log.write_log("点了第 %d 张候选卡片没进 9.9包邮 页，换下一张" % (idx + 1), "WARN")
                if not ui.goto_home():
                    break
            if round_ == 0:
                log.write_log("首页候选卡片都没进 9.9包邮，冷启动再来一轮", "WARN")
                if not ui.restart_to_home():
                    break
        return False

    def _home_cards(self, ui, tries=6):
        """首页正文里的「9.9包邮, xx」卡片（content-desc 才有值，text 为空）。

        真机同一屏会命中两张：
          [23,993][530,1327]    desc='9.9包邮, 买一送一'      507x334  <- 要的这张
          [648,1433][1045,1652] desc='9.9包邮, 厨具小电日用'   397x219  <- 秒送推荐位
        按「面积从大到小」排，宽 < 400 的直接不要。
        """
        for i in range(tries):
            out = []
            for n in self._nodes(ui):
                v = " ".join(((n.get("text") or "") + " " + (n.get("desc") or "")).split())
                if HOME_CARD_DESC not in v:
                    continue
                b = n["bounds"]
                if b[3] <= b[1] or b[2] <= b[0]:
                    continue
                w, h = b[2] - b[0], b[3] - b[1]
                if w < HOME_CARD_MIN_W or h < HOME_CARD_MIN_H:
                    continue
                if b[1] < HOME_CARD_MIN_Y:
                    continue                  # 顶部频道 tab 行
                if b[3] > ui.H - 200:
                    continue                  # 被底部导航压住的不用
                out.append((-(w * h), b[1], n))
            if out:
                out.sort(key=lambda t: (t[0], t[1]))
                return [t[2] for t in out]
            if i < tries - 1:
                ui.sleep(1.2)
                ui.invalidate()
        return []

    def _is_nine_page(self, nodes):
        """是不是 9.9包邮 频道页。

        真机踩过：原来拿【今日半价】/【领券中心】做**全页子串**匹配，
        结果京东首页正文里也有「领券中心」几个字，明明还停在首页却判成
        「已进入 9.9包邮」，后面找京豆卡自然找不到。收紧成两条硬特征：
          1. 京豆浮层卡锚点（首页没有，实测 _bean_anchor(首页)=None）
          2. 顶部 tab 行 y in [400,560] 上有一个文案**完全等于**【今日半价】的节点
        """
        if self._bean_anchor(nodes):
            return True
        for n in nodes or []:
            b = n["bounds"]
            if b[3] <= b[1] or b[2] <= b[0]:
                continue
            if (n.get("text") or "").strip() != u"今日半价":
                continue
            if 400 <= b[1] <= 560:
                return True
        return False

    def _wait_nine_page(self, ui, log, tries=8):
        """等 9.9包邮 频道页。按次数等，不用墙钟，方便离线测。"""
        for _ in range(tries):
            nodes = self._nodes(ui)
            if nodes and self._is_nine_page(nodes):
                return True
            ui.sleep(1.5)
        log.write_log("等待【9.9包邮】频道页超时", "WARN")
        return False

    def _bean_anchor(self, nodes):
        """京豆浮层卡上的可点锚点（「抽3000京豆 再签2天」之类）。"""
        best = None
        for n in nodes or []:
            b = n["bounds"]
            if b[3] <= b[1] or b[2] <= b[0]:
                continue
            v = (n.get("text") or "") + (n.get("desc") or "")
            if not any(k in v for k in BEAN_ANCHOR_KEYWORDS):
                continue
            if not (BEAN_ANCHOR_Y[0] <= b[1] <= BEAN_ANCHOR_Y[1]):
                continue
            if b[0] < 400:
                continue                  # 京豆卡在右侧
            cand = (0 if n.get("clickable") else 1, b[1], n)
            if best is None or cand[:2] < best[:2]:
                best = cand
        return best[2] if best else None

    # ---------- 弹层 ----------
    def _open_bean_panel(self, ui, log, tries=2):
        """点京豆浮层卡，打开【天天砸蛋】弹层。"""
        for t in range(tries):
            nodes = self._nodes(ui)
            anchor = self._bean_anchor(nodes)
            if anchor is not None:
                pos = ui.center(anchor)
                log.write_log("命中京豆浮层卡 %s（%r），点击 (%d,%d)"
                              % (anchor["bounds"], anchor.get("text"), pos[0], pos[1]))
            else:
                pos = (ui.sx(BEAN_CARD_FALLBACK[0]), ui.sy(BEAN_CARD_FALLBACK[1]))
                log.write_log("没找到京豆卡锚点，用兜底坐标 (%d,%d)" % pos, "WARN")
            ui.adb_tap(pos, pause=3.0)
            ui.invalidate()

            if self._wait_panel(ui, log):
                log.write_log("【天天砸蛋】京豆任务弹层已打开")
                return True
            log.write_log("第 %d 次点京豆卡没弹出任务列表，重试" % (t + 1), "WARN")
        return False

    def _wait_panel(self, ui, log, tries=8):
        """等【天天砸蛋】弹层。同样按次数等。"""
        for _ in range(tries):
            nodes = self._nodes(ui)
            if nodes and panel_visible(nodes):
                return True
            ui.sleep(1.5)
        return False

    # ---------- 任务循环 ----------
    def _process_tasks(self, ui, log, stop_event):
        attempted = set()
        done = 0
        scrolls = 0
        read_fails = 0
        reenter = 0
        sweeps = 0

        while len(attempted) < MAX_TASKS:
            if stop_event.is_set():
                break
            nodes = self._nodes(ui)
            if not nodes:
                read_fails += 1
                if read_fails >= MAX_READ_FAILS:
                    log.write_log("连续 %d 次读不到页面，收尾" % read_fails, "WARN")
                    break
                continue
            read_fails = 0

            if not panel_visible(nodes):
                if reenter >= MAX_REENTER:
                    log.write_log("弹层反复丢失，重进次数用尽，收尾", "WARN")
                    break
                reenter += 1
                log.write_log("任务弹层不见了，第 %d 次重进" % reenter, "WARN")
                if not self._reenter(ui, log):
                    break
                continue

            rows = parse_task_rows(nodes)
            row, reason = pick_target(rows, attempted)
            if row is None:
                if reason == "none":
                    # parse_task_rows 只看得到屏内节点，列表长的时候可能漏。
                    # 收尾前先把列表从头到尾扫一遍再下结论。
                    if sweeps < MAX_SWEEPS and self._sweep_for_target(ui, log, attempted):
                        sweeps += 1
                        continue
                    log.write_log("任务列表里已没有可做任务")
                    break
                if scrolls >= MAX_SCROLLS:
                    log.write_log("滚动 %d 次仍没有可点任务，收尾" % scrolls, "WARN")
                    break
                scrolls += 1
                self._scroll_panel(ui, log, reason)
                continue

            scrolls = 0
            attempted.add(row["key"])
            dwell = browse_seconds(row["secs"])
            log.write_log("任务【%s】%r 按钮【%s】%s，停留 %ds"
                          % (row["title"] or u"(无标题)", row["reward"], row["btn"],
                             row["btn_bounds"], dwell))
            ui.adb_tap((row["cx"], row["cy"]), pause=1.5)
            ui.invalidate()
            ui.sleep(2.0)

            if self._dismiss_guide(ui, log):
                # 桌面组件这类任务没有可浏览页，关掉引导层就算尝试过
                if self._return_to_panel(ui, log):
                    continue
                if reenter >= MAX_REENTER:
                    break
                reenter += 1
                if not self._reenter(ui, log):
                    break
                continue

            ui.sleep(dwell)
            if self._return_to_panel(ui, log):
                sweeps = 0
                if self._row_completed(ui, row):
                    done += 1
                    log.write_log("任务【%s】已完成" % (row["title"] or row["reward"]))
                else:
                    log.write_log("任务【%s】回弹层了但按钮还没变【已完成】"
                                  % (row["title"] or row["reward"]), "WARN")
                continue

            if reenter >= MAX_REENTER:
                log.write_log("回不到任务弹层，重进次数用尽，收尾", "WARN")
                break
            reenter += 1
            log.write_log("任务【%s】后回不到弹层，第 %d 次重进"
                          % (row["title"] or row["reward"], reenter), "WARN")
            if not self._reenter(ui, log):
                break

        return done, len(attempted)

    def _sweep_for_target(self, ui, log, attempted, max_scrolls=SWEEP_SCROLLS):
        """把任务列表从头到尾扫一遍，找有没有被滚动位置漏掉的可做任务。

        parse_task_rows 只能看到屏内节点（屏外 bounds 会退化被丢掉），
        所以「当前屏没有可做任务」不等于「列表里没有」。收尾前扫一遍。

        真机踩过（2026-11-12 第 2 次运行）：一开始每滑一下都前后各读一次页面
        来判断「滑不动了」，而这个 H5 页 page_source 一次要 1~2 秒，
        收尾扫描硬生生花了 3 分 09 秒。改成固定滑 SWEEP_SCROLLS 下、
        每滑一下只读一次，整轮压到十几秒。
        """
        # 先回列表顶部（手指下滑 = 内容下移），不检测是否滑到底，固定几下
        for _ in range(max_scrolls):
            ui.adb_swipe(ui.W // 2, ui.sy(1740), ui.W // 2, ui.sy(2100), duration=350)
            ui.sleep(0.9)
            ui.invalidate()
        # 再逐屏往下扫
        for i in range(max_scrolls + 1):
            rows = parse_task_rows(self._nodes(ui))
            left = [r for r in rows if r["doable"] and r["key"] not in attempted]
            if left:
                log.write_log("全表扫描发现 %d 个漏掉的可做任务（如【%s】）"
                              % (len(left), left[0]["title"] or left[0]["reward"]))
                return True
            if i < max_scrolls:
                ui.adb_swipe(ui.W // 2, ui.sy(2100), ui.W // 2, ui.sy(1740), duration=350)
                ui.sleep(0.9)
                ui.invalidate()
        return False

    def _scroll_panel(self, ui, log, reason):
        """在弹层里滚动任务列表（注意不要碰到底部导航栏）。"""
        x = ui.W // 2
        if reason == "below":
            log.write_log("目标任务在安全区下方，列表上滑")
            ui.adb_swipe(x, ui.sy(2100), x, ui.sy(1740), duration=400)
        else:
            log.write_log("目标任务在安全区上方，列表下滑")
            ui.adb_swipe(x, ui.sy(1740), x, ui.sy(2100), duration=400)
        ui.sleep(1.4)
        ui.invalidate()

    def _dismiss_guide(self, ui, log, checks=2):
        """关掉「添加小组件到手机桌面」引导层。

        真机踩过：引导层不一定在点完 2 秒内就出来，只探一次会漏，
        漏了就会白等 10 秒 dwell，然后靠 _return_to_panel 兜底去关。
        这里给两次机会，间隔 1.2 秒。
        """
        for i in range(checks):
            nodes = self._nodes(ui)
            if guide_visible(nodes):
                log.write_log("出现「添加小组件到手机桌面」引导层，点 X 关掉", "WARN")
                ui.adb_tap((ui.sx(GUIDE_CLOSE_PT[0]), ui.sy(GUIDE_CLOSE_PT[1])), pause=1.5)
                ui.invalidate()
                if guide_visible(self._nodes(ui)):
                    log.write_log("X 没关掉，改用返回键", "WARN")
                    ui.back(pause=1.5)
                return True
            if i < checks - 1:
                ui.sleep(1.2)
                ui.invalidate()
        return False

    def _row_completed(self, ui, row):
        """回到弹层后再看一眼：那一行按钮是不是真的变成【已完成】了。

        真机踩过：【添加"9.9包邮"桌面组件】点去完成只是弹了个引导层，
        任务并没有完成。旧代码只要「能回到弹层」就记一次完成，
        最终日志会谎报「完成 2 个任务」。行不在屏内时无法判断，按完成计。
        """
        rows = parse_task_rows(self._nodes(ui))
        same = [r for r in rows if r["key"] == row["key"]]
        if not same:
            return True                   # 行不在当前屏，无法核对，不冤枉它
        return same[0]["btn"] in DONE_TEXTS

    def _return_to_panel(self, ui, log, tries=3):
        """从任务落地页回到京豆任务弹层。"""
        for i in range(tries):
            nodes = self._nodes(ui)
            if nodes and panel_visible(nodes):
                return True
            if nodes and guide_visible(nodes):
                ui.adb_tap((ui.sx(GUIDE_CLOSE_PT[0]), ui.sy(GUIDE_CLOSE_PT[1])), pause=1.5)
                ui.invalidate()
                continue
            if i:
                log.write_log("第 %d 次返回仍没回到弹层" % i, "WARN")
            ui.back(pause=2.0)
            ui.sleep(0.8)
            ui.invalidate()
        return panel_visible(self._nodes(ui))

    def _reenter(self, ui, log):
        """整链重进：首页 -> 9.9包邮 -> 京豆卡 -> 弹层。"""
        if not self._open_nine_nine(ui, log):
            return False
        return self._open_bean_panel(ui, log)

    # ---------- 小工具 ----------
    def _nodes(self, ui, tries=3, pause=1.5):
        """读页面节点，读不到就重读。

        page_source 在页面切换瞬间会报
        `Timed out waiting for the root AccessibilityNodeInfo`，
        jd_ui.source() 吞掉异常返回空串，nodes() 就成了 []。
        读失败 != 页面没了，所以先重读再下结论。
        """
        for i in range(tries):
            ui.invalidate()
            ns = ui.nodes()
            if ns:
                return ns
            if i < tries - 1:
                ui.sleep(pause)
        return []

    def _page_hash(self, ui):
        """页面指纹，用来判断滑动有没有效果。"""
        ns = self._nodes(ui, tries=1)
        if not ns:
            return None
        return hash(tuple(sorted(
            ((n.get("text") or "") + "|" + str(n.get("bounds")))
            for n in ns if (n.get("text") or "").strip()
        )))
