# -*- coding: utf-8 -*-
"""家电家居 模块离线回归（不连手机、不连 Appium）。

覆盖：
  A. 夹具驱动：真机 dump 上的行配对 / 排除非浏览任务 / 屏外节点过滤 / X+4 换算
  B. 发现好物页三个「家电家居」只点带图标的那个
  C. 入口三级链路：金刚区第1页 -> 第2页 -> 全部频道-发现好物
  D. 做任务循环：做完就少一行、卡住会换行、滚不动就收尾、stop 立即生效
  E. 容错：页面没到、节点为空

夹具（真机 1080x2340，2026-11-12 抓的）：
  _fixture_ha_page.xml      家电家居首页（有【每日领京豆】+【赚更多京豆】，没有任务行）
  _fixture_ha_tasks.xml     点开【赚更多京豆】后的任务列表
  _fixture_ha_discover.xml  【发现好物】页（三个「家电家居」）
"""
import io
import re
import sys
import threading
import xml.etree.ElementTree as ET

sys.path.insert(0, ".")

from modules.task6_home_appliance import (
    Task6HomeAppliance, parse_task_rows, row_sig, has_task_list, browse_seconds,
    _row_title, _PROGRESS_RE, _BROWSE_RE, parse_claim_buttons,
    BROWSE_EXTRA, BTN_MIN_X, ROW_TOL, ENTRY_KEYWORDS,
    CLAIM_TEXTS, MAX_CLAIM_CLICKS, CLAIM_WAIT,
)

PASSED = []
FAILED = []


def check(name, cond, detail=""):
    if cond:
        PASSED.append(name)
        print("PASS %s" % name)
    else:
        FAILED.append(name)
        print("FAIL %s   %s" % (name, detail))


# ---------------------------------------------------------------- 夹具工具
_BOUNDS_RE = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")


def load(path):
    """把 dump 解析成 jd_ui.nodes() 同样的结构（保留退化 bounds，交给业务过滤）。"""
    s = io.open(path, encoding="utf-8", errors="replace").read()
    root = ET.fromstring(s.encode("utf-8"))
    out = []
    for n in root.iter():
        m = _BOUNDS_RE.match(n.get("bounds") or "")
        if not m:
            continue
        out.append({
            "text": (n.get("text") or "").strip(),
            "desc": (n.get("content-desc") or "").strip(),
            "bounds": tuple(int(x) for x in m.groups()),
            "clickable": n.get("clickable") == "true",
            "class": (n.get("class") or "").rsplit(".", 1)[-1],
        })
    return out


def nd(text, x1, y1, x2, y2, clickable=False):
    return {"text": text, "desc": "", "bounds": (x1, y1, x2, y2),
            "clickable": clickable, "class": "TextView"}


def row_nodes(i, title, secs=10, btn=u"去完成", y=None):
    """按真机行结构造一行：标题在上、，浏览Ns可领 在下一行、按钮贴右。"""
    y = 1385 + i * 200 if y is None else y
    return [
        nd(title, 203, y, 657, y + 49),
        nd(u"，浏览%ds可领" % secs, 429, y + 66, 643, y + 104),
        nd(btn, 814, y + 13, 1031, y + 96, clickable=True),
    ]


def screen(*rows):
    out = []
    for r in rows:
        out.extend(r)
    return out


# 「页面在、但没有可做任务」的真实样子：仍有家电家居 WebView 节点。
# 不能用 [] 表示空屏——空列表现在代表「page_source 读失败」，会走重试分支。
EMPTY = [nd(u"家电家居", 0, 439, 1080, 2199)]


class Log(object):
    def __init__(self):
        self.lines = []

    def write_log(self, msg, level="INFO"):
        self.lines.append((level, msg))

    def done(self, msg=""):
        self.lines.append(("DONE", msg))

    def error(self, msg):
        self.lines.append(("ERROR", msg))

    def text(self):
        return "\n".join("[%s] %s" % (lv, m) for lv, m in self.lines)


# ---------------------------------------------------------------- A 夹具驱动
print("=== A: 真机 dump 上的行配对 ===")
PAGE = load("_fixture_ha_page.xml")
TASKS = load("_fixture_ha_tasks.xml")
DISC = load("_fixture_ha_discover.xml")

print("   节点数 首页=%d 任务列表=%d 发现好物=%d" % (len(PAGE), len(TASKS), len(DISC)))

check("A1 家电家居首页不算任务列表（否则不会去点赚更多京豆）",
      has_task_list(PAGE) is False, str(has_task_list(PAGE)))
check("A2 任务列表被正确识别", has_task_list(TASKS) is True, str(has_task_list(TASKS)))
check("A3 首页解析出 0 个可做任务", parse_task_rows(PAGE) == [],
      str(parse_task_rows(PAGE)))

rows = parse_task_rows(TASKS)
check("A4 任务列表解析出 4 个可做任务（第5行在屏外）", len(rows) == 4,
      "got=%d %r" % (len(rows), [r["title"] for r in rows]))
check("A5 标题都带 (N/M) 进度", all(_PROGRESS_RE.search(r["title"]) for r in rows),
      str([r["title"] for r in rows]))
SUBTITLES = {u"抢20元外卖金券", u"好货1折起",
             u"打卡无门槛领福利", u"逛频道天天赚好礼"}
