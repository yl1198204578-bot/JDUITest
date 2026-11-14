# -*- coding: utf-8 -*-
"""任务6【家电家居】：进家电家居页 -> 每日领京豆 -> 赚更多京豆 -> 做【浏览Xs可领】任务。

入口（三级，与需求一致）：
  1. 京东首页金刚区第 1 页，节点 desc="家电家居"
  2. 金刚区第 2 页（左滑一次）再找
  3. 第 2 页【全部频道】->【发现好物】->【家电家居】

【发现好物】页上有三个「家电家居」，必须点对：
  - 顶部筛选 chip  (387,368,607,470) clickable=true   <- 不能点，只是筛选
  - 区块标题      (55,1476,1025,1548) 全宽、不可点    <- 不能点
  - 带图标的区块项 (77,1677,231,1724) 窄、不可点      <- 点它（点击由父容器接管）
  判据：宽度 < 400 且 y > 800。

任务判定（需求原文）：
  可做 = 描述含【浏览Xs可领】且按钮是【逛一逛】或【去完成】；
  停留 (X+4) 秒；循环到列表里没有可做任务为止。
  做完任务后再循环点【领取】，直到任务列表里没有领取按钮。

实测（2026-11-12，1080x2340）：
- 家电家居页是原生页面，节点可读，**不需要 OCR**（与 JOY游记 相反）。
- 任务行结构：标题一行 +「，浏览10s可领」同一行文字 + 右侧按钮，
  按钮中心比文字中心高约 30px，所以配对容差取 70。
- 【分享好友助力】这类没有「浏览Ns可领」，自动排除。
- 列表可滚动，屏外节点 bounds 会退化成 y2<=y1，必须先过滤。
"""
import re
import time

from modules.base import BaseModule
import utils.driver as driver
from utils.jd_ui import JDUI

BROWSE_EXTRA = 4                      # 停留 = X + 4 秒
BROWSE_BUTTON_TEXTS = (u"逛一逛", u"去完成")
# 做完任务后任务行右侧会变成【领取】。
# 用户 2026-11-12 要求：一直点到任务列表里没有【领取】按钮为止。
# 注意只认「领取」三个字：页面上还有「立即领取」（带图标的横排位，
# 真机 (1058,1562)），那不是任务奖励，点了白点。用户已明确不要它。
CLAIM_TEXTS = (u"领取",)
BTN_MIN_X = 700                       # 按钮必须贴右
ROW_TOL = 70                          # 按钮与「浏览Ns可领」的 y 容差
# 只认【每日领京豆】/【赚更多京豆】。
# 千万不要把【家电馆】算进来：金刚区点【家电家居】落的就是家电馆，
# 而家电馆里没有京豆任务（实测 _fixture_ha_appliance_hall.xml）。
ENTRY_KEYWORDS = (u"每日领京豆", u"赚更多京豆")

MAX_TASKS = 40
MAX_SCROLLS = 10
MAX_NO_PROGRESS = 3
MAX_REENTER = 3
MAX_READ_FAILS = 4                   # 连续读不到页面几次就收尾
MAX_CLAIM_CLICKS = 40                # 领取阶段最多点多少次
CLAIM_WAIT = 1.0                     # 点完一个【领取】等多久再点下一个（用户定的 1s）
MAX_CLAIM_SCROLLS = 8                # 领取阶段最多滚动几次

_BROWSE_RE = re.compile(u"浏览\\s*(\\d+)\\s*[sS\u79d2]")
# 标题里的 (N/M) 进度，如【逛外卖频道（0/1）】
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
                     "cx": b["cx"], "cy": b["cy"], "btn": b["text"]})
    rows.sort(key=lambda r: r["cy"])
    return rows


