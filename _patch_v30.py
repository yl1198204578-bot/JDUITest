# -*- coding: utf-8 -*-
"""v3 提速 + 稳定性补丁。

1) adb_tap 支持 settle 参数（原来 pause 被 sleep 两次）
2) 断连快速失败：adb devices 为空时 0.5s 返回，不再每次干等 20s
3) 任务循环里彻底不碰 page_source（instrumentation 崩在它上面）
4) 各处 wait 收紧
"""
import io
import os
import uuid

ROOT = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.join(ROOT, "modules", "task14_coupons_v2.py")
UI = os.path.join(ROOT, "utils", "jd_ui.py")


def swap(path, s):
    tmp = os.path.join(ROOT, "_tmp_%s.py" % uuid.uuid4().hex[:8])
    io.open(tmp, "w", encoding="utf-8", newline="\n").write(s)
    os.remove(path)
    os.rename(tmp, path)


def rep(s, old, new, tag):
    assert old in s, "MISS: " + tag
    return s.replace(old, new, 1)


# ---------------- jd_ui.py: adb_tap settle ----------------
s = io.open(UI, encoding="utf-8").read()
s = rep(s,
        """    def adb_tap(self, key_or_xy, pause=1.5):""",
        """    def adb_tap(self, key_or_xy, pause=1.5, settle=None):""",
        "ui sig")
s = rep(s,
        """        self.sleep(pause)
        self.invalidate()
        self.sleep(pause)
        self.invalidate()""",
        """        # pause 是点击后等页面起反应的时间；settle 是再补一段（默认同 pause）。
        # 任务循环里把 settle 收到 0，省掉一半等待。
        self.sleep(pause)
        self.invalidate()
        if settle is None:
            settle = pause
        if settle:
            self.sleep(settle)
            self.invalidate()""",
        "ui double sleep")
swap(UI, s)
print("jd_ui patched")

# ---------------- 模块 ----------------
s = io.open(MOD, encoding="utf-8").read()

# 1) 常量
s = rep(s,
        "MAX_OCR = 400",
        "MAX_OCR = 400\nMAX_REVIVE = 2                # Appium 整轮最多重连 2 次\nREVIVE_ADB_WAIT = 6.0         # 断连后等 adb 回来的秒数",
        "const MAX_REVIVE")

# 2) adb 探活工具
s = rep(s,
        "def _default_shot(ui):",
        '''def _device_online(adb):
    """adb devices 里有没有一台 state=device 的机器（≈0.3s）。"""
    if not adb:
        return False
    try:
        out = subprocess.check_output([adb, "devices"], stderr=subprocess.STDOUT,
                                      timeout=8)
    except Exception:
        return False
    if not isinstance(out, str):
        out = out.decode("utf-8", "replace")
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            return True
    return False


def _adb_reconnect(adb, wait=REVIVE_ADB_WAIT):
    """USB 偶发掉线：reconnect offline + 等一会儿，比重建 session 便宜得多。"""
    try:
        subprocess.call([adb, "reconnect", "offline"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        timeout=10)
    except Exception:
        pass
    deadline = time.time() + wait
    while time.time() < deadline:
        if _device_online(adb):
            return True
        time.sleep(1.0)
    return False


def _default_shot(ui):''',
        "device helper")

# 3) __init__ 增加状态
s = rep(s,
        """        self.panel_ref = None            # 面板标题条像素参照
        self._verify_hit = False""",
        """        self.panel_ref = None            # 面板标题条像素参照
        self._verify_hit = False
        self.revives = 0                 # 已重连次数
        self._dead = False               # Appium 彻底不可用：整个模块转纯 adb""",
        "init dead")

# 4) _revive 重写
old_revive = s[s.index("    def _revive(self):"):s.index("    def _snap(self):")]
new_revive = '''    def _revive(self):
        """uiautomator2 instrumentation 崩了（ECONNREFUSED 8201）时重建 session。

        真机实测两个坑：
        1. 手机掉 usb 后 create session 会干等 20s 才报「找不到设备」，
           连试 8 次就是 160s 白扔 —— 先用 adb devices 探活，断了立刻退。
        2. 重连也救不回来时，继续在每个探针里重试只会把整轮时间吃光，
           所以整轮最多 2 次，之后置 _dead 让上层快速收尾。
        """
        if self._dead:
            return False
        if self.revives >= MAX_REVIVE:
            self._dead = True
            self._say(u"Appium 重连 %d 次仍不可用，收尾" % self.revives, "WARN")
            return False
        adb = adb_path()
        if adb and not _device_online(adb):
            self._say(u"adb 里没有设备（USB 掉线？），等 %.0fs 看能不能回来"
                      % REVIVE_ADB_WAIT, "WARN")
            if not _adb_reconnect(adb):
                self._dead = True
                self._say(u"手机已断开：请重新插 USB / 确认「允许 USB 调试」，"
                          u"再点一次运行", "ERROR")
                return False
            self._say(u"adb 已恢复，继续重建 session", "WARN")
        self.revives += 1
        try:
            d = driver.get_driver()
        except Exception as e:
            self._say(u"重连 Appium 失败：%s" % e, "WARN")
            return False
        self.ui.d = d
        self.ui.invalidate()
        self._say(u"Appium session 已重建（第 %d 次），继续跑" % self.revives, "WARN")
        return True

'''
s = s.replace(old_revive, new_revive, 1)