check("A6 标题不会被同一行的副标题抢走",
      all(r["title"] not in SUBTITLES for r in rows),
      str([r["title"] for r in rows]))
check("A7 四个任务名与真机一致",
      [r["title"] for r in rows] == [
          u"逛外卖频道（0/1）", u"逛秒杀频道（0/1）",
          u"限时0元好礼（0/1）", u"看视频赚现金（0/1）"],
      str([r["title"] for r in rows]))
check("A8 全部是 浏览10s 可领", all(r["secs"] == 10 for r in rows),
      str([r["secs"] for r in rows]))
check("A9 按钮都是【去完成】", all(r["btn"] == u"去完成" for r in rows),
      str([r["btn"] for r in rows]))
check("A10 点的是右侧按钮 x（>= %d）" % BTN_MIN_X,
      all(r["cx"] >= BTN_MIN_X for r in rows), str([r["cx"] for r in rows]))
check("A11 按 y 从上到下排序",
      [r["cy"] for r in rows] == sorted(r["cy"] for r in rows), str([r["cy"] for r in rows]))
check("A12 【分享好友助力（0/11）】被排除（没有浏览Ns可领）",
      all(u"分享好友" not in r["title"] for r in rows), str([r["title"] for r in rows]))
check("A13 屏外退化的【每日签到领现金】被排除",
      all(u"每日签到" not in r["title"] for r in rows), str([r["title"] for r in rows]))

print("\n=== A14-A22: 时长与边界 ===")
check("A14 X+4：10 -> 14", browse_seconds(10) == 14, str(browse_seconds(10)))
check("A15 X+4：5 -> 9", browse_seconds(5) == 9)
check("A16 X+4：15 -> 19", browse_seconds(15) == 19)
check("A17 BROWSE_EXTRA 就是 4", BROWSE_EXTRA == 4, str(BROWSE_EXTRA))
check("A18 浏览5s可领 -> secs=5",
      [r["secs"] for r in parse_task_rows(
          [nd(u"逛一逛", 900, 1100, 1000, 1180, True),
           nd(u"，浏览5s可领", 350, 1130, 560, 1168)])] == [5])
check("A19 浏览15s可领 -> secs=15",
      [r["secs"] for r in parse_task_rows(
          [nd(u"去完成", 900, 1100, 1000, 1180, True),
           nd(u"，浏览15s可领", 350, 1130, 560, 1168)])] == [15])
check("A20 只有按钮没有浏览小字 -> 不算任务",
      parse_task_rows([nd(u"去完成", 900, 1100, 1000, 1180, True)]) == [])
check("A21 小字离按钮太远（> ROW_TOL）-> 不配对",
      parse_task_rows([nd(u"去完成", 900, 1100, 1000, 1180, True),
                       nd(u"，浏览10s可领", 350, 1100 + ROW_TOL + 60, 560, 1100 + ROW_TOL + 98)]) == [])
check("A22 左侧描述里的【逛一逛】不算按钮",
      parse_task_rows([nd(u"逛一逛精选(0/8)", 200, 1100, 500, 1140),
                       nd(u"，浏览10s可领", 350, 1130, 560, 1168)]) == [])

print("\n=== A23-A26: 签名 ===")
sig_a = row_sig([{"title": u"逛外卖频道（0/1）", "secs": 10}])
sig_b = row_sig([{"title": u"逛外卖频道（1/1）", "secs": 10}])
check("A23 (0/1)->(1/1) 签名变化", sig_a != sig_b, "%r vs %r" % (sig_a, sig_b))
check("A24 内容相同签名相同", sig_a == row_sig([{"title": u"逛外卖频道（0/1）", "secs": 10}]))
check("A25 行数减少也算进展（签名必然变短）", len(sig_b) == 1)
check("A26 半角括号进度也能识别", _PROGRESS_RE.search(u"任务(0/1)") is not None)


# ---------------------------------------------------------------- B 发现好物三选一
print("\n=== B: 【发现好物】三个家电家居 ===")


