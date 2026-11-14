# -*- coding: utf-8 -*-
"""任务12【京东好礼】：京东首页【新品】->【送礼新品】->【好礼许愿】下【抽】
->【好礼许愿机】->【赚次数】任务弹窗 -> 做【浏览Xs得许愿次数】任务停留 X+4 秒
-> 循环直到任务列表没有可做任务。**没有领取奖励步骤**。

真机实测（2026-11-13，1080x2340，Appium 3.9/uiautomator2）：

1. 首页顶部 tab 行【特价/首页/秒送/外卖/新品】，【新品】是
   text='新品' 的 TextView (562,99,712,226)，点中心 (637,162) 进新品页。
   冷启动会回弹，要连续两次 dump bounds 一致再点（同 task11 的坑）。
2. 新品页有二级 tab 行（RecyclerView y=342~530），每格 ViewGroup
   clickable=true；【送礼新品】是 text='送礼新品' (432,446,596,504)，
   其父格 (416,342,612,530)，点 (514,436) 切换成功。
   页面标记：WebView text='京东新品' / '品质好礼逛京东'。
3. 【好礼许愿】卡片右下【抽】是 H5 图片按钮，文字被埋点替换成
   text='image'，只能按「x1>=900 且 650<=y1<=820 的 clickable Image」
   定位，真机 bounds=(954,706,1034,772)，中心 (994,739)。
4. 【好礼许愿机】页 XML 文字完整：WebView text='好礼许愿机'，
   【赚次数】是 clickable=true 的 TextView (819,1614,1036,1757)。
5. 任务弹窗叠加在抽奖页上，dump 里两页节点混在一起；判存在只认
   弹窗独有标题【做任务获得许愿次数】。弹窗从 y≈580 起，任务列表
   可视区 y≈790~2340，tab【今日任务/中奖记录】固定 y=698~778。
6. **任务池全量上报**：一份 XML 里约 18 行任务（含屏幕外），滚动只改
   bounds；屏幕外节点 bounds 被裁成 y2<=y1（被 JDUI.parse_bounds 丢掉），
   但列表**上部被弹窗裁掉的节点 bounds 仍有效**（如按钮 (838,22,1025,104)
   displayed=true），点它会落到原页。必须用 SAFE_TOP=790 过滤。
7. 可做任务 = 副标题【浏览Xs得许愿次数+N】+ 右侧按钮【逛一逛/去完成】。
   必须排除：
     - 【浏览5s得浏览票数+1】（逛京东指数领京豆）—— 奖励不是许愿次数
     - 【浏览5s得许愿机会+1】—— 文案变体，按需求字面排除
     - 【助力成功得许愿次数+1】/【下单可得许愿次数+1】—— 不是浏览任务，
       按钮是【去助力】/【去下单】，不在白名单
     - 【已完成】【已领取】等
   X 动态：同页混排【浏览25s】【浏览5s】，小写 s / 中文「秒」都兼容。
8. 点按钮跳商品详情/会场落地页，**back 一次**就回弹窗，且列表位置保持
   （不回顶）。做完后带进度的任务进度 +1（浏览精选会场 2/4->3/4、
   浏览会场 0/4->1/4->2/4），做满后整行消失、后面的行上移并补新任务。
   所以台账 key 要去掉 (N/M) 进度，且允许同一任务跨轮重复做。
9. 没有【领取奖励】/【开心收下】，不要做任何领奖动作。
10. 池子会补位，可能不会自然跑空：除「整轮扫完无可做任务」外必须加
    MAX_TASKS / MAX_CYCLES / 单任务次数上限，防止真机上无限循环。
"""
import re

from modules.base import BaseModule
import utils.driver as driver
from utils.jd_ui import JDUI

# ---------- 页面标记 ----------
NEW_TAB_TEXT = u"新品"
GIFT_TAB_TEXT = u"送礼新品"
NEW_PAGE_MARK = u"京东新品"
GIFT_PAGE_MARK = u"品质好礼逛京东"
WISH_PAGE_MARK = u"好礼许愿机"
EARN_TEXT = u"赚次数"
PANEL_MARK = u"做任务获得许愿次数"

