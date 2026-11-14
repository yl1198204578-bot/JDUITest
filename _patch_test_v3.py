# -*- coding: utf-8 -*-
"""回归脚本补 v3 用例：
  - 修 L5（MAX_CYCLES 改名 MAX_PASSES）
  - N 段：断连快速失败 / 重连次数封顶 / 任务循环零 XML / 点击只等一次
"""
import io
import os
import uuid

ROOT = os.path.dirname(os.path.abspath(__file__))
P = os.path.join(ROOT, "_test_task14_coupons.py")
s = io.open(P, encoding="utf-8").read()


def rep(old, new, tag):
    global s
    assert old in s, "MISS " + tag
    s = s.replace(old, new, 1)


# ---- L5：常量改名
rep('''      "MAX_CYCLES" in SRC and "done == 0" in SRC)''',
    '''      ("MAX_CYCLES" in SRC or "MAX_PASSES" in SRC) and "done == 0" in SRC)''',
    "L5")

# ---- SimUI 记录 page_source 调用时的页面状态
rep("""        self.invalidated = 0
        self.shots = 0""",
    """        self.invalidated = 0
        self.shots = 0
        self.source_calls = 0
        self.source_states = []""",
    "sim init counters")

rep('''    def source(self, fresh=False):
        return u"<dummy/>"''',
    '''    def source(self, fresh=False):
        self.source_calls += 1
        self.source_states.append(self.state)
        return u"<dummy/>"''',
    "sim source counter")

# ---- 追加 N 段
TAIL = '''

# ================================================================ N
print("\\n--- N. v3 稳定性 / 提速 ---")
check("N1 源码里任务循环不再 dump XML（无 force_xml 兜底）",
      "force_xml=True)" not in SRC.split("def _do_one")[1].split(
          "def _refresh_panel")[0],
      "任务循环还有 XML 兜底")
check("N2 点击等待不再叠加两次 pause（用 settle=0）",
      "settle=0" in SRC and "settle=None" in SRC)


class _Gone(object):
    """adb 掉线时的替身：设备列表为空。"""

    def __init__(self):
        self.online_calls = 0
        self.reconnect_calls = 0

    def online(self, adb):
        self.online_calls += 1
        return False

    def reconnect(self, adb, wait=None):
        self.reconnect_calls += 1
        return False


g = _Gone()
_old_online, _old_reconnect, _old_adbpath = (
    MOD._device_online, MOD._adb_reconnect, MOD.adb_path)
MOD._device_online = g.online
MOD._adb_reconnect = g.reconnect
MOD.adb_path = lambda: "adb"
try:
    gd = {"calls": 0}

    class _D2(object):
        @staticmethod
        def get_driver():
            gd["calls"] += 1
            raise AssertionError("断连时不该去建 session")

    m3 = Task14Coupons()
    m3.ui = SimUI()
    m3.log = Log()
    m3.stop = threading.Event()
    _old_drv = MOD.driver
    MOD.driver = _D2()
    try:
        r = m3._revive()
    finally:
        MOD.driver = _old_drv
    check("N3 adb 里没设备时 _revive 立刻放弃（不干等 20s 建 session）",
          r is False and gd["calls"] == 0, "%s / %s" % (r, gd["calls"]))
    check("N4 断连会先试一次 reconnect", g.reconnect_calls == 1,
          "%d" % g.reconnect_calls)
    check("N5 断连时置 _dead，后续 _snap 不再读屏", m3._dead is True)
    t0 = time.time()
    st, nodes = m3._snap()
    check("N6 已 _dead 时 _snap 直接返回不读屏",
          st == "other" and nodes == [] and time.time() - t0 < 0.05)
    check("N7 断连日志明确提示插好 USB",
          u"USB" in m3.log.text())
finally:
    MOD._device_online, MOD._adb_reconnect, MOD.adb_path = (
        _old_online, _old_reconnect, _old_adbpath)


class _Never(object):
    """设备在，但 session 一直建不起来。"""

    def __init__(self):
        self.calls = 0

    def online(self, adb):
        return True


nv = _Never()
_old_online = MOD._device_online
MOD._device_online = nv.online
MOD.adb_path = lambda: "adb"
_old_drv = MOD.driver


class _BoomDriver(object):
    @staticmethod
    def get_driver():
        raise RuntimeError("boom")


MOD.driver = _BoomDriver()
try:
    m4 = Task14Coupons()
    m4.ui = SimUI()
    m4.log = Log()
    m4.stop = threading.Event()
    res = [m4._revive() for _ in range(4)]
finally:
    MOD.driver = _old_drv
    MOD._device_online = _old_online
    MOD.adb_path = _old_adbpath
check("N8 Appium 重连次数封顶，不会无限重试吃满时间",
      res[0] is False and res[1] is False and res[2] is False and
      res[3] is False and m4.revives == MOD.MAX_REVIVE,
      "%s revives=%d" % (res, m4.revives))


sim_x = SimUI()
log_x, _ = run_sim(sim_x)
_bad = [st for st in sim_x.source_states if st in ("panel", "blind", "landing")]
check("N9 面板/落地页期间一次 page_source 都没读（instrumentation 不会被打崩）",
      _bad == [] and sim_x.browses == 3,
      "读到 %d 次: %s" % (len(_bad), _bad[:5]))
check("N10 换成纯像素通道后仍然做完 3 个任务",
      sim_x.browses == 3, "%d" % sim_x.browses)
'''

anchor = '''

print("\\n================ 汇总 ================")'''
assert anchor in s
s = s.replace(anchor, TAIL + anchor, 1)

# 需要 time
if "\nimport time\n" not in s:
    s = s.replace("import threading\n", "import threading\nimport time\n", 1)

tmp = os.path.join(ROOT, "_tmp_%s.py" % uuid.uuid4().hex[:8])
io.open(tmp, "w", encoding="utf-8", newline="\n").write(s)
os.rename(P, os.path.join(ROOT, "_archive", "test_task14_prev.txt"))
os.rename(tmp, P)
print("patched")
