# -*- coding: utf-8 -*-
"""回归补丁：J12~J15 也必须走替身，否则 _default_shot 会去截真机。"""
import io
import os
import uuid

P = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 "_test_task14_coupons_v2.py")
s = io.open(P, encoding="utf-8").read()

old = '''m2.stop = threading.Event()
check("J12 _reach_center 从首页走到领券中心（顺手关掉浮层）",'''
new = '''m2.stop = threading.Event()
# 这一段的 _open_panel 会截图，必须注入替身，否则会去截真机
_j_shot, _j_ocr = MOD.SHOT_HOOK, MOD.OCR_HOOK
MOD.SHOT_HOOK = lambda ui: "_fixture_coupon_panel.png"
MOD.OCR_HOOK = lambda path: sim2.ocr_items()
check("J12 _reach_center 从首页走到领券中心（顺手关掉浮层）",'''
assert old in s
s = s.replace(old, new)

old = '''check("J15 _open_panel 从 center 打开面板",
      m2._open_panel() and sim2.state == "panel" and
      sim2.panel_opens == 1)'''
new = '''check("J15 _open_panel 从 center 打开面板",
      m2._open_panel() and sim2.state == "panel" and
      sim2.panel_opens == 1)
MOD.SHOT_HOOK, MOD.OCR_HOOK = _j_shot, _j_ocr'''
assert old in s
s = s.replace(old, new)

tmp = os.path.join(os.path.dirname(P), "_tmp_%s.py" % uuid.uuid4().hex[:8])
io.open(tmp, "w", encoding="utf-8").write(s)
os.remove(P)
os.rename(tmp, P)
print("ok")
