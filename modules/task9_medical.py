# -*- coding: utf-8 -*-
"""任务9【看病买药】：金刚区/全部频道进看病买药 -> 签到领京豆 -> 全场秒杀·天天低价
-> 【领更多京豆】-> 做【浏览Xs】任务，停留 X+4 秒，做完不领取。

入口（三级，与需求一致）：
  1. 京东首页金刚区**第 1 页**找 desc="看病买药"
     （金刚区 = 有【秒杀】那一行，一排 5 个半图标；真机 1080x2340 下这一行 y=440~601，
       看病买药是第 2 格 (194,440,388,601)，点中心 (291,520)）
  2. 第 1 页没有就左滑到**第 2 页**再找
  3. 第 2 页也没有就点第 2 页的【全部频道】
     -> 【发现好物】tab -> 【医疗保健】-> 【看病买药】图标

页面链路：
  看病买药页 -> 点【签到领京豆】（在「天天低价·秒杀」卡片左下角，
                文案 (73,1523,233,1567)，整张卡没有 clickable 祖先，直接点文字中心）
  -> 【全场秒杀·天天低价】页（标记：出现【我的签到日历】）
  -> 点【领更多京豆】（在【我的签到日历】正下方，
                文案 (712,434,946,492)，可点祖先是 (671,401,1036,530)，点中心 (853,465)）
  -> 【做任务赚更多京豆】底部弹层（弹层顶 y≈700，标题 (33,734,451,800)）

任务行结构（真机实测）：
  标题  【天天逛特价2元也包邮】        [181,874][599,935]   多数**没有** (N/M) 进度
  副标题【浏览5s】                    [181,935][291,979]   判定用它
  奖励  【1】+【京豆】
  按钮  【去完成】                    [863,882][1036,973]  贴右

可做任务 = 副标题含【浏览Ns】且按钮是【逛一逛】或【去完成】；停留 (X+4) 秒。
**做完不需要领取**，直接结束。

真机踩过的坑（2026-11-12）：
1. 【签到领京豆】和【领更多京豆】都不是 clickable 节点：
   前者连 clickable 祖先都没有（整张卡不可点），只能点文字中心；
   后者的可点祖先是 (671,401,1036,530)，比文字框大一圈。
2. 【领更多京豆】文案有两处：页面标题是「做任务 领更多京豆」（带空格），
   按钮才是「领更多京豆」，必须**完全相等**匹配，否则会点到标题上。
3. 弹层里有个【领红包】浮层挂在右下角 (935,2040,1067,2172)，
   正好盖住第 7 行【逛外卖频道】的【去完成】(863,2002,1036,2092)。
   所以安全区下界必须收到 2000，让这一行先滚上来再点。
4. 弹层是底部弹层，但 dump 里同时能看到背后秒杀页的节点（y<700 的
   【下场晚8点预告】【0.99秒杀中…】，以及横向滚出屏幕的 x>1080 商品卡）。
   判定任务行必须靠「右侧按钮 + 同行【浏览Ns】」，别用整页子串。
5. 弹层右上角有个【关闭弹窗】(998,695,1047,745)，安全区上界要避开它。
"""
import re

from modules.base import BaseModule
import utils.driver as driver
from utils.jd_ui import JDUI

# ---------- 入口 ----------
MED_DESC = u"看病买药"
ALL_CHANNEL = u"全部频道"
FIND_GOODS = u"发现好物"
MED_TAB = u"医疗保健"
SIGN_IN = u"签到领京豆"          # 看病买药页的签到入口
WP_MARK = u"我的签到日历"        # 全场秒杀·天天低价页独有
MORE_BEAN = u"领更多京豆"        # 要完全相等，页面标题是「做任务 领更多京豆」
PANEL_MARK = u"做任务赚更多京豆"
CLOSE_PANEL = u"关闭弹窗"

# ---------- 任务列表 ----------
BROWSE_BUTTON_TEXTS = (u"逛一逛", u"去完成")
DONE_TEXTS = (u"已完成", u"已领取", u"已结束")
BTN_MIN_X = 700                  # 按钮必须贴右
ROW_TOL = 70                     # 按钮与【浏览Ns】的 y 容差
BROWSE_EXTRA = 4                 # 停留 = X + 4 秒

