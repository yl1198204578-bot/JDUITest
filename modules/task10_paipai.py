# -*- coding: utf-8 -*-
"""任务10【拍拍二手】：金刚区/全部频道进拍拍二手 -> 【自营】tab -> 【赚更多京豆】
-> 做【浏览Xs可领】任务，停留 X+4 秒 -> 逐个【领取】奖励（间隔 1s）。

入口（三级，与需求一致）：
  1. 京东首页金刚区**第 1 页**找 desc="拍拍二手"
     （金刚区 = 有【秒杀】那一行，一排 5 个半图标；真机 1080x2340 下这一行 y=440~601）
  2. 第 1 页没有就左滑到**第 2 页**再找
  3. 第 2 页也没有就点第 2 页的【全部频道】
     -> 【发现好物】tab -> 二级 tab 横滑到【二手】-> 页面底部【二手】分组里的【拍拍二手】

页面链路：
  拍拍二手页（等 3s 稳定）
  -> 点【自营】tab（顶部 tab 行第 5 个左右，带红色 % 角标；切完等 5s）
  -> 点【每日领京豆】正下方的【赚更多京豆】（粉色按钮，真机 (46,1343,500,1423)）
  -> 【做任务领京豆】底部弹层（橙色标题栏 y≈1005~1156）

任务行结构（真机实测，弹层叠加在自营页上，dump 里两页节点混在一起）：
  标题  【逛便宜包邮频道（0/1）】     [203,1426][739,1475]   一定带 (N/M) 进度
  副标题【领最高3000京豆】+【，浏览10s可领】 [431,1492][646,1533]   判定用它
  奖励  【+1】
  按钮  【去完成】                   [814,1442][1031,1525]   贴右
  做完后按钮变【领取】-> 点完变【已完成】

可做任务 = 副标题含【浏览Ns可领】且按钮是【逛一逛】/【去完成】。
弹层里第一行【分享好友助力（0/11）】按钮也是【去完成】，但副标题是
「每邀一位好友助力领京豆」（没有浏览Ns）——按需求**必须排除**，
parse_task_rows 靠「按钮 + 同行浏览Ns」配对天然排掉它。

真机踩过的坑（2026-11-12）：
1. 金刚区**会个性化重排**：同一天里【拍拍二手】先后出现在
   第 2 页 (867,763,1080,924) 和 第 2 页 (651,601,867,762)，
   第 1 页也可能有。只按 desc 找，绝不写死坐标。
2. 【全部频道】页刚打开时 page_source 只有 **12KB 骨架**（18 个节点），
   必须轮询到出现【发现好物】且字符数 > 6 万才算渲染完。
3. 【发现好物】的二级 tab 行是**横向滚动**的：点完 tab 后
   【二手】bounds 是 (1828,368,1977,470)，x 全在 1080 屏幕外，
   直接点 (1902,419) 没反应。横滑 y=419 **2 次**才到 (921,368,1067,470)。
4. 点完【二手】二级 tab，页面会自动滚到【二手】分组（列表最底部），
   【拍拍二手】文字在 (77,2169,2316)，可点祖先 (55,2070,253,2216)，
   中心 (154,2143) —— 已经很贴近底部导航（y>=2169），所以点祖先框中心而不是
   文字中心（文字中心 y=2192 会落到导航条上）。
5. 【赚更多京豆】文案有两处风险：自营页是按钮，弹层打开后背后那份**仍在 dump 里
   且 clk=True**。所以「弹层在不在」绝不能用【赚更多京豆】判断，
   要用【做任务领京豆】标题或「浏览Ns + 按钮」组合。
6. 弹层里任务行背后是自营页的商品卡文案（y 和任务行撞在一起），
   选标题必须「有 (N/M) 进度 > 纵向最近」，否则会把『手机』当任务名。
7. 任务跳转的落地页是【特价/9.9包邮】频道页，**back 一次**就回弹层，
   不像领水滴要穿多级。
8. 弹层右上角挂着一个【直播回放】视频小窗（约 873,1264-1032,1572），
   正好压住第 1、2 行【去完成】按钮的右半部分 —— 按钮中心 (922,1281)/(922,1483)
   都在小窗里，点下去是打开直播不是做任务。它是原生视频浮层，
   **XML 里连节点都没有**，只能按坐标拖；而且必须用 `input draganddrop`
   （长按拖拽），`input swipe` 会被识别成列表滚动。拖到顶部后小窗消失，
   前两行按钮完整可见。
"""
import re

from modules.base import BaseModule
import utils.driver as driver
from utils.jd_ui import JDUI

# ---------- 入口 ----------
PP_DESC = u"拍拍二手"
ALL_CHANNEL = u"全部频道"
FIND_GOODS = u"发现好物"
USED_TAB = u"二手"
SELF_TAB = u"自营"               # 拍拍二手页顶部 tab
SELF_MARK = u"每日领京豆"        # 自营 tab 页独有卡片
MORE_BEAN = u"赚更多京豆"        # 卡片正下方的粉色按钮
PANEL_MARK = u"做任务领京豆"