class TapUI(object):
    W, H = 1080, 2340

    def __init__(self, nodes):
        self._nodes = nodes
        self.taps = []
        self.invalidated = 0

    def nodes(self, xml=None, contains=None):
        return self._nodes

    @staticmethod
    def center(n):
        b = n["bounds"]
        return ((b[0] + b[2]) // 2, (b[1] + b[3]) // 2)

    def tap(self, pos, pause=0):
        self.taps.append(pos)

    def invalidate(self):
        self.invalidated += 1

    def sleep(self, s):
        return True


m6 = Task6HomeAppliance()
ui = TapUI(DISC)
m6._tap_appliance_item(ui, Log())
check("B1 发现好物页点中带图标的窄项 (154,1700)",
      ui.taps == [(154, 1700)], str(ui.taps))
check("B2 没有点顶部筛选 chip (497,419)", (497, 419) not in ui.taps, str(ui.taps))
check("B3 没有点全宽区块标题 (540,1512)", (540, 1512) not in ui.taps, str(ui.taps))
check("B4 点完清缓存", ui.invalidated >= 1, str(ui.invalidated))

try:
    m6._tap_appliance_item(TapUI([]), Log())
    check("B5 没有候选时抛错（不静默跳过）", False, "no raise")
except RuntimeError as e:
    check("B5 没有候选时抛错（不静默跳过）", True, str(e))

# 只有一个顶部 chip 时也不能点
try:
    m6._tap_appliance_item(TapUI([nd(u"家电家居", 387, 368, 607, 470, True)]), Log())
    check("B6 只有顶部 chip 时抛错（宁可不点也不点错）", False, "no raise")
except RuntimeError:
    check("B6 只有顶部 chip 时抛错（宁可不点也不点错）", True)


# ---------------------------------------------------------------- C 入口
print("\n=== C: 入口三级链路 ===")


def kk(desc, x1, y1, x2, y2):
    return {"desc": desc, "bounds": (x1, y1, x2, y2),
            "y1": y1, "y2": y2, "cy": (y1 + y2) // 2}


KK_P1 = [kk(u"秒杀", 0, 440, 194, 601), kk(u"种豆得豆", 194, 440, 388, 601),
         kk(u"家电家居", 388, 440, 581, 601), kk(u"东东农场", 581, 440, 775, 601)]
KK_P2 = [kk(u"全部频道", 867, 924, 1080, 1085)]


class EntryUI(object):
    W, H = 1080, 2340

    def __init__(self, pages, nodes=None):
        self.pages = pages
        self.page = 0
        self.taps = []
        self.swipes = []
        self.channels = 0
        self.home_calls = 0
        self._nodes = nodes or []

    def _stable_kingkong_icon(self, desc, tries=4):
        hit = [n for n in self.pages[self.page] if n["desc"] == desc]
        return (hit[0], True) if hit else (None, False)

    def swipe_kingkong(self, direction="left", pause=0):
        self.swipes.append(direction)
        if self.page < len(self.pages) - 1:
            self.page += 1

    def invalidate(self):
        pass

    def sleep(self, s):
        return True

    def tap(self, pos, pause=0):
        self.taps.append(pos)

    @staticmethod
    def center(n):
        b = n["bounds"]
        return ((b[0] + b[2]) // 2, (b[1] + b[3]) // 2)

    def nodes(self, xml=None, contains=None):
        return self._nodes

    def goto_home(self, max_back=10):
        self.home_calls += 1
        return True

    def to_all_channels(self):
        self.channels += 1


class EntryScripted(Task6HomeAppliance):
    def __init__(self, ok_pages):
        self.ok_pages = list(ok_pages)
        self.waits = []
        self.tap_nodes = []
        self.appliance = 0

    def _wait_page(self, ui, log, timeout=25):
        self.waits.append(ui.page)
        return self.ok_pages.pop(0) if self.ok_pages else False

    def _tap_node(self, ui, log, kw, where, pause=5, exact=False):
        self.tap_nodes.append(kw)

    def _tap_appliance_item(self, ui, log):
        self.appliance += 1


# C1: 金刚区第 1 页就有，且一次成功
m = EntryScripted([True])
ui = EntryUI([KK_P1, KK_P2])
log = Log()
check("C1 金刚区第1页命中即返回", m._open_page(ui, log) is True)
check("C2 点的是【家电家居】图标中心 (484,520)",
      ui.taps == [(484, 520)], str(ui.taps))
check("C3 没有多余左滑", ui.swipes == [], str(ui.swipes))
check("C4 没走全部频道兜底", ui.channels == 0, str(ui.channels))

# C5: 第 1 页没有 -> 左滑 -> 第 2 页有
m = EntryScripted([True])
ui = EntryUI([KK_P1[:2], KK_P2 + [kk(u"家电家居", 0, 924, 194, 1085)]])
m._open_page(ui, Log())
check("C5 第1页没有时左滑到第2页", ui.swipes == ["left"], str(ui.swipes))
check("C6 第2页命中【家电家居】并点击", ui.taps == [(97, 1004)], str(ui.taps))

# C7: 两页都没有 -> 全部频道-发现好物
m = EntryScripted([True])
ui = EntryUI([KK_P1[:2], KK_P2])
log = Log()
ok = m._open_page(ui, log)
check("C7 两页都没有时走全部频道", ok is True and ui.channels == 1,
      "ok=%s channels=%d" % (ok, ui.channels))
check("C8 全部频道里点的是【发现好物】", u"发现好物" in m.tap_nodes, str(m.tap_nodes))
check("C9 最后点了【家电家居】图标项", m.appliance == 1, str(m.appliance))

# C10: 金刚区点进去但不是家电家居页（家电馆）-> 必须继续兜底，不能算成功
class WrongPage(EntryScripted):
    def _wait_page(self, ui, log, timeout=25):
        # 第1页点完落到家电馆（False），第2页没图标，兜底后成功（True）
        return self.ok_pages.pop(0) if self.ok_pages else False


m = WrongPage([False, True])
ui = EntryUI([KK_P1, KK_P2])
ok = m._open_page(ui, Log())
check("C10 点进【家电馆】不算成功，会继续兜底",
      ok is True and ui.channels == 1, "ok=%s channels=%d" % (ok, ui.channels))
check("C10b 落错页后先回首页再翻金刚区", ui.home_calls >= 1, "home_calls=%d" % ui.home_calls)
check("C11 【家电馆】不在入口关键词里", u"家电馆" not in ENTRY_KEYWORDS, str(ENTRY_KEYWORDS))
check("C12 入口关键词是 每日领京豆/赚更多京豆",
      ENTRY_KEYWORDS == (u"每日领京豆", u"赚更多京豆"), str(ENTRY_KEYWORDS))


# C13-C14: _wait_page 用真机 dump 验证
class NodeUI(object):
    def __init__(self, nodes):
        self._nodes = nodes
        self.sleeps = []

    def nodes(self, xml=None, contains=None):
        return self._nodes

    def sleep(self, s):
        self.sleeps.append(s)
        return True

    def invalidate(self):
        pass


check("C13 _wait_page 在家电家居首页为 True",
      Task6HomeAppliance()._wait_page(NodeUI(PAGE), Log(), timeout=0.05) is True)
check("C14 _wait_page 在家电馆页为 False",
      Task6HomeAppliance()._wait_page(NodeUI(load("_fixture_ha_appliance_hall.xml")),
                                      Log(), timeout=0.05) is False)


# ---------------------------------------------------------------- D 做任务循环
print("\n=== D: 做任务循环 ===")


class FlowUI(object):
    W, H = 1080, 2340

    def __init__(self, states, fail_first=0):
        self.states = list(states)
        self.pos = 0
        self.taps = []
        self.sleeps = []
        self.backs = 0
        self.fail_left = fail_first     # 前 N 次 nodes() 返回 []，模拟 page_source 超时
        self.reads = 0

    def nodes(self, xml=None, contains=None):
        self.reads += 1
        if self.fail_left > 0:
            self.fail_left -= 1
            return []
        return self.states[min(self.pos, len(self.states) - 1)]

    def tap(self, pos, pause=0):
        self.taps.append(pos)

    def sleep(self, s):
        self.sleeps.append(s)
        return True

    def back(self, pause=0):
        self.backs += 1
        self.pos = min(self.pos + 1, len(self.states) - 1)

    def invalidate(self):
        pass

    def adb_swipe(self, *a, **kw):
        pass

    def source(self, fresh=False):
        return None


class FlowScripted(Task6HomeAppliance):
    def __init__(self, scroll_results=None, reenter_ok=True):
        self.scroll_results = list(scroll_results or [])
        self.scrolls = 0
        self.reenter = 0
        self.reenter_ok = reenter_ok

    def _scroll(self, ui):
        self.scrolls += 1
        ui.pos = min(ui.pos + 1, len(ui.states) - 1)
        return self.scroll_results.pop(0) if self.scroll_results else False

    def _reenter(self, ui, log):
        self.reenter += 1
        return self.reenter_ok


stop = threading.Event()

R1 = row_nodes(0, u"逛外卖频道（0/1）")
R2 = row_nodes(1, u"逛秒杀频道（0/1）")

# D1: 两个任务 -> 空
m = FlowScripted()
ui = FlowUI([screen(R1, R2), screen(R2), EMPTY])
done = m._process_tasks(ui, Log(), stop)
check("D1 做完 2 个任务后结束", done == 2, "done=%d" % done)
check("D2 每次停留 14 秒", ui.sleeps == [14, 14], str(ui.sleeps))
check("D3 点了 2 次按钮", len(ui.taps) == 2, str(ui.taps))
check("D4 点的是右侧按钮 (922,1439)/(922,1639)",
      ui.taps == [(922, 1439), (922, 1639)], str(ui.taps))
check("D5 每次做完返回一次", ui.backs == 2, "backs=%d" % ui.backs)
check("D6 空屏滚不动就收尾", m.scrolls == 1, "scrolls=%d" % m.scrolls)

# D7: 首屏空 -> 滚动出现任务 -> 做完
m = FlowScripted(scroll_results=[True, False])
ui = FlowUI([EMPTY, screen(R1), EMPTY])
done = m._process_tasks(ui, Log(), stop)
check("D7 空屏先滚动再找", done == 1 and m.scrolls >= 1,
      "done=%d scrolls=%d" % (done, m.scrolls))

# D8: 点了没算完成 -> 该行最多试 2 次就换行
SAME = screen(R1)
m = FlowScripted()
ui = FlowUI([SAME, SAME, SAME, SAME])
done = m._process_tasks(ui, Log(), stop)
check("D8 无进展不算完成任务", done == 0, "done=%d" % done)
check("D9 同一行最多试 2 次就放弃", len(ui.taps) == 2, str(len(ui.taps)))
check("D10 放弃后去滚动", m.scrolls == 1, "scrolls=%d" % m.scrolls)

# D11: 卡住时会换到另一个任务
R1b = row_nodes(0, u"逛外卖频道（0/1）")
R2b = row_nodes(1, u"逛秒杀频道（0/1）")
m = FlowScripted()
ui = FlowUI([screen(R1b, R2b)] * 6)
m._process_tasks(ui, Log(), stop)
titles = [t for t in ui.taps]
check("D11 两个任务都会被尝试（不会死磕第一行）", len(set(titles)) == 2, str(titles))

# D12: 返回后列表丢了 -> 重进
class LostFlow(FlowScripted):
    def __init__(self):
        FlowScripted.__init__(self)
        self.reenter = 0

    def _reenter(self, ui, log):
        self.reenter += 1
        return False


m = LostFlow()
ui = FlowUI([screen(R1), EMPTY])
done = m._process_tasks(ui, Log(), stop)
check("D12 返回后列表丢了会尝试重进", m.reenter >= 1, "reenter=%d" % m.reenter)
check("D13 重进也失败就收尾（不无限循环）", done == 0, "done=%d" % done)

# D14: stop_event 已置位 -> 一下都不点
m = FlowScripted()
ui = FlowUI([screen(R1)])
st = threading.Event()
st.set()
done = m._process_tasks(ui, Log(), st)
check("D14 stop 已置位时不点任何按钮", ui.taps == [] and done == 0, str(ui.taps))

# D15: 任务上限
many = [row_nodes(i, u"任务%d（0/1）" % i) for i in range(3)]
m = FlowScripted()
ui = FlowUI([screen(*many)] * 80)
done = m._process_tasks(ui, Log(), stop)
check("D15 不会无限做下去（有上限）", done <= 40, "done=%d" % done)

# D16: 用真机任务列表跑一遍第一轮，确认点的是 (922,1439)
class RealFlow(FlowScripted):
    pass


m = FlowScripted()
ui = FlowUI([TASKS, TASKS, EMPTY])
m._process_tasks(ui, Log(), stop)
check("D16 真机 dump 上第一次点的是 (922,1439)",
      ui.taps and ui.taps[0] == (922, 1439), str(ui.taps[:1]))

# D17: page_source 瞬时超时 -> 就地重试，不能去重进页面
m = FlowScripted()
# 留一个任务在列表里，这样「列表不在场」只能是读失败引起的
ui = FlowUI([screen(R1, R2), screen(R2)], fail_first=2)
done = m._process_tasks(ui, Log(), stop)
check("D17 读失败后就地重试仍能完成任务", done == 1,
      "done=%d reenter=%d" % (done, m.reenter))
check("D18 读失败不触发整页重进", m.reenter == 0, "reenter=%d" % m.reenter)
check("D19 读失败不会影响点按钮", len(ui.taps) >= 1, str(ui.taps))

# D20: 连续读不到 -> 提前结束（不死循环）
m = FlowScripted()
ui = FlowUI([EMPTY], fail_first=999)
done = m._process_tasks(ui, Log(), stop)
check("D20 连续读不到页面会收尾", done == 0 and m.reenter == 0,
      "done=%d reenter=%d" % (done, m.reenter))
check("D21 收尾前至少重试过 MAX_READ_FAILS 次",
      ui.reads >= 4, "reads=%d" % ui.reads)


# ---------------------------------------------------------------- E 任务面板
print("\n=== E: 打开任务面板 ===")


class DialogScripted(Task6HomeAppliance):
    def __init__(self, node_seq, page_ok=True):
        self.node_seq = list(node_seq)
        self.tap_nodes = []
        self.page_ok = page_ok

    def _wait_page(self, ui, log, timeout=25):
        return self.page_ok

    def _open_page(self, ui, log):
        self.tap_nodes.append("<reopen>")
        return True

    def _tap_node(self, ui, log, kw, where, pause=5, exact=False):
        self.tap_nodes.append(kw)


class SeqUI(object):
    W, H = 1080, 2340

    def __init__(self, seq):
        self.seq = list(seq)
        self.i = 0

    def nodes(self, xml=None, contains=None):
        v = self.seq[min(self.i, len(self.seq) - 1)]
        self.i += 1
        return v

    def invalidate(self):
        pass

    def back(self, pause=0):
        pass


# E1: 已经是任务列表 -> 不点任何东西
m = DialogScripted([TASKS])
check("E1 任务列表已打开时直接返回", m._open_task_dialog(SeqUI([TASKS]), Log()) is True)
check("E2 已打开时没有多余点击", m.tap_nodes == [], str(m.tap_nodes))

# E3: 首页 -> 点赚更多京豆 -> 出列表
m = DialogScripted([PAGE, PAGE, TASKS])
ok = m._open_task_dialog(SeqUI([PAGE, PAGE, TASKS]), Log())
check("E3 首页先点【赚更多京豆】", ok is True and m.tap_nodes == [u"赚更多京豆"],
      str(m.tap_nodes))

# E4: 点完没出列表 -> 重试，超过次数抛错
m = DialogScripted([PAGE])
try:
    m._open_task_dialog(SeqUI([PAGE]), Log())
    check("E4 点不开任务列表时抛错（不假装成功）", False, "no raise")
except RuntimeError:
    check("E4 点不开任务列表时抛错（不假装成功）", True)

# E5: 不在家电家居页 -> 先重新进入
m = DialogScripted([PAGE, PAGE, TASKS], page_ok=False)
ok = m._open_task_dialog(SeqUI([PAGE, PAGE, TASKS]), Log())
check("E5 不在页面上会先重新进入", "<reopen>" in m.tap_nodes, str(m.tap_nodes))


# ---------------------------------------------------------------- G 领取奖励
print("\n=== G: 领取奖励（用户 2026-11-12 新需求） ===")

check("G1 真机 dump 里的【立即领取】在屏外，不算",
      parse_claim_buttons(TASKS) == [], str(parse_claim_buttons(TASKS)))
check("G2 家电家居首页没有领取按钮",
      parse_claim_buttons(PAGE) == [], str(parse_claim_buttons(PAGE)))


def claim_btn(text, cx, cy):
    return {"text": text, "desc": "", "bounds": (cx - 100, cy - 40, cx + 100, cy + 40),
            "clickable": True, "class": "Button"}


def claim_row(text, cx, cy, title=u"任务（1/1）"):
    """一个真实的任务行：左侧 (N/M) 标题 + 右侧按钮。"""
    return [nd(title, 203, cy - 54, 657, cy - 5), claim_btn(text, cx, cy)]


check("G3 任务行里可点的【领取】被识别",
      len(parse_claim_buttons(claim_row(u"领取", 900, 1500))) == 1,
      str(parse_claim_buttons(claim_row(u"领取", 900, 1500))))
check("G4 【立即领取】不算（用户 2026-11-12 纠正）",
      parse_claim_buttons(claim_row(u"立即领取", 900, 1500)) == [],
      str(parse_claim_buttons(claim_row(u"立即领取", 900, 1500))))
check("G5 【完成即可领取现金奖励】不算（文案不等 + 不可点）",
      parse_claim_buttons([{"text": u"完成即可领取现金奖励",
                            "desc": "", "bounds": (203, 2234, 522, 2280),
                            "clickable": False, "class": "TextView"}]) == [])
check("G6 可点但文案不完全相等也不算",
      parse_claim_buttons(claim_row(u"去领取", 900, 1500)) == [])
check("G7 按 y 从上到下排序",
      [b["cy"] for b in parse_claim_buttons(
          claim_row(u"领取", 900, 1900) + claim_row(u"领取", 900, 1400))]
      == [1400, 1900])

# 用户反馈「点领取却退出页面」的根因：
# 页面别处（每日领京豆区块）也有「领取」，它没有 (N/M) 标题，点了会跳走。
check("G7b 页面别处的【领取】（无任务行标题）不算",
      parse_claim_buttons([claim_btn(u"领取", 922, 876)]) == [],
      str(parse_claim_buttons([claim_btn(u"领取", 922, 876)])))
check("G7c 标题在右侧不算（必须在按钮左边）",
      parse_claim_buttons([claim_btn(u"领取", 900, 1500),
                           nd(u"任务（1/1）", 1000, 1446, 1080, 1495)]) == [])


class ClaimUI(object):
    W, H = 1080, 2340

    def __init__(self, buttons, locked=None, scrolled=False):
        self.buttons = list(buttons)          # (text, cx, cy)
        self.locked = list(locked or [])      # 滚动一次后才出现
        self.taps = []
        self.sleeps = []
        self.scrolled = scrolled
        self.swipes_up = 0
        self.swipes_down = 0
        self.backs = 0

    def source(self, fresh=False):
        return "scroll=%s|n=%d" % (self.scrolled, len(self.buttons))

    def adb_swipe(self, x1, y1, x2, y2, duration=300):
        # 手指从上往下 = 页面回到顶部
        if y2 > y1:
            self.swipes_up += 1
            self.scrolled = False
        else:
            self.swipes_down += 1
            self.scrolled = True

    def unlock(self):
        self.buttons.extend(self.locked)
        self.locked = []

    def invalidate(self):
        pass

    def sleep(self, s):
        self.sleeps.append(s)
        return True

    def nodes(self, xml=None, contains=None):
        out = [nd(u"家电家居", 0, 439, 1080, 2199)]
        # 一个已完成、已领取的行：标题在、按钮没了。
        # 用来保证「这是任务列表」，否则领取阶段会被守卫跳过。
        out.append(nd(u"逛外卖频道（1/1）", 203, 1181, 657, 1231))
        for i, (txt, cx, cy) in enumerate(self.buttons):
            out.extend(claim_row(txt, cx, cy, u"任务%d（1/1）" % i))
        return out

    def tap(self, pos, pause=0):
        self.taps.append(pos)
        if pause:
            self.sleeps.append(pause)     # tap 后的等待也记下来
        self.buttons = [b for b in self.buttons if (b[1], b[2]) != tuple(pos)]

    def back(self, pause=0):
        self.backs += 1


class ClaimStuckUI(ClaimUI):
    """点了不消失的假按钮。"""

    def tap(self, pos, pause=0):
        self.taps.append(pos)


class ClaimScripted(Task6HomeAppliance):
    def __init__(self, scroll_results=None):
        self.scroll_results = list(scroll_results or [])
        self.scrolls = 0

    def _scroll(self, ui):
        self.scrolls += 1
        if hasattr(ui, "adb_swipe"):
            ui.adb_swipe(ui.W // 2, int(ui.H * 0.78), ui.W // 2, int(ui.H * 0.42), 500)
        if hasattr(ui, "unlock"):
            ui.unlock()
        return self.scroll_results.pop(0) if self.scroll_results else False


m = ClaimScripted()
ui = ClaimUI([(u"领取", 900, 1400), (u"领取", 900, 1700),
              (u"领取", 900, 2000)])
got = m._claim_rewards(ui, Log(), stop, max_scrolls=0, to_top=False)
check("G8 3 个【领取】都点了", got == 3, "got=%d" % got)
check("G9 点完列表没有领取按钮了", ui.buttons == [], str(ui.buttons))
check("G10 点完就结束，不滚动、不退出弹窗",
      m.scrolls == 0 and ui.backs == 0, "scrolls=%d backs=%d" % (m.scrolls, ui.backs))

# 点不掉的按钮不能死循环
m = ClaimScripted()
ui = ClaimStuckUI([(u"领取", 900, 1400)])
got = m._claim_rewards(ui, Log(), stop, max_scrolls=0, to_top=False)
check("G11 点不掉的按钮最多点 2 次", got == 2, "got=%d" % got)
check("G12 点不掉的按钮点完就停，不死循环", m.scrolls == 0,
      "scrolls=%d" % m.scrolls)

# 当前屏没有 -> 滚动后出现
m = ClaimScripted(scroll_results=[True, False])
ui = ClaimUI([], locked=[(u"领取", 900, 1600)])
got = m._claim_rewards(ui, Log(), stop, max_scrolls=2, to_top=False)
check("G13 需要时才滚动找（显式放开 max_scrolls）", got == 1, "got=%d" % got)

# 滚不动就收尾
m = ClaimScripted(scroll_results=[False])
ui = ClaimUI([])
got = m._claim_rewards(ui, Log(), stop, max_scrolls=0, to_top=False)
check("G14 不滚动时 -> 没领取就直接收尾", got == 0 and m.scrolls == 0,
      "got=%d scrolls=%d" % (got, m.scrolls))

# stop 立即生效
m = ClaimScripted()
ui = ClaimUI([(u"领取", 900, 1400)])
st2 = threading.Event()
st2.set()
got = m._claim_rewards(ui, Log(), st2)
check("G15 stop 已置位时不点领取", got == 0 and ui.taps == [], str(ui.taps))

# 领取上限
m = ClaimScripted(scroll_results=[True] * 50)
ui = ClaimUI([(u"领取", 900, 1200 + i * 90) for i in range(100)])
got = m._claim_rewards(ui, Log(), stop)
check("G16 领取次数有上限", got <= MAX_CLAIM_CLICKS, "got=%d" % got)

check("G17 CLAIM_TEXTS 只有【领取】", CLAIM_TEXTS == (u"领取",), str(CLAIM_TEXTS))

# 任务列表不在场 -> 不能乱点别的页面上的【领取】
m = ClaimScripted()
ui = ClaimUI([(u"领取", 900, 1400)])
ui.nodes = lambda xml=None, contains=None: [nd(u"家电家居", 0, 439, 1080, 2199),
                                            claim_btn(u"领取", 900, 1400)]
got = m._claim_rewards(ui, Log(), stop)
check("G18 任务列表不在场时跳过领取", got == 0 and ui.taps == [],
      "got=%d taps=%s" % (got, ui.taps))


# ---------------------------------------------------------------- H 点节点容错
print("\n=== H: _tap_node 重试与滚动查找 ===")


class TapSeqUI(object):
    """每次 nodes() 依次返回一个快照（最后一个重复）。"""
    W, H = 1080, 2340

    def __init__(self, seq):
        self.seq = list(seq)
        self.i = 0
        self.taps = []
        self.swipes = 0
        self.sleeps = []

    def nodes(self, xml=None, contains=None):
        v = self.seq[min(self.i, len(self.seq) - 1)]
        self.i += 1
        return v

    @staticmethod
    def center(n):
        b = n["bounds"]
        return ((b[0] + b[2]) // 2, (b[1] + b[3]) // 2)

    def tap(self, pos, pause=0):
        self.taps.append(pos)

    def invalidate(self):
        pass

    def sleep(self, s):
        self.sleeps.append(s)
        return True

    def adb_swipe(self, *a, **kw):
        self.swipes += 1


FOUND = [nd(u"发现好物", 849, 396, 1025, 536, clickable=True)]

# H1: 第一次没渲染出来，第二次才有 -> 仍然点中
m = Task6HomeAppliance()
ui = TapSeqUI([EMPTY, FOUND])
ok = m._tap_node(ui, Log(), u"发现好物", u"全部频道页", pause=0)
check("H1 没渲染出来时会重试到点中", ok is True and ui.taps == [(937, 466)],
      "taps=%s" % ui.taps)
check("H2 重试期间先滚动找", ui.swipes >= 1, "swipes=%d" % ui.swipes)

# H3: 一直找不到 -> 抛错（不能静默跳过）
m = Task6HomeAppliance()
ui = TapSeqUI([EMPTY])
try:
    m._tap_node(ui, Log(), u"发现好物", u"全部频道页", pause=0)
    check("H3 一直找不到时抛错", False, "no raise")
except RuntimeError:
    check("H3 一直找不到时抛错", True)

# H4: 优先点 clickable 的那个
both = [nd(u"赚更多京豆", 46, 1423, 500, 1503, clickable=False),
        nd(u"赚更多京豆", 46, 1623, 500, 1703, clickable=True)]
m = Task6HomeAppliance()
ui = TapSeqUI([both])
m._tap_node(ui, Log(), u"赚更多京豆", u"家电家居页", pause=0)
check("H4 优先点可点的那个", ui.taps == [(273, 1663)], str(ui.taps))

# H5: 真机首页 dump 上点【赚更多京豆】落到 (273,1463)
m = Task6HomeAppliance()
ui = TapSeqUI([PAGE])
m._tap_node(ui, Log(), u"赚更多京豆", u"家电家居页", pause=0)
check("H5 真机首页上点中【赚更多京豆】(273,1463)",
      ui.taps == [(273, 1463)], str(ui.taps))


# ---------------------------------------------------------------- I 领取阶段的点法
print("\n=== I: 领取阶段——原地一个一个点，不退出弹窗 ===")

CLAIM_DUMP = load("_fixture_ha_claim.xml")
cbtns = parse_claim_buttons(CLAIM_DUMP)
check("I1 真机「只剩领取」的 dump 里有 4 个【领取】",
      len(cbtns) == 4, "got=%d %r" % (len(cbtns), cbtns))
check("I2 四个都在右侧按钮列 x=922",
      all(b["cx"] == 922 for b in cbtns), str([b["cx"] for b in cbtns]))
check("I3 该页仍算任务列表（领取阶段不会被守卫跳过）",
      has_task_list(CLAIM_DUMP) is True)
check("I4 该页已没有可做浏览任务",
      parse_task_rows(CLAIM_DUMP) == [], str(parse_task_rows(CLAIM_DUMP)))

REAL4 = [(u"领取", 922, 1439), (u"领取", 922, 1642),
         (u"领取", 922, 1844), (u"领取", 922, 2044)]

m = ClaimScripted()
ui = ClaimUI(list(REAL4))
got = m._claim_rewards(ui, Log(), stop, max_scrolls=0, to_top=False)
check("I5 四个【领取】全部点完", got == 4, "got=%d" % got)
check("I6 点的就是真机坐标", sorted(ui.taps) == sorted(
      [(b[1], b[2]) for b in REAL4]), str(ui.taps))
check("I7 每点一个都等 %.0f 秒" % CLAIM_WAIT,
      ui.sleeps == [CLAIM_WAIT] * 4, str(ui.sleeps))
check("I8 原地领取不滚动", ui.swipes_up == 0 and ui.swipes_down == 0,
      "up=%d down=%d" % (ui.swipes_up, ui.swipes_down))
check("I9 领取过程不按返回（不关弹窗）", ui.backs == 0, "backs=%d" % ui.backs)
check("I10 CLAIM_WAIT 就是 1 秒", CLAIM_WAIT == 1.0, str(CLAIM_WAIT))

# 跳到别的页（没有任务行）就收尾，不能去按返回把弹窗关了
class GoneUI(ClaimUI):
    def nodes(self, xml=None, contains=None):
        if self.taps:
            return [nd(u"家电家居", 0, 439, 1080, 2199)]
        return ClaimUI.nodes(self, xml, contains)


ui = GoneUI([(u"领取", 922, 1439)])
got = ClaimScripted()._claim_rewards(ui, Log(), stop, max_scrolls=0, to_top=False)
check("I11 列表不见就收尾", got == 1, "got=%d" % got)
check("I12 不会去按返回（那会把弹窗关掉）", ui.backs == 0,
      "backs=%d" % ui.backs)

# 真机任务列表（还没做完）里没有领取 -> 0 次，不乱点
ui = ClaimUI([])
got = ClaimScripted()._claim_rewards(ui, Log(), stop, max_scrolls=0, to_top=False)
check("I14 没有领取时不点任何东西", got == 0 and ui.taps == [], str(ui.taps))

# 最终补扫：to_top=True 会先往上滑回顶，但不会去点页面别处的领取
m = ClaimScripted()
ui = ClaimUI(list(REAL4), scrolled=True)
got = m._claim_rewards(ui, Log(), stop, max_scrolls=0, to_top=True)
check("I15 最终补扫会先滑回顶部", ui.swipes_up >= 1,
      "up=%d" % ui.swipes_up)
check("I16 回顶后仍然把 4 个领取点完", got == 4, "got=%d" % got)

# 页面别处的【领取】（无任务行标题）绝不能点
class StrayUI(ClaimUI):
    def nodes(self, xml=None, contains=None):
        out = ClaimUI.nodes(self, xml, contains)
        out.append(claim_btn(u"领取", 922, 876))     # 每日领京豆区块里的领取
        return out


ui = StrayUI([])
got = ClaimScripted()._claim_rewards(ui, Log(), stop, max_scrolls=0, to_top=False)
check("I17 页面别处的【领取】不会被点", got == 0 and ui.taps == [],
      "got=%d taps=%s" % (got, ui.taps))


# ---------------------------------------------------------------- F 容错
print("\n=== F: 容错 ===")
check("F1 parse_task_rows(None) -> []", parse_task_rows(None) == [])
check("F2 parse_task_rows([]) -> []", parse_task_rows([]) == [])
check("F3 has_task_list(None) -> False", has_task_list(None) is False)
check("F4 has_task_list([]) -> False", has_task_list([]) is False)
check("F5 _row_title 无候选返回空串",
      _row_title([], {"cy": 1000}) == u"", repr(_row_title([], {"cy": 1000})))
check("F6 row_sig(None) -> ()", row_sig(None) == ())
check("F7 浏览正则不吃【浏览页面Xs】以外的东西",
      _BROWSE_RE.search(u"分享好友助力（0/11）") is None)

print("\n==== %d passed, %d failed ====" % (len(PASSED), len(FAILED)))
if FAILED:
    for f in FAILED:
        print("  FAILED: %s" % f)
    sys.exit(1)