SAFE_TOP = 820                   # 弹层可点安全区上界（标题栏 y≈734~800 之下）
SAFE_BOTTOM = 2000               # 安全区下界（【领红包】浮层从 y=2040 开始）

MAX_TASKS = 40
MAX_SCROLLS = 8
MAX_NO_PROGRESS = 3
MAX_REENTER = 3
MAX_READ_FAILS = 4

_BROWSE_RE = re.compile(u"浏览\\s*(\\d+)\\s*[sS\u79d2]")
_PROGRESS_RE = re.compile(u"[（(]\\s*\\d+\\s*/\\s*\\d+\\s*[）)]")


# ---------------------------------------------------------------- 纯逻辑
def browse_seconds(x):
    """页面要求 X 秒 -> 实际停留 X + BROWSE_EXTRA。"""
    return int(x) + BROWSE_EXTRA


def parse_task_rows(nodes, btn_min_x=BTN_MIN_X, row_tol=ROW_TOL):
    """把节点配对成任务行。

    只有「右侧按钮（逛一逛/去完成）+ 同一行的【浏览Ns】」才算可做任务，
    所以【去领取】【完成得】这类天然被排除。
    返回 [{'title','secs','cx','cy','btn','btn_bounds'}]，按 cy 升序。
    """
    btns = []
    subs = []
    for n in nodes or []:
        b = n.get("bounds") or (0, 0, 0, 0)
        if b[3] <= b[1] or b[2] <= b[0]:
            continue                       # 屏外/退化节点
        txt = (n.get("text") or "").strip()
        desc = (n.get("desc") or "").strip()
        cx = (b[0] + b[2]) // 2
        cy = (b[1] + b[3]) // 2
        if txt in BROWSE_BUTTON_TEXTS and cx >= btn_min_x:
            btns.append({"text": txt, "cx": cx, "cy": cy, "bounds": b})
            continue
        m = _BROWSE_RE.search(txt) or _BROWSE_RE.search(desc)
        if m:
            subs.append({"secs": int(m.group(1)), "cx": cx, "cy": cy, "bounds": b})
    rows = []
    for b in btns:
        cand = [(abs(s["cy"] - b["cy"]), s) for s in subs
                if abs(s["cy"] - b["cy"]) <= row_tol]
        if not cand:
            continue
        cand.sort(key=lambda t: t[0])
        s = cand[0][1]
        rows.append({"title": _row_title(nodes, b), "secs": s["secs"],
                     "cx": b["cx"], "cy": b["cy"], "btn": b["text"],
                     "btn_bounds": b["bounds"]})
    rows.sort(key=lambda r: r["cy"])
    return rows


