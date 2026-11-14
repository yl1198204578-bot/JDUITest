# -*- coding: utf-8 -*-
"""v2.4：标定后的像素判据 + 刷新用点 X 关面板。

_calib_px.py 实测（1080x2340）：
  面板在场：同一块补丁三帧完全一致（差 0.0）
  面板关掉：(44,876,292,958) 差 41.5 —— 只取标题文字，避开会动的 ￥ 图标
  阈值 20 安全；另外 back 关不掉这个半屏 sheet，刷新必须点右上角 X。
"""
import io
import os
import uuid

P = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 "modules", "task14_coupons_v2.py")
s = io.open(P, encoding="utf-8").read()

old = """PANEL_DIFF_MAX = 28          # 标题条补丁的平均灰度差上限（>28 认为面板没了）
RED_MIN = 0.30               # 按钮区「京东红」像素占比下限（去完成 vs 已完成）
PATCH_BOX = (0, 860, 700, 1010)
PATCH_SIZE = (24, 8)"""
new = """PANEL_DIFF_MAX = 20          # 标题条补丁的平均灰度差上限（>20 认为面板没了）
RED_MIN = 0.30               # 按钮区「京东红」像素占比下限（去完成 vs 已完成）
PATCH_BOX = (44, 876, 292, 958)   # 只框【做任务得奖励】文字，避开会动的 ￥ 图标
PATCH_SIZE = (24, 8)
PANEL_CLOSE_XY = (1015, 895)      # 弹窗右上角 X（back 关不掉这个半屏 sheet）"""
assert old in s
s = s.replace(old, new)

a = s.index("    def _refresh_panel(self):")
b = s.index("    def _do_tasks(self):")
NEW = '''    def _refresh_panel(self):
        """点 X 关掉再重开任务面板，让服务端重新下发任务池。

        真机实测 back 关不掉这个半屏 sheet（只会把背景页一起退掉），
        必须点右上角 X。
        """
        if self._refreshed:
            return False
        self._refreshed = True
        self._say(u"列表里已没有可做任务，关掉弹窗重开刷新一次任务池")
        self.ui.adb_tap(PANEL_CLOSE_XY, pause=0.8)
        self.ui.sleep(0.8)
        self.expect_panel = False
        self.panel_believed = False
        self.panel_ref = None
        for _ in range(2):
            if not self._panel_there():
                break
            self._say(u"X 没关掉，再点一次", "WARN")
            self.ui.adb_tap(PANEL_CLOSE_XY, pause=0.8)
            self.ui.sleep(0.8)
        return self._open_panel()

'''
s = s[:a] + NEW + s[b:]

tmp = os.path.join(os.path.dirname(P), "_tmp_%s.py" % uuid.uuid4().hex[:8])
io.open(tmp, "w", encoding="utf-8").write(s)
os.remove(P)
os.rename(tmp, P)
print("ok")
