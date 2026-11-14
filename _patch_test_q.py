# -*- coding: utf-8 -*-
"""回归补 Q 段：v3.2 提速（回顶判像素、重开走缓存坐标、收尾分「没开始」）。"""
import io
import os
import uuid

ROOT = os.path.dirname(os.path.abspath(__file__))
P = os.path.join(ROOT, "_test_task14_coupons.py")
s = io.open(P, encoding="utf-8").read()

TAIL = '''

# ================================================================ Q
print("\\n--- Q. v3.2 提速 ---")
mq = Task14Coupons()
sq = SimUI()
sq.state = "panel"
mq.ui = sq
mq.log = Log()
mq.stop = threading.Event()
mq.panel_believed = True
mq.expect_panel = True
_ocr0 = sq.ocr_calls
mq.scrolled = True
mq._to_top()
check("Q1 回顶判「到没到顶」不再烧整帧 OCR",
      sq.ocr_calls == _ocr0, "OCR 多跑了 %d 次" % (sq.ocr_calls - _ocr0))
check("Q2 回顶会真的往下滑（没滑过就不动）",
      len(sq.swipes) >= 1, "%d" % len(sq.swipes))
sq2 = SimUI()
mq2 = Task14Coupons()
mq2.ui = sq2
mq2.log = Log()
mq2.stop = threading.Event()
mq2.scrolled = False
_before = len(sq2.swipes)
mq2._to_top()
check("Q3 没滑过列表时不回顶（避免把半屏 sheet 拖关）",
      len(sq2.swipes) == _before, "%d" % len(sq2.swipes))

mr = Task14Coupons()
sr = SimUI()
sr.state = "center"
sr.panel_opens = 0
mr.ui = sr
mr.log = Log()
mr.stop = threading.Event()
mr._entry_bounds = ENTRY_PT
mr.panel_believed = False
mr.expect_panel = False
_ocr1 = sr.ocr_calls
_ok = mr._reopen_fast()
check("Q4 弹窗被带关时直接点缓存入口卡重开（不跑整轮状态机）",
      _ok is True and sr.state == "panel" and sr.panel_opens == 1,
      "%s %s %d" % (_ok, sr.state, sr.panel_opens))
check("Q5 重开只用一次标题条 OCR（≈1.5s），不是整帧",
      sr.ocr_calls - _ocr1 <= 2, "%d" % (sr.ocr_calls - _ocr1))

mr2 = Task14Coupons()
sr2 = SimUI()
sr2.state = "center"
mr2.ui = sr2
mr2.log = Log()
mr2.stop = threading.Event()
mr2._entry_bounds = None          # 没有缓存坐标 → 退回完整状态机
_ok2 = mr2._reopen_fast()
check("Q6 没有缓存坐标时仍能重开（退回 _open_panel）",
      _ok2 is True and sr2.state == "panel", "%s %s" % (_ok2, sr2.state))

ml = Task14Coupons()
ml.log = Log()
ml.attempts = {task_key(u"逛一逛活动得奖励", u"去完成"): 5}
_rows = [{"key": task_key(u"逛一逛活动得奖励", u"去完成"),
          "title": u"逛一逛活动得奖励(0/5)", "reward": u"浏览完成得2京豆",
          "text": u"去完成", "beans": 2, "bounds": (855, 1115, 970, 1176)},
         {"key": task_key(u"浏览会场得京豆", u"去完成"),
          "title": u"浏览会场得京豆(0/6)", "reward": u"浏览完成得2京豆",
          "text": u"去完成", "beans": 2, "bounds": (855, 1311, 970, 1372)}]
ml._report_left(_rows)
_txt = ml.log.text()
check("Q7 收尾把「一次都没开始」和「做了没做满」分开说",
      u"一次都没做" in _txt and u"没做满" not in _txt, _txt[-200:])
'''

anchor = '''

print("\\n================ 汇总 ================")'''
assert anchor in s
s = s.replace(anchor, TAIL + anchor, 1)

tmp = os.path.join(ROOT, "_tmp_%s.py" % uuid.uuid4().hex[:8])
io.open(tmp, "w", encoding="utf-8", newline="\n").write(s)
os.rename(P, os.path.join(ROOT, "_archive", "test_prev4_%s.txt"
                          % uuid.uuid4().hex[:6]))
os.rename(tmp, P)
print("patched")
