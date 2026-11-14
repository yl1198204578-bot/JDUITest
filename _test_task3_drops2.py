# -*- coding: utf-8 -*-
"""任务3【东东农场-领水滴】回归 v2（不连手机）。

覆盖用户 2026-11-11 反馈的三个问题：
  1. 只认「描述含 浏览6秒，奖励」+「按钮为 去完成/逛一逛」的未做任务，
     一次扫出当前屏全部此类行；非浏览任务的「去完成」不能被误点。
  2. 逐屏下滑，把全部未做任务做完，不能因为中间几屏没有任务就提前退出。
  3. 做完后回列表顶部，从第一个【去领奖/去领取】逐个领取直到没有。

证据来自真机采集的 _drops/*.xml；SimUI 用同一套 bounds 规则模拟长列表滚动。
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
    Task3FarmDrops, BROWSE_BUTTON_TEXTS, CLAIM_BUTTON_TEXTS,
    BROWSE_DESC_KEY,
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


class FakeUI(BoundsMixin):
    def __init__(self, xml_or_path):
        if os.path.isfile(xml_or_path):
            with open(xml_or_path, encoding="utf-8-sig", errors="replace") as f:
                xml_or_path = f.read()
        self._xml = xml_or_path

    def source(self, fresh=False):
        return self._xml

    def invalidate(self):
        pass


class SimUI(BoundsMixin):
    """长任务列表弹窗模拟器。

    真机规律：屏幕内节点 bounds 有效且 displayed=true；屏幕外节点 bounds
    被裁成 [838,y][1025,2341]（y1>y2，无效）且 displayed=false。
    swipe 平移 offset，tap 按 y 找到行并推进按钮状态。
    """
    STEP = 670
    ROW_H = 225
    TOP = 805

    def __init__(self, rows, max_offset=None):
        self.rows = [dict(r) for r in rows]
        self.offset = 0
        self.in_browse = False
        self.taps = []
        self.swipes = []
        self.max_offset = (len(rows) * self.ROW_H - 1200) if max_offset is None else max_offset

    def source(self, fresh=False):
        if self.in_browse:
            return ('<?xml version="1.0" encoding="UTF-8"?><hierarchy>'
                    '<node text="浏览商品详情页" bounds="[0,0][1080,200]" '
                    'displayed="true" clickable="false"/></hierarchy>')
        p = ['<?xml version="1.0" encoding="UTF-8"?><hierarchy>',
             '<node text="关闭任务面板" bounds="[900,600][1000,660]" '
             'displayed="true" clickable="true"/>']
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
        self.invalidate()

    def back(self, pause=2.0):
        self.in_browse = False
        self.invalidate()

    def tap(self, xy, pause=1.0):
        self.taps.append(xy)
        y = xy[1]
        for i, r in enumerate(self.rows):
            top = self.TOP + i * self.ROW_H - self.offset
            if not (top <= y <= top + 86):
                continue
            if r["btn"] in BROWSE_BUTTON_TEXTS:
                r["btn"] = "去领奖"
                self.in_browse = True
            elif r["btn"] in CLAIM_BUTTON_TEXTS:
                r["btn"] = "已领取"
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


class Stop(object):
    def is_set(self):
        return False


mod = Task3FarmDrops()
DIALOG = os.path.join(ROOT, "_drops", "dialog.xml")
MID = os.path.join(ROOT, "_drops", "mid.xml")
LIST2 = os.path.join(ROOT, "_drops", "list2.xml")

# ---------- I: 当前屏一次扫出全部未做任务，且条件严格 ----------
print("=== I: 未做任务识别 ===")
ui = FakeUI(DIALOG)
rows = mod._find_browse_rows(ui)
check("I 扫出未做任务", len(rows) >= 1, "rows=%d" % len(rows))
check("I 按钮都是 去完成/逛一逛",
      all(r["btn_text"] in BROWSE_BUTTON_TEXTS for r in rows),
      str([r["btn_text"] for r in rows]))
check("I 描述都含 浏览6秒 + 奖励",
      all(BROWSE_DESC_KEY in r["desc"] and "奖励" in r["desc"] for r in rows),
      str([r["desc"] for r in rows]))
# dialog.xml 里共 12 条「浏览6秒」描述，但只有 2 条 bounds 有效；
# 其中 y=858 那条按钮已是【去领奖】，所以屏内可点的只剩 1 条。
check("I 屏幕外无效 bounds 的行不计入", len(rows) == 1, "rows=%d" % len(rows))

# ---------- J: 滚动后的页面能扫出多条 ----------
print("=== J: 滚动后的页面 ===")
ui_mid = FakeUI(MID)
rows_mid = mod._find_browse_rows(ui_mid)
check("J mid.xml 一次扫出多条未做任务", len(rows_mid) >= 2, "rows=%d" % len(rows_mid))
check("J 行按 y 从上到下排序",
      all(rows_mid[i]["bounds"][1] <= rows_mid[i + 1]["bounds"][1]
          for i in range(len(rows_mid) - 1)))

# ---------- K: 兼容用户口述的【去领取】 ----------
print("=== K: 兼容 去领取 ===")
claim_xml = (
    '<?xml version="1.0" encoding="UTF-8"?><hierarchy>'
    '<node text="关闭任务面板" bounds="[900,600][1000,660]" displayed="true" clickable="true"/>'
    '<node text="浏览6秒，奖励+10g" bounds="[189,858][770,907]" displayed="true" clickable="false"/>'
    '<node text="去领取" bounds="[838,805][1025,891]" displayed="true" clickable="false"/>'
    '</hierarchy>')
u_claim = FakeUI(claim_xml)
check("K _is_drops_dialog 认 去领取", mod._is_drops_dialog(u_claim))
check("K _find_claim_buttons 找到 去领取",
      [b["text"] for b in mod._find_claim_buttons(u_claim)] == ["去领取"])
check("K 去领取 不算未做任务", mod._find_next_browse_task(u_claim) is None)

# ---------- L: 滚动指纹能区分不同屏 ----------
print("=== L: 滚动指纹 ===")
check("L 不同滚动位置指纹不同",
      mod._fingerprint(FakeUI(DIALOG)) != mod._fingerprint(FakeUI(LIST2)))
check("L 同一页面指纹稳定",
      mod._fingerprint(FakeUI(DIALOG)) == mod._fingerprint(FakeUI(DIALOG)))

# ---------- M: 完整流程模拟（三个问题一起验） ----------
print("=== M: 完整流程模拟 ===")
BROWSE = "浏览6秒，奖励+10g"
layout = [
    (BROWSE, "逛一逛"),
    ("下1单奖励+3000g", "去完成"),          # 非浏览任务，不该点
    (BROWSE, "去完成"),
    ("完成任务奖励+150g", "去完成"),        # 非浏览任务，不该点
    ("浏览6秒，奖励+30g", "逛一逛"),
    ("访问并登录奖励+50g", "去完成"),       # 非浏览任务，不该点
    (BROWSE, "逛一逛"),
    (BROWSE, "去完成"),
    (BROWSE, "逛一逛"),
    (BROWSE, "去完成"),
    ("浏览6秒，奖励+20g", "逛一逛"),
    (BROWSE, "去完成"),
]
non_browse_idx = (1, 3, 5)
expected = sum(1 for d, _ in layout if BROWSE_DESC_KEY in d and "奖励" in d)

sim = SimUI([{"desc": d, "btn": b} for d, b in layout])
log = Log()
browse_cnt, claim_cnt = mod._process_tasks(sim, log, Stop())

check("M 全部浏览任务都做完", browse_cnt == expected,
      "browse=%d expected=%d" % (browse_cnt, expected))
check("M 领奖次数等于浏览任务数", claim_cnt == expected,
      "claim=%d expected=%d" % (claim_cnt, expected))
check("M 非浏览任务没有被误点",
      all(sim.rows[i]["btn"] == "去完成" for i in non_browse_idx),
      str([sim.rows[i]["btn"] for i in non_browse_idx]))
check("M 所有浏览行最终为已领取",
      all(sim.rows[i]["btn"] == "已领取" for i in range(len(layout))
          if i not in non_browse_idx))
check("M 确实向下滑了多屏（问题2）",
      sim.swipes.count("task_list") >= 3,
      "task_list=%d" % sim.swipes.count("task_list"))
check("M 领奖前回了列表顶部（问题3）",
      sim.swipes.count("task_list_down") >= 2,
      "task_list_down=%d" % sim.swipes.count("task_list_down"))
down_logs = [m for lv, m in log.lines if "下滑第" in m]
check("M 日志有逐屏下滑记录", len(down_logs) >= 2, str(down_logs[:3]))
check("M 日志有回顶部记录",
      any("回到列表顶部" in m for lv, m in log.lines))

# ---------- N: 旧接口兼容 ----------
print("=== N: 旧接口兼容 ===")
check("N _find_next_browse_task 仍可用",
      mod._find_next_browse_task(FakeUI(DIALOG)) is not None)
check("N _find_claim_button 仍可用",
      mod._find_claim_button(FakeUI(DIALOG)) is not None)

# ---------- O: 农场页入口按钮不受影响 ----------
print("=== O: 领水滴入口 ===")
check("O 完全渲染能找到 expo_task_icon",
      mod._find_drops_button(FakeUI(os.path.join(ROOT, "_farm_farm_home2.xml"))) is not None)
check("O 未渲染不会误判",
      mod._find_drops_button(FakeUI(os.path.join(ROOT, "_drops", "01_farm_home.xml"))) is None)

print("\n==== %d passed, %d failed ====" % (len(PASSED), len(FAILED)))
if FAILED:
    for f in FAILED:
        print("  FAILED: %s" % f)
    sys.exit(1)
