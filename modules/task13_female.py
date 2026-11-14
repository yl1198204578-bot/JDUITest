# -*- coding: utf-8 -*-
"""任务13：【女性专区】天天送惊喜 —— 做浏览任务 + 领取奖励。

入口（用户指定，全部复用 utils/jd_ui.py 的公共金刚区方法；不走放大镜/中文搜索）：
  京东首页 → 用【秒杀】锚点确认金刚区那一行（一排 5 个半图标）
  → 第一屏找【女性专区】图标，找到就点
  → 没找到左滑到第二屏再找，找到就点
  → 两屏都没有 → 点第二屏【全部频道】→ 停留 3s 稳定
  → 切【优惠权益】tab → 找【女性专区】入口 → 点进活动页
  → 点【做任务 赚更多惊喜值】进任务弹窗

任务：
  可做任务 = 右侧 Button 文案为【去浏览 / 逛一逛 / 去完成】
  每次停留 random.randint(15, 18) 秒，back 一次回弹窗
  循环扫到列表没有可做任务为止
  最后逐个点【领取奖励】→【开心收下】，全部领完结束

真机踩坑（2026-11-13）：
  * 金刚区第二屏的【女性专区】格子坐标会变（两次实测 (867,601,1080,762)
    与 (651,440,867,601)），必须按 content-desc 动态找，禁止写死坐标。
  * 弹窗与活动页节点混在同一份 XML；判定弹窗只能用独有的
    【做任务赚惊喜值】标题，不能用活动页的【做任务 赚更多惊喜值】按钮。
  * 任务列表滚动后，所有节点 bounds 整体平移约 890px；屏幕外行的
    displayed 仍可能是 true，所以唯一可靠的可视判据是
    SAFE_TOP <= y1 且 y2 <= SAFE_BOTTOM（tab 底部 y=1121）。
    直接点 y=329 那类屏幕外按钮会点到背后的活动页。
  * 落地页里也有【去完成】文字，但它是 clickable=false 的 TextView；
    任务按钮是 clickable=true 的 Button，且必须先确认处在弹窗页。
  * 点【领取奖励】会弹「恭喜获得奖励」，同时任务弹窗被关闭，
    点【开心收下】后回到活动主页 —— 要领下一个必须重新点
    【做任务 赚更多惊喜值】打开弹窗。
  * 全部频道/活动页首帧常只有 18 个节点的骨架，必须轮询复核。
"""
import random
import re

import utils.driver as driver
from modules.base import BaseModule
from utils.jd_ui import JDUI

# ---------------- 页面与按钮常量 ----------------
FEMALE_ICON = u"女性专区"
ALL_CHANNELS = u"全部频道"
QUANYI_TAB = u"优惠权益"
TASK_ENTRY = u"做任务 赚更多惊喜值"
PANEL_MARK = u"做任务赚惊喜值"
PANEL_TABS = (u"全部", u"惊喜任务", u"下单任务")
BTN_TEXTS = (u"去浏览", u"逛一逛", u"去完成")
CLAIM_TEXT = u"领取奖励"
HAPPY_TEXT = u"开心收下"
REWARD_CLOSE = u"关闭"
REWARD_MARK = u"恭喜获得奖励"
VERIFY_MARKS = (u"京东验证", u"快速验证")

# 任务列表可视区（弹窗标题 y=771~829，tab y=1013~1121，底栏 y=2340）
SAFE_TOP = 1150
SAFE_BOTTOM = 2340
BTN_MIN_X = 800
BTN_MAX_X = 1060
TITLE_MAX_X = 700
TITLE_MIN_X = 100
TITLE_MAX_DY = 220
TITLE_ANCHOR_X = 217     # 弹窗任务标题统一左对齐在这个 x
TITLE_X_TOL = 70         # 背景页商品卡文案 x>=550，靠这判据排除

DWELL_MIN = 15
DWELL_MAX = 18

# 列表内滑动（1080x2340 基准，运行时用 ui.sx/ui.sy 缩放）
SWIPE_UP = (540, 2100, 540, 1250)
SWIPE_DOWN = (540, 1250, 540, 2100)
SWIPE_MS = 450

MAX_TASKS = 40          # 总浏览次数硬上限
MAX_CYCLES = 8          # 「从顶扫到底」最大轮次
MAX_STEPS = 180         # 单轮最多动作步数
MAX_SCROLLS = 12        # 单轮最多上滑屏数
MAX_PER_TASK = 3        # 同一任务本轮最多做几次
MAX_RETRY = 2           # 单任务连续失败几次后拉黑
MAX_CLAIMS = 20         # 最多领奖个数
MAX_READ_FAILS = 4      # 连续读不到页面
MAX_TO_TOP = 8          # 回顶最多下滑次数