def _row_title(nodes, btn, row_tol=ROW_TOL, btn_min_x=BTN_MIN_X):
    """按钮左侧、同一行区域的文字就是任务标题。

    这个弹层多数行**没有** (N/M) 进度，所以不能只靠进度挑。
    同一行上「标题」和副标题【浏览5s】离按钮差不多近，但副标题被 _BROWSE_RE
    排除掉了。

    真机踩过（2026-11-12 第一次跑）：弹层是底部弹层，dump 里同时带着背后秒杀页的
    商品文案，那些文案的 y 正好和任务行撞在一起——第 1 行按钮 cy=927，
    任务标题『天天逛特价2元也包邮』cy=904（差 23），而秒杀卡片的
    『500+条评价』[489,904][676,968] cy=936（差 9），只比距离就会选错，
    日志里任务名变成【500+条评价】，attempted 台账也跟着串行。
    所以排序键改成「有 (N/M) 进度 > 最靠左 > 纵向最近」：
    任务标题一律从 x=181 起排，背后商品文案从 x≈400 起，一判就分开。
    """
    best = None
    for n in nodes or []:
        b = n.get("bounds") or (0, 0, 0, 0)
        if b[3] <= b[1] or b[2] <= b[0]:
            continue
        if ((b[0] + b[2]) // 2) >= btn_min_x:
            continue
        txt = (n.get("text") or "").strip()
        if not txt or _BROWSE_RE.search(txt):
            continue
        if txt in BROWSE_BUTTON_TEXTS or txt in DONE_TEXTS:
            continue
        if len(re.findall(u"[\u4e00-\u9fa5]", txt)) < 2:
            continue
        cy = (b[1] + b[3]) // 2
        if abs(cy - btn["cy"]) > row_tol:
            continue
        score = (0 if _PROGRESS_RE.search(txt) else 1, b[0],
                 abs(cy - btn["cy"]), cy)
        if best is None or score < best[0]:
            best = (score, txt)
    return best[1] if best else u""


def row_sig(rows):
    """任务行签名：标题 + 停留秒数，做完一步签名就变。"""
    return tuple(sorted((r.get("title") or u"") + u"|" + str(r.get("secs"))
                        for r in (rows or [])))


def pick_target(rows, attempted, safe_top=SAFE_TOP, safe_bottom=SAFE_BOTTOM):
    """挑一个可做、没试过、且在安全区里的行。

    返回 (row, reason)：row 非 None 直接点；
    reason='below' 目标在下方要上滑，'above' 在上方要下滑，'none' 没得做了。
    """
    doable = [r for r in (rows or []) if r["title"] not in attempted]
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
    if any(r["btn_bounds"][1] > safe_bottom for r in doable):
        return None, "below"
    return None, "above"


def has_task_panel(nodes):
    """任务弹层是否在场：有弹层标题，或任务行，或【关闭弹窗】。"""
    for n in nodes or []:
        txt = (n.get("text") or "").strip()
        if txt == PANEL_MARK or txt == CLOSE_PANEL:
            return True
        if txt in BROWSE_BUTTON_TEXTS:
            return True
        if _BROWSE_RE.search(txt):
            return True
    return False


def is_medical_page(nodes):
    """看病买药页：有【签到领京豆】入口。"""
    for n in nodes or []:
        if SIGN_IN in (n.get("text") or ""):
            return True
    return False


def is_wp_page(nodes):
    """全场秒杀·天天低价页：有【我的签到日历】。"""
    for n in nodes or []:
        if WP_MARK in (n.get("text") or ""):
            return True
    return False


def find_sign_in(nodes):
    """看病买药页的【签到领京豆】文字节点（整张卡不可点，只能点文字中心）。"""
    for n in nodes or []:
        b = n.get("bounds") or (0, 0, 0, 0)
        if b[3] <= b[1] or b[2] <= b[0]:
            continue
        if SIGN_IN in (n.get("text") or ""):
            return n
    return None


def find_more_bean(nodes):
    """【领更多京豆】按钮。必须完全相等：页面标题是「做任务 领更多京豆」。"""
    for n in nodes or []:
        b = n.get("bounds") or (0, 0, 0, 0)
        if b[3] <= b[1] or b[2] <= b[0]:
            continue
        if (n.get("text") or "").strip() == MORE_BEAN:
            return n
    return None


def clickable_ancestor(nodes, node):
    """包住 node 中心的最小可点节点（【领更多京豆】就靠它找）。

    真机：『领更多京豆』(712,434,946,492) 是普通 TextView，
    可点区域是外面那层 View (671,401,1036,530)。
    """
    b = node.get("bounds") or (0, 0, 0, 0)
    c = ((b[0] + b[2]) // 2, (b[1] + b[3]) // 2)
    best = None
    for n in nodes or []:
        if not n.get("clickable"):
            continue
        nb = n.get("bounds") or (0, 0, 0, 0)
        if not (nb[0] <= c[0] <= nb[2] and nb[1] <= c[1] <= nb[3]):
            continue
        area = (nb[2] - nb[0]) * (nb[3] - nb[1])
        if best is None or area < best[0]:
            best = (area, nb)
    return best[1] if best else None


# ---------------------------------------------------------------- 模块
class Task9Medical(BaseModule):
    name = "看病买药"
    description = ("金刚区/全部频道进【看病买药】→ 签到领京豆 → 全场秒杀·天天低价 → "
                   "【领更多京豆】→ 做【浏览Xs】任务，停留 X+4 秒，不领取")
    icon = "💊"

    def run(self, log, stop_event):
        ui = JDUI(driver.get_driver(), log, stop_event)
        log.write_log("设备分辨率 %dx%d" % (ui.W, ui.H))

        if not self._open_medical(ui, log, cold=True):
            raise RuntimeError("未能进入【看病买药】")
        if stop_event.is_set():
            return
        if not self._open_wp(ui, log):
            raise RuntimeError("【看病买药】页未能点进【签到领京豆】")
        if stop_event.is_set():
            return
        if not self._open_panel(ui, log):
            raise RuntimeError("【全场秒杀·天天低价】页未能打开任务弹层")
        if stop_event.is_set():
            return

        done = self._process_tasks(ui, log, stop_event)
        if stop_event.is_set():
            return
        log.done("看病买药 完成 %d 个浏览任务" % done)

    # ---------- 入口 ----------
    def _open_medical(self, ui, log, cold=False):
        """首页 -> 看病买药 页（金刚区第1页 -> 第2页 -> 全部频道-发现好物-医疗保健）。"""
        if cold:
            if not ui.restart_to_home():
                log.write_log("冷启动回首页失败", "WARN")
                if not ui.goto_home():
                    return False
        else:
            if not ui.goto_home():
                log.write_log("回首页失败", "WARN")
                return False
            ui.swipe_kingkong("right", pause=1.5)     # 先翻回金刚区第 1 页
        ui.ensure_kingkong_visible()

        for page in (1, 2):
            icon, _stable = ui._stable_kingkong_icon(MED_DESC)
            if icon is not None:
                pos = ui.center(icon)
                log.write_log("金刚区第 %d 页命中【%s】%s，点击 (%d,%d)"
                              % (page, MED_DESC, icon["bounds"], pos[0], pos[1]))
                ui.tap(pos, pause=6)
                ui.invalidate()
                if self._wait_medical(ui, log):
                    log.write_log("已进入【看病买药】（金刚区第 %d 页）" % page)
                    return True
                log.write_log("点了金刚区【%s】但没进看病买药页，继续下一级入口" % MED_DESC, "WARN")
            else:
                log.write_log("金刚区第 %d 页没有【%s】" % (page, MED_DESC))
            if page == 1:
                ui.swipe_kingkong("left", pause=2)
                ui.invalidate()

        log.write_log("金刚区两页都没有，走【全部频道】-【发现好物】-【医疗保健】-【看病买药】", "WARN")
        if not self._enter_from_all_channels(ui, log):
            return False
        if self._wait_medical(ui, log):
            log.write_log("已进入【看病买药】（全部频道）")
            return True
        return False

    def _enter_from_all_channels(self, ui, log):
        """全部频道 -> 发现好物 tab -> 医疗保健 -> 看病买药 图标。"""
        nodes = self._nodes(ui)
        if not self._tap_label(ui, log, nodes, ALL_CHANNEL, u"金刚区第2页", pause=4):
            return False
        ui.sleep(2.0)
        ui.invalidate()

        nodes = self._nodes(ui)
        if self._tap_label(ui, log, nodes, FIND_GOODS, u"全部频道页", pause=2.5):
            ui.sleep(2.0)
            ui.invalidate()
            nodes = self._nodes(ui)          # 点完 tab 整页会重绘，必须重读
        else:
            log.write_log("全部频道页没找到【%s】tab，直接找【%s】" % (FIND_GOODS, MED_TAB), "WARN")

        node, nodes = self._reveal_tab(ui, log, nodes, MED_TAB)
        if node is not None:
            self._tap_node(ui, log, nodes, node, MED_TAB, u"全部频道页", pause=2.5)
            ui.sleep(2.5)
            ui.invalidate()
            nodes = self._nodes(ui)          # 点完子 tab 会滚到该区块，必须重读
        else:
            log.write_log("全部频道页没找到【%s】子 tab，直接找【%s】" % (MED_TAB, MED_DESC), "WARN")

        return self._tap_label(ui, log, nodes, MED_DESC, u"全部频道页", pause=6)

    def _find_label(self, nodes, label):
        """文案完全等于 label 的第一个有效节点。"""
        cands = [n for n in nodes or []
                 if (n.get("text") or "").strip() == label
                 or (n.get("desc") or "").strip() == label]
        cands = [n for n in cands
                 if n["bounds"][3] > n["bounds"][1] and n["bounds"][2] > n["bounds"][0]]
        return cands[0] if cands else None

    def _tap_label(self, ui, log, nodes, label, where, pause=4):
        """找文案完全等于 label 的节点，点包含它的最小可点祖先中心。"""
        node = self._find_label(nodes, label)
        if node is None:
            log.write_log("%s 没找到【%s】" % (where, label), "WARN")
            return False
        return self._tap_node(ui, log, nodes, node, label, where, pause)

    def _tap_node(self, ui, log, nodes, node, label, where, pause=4):
        """点节点：自己可点就用自己，否则用包含它的最小可点祖先。"""
        if node.get("clickable"):
            box = node["bounds"]
        else:
            box = clickable_ancestor(nodes, node)
        if box is None:
            box = node["bounds"]
        pos = ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2)
        log.write_log("%s 命中【%s】%s，点击 (%d,%d)" % (where, label, box, pos[0], pos[1]))
        ui.adb_tap(pos, pause=pause)
        ui.invalidate()
        return True

    def _reveal_tab(self, ui, log, nodes, label, anchor_label=FIND_GOODS,
                    max_swipes=6):
        """把横向滚动的子 tab 拉进屏幕，返回 (node, nodes)。

        真机踩过（2026-11-12）：点完【发现好物】后子 tab 行是
        「汽车 / 服饰美妆 / 家电家居 / 3C数码 / 图书文教 / … / 医疗保健 / …」，
        【医疗保健】的 bounds 是 (1441,368,1661,470)，**x 已经超出 1080 屏幕**，
        直接点中心 (1551,419) 是屏幕外坐标，点了没反应。
        更早一点的 dump 里它干脆**整个没渲染**（只渲染了前 5 个可见 tab），
        这时连节点都找不到，所以「找不到」也要滑。

        滑动行的 y：优先用标签自己的 cy；标签没渲染时用锚点（【发现好物】）
        的 cy + 120 —— 真机实测子 tab 行就在主 tab 行下面约 120px。
        真机实测滑 1 次就到位：(1441,368,1661,470) -> (533,368,753,470)。
        """
        node = self._find_label(nodes, label)
        anchor = self._find_label(nodes, anchor_label)
        if node is not None:
            row_y = (node["bounds"][1] + node["bounds"][3]) // 2
        elif anchor is not None:
            row_y = (anchor["bounds"][1] + anchor["bounds"][3]) // 2 + 120
        else:
            row_y = 520
        swipes = 0
        while swipes < max_swipes:
            on_screen = (node is not None
                         and node["bounds"][0] >= 0
                         and node["bounds"][2] <= ui.W)
            if on_screen:
                break
            if node is None:
                log.write_log("子 tab【%s】没渲染出来，第 %d 次左滑 y=%d"
                              % (label, swipes + 1, row_y))
            else:
                log.write_log("子 tab【%s】在屏外 %s，第 %d 次左滑 y=%d"
                              % (label, node["bounds"], swipes + 1, row_y))
            ui.adb_swipe(ui.sx(950), row_y, ui.sx(150), row_y, duration=500)
            ui.sleep(1.5)
            ui.invalidate()
            nodes = self._nodes(ui)
            node = self._find_label(nodes, label)
            if node is not None:
                row_y = (node["bounds"][1] + node["bounds"][3]) // 2
            swipes += 1
        if node is None:
            log.write_log("子 tab【%s】滑 %d 次仍没出现" % (label, swipes), "WARN")
            return None, nodes
        if node["bounds"][0] < 0 or node["bounds"][2] > ui.W:
            log.write_log("子 tab【%s】滑 %d 次仍在屏外 %s"
                          % (label, swipes, node["bounds"]), "WARN")
            return None, nodes
        if swipes:
            log.write_log("子 tab【%s】已滑进屏幕 %s" % (label, node["bounds"]))
        return node, nodes

    def _wait_medical(self, ui, log, tries=8):
        """等【看病买药】页：出现【签到领京豆】。"""
        for _ in range(tries):
            nodes = self._nodes(ui)
            if nodes and is_medical_page(nodes):
                return True
            ui.sleep(1.5)
        log.write_log("等待【看病买药】页超时", "WARN")
        return False

    # ---------- 签到领京豆 ----------
    def _open_wp(self, ui, log):
        """看病买药页点【签到领京豆】进【全场秒杀·天天低价】页。"""
        nodes = self._nodes(ui)
        node = find_sign_in(nodes)
        if node is None:
            log.write_log("看病买药页没找到【%s】，下滑一屏再找" % SIGN_IN, "WARN")
            ui.adb_swipe(ui.W // 2, ui.sy(1900), ui.W // 2, ui.sy(1500), duration=400)
            ui.sleep(1.5)
            ui.invalidate()
            nodes = self._nodes(ui)
            node = find_sign_in(nodes)
        if node is None:
            log.write_log("看病买药页始终没找到【%s】" % SIGN_IN, "WARN")
            return False

        box = node["bounds"]
        pos = ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2)
        log.write_log("命中【%s】%s，点击 (%d,%d)" % (node["text"], box, pos[0], pos[1]))
        ui.adb_tap(pos, pause=3.0)
        ui.sleep(3.0)
        ui.invalidate()
        if self._wait_wp(ui, log):
            log.write_log("已进入【全场秒杀·天天低价】")
            return True
        # 兜底：文字中心有时点在文字缝里，往上挪 60px 点图标
        pos2 = (pos[0], pos[1] - 60)
        log.write_log("点【%s】后没进秒杀页，改点 (%d,%d)" % (SIGN_IN, pos2[0], pos2[1]), "WARN")
        ui.adb_tap(pos2, pause=3.0)
        ui.sleep(3.0)
        ui.invalidate()
        if self._wait_wp(ui, log):
            log.write_log("已进入【全场秒杀·天天低价】（兜底点击）")
            return True
        return False

    def _wait_wp(self, ui, log, tries=8):
        """等【全场秒杀·天天低价】页：出现【我的签到日历】。"""
        for _ in range(tries):
            nodes = self._nodes(ui)
            if nodes and is_wp_page(nodes):
                return True
            ui.sleep(1.5)
        log.write_log("等待【全场秒杀·天天低价】页超时", "WARN")
        return False

    # ---------- 任务弹层 ----------
    def _open_panel(self, ui, log):
        """点【我的签到日历】正下方的【领更多京豆】打开任务弹层。"""
        nodes = self._nodes(ui)
        node = find_more_bean(nodes)
        if node is None:
            log.write_log("秒杀页没找到【%s】按钮" % MORE_BEAN, "WARN")
            return False
        box = clickable_ancestor(nodes, node) or node["bounds"]
        pos = ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2)
        log.write_log("命中【%s】%s，可点区 %s，点击 (%d,%d)"
                      % (node["text"], node["bounds"], box, pos[0], pos[1]))
        ui.adb_tap(pos, pause=2.0)
        ui.sleep(3.0)
        ui.invalidate()
        if self._wait_panel(ui, log):
            log.write_log("【%s】任务弹层已打开" % PANEL_MARK)
            return True
        log.write_log("点了【%s】没弹出任务列表，再点一次" % MORE_BEAN, "WARN")
        ui.adb_tap(pos, pause=2.0)
        ui.sleep(3.0)
        ui.invalidate()
        if self._wait_panel(ui, log):
            log.write_log("【%s】任务弹层已打开（第二次点击）" % PANEL_MARK)
            return True
        return False

    def _wait_panel(self, ui, log, tries=8):
        for _ in range(tries):
            nodes = self._nodes(ui)
            if nodes and has_task_panel(nodes):
                return True
            ui.sleep(1.5)
        return False

    # ---------- 做任务 ----------
    def _process_tasks(self, ui, log, stop_event):
        attempted = set()
        done = 0
        scrolls = 0
        read_fails = 0
        reenter = 0

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

            if not has_task_panel(nodes):
                log.write_log("任务弹层不见了，先试轻量重开", "WARN")
                if not self._recover_panel(ui, log):
                    if reenter >= MAX_REENTER:
                        log.write_log("任务弹层反复丢失，重进次数用尽，收尾", "WARN")
                        break
                    reenter += 1
                    log.write_log("轻量重开失败，第 %d 次整链重进" % reenter, "WARN")
                    if not self._reenter(ui, log):
                        break
                continue

            rows = parse_task_rows(nodes)
            row, reason = pick_target(rows, attempted)
            if row is None:
                if reason == "none":
                    log.write_log("任务列表里已没有可做任务")
                    break
                if scrolls >= MAX_SCROLLS:
                    log.write_log("滚动 %d 次仍没有可点任务，收尾" % scrolls, "WARN")
                    break
                scrolls += 1
                self._scroll_panel(ui, log, reason)
                continue

            scrolls = 0
            attempted.add(row["title"])
            dwell = browse_seconds(row["secs"])
            log.write_log("任务【%s】按钮【%s】%s，停留 %ds"
                          % (row["title"], row["btn"], row["btn_bounds"], dwell))
            ui.adb_tap((row["cx"], row["cy"]), pause=1.5)
            ui.invalidate()
            ui.sleep(dwell)
            ui.back(pause=2.0)
            ui.sleep(1.0)
            ui.invalidate()

            nodes = self._nodes(ui)
            if not nodes:
                nodes = self._nodes(ui, tries=5, pause=2.5)
            if not has_task_panel(nodes):
                log.write_log("浏览后没回到任务弹层，先试轻量重开", "WARN")
                if not self._recover_panel(ui, log):
                    if reenter >= MAX_REENTER:
                        log.write_log("回不到任务弹层，重进次数用尽，收尾", "WARN")
                        break
                    reenter += 1
                    log.write_log("轻量重开失败，第 %d 次整链重进" % reenter, "WARN")
                    if not self._reenter(ui, log):
                        break
                    continue
                nodes = self._nodes(ui)

            after = parse_task_rows(nodes)
            if row["title"] not in [r["title"] for r in after]:
                done += 1
                log.write_log("浏览完成 #%d（可做任务 %d -> %d）"
                              % (done, len(rows), len(after)))
            else:
                log.write_log("任务【%s】做完但列表没变，换下一个" % row["title"], "WARN")

        return done

    def _scroll_panel(self, ui, log, reason):
        """在弹层里滚动任务列表。

        x 用屏幕中线：右下角 (935,2040,1067,2172) 挂着【领红包】浮层，
        贴着右边滑会把它拖出来。
        """
        x = ui.W // 2
        if reason == "below":
            log.write_log("目标任务在安全区下方，列表上滑")
            ui.adb_swipe(x, ui.sy(2000), x, ui.sy(1500), duration=400)
        else:
            log.write_log("目标任务在安全区上方，列表下滑")
            ui.adb_swipe(x, ui.sy(1500), x, ui.sy(2000), duration=400)
        ui.sleep(1.4)
        ui.invalidate()

    def _panel_sig(self, ui):
        """弹层指纹：任务行，用来判断滚动有没有效果。"""
        nodes = self._nodes(ui, tries=1)
        if not nodes:
            return None
        return row_sig(parse_task_rows(nodes))

    def _recover_panel(self, ui, log):
        """弹层丢了之后先试「轻量重开」，避免动辄整链重进。

        顺序：
          1. 弹层本来就在 -> 直接 True；
          2. 还能看到【领更多京豆】-> 点它重开；
          3. 否则 back 退一步再看，最多两次。
        """
        nodes = self._nodes(ui)
        if nodes and has_task_panel(nodes):
            return True
        node = find_more_bean(nodes) if nodes else None
        if node is not None:
            box = clickable_ancestor(nodes, node) or node["bounds"]
            pos = ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2)
            log.write_log("还在秒杀页，点【%s】重开弹层 (%d,%d)"
                          % (node["text"], pos[0], pos[1]))
            ui.adb_tap(pos, pause=2.0)
            ui.sleep(3.0)
            ui.invalidate()
            if self._wait_panel(ui, log, tries=5):
                return True
        for i in range(2):
            ui.back(pause=2.0)
            ui.invalidate()
            nodes = self._nodes(ui)
            if nodes and has_task_panel(nodes):
                log.write_log("返回 %d 次后弹层又出现了" % (i + 1))
                return True
            node = find_more_bean(nodes) if nodes else None
            if node is not None:
                box = clickable_ancestor(nodes, node) or node["bounds"]
                pos = ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2)
                log.write_log("退回秒杀页，点【%s】重开弹层" % node["text"])
                ui.adb_tap(pos, pause=2.0)
                ui.sleep(3.0)
                ui.invalidate()
                if self._wait_panel(ui, log, tries=5):
                    return True
        log.write_log("轻量重开失败（当前页不是秒杀页）", "WARN")
        return False

    def _reenter(self, ui, log):
        """整链重进：首页 -> 看病买药 -> 签到领京豆 -> 领更多京豆弹层。"""
        if not self._open_medical(ui, log):
            return False
        if not self._open_wp(ui, log):
            return False
        return self._open_panel(ui, log)

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
