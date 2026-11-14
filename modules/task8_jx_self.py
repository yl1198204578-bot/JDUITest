# -*- coding: utf-8 -*-
"""任务8【京喜自营】：金刚区/全部频道进京喜自营 -> 王牌秒杀【去领取】->【领N京豆】
-> 做【浏览Xs可领】任务 -> 领【领取】奖励。

入口（三级，与需求一致）：
  1. 京东首页金刚区**第 1 页**找 desc="京喜自营"
     （金刚区 = 有【秒杀】那一行，一排 5 个半图标；真机 1080x2340 下这一行 y=440~601，
       京喜自营在第 4 格 (581,440,775,601)）
  2. 第 1 页没有就左滑到**第 2 页**再找
  3. 第 2 页也没有就点第 2 页的【全部频道】(867,924,1080,1085)
     -> 【优惠权益】tab (321,396,495,536) -> 【京喜自营】图标

京喜自营页 -> 王牌秒杀页：
  - 页面左上【王牌秒杀】卡片里有「最高121京豆」，它下面那个红按钮就是【去领取】。
    这个按钮**不是文本节点**，只有文字「最高121京豆」是 TextView；
    可点区域是包着它的 View (68,500,244,704)，点它靠下的位置即可。
  - 进【王牌秒杀】页后，右侧浮层有个【领 121 京豆】按钮
    （真机 (918,1603,1058,1746)，文案带空格：'领 121 京豆'）。
    **用户明确说这个入口要等 2~3 秒才展示出来**，所以必须轮询等待。
  - 点【领 121 京豆】弹出【做任务领京豆】底部弹层，里面才是任务列表。

任务行结构（真机实测，和家电家居几乎一样）：
  标题  【逛9.9包邮频道（0/1）】      <- 带 (N/M) 进度（全角括号）
  描述  【最高抽30元红包】+【，浏览10s可领】+【+1】
  按钮  【去完成】/【逛一逛】/【领取】/【已完成】

可做任务 = 描述含【浏览Ns可领】且按钮是【逛一逛】或【去完成】；停留 (X+4) 秒。
做完任务按钮变【领取】，需要点掉：**点一个等 1 秒再点下一个**，全部领完才结束。

真机踩过的坑（2026-11-12）：
1. 【去领取】不是文本节点，页面 dump 里只有「最高121京豆」，必须找它的可点祖先。
2. 【领 121 京豆】要等 2~3 秒才出现，一进来就查会扑空。
3. 弹层打开时**底部导航栏被盖住**（dump 里查不到 商品/一单回本/直播/客服），
   所以安全区可以放宽到 y≈2200；但 y>=2300 的行会被屏幕底边裁掉，必须先滚动。
4. 点【领取】只是把按钮变【已完成】，不跳页、不关弹层，所以可以原地一个接一个点。
5. 全部频道页默认停在【生活服务】tab，京喜自营在 y≈2092（屏幕外一大截）；
   点了【优惠权益】tab 之后整页滚到该区块，京喜自营跑到 y≈585。
   所以「点 tab」这一步不能省，而且点完必须重新读节点再定位。
"""
import re

from modules.base import BaseModule
import utils.driver as driver
from utils.jd_ui import JDUI

# ---------- 入口 ----------
JX_DESC = u"京喜自营"
ALL_CHANNEL = u"全部频道"
BENEFIT_TAB = u"优惠权益"
WP_MARK = u"王牌秒杀"
PANEL_MARK = u"做任务领京豆"
BEAN_CARD_KEYWORDS = (u"最高", u"京豆")      # 京喜自营页「最高121京豆」
BEAN_ENTRY_RE = re.compile(u"领\\s*\\d+\\s*京豆")   # 王牌秒杀页「领 121 京豆」

# ---------- 任务列表 ----------
BROWSE_BUTTON_TEXTS = (u"逛一逛", u"去完成")
CLAIM_TEXTS = (u"领取",)
BTN_MIN_X = 700                       # 按钮必须贴右
ROW_TOL = 70                          # 按钮与「浏览Ns可领」的 y 容差
BROWSE_EXTRA = 4                      # 停留 = X + 4 秒