# ---------- 任务行 ----------
# 严格按需求：只有「浏览Xs得许愿次数」才算可做任务。
SUB_RE = re.compile(u"浏览\\s*(\\d+)\\s*[秒sS]\\s*得\\s*许愿次数")
PROGRESS_RE = re.compile(u"[（(]\\s*\\d+\\s*/\\s*\\d+\\s*[）)]")
BTN_TEXTS = (u"逛一逛", u"去完成")
DONE_TEXTS = (u"已完成", u"已领取", u"已结束", u"去助力", u"去下单",
              u"去领取", u"领取奖励")

# ---------- 坐标（1080x2340 基准，运行时按 sx/sy 缩放）----------
CHOU_POS = (994, 739)            # 【抽】图片按钮中心
EARN_POS = (927, 1685)           # 【赚次数】按钮中心
GIFT_TAB_DY = -10                # 【送礼新品】点 TextView 上沿略上方（父格内）

# ---------- 可视区与配对 ----------
BTN_MIN_X = 700                  # 任务按钮贴右
SUB_MAX_X = 700                  # 副标题贴左
SAFE_TOP = 790                   # 弹窗任务列表可视区上界（tab 区 y<=778）
SAFE_BOTTOM = 2320               # 下界（避开屏幕底边）
ROW_TOL = 90                     # 按钮与副标题 y 容差（行距约 225px）
BROWSE_EXTRA = 4                 # 停留 = X + 4 秒

# ---------- 节奏与上限 ----------
PAGE_WAIT = 2.5                  # 每次转场后的稳定等待
MAX_TASKS = 40                   # 总浏览次数硬上限（池子会补位）
MAX_CYCLES = 8                   # 「扫一整轮」最大轮次
MAX_STEPS = 180                  # 单轮最多动作步数
MAX_SCROLLS = 10                 # 单轮最多上滑屏数
MAX_PER_TASK = 6                 # 同一任务本轮最多做几次（进度上限 4 留余量）
MAX_RETRY = 2                    # 单任务连续失败几次后拉黑
MAX_READ_FAILS = 4               # 连续读不到页面


# ---------------------------------------------------------------- 纯逻辑
def browse_seconds(x):
    """页面要求 X 秒 -> 实际停留 X + 4。"""
    return int(x) + BROWSE_EXTRA


def task_key(title, secs):
    """稳定行 id：去掉会随浏览变化的 (N/M) 进度。

    真机：浏览精选会场(2/4)->(3/4) 是同一个任务，标题原文不能做台账 key，
    否则每做一次都算新任务、防重复失效。
    """
    return PROGRESS_RE.sub(u"", title or u"") + u"|" + str(secs)


def _valid(b):
    return bool(b) and b[2] > b[0] and b[3] > b[1]


def parse_task_rows(nodes, btn_min_x=BTN_MIN_X, row_tol=ROW_TOL,
                    safe_top=SAFE_TOP, safe_bottom=SAFE_BOTTOM):
    """可做任务 = 副标题【浏览Xs得许愿次数】+ 同行按钮【逛一逛/去完成】。

    只取当前弹窗可视区内的节点：屏幕外节点 bounds 会被裁成 y2<=y1（已由
    JDUI.nodes 丢掉），但列表顶部被弹窗裁掉的节点 bounds 仍有效，必须靠
    safe_top 过滤，否则会点到原页上去。
    """
    subs = []
    for n in nodes or []:
        b = n.get("bounds") or (0, 0, 0, 0)
        if not _valid(b) or b[0] > SUB_MAX_X:
            continue
        m = SUB_RE.search((n.get("text") or "").strip())
        if m:
            subs.append((int(m.group(1)), (b[1] + b[3]) // 2, b[0],
                         (n.get("text") or "").strip()))
    rows = []
    for n in nodes or []:
        b = n.get("bounds") or (0, 0, 0, 0)
        if not _valid(b):
            continue
        txt = (n.get("text") or "").strip()
        if txt not in BTN_TEXTS or b[0] < btn_min_x:
            continue
        cx = (b[0] + b[2]) // 2
        cy = (b[1] + b[3]) // 2
        if not (safe_top <= cy <= safe_bottom):
            continue
        cand = [(abs(cy - s[1]), s) for s in subs if abs(cy - s[1]) <= row_tol]
        if not cand:
            continue
        cand.sort(key=lambda z: z[0])
        secs, sub_cy, sub_x1, sub_text = cand[0][1]
        # 同屏校验：副标题不能是被弹窗顶部裁掉的那一行
        if not (safe_top - row_tol <= sub_cy <= safe_bottom + row_tol):
            continue
        title = _row_title(nodes, cy, b, sub_x1, row_tol)
        rows.append({"title": title, "secs": secs, "sub": sub_text,
                     "key": task_key(title, secs), "cx": cx, "cy": cy,
                     "btn": txt, "btn_bounds": b})
    rows.sort(key=lambda r: r["cy"])
    return rows


