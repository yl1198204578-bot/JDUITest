# -*- coding: utf-8 -*-
"""任务11【国家补贴x超级补贴】：京东首页卡片 -> 补贴页等 3s ->【查看奖励】
->【恭喜获得惊喜福利】弹窗 -> 做【浏览页面Xs+京豆】任务停留 X+4 秒
-> 逐个【领取奖励】->【开心收下】-> 循环直到任务列表没有可做任务。

真机实测（2026-11-12，1080x2340，Appium 3.9/uiautomator2）：
1. 首页入口是【国家补贴×超级补贴】商品卡，节点
   desc="国家补贴×超级补贴," bounds=(23,639,530,973)，整块及祖先都
   clickable=false，只有内部两个商品格子可点；点**标题条**
   (卡片中心 x, y1+44) 才进活动页，点商品格子会进商品详情。
2. 冷启动后首页会回弹（同 task1 的 _stable_kingkong_icon 坑）：
   必须连续两次 dump 入口卡片 bounds 一致再点，否则点空、停在首页。
3. 补贴页是 H5：顶部 icon 行【推荐/国家补贴/超级补贴/补贴超市/外卖补贴】
   能透出文字，但【天天领补贴】卡片和【查看奖励】按钮**完全没有节点文字**，
   H5 把可点区的 text 换成了埋点文案（"手动点击翻转测试"/"苹果手机"）。
   【查看奖励】只能按参考坐标 (270,796) 点（覆盖卡片 [22,564][517,839] 下部）。
4. 弹窗【恭喜获得惊喜福利】是叠加层，dump 里同时带着补贴页的商品卡/分类 tab，
   所以「弹窗在不在」只认弹窗独有标题，绝不能用背景页文案判断。
5. 弹窗 XML 文字完整（与种豆得豆活动页不同，别照抄旧结论去做 OCR）。
   任务行：标题【点击5个商品可领3京豆(0/2)】+ 副标题【浏览页面20秒】
   +【+3京豆】+ 右侧按钮【去看看】。按钮 TextView clickable=false，
   但整行有个 clickable View (22,1823,1058,2024)，按坐标点按钮中心有效。
6. 必须排除的行：【分享得红包 最高8.8元】+【去看看】（没有浏览Xs）、
   【邀请5人助力】+【立即邀请】、【已完成】。
   判定用「右侧按钮 ∈ {去看看,去完成} + 同行有【浏览页面Xs】」天然排除。
7. X 是动态的：同页混排【浏览页面20秒】【浏览页面10秒】【浏览页面10s】
   （小写 s 也要兼容），停留 = X + 4。
8. 点【去看看】跳落地页，**back 一次**就回弹窗（不像领水滴要穿多级）。
   做完后按钮变【领取奖励】，进度 (0/2)->(1/2)；点【领取奖励】弹
   【开心收下】(222,1265,858,1389,clickable=true)，点完关闭。
   领完后该任务重新变【去看看】且进度 +1（(0/5)->(1/5)->(2/5)），
   做满才变【已完成】——所以主循环必须「做一批 -> 领一批 -> 再检查」，
   且要有总任务数/总轮次上限防止任务池过大跑不完。
9. 弹窗列表可上下滚：上滑 7 屏到底、下滑 4 屏回顶，用节点签名判界。
   滚动后按钮 y 从 632 到 2340 都可能出现，一屏最多 9 个按钮但只有
   带【浏览页面Xs】的 2~5 个是可做任务。
10. 右侧有两个悬浮层：【3元】红包 (1019,1300,1053,1334) 带 desc=关闭，
    点 (1036,1317) 可关掉且不会误关弹窗；【￥8.8 补晚8加码】
    (929,1661,1072,1804) 从 x=929 起，而按钮中心 x≈926 恰好在它左侧，
    点按钮文字中心不会被挡。
11. H5 弹窗偶发给上一帧：刚点【查看奖励】那次 dump 可能只有 90 节点骨架，
    必须轮询等到弹窗标题出现；点任务/领奖前也一律重新读节点，
    绝不复用滚动前的 bounds。
"""
import re

from modules.base import BaseModule
import utils.driver as driver
from utils.jd_ui import JDUI

# ---------- 页面标记 ----------
ENTRY_MARK = u"国家补贴×超级补贴"
PAGE_MARKS = (u"补贴超市", u"超补惊喜权益", u"国家补贴x超级补贴")
PANEL_MARK = u"恭喜获得惊喜福利"
HAPPY_MARK = u"开心收下"
CLAIM_MARK = u"领取奖励"
BROWSE_BUTTON_TEXTS = (u"去看看", u"去完成")
DONE_TEXTS = (u"已完成", u"已领取", u"已结束")

