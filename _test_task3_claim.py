# -*- coding: utf-8 -*-
"""任务3【东东农场-领水滴】回归 v3：领奖阶段「不空滑」+「做任务<->领奖」交替循环。

对应用户 2026-11-13 的反馈：
  「任务屏数一共才 4~5 屏，但是尝试领取却划了 8 次，累计领取次数没发生变化，
    如果没找到去领取，不能再去完成浏览任务吗？」

覆盖点：
  P  _global_counts()：屏幕外节点（bounds 无效、displayed=false）也要数进来
  Q  领奖阶段全表没有【去领奖】-> 0 次滑动直接跳过（本次修复的核心）
  R  领奖阶段领到「已知数量」就收尾，不再把整张列表扫一遍
  S  _process_tasks：做任务 -> 领奖 -> 再做任务 交替循环（领取后新放出的任务不丢）
  T  有界退出：XML 说有【去领奖】但永远滚不到时，靠 MAX_CLAIM_IDLE_SCROLLS 收尾

不连手机、不连 Appium：所有 UI 都是本地模拟器。
"""
import io
import os
import re
import sys
import types

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

mock_driver = types.ModuleType("utils.driver")
mock_driver.get_driver = lambda: None
sys.modules["utils.driver"] = mock_driver

import modules.task3_farm_drops as mod
from modules.task3_farm_drops import (
    Task3FarmDrops, BROWSE_BUTTON_TEXTS, CLAIM_BUTTON_TEXTS, BROWSE_DESC_KEY,
    MAX_CLAIM_IDLE_SCROLLS,
)

PASSED, FAILED = [], []


def check(name, cond, detail=""):
    if cond:
        PASSED.append(name)
        print("PASS %s %s" % (name, detail))
    else:
        FAILED.append(name)
        print("FAIL %s %s" % (name, detail))