def _row_title(nodes, btn_cy, btn_bounds, sub_x1, row_tol=ROW_TOL):
    """按钮左侧同一行的任务标题。

    排序键「带 (N/M) 进度 > 与副标题左对齐 > 纵向最近 > 最靠左」。
    弹窗任务标题与副标题都从 x1≈189 起，背景页商品卡是 x1=22 或更大的
    其它列，用「与副标题 x1 差 <= 40」把背景页文案排除掉。
    """
    best = None
    for n in nodes or []:
        b = n.get("bounds") or (0, 0, 0, 0)
        if not _valid(b):
            continue
        txt = (n.get("text") or "").strip()
        if not txt or SUB_RE.search(txt):
            continue
        if txt in BTN_TEXTS or txt in DONE_TEXTS:
            continue
        if len(re.findall(u"[\u4e00-\u9fa5]", txt)) < 2:
            continue
        cy = (b[1] + b[3]) // 2
        if abs(cy - btn_cy) > row_tol + 40:
            continue
        if b[0] > btn_bounds[0] + 30:
            continue
        aligned = abs(b[0] - sub_x1) <= 40
        progressive = bool(PROGRESS_RE.search(txt))
        score = (0 if progressive else 1,
                 0 if aligned else 1,
                 abs(cy - btn_cy), b[0], cy)
        if best is None or score < best[0]:
            best = (score, txt, aligned or progressive)
    if best is None:
        return u""
    # 既不带进度、也不与副标题同列 -> 一定是背景页文案，宁可留空
    return best[1] if best[2] else u""


def panel_sig(nodes, safe_top=SAFE_TOP, safe_bottom=SAFE_BOTTOM):
    """当前屏弹窗指纹，用来判断滚动有没有到顶/到底。"""
    if not nodes:
        return None
    sig = []
    for n in nodes or []:
        b = n.get("bounds") or (0, 0, 0, 0)
        if not _valid(b):
            continue
        t = (n.get("text") or "").strip()
        if not t:
            continue
        cy = (b[1] + b[3]) // 2
        if not (safe_top - 120 <= cy <= safe_bottom + 120):
            continue
        if (t in BTN_TEXTS or t in DONE_TEXTS or SUB_RE.search(t)
                or PROGRESS_RE.search(t)):
            sig.append((t, cy))
    return tuple(sorted(sig))


def pick_target(rows, blacklist, attempts, max_per_task=MAX_PER_TASK):
    """按屏幕从上到下挑一个没被拉黑、且没做超上限的任务行。"""
    for r in rows or []:
        if r["key"] in blacklist:
            continue
        if attempts.get(r["key"], 0) >= max_per_task:
            continue
        return r
    return None


def is_panel(nodes):
    """弹窗是否在场：只认弹窗独有标题（弹层与原页节点混叠）。"""
    return any((n.get("text") or "").strip() == PANEL_MARK
               for n in nodes or [])


def is_wish_page(nodes):
    return any((n.get("text") or "").strip() == WISH_PAGE_MARK
               for n in nodes or [])


def is_new_page(nodes):
    return any(NEW_PAGE_MARK in (n.get("text") or "").strip()
               for n in nodes or [])


def is_gift_page(nodes):
    return any(GIFT_PAGE_MARK in (n.get("text") or "").strip()
               for n in nodes or [])