SAFE_TOP = 1450                       # 弹层可点安全区上界（「赚更多京豆」以下）
SAFE_BOTTOM = 2200                    # 安全区下界（再往下会被屏幕底边裁掉）

MAX_TASKS = 40
MAX_SCROLLS = 8
MAX_NO_PROGRESS = 3
MAX_REENTER = 3
MAX_READ_FAILS = 4
MAX_CLAIM_CLICKS = 40
MAX_CLAIM_SCROLLS = 4
CLAIM_WAIT = 1.0                      # 点完一个【领取】等 1 秒再点下一个（用户定的）
BEAN_ENTRY_TRIES = 12                 # 【领N京豆】最多等多少次（每次 0.8s ≈ 10s）
BEAN_ENTRY_PAUSE = 0.8

_BROWSE_RE = re.compile(u"浏览\\s*(\\d+)\\s*[sS\u79d2]")
_PROGRESS_RE = re.compile(u"[（(]\\s*\\d+\\s*/\\s*\\d+\\s*[）)]")


# ---------------------------------------------------------------- 纯逻辑
def browse_seconds(x):
    """页面要求 X 秒 -> 实际停留 X + BROWSE_EXTRA。"""
    return int(x) + BROWSE_EXTRA


def parse_task_rows(nodes, btn_min_x=BTN_MIN_X, row_tol=ROW_TOL):
    """把节点配对成任务行。

    只有「右侧按钮（逛一逛/去完成）+ 同一行的【浏览Ns可领】」才算可做任务，
    所以【分享好友助力】这类天然被排除。
    返回 [{'title','secs','cx','cy','btn'}]，按 cy 升序。
    """
    btns = []
    subs = []
    for n in nodes or []:
        b = n.get("bounds") or (0, 0, 0, 0)
        if b[3] <= b[1] or b[2] <= b[0]:
            continue                      # 屏外/退化节点
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