# ---------- 任务列表 ----------
BROWSE_BUTTON_TEXTS = (u"逛一逛", u"去完成")
CLAIM_TEXTS = (u"领取",)
DONE_TEXTS = (u"已完成", u"已领取", u"已结束")
BTN_MIN_X = 700                  # 按钮必须贴右
ROW_TOL = 70                     # 按钮与【浏览Ns可领】的 y 容差
BROWSE_EXTRA = 4                 # 停留 = X + 4 秒

SAFE_TOP = 1180                  # 弹层可点安全区上界（橙色标题栏 y≈1005~1156 之下）
SAFE_BOTTOM = 2335               # 安全区下界（最后一行领取按钮 y2=2331）

PP_PAGE_WAIT = 3.0               # 需求：进拍拍二手页等 3s 稳定
SELF_TAB_WAIT = 5.0              # 需求：切【自营】tab 后等 5s 稳定

# 【直播回放】视频小窗：原生浮层，XML 里**没有任何节点**（text/desc 全空），
# 只能按坐标拖。真机 1080x2340 实测约 (873,1264)-(1032,1572)。
LIVE_FLOAT_CENTER = (952, 1418)  # 小窗中心（落在第 1、2 行任务之间，不会误触按钮）
LIVE_FLOAT_TOP = (952, 210)      # 拖到屏幕顶部
LIVE_FLOAT_DURATION = 1500       # draganddrop 时长（太短会被当成 fling）
TAB_REVEAL_SWIPES = 6            # 二级 tab 最多横滑次数
LIST_SCROLL_TRIES = 4            # 找【赚更多京豆】时最多上下滑次数

MAX_TASKS = 40
MAX_SCROLLS = 8
MAX_REENTER = 3
MAX_READ_FAILS = 4
MAX_RETRY = 1                    # 单个任务最多重试次数（首次点击可能被弹层动画吞）
MAX_CLAIM_CLICKS = 40
MAX_CLAIM_SCROLLS = 4
CLAIM_WAIT = 1.0                 # 需求：点【领取】后等 1s 再点下一个

_BROWSE_RE = re.compile(u"浏览\\s*(\\d+)\\s*[sS\u79d2]")
_PROGRESS_RE = re.compile(u"[（(]\\s*\\d+\\s*/\\s*\\d+\\s*[）)]")


# ---------------------------------------------------------------- 纯逻辑
def browse_seconds(x):
    """页面要求 X 秒 -> 实际停留 X + BROWSE_EXTRA。"""
    return int(x) + BROWSE_EXTRA