def find_new_tab(nodes):
    """首页顶部【新品】tab（y1<250），返回中心坐标。"""
    for n in nodes or []:
        b = n.get("bounds") or (0, 0, 0, 0)
        if not _valid(b):
            continue
        if (n.get("text") or "").strip() != NEW_TAB_TEXT:
            continue
        if b[1] >= 250:
            continue
        return ((b[0] + b[2]) // 2, (b[1] + b[3]) // 2)
    return None


def find_gift_tab(nodes, dy=GIFT_TAB_DY):
    """新品页二级 tab【送礼新品】，返回其可点格内的坐标。"""
    for n in nodes or []:
        b = n.get("bounds") or (0, 0, 0, 0)
        if not _valid(b):
            continue
        if (n.get("text") or "").strip() != GIFT_TAB_TEXT:
            continue
        return ((b[0] + b[2]) // 2, b[1] + dy)
    return None


def find_chou_button(nodes):
    """【好礼许愿】卡片右下【抽】图片按钮：H5 无文字，按区域找 clickable Image。"""
    cands = []
    for n in nodes or []:
        b = n.get("bounds") or (0, 0, 0, 0)
        if not _valid(b):
            continue
        if not n.get("clickable"):
            continue
        if (n.get("class") or "").lower().find("image") < 0:
            continue
        if b[0] >= 900 and 650 <= b[1] <= 820 and b[2] <= 1080 and b[3] <= 850:
            cands.append((b[2] - b[0], b))
    if not cands:
        return None
    cands.sort(key=lambda z: z[0])
    b = cands[0][1]
    return ((b[0] + b[2]) // 2, (b[1] + b[3]) // 2)


def find_earn_button(nodes):
    """【赚次数】按钮（clickable=true，文字完整）。"""
    for n in nodes or []:
        b = n.get("bounds") or (0, 0, 0, 0)
        if not _valid(b):
            continue
        if (n.get("text") or "").strip() != EARN_TEXT:
            continue
        return ((b[0] + b[2]) // 2, (b[1] + b[3]) // 2)
    return None


# ---------------------------------------------------------------- 模块
class Task12Gift(BaseModule):
    name = u"京东好礼"
    description = (u"首页【新品】→【送礼新品】→【好礼许愿】下【抽】→"
                   u"【好礼许愿机】→【赚次数】弹窗 → 做【浏览Xs得许愿次数】"
                   u"任务停留 X+4 秒 → 循环至无可做任务（无需领取奖励）")
    icon = u"\U0001F9E7"

    def run(self, log, stop_event):
        ui = JDUI(driver.get_driver(), log, stop_event)
        log.write_log(u"设备分辨率 %dx%d" % (ui.W, ui.H))

        if not self._open_panel(ui, log):
            raise RuntimeError(u"未能打开【做任务获得许愿次数】任务弹窗")
        if stop_event.is_set():
            return

        total = 0
        blacklist = set()
        attempts = {}
        for cycle in range(MAX_CYCLES):
            if stop_event.is_set() or total >= MAX_TASKS:
                break
            log.write_log(u"===== 第 %d 轮：扫描并做任务 =====" % (cycle + 1))
            self._scroll_top(ui)
            done = self._scan_and_do(ui, log, stop_event, blacklist,
                                     attempts, total)
            total += done
            log.write_log(u"第 %d 轮完成浏览 %d 次（累计 %d 次）"
                          % (cycle + 1, done, total))
            if done == 0:
                log.write_log(u"任务列表已没有可做任务，结束")
                break
        if total >= MAX_TASKS:
            log.write_log(u"已达总浏览次数上限 %d，收尾" % MAX_TASKS, "WARN")
        log.done(u"京东好礼 完成 %d 次浏览任务（无需领取奖励）" % total)

    # ---------- 入口链路 ----------
    def _open_panel(self, ui, log, cold=True):
        if cold:
            if not ui.restart_to_home():
                log.write_log(u"冷启动回首页失败，走 goto_home", "WARN")
                if not ui.goto_home():
                    return False
            ui.sleep(2)

        pos = self._stable_new_tab(ui, log)
        if pos is None:
            log.write_log(u"首页始终没找到【新品】tab", "WARN")
            return False
        log.write_log(u"点首页【新品】tab %s" % (pos,))
        ui.adb_tap(pos, pause=2.0)
        ui.sleep(PAGE_WAIT)
        ui.invalidate()
        if not self._wait_for(ui, log, is_new_page, u"新品页"):
            return False

        gpos = None
        for _ in range(6):
            ns = self._nodes(ui, tries=1)
            gpos = find_gift_tab(ns)
            if gpos:
                break
            ui.sleep(1.0)
        if gpos is None:
            log.write_log(u"新品页没找到【送礼新品】tab", "WARN")
            return False
        log.write_log(u"点二级 tab【送礼新品】%s" % (gpos,))
        ui.adb_tap(gpos, pause=2.0)
        ui.sleep(PAGE_WAIT)
        ui.invalidate()
        if not self._wait_for(ui, log, is_gift_page, u"送礼新品页"):
            return False

        cpos = None
        for _ in range(6):
            ns = self._nodes(ui, tries=1)
            cpos = find_chou_button(ns)
            if cpos:
                break
            ui.sleep(1.0)
        if cpos is None:
            cpos = (ui.sx(CHOU_POS[0]), ui.sy(CHOU_POS[1]))
            log.write_log(u"【抽】按钮没识别到，用参考坐标 %s" % (cpos,), "WARN")
        log.write_log(u"点【好礼许愿】卡片下【抽】%s" % (cpos,))
        ui.adb_tap(cpos, pause=2.0)
        ui.sleep(PAGE_WAIT)
        ui.invalidate()
        if not self._wait_for(ui, log, is_wish_page, u"好礼许愿机"):
            return False
        return self._tap_earn(ui, log)

    def _stable_new_tab(self, ui, log, tries=8):
        """冷启动首页回弹：连续两次 dump【新品】tab 位置一致才认为可点。"""
        last = None
        for i in range(tries):
            ns = self._nodes(ui, tries=1)
            cur = find_new_tab(ns)
            if cur is not None and last is not None and cur == last:
                log.write_log(u"【新品】tab 位置稳定 %s（第 %d 次读）"
                              % (cur, i + 1))
                return cur
            last = cur
            ui.sleep(0.9)
        log.write_log(u"【新品】tab 位置未稳定，用最后一次 %s" % (last,), "WARN")
        return find_new_tab(self._nodes(ui, tries=2))

    def _wait_for(self, ui, log, predicate, label, tries=8):
        for i in range(tries):
            ns = self._nodes(ui, tries=1)
            if ns and predicate(ns):
                log.write_log(u"已进入【%s】（第 %d 次读，nodes=%d）"
                              % (label, i + 1, len(ns)))
                return True
            ui.sleep(1.0)
        log.write_log(u"等待【%s】超时" % label, "WARN")
        return False

    def _tap_earn(self, ui, log, retries=2):
        """点【赚次数】并轮询等弹窗标题出现（H5 偶发给上一帧）。"""
        for k in range(retries):
            ns = self._nodes(ui, tries=2)
            pos = find_earn_button(ns)
            if pos is None:
                pos = (ui.sx(EARN_POS[0]), ui.sy(EARN_POS[1]))
            log.write_log(u"点【赚次数】%s 第 %d 次" % (pos, k + 1))
            ui.adb_tap(pos, pause=2.0)
            ui.invalidate()
            for i in range(8):
                ns2 = self._nodes(ui, tries=1)
                if ns2 and is_panel(ns2):
                    log.write_log(u"【%s】弹窗已渲染（第 %d 次读）"
                                  % (PANEL_MARK, i + 1))
                    return True
                ui.sleep(1.0)
            log.write_log(u"第 %d 次点【赚次数】没弹出弹窗" % (k + 1), "WARN")
        return False

    # ---------- 主扫描循环 ----------
    def _scan_and_do(self, ui, log, stop_event, blacklist, attempts, already):
        done = 0
        fails = {}
        last_sig = None
        stagnant = 0
        scrolls = 0
        read_fails = 0

        for step in range(MAX_STEPS):
            if stop_event.is_set() or already + done >= MAX_TASKS:
                break
            ns = self._nodes(ui)
            if not ns:
                read_fails += 1
                if read_fails >= MAX_READ_FAILS:
                    log.write_log(u"连续 %d 次读不到页面，收尾" % read_fails,
                                  "WARN")
                    break
                continue
            read_fails = 0
            if not is_panel(ns):
                log.write_log(u"任务弹窗不见了，尝试恢复", "WARN")
                if not self._recover(ui, log):
                    break
                ns = self._nodes(ui)
                if not is_panel(ns):
                    break

            rows = parse_task_rows(ns)
            row = pick_target(rows, blacklist, attempts)
            if row is None:
                s = panel_sig(ns)
                if s == last_sig:
                    stagnant += 1
                else:
                    stagnant = 0
                last_sig = s
                if stagnant >= 2 or scrolls >= MAX_SCROLLS:
                    log.write_log(u"列表已扫到底，本轮没有更多可做任务")
                    break
                scrolls += 1
                self._swipe(ui, "up")
                continue

            last_sig = None
            ok = self._do_one(ui, log, row, stop_event)
            key = row["key"]
            if ok:
                done += 1
                fails.pop(key, None)
                attempts[key] = attempts.get(key, 0) + 1
                log.write_log(u"浏览完成 #%d / 本轮 #%d（%ds）【%s】"
                              % (already + done, done,
                                 browse_seconds(row["secs"]), row["title"]))
                # 带进度任务要重复做（0/4->4/4），跨轮允许；但状态不刷新时
                # 同一行会被反复点，超过上限就本轮拉黑。
                if attempts[key] > MAX_PER_TASK:
                    blacklist.add(key)
                    log.write_log(u"任务【%s】已做 %d 次仍显示可做，疑似状态"
                                  u"未刷新，本轮拉黑" % (row["title"],
                                                   attempts[key]), "WARN")
            else:
                n = fails.get(key, 0) + 1
                fails[key] = n
                if n > MAX_RETRY:
                    blacklist.add(key)
                    log.write_log(u"任务【%s】连续 %d 次没做成功，本轮拉黑"
                                  % (row["title"], n), "WARN")
                else:
                    log.write_log(u"任务【%s】第 %d 次没做成功，稍后重试"
                                  % (row["title"], n), "WARN")
        return done

    def _do_one(self, ui, log, row, stop_event):
        """点按钮 -> 确认跳出弹窗 -> 停留 X+4 -> back 回弹窗。"""
        dwell = browse_seconds(row["secs"])
        log.write_log(u"任务【%s】按钮【%s】%s，停留 %ds"
                      % (row["title"], row["btn"], row["btn_bounds"], dwell))
        ui.adb_tap((row["cx"], row["cy"]), pause=1.2)
        ui.invalidate()
        jumped = False
        for _ in range(3):
            ns = self._nodes(ui, tries=1)
            if ns and not is_panel(ns):
                jumped = True
                break
            ui.sleep(0.8)
        if not jumped:
            log.write_log(u"点了按钮但弹窗没消失，本次点击可能被吞", "WARN")
            return False
        if not ui.sleep(dwell):
            return False
        ui.back(pause=2.0)
        ui.sleep(1.0)
        ui.invalidate()
        for _ in range(4):
            ns = self._nodes(ui, tries=1)
            if ns and is_panel(ns):
                return True
            ui.sleep(1.0)
        log.write_log(u"浏览后没回到任务弹窗，尝试恢复", "WARN")
        return self._recover(ui, log)

    # ---------- 滚动与恢复 ----------
    def _swipe(self, ui, direction):
        """在弹窗列表里滚一屏；x 用屏幕中线，避开右侧浮层。"""
        x = ui.W // 2
        y_hi, y_lo = ui.sy(2100), ui.sy(1420)
        if direction == "up":
            ui.adb_swipe(x, y_hi, x, y_lo, duration=450)
        else:
            ui.adb_swipe(x, y_lo, x, y_hi, duration=450)
        ui.sleep(1.4)
        ui.invalidate()

    def _scroll_top(self, ui, max_swipes=8):
        prev = None
        for _ in range(max_swipes):
            self._swipe(ui, "down")
            s = panel_sig(self._nodes(ui, tries=1))
            if s is not None and s == prev:
                break
            prev = s

    def _recover(self, ui, log):
        """弹窗丢了之后分级恢复：就地重点【赚次数】-> back -> 整链重进。"""
        for i in range(3):
            ns = self._nodes(ui, tries=1)
            if ns and is_panel(ns):
                if i:
                    log.write_log(u"返回 %d 次后弹窗又出现了" % i)
                return True
            if i == 0 and ns and is_wish_page(ns):
                if self._tap_earn(ui, log, retries=1):
                    log.write_log(u"就地重点【赚次数】恢复成功")
                    return True
            ui.back(pause=1.5)
            ui.invalidate()
        log.write_log(u"恢复到首页重进整条入口链路", "WARN")
        return self._open_panel(ui, log, cold=True)

    # ---------- 小工具 ----------
    def _nodes(self, ui, tries=3, pause=1.2):
        """读页面节点；H5 转场瞬间 page_source 会空，重读再下结论。"""
        for i in range(tries):
            ui.invalidate()
            ns = ui.nodes()
            if ns:
                return ns
            if i < tries - 1:
                ui.sleep(pause)
        return []