# ---------- 坐标（参考分辨率 1080x2340，运行时按 sx/sy 缩放）----------
REWARD_POS = (270, 796)          # 【天天领补贴】卡片下部【查看奖励】
FLOAT_CLOSE_POS = (1036, 1317)   # 右侧【3元】红包浮层的关闭按钮
ENTRY_TITLE_DY = 44              # 点卡片标题条：y = bounds.y1 + 44

# ---------- 任务行 ----------
BROWSE_RE = re.compile(u"浏览页面\\s*(\\d+)\\s*[秒sS]")
PROGRESS_RE = re.compile(u"[（(]\\s*\\d+\\s*/\\s*\\d+\\s*[）)]")
BTN_MIN_X = 700                  # 任务按钮必须贴右
ROW_TOL = 75                     # 按钮与【浏览页面Xs】的 y 容差（行距约 195px）
BROWSE_EXTRA = 4                 # 停留 = X + 4 秒
SAFE_TOP = 600                   # 滚动后按钮最小 y≈632
# 弹窗是全屏 H5 覆盖层，底部没有原生导航条；真机第 4 行按钮
# (869,2296,984,2332) 的 y2=2332，旧值 2320 会把它整行过滤掉。
SAFE_BOTTOM = 2340               # = 屏幕高，只挡真正超出屏幕的节点

# ---------- 节奏与上限 ----------
PAGE_WAIT = 3.0                  # 需求：进补贴页等 3s 稳定
MAX_TASKS = 60                   # 总浏览次数上限（任务池很大，防跑不完）
MAX_CYCLES = 12                  # 「做一批->领一批」最大轮次
MAX_TASK_STEPS = 200             # 单轮最多扫描/动作步数
MAX_RETRY = 2                    # 单个任务连续失败几次后拉黑
MAX_SCROLLS = 10                 # 单轮最多滚动屏数
MAX_CLAIM_CLICKS = 60            # 单轮最多领取次数
MAX_READ_FAILS = 4               # 连续读不到页面
CLAIM_WAIT = 1.0                 # 领取后等待


# ---------------------------------------------------------------- 纯逻辑
def browse_seconds(x):
    """页面要求 X 秒 -> 实际停留 X + 4。"""
    return int(x) + BROWSE_EXTRA


def task_key(title, secs):
    """稳定行 id：去掉会随浏览次数变化的 (N/M) 进度。

    真机：点击4个商品可领京豆(0/5)->(1/5)->(2/5) 是同一个任务，
    标题带进度的原文不能做台账 key，否则每做一次都算新任务、防重复失效。
    """
    return PROGRESS_RE.sub(u"", title or u"") + u"|" + str(secs)