def _row_title(nodes, btn):
    """按钮左侧、同一行区域的文字就是任务标题。

    同一行上「标题」和「副标题」离按钮一样近（实测都是 ~30px），
    只拼距离会抽到副标题，导致做完一步签名不变、永远判「没进展」。
    标题带 (N/M) 进度，所以优先它。
    """
    best = None
    for n in nodes or []:
        b = n.get("bounds") or (0, 0, 0, 0)
        if b[3] <= b[1] or b[2] <= b[0]:
            continue
        if ((b[0] + b[2]) // 2) >= BTN_MIN_X:
            continue
        txt = (n.get("text") or "").strip()
        if not txt or _BROWSE_RE.search(txt):
            continue
        if len(re.findall(u"[\u4e00-\u9fa5]", txt)) < 2:
            continue
        cy = (b[1] + b[3]) // 2
        if abs(cy - btn["cy"]) > ROW_TOL:
            continue
        score = (0 if _PROGRESS_RE.search(txt) else 1, abs(cy - btn["cy"]), cy)
        if best is None or score < best[0]:
            best = (score, txt)
    return best[1] if best else u""


def row_sig(rows):
    """任务行签名：标题含 (N/M)，做完一步签名就变。"""
    return tuple(sorted((r.get("title") or u"") + u"|" + str(r.get("secs"))
                        for r in (rows or [])))


def parse_claim_buttons(nodes, btn_min_x=BTN_MIN_X, row_tol=ROW_TOL):
    """任务行右侧的【领取】按钮，按 y 从上到下。

    三个条件同时满足才算：
      1. 文案完全等于【领取】且 clickable
      2. 贴右（x >= btn_min_x），和【去完成】在同一列
      3. **同一行左侧有带 (N/M) 进度的任务标题**

    第 3 条是关键：王牌秒杀页右侧还浮着一个【领 121 京豆】按钮，
    页面上别处也可能有「领取」，用「同行有 (N/M) 标题」把它们区分开。
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
        out.append({"text": (n.get("text") or "").strip(), "cx": cx, "cy": cy})
    out.sort(key=lambda r: r["cy"])
    return out


def _row_has_progress(nodes, btn_bounds, btn_cy, row_tol=ROW_TOL):
    """按钮左侧同一行是否有 (N/M) 进度标题。"""
    for n in nodes or []:
        b = n.get("bounds") or (0, 0, 0, 0)
        if b[3] <= b[1] or b[2] <= b[0]:
            continue
        if b[2] > btn_bounds[0]:
            continue
        if abs(((b[1] + b[3]) // 2) - btn_cy) > row_tol:
            continue
        if _PROGRESS_RE.search((n.get("text") or "").strip()):
            return True
    return False


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
    """任务弹层是否在场：有弹层标题，或任务行，或领取按钮。"""
    for n in nodes or []:
        txt = (n.get("text") or "").strip()
        if txt == PANEL_MARK:
            return True
        if txt in BROWSE_BUTTON_TEXTS:
            return True
        if _BROWSE_RE.search(txt) or _PROGRESS_RE.search(txt):
            return True
    return False


def find_bean_entry(nodes):
    """王牌秒杀页右侧那个【领 N 京豆】浮层按钮（文案带空格：'领 121 京豆'）。"""
    for n in nodes or []:
        b = n.get("bounds") or (0, 0, 0, 0)
        if b[3] <= b[1] or b[2] <= b[0]:
            continue
        if not n.get("clickable"):
            continue
        txt = (n.get("text") or "").strip()
        if BEAN_ENTRY_RE.search(txt):
            return n
    return None


def find_wp_bean_text(nodes):
    """京喜自营页【王牌秒杀】卡片里的「最高N京豆」文字节点。

    真机踩过：京东首页正文里也有「最高88京豆」这类广告文案，
    京喜自营页下方商品位也可能出现同样的字样。王牌秒杀卡片在最上面，
    所以按 (y1, x1) 取最靠上的那个，别拿下面广告位的凑数。
    """
    best = None
    for n in nodes or []:
        b = n.get("bounds") or (0, 0, 0, 0)
        if b[3] <= b[1] or b[2] <= b[0]:
            continue
        txt = (n.get("text") or "").strip()
        if not all(k in txt for k in BEAN_CARD_KEYWORDS):
            continue
        if best is None or (b[1], b[0]) < best[0]:
            best = ((b[1], b[0]), n)
    return best[1] if best else None


def clickable_ancestor(nodes, node):
    """包住 node 中心的最小可点节点（京喜自营页【去领取】就靠它找）。

    真机：『最高121京豆』(79,599,231,632) 是普通 TextView，
    可点区域是外面那层 View (68,500,244,704)，【去领取】就在它下半部分。
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
class Task8JxSelf(BaseModule):
    name = "京喜自营"
    description = ("金刚区/全部频道进【京喜自营】→ 王牌秒杀【去领取】→【领N京豆】→ "
                   "做【浏览Xs可领】任务，停留 X+4 秒，最后逐个【领取】奖励")
    icon = "🎁"

    def run(self, log, stop_event):
        ui = JDUI(driver.get_driver(), log, stop_event)
        log.write_log("设备分辨率 %dx%d" % (ui.W, ui.H))

        if not self._open_jx(ui, log, cold=True):
            raise RuntimeError("未能进入【京喜自营】")
        if stop_event.is_set():
            return
        if not self._open_wp(ui, log):
            raise RuntimeError("【京喜自营】页未能进入【王牌秒杀】")
        if stop_event.is_set():
            return
        if not self._open_panel(ui, log):
            raise RuntimeError("【王牌秒杀】页未能打开【领N京豆】任务弹层")
        if stop_event.is_set():
            return

        done = self._process_tasks(ui, log, stop_event)
        if stop_event.is_set():
            return
        claimed = self._claim_all(ui, log, stop_event)
        if stop_event.is_set():
            return
        log.done("京喜自营 完成 %d 个浏览任务，领取 %d 次奖励" % (done, claimed))

    # ---------- 入口 ----------
    def _open_jx(self, ui, log, cold=False):
        """首页 -> 京喜自营 页（金刚区第1页 -> 第2页 -> 全部频道-优惠权益）。"""
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
            icon, _stable = ui._stable_kingkong_icon(JX_DESC)
            if icon is not None:
                pos = ui.center(icon)
                log.write_log("金刚区第 %d 页命中【%s】%s，点击 (%d,%d)"
                              % (page, JX_DESC, icon["bounds"], pos[0], pos[1]))
                ui.tap(pos, pause=8)
                ui.invalidate()
                if self._wait_jx(ui, log):
                    log.write_log("已进入【京喜自营】（金刚区第 %d 页）" % page)
                    return True
                log.write_log("点了金刚区【%s】但没进京喜自营页，继续下一级入口" % JX_DESC, "WARN")
            else:
                log.write_log("金刚区第 %d 页没有【%s】" % (page, JX_DESC))
            if page == 1:
                ui.swipe_kingkong("left", pause=2)
                ui.invalidate()

        log.write_log("金刚区两页都没有，走【全部频道】-【优惠权益】-【京喜自营】", "WARN")
        if not self._enter_from_all_channels(ui, log):
            return False
        if self._wait_jx(ui, log):
            log.write_log("已进入【京喜自营】（全部频道）")
            return True
        return False

    def _enter_from_all_channels(self, ui, log):
        """全部频道 -> 优惠权益 tab -> 京喜自营 图标。"""
        nodes = self._nodes(ui)
        hit = self._tap_label(ui, log, nodes, ALL_CHANNEL, u"金刚区第2页", pause=4)
        if not hit:
            return False
        ui.sleep(2.0)
        ui.invalidate()

        nodes = self._nodes(ui)
        if self._tap_label(ui, log, nodes, BENEFIT_TAB, u"全部频道页", pause=2.5):
            ui.sleep(2.0)
            ui.invalidate()
            nodes = self._nodes(ui)          # 点完 tab 整页会滚动，必须重读
        else:
            log.write_log("全部频道页没找到【%s】tab，直接找【%s】" % (BENEFIT_TAB, JX_DESC), "WARN")

        return self._tap_label(ui, log, nodes, JX_DESC, u"全部频道页", pause=8)

    def _tap_label(self, ui, log, nodes, label, where, pause=4):
        """找文案完全等于 label 的节点，点包含它的最小可点祖先中心。"""
        cands = [n for n in nodes or []
                 if (n.get("text") or "").strip() == label
                 or (n.get("desc") or "").strip() == label]
        cands = [n for n in cands if n["bounds"][3] > n["bounds"][1] and n["bounds"][2] > n["bounds"][0]]
        if not cands:
            log.write_log("%s 没找到【%s】" % (where, label), "WARN")
            return False
        target = cands[0]
        if target.get("clickable"):
            # 自己就可点（如【优惠权益】tab）就用它自己的 bounds。
            # 真机踩过：拿 clickable_ancestor 会命中 tab 内部一个更小的可点节点
            # (247,231,445,308)，虽然也在 tab 里，但没必要绕这一层。
            box = target["bounds"]
        else:
            box = clickable_ancestor(nodes, target)
        if box is None:
            box = target["bounds"]
        pos = ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2)
        log.write_log("%s 命中【%s】%s，点击 (%d,%d)" % (where, label, box, pos[0], pos[1]))
        ui.adb_tap(pos, pause=pause)
        ui.invalidate()
        return True

    def _wait_jx(self, ui, log, tries=8):
        """等【京喜自营】页：出现【王牌秒杀】或「最高N京豆」。"""
        for _ in range(tries):
            nodes = self._nodes(ui)
            if nodes:
                joined = u" ".join(((n.get("text") or "") + (n.get("desc") or ""))
                                   for n in nodes)
                if WP_MARK in joined or find_wp_bean_text(nodes) is not None:
                    return True
            ui.sleep(1.5)
        log.write_log("等待【京喜自营】页超时", "WARN")
        return False

    # ---------- 王牌秒杀 ----------
    def _open_wp(self, ui, log):
        """京喜自营页点【王牌秒杀】卡片里的【去领取】。"""
        nodes = self._nodes(ui)
        txt = find_wp_bean_text(nodes)
        if txt is None:
            log.write_log("京喜自营页没找到「最高N京豆」文案", "WARN")
            return False
        box = clickable_ancestor(nodes, txt)
        if box is None:
            log.write_log("「%s」没有可点祖先，无法点【去领取】" % txt["text"], "WARN")
            return False
        # 【去领取】在这个可点区域的下半部分
        pos = ((box[0] + box[2]) // 2, box[1] + int((box[3] - box[1]) * 0.8))
        log.write_log("命中【王牌秒杀】「%s」%s，点【去领取】(%d,%d)"
                      % (txt["text"], box, pos[0], pos[1]))
        ui.adb_tap(pos, pause=2.0)
        ui.sleep(3.0)
        ui.invalidate()
        if not self._wait_wp(ui, log):
            # 兜底：直接点可点区域中心再试一次
            pos = ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2)
            log.write_log("点【去领取】后没进王牌秒杀页，改点区域中心 (%d,%d)" % pos, "WARN")
            ui.adb_tap(pos, pause=2.0)
            ui.sleep(3.0)
            ui.invalidate()
            return self._wait_wp(ui, log)
        return True

    def _wait_wp(self, ui, log, tries=8):
        """等【王牌秒杀】页。

        真机踩过（2026-11-12 第一次跑离线测就暴露了）：京喜自营页上本来就有一块
        「王牌秒杀」卡片标题，只拿 `WP_MARK in joined` 判断的话，点【去领取】
        没生效也会被判成「已进入王牌秒杀页」，后面找【领N京豆】自然扑空。
        所以改成两条：
          1. 出现【领N京豆】浮层按钮（王牌秒杀页独有）-> 到了；
          2. 或者「最高N京豆」不见了、同时还有「王牌秒杀」字样 -> 也算到了
             （【领N京豆】要等 2~3 秒才渲染，这中间靠第 2 条兜着）。
        """
        for _ in range(tries):
            nodes = self._nodes(ui)
            if nodes:
                if find_bean_entry(nodes) is not None:
                    return True
                if find_wp_bean_text(nodes) is None:
                    joined = u" ".join(((n.get("text") or "") + (n.get("desc") or ""))
                                       for n in nodes)
                    if WP_MARK in joined:
                        return True
            ui.sleep(1.5)
        log.write_log("等待【王牌秒杀】页超时", "WARN")
        return False

    # ---------- 任务弹层 ----------
    def _open_panel(self, ui, log):
        """等【领N京豆】浮层按钮出现（用户说 2~3 秒），点它打开任务弹层。"""
        node = None
        for i in range(BEAN_ENTRY_TRIES):
            node = find_bean_entry(self._nodes(ui))
            if node is not None:
                if i:
                    log.write_log("【领N京豆】等了 %.1fs 才出现" % (i * BEAN_ENTRY_PAUSE))
                break
            ui.sleep(BEAN_ENTRY_PAUSE)
            ui.invalidate()
        if node is None:
            log.write_log("【王牌秒杀】页始终没出现【领N京豆】按钮", "WARN")
            return False

        pos = ui.center(node)
        log.write_log("命中【%s】%s，点击 (%d,%d)"
                      % (node["text"], node["bounds"], pos[0], pos[1]))
        ui.adb_tap(pos, pause=2.0)
        ui.sleep(3.0)
        ui.invalidate()
        if self._wait_panel(ui, log):
            log.write_log("【做任务领京豆】任务弹层已打开")
            return True
        log.write_log("点了【领N京豆】没弹出任务列表", "WARN")
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
                # 真机踩过（2026-11-12 第一次运行）：【新用户至高5元】和
                # 【来农场浇水领免费水果】这两个任务跳的是京东自家的页面，
                # 按一次 back 落回的是京喜自营页而不是王牌秒杀弹层。
                # 旧代码直接整链重进（约 40 秒），5 个任务白花 80 秒。
                # 现在先试「轻量重开」：只要还能看到【领N京豆】就点它重开弹层。
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
                # 刚做完那一行就在当前屏，顺手把【领取】点掉（不滚动）
                self._claim_once(ui, log, stop_event, max_clicks=5)
            else:
                log.write_log("任务【%s】做完但计数没变，换下一个" % row["title"], "WARN")

        return done

    def _scroll_panel(self, ui, log, reason):
        """在弹层里滚动任务列表（弹层盖住底部导航，滑到 y=2200 也安全）。"""
        x = ui.W // 2
        if reason == "below":
            log.write_log("目标任务在安全区下方，列表上滑")
            ui.adb_swipe(x, ui.sy(2050), x, ui.sy(1700), duration=400)
        else:
            log.write_log("目标任务在安全区上方，列表下滑")
            ui.adb_swipe(x, ui.sy(1700), x, ui.sy(2050), duration=400)
        ui.sleep(1.4)
        ui.invalidate()

    # ---------- 领取奖励 ----------
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
            log.write_log("顺手领取 %d 次奖励" % claimed)
        return claimed

    def _claim_all(self, ui, log, stop_event):
        """全部领完：先回列表顶部，再逐屏往下扫，点一个等 1 秒。"""
        claimed = 0
        self._scroll_panel_to_top(ui)
        for _ in range(MAX_CLAIM_SCROLLS + 1):
            if stop_event.is_set():
                break
            before = self._panel_sig(ui)
            claimed += self._claim_once(ui, log, stop_event,
                                        max_clicks=MAX_CLAIM_CLICKS - claimed)
            if claimed >= MAX_CLAIM_CLICKS:
                break
            after = self._panel_sig(ui)
            if before == after:
                # 这一屏没有可领的了，往下滚一屏再看
                ui.adb_swipe(ui.W // 2, ui.sy(2050), ui.W // 2, ui.sy(1700), duration=400)
                ui.sleep(1.4)
                ui.invalidate()
                if self._panel_sig(ui) == after:
                    break                     # 滚不动了，到底
        log.write_log("领取阶段共领取 %d 次" % claimed)
        return claimed

    def _scroll_panel_to_top(self, ui, max_swipes=4):
        for _ in range(max_swipes):
            ui.adb_swipe(ui.W // 2, ui.sy(1700), ui.W // 2, ui.sy(2050), duration=400)
            ui.sleep(1.0)
            ui.invalidate()

    def _panel_sig(self, ui):
        """弹层指纹：任务行 + 领取按钮，用来判断滚动/领取有没有效果。"""
        nodes = self._nodes(ui, tries=1)
        if not nodes:
            return None
        parts = list(row_sig(parse_task_rows(nodes)))
        parts += ["claim|%d,%d" % (b["cx"], b["cy"]) for b in parse_claim_buttons(nodes)]
        return tuple(parts)

    def _recover_panel(self, ui, log):
        """弹层丢了之后先试「轻量重开」，避免动辄整链重进。

        顺序：
          1. 如果还在王牌秒杀页（能看到【领N京豆】），直接点它重开弹层；
          2. 否则按 back 退一步再看，最多两次；
          3. 都不行才返回 False，交给上层整链重进。
        """
        nodes = self._nodes(ui)
        if nodes and has_task_panel(nodes):
            return True                   # 弹层本来就在，什么都不用做
        node = find_bean_entry(nodes) if nodes else None
        if node is not None:
            pos = ui.center(node)
            log.write_log("还在王牌秒杀页，点【%s】重开弹层 (%d,%d)"
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
            node = find_bean_entry(nodes) if nodes else None
            if node is not None:
                pos = ui.center(node)
                log.write_log("退回王牌秒杀页，点【%s】重开弹层" % node["text"])
                ui.adb_tap(pos, pause=2.0)
                ui.sleep(3.0)
                ui.invalidate()
                if self._wait_panel(ui, log, tries=5):
                    return True
        log.write_log("轻量重开失败（当前页不是王牌秒杀页）", "WARN")
        return False

    def _reenter(self, ui, log):
        """整链重进：首页 -> 京喜自营 -> 王牌秒杀 -> 领N京豆弹层。"""
        if not self._open_jx(ui, log):
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
