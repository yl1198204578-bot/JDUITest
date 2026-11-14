# -*- coding: utf-8 -*-
"""补 panel_ref 初始化。"""
import io
import os
import uuid

P = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 "modules", "task14_coupons_v2.py")
s = io.open(P, encoding="utf-8").read()

old = "        self._prev_progress = {}         # 上一整帧的 (key -> N)\n"
new = ("        self._prev_progress = {}         # 上一整帧的 (key -> N)\n"
       "        self.panel_ref = None            # 面板标题条像素参照\n")
assert old in s
s = s.replace(old, new, 1)

old = """        self._prev_progress = {}
        self._verify_hit = False"""
new = """        self._prev_progress = {}
        self.panel_ref = None
        self._verify_hit = False"""
assert old in s
s = s.replace(old, new)

tmp = os.path.join(os.path.dirname(P), "_tmp_%s.py" % uuid.uuid4().hex[:8])
io.open(tmp, "w", encoding="utf-8").write(s)
os.remove(P)
os.rename(tmp, P)
print("ok", s.count("panel_ref"))
