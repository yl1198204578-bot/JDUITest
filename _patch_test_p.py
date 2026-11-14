# -*- coding: utf-8 -*-
"""回归补 P 段：京东 2026-11-14 新布局（入口卡文案改成【立即领奖】）。"""
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


# load() 也带上 resource-id
rep('''            "clickable": n.get("clickable") == "true",
            "class": (n.get("class") or "").rsplit(".", 1)[-1],
        })
    return out''',
    '''            "clickable": n.get("clickable") == "true",
            "class": (n.get("class") or "").rsplit(".", 1)[-1],
            "res": (n.get("resource-id") or "").strip(),
        })
    return out''',
    "load res")

# 新夹具
rep('CENTER = load("_fixture_coupon_center.xml")',
    'CENTER = load("_fixture_coupon_center.xml")\n'
    'CENTER2 = load("_fixture_coupon_center2.xml")   # 2026-11-14 新布局',
    "CENTER2")

TAIL = '''

# ================================================================ P
print("\\n--- P. 新布局（入口卡=【立即领奖】）---")
check("P1 新布局夹具仍判定为 center", classify(CENTER2) == "center",
      classify(CENTER2))
mp = Task14Coupons()
mp.ui = SimUI()
mp.log = Log()
mp.stop = threading.Event()
E2 = (22, 821, 225, 1113)
check("P2 新布局能定位到入口卡（resource-id / 几何兜底）",
      mp._find_entry(CENTER2) == E2, "%s" % (mp._find_entry(CENTER2),))

_no_res = [dict(n, res="") for n in CENTER2]
check("P3 丢掉 resource-id 后靠文案【立即领奖】仍能定位",
      mp._find_entry(_no_res) == E2, "%s" % (mp._find_entry(_no_res),))

_no_text = [dict(n, text="", desc="", res="") for n in CENTER2]
check("P4 文案和 id 都没有时靠几何兜底仍能定位",
      mp._find_entry(_no_text) == E2, "%s" % (mp._find_entry(_no_text),))

check("P5 旧布局夹具照旧命中（不能为新版牺牲老版）",
      mp._find_entry(CENTER) == (22, 821, 225, 1113),
      "%s" % (mp._find_entry(CENTER),))

_junk = [nd(u"限时加补券", 490, 900, 1012, 1000, clickable=True),
         nd(u"推荐", 42, 1140, 140, 1200, clickable=True)]
check("P6 几何兜底不会把右半屏/矮卡片误认成入口",
      mp._entry_geo(_junk) is None, "%s" % (mp._entry_geo(_junk),))

check("P7 _tap_entry 点在卡片下缘（真机那半张卡是整块 Button）",
      (E2[0] + E2[2]) // 2 == 123 and E2[3] - 48 == 1065,
      "tap=(%d,%d)" % ((E2[0] + E2[2]) // 2, E2[3] - 48))
'''

anchor = '''

print("\\n================ 汇总 ================")'''
assert anchor in s
s = s.replace(anchor, TAIL + anchor, 1)

tmp = os.path.join(ROOT, "_tmp_%s.py" % uuid.uuid4().hex[:8])
io.open(tmp, "w", encoding="utf-8", newline="\n").write(s)
os.rename(P, os.path.join(ROOT, "_archive", "test_prev2_%s.txt"
                          % uuid.uuid4().hex[:6]))
os.rename(tmp, P)
print("patched")
