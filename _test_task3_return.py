# -*- coding: utf-8 -*-
"""任务3 回归 v3：浏览后「回不到任务面板」问题（不连手机）。

用户 2026-11-11 反馈：领水滴任务没跑完，清单里其实还有任务，
「再浏览任务的时候可能受弹窗影响，无法返回」。

复现证据（全部来自真机采集的 XML）：
  _drops/dialog3.xml      系统跳转确认「京东 想要打开 百度，是否允许？」
  _drops/after_do.xml     京东直播页「继续浏览4秒」/「关闭直播间」
  _drops/do_first.xml     商品详情页（左上角 返回）
  _drops/dialog2.xml      只有「返回」的过渡页
  _drops/dialog4.xml      农场 H5「哎呀，出了点问题」/「重新连接」
  _live_now.xml           京东首页 +「浮层活动」浮层
  _drops/probe_check.xml  频道/首页 +「浮层活动」浮层

旧实现的死穴：_do_one_browse 只按一次 back(2)，回不来就 return "stopped"
掐断整个 Phase 1，后面的任务一个都不做。本套用例验证新的分步恢复。
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

from modules.task3_farm_drops import (
    Task3FarmDrops, BROWSE_DESC_KEY, BROWSE_BUTTON_TEXTS, CLAIM_BUTTON_TEXTS,
    ST_DIALOG, ST_JUMP, ST_OVERLAY, ST_HOME, ST_FARM_ERR, ST_FARM, ST_BROWSE,
)

PASSED, FAILED = [], []


def check(name, cond, detail=""):
    if cond:
        PASSED.append(name)
        print("PASS %s %s" % (name, detail))
    else:
        FAILED.append(name)
        print("FAIL %s %s" % (name, detail))


class Bounds(object):
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


def read(path):
    with io.open(path, encoding="utf-8-sig", errors="replace") as f:
        return f.read()


D = os.path.join(ROOT, "_drops")
XML = {
    "dialog": read(os.path.join(D, "dialog5.xml")),
    "jump": read(os.path.join(D, "dialog3.xml")),
    "live": read(os.path.join(D, "after_do.xml")),
    "product": read(os.path.join(D, "do_first.xml")),
    "transit": read(os.path.join(D, "dialog2.xml")),
    "farm_err": read(os.path.join(D, "dialog4.xml")),
    "home_overlay": read(os.path.join(ROOT, "_live_now.xml")),
    "probe": read(os.path.join(D, "probe_check.xml")),
}
# 真机商品详情页把提示渲染成竖排文字（节点内带换行），且这屏没有「返回」
VERTICAL_XML = (
    '<?xml version="1.0" encoding="UTF-8"?><hierarchy>'
    '<node text="继\n续\n滑\n动\n查\n看\n图\n文\n详\n情" '
    'bounds="[400,1800][680,1900]" displayed="true" clickable="false"/>'
    '<node text="啄木鸟两件套装" bounds="[44,300][900,400]" '
    'displayed="true" clickable="false"/>'
    '</hierarchy>')

HOME_XML = (
    '<?xml version="1.0" encoding="UTF-8"?><hierarchy>'
    '<node text="东东农场" content-desc="东东农场" bounds="[100,900][200,1000]" '
    'displayed="true" clickable="true"/>'
    '<node text="首页" content-desc="首页, 已选中" bounds="[0,2200][200,2340]" '
    'displayed="true" clickable="true"/>'
    '</hierarchy>')


class StaticUI(Bounds):
    """固定页面的假 UI，可记录 tap/back，并支持按脚本推进页面。"""

    def __init__(self, pages):
        self.pages = list(pages)
        self.taps = []
        self.backs = []
        self.swipes = []

    def source(self, fresh=False):
        return self.pages[0]

    def invalidate(self):
        pass

    def sleep(self, seconds):
        return True

    def back(self, pause=2.0):
        self.backs.append(pause)
        if len(self.pages) > 1:
            self.pages.pop(0)

    def tap(self, xy, pause=1.0):
        self.taps.append(xy)

    def swipe(self, key, pause=1.0):
        self.swipes.append(key)

    def goto_home(self):
        return True

    def open_farm(self):
        return True


class ChainUI(StaticUI):
    """浏览态下点击拦截层按钮（拒绝 / 重新连接）会推进一层返回链。"""

    def tap(self, xy, pause=1.0):
        StaticUI.tap(self, xy, pause)
        if len(self.pages) > 1:
            self.pages.pop(0)


class Log(object):
    def __init__(self):
        self.lines = []

    def write_log(self, msg, level="INFO"):
        self.lines.append((level, msg))

    def done(self, msg):
        pass

    def error(self, msg):
        pass


class Stop(object):
    def is_set(self):
        return False


mod = Task3FarmDrops()

# ---------- P: 真机 XML 的页面分类 ----------
print("=== P: 页面分类（真机 XML） ===")
cases = [
    ("P 任务弹窗", "dialog", ST_DIALOG),
    ("P 系统跳转确认", "jump", ST_JUMP),
    ("P 京东直播浏览页", "live", ST_BROWSE),
    ("P 商品详情浏览页", "product", ST_BROWSE),
    ("P 只有返回的过渡页", "transit", ST_BROWSE),
    ("P 农场 H5 断连页", "farm_err", ST_FARM_ERR),
    ("P 首页+浮层", "home_overlay", ST_OVERLAY),
    ("P 频道页+浮层", "probe", ST_OVERLAY),
    ("P 纯首页（无浮层）", HOME_XML, ST_HOME),
    ("P 竖排文字的商品详情页", VERTICAL_XML, ST_BROWSE),
]
for name, page, expected in cases:
    xml = page if page.startswith("<?xml") else XML[page]
    got = mod._classify(StaticUI([xml]))
    check(name, got == expected, "got=%s expected=%s" % (got, expected))

# 首页也带 text="东东农场"，必须判成 HOME 而不是 FARM
check("P 首页不会被误判成农场页", mod._classify(StaticUI([HOME_XML])) != ST_FARM)

# ---------- Q: 拦截层清理，绝不点「始终允许」 ----------
print("=== Q: 拦截层清理 ===")
ui = StaticUI([XML["jump"]])
cleared = mod._clear_blockers(ui, Log())
refuse = (310, 2174)      # 拒绝 [98,2105][523,2243] 的中心
always = (768, 2174)      # 始终允许 [556,2105][981,2243] 的中心
check("Q 系统跳转确认被点掉", cleared is True)
check("Q 点的是【拒绝】", ui.taps == [refuse], str(ui.taps))
check("Q 绝不点【始终允许】", always not in ui.taps, str(ui.taps))
check("Q 正常任务弹窗不会误点",
      mod._clear_blockers(StaticUI([XML["dialog"]]), Log()) is False)
ui2 = StaticUI([XML["dialog"]])
mod._clear_blockers(ui2, Log())
check("Q 正常弹窗零点击", ui2.taps == [], str(ui2.taps))

# ---------- R: 系统弹窗盖住时不能误判「已在弹窗」 ----------
print("=== R: 弹窗判定防误判 ===")
check("R 跳转确认不算任务弹窗",
      mod._is_drops_dialog(StaticUI([XML["jump"]])) is False)
composite = XML["jump"].replace("</hierarchy>", "") + \
    '<node text="关闭任务面板" bounds="[900,600][1000,660]" ' \
    'displayed="true" clickable="true"/></hierarchy>'
check("R 系统弹窗盖在任务弹窗上仍不算",
      mod._is_drops_dialog(StaticUI([composite])) is False)
check("R 正常任务弹窗仍认得",
      mod._is_drops_dialog(StaticUI([XML["dialog"]])) is True)

# ---------- S: 多级返回状态机 ----------
print("=== S: 分步返回（旧实现一次 back 必挂） ===")
# 真实链路：直播浏览页 -> 系统跳转确认 -> 农场断连页 -> 任务弹窗
chain = [XML["live"], XML["jump"], XML["farm_err"], XML["dialog"]]
ui = ChainUI(chain)
log = Log()
res = mod._ensure_dialog(ui, log, Stop())
check("S 多级链路能回到弹窗", res == "ok", "res=%s" % res)
check("S 链路不止一步（证明一次 back 不够）", len(chain) > 2)
check("S 至少按了返回键", len(ui.backs) >= 1, "backs=%d" % len(ui.backs))
check("S 清掉了【拒绝】", refuse in ui.taps, str(ui.taps))
check("S 点过【重新连接】",
      any(abs(x - 541) < 5 and abs(y - 1916) < 20 for x, y in ui.taps),
      str(ui.taps))

# 链路以首页收尾 -> 必须交出去重建入口
chain_home = [XML["live"], XML["jump"], HOME_XML]
ui = ChainUI(chain_home)
res = mod._ensure_dialog(ui, Log(), Stop())
check("S 落到首页时返回 home 信号", res == "home", "res=%s" % res)

# ---------- U: 滑动被浮层吞掉时不能误判「到底」 ----------
print("=== U: 到底判定不被浮层骗 ===")
class SwallowUI(StaticUI):
    """第一屏滑动被浮层吞掉（指纹不变），清掉浮层后滑动才生效。"""

    def __init__(self):
        StaticUI.__init__(self, [XML["dialog"]])
        self.blocked = True

    def swipe(self, key, pause=1.0):
        StaticUI.swipe(self, key, pause)
        if not self.blocked and key == "task_list":
            self.pages = [XML["dialog"].replace("[189,858]", "[189,158]")]

    def tap(self, xy, pause=1.0):
        StaticUI.tap(self, xy, pause)
        self.blocked = False


class BlockUI(SwallowUI):
    """伪造一个带「关闭浮层活动」按钮的屏，让 _clear_blockers 有东西可点。"""

    def source(self, fresh=False):
        if not self.blocked:
            return StaticUI.source(self, fresh)
        return (XML["dialog"].replace(
            "</hierarchy>",
            '<node text="关闭浮层活动" bounds="[900,600][1000,660]" '
            'displayed="true" clickable="true"/></hierarchy>'))


bui = BlockUI()
ok = mod._scroll_down(bui, Log())
check("U 滑不动时先清拦截层再重试", ok is True)
check("U 确实点掉了浮层关闭按钮", len(bui.taps) == 1, str(bui.taps))
check("U 一共滑了两次（含确认滑）", bui.swipes.count("task_list") == 2,
      str(bui.swipes))

# ---------- V: 全流程 —— 一个任务被弹窗链打断，剩余任务仍要做完 ----------
print("=== V: 被打断后不终止整个列表 ===")
BROWSE = "浏览6秒，奖励+10g"
layout = [
    (BROWSE, "逛一逛"),
    ("下1单奖励+3000g", "去完成"),
    (BROWSE, "去完成"),                 # chaos_idx=2：走完整弹窗链 + 重建入口
    ("完成任务奖励+150g", "去完成"),
    ("浏览6秒，奖励+30g", "逛一逛"),
    (BROWSE, "逛一逛"),
    ("访问并登录奖励+50g", "去完成"),
    (BROWSE, "去完成"),
    (BROWSE, "逛一逛"),
    ("浏览6秒，奖励+20g", "逛一逛"),
    (BROWSE, "去完成"),
]
non_browse_idx = (1, 3, 6)
chaos_idx = 2
expected = sum(1 for d, _ in layout if BROWSE_DESC_KEY in d and "奖励" in d)


class ChaosUI(Bounds):
    """长列表 + 可脚本化的「浏览后返回链」。"""

    STEP = 670
    ROW_H = 225
    TOP = 805

    def __init__(self, rows):
        self.rows = [dict(r) for r in rows]
        self.offset = 0
        self.chain = []            # in_browse 时的页面链
        self.taps = []
        self.backs = []
        self.swipes = []
        self.reenters = 0
        self.max_offset = max(0, len(rows) * self.ROW_H - 1200)

    @property
    def in_browse(self):
        return bool(self.chain)

    def goto_home(self):
        self.chain = []
        return True

    def open_farm(self):
        """重建入口：回到弹窗顶部，任务状态（服务端）保持不变。"""
        self.chain = []
        self.offset = 0
        self.reenters += 1
        return True

    def source(self, fresh=False):
        if self.chain:
            return self.chain[0]
        p = ['<?xml version="1.0" encoding="UTF-8"?><hierarchy>',
             '<node text="关闭任务面板" bounds="[900,600][1000,660]" '
             'displayed="true" clickable="true"/>',
             '<node text="点击前往做任务领水滴页面" resource-id="expo_task_icon" '
             'bounds="[401,1520][577,1713]" displayed="true" clickable="true"/>']
        for i, r in enumerate(self.rows):
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

    def swipe(self, key, pause=1.0):
        self.swipes.append(key)
        if key == "task_list":
            self.offset = min(self.max_offset, self.offset + self.STEP)
        elif key == "task_list_down":
            self.offset = max(0, self.offset - self.STEP)

    def back(self, pause=2.0):
        self.backs.append(pause)
        if self.chain:
            self.chain.pop(0)

    def tap(self, xy, pause=1.0):
        self.taps.append(xy)
        if self.chain:
            # 浏览态：任何点击（拒绝 / 重新连接）都推进一层返回链
            if self.chain:
                self.chain.pop(0)
            return
        y = xy[1]
        for i, r in enumerate(self.rows):
            top = self.TOP + i * self.ROW_H - self.offset
            if not (top <= y <= top + 86):
                continue
            if r["btn"] in BROWSE_BUTTON_TEXTS:
                r["btn"] = "去领奖"
                if i == chaos_idx:
                    # 直播页 -> 系统跳转确认 -> 农场断连 -> 首页（需重建入口）
                    self.chain = [XML["live"], XML["jump"],
                                  XML["farm_err"], HOME_XML]
                else:
                    self.chain = [XML["live"]]
            elif r["btn"] in CLAIM_BUTTON_TEXTS:
                r["btn"] = "已领取"
            return


sim = ChaosUI([{"desc": d, "btn": b} for d, b in layout])
log = Log()
browse_cnt, claim_cnt = mod._process_tasks(sim, log, Stop())

check("V 全部浏览任务都做完", browse_cnt == expected,
      "browse=%d expected=%d" % (browse_cnt, expected))
check("V 领奖次数等于浏览任务数", claim_cnt == expected,
      "claim=%d expected=%d" % (claim_cnt, expected))
check("V 被打断的那个任务没被丢弃",
      sim.rows[chaos_idx]["btn"] == "已领取",
      "btn=%s" % sim.rows[chaos_idx]["btn"])
check("V 确实发生了入口重建", sim.reenters >= 1,
      "reenters=%d" % sim.reenters)
check("V 非浏览任务没被误点",
      all(sim.rows[i]["btn"] == "去完成" for i in non_browse_idx),
      str([sim.rows[i]["btn"] for i in non_browse_idx]))
check("V 所有浏览行最终为已领取",
      all(sim.rows[i]["btn"] == "已领取" for i in range(len(layout))
          if i not in non_browse_idx))
check("V 日志里有清拦截层记录",
      any("清掉拦截层【拒绝】" in m for lv, m in log.lines))
check("V 日志里有重建入口记录",
      any("重建入口" in m for lv, m in log.lines))
check("V 没有出现「停止浏览任务」这类旧式提前退出",
      not any("弹窗已关闭，停止浏览任务" in m for lv, m in log.lines))
check("V 重建后仍继续向下滚动找剩余任务",
      sim.swipes.count("task_list") >= 3,
      "task_list=%d" % sim.swipes.count("task_list"))

print("\n==== %d passed, %d failed ====" % (len(PASSED), len(FAILED)))
if FAILED:
    for f in FAILED:
        print("  FAILED: %s" % f)
    sys.exit(1)