def _row_title(nodes, btn):
    """按钮左侧、同一行区域的文字就是任务标题。"""
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
        # 同一行上「标题」和「副标题」离按钮一样近（实测都是 ~30px），
        # 只拼距离会抽到「抢20元外卖金券」这种静态副标题，导致做完一步签名
        # 不变、永远判「没进展」。标题带 (N/M) 进度，所以优先它。
        score = (0 if _PROGRESS_RE.search(txt) else 1, abs(cy - btn["cy"]), cy)
        if best is None or score < best[0]:
            best = (score, txt)
    return best[1] if best else u""


def row_sig(rows):
    """任务行签名：标题含 (N/M)，做完一步签名就变。"""
    return tuple(sorted((r.get("title") or u"") + u"|" + str(r.get("secs")) for r in (rows or [])))


def parse_claim_buttons(nodes, btn_min_x=BTN_MIN_X, row_tol=ROW_TOL):
    """任务行右侧的【领取】按钮，按 y 从上到下。

    三个条件同时满足才算：
      1. 文案完全等于【领取】且 clickable
         （排除【立即领取】和「完成即可领取现金奖励」这种不可点文案）
      2. 贴右（x >= btn_min_x），和【去完成】在同一列
      3. **同一行左侧有带 (N/M) 进度的任务标题**

    第 3 条是真机踩出来的：页面别处（每日领京豆区块、下方推荐位）
    也有「领取」，点了会直接跳到另一个页面，用户实测就是
    「点领取却退出了页面」。任务行的领取必带标题如
    【逛外卖频道（1/1）】，用这个特征把它们区分开。
    """
    out = []
    for n in nodes or []:
        b = n.get("bounds") or (0, 0, 0, 0)
        if b[3] <= b[1] or b[2] <= b[0]:
            continue                      # 屏外/退化节点
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
            continue                      # 必须在按钮左边
        if abs(((b[1] + b[3]) // 2) - btn_cy) > row_tol:
            continue
        if _PROGRESS_RE.search((n.get("text") or "").strip()):
            return True
    return False


def has_task_list(nodes):
    """任务列表是否在场。

    不能拿【每日领京豆】/【赚更多京豆】判断：任务列表是在同一个 WebView
    里向下展开的，两份 dump（_fixture_ha_page.xml 与 _fixture_ha_tasks.xml）
    都有这两个词，只不过后者多了任务行。用它们判会把首页误判成
    任务列表，于是不点【赚更多京豆】就去读行，永远读不到。
    只认任务行特征：按钮、【浏览Ns可领】、或标题里的 (N/M) 进度。
    """
    for n in nodes or []:
        txt = (n.get("text") or "").strip()
        if txt in BROWSE_BUTTON_TEXTS:
            return True
        if _BROWSE_RE.search(txt) or _PROGRESS_RE.search(txt):
            return True
    return False


# ---------------------------------------------------------------- 模块
class Task6HomeAppliance(BaseModule):
    name = "家电家居"
    description = "进入【家电家居】做【浏览Xs可领】任务（逛一逛/去完成），停留 X+4 秒，直到没有可做任务"
    icon = "🏠"

    def run(self, log, stop_event):
        ui = JDUI(driver.get_driver(), log, stop_event)
        log.write_log("设备分辨率 %dx%d" % (ui.W, ui.H))

        if not ui.restart_to_home():
            raise RuntimeError("冷启动后未识别到京东首页，无法定位金刚区【家电家居】")
        ui._restarted = True
        if stop_event.is_set():
            return

        self._open_page(ui, log)
        if stop_event.is_set():
            return

        self._open_task_dialog(ui, log)
        if stop_event.is_set():
            return

        done = self._process_tasks(ui, log, stop_event)
        if stop_event.is_set():
            return
        claimed = self._claim_rewards(ui, log, stop_event,
                                      max_scrolls=MAX_CLAIM_SCROLLS, to_top=True)
        log.done("家电家居 完成 %d 个浏览任务，领取 %d 次奖励" % (done, claimed))

    # ---------- 入口 ----------
    def _open_page(self, ui, log):
        """三级入口：金刚区第1页 -> 第2页 -> 全部频道-发现好物。

        真机实测：金刚区第 1 页确实有【家电家居】，但点下去落的是
        【家电馆】频道页（_fixture_ha_appliance_hall.xml），里面没有京豆任务。
        所以这条捷径只能当「试一下」，失败就往下走；而且落错页后
        必须先回首页再翻金刚区，否则滑的是岔路页面。
        """
        for page in (1, 2):
            icon, _stable = ui._stable_kingkong_icon(u"家电家居")
            tapped = False
            if icon is not None:
                x1, y1, x2, y2 = icon["bounds"]
                pos = ((x1 + x2) // 2, (y1 + y2) // 2)
                log.write_log("金刚区第 %d 页命中【家电家居】%s，点击 (%d,%d)"
                              % (page, icon["bounds"], pos[0], pos[1]))
                ui.tap(pos, pause=7)
                tapped = True
                if self._wait_page(ui, log):
                    log.write_log("已进入【家电家居】（金刚区第 %d 页）" % page)
                    return True
                log.write_log("点了金刚区【家电家居】但落到别的页（如【家电馆】），继续下一级入口", "WARN")
            else:
                log.write_log("金刚区第 %d 页没有【家电家居】" % page)
            if page == 1:
                if tapped and not ui.goto_home():
                    log.write_log("回首页失败，直接走【全部频道】兜底", "WARN")
                    break
                log.write_log("左滑金刚区到第 2 页")
                ui.swipe_kingkong("left", pause=2)
                ui.invalidate()

        log.write_log("金刚区两页都没有，走【全部频道】-【发现好物】", "WARN")
        ui.to_all_channels()
        self._tap_node(ui, log, u"发现好物", u"全部频道页", pause=5)
        self._tap_appliance_item(ui, log)
        if not self._wait_page(ui, log):
            raise RuntimeError("三级入口都失败，未能进入【家电家居】")
        log.write_log("已进入【家电家居】（全部频道-发现好物）")
        return True

    def _tap_appliance_item(self, ui, log):
        """【发现好物】里有三个「家电家居」，点带图标的那个窄项。"""
        nodes = self._nodes(ui)
        cands = []
        for n in nodes:
            txt = " ".join(((n.get("text") or "") + " " + (n.get("desc") or "")).split())
            if txt != u"家电家居":
                continue
            b = n["bounds"]
            if b[3] <= b[1] or b[2] <= b[0]:
                continue
            width = b[2] - b[0]
            if width >= 400 or b[1] < 800:
                continue                      # 顶部 chip / 全宽区块标题
            cands.append((b[1], ui.center(n), b))
        if not cands:
            raise RuntimeError("【发现好物】页没有找到带图标的【家电家居】项")
        cands.sort()
        _, pos, b = cands[0]
        log.write_log("发现好物页命中【家电家居】图标项 %s，点击 (%d,%d)" % (b, pos[0], pos[1]))
        ui.tap(pos, pause=9)
        ui.invalidate()

    def _tap_node(self, ui, log, kw, where, pause=5, exact=False, tries=3, scrolls=2):
        """在当前页点中文案含 kw 的节点，找不到就重试 + 向下滚动找。

        真机踩过（2026-11-12 第三次运行）：进了【全部频道】但页面还没把
        【发现好物】渲染出来，原来一次性查不到就直接抛错，整个任务失败。
        """
        for t in range(tries):
            best = None
            for n in self._nodes(ui):
                v = " ".join(((n.get("text") or "") + " " + (n.get("desc") or "")).split())
                hit = (v == kw) if exact else (kw in v)
                if not hit:
                    continue
                b = n["bounds"]
                if b[3] <= b[1] or b[2] <= b[0]:
                    continue
                cand = (0 if n.get("clickable") else 1, b[1], n)
                if best is None or cand[:2] < best[:2]:
                    best = cand
            if best:
                n = best[2]
                pos = ui.center(n)
                log.write_log("%s 命中【%s】%s，点击 (%d,%d)"
                              % (where, kw, n["bounds"], pos[0], pos[1]))
                ui.tap(pos, pause=pause)
                ui.invalidate()
                return True
            if t < tries - 1:
                if scrolls > 0:
                    scrolls -= 1
                    log.write_log("%s 未找到【%s】，向下滚动再找" % (where, kw), "WARN")
                    ui.adb_swipe(ui.W // 2, int(ui.H * 0.75),
                                 ui.W // 2, int(ui.H * 0.45), duration=500)
                    ui.sleep(1.5)
                else:
                    ui.sleep(2)
                ui.invalidate()
        raise RuntimeError("%s 未找到【%s】节点" % (where, kw))

    def _nodes(self, ui, tries=3, pause=1.5):
        """读页面节点，读不到就重读。

        真机踩过（run 2026-11-12 第 5 个任务后）：从浏览页退回的瞬间主线程还在忙，
        page_source 会报 `Timed out after 10082ms waiting for the root
        AccessibilityNodeInfo`，jd_ui.source() 吞掉异常返回 None，
        nodes() 从而返回 []。旧代码把「读失败」当成「任务列表没了」，
        于是整页重进，白白多花 2 分钟。这里先重读再下结论。
        """
        for i in range(tries):
            ui.invalidate()
            ns = ui.nodes()
            if ns:
                return ns
            if i < tries - 1:
                ui.sleep(pause)
        return []

    def _wait_page(self, ui, log, timeout=25):
        """等到【家电家居】页出现。

        区分两种失败：
          - 读到了页面但没有关键词 -> 确实不是家电家居页，立即返回 False
          - 页面一直读不出来（page_source 超时）-> 继续等到超时
        """
        deadline = time.time() + timeout
        while True:
            nodes = self._nodes(ui)
            if nodes:
                for n in nodes:
                    txt = (n.get("text") or "").strip()
                    if any(k in txt for k in ENTRY_KEYWORDS):
                        return True
                return False
            if time.time() >= deadline:
                log.write_log("页面一直读不出来，无法判断是否在【家电家居】页", "WARN")
                return False
            ui.sleep(2)

    # ---------- 任务面板 ----------
    def _open_task_dialog(self, ui, log):
        """点【赚更多京豆】把任务列表展开。

        【每日领京豆】只是区块标题（clickable=false），点它没用，
        所以先直接点可点的【赚更多京豆】；万一页面改版先点标题再点。
        """
        for i in range(MAX_REENTER):
            if has_task_list(ui.nodes()):
                log.write_log("任务列表已经打开")
                return True
            if not self._wait_page(ui, log, timeout=8):
                # 先回退一步（浏览页/二级页退一步就回来了），
                # 还不行才整页重进。直接重进太贵（要走完三级入口）。
                log.write_log("不在【家电家居】页，先回退一步找", "WARN")
                ui.back(2.5)
                if not self._wait_page(ui, log, timeout=8):
                    log.write_log("回退后仍不在页面上，重新进入（第 %d 次）" % (i + 1), "WARN")
                    self._open_page(ui, log)
            try:
                self._tap_node(ui, log, u"赚更多京豆", u"家电家居页", pause=6)
            except RuntimeError:
                log.write_log("没找到【赚更多京豆】，先点【每日领京豆】展开", "WARN")
                self._tap_node(ui, log, u"每日领京豆", u"家电家居页", pause=4)
                self._tap_node(ui, log, u"赚更多京豆", u"家电家居页", pause=6)
            if has_task_list(ui.nodes()):
                log.write_log("任务列表已打开")
                return True
            log.write_log("任务列表未出现（第 %d 次）" % (i + 1), "WARN")
        raise RuntimeError("点了【赚更多京豆】但任务列表没打开")

    def _reenter(self, ui, log):
        for i in range(MAX_REENTER):
            log.write_log("尝试重新打开任务列表（第 %d 次）" % (i + 1), "WARN")
            if has_task_list(ui.nodes()):
                return True
            try:
                self._open_task_dialog(ui, log)
                return True
            except Exception as e:
                log.write_log("重开失败：%s" % e, "WARN")
                ui.back(2)
        return False

    # ---------- 做任务 ----------
    def _process_tasks(self, ui, log, stop_event):
        done = 0
        scrolls = 0
        no_progress = 0
        stuck = {}

        read_fails = 0
        while not stop_event.is_set() and done < MAX_TASKS:
            nodes = self._nodes(ui)
            if not nodes:
                # 读失败 != 列表没了：原地重试，别去重进页面
                read_fails += 1
                log.write_log("页面读取失败（第 %d 次），稍后重试" % read_fails, "WARN")
                if read_fails >= MAX_READ_FAILS:
                    log.write_log("连续 %d 次读不到页面，提前结束" % read_fails, "WARN")
                    break
                ui.sleep(3)
                continue
            read_fails = 0
            if not has_task_list(nodes):
                if not self._reenter(ui, log):
                    log.write_log("无法回到任务列表，提前结束", "WARN")
                    break
                nodes = ui.nodes()

            rows = parse_task_rows(nodes)
            cand_rows = [r for r in rows
                         if stuck.get(r.get("title") or u"", 0) < 2]
            if not cand_rows:
                if scrolls >= MAX_SCROLLS:
                    log.write_log("可做任务都试过且没进展，结束")
                    break
                log.write_log("当前屏没有可做任务，向下滚动找")
                if not self._scroll(ui):
                    log.write_log("滚动后画面没有变化，判定已到底")
                    break
                scrolls += 1
                stuck.clear()
                continue

            row = cand_rows[0]
            key = row.get("title") or u""
            secs = browse_seconds(row["secs"])
            log.write_log("浏览任务：%s -> 按钮【%s】(%d,%d)，停留 %d 秒"
                          % (key or row["btn"], row["btn"], row["cx"], row["cy"], secs))
            before = row_sig(rows)
            ui.tap((row["cx"], row["cy"]), pause=3)
            if not ui.sleep(secs):
                log.write_log("被停止，中断任务", "WARN")
                break

            log.write_log("返回任务列表")
            ui.back(2.5)
            ui.invalidate()
            nodes = self._nodes(ui)
            if not nodes:
                # 上一步读失败就重读，不能当成列表没了而去重进
                log.write_log("返回后页面读取失败，继续重试", "WARN")
                nodes = self._nodes(ui, tries=5, pause=2.5)
            if not has_task_list(nodes):
                if not self._reenter(ui, log):
                    log.write_log("返回后无法回到任务列表，提前结束", "WARN")
                    break
                nodes = self._nodes(ui)

            after_rows = parse_task_rows(nodes)
            if row_sig(after_rows) != before or len(after_rows) < len(rows):
                done += 1
                no_progress = 0
                stuck.pop(key, None)
                log.write_log("浏览完成 #%d（可做任务 %d -> %d）"
                              % (done, len(rows), len(after_rows)))
                # 刚做完的那一行就在当前屏，顺手把它的【领取】点掉，
                # 不滚动、不退出弹窗（max_scrolls=0）。
                self._claim_rewards(ui, log, stop_event, max_clicks=5,
                                    max_scrolls=0, to_top=False)
            else:
                no_progress += 1
                stuck[key] = stuck.get(key, 0) + 1
                log.write_log("该任务计数没有变化，换一个任务", "WARN")
                if no_progress >= MAX_NO_PROGRESS:
                    log.write_log("连续 %d 次没有进展，滚动换一批" % no_progress, "WARN")
                    no_progress = 0
                    if not self._scroll(ui):
                        log.write_log("滚动后画面没有变化，判定已到底")
                        break
                    scrolls += 1
                    if scrolls >= MAX_SCROLLS:
                        break

        return done

    # ---------- 领取奖励 ----------
    def _claim_rewards(self, ui, log, stop_event, max_clicks=MAX_CLAIM_CLICKS,
                       max_scrolls=MAX_CLAIM_SCROLLS, to_top=True):
        """把任务行右侧的【领取】一个一个点掉。

        用户 2026-11-12 三次纠正：
          1. 只认【领取】，不认【立即领取】；
          2. 点完等 1 秒就点下一个；
          3. **不要把任务列表弹窗关掉 / 退出页面**。

        所以这里一律不按返回键、不关弹窗；不同意图的【领取】
        已由 parse_claim_buttons 的「必须挂在任务行上」过滤掉。
        """
        if not has_task_list(self._nodes(ui)):
            log.write_log("任务列表不在场，跳过领取阶段", "WARN")
            return 0

        if to_top:
            n = self._scroll_to_top(ui)
            log.write_log("领取前先滚回任务列表顶部（滑动 %d 次）" % n)

        claimed = 0
        scrolls = 0
        read_fails = 0
        tried = {}

        while not stop_event.is_set() and claimed < max_clicks:
            nodes = self._nodes(ui)
            if not nodes:
                read_fails += 1
                log.write_log("领取阶段读不到页面（第 %d 次），稍后重试" % read_fails, "WARN")
                if read_fails >= MAX_READ_FAILS:
                    log.write_log("领取阶段连续读不到页面，收尾", "WARN")
                    break
                ui.sleep(3)
                continue
            read_fails = 0

            btns = [b for b in parse_claim_buttons(nodes)
                    if tried.get((b["cx"], b["cy"]), 0) < 2]
            if not btns:
                if scrolls >= max_scrolls:
                    break
                log.write_log("当前屏没有【领取】，向下滚动再找")
                if not self._scroll(ui):
                    log.write_log("滚动后画面没变化，判定没有更多【领取】了")
                    break
                scrolls += 1
                tried.clear()
                continue

            b = btns[0]
            key = (b["cx"], b["cy"])
            log.write_log("领取奖励：点【%s】(%d,%d)，等 %.0f 秒点下一个"
                          % (b["text"], b["cx"], b["cy"], CLAIM_WAIT))
            ui.tap((b["cx"], b["cy"]), pause=CLAIM_WAIT)
            tried[key] = tried.get(key, 0) + 1
            claimed += 1
            ui.invalidate()

        if claimed:
            log.write_log("共点了 %d 次【领取】" % claimed)
        else:
            log.write_log("当前屏没有【领取】按钮")
        return claimed

    def _scroll_to_top(self, ui, max_swipes=8):
        """把页面滚回任务列表顶部。

        做任务阶段会一路向下滚，结束时领取按钮多半已经在屏幕上方了。
        这里只滑不点，所以不会跳页；滑动次数有上限。
        """
        for i in range(max_swipes):
            before = self._page_hash(ui)
            ui.adb_swipe(ui.W // 2, int(ui.H * 0.35),
                         ui.W // 2, int(ui.H * 0.80), duration=400)
            ui.sleep(1.2)
            ui.invalidate()
            after = self._page_hash(ui)
            if before is not None and after is not None and before == after:
                return i
        return max_swipes

    def _scroll(self, ui):
        """在任务列表区域内向上滑一屏。"""
        x = ui.W // 2
        before = self._page_hash(ui)
        ui.adb_swipe(x, int(ui.H * 0.78), x, int(ui.H * 0.42), duration=500)
        ui.sleep(1.5)
        ui.invalidate()
        after = self._page_hash(ui)
        if before is None or after is None:
            return True
        return before != after

    def _page_hash(self, ui):
        try:
            src = ui.source()
            return hash(src) if src else None
        except Exception:
            return None