def parse_task_rows(nodes, btn_min_x=BTN_MIN_X, row_tol=ROW_TOL):
    """可做任务 = 右侧按钮【去看看/去完成】+ 同行【浏览页面Xs】。

    天然排除【分享得红包】(无浏览Xs)、【邀请5人助力】(按钮是立即邀请)、
    【已完成】【领取奖励】(不在按钮白名单)、以及背景页商品卡文案。

    返回 [{'title','secs','key','cx','cy','btn','btn_bounds'}]，按 cy 升序。
    """
    subs = []
    for n in nodes or []:
        b = n.get("bounds") or (0, 0, 0, 0)
        if b[3] <= b[1] or b[2] <= b[0]:
            continue
        m = BROWSE_RE.search((n.get("text") or "").strip())
        if m:
            # x1 用来给标题做「左对齐」判据：弹窗任务标题与副标题同列
            subs.append((int(m.group(1)), (b[1] + b[3]) // 2, b[0]))
    rows = []
    for n in nodes or []:
        b = n.get("bounds") or (0, 0, 0, 0)
        if b[3] <= b[1] or b[2] <= b[0]:
            continue
        txt = (n.get("text") or "").strip()
        if txt not in BROWSE_BUTTON_TEXTS:
            continue
        cx = (b[0] + b[2]) // 2
        cy = (b[1] + b[3]) // 2
        if cx < btn_min_x:
            continue
        cand = [(abs(cy - s[1]), s) for s in subs if abs(cy - s[1]) <= row_tol]
        if not cand:
            continue
        cand.sort(key=lambda z: z[0])
        sub = cand[0][1]
        secs = sub[0]
        title = _row_title(nodes, cy, b, sub[2], row_tol)
        rows.append({"title": title, "secs": secs,
                     "key": task_key(title, secs), "cx": cx, "cy": cy,
                     "btn": txt, "btn_bounds": b})
    rows.sort(key=lambda r: r["cy"])
    return rows


def _row_title(nodes, btn_cy, btn_bounds, sub_x1, row_tol=ROW_TOL):
    """按钮左侧同一行的任务标题。

    排序键「带 (N/M) 进度 > 与副标题左对齐 > 纵向最近 > 最靠左」。

    真机踩过（2026-11-12 scroll3）：有些任务标题不带进度，例如
    【超级明星抽8888红包】(192,1628,770,1677) 和【厨房卫浴补贴】
    (192,1823,770,1873)，此时旧版「最靠左」兜底会选中背景页商品卡
    【商超同款-樱花+玫瑰沐浴露2瓶装, 价格: 10.28元】(x1=22)。
    弹窗任务标题与【浏览页面Xs】副标题都从 x1≈192 起，背景页商品卡
    是 x1=22 或 434，用「与副标题 x1 差 <= 40」就能一判分开。
    """
    best = None
    for n in nodes or []:
        b = n.get("bounds") or (0, 0, 0, 0)
        if b[3] <= b[1] or b[2] <= b[0]:
            continue
        txt = (n.get("text") or "").strip()
        if not txt or BROWSE_RE.search(txt):
            continue
        if txt in BROWSE_BUTTON_TEXTS or txt in DONE_TEXTS or txt == CLAIM_MARK:
            continue
        if len(re.findall(u"[\u4e00-\u9fa5]", txt)) < 2:
            continue
        cy = (b[1] + b[3]) // 2
        if abs(cy - btn_cy) > row_tol:
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


def parse_claim_buttons(nodes, btn_min_x=BTN_MIN_X):
    """任务行右侧的【领取奖励】按钮，按 y 从上到下。"""
    out = []
    for n in nodes or []:
        b = n.get("bounds") or (0, 0, 0, 0)
        if b[3] <= b[1] or b[2] <= b[0]:
            continue
        if (n.get("text") or "").strip() != CLAIM_MARK:
            continue
        cx = (b[0] + b[2]) // 2
        if cx < btn_min_x:
            continue
        out.append({"cx": cx, "cy": (b[1] + b[3]) // 2, "bounds": b})
    out.sort(key=lambda r: r["cy"])
    return out


def find_happy(nodes):
    """【开心收下】按钮（弹窗独有，clickable=true）。"""
    for n in nodes or []:
        b = n.get("bounds") or (0, 0, 0, 0)
        if b[3] <= b[1] or b[2] <= b[0]:
            continue
        if (n.get("text") or "").strip() == HAPPY_MARK:
            return n
    return None


def is_bt_page(nodes):
    """是否已在【国家补贴x超级补贴】页。

    注意首页也有 desc='国家补贴' 的顶部 tab，但 PAGE_MARKS 用的是
    【补贴超市】/【超补惊喜权益】/小写 x 的页面根节点，首页都没有。
    """
    for n in nodes or []:
        t = (n.get("text") or "").strip()
        d = (n.get("desc") or "").strip()
        if any(m in t or m in d for m in PAGE_MARKS):
            return True
    return False


def is_panel(nodes):
    """任务弹窗是否在场：只认弹窗独有标题。

    弹层叠加在补贴页上，dump 里两页节点混在一起，绝不能用背景页文案判断。
    """
    return any(PANEL_MARK in ((n.get("text") or "").strip())
               for n in nodes or [])


def panel_sig(nodes):
    """弹窗指纹：按钮 + 浏览文案 + 带进度标题，用来判断滚动有没有到界。"""
    if not nodes:
        return None
    sig = []
    for n in nodes:
        t = (n.get("text") or "").strip()
        if not t:
            continue
        if (t in BROWSE_BUTTON_TEXTS or t == CLAIM_MARK or t in DONE_TEXTS
                or BROWSE_RE.search(t) or PROGRESS_RE.search(t)):
            sig.append(t)
    return tuple(sorted(sig))


def pick_target(rows, blacklist, safe_top=SAFE_TOP, safe_bottom=SAFE_BOTTOM):
    """挑一个没被拉黑、且在可点安全区里的任务行。"""
    for r in rows or []:
        if r["key"] in blacklist:
            continue
        b = r["btn_bounds"]
        if b[1] >= safe_top and b[3] <= safe_bottom:
            return r
    return None


def find_entry(nodes, mark=ENTRY_MARK):
    """首页【国家补贴×超级补贴】入口卡片（取最靠上的那个）。"""
    cands = [n for n in nodes or []
             if mark in ((n.get("desc") or "").strip())]
    cands = [n for n in cands
             if n["bounds"][3] > n["bounds"][1]
             and n["bounds"][2] > n["bounds"][0]]
    if not cands:
        return None
    cands.sort(key=lambda n: (n["bounds"][1], n["bounds"][0]))
    return cands[0]


# ---------------------------------------------------------------- 模块
class Task11Subsidy(BaseModule):
    name = u"国家补贴×超级补贴"
    description = (u"首页【国家补贴×超级补贴】卡片 → 等3s →【查看奖励】→ "
                   u"【恭喜获得惊喜福利】弹窗 → 做【浏览页面Xs+京豆】任务停留 X+4 秒 "
                   u"→ 逐个【领取奖励】→【开心收下】→ 循环至无可做任务")
    icon = u"\U0001F4B0"

    def run(self, log, stop_event):
        ui = JDUI(driver.get_driver(), log, stop_event)
        log.write_log(u"设备分辨率 %dx%d" % (ui.W, ui.H))

        if not self._open_panel(ui, log):
            raise RuntimeError(u"未能打开【恭喜获得惊喜福利】任务弹窗")
        if stop_event.is_set():
            return

        total_done = 0
        total_claimed = 0
        for cycle in range(MAX_CYCLES):
            if stop_event.is_set():
                break
            log.write_log(u"===== 第 %d 轮：做任务 -> 领奖励 =====" % (cycle + 1))
            self._scroll_top(ui)
            done = self._do_tasks(ui, log, stop_event, total_done)
            total_done += done
            if stop_event.is_set():
                break
            self._scroll_top(ui)
            claimed = self._claim_all(ui, log, stop_event)
            total_claimed += claimed
            log.write_log(u"第 %d 轮：完成浏览 %d 次，领取奖励 %d 次"
                          % (cycle + 1, done, claimed))
            if done == 0 and claimed == 0:
                log.write_log(u"任务列表已没有可做任务，结束")
                break
            if total_done >= MAX_TASKS:
                log.write_log(u"已达总浏览次数上限 %d，收尾" % MAX_TASKS, "WARN")
                break
        log.done(u"国家补贴×超级补贴 完成 %d 次浏览任务，领取 %d 次奖励"
                 % (total_done, total_claimed))

    # ---------- 入口 ----------
    def _open_panel(self, ui, log):
        """首页 -> 补贴页（等3s）->【查看奖励】-> 轮询等弹窗。"""
        if not ui.restart_to_home():
            log.write_log(u"冷启动回首页失败，走 goto_home", "WARN")
            if not ui.goto_home():
                return False
        ui.sleep(2)

        ent = self._stable_entry(ui, log)
        if ent is None:
            log.write_log(u"首页始终没找到【%s】入口卡片" % ENTRY_MARK, "WARN")
            return False
        b = ent["bounds"]
        pos = ((b[0] + b[2]) // 2, b[1] + ENTRY_TITLE_DY)
        log.write_log(u"命中首页入口卡片 %s，点标题条 (%d,%d)"
                      % (b, pos[0], pos[1]))
        ui.adb_tap(pos, pause=2.0)
        ui.sleep(PAGE_WAIT)                    # 需求：进页面等 3s 稳定
        ui.invalidate()

        if not self._wait_bt_page(ui, log):
            log.write_log(u"点了入口但没进补贴页，重试一次", "WARN")
            if not ui.goto_home():
                return False
            ent = self._stable_entry(ui, log)
            if ent is None:
                return False
            b = ent["bounds"]
            ui.adb_tap(((b[0] + b[2]) // 2, b[1] + ENTRY_TITLE_DY), pause=2.0)
            ui.sleep(PAGE_WAIT)
            if not self._wait_bt_page(ui, log):
                return False

        self._dismiss_float(ui, log)
        return self._tap_reward(ui, log)

    def _stable_entry(self, ui, log, tries=8):
        """冷启动后首页回弹：连续两次 dump 入口 bounds 一致才认为可点。"""
        last = None
        for i in range(tries):
            ns = self._nodes(ui, tries=1)
            cur = find_entry(ns)
            cur_b = cur["bounds"] if cur else None
            if cur_b is not None and last is not None and cur_b == last:
                log.write_log(u"入口卡片位置稳定 %s（第 %d 次读）" % (cur_b, i + 1))
                return cur
            last = cur_b
            ui.sleep(0.9)
        log.write_log(u"入口卡片位置未稳定，用最后一次 %s" % last, "WARN")
        return find_entry(self._nodes(ui, tries=2))

    def _wait_bt_page(self, ui, log, tries=10):
        for i in range(tries):
            ns = self._nodes(ui, tries=1)
            if ns and is_bt_page(ns):
                log.write_log(u"已进入【国家补贴x超级补贴】页（nodes=%d）" % len(ns))
                return True
            ui.sleep(1.2)
        log.write_log(u"等待补贴页超时", "WARN")
        return False

    def _tap_reward(self, ui, log, retries=2):
        """点【查看奖励】并轮询等弹窗标题出现（H5 偶发给上一帧骨架）。"""
        pos = (ui.sx(REWARD_POS[0]), ui.sy(REWARD_POS[1]))
        for k in range(retries):
            log.write_log(u"点【查看奖励】(%d,%d) 第 %d 次" % (pos[0], pos[1], k + 1))
            ui.adb_tap(pos, pause=2.0)
            for i in range(10):
                ns = self._nodes(ui, tries=1)
                if ns and is_panel(ns):
                    log.write_log(u"【%s】弹窗已渲染（第 %d 次读，nodes=%d）"
                                  % (PANEL_MARK, i + 1, len(ns)))
                    self._dismiss_float(ui, log)
                    return True
                ui.sleep(1.2)
            log.write_log(u"第 %d 次点【查看奖励】没弹出弹窗" % (k + 1), "WARN")
        return False

    def _dismiss_float(self, ui, log):
        """关掉右侧【3元】红包浮层；实测不会误关弹窗，失败不影响主流程。"""
        ns = self._nodes(ui, tries=1)
        has = any(u"关闭" in (n.get("desc") or "") for n in ns)
        if not has:
            return
        pos = (ui.sx(FLOAT_CLOSE_POS[0]), ui.sy(FLOAT_CLOSE_POS[1]))
        log.write_log(u"关掉右侧【3元】悬浮红包 (%d,%d)" % (pos[0], pos[1]))
        ui.adb_tap(pos, pause=1.0)

    # ---------- 做任务 ----------
    def _do_tasks(self, ui, log, stop_event, already):
        done = 0
        fails = {}
        success = {}
        blacklist = set()
        last_sig = None
        stagnant = 0
        read_fails = 0
        scrolls = 0

        for step in range(MAX_TASK_STEPS):
            if stop_event.is_set() or already + done >= MAX_TASKS:
                break
            ns = self._nodes(ui)
            if not ns:
                read_fails += 1
                if read_fails >= MAX_READ_FAILS:
                    log.write_log(u"连续 %d 次读不到页面，收尾" % read_fails, "WARN")
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
            row = pick_target(rows, blacklist)
            if row is None:
                # 当前屏没有可做任务：上滑一屏，连续两屏指纹相同即到底
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
            if ok:
                done += 1
                fails.pop(row["key"], None)
                log.write_log(u"浏览完成 #%d / 本轮 #%d（%ds）"
                              % (already + done, done, browse_seconds(row["secs"])))
                # 真机上做完该行按钮会变【领取奖励】。若后端刷新慢、按钮仍是
                # 【去看看】，不设防会对同一行反复浏览直到打满 MAX_TASKS。
                # 同一个任务需要多次进度（0/5->5/5）是**跨轮**发生的
                # （每轮领取后重新可做），本轮内连续做超过 2 次即视为异常。
                n = success.get(row["key"], 0) + 1
                success[row["key"]] = n
                if n > 2:
                    blacklist.add(row["key"])
                    log.write_log(u"任务【%s】本轮连续做 %d 次仍显示可做，"
                                  u"疑似状态未刷新，本轮拉黑" % (row["title"], n),
                                  "WARN")
            else:
                n = fails.get(row["key"], 0) + 1
                fails[row["key"]] = n
                if n > MAX_RETRY:
                    blacklist.add(row["key"])
                    log.write_log(u"任务【%s】连续 %d 次没做成功，本轮拉黑"
                                  % (row["title"], n), "WARN")
                else:
                    log.write_log(u"任务【%s】第 %d 次没做成功，稍后重试"
                                  % (row["title"], n), "WARN")
        return done

    def _do_one(self, ui, log, row, stop_event):
        """点按钮 -> 确认跳到落地页 -> 停留 X+4 -> back 回弹窗。"""
        dwell = browse_seconds(row["secs"])
        log.write_log(u"任务【%s】按钮【%s】%s，停留 %ds"
                      % (row["title"], row["btn"], row["btn_bounds"], dwell))
        ui.adb_tap((row["cx"], row["cy"]), pause=1.2)
        ui.invalidate()
        # 点完弹窗标题消失 = 真跳到落地页（点击没被动画吞掉）
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

    # ---------- 领奖 ----------
    def _claim_all(self, ui, log, stop_event):
        claimed = 0
        seen = {}
        last_sig = None
        stagnant = 0
        scrolls = 0
        self._scroll_top(ui)
        for step in range(MAX_CLAIM_CLICKS + MAX_SCROLLS):
            if stop_event.is_set() or claimed >= MAX_CLAIM_CLICKS:
                break
            ns = self._nodes(ui)
            if not ns or not is_panel(ns):
                log.write_log(u"领奖阶段弹窗不在，跳过", "WARN")
                break
            btns = parse_claim_buttons(ns)
            if not btns:
                s = panel_sig(ns)
                if s == last_sig:
                    stagnant += 1
                else:
                    stagnant = 0
                last_sig = s
                if stagnant >= 2 or scrolls >= MAX_SCROLLS:
                    break
                scrolls += 1
                self._swipe(ui, "up")
                continue
            last_sig = None
            b = btns[0]
            key = (b["cx"], b["cy"])
            if seen.get(key, 0) >= 2:
                rest = [x for x in btns if (x["cx"], x["cy"]) != key]
                if not rest:
                    break
                b = rest[0]
                key = (b["cx"], b["cy"])
            seen[key] = seen.get(key, 0) + 1
            ui.adb_tap((b["cx"], b["cy"]), pause=1.0)
            ui.invalidate()
            happy = None
            for _ in range(4):
                ns2 = self._nodes(ui, tries=1)
                happy = find_happy(ns2)
                if happy is not None:
                    break
                ui.sleep(0.7)
            if happy is None:
                log.write_log(u"点【领取奖励】没出现【开心收下】", "WARN")
                continue
            hb = happy["bounds"]
            ui.adb_tap(((hb[0] + hb[2]) // 2, (hb[1] + hb[3]) // 2),
                       pause=CLAIM_WAIT)
            claimed += 1
            ui.invalidate()
        if claimed:
            log.write_log(u"本轮共领取 %d 次奖励" % claimed)
        return claimed

    # ---------- 滚动与恢复 ----------
    def _swipe(self, ui, direction, distance=680):
        """在弹窗列表里滚一屏；x 用屏幕中线，避开右侧浮层。"""
        x = ui.W // 2
        y_hi, y_lo = ui.sy(2100), ui.sy(1420)
        if direction == "up":
            ui.adb_swipe(x, y_hi, x, y_lo, duration=450)
        else:
            ui.adb_swipe(x, y_lo, x, y_hi, duration=450)
        ui.sleep(1.4)
        ui.invalidate()

    def _scroll_top(self, ui, max_swipes=6):
        prev = None
        for _ in range(max_swipes):
            self._swipe(ui, "down")
            ns = self._nodes(ui, tries=1)
            s = panel_sig(ns)
            if s is not None and s == prev:
                break
            prev = s

    def _recover(self, ui, log):
        """弹窗丢了之后分级恢复：back -> 重点【查看奖励】-> 整链重进。"""
        for i in range(3):
            ns = self._nodes(ui, tries=1)
            if ns and is_panel(ns):
                if i:
                    log.write_log(u"返回 %d 次后弹窗又出现了" % i)
                return True
            if i == 0 and ns and is_bt_page(ns):
                # 还在补贴页，直接重点【查看奖励】
                if self._tap_reward(ui, log, retries=1):
                    log.write_log(u"就地重点【查看奖励】恢复成功")
                    return True
            ui.back(pause=1.5)
            ui.invalidate()
        log.write_log(u"恢复到补贴页重进", "WARN")
        if not self._wait_bt_page(ui, log, tries=4):
            return False
        return self._tap_reward(ui, log, retries=2)

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