class BoundsMixin(object):
    W, H = 1080, 2340
    stop = None

    @staticmethod
    def parse_bounds(raw):
        m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", raw or "")
        if not m:
            return None
        x1, y1, x2, y2 = [int(v) for v in m.groups()]
        if x2 <= x1 or y2 <= y1:
            return None
        return (x1, y1, x2, y2)

    @staticmethod
    def center(node):
        x1, y1, x2, y2 = node["bounds"]
        return ((x1 + x2) // 2, (y1 + y2) // 2)


BROWSE = u"浏览6秒，奖励+10g"


class ListSim(BoundsMixin):
    """长任务列表弹窗模拟器（与真机同一套 bounds 规则）。

    rows 每项 {'desc':..., 'btn':...}；`fixed_y` 可把某行钉在固定 y
    （用来模拟「XML 里有、但永远滚不到」的幽灵行）。
    """

    STEP = 670
    ROW_H = 225
    TOP = 805

    def __init__(self, rows, max_offset=None, unlock_on_claim=None):
        self.rows = [dict(r) for r in rows]
        self.offset = 0
        self.in_browse = False
        self.taps = []
        self.swipes = []
        self.unlock_on_claim = list(unlock_on_claim or [])
        self.max_offset = (max(len(self.rows) * self.ROW_H - 1200, 0)
                           if max_offset is None else max_offset)

    # ---- 页面 ----
    def source(self, fresh=False):
        if self.in_browse:
            return ('<?xml version="1.0" encoding="UTF-8"?><hierarchy>'
                    '<node text="浏览商品详情页" bounds="[0,0][1080,200]" '
                    'displayed="true" clickable="false"/></hierarchy>')
        p = ['<?xml version="1.0" encoding="UTF-8"?><hierarchy>',
             '<node text="关闭任务面板" bounds="[900,600][1000,660]" '
             'displayed="true" clickable="true"/>']
        for i, r in enumerate(self.rows):
            top = r.get("fixed_y")
            if top is None:
                top = self.TOP + i * self.ROW_H - self.offset
            if 0 <= top and top + 100 <= self.H:
                bb = "[838,%d][1025,%d]" % (top, top + 86)
                db = "[189,%d][770,%d]" % (top + 50, top + 100)
                disp = "true"
            else:
                y = max(top, self.H + 1)
                bb = "[838,%d][1025,%d]" % (y, self.H + 1)
                db = "[189,%d][770,%d]" % (y + 50, self.H + 1)
                disp = "false"
            p.append('<node text="%s" bounds="%s" displayed="%s" clickable="false"/>'
                     % (r["btn"], bb, disp))
            p.append('<node text="%s" bounds="%s" displayed="%s" clickable="false"/>'
                     % (r["desc"], db, disp))
        p.append("</hierarchy>")
        return "".join(p)

    def invalidate(self):
        pass

    def sleep(self, seconds):
        return True

    def snapshot(self, name):
        pass

    def swipe(self, key, pause=1.0):
        self.swipes.append(key)
        if key == "task_list":
            self.offset = min(self.max_offset, self.offset + self.STEP)
        elif key == "task_list_down":
            self.offset = max(0, self.offset - self.STEP)

    def back(self, pause=2.0):
        self.in_browse = False

    def tap(self, xy, pause=1.0):
        self.taps.append(xy)
        if self.in_browse:
            return
        y = xy[1]
        for i, r in enumerate(self.rows):
            top = r.get("fixed_y")
            if top is None:
                top = self.TOP + i * self.ROW_H - self.offset
            if not (top <= y <= top + 86):
                continue
            if r["btn"] in BROWSE_BUTTON_TEXTS:
                r["btn"] = u"去领奖"
                self.in_browse = True
            elif r["btn"] in CLAIM_BUTTON_TEXTS:
                r["btn"] = u"已领取"
                for extra in self.unlock_on_claim:
                    self.rows.append(dict(extra))
                self.unlock_on_claim = []
            return


class Log(object):
    def __init__(self):
        self.lines = []

    def write_log(self, msg, level="INFO"):
        self.lines.append((level, msg))

    def done(self, msg):
        pass

    def error(self, msg):
        pass

    def text(self):
        return "\n".join(m for _, m in self.lines)


class Stop(object):
    def __init__(self, flag=False):
        self.flag = flag

    def is_set(self):
        return self.flag


def xml_rows(rows):
    """直接把 rows 渲染成弹窗 XML（测 _global_counts 用）。"""
    p = ['<?xml version="1.0" encoding="UTF-8"?><hierarchy>',
         '<node text="关闭任务面板" bounds="[900,600][1000,660]" '
         'displayed="true" clickable="true"/>']
    for i, r in enumerate(rows):
        top = r.get("y", 805 + i * 225)
        valid = r.get("valid", True)
        if valid:
            bb = "[838,%d][1025,%d]" % (top, top + 86)
            db = "[189,%d][770,%d]" % (top + 50, top + 100)
            disp = "true"
        else:
            bb = "[838,%d][1025,%d]" % (2341, 2341)
            db = "[189,%d][770,%d]" % (2391, 2341)
            disp = "false"
        p.append('<node text="%s" bounds="%s" displayed="%s" clickable="false"/>'
                 % (r["btn"], bb, disp))
        p.append('<node text="%s" bounds="%s" displayed="%s" clickable="false"/>'
                 % (r["desc"], db, disp))
    p.append("</hierarchy>")
    return "".join(p)


class XmlUI(BoundsMixin):
    def __init__(self, xml):
        self._xml = xml

    def source(self, fresh=False):
        return self._xml

    def invalidate(self):
        pass


mod_task = Task3FarmDrops()

# ======================================================================
print("=== P: _global_counts 把屏幕外节点也算进来 ===")
rows = [
    {"desc": BROWSE, "btn": u"去领奖", "valid": True, "y": 805},
    {"desc": BROWSE, "btn": u"去领奖", "valid": False},
    {"desc": BROWSE, "btn": u"去领奖", "valid": False},
    {"desc": BROWSE, "btn": u"已领取", "valid": False},
]
ui = XmlUI(xml_rows(rows))
c = mod_task._global_counts(ui)
check("P1 3 个【去领奖】里 2 个在屏幕外也要数到", c["claim"] == 3, "claim=%d" % c["claim"])
check("P2 已领取也计入 done", c["done"] == 1, "done=%d" % c["done"])

rows = [{"desc": BROWSE, "btn": u"已领取"} for _ in range(4)]
c = mod_task._global_counts(XmlUI(xml_rows(rows)))
check("P3 全是已领取时 claim=0", c["claim"] == 0 and c["done"] == 4, str(c))

c = mod_task._global_counts(XmlUI(""))
check("P4 空 XML 不炸", c == {"claim": 0, "done": 0}, str(c))

# ======================================================================
print("\n=== Q: 全表没有【去领奖】-> 一次都不滑（本次修复核心） ===")
sim = ListSim([{"desc": BROWSE, "btn": u"已领取"} for _ in range(30)])
log = Log()
n, _, aborted = mod_task._phase_claim(sim, log, Stop(), 0)
check("Q1 没奖可领时领奖数为 0", n == 0, "claim=%d" % n)
check("Q2 没奖可领时一次 task_list 都不滑",
      sim.swipes.count("task_list") == 0, "swipes=%r" % sim.swipes)
check("Q3 日志说明跳过原因",
      u"跳过领奖、不再空滑" in log.text(), log.text()[-80:])
check("Q4 没被误判成中断", aborted is False, "aborted=%r" % aborted)

# 老行为对照：真机弹窗列表 XML 的 y 从 805 排到 7375（约 6570px），
# 而 task_list 一次只滑 670px（约 0.44 屏），所以老逻辑要滑 8 次以上才到底。
check("Q5 对照：同规模列表老逻辑要滑 8 次以上才到底",
      (30 * 225 - 1200) // ListSim.STEP >= 8,
      "max_offset=%d step=%d -> %d 次" % (
          sim.max_offset, ListSim.STEP,
          (30 * 225 - 1200) // ListSim.STEP))

# ======================================================================
print("\n=== R: 领到「已知数量」就收尾，不整表扫一遍 ===")
rows = [{"desc": u"下单得10g", "btn": u"去完成"} for _ in range(4)]
rows += [{"desc": BROWSE, "btn": u"去领奖"}]
rows += [{"desc": u"签到得5g", "btn": u"去完成"} for _ in range(4)]
rows += [{"desc": BROWSE, "btn": u"去领奖"}]
rows += [{"desc": u"邀请得20g", "btn": u"去完成"} for _ in range(6)]
sim = ListSim(rows)
log = Log()
n, _, aborted = mod_task._phase_claim(sim, log, Stop(), 0)
check("R1 两个【去领奖】都领到", n == 2, "claim=%d" % n)
check("R2 领完立刻收尾，没有继续往下扫",
      u"列表里已没有【去领奖】，领奖完成" in log.text(), log.text()[-100:])
check("R3 滑屏次数远小于整表 15 行所需",
      sim.swipes.count("task_list") <= 2, "task_list=%d" % sim.swipes.count("task_list"))
check("R4 开局日志报出待领数量",
      u"列表里还有 2 个【去领奖】待领" in log.text(), "")

# ======================================================================
print("\n=== S: 做任务 -> 领奖 -> 再做任务 交替循环 ===")
sim = ListSim(
    [{"desc": BROWSE, "btn": u"去完成"}],
    unlock_on_claim=[{"desc": u"浏览6秒，奖励+30g", "btn": u"去完成"}],
)
log = Log()
b, c = mod_task._process_tasks(sim, log, Stop())
check("S1 第 2 轮把领取后新放出的任务也做了", b == 2, "browse=%d" % b)
check("S2 两轮共领 2 次", c == 2, "claim=%d" % c)
check("S3 日志有「继续下一轮」", u"继续下一轮" in log.text(), "")
check("S4 日志里出现第 2 轮标题", u"第 2 轮" in log.text(), "")

# 领不到奖励时要回浏览阶段确认（用户原话：没找到去领取，能不能再去完成浏览任务）
sim = ListSim([{"desc": BROWSE, "btn": u"去完成"}])
sim.rows[0]["btn"] = u"去完成"
orig_tap = sim.tap


def tap_that_swallows(xy, pause=1.0):
    """点【去完成】不生效（模拟被弹层动画吞掉），于是永远领不到奖励。"""
    sim.taps.append(xy)
    return


sim.tap = tap_that_swallows
log = Log()
b, c = mod_task._process_tasks(sim, log, Stop())
check("S5 领不到奖励时回到浏览阶段再确认", u"回到浏览任务再确认一次" in log.text(),
      log.text()[-120:])
check("S6 有界：不会无限循环", u"第 3 轮" not in log.text(), "")

# ======================================================================
print("\n=== T: 幽灵【去领奖】（XML 有、永远滚不到）要有界收尾 ===")
rows = [{"desc": BROWSE, "btn": u"去领奖", "fixed_y": 5000} for _ in range(2)]
rows += [{"desc": u"下单得10g", "btn": u"去完成"} for _ in range(12)]
sim = ListSim(rows, max_offset=6000)
log = Log()
n, _, aborted = mod_task._phase_claim(sim, log, Stop(), 0)
check("T1 幽灵按钮不会无限滑", sim.swipes.count("task_list") <= MAX_CLAIM_IDLE_SCROLLS,
      "task_list=%d" % sim.swipes.count("task_list"))
check("T2 最终领取数为 0", n == 0, "claim=%d" % n)
check("T3 有兜底日志", (u"连续 %d 屏没有【去领奖】" % MAX_CLAIM_IDLE_SCROLLS) in log.text()
      or u"已到列表底部" in log.text(), log.text()[-120:])

# ======================================================================
print("\n=== U: stop_event 立即生效 ===")
sim = ListSim([{"desc": BROWSE, "btn": u"去领奖"}])
n, _, aborted = mod_task._phase_claim(sim, Log(), Stop(True), 0)
check("U1 预先 stop 不领奖", n == 0 and aborted is True, "n=%d aborted=%r" % (n, aborted))

print("\n==== %d passed, %d failed ====" % (len(PASSED), len(FAILED)))
if FAILED:
    for f in FAILED:
        print("  FAILED: %s" % f)
    sys.exit(1)