PROGRESS_RE = re.compile(u"[（(]\\s*\\d+\\s*/\\s*\\d+\\s*[）)]")
DATE_RE = re.compile(u"^\\d{4}\\.\\d{2}\\.\\d{2}")
PRICE_RE = re.compile(u"[¥￥]|到手价|^\\d+\\.\\d+$")
NOISE_TEXTS = (u"惊喜值", u"京豆", u"大奖进度", u"完成得惊喜好物",
               u"领试用好物", u"个", u"后失效", u"已领取")
ALL_BTN_TEXTS = BTN_TEXTS + (CLAIM_TEXT, u"已完成", HAPPY_TEXT, REWARD_CLOSE)


# ---------------- 纯函数：解析与判定 ----------------
def norm(t):
    """H5 会把文字渲染成竖排（带 \\n），关键字匹配前先压掉空白。"""
    return re.sub(r"\s+", "", t or u"")


def valid(b):
    return bool(b) and len(b) == 4 and b[2] > b[0] and b[3] > b[1]


def center(b):
    return ((b[0] + b[2]) // 2, (b[1] + b[3]) // 2)


def in_list(b):
    """按钮是否真的落在当前屏的弹窗任务列表可视区。"""
    return (valid(b)
            and SAFE_TOP <= b[1]
            and b[3] <= SAFE_BOTTOM
            and b[0] >= BTN_MIN_X
            and b[2] <= BTN_MAX_X)


def is_task_button(n):
    """弹窗任务行按钮 = 贴右 + 可视区 + clickable Button + 白名单文案。"""
    t = norm(n.get("text"))
    return (t in BTN_TEXTS
            and bool(n.get("clickable"))
            and n.get("class") == "Button"
            and in_list(n.get("bounds")))


def is_claim_button(n):
    t = norm(n.get("text"))
    return (t == CLAIM_TEXT
            and bool(n.get("clickable"))
            and n.get("class") == "Button"
            and in_list(n.get("bounds")))


def classify(nodes):
    """页面状态：verify / reward / panel / female / channels / quanyi / other。"""
    if not nodes:
        return "other"
    texts = set(norm(n.get("text")) for n in nodes)
    descs = set(norm(n.get("desc")) for n in nodes)
    blob = texts | descs
    if any(any(v in t for v in VERIFY_MARKS) for t in blob):
        return "verify"
    if HAPPY_TEXT in texts or REWARD_MARK in texts:
        return "reward"
    if PANEL_MARK in texts:
        return "panel"
    nt = norm(TASK_ENTRY)
    if FEMALE_ICON in texts and nt in texts:
        return "female"
    if FEMALE_ICON in texts and QUANYI_TAB in texts:
        return "quanyi"
    if ALL_CHANNELS in texts and QUANYI_TAB in texts:
        return "channels"
    return "other"


def row_title(nodes, btn_bounds):
    """给右側按钮配同行标题。

    标题必须在按钮上方开始（副标题【惊喜值】/日期都在按钮下方或更下）。
    弹窗任务标题统一左对齐 x≈217，背景页商品卡的「¥269.00 / 到手价」
    x≈574~687 且纵向更近，只按距离排会被它抢走，所以对齐优先于距离，
    并直接排除价格文案。
    """
    bx1, by1, bx2, by2 = btn_bounds
    bcy = (by1 + by2) // 2
    cands = []
    for n in nodes:
        t = norm(n.get("text"))
        if not t or len(t) < 3 or t in NOISE_TEXTS or DATE_RE.match(t):
            continue
        if PRICE_RE.search(t):
            continue
        b = n.get("bounds")
        if not valid(b) or b[0] < TITLE_MIN_X or b[0] > TITLE_MAX_X:
            continue
        if b[1] >= by1 + 10 or b[3] < by1 - TITLE_MAX_DY:
            continue
        cy = (b[1] + b[3]) // 2
        dist = bcy - cy
        if dist < -20 or dist > 180:
            continue
        prog = bool(PROGRESS_RE.search(t))
        aligned = abs(b[0] - TITLE_ANCHOR_X) <= TITLE_X_TOL
        cands.append((0 if aligned else 1, 0 if prog else 1,
                      abs(dist), b[0], -len(t), t))
    if not cands:
        return u""
    cands.sort()
    return cands[0][5]


def task_key(title, btn_text):
    """台账 key 去掉 (N/M) 进度，任务做完进度 +1 时仍是同一个任务。"""
    return PROGRESS_RE.sub(u"", title or u"") + u"|" + norm(btn_text)


def parse_rows(nodes, kind="task"):
    """解析当前屏可做任务 / 待领奖励行。"""
    if classify(nodes) != "panel":
        return []
    pred = is_task_button if kind == "task" else is_claim_button
    out = []
    for n in nodes:
        if not pred(n):
            continue
        b = n["bounds"]
        t = norm(n.get("text"))
        title = row_title(nodes, b)
        out.append({
            "text": t,
            "title": title,
            "bounds": b,
            "center": center(b),
            "key": task_key(title, t),
        })
    out.sort(key=lambda r: (r["bounds"][1], r["bounds"][0]))
    return out


def panel_sig(nodes):
    """当前屏可视区按钮签名，用于判「滑到底 / 回到顶部」。"""
    items = []
    for n in nodes:
        t = norm(n.get("text"))
        b = n.get("bounds")
        if t in ALL_BTN_TEXTS and in_list(b):
            items.append((t, tuple(b)))
    items.sort()
    return tuple(items)


def dwell_seconds(rnd=None):
    """每次浏览停留 15~18 秒随机。"""
    r = rnd if rnd is not None else random
    return r.randint(DWELL_MIN, DWELL_MAX)


def pick_target(rows, blacklist, attempts, max_per_task=MAX_PER_TASK):
    """挑一个还没做满 / 没被拉黑的任务。"""
    for r in rows:
        if r["key"] in blacklist:
            continue
        if attempts.get(r["key"], 0) >= max_per_task:
            continue
        return r
    return None


# ---------------- 模块主体 ----------------
class Task13Female(BaseModule):
    name = u"女性专区"
    description = (u"首页金刚区【女性专区】图标（两屏找不到则走"
                   u"【全部频道】-优惠权益-女性专区）→【做任务 赚更多惊喜值】"
                   u"→ 做【去浏览/逛一逛/去完成】任务停留 15~18 秒随机"
                   u"→ 循环至无可做任务 → 逐个【领取奖励】【开心收下】")
    icon = u"\U0001F457"

    def __init__(self):
        self.ui = None
        self.log = None
        self.stop = None

    # ---------- 基础封装 ----------
    def _say(self, msg, level="INFO"):
        if self.log is not None:
            self.log.write_log(msg, level)

    def _stopped(self):
        return self.stop is not None and self.stop.is_set()

    def _snap(self):
        self.ui.invalidate()
        xml = self.ui.source(fresh=True)
        nodes = self.ui.nodes(xml) if xml else []
        return classify(nodes), nodes

    def _find_text(self, text, clickable=None, nodes=None):
        if nodes is None:
            _, nodes = self._snap()
        want = norm(text)
        for n in nodes:
            if want not in (norm(n.get("text")), norm(n.get("desc"))):
                continue
            if clickable is not None and bool(n.get("clickable")) != clickable:
                continue
            b = n.get("bounds")
            if valid(b):
                return tuple(b)
        return None

    def _tap(self, b, pause=1.2):
        self.ui.adb_tap(center(b), pause=pause)

    def _find_icon(self, desc, stable=True):
        """复用公共 kingkong_icons()：按 content-desc 动态找金刚区格子。

        冷启动首页会回弹，坐标会漂；连续两次 dump 的 bounds 一致才敢点
        （与公共 _stable_kingkong_icon 同一思路）。查不到返回 None。
        """
        last = None
        tries = 3 if stable else 1
        for i in range(tries):
            self.ui.invalidate()
            icons = self.ui.kingkong_icons(self.ui.source(fresh=True))
            hits = [x for x in icons
                    if desc in x["desc"] and valid(x["bounds"])]
            cur = tuple(hits[0]["bounds"]) if hits else None
            if cur is None:
                return None
            if cur == last:
                return cur
            last = cur
            if i < tries - 1:
                self.ui.sleep(0.8)
        return last

    def _clickable_container(self, b, nodes):
        """H5 文本节点常不可点，取包住它的最小可点父容器。"""
        cx, cy = center(b)
        hits = []
        for n in nodes:
            nb = n.get("bounds")
            if not n.get("clickable") or not valid(nb):
                continue
            if not (nb[0] <= cx <= nb[2] and nb[1] <= cy <= nb[3]):
                continue
            w, h = nb[2] - nb[0], nb[3] - nb[1]
            if w <= 400 and h <= 400:
                hits.append((w * h, tuple(nb)))
        if not hits:
            return None
        hits.sort()
        return hits[0][1]

    def _scroll(self, spec, pause=1.5):
        x1, y1, x2, y2 = spec
        self.ui.adb_swipe(self.ui.sx(x1), self.ui.sy(y1),
                          self.ui.sx(x2), self.ui.sy(y2), SWIPE_MS)
        self.ui.sleep(pause)
        self.ui.invalidate()

    def _scroll_up(self):
        self._scroll(SWIPE_UP)

    def _scroll_down(self):
        self._scroll(SWIPE_DOWN)

    def _wait_state(self, want, tries=6, pause=1.5):
        """H5 首帧常只有 18 个节点骨架，轮询复核。"""
        for k in range(tries):
            state, nodes = self._snap()
            if state == want:
                self._say(u"已进入【%s】（第 %d 次读，nodes=%d）"
                          % (want, k + 1, len(nodes)))
                return True
            if state == "verify":
                return False
            self.ui.sleep(pause)
        self._say(u"等待【%s】超时" % want, "WARN")
        return False

    # ---------- 入口链路 ----------
    def _enter(self):
        ui = self.ui
        if not ui.restart_to_home():
            self._say(u"冷启动回首页失败，走 goto_home", "WARN")
            ui.goto_home()
        ui.ensure_kingkong_visible()
        row = ui.kingkong_row()
        if row:
            self._say(u"金刚区行 y=%d~%d（%d 个小图标）"
                      % (row[0], row[1], len(row[2])))
        else:
            self._say(u"未识别到金刚区小图标，仍按公共方法滑动", "WARN")

        # 第一屏找【女性专区】
        b = self._find_icon(FEMALE_ICON)
        if b:
            self._say(u"金刚区第一屏找到【女性专区】%s" % (b,))
            self._tap(b, pause=2.0)
            return self._wait_state("female")

        # 第二屏找【女性专区】
        ui.swipe_kingkong("left", pause=1.8)
        b = self._find_icon(FEMALE_ICON)
        if b:
            self._say(u"金刚区第二屏找到【女性专区】%s" % (b,))
            self._tap(b, pause=2.0)
            return self._wait_state("female")

        # 两屏都没有 → 走【全部频道】-优惠权益-女性专区
        b = self._find_icon(ALL_CHANNELS)
        for _ in range(2):
            if b:
                break
            ui.swipe_kingkong("left", pause=1.8)
            b = self._find_icon(ALL_CHANNELS)
        if not b:
            self._say(u"两屏都没找到【女性专区】，也没找到【全部频道】", "WARN")
            return False
        self._say(u"走兜底入口：点【全部频道】%s" % (b,))
        self._tap(b, pause=2.0)
        ui.sleep(3)                      # 用户要求：全部频道页停留 3s 稳定
        if not self._wait_state("channels"):
            self._say(u"【全部频道】页没稳定，仍尝试点【优惠权益】", "WARN")

        _, nodes = self._snap()
        tab = self._find_text(QUANYI_TAB, clickable=True, nodes=nodes)
        if not tab:
            self._say(u"【全部频道】页没找到【优惠权益】tab", "WARN")
            return False
        self._say(u"点【优惠权益】tab %s" % (tab,))
        self._tap(tab, pause=1.8)
        if not self._wait_state("quanyi", tries=5, pause=1.2):
            self._say(u"优惠权益分类没稳定，仍尝试找【女性专区】", "WARN")

        _, nodes = self._snap()
        ent = self._find_text(FEMALE_ICON, nodes=nodes)
        if not ent:
            self._say(u"优惠权益分类里没找到【女性专区】入口", "WARN")
            return False
        box = self._clickable_container(ent, nodes) or ent
        self._say(u"点优惠权益里的【女性专区】%s（文本 %s）" % (box, ent))
        self._tap(box, pause=2.0)
        return self._wait_state("female")

    # ---------- 弹窗 / 奖励弹窗 ----------
    def _clear_reward(self):
        state, nodes = self._snap()
        if state != "reward":
            return False
        b = (self._find_text(HAPPY_TEXT, clickable=True, nodes=nodes)
             or self._find_text(REWARD_CLOSE, clickable=True, nodes=nodes))
        if not b:
            return False
        self._say(u"奖励弹窗点【开心收下/关闭】%s" % (b,))
        self._tap(b, pause=1.2)
        return True

    def _open_panel(self):
        for k in range(4):
            if self._stopped():
                return False
            state, nodes = self._snap()
            if state == "panel":
                return True
            if state == "verify":
                return False
            if state == "reward":
                self._clear_reward()
                continue
            if state != "female":
                self._say(u"当前不在活动页（%s），尝试恢复" % state, "WARN")
                if not self._ensure_panel():
                    return False
                continue
            b = self._find_text(TASK_ENTRY, clickable=True, nodes=nodes)
            if not b:
                self.ui.sleep(1.5)
                continue
            self._say(u"点【做任务 赚更多惊喜值】%s 第 %d 次" % (b, k + 1))
            self._tap(b, pause=1.5)
            self.ui.sleep(1.5)
            state2, _ = self._snap()
            if state2 == "panel":
                self._say(u"任务弹窗已渲染（第 %d 次读）" % (k + 1))
                return True
        self._say(u"连续 4 次没打开任务弹窗", "WARN")
        return False

    def _ensure_panel(self):
        state, _ = self._snap()
        if state == "panel":
            return True
        if state == "verify":
            self._say(u"停在【京东验证】风控页，需人工点掉", "WARN")
            return False
        if state == "reward":
            self._clear_reward()
            state, _ = self._snap()
        if state == "female":
            return self._open_panel()
        # 落地页 / 其它：先 back 几级找活动页
        for i in range(3):
            if self._stopped():
                return False
            self.ui.back(pause=1.2)
            state, _ = self._snap()
            if state == "female":
                return self._open_panel()
            if state == "panel":
                return True
            if state == "verify":
                return False
        self._say(u"就地恢复失败，重走整条入口链路", "WARN")
        return self._enter() and self._open_panel()

    def _scroll_to_top(self):
        """连续下滑直到签名不再变化，保证每轮从列表顶部开始扫。"""
        same = 0
        for _ in range(MAX_TO_TOP):
            if self._stopped():
                return
            _, nodes = self._snap()
            sig = panel_sig(nodes)
            self._scroll_down()
            _, nodes2 = self._snap()
            if panel_sig(nodes2) == sig:
                same += 1
                if same >= 2:
                    return
            else:
                same = 0

    # ---------- 做任务 ----------
    def _do_one(self, row):
        """点任务 → 确认离开弹窗 → 停留 15~18s → back 一次回弹窗。"""
        self._tap(row["bounds"], pause=1.0)
        self.ui.sleep(1.5)
        state, _ = self._snap()
        if state == "panel":
            # H5 转场那一两帧 / 点击被吞 / 网络失败：重试一次
            self._tap(row["bounds"], pause=1.0)
            self.ui.sleep(2.0)
            state, _ = self._snap()
            if state == "panel":
                self._say(u"点了按钮但弹窗没消失，本次点击可能被吞", "WARN")
                return False
        secs = dwell_seconds()
        self._say(u"任务【%s】按钮【%s】%s，停留 %ds"
                  % (row["title"] or row["key"], row["text"],
                     row["bounds"], secs))
        if not self.ui.sleep(secs):
            return False
        self.ui.back(pause=2.0)
        state2, _ = self._snap()
        if state2 != "panel":
            # 转场帧复核，别直接当成「回不来」
            for _ in range(2):
                self.ui.sleep(1.0)
                state2, _ = self._snap()
                if state2 == "panel":
                    break
            if state2 != "panel":
                self._say(u"浏览后没回到任务弹窗，尝试恢复", "WARN")
                self._ensure_panel()
        return True

    def _do_tasks(self):
        total = 0
        attempts = {}
        for cycle in range(MAX_CYCLES):
            if self._stopped() or total >= MAX_TASKS:
                break
            self._say(u"===== 第 %d 轮：扫描并做任务 =====" % (cycle + 1))
            if not self._ensure_panel():
                break
            self._scroll_to_top()
            done = 0
            blacklist = set()
            failures = {}
            read_fails = 0
            stagnant = 0
            scrolls = 0
            for step in range(MAX_STEPS):
                if self._stopped() or total >= MAX_TASKS:
                    break
                state, nodes = self._snap()
                if not nodes:
                    read_fails += 1
                    if read_fails >= MAX_READ_FAILS:
                        self._say(u"连续 %d 次读不到页面，收尾" % read_fails, "WARN")
                        break
                    self.ui.sleep(1.0)
                    continue
                read_fails = 0
                if state == "verify":
                    self._say(u"停在【京东验证】风控页，停止", "WARN")
                    return total
                if state == "reward":
                    self._clear_reward()
                    state, nodes = self._snap()
                if state != "panel":
                    if not self._ensure_panel():
                        break
                    state, nodes = self._snap()
                    if state != "panel":
                        break
                rows = parse_rows(nodes, "task")
                pick = pick_target(rows, blacklist, attempts)
                if pick:
                    key = pick["key"]
                    ok = self._do_one(pick)
                    attempts[key] = attempts.get(key, 0) + 1
                    if ok:
                        total += 1
                        done += 1
                        failures[key] = 0
                        self._say(u"浏览完成 #%d / 本轮 #%d【%s】"
                                  % (total, done, pick["title"] or key))
                    else:
                        n = failures.get(key, 0) + 1
                        failures[key] = n
                        if n >= MAX_RETRY:
                            blacklist.add(key)
                            self._say(u"任务【%s】连续 %d 次没做成功，本轮拉黑"
                                      % (key, n), "WARN")
                    continue               # 同一屏状态已变，重新解析，不滑动
                # 当前屏没有可做任务 → 上滑一屏
                sig = panel_sig(nodes)
                self._scroll_up()
                _, nodes2 = self._snap()
                if panel_sig(nodes2) == sig:
                    stagnant += 1
                else:
                    stagnant = 0
                scrolls += 1
                if stagnant >= 2 or scrolls >= MAX_SCROLLS:
                    self._say(u"列表已扫到底，本轮没有更多可做任务")
                    break
            self._say(u"第 %d 轮完成浏览 %d 次（累计 %d 次）"
                      % (cycle + 1, done, total))
            if done == 0:
                self._say(u"任务列表已没有可做任务，结束做任务阶段")
                break
        if total >= MAX_TASKS:
            self._say(u"已达总浏览次数上限 %d，收尾" % MAX_TASKS, "WARN")
        return total

    # ---------- 领取奖励 ----------
    def _claim_all(self):
        claimed = 0
        for i in range(MAX_CLAIMS):
            if self._stopped():
                break
            if not self._ensure_panel():
                break
            self._scroll_to_top()
            found = None
            stagnant = 0
            for s in range(MAX_SCROLLS):
                state, nodes = self._snap()
                if state == "verify":
                    return claimed
                if state != "panel":
                    break
                rows = parse_rows(nodes, "claim")
                if rows:
                    found = rows[0]
                    break
                sig = panel_sig(nodes)
                self._scroll_up()
                _, nodes2 = self._snap()
                if panel_sig(nodes2) == sig:
                    stagnant += 1
                else:
                    stagnant = 0
                if stagnant >= 2:
                    break
            if not found:
                self._say(u"没有待领取的【领取奖励】，领奖结束")
                break
            self._say(u"点第 %d 个【领取奖励】%s【%s】"
                      % (i + 1, found["bounds"], found["title"]))
            self._tap(found["bounds"], pause=1.2)
            self.ui.sleep(1.5)
            state, nodes = self._snap()
            if state == "reward":
                self._clear_reward()
                claimed += 1
                continue
            # 弹窗可能还没渲染，再复核一帧
            self.ui.sleep(1.0)
            state, nodes = self._snap()
            if state == "reward":
                self._clear_reward()
            claimed += 1
            self._say(u"领取后页面状态 %s，继续检查下一个" % state)
        else:
            self._say(u"已达领奖个数上限 %d" % MAX_CLAIMS, "WARN")
        return claimed

    # ---------- 入口 ----------
    def run(self, log, stop_event):
        ui = JDUI(driver.get_driver(), log, stop_event)
        self.ui = ui
        self.log = log
        self.stop = stop_event
        self._say(u"设备分辨率 %dx%d" % (ui.W, ui.H))
        if not self._enter():
            self._say(u"没能进入【女性专区】活动页，任务结束", "WARN")
            log.done(u"女性专区 未完成（入口失败）")
            return
        if not self._open_panel():
            self._say(u"没能打开任务弹窗，任务结束", "WARN")
            log.done(u"女性专区 未完成（弹窗失败）")
            return
        total = self._do_tasks()
        claimed = self._claim_all()
        log.done(u"女性专区 完成 %d 次浏览任务，领取 %d 个奖励"
                 % (total, claimed))