def parse_task_rows(nodes, btn_min_x=BTN_MIN_X, row_tol=ROW_TOL):
    """把节点配对成任务行。

    只有「右侧按钮（逛一逛/去完成）+ 同一行的【浏览Ns可领】」才算可做任务，
    所以【分享好友助力】（无浏览）、【领取】、【已完成】天然被排除。
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

    真机踩过（2026-11-12）：弹层是覆盖层，dump 里同时带着背后自营页的节点。
    第 2 行按钮 cy=1483，任务标题『逛便宜包邮频道（0/1）』cy=1450（差 33），
    背后自营页的分类 tab『手机』[195,1475][286,1607] cy=1541（差 57）。
    只按距离还好，但为了稳，排序键是
    「有 (N/M) 进度 > 纵向最近 > 最靠左」：
    弹层里每个任务标题都带 (N/M)，背后文案一个都没有，一判就分开。
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
        if txt in BROWSE_BUTTON_TEXTS or txt in DONE_TEXTS or txt in CLAIM_TEXTS:
            continue
        if len(re.findall(u"[\u4e00-\u9fa5]", txt)) < 2:
            continue
        cy = (b[1] + b[3]) // 2
        if abs(cy - btn["cy"]) > row_tol:
            continue
        score = (0 if _PROGRESS_RE.search(txt) else 1,
                 abs(cy - btn["cy"]), b[0], cy)
        if best is None or score < best[0]:
            best = (score, txt)
    return best[1] if best else u""


def row_sig(rows):
    """任务行签名：标题 + 停留秒数，做完一步签名就变。"""
    return tuple(sorted((r.get("title") or u"") + u"|" + str(r.get("secs"))
                        for r in (rows or [])))


def _row_has_progress(nodes, btn_bounds, btn_cy, row_tol=ROW_TOL):
    """按钮左侧同一行是否有 (N/M) 进度标题。"""
    for n in nodes or []:
        b = n.get("bounds") or (0, 0, 0, 0)
        if b[3] <= b[1] or b[2] <= b[0]:
            continue
        if b[2] > btn_bounds[0] + 30:
            # 真机：标题『每日签到领现金（1/1）』(203,2212,816,2262) 的右边缘
            # 比【领取】按钮 (814,2248,1031,2331) 的左边缘还大 2px，
            # 严格比较会把这一行的领取按钮整个漏掉。留 30px 重叠容差。
            continue
        if abs(((b[1] + b[3]) // 2) - btn_cy) > row_tol:
            continue
        if _PROGRESS_RE.search((n.get("text") or "").strip()):
            return True
    return False


def parse_claim_buttons(nodes, btn_min_x=BTN_MIN_X, row_tol=ROW_TOL):
    """任务行右侧的【领取】按钮，按 y 从上到下。

    三个条件同时满足才算：
      1. 文案完全等于【领取】且 clickable
      2. 贴右（x >= btn_min_x），和【去完成】在同一列
      3. **同一行左侧有带 (N/M) 进度的任务标题**

    第 3 条是关键：自营页背后还有【查余额】等可点节点，
    用「同行有 (N/M) 标题」把它们区分开。
    """
    out = []
    for n in nodes or []:
        b = n.get("bounds") or (0, 0, 0, 0)
        if b[3] <= b[1] or b[2] <= b[0]:
            continue
        if (n.get("text") or "").strip() not in CLAIM_TEXTS:
            continue
        if not n.get("clickable"):
            continue
        cx = (b[0] + b[2]) // 2
        cy = (b[1] + b[3]) // 2
        if cx < btn_min_x:
            continue
        if not _row_has_progress(nodes, b, cy, row_tol):
            continue
        out.append({"text": (n.get("text") or "").strip(), "cx": cx, "cy": cy,
                    "bounds": b})
    out.sort(key=lambda r: r["cy"])
    return out


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
    """任务弹层是否在场：有弹层标题，或任务行（浏览Ns / 逛一逛 / 去完成）。

    注意不能用【赚更多京豆】判断——弹层打开后背后自营页那份仍在 dump 里。
    """
    for n in nodes or []:
        txt = (n.get("text") or "").strip()
        if txt == PANEL_MARK:
            return True
        if txt in BROWSE_BUTTON_TEXTS:
            return True
        if _BROWSE_RE.search(txt):
            return True
    return False


def find_self_tab(nodes):
    """拍拍二手页顶部 tab 行的【自营】。完全相等 + y 在 tab 行范围内。"""
    for n in nodes or []:
        if (n.get("text") or "").strip() != SELF_TAB:
            continue
        b = n.get("bounds") or (0, 0, 0, 0)
        if b[3] <= b[1] or b[2] <= b[0]:
            continue
        cy = (b[1] + b[3]) // 2
        if 250 <= cy <= 560:
            return n
    return None


def is_pp_page(nodes):
    """拍拍二手页：顶部 tab 行里有【自营】。"""
    return find_self_tab(nodes) is not None


def is_self_page(nodes):
    """【自营】tab 页：出现【每日领京豆】卡片或【赚更多京豆】按钮。"""
    for n in nodes or []:
        t = (n.get("text") or "").strip()
        if t == SELF_MARK or t == MORE_BEAN:
            return True
    return False


def find_more_bean(nodes):
    """【赚更多京豆】按钮（在【每日领京豆】正下方，粉色）。完全相等匹配。"""
    for n in nodes or []:
        b = n.get("bounds") or (0, 0, 0, 0)
        if b[3] <= b[1] or b[2] <= b[0]:
            continue
        if (n.get("text") or "").strip() == MORE_BEAN:
            return n
    return None


def clickable_ancestor(nodes, node):
    """包住 node 中心的最小可点节点。

    真机：拍拍二手页【自营】文字 (836,378,975,432) 不可点，
    可点区域是外面那层 (807,225,1003,439)；
    全部频道页【拍拍二手】文字 (77,2169,231,2216) 的可点区是 (55,2070,253,2216)。
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
class Task10Paipai(BaseModule):
    name = "拍拍二手"
    description = ("金刚区/全部频道进【拍拍二手】→【自营】tab →【赚更多京豆】→ "
                   "做【浏览Xs可领】任务停留 X+4 秒 → 逐个【领取】奖励（间隔 1s）")
    icon = "♻"

    def run(self, log, stop_event):
        ui = JDUI(driver.get_driver(), log, stop_event)
        log.write_log("设备分辨率 %dx%d" % (ui.W, ui.H))

        if not self._open_pp(ui, log, cold=True):
            raise RuntimeError("未能进入【拍拍二手】")
        if stop_event.is_set():
            return
        if not self._open_self(ui, log):
            raise RuntimeError("【拍拍二手】页未能切到【自营】tab")
        if stop_event.is_set():
            return
        if not self._open_panel(ui, log):
            raise RuntimeError("【自营】页未能打开【赚更多京豆】任务弹层")
        if stop_event.is_set():
            return
        # 弹层刚展开时列表还在做动画，立刻点第一行会被吞掉（真机跑 #1 踩过）
        ui.sleep(2.0)

        done = self._process_tasks(ui, log, stop_event)
        if stop_event.is_set():
            return
        claimed = self._claim_all(ui, log, stop_event)
        log.done("拍拍二手 完成 %d 个浏览任务，领取 %d 次奖励" % (done, claimed))

    # ---------- 入口 ----------
    def _open_pp(self, ui, log, cold=False):
        """首页 -> 拍拍二手页（金刚区第1页 -> 第2页 -> 全部频道-发现好物-二手）。"""
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
            icon, _stable = ui._stable_kingkong_icon(PP_DESC)
            if icon is not None:
                pos = ui.center(icon)
                log.write_log("金刚区第 %d 页命中【%s】%s，点击 (%d,%d)"
                              % (page, PP_DESC, icon["bounds"], pos[0], pos[1]))
                ui.tap(pos, pause=3.0)
                ui.sleep(PP_PAGE_WAIT)                # 需求：进页面等 3s 稳定
                ui.invalidate()
                if self._wait_pp(ui, log):
                    log.write_log("已进入【拍拍二手】（金刚区第 %d 页）" % page)
                    return True
                log.write_log("点了金刚区【%s】但没进拍拍二手页，继续下一级入口"
                              % PP_DESC, "WARN")
            else:
                log.write_log("金刚区第 %d 页没有【%s】" % (page, PP_DESC))
            if page == 1:
                ui.swipe_kingkong("left", pause=2)
                ui.invalidate()

        log.write_log("金刚区两页都没有，走【全部频道】-【发现好物】-【二手】-【拍拍二手】",
                      "WARN")
        if not self._enter_from_all_channels(ui, log):
            return False
        ui.sleep(PP_PAGE_WAIT)                        # 需求：进页面等 3s 稳定
        if self._wait_pp(ui, log):
            log.write_log("已进入【拍拍二手】（全部频道）")
            return True
        return False

    def _enter_from_all_channels(self, ui, log):
        """全部频道 -> 发现好物 tab -> 二级 tab【二手】-> 【拍拍二手】图标。"""
        nodes = self._nodes(ui, tries=1)
        if not self._tap_label(ui, log, nodes, ALL_CHANNEL, u"金刚区第2页", pause=4):
            return False
        # 全部频道页刚打开时 page_source 只有 12KB 骨架，必须等渲染完
        nodes = self._wait_labels(ui, log, (FIND_GOODS,), u"全部频道页", tries=12)
        if not nodes:
            return False

        if self._tap_label(ui, log, nodes, FIND_GOODS, u"全部频道页", pause=2.5):
            nodes = self._wait_labels(ui, log, (USED_TAB,), u"发现好物 tab", tries=10)
            if not nodes:
                return False
        else:
            log.write_log("全部频道页没找到【%s】tab，直接找【%s】"
                          % (FIND_GOODS, USED_TAB), "WARN")

        node, nodes = self._reveal_tab(ui, log, nodes, USED_TAB)
        if node is None:
            log.write_log("二级 tab【%s】没露出来，试竖滑到底部找【%s】"
                          % (USED_TAB, PP_DESC), "WARN")
        else:
            self._tap_node(ui, log, nodes, node, USED_TAB, u"全部频道页", pause=2.5)
            ui.sleep(2.0)
            ui.invalidate()
            nodes = self._nodes(ui, tries=1)

        # 点完【二手】页面会自动滚到【二手】分组；万一没有就竖滑到底部
        pp = self._find_label(nodes, PP_DESC)
        tries = 0
        while pp is None and tries < LIST_SCROLL_TRIES:
            tries += 1
            log.write_log("全部频道页没看到【%s】，第 %d 次上滑" % (PP_DESC, tries))
            ui.adb_swipe(ui.W // 2, ui.sy(1900), ui.W // 2, ui.sy(900), duration=500)
            ui.sleep(1.8)
            ui.invalidate()
            nodes = self._nodes(ui, tries=1)
            pp = self._find_label(nodes, PP_DESC)
        if pp is None:
            log.write_log("全部频道页始终没找到【%s】" % PP_DESC, "WARN")
            return False
        return self._tap_node(ui, log, nodes, pp, PP_DESC, u"全部频道页", pause=3.0)

    def _find_label(self, nodes, label):
        """文案完全等于 label 的有效节点（多个时取 y 最小的那个）。

        【发现好物】在全部频道页有两处：一级 tab（cy≈301）和区块标题（cy≈523），
        取最上面那个才是可点的 tab。
        """
        cands = [n for n in nodes or []
                 if (n.get("text") or "").strip() == label
                 or (n.get("desc") or "").strip() == label]
        cands = [n for n in cands
                 if n["bounds"][3] > n["bounds"][1] and n["bounds"][2] > n["bounds"][0]]
        if not cands:
            return None
        cands.sort(key=lambda n: (n["bounds"][1], n["bounds"][0]))
        return cands[0]

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
                    max_swipes=TAB_REVEAL_SWIPES):
        """把横向滚动的二级 tab 拉进屏幕，返回 (node, nodes)。

        真机踩过（2026-11-12）：点完【发现好物】后二级 tab 行是
        「图书文教 / 发现 / 工业五金 / 医疗保健 / 超市 / 二手」，
        【二手】bounds 是 (1828,368,1977,470)，**x 全在 1080 屏幕外**，
        直接点中心 (1902,419) 是屏幕外坐标，点了没反应。
        横滑 2 次后到 (921,368,1067,470)。

        滑动行的 y：优先用标签自己的 cy；标签没渲染时用锚点（【发现好物】）
        的 cy + 120 —— 真机实测二级 tab 行就在主 tab 行下面约 120px。
        """
        node = self._find_label(nodes, label)
        anchor = self._find_label(nodes, anchor_label)
        if node is not None:
            row_y = (node["bounds"][1] + node["bounds"][3]) // 2
        elif anchor is not None:
            row_y = (anchor["bounds"][1] + anchor["bounds"][3]) // 2 + 120
        else:
            row_y = 419
        swipes = 0
        while swipes < max_swipes:
            on_screen = (node is not None
                         and node["bounds"][0] >= 0
                         and node["bounds"][2] <= ui.W)
            if on_screen:
                break
            if node is None:
                log.write_log("二级 tab【%s】没渲染出来，第 %d 次左滑 y=%d"
                              % (label, swipes + 1, row_y))
            else:
                log.write_log("二级 tab【%s】在屏外 %s，第 %d 次左滑 y=%d"
                              % (label, node["bounds"], swipes + 1, row_y))
            ui.adb_swipe(ui.sx(950), row_y, ui.sx(120), row_y, duration=500)
            ui.sleep(1.5)
            ui.invalidate()
            nodes = self._nodes(ui, tries=1)
            node = self._find_label(nodes, label)
            if node is not None:
                row_y = (node["bounds"][1] + node["bounds"][3]) // 2
            swipes += 1
        if node is None:
            log.write_log("二级 tab【%s】滑 %d 次仍没出现" % (label, swipes), "WARN")
            return None, nodes
        if node["bounds"][0] < 0 or node["bounds"][2] > ui.W:
            log.write_log("二级 tab【%s】滑 %d 次仍在屏外 %s"
                          % (label, swipes, node["bounds"]), "WARN")
            return None, nodes
        if swipes:
            log.write_log("二级 tab【%s】已滑进屏幕 %s" % (label, node["bounds"]))
        return node, nodes

    def _wait_labels(self, ui, log, labels, where, tries=10, pause=1.2):
        """轮询直到 dump 里出现 labels 里任意一个文案（且页面不是骨架）。"""
        for i in range(tries):
            nodes = self._nodes(ui, tries=1)
            if nodes:
                texts = [(n.get("text") or "").strip() for n in nodes]
                texts += [(n.get("desc") or "").strip() for n in nodes]
                if any(l in texts for l in labels) and len(nodes) > 40:
                    return nodes
            ui.sleep(pause)
        log.write_log("%s 等 %d 次仍未渲染出 %s" % (where, tries, u"/".join(labels)), "WARN")
        return self._nodes(ui, tries=2)

    def _wait_pp(self, ui, log, tries=8):
        """等拍拍二手页：顶部 tab 行出现【自营】。"""
        for _ in range(tries):
            nodes = self._nodes(ui)
            if nodes and is_pp_page(nodes):
                return True
            ui.sleep(1.5)
        log.write_log("等待【拍拍二手】页超时", "WARN")
        return False

    # ---------- 自营 tab ----------
    def _open_self(self, ui, log):
        """点顶部 tab 行的【自营】，切完等 5s 稳定。"""
        nodes = self._nodes(ui)
        node = find_self_tab(nodes)
        if node is None:
            log.write_log("拍拍二手页没找到【%s】tab，横滑 tab 行再找" % SELF_TAB, "WARN")
            row_y = 405
            for i in range(TAB_REVEAL_SWIPES):
                ui.adb_swipe(ui.sx(950), row_y, ui.sx(150), row_y, duration=500)
                ui.sleep(1.5)
                ui.invalidate()
                nodes = self._nodes(ui, tries=1)
                node = find_self_tab(nodes)
                if node is not None:
                    log.write_log("横滑 %d 次后出现【%s】%s"
                                  % (i + 1, SELF_TAB, node["bounds"]))
                    break
        if node is None:
            log.write_log("始终没找到【%s】tab" % SELF_TAB, "WARN")
            return False

        box = clickable_ancestor(nodes, node) or node["bounds"]
        # 点**文字中心**：文字一定落在可点祖先内，比点祖先框中心更准
        # （祖先框 (419,225,662,439) 中心 y=332 落在图标上半部）
        pos = ((node["bounds"][0] + node["bounds"][2]) // 2,
               (node["bounds"][1] + node["bounds"][3]) // 2)
        log.write_log("命中【%s】tab %s，可点区 %s，点击 (%d,%d)"
                      % (SELF_TAB, node["bounds"], box, pos[0], pos[1]))
        ui.adb_tap(pos, pause=2.0)
        ui.sleep(SELF_TAB_WAIT)                       # 需求：切完等 5s 稳定
        ui.invalidate()
        if self._wait_self(ui, log):
            log.write_log("已切到【%s】tab" % SELF_TAB)
            return True
        log.write_log("点了【%s】tab 没看到【%s】，再点一次" % (SELF_TAB, SELF_MARK), "WARN")
        ui.adb_tap(pos, pause=2.0)
        ui.sleep(SELF_TAB_WAIT)
        ui.invalidate()
        if self._wait_self(ui, log):
            log.write_log("已切到【%s】tab（第二次点击）" % SELF_TAB)
            return True
        return False

    def _wait_self(self, ui, log, tries=8):
        """等【自营】tab 页：出现【每日领京豆】/【赚更多京豆】。"""
        for _ in range(tries):
            nodes = self._nodes(ui)
            if nodes and is_self_page(nodes):
                return True
            ui.sleep(1.5)
        log.write_log("等待【%s】tab 页超时" % SELF_TAB, "WARN")
        return False

    # ---------- 任务弹层 ----------
    def _open_panel(self, ui, log):
        """点【每日领京豆】正下方的【赚更多京豆】打开任务弹层。"""
        nodes = self._nodes(ui)
        node = find_more_bean(nodes)
        tries = 0
        while node is None and tries < LIST_SCROLL_TRIES:
            tries += 1
            log.write_log("自营页没看到【%s】，第 %d 次滑动再找" % (MORE_BEAN, tries))
            if tries % 2:
                ui.adb_swipe(ui.W // 2, ui.sy(1900), ui.W // 2, ui.sy(1200), duration=400)
            else:
                ui.adb_swipe(ui.W // 2, ui.sy(1200), ui.W // 2, ui.sy(1900), duration=400)
            ui.sleep(1.5)
            ui.invalidate()
            nodes = self._nodes(ui, tries=1)
            node = find_more_bean(nodes)
        if node is None:
            log.write_log("自营页始终没找到【%s】按钮" % MORE_BEAN, "WARN")
            return False

        box = clickable_ancestor(nodes, node) or node["bounds"]
        pos = ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2)
        log.write_log("命中【%s】%s，可点区 %s，点击 (%d,%d)"
                      % (node["text"], node["bounds"], box, pos[0], pos[1]))
        ui.adb_tap(pos, pause=2.0)
        ui.sleep(3.0)
        ui.invalidate()
        if self._wait_panel(ui, log):
            self._move_live_float(ui, log)
            log.write_log("【%s】任务弹层已打开" % PANEL_MARK)
            return True
        log.write_log("点了【%s】没弹出任务列表，再点一次" % MORE_BEAN, "WARN")
        ui.adb_tap(pos, pause=2.0)
        ui.sleep(3.0)
        ui.invalidate()
        if self._wait_panel(ui, log):
            self._move_live_float(ui, log)
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

    # ---------- 直播回放小窗 ----------
    def _move_live_float(self, ui, log):
        """把弹层右侧的【直播回放】视频小窗拖到屏幕顶部。

        真机踩过（2026-11-12）：小窗约 (873,1264)-(1032,1572)，正好压住
        第 1、2 行【去完成】按钮的右半部分，按钮中心 (922,1281)/(922,1483)
        都在小窗里 —— 点下去打开的是直播，不是任务页。第一次跑
        「1元抢手机」就是这样失败的（日志写着「做完但列表没变」）。

        小窗是原生视频浮层，**XML 里没有节点**（text/desc 全空），只能按坐标拖。
        必须用 `input draganddrop`（长按拖拽）：`input swipe` 会被识别成
        列表滚动（实测拖完只是列表滚了一屏，小窗纹丝不动）。

        小窗不在时执行也无副作用（落点在两行之间，WebView 直接忽略）。
        """
        x, y = LIVE_FLOAT_CENTER
        tx, ty = LIVE_FLOAT_TOP
        log.write_log("先把右侧【直播回放】小窗拖到顶部 (%d,%d)->(%d,%d)" % (x, y, tx, ty))
        ok = self._drag_float(ui, x, y, tx, ty, duration=LIVE_FLOAT_DURATION)
        ui.sleep(1.5)
        ui.invalidate()
        if not ok:
            log.write_log("拖【直播回放】小窗失败，前两行按钮可能被挡", "WARN")
        return ok

    def _drag_float(self, ui, x1, y1, x2, y2, duration=LIVE_FLOAT_DURATION):
        """优先用 ui.adb_drag（离线测试的替身），真机上走 adb input draganddrop。"""
        fn = getattr(ui, "adb_drag", None)
        if fn is not None:
            return fn(x1, y1, x2, y2, duration=duration)
        return self._adb_drag(ui, x1, y1, x2, y2, duration)

    def _adb_drag(self, ui, x1, y1, x2, y2, duration=LIVE_FLOAT_DURATION):
        """adb shell input draganddrop：长按拖拽，用来拖走原生视频浮层。"""
        import os
        import shutil
        import subprocess
        adb = getattr(ui, "_adb_path", None) or shutil.which("adb")
        if not adb:
            adb = os.path.join(os.environ.get("ANDROID_HOME", ""),
                               "platform-tools", "adb.exe")
            if not os.path.isfile(adb):
                adb = "adb"
        try:
            r = subprocess.run([adb, "shell", "input", "draganddrop",
                                str(int(x1)), str(int(y1)),
                                str(int(x2)), str(int(y2)), str(int(duration))],
                               capture_output=True, timeout=30)
            if r.returncode != 0:
                msg = (r.stderr or b"").decode("utf-8", "ignore")[:80]
                ui.say("draganddrop 返回 %d: %s" % (r.returncode, msg), "WARN")
                return False
            return True
        except Exception as e:
            ui.say("draganddrop 失败: %s" % e, "WARN")
            return False

    # ---------- 做任务 ----------
    def _process_tasks(self, ui, log, stop_event):
        attempted = set()
        failed = {}
        swept = False
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
                    # 重进后是全新弹层：只拉黑「连续失败」的任务，其余允许重试
                    attempted = set(t for t, n in failed.items() if n > MAX_RETRY)
                continue

            rows = parse_task_rows(nodes)
            row, reason = pick_target(rows, attempted)
            if row is None and reason == "none" and not swept:
                # 真机任务池很大（同一天两次跑列表完全不同），当前屏没有不代表到底了
                swept = True
                log.write_log("当前屏没有可做任务，先滑到底再确认")
                for _ in range(3):
                    ui.adb_swipe(ui.W // 2, ui.sy(2100), ui.W // 2,
                                 ui.sy(1500), duration=400)
                    ui.sleep(1.2)
                    ui.invalidate()
                nodes = self._nodes(ui)
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
                    # 重进后是全新弹层：只拉黑「连续失败」的任务，其余允许重试
                    attempted = set(t for t, n in failed.items() if n > MAX_RETRY)
                    continue
                nodes = self._nodes(ui)

            after = parse_task_rows(nodes)
            if row["title"] not in [r["title"] for r in after]:
                done += 1
                log.write_log("浏览完成 #%d（可做任务 %d -> %d）"
                              % (done, len(rows), len(after)))
            else:
                # 真机踩过（2026-11-12 跑 #1）：弹层刚打开就点第一行，点击被动画吞掉，
                # 浏览完回来进度没变。这种允许重试一次，别直接当成做不了。
                fails = failed.get(row["title"], 0) + 1
                failed[row["title"]] = fails
                if fails <= MAX_RETRY:
                    attempted.discard(row["title"])
                    log.write_log("任务【%s】第 %d 次没做成功，稍后重试"
                                  % (row["title"], fails), "WARN")
                else:
                    log.write_log("任务【%s】连续 %d 次没做成功，放弃"
                                  % (row["title"], fails), "WARN")

        return done

    def _scroll_panel(self, ui, log, reason):
        """在弹层里滚动任务列表。x 用屏幕中线，避开右侧那个半透明把手。"""
        x = ui.W // 2
        if reason == "below":
            log.write_log("目标任务在安全区下方，列表上滑")
            ui.adb_swipe(x, ui.sy(2100), x, ui.sy(1500), duration=400)
        else:
            log.write_log("目标任务在安全区上方，列表下滑")
            ui.adb_swipe(x, ui.sy(1500), x, ui.sy(2100), duration=400)
        ui.sleep(1.4)
        ui.invalidate()

    # ---------- 领取 ----------
    def _claim_once(self, ui, log, stop_event, max_clicks=5):
        """原地领当前屏的【领取】：点一个等 1 秒再点下一个，不滚动、不退出弹层。"""
        claimed = 0
        seen = {}
        while claimed < max_clicks:
            if stop_event.is_set():
                break
            btns = parse_claim_buttons(self._nodes(ui))
            if not btns:
                break
            b = btns[0]
            key = (b["cx"], b["cy"])
            if seen.get(key, 0) >= 2:
                # 同一个坐标点两次还不变，说明点不动，跳过
                btns = [x for x in btns if (x["cx"], x["cy"]) != key]
                if not btns:
                    break
                b = btns[0]
                key = (b["cx"], b["cy"])
            seen[key] = seen.get(key, 0) + 1
            ui.adb_tap((b["cx"], b["cy"]), pause=CLAIM_WAIT)
            claimed += 1
            ui.invalidate()
        if claimed:
            log.write_log("本屏领取 %d 次奖励" % claimed)
        return claimed

    def _claim_all(self, ui, log, stop_event):
        """全部领完：先回列表顶部，再逐屏往下扫，点一个等 1 秒。

        每屏领完只多读**一次**节点判断「还有没有【领取】」，
        比拿整页签名对比快一半（真机 page_source 一次 3~5s，
        签名方案每屏要读 2~3 次，5 屏就多花 50s）。
        """
        claimed = 0
        self._scroll_panel_to_top(ui)
        for _ in range(MAX_CLAIM_SCROLLS + 1):
            if stop_event.is_set():
                break
            claimed += self._claim_once(ui, log, stop_event,
                                        max_clicks=MAX_CLAIM_CLICKS - claimed)
            if claimed >= MAX_CLAIM_CLICKS:
                break
            # 这一屏领完了，往下滚一屏看还有没有
            ui.adb_swipe(ui.W // 2, ui.sy(2100), ui.W // 2, ui.sy(1600), duration=400)
            ui.sleep(1.4)
            ui.invalidate()
            if not parse_claim_buttons(self._nodes(ui, tries=1)):
                break                         # 没领取按钮了（或到底滚不动）
        log.write_log("领取阶段共领取 %d 次" % claimed)
        return claimed

    def _scroll_panel_to_top(self, ui, max_swipes=4):
        for _ in range(max_swipes):
            ui.adb_swipe(ui.W // 2, ui.sy(1600), ui.W // 2, ui.sy(2100), duration=400)
            ui.sleep(1.0)
            ui.invalidate()

    def _panel_sig(self, ui):
        """弹层指纹：所有 (N/M) 标题 + 按钮文案，用来判断滚动/领取有没有变化。

        不能用 parse_task_rows：任务都做完后它恒为空，签名永远相等。
        """
        nodes = self._nodes(ui, tries=1)
        if not nodes:
            return None
        sig = []
        for n in nodes or []:
            t = (n.get("text") or "").strip()
            if _PROGRESS_RE.search(t) or t in CLAIM_TEXTS or t in DONE_TEXTS \
                    or t in BROWSE_BUTTON_TEXTS:
                sig.append(t)
        return tuple(sig)

    # ---------- 恢复 ----------
    def _light_reopen(self, ui, log):
        """就地重开弹层：还在自营页就点【赚更多京豆】，退到拍拍二手页就先点【自营】。

        真机踩过（2026-11-12 跑 #2）：做完【逛京东服务】back 一次直接落到
        拍拍二手页（不是弹层），旧实现只认【赚更多京豆】，判失败后整链重进，
        白花 70s。这里补一级「中量恢复」，一般 15s 就能回弹层。
        """
        nodes = self._nodes(ui)
        if not nodes:
            return False
        if has_task_panel(nodes):
            return True
        if is_pp_page(nodes) and not is_self_page(nodes):
            log.write_log("退到拍拍二手页了，重新点【%s】tab" % SELF_TAB)
            if not self._open_self(ui, log):
                return False
            nodes = self._nodes(ui)
        node = find_more_bean(nodes) if nodes else None
        if node is None:
            return False
        box = clickable_ancestor(nodes, node) or node["bounds"]
        pos = ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2)
        log.write_log("还在自营页，点【%s】重开弹层 (%d,%d)"
                      % (node["text"], pos[0], pos[1]))
        ui.adb_tap(pos, pause=2.0)
        ui.sleep(3.0)
        ui.invalidate()
        if not self._wait_panel(ui, log, tries=5):
            return False
        self._move_live_float(ui, log)      # 重开弹层后小窗会重新出现
        return True

    def _recover_panel(self, ui, log):
        """弹层丢了之后分级恢复，避免动辄整链重进（一次 70s）。

        顺序：
          1. 弹层本来就在 -> True；
          2. 就地重开（自营页点【赚更多京豆】/ 拍拍二手页先点【自营】）；
          3. back 一次，再做一遍 1、2；
          4. 再 back 一次，再做一遍。
        """
        for i in range(3):
            nodes = self._nodes(ui)
            if nodes and has_task_panel(nodes):
                if i:
                    log.write_log("返回 %d 次后弹层又出现了" % i)
                return True
            if self._light_reopen(ui, log):
                if i:
                    log.write_log("返回 %d 次后就地重开弹层成功" % i)
                else:
                    log.write_log("就地重开弹层成功")
                return True
            if i >= 2:
                break
            ui.back(pause=2.0)
            ui.invalidate()
        log.write_log("分级恢复失败（当前页既不是自营页也不是拍拍二手页）", "WARN")
        return False

    def _reenter(self, ui, log):
        """整链重进：首页 -> 拍拍二手 -> 自营 tab -> 赚更多京豆弹层。"""
        if not self._open_pp(ui, log):
            return False
        if not self._open_self(ui, log):
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
