# -*- coding: utf-8 -*-
"""v3.1：入口卡片适配京东 2026-11-14 的新布局。

真机实测（_fixture_coupon_center2.xml）：
  领券中心整页是 canvas 渲染，无障碍树里只剩一个原生 Button：
      text="立即领奖" resource-id="coupon-left-entry" bounds=[22,821][225,1113]
  之前的【更多任务】/【领更多】/【天天领豆】全部不在树里 ——
  按旧文案找入口会 12 次全部落空，最后「未完成（没能打开任务弹窗）」。
"""
import io
import os
import uuid

ROOT = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.join(ROOT, "modules", "task14_coupons.py")
UI = os.path.join(ROOT, "utils", "jd_ui.py")

s = io.open(MOD, encoding="utf-8").read()


def rep(old, new, tag):
    global s
    assert old in s, "MISS " + tag
    s = s.replace(old, new, 1)


rep('ENTRY_TEXTS = (u"更多任务", u"领更多", u"天天领豆")',
    '''# 入口卡的文案京东来回换：更多任务 / 领更多 / 天天领豆 / 立即领奖 / 去完成
ENTRY_TEXTS = (u"更多任务", u"领更多", u"天天领豆", u"立即领奖", u"去完成")
# 比文案稳的是原生控件的 resource-id（2026-11-14 抓到的就是 coupon-left-entry）
ENTRY_RES = (u"coupon-left-entry", u"left-entry")''',
    "ENTRY_TEXTS")

old = s[s.index("    def _find_entry(self, nodes):"):s.index("    def _tap_entry(self, b):")]
new = '''    def _find_entry(self, nodes):
        """找【天天领豆】入口卡。

        三级判据，从稳到糙：
        1. resource-id（真机 coupon-left-entry）：京东改文案也认得出
        2. 文案白名单：更多任务/领更多/天天领豆/立即领奖/去完成
        3. 几何兜底：左半屏、高 150~560 的 clickable 竖卡（页面 canvas 化后
           只剩入口卡是原生控件，兜底基本不会误伤）

        y 不要再卡死 600~1400：领券中心页偶发多插一行金刚区或更高的券 banner，
        实测同一天那张卡被顶到 y≈1685，卡死区间会让状态机静默空转。
        """
        for want in ENTRY_RES:
            for n in nodes:
                if want in (n.get("res") or ""):
                    b = n.get("bounds")
                    if valid(b):
                        return tuple(b)
        for want in ENTRY_TEXTS:
            b = self._find_text(want, nodes, y_min=300, x_max=460,
                                clickable=True)
            if b:
                return b
        for want in ENTRY_TEXTS:
            b = self._find_text(want, nodes, y_min=300, x_max=460,
                                clickable=False)
            if b:
                return self._clickable_container(b, nodes) or b
        return self._entry_geo(nodes)

    def _entry_geo(self, nodes):
        """几何兜底：左半屏的纵向卡片按钮（入口卡就是这么长出来的）。"""
        best = None
        for n in nodes:
            b = n.get("bounds")
            if not valid(b) or not n.get("clickable"):
                continue
            w, h = b[2] - b[0], b[3] - b[1]
            if b[2] > 520 or w < 100:
                continue
            if h < 150 or h > 560:
                continue
            if not (500 <= b[1] <= 1600):
                continue
            if best is None or b[1] < best[1]:
                best = b
        return tuple(best) if best else None

'''
s = s.replace(old, new, 1)

tmp = os.path.join(ROOT, "_tmp_%s.py" % uuid.uuid4().hex[:8])
io.open(tmp, "w", encoding="utf-8", newline="\n").write(s)
os.rename(MOD, os.path.join(ROOT, "_archive", "task14_prev3_%s.txt"
                            % uuid.uuid4().hex[:6]))
os.rename(tmp, MOD)
print("module patched")

# ---------------- jd_ui：nodes 带上 resource-id ----------------
u = io.open(UI, encoding="utf-8").read()
old_ui = '''            out.append({
                "text": t,
                "desc": desc,
                "bounds": b,
                "clickable": n.get("clickable") == "true",
                "class": (n.get("class") or "").rsplit(".", 1)[-1],
            })'''
new_ui = '''            out.append({
                "text": t,
                "desc": desc,
                "bounds": b,
                "clickable": n.get("clickable") == "true",
                "class": (n.get("class") or "").rsplit(".", 1)[-1],
                "res": (n.get("resource-id") or "").strip(),
            })'''
assert old_ui in u
u = u.replace(old_ui, new_ui, 1)
tmp = os.path.join(ROOT, "_tmp_%s.py" % uuid.uuid4().hex[:8])
io.open(tmp, "w", encoding="utf-8", newline="\n").write(u)
os.rename(UI, os.path.join(ROOT, "_archive", "jd_ui_prev_%s.txt"
                           % uuid.uuid4().hex[:6]))
os.rename(tmp, UI)
print("jd_ui patched")