# 5) _snap 快速失败
s = rep(s,
        """    def _snap(self):
        self.ui.invalidate()""",
        """    def _snap(self):
        if self._dead:
            return "other", []
        self.ui.invalidate()""",
        "snap dead")

# 6) _left_panel 收紧等待
old_lp = s[s.index("    def _left_panel(self, tries=4):"):s.index("    def _row_ready(self, row, shot=None):")]
new_lp = '''    def _left_panel(self, tries=3):
        """点完任务按钮后确认已经离开面板。

        True=已离开 / False=面板还在（点击被吞）/ None=判不出来。
        先等 0.35s 再截图：截图本身要 0.95s，等于替页面争取了近 1.3s 跳转时间，
        比「死等 1s 再截」便宜一半（真机 v2 每任务在这里花 2.2s）。
        """
        self.ui.sleep(0.35)
        for i in range(tries):
            there = self._panel_there()
            if there is None:
                return None
            if not there:
                return True
            self.ui.sleep(0.9 if i < 2 else 1.4)
        return False

'''
s = s.replace(old_lp, new_lp, 1)

# 7) _do_one：不碰 XML + 收紧等待
old_do = s[s.index("    def _do_one(self, row):"):s.index("    def _refresh_panel(self):")]
new_do = '''    def _do_one(self, row):
        """点按钮 → 确认离场 → 停留 9~10s → back 一次回面板。

        全程只用「截图 + 像素」，一次 page_source 都不读：
        真机 21:5x 那次就是在这里 dump XML 把 uiautomator2 server 打崩的，
        之后要重建 session，一个任务赔掉 300s。
        """
        pt = row.get("center") or center(row["bounds"])
        self.ui.adb_tap(pt, pause=0.4, settle=0)
        left = self._left_panel()
        if left is None:
            # 像素判不出来就再看一帧；仍判不出就按「已离开」走，
            # 真正的成功判据是停留结束 back 回来时面板还在。（不读 XML）
            left = not (self._panel_there() is True)
        if not left:
            self._say(u"点了按钮页面没动，本次点击可能被吞", "WARN")
            return False, None
        secs = self._dwell()
        self._say(u"任务【%s】%s 按钮【%s】%s，停留 %ds"
                  % (row["title"] or row["key"], row["reward"],
                     row["text"], pt, secs))
        if not self.ui.sleep(secs):
            return False, None
        self._back(pause=0.5)
        shot = None
        for _ in range(3):
            shot = self._shot()
            there = self._panel_there(shot)
            if there is None:
                break
            if there:
                self.panel_believed = True
                return True, shot
            self.ui.sleep(0.7)
        self._say(u"浏览后没回到任务弹窗，重建入口", "WARN")
        self.panel_believed = False
        return self._open_panel(), None

'''
s = s.replace(old_do, new_do, 1)

# 8) _reach_center：点击等待减半（原来 pause 被 sleep 两次 = 3.2s）
s = rep(s,
        """                if b:
                    self._say(u"点顶部一级 tab【特价】%s" % (b,))
                    self._tap(b, pause=1.6)
                    self.ui.sleep(1.0)
                    continue""",
        """                if b:
                    self._say(u"点顶部一级 tab【特价】%s" % (b,))
                    self._tap(b, pause=1.4, settle=0)
                    self.ui.sleep(0.6)
                    continue""",
        "tejia tap")
s = rep(s,
        """                if b:
                    self._say(u"点二级 tab【领券中心】%s" % (b,))
                    self._tap(b, pause=1.6)
                    self.ui.sleep(1.2)
                    continue""",
        """                if b:
                    self._say(u"点二级 tab【领券中心】%s" % (b,))
                    self._tap(b, pause=1.4, settle=0)
                    self.ui.sleep(0.8)
                    continue""",
        "coupon tap")
s = rep(s,
        """    def _tap(self, b, pause=1.0):
        # b 来自 XML/OCR，已经是设备像素，不再 sx/sy 缩放
        self.ui.adb_tap(center(b), pause=pause)""",
        """    def _tap(self, b, pause=1.0, settle=None):
        # b 来自 XML/OCR，已经是设备像素，不再 sx/sy 缩放
        self.ui.adb_tap(center(b), pause=pause, settle=settle)""",
        "_tap sig")

# 9) 入口点击后等待 1.2 -> 0.9
s = rep(s, """            self._tap_entry(b)
            self.expect_panel = True
            self.panel_believed = True
            self.scrolled = False
            self.ui.sleep(1.2)""",
        """            self._tap_entry(b)
            self.expect_panel = True
            self.panel_believed = True
            self.scrolled = False
            self.ui.sleep(0.9)""",
        "entry wait")

# 10) main 收尾：断连要说清楚
s = rep(s,
        """        if total >= MAX_TASKS:""",
        """        if self._dead:
            self._say(u"手机/Appium 中途断开，本轮提前结束（已浏览 %d 次）。"
                      u"重新插好 USB 后再跑一次即可接着做。" % total, "ERROR")
        if total >= MAX_TASKS:""",
        "dead report")

swap(MOD, s)
print("module patched, lines =", s.count("\n"))
