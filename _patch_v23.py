# -*- coding: utf-8 -*-
"""v2.3：面板在场 / 按钮是否还在 改用像素校验（1.0s），不再每帧跑 OCR（2.1s）。

真机实测（_test_shot.py / _debug_panel.py）：
  截图 0.9s，取像素补丁 0.00s，标题条 OCR 2.1s（3 块），整帧 OCR 8~19s（27 块）。
  所以「点完跳没跳走」「按钮还在不在」这类二元判断用像素，OCR 只留给整帧解析。
"""
import io
import os
import uuid

P = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 "modules", "task14_coupons_v2.py")
s = io.open(P, encoding="utf-8").read()

# ---------- 1. 常量 ----------
old = "MAX_OCR = 400"
new = ("MAX_OCR = 400\n"
       "PANEL_DIFF_MAX = 28          # 标题条补丁的平均灰度差上限（>28 认为面板没了）\n"
       "RED_MIN = 0.30               # 按钮区「京东红」像素占比下限（去完成 vs 已完成）\n"
       "PATCH_BOX = (0, 860, 700, 1010)\n"
       "PATCH_SIZE = (24, 8)\n")
assert old in s
s = s.replace(old, new, 1)

# ---------- 2. 像素工具（纯函数，放模块级） ----------
old = "def adb_path():"
new = '''def patch_vec(shot, box=None, size=None):
    """把标题条压成 24x8 灰度向量，用于判「面板还在不在」（≈0.15s）。"""
    if not shot or not os.path.isfile(shot):
        return None
    try:
        from PIL import Image
        im = Image.open(shot)
        g = im.crop(box or PATCH_BOX).convert("L").resize(size or PATCH_SIZE)
        return list(g.getdata())
    except Exception:
        return None


def patch_diff(a, b):
    if not a or not b or len(a) != len(b):
        return 999.0
    return sum(abs(x - y) for x, y in zip(a, b)) / float(len(a))


def red_ratio(shot, box):
    """按钮区里「京东红」像素占比：0.3 以上基本就是【去完成】红按钮。"""
    if not shot or not os.path.isfile(shot):
        return 0.0
    try:
        from PIL import Image
        im = Image.open(shot).crop(box)
        px = im.convert("RGB").getdata()
        n = 0
        hit = 0
        for r, g, b in px:
            n += 1
            if r > 170 and g < 110 and b < 110:
                hit += 1
        return hit / float(n or 1)
    except Exception:
        return 0.0


def adb_path():'''
assert old in s
s = s.replace(old, new, 1)

# ---------- 3. _ocr 支持传入已截好的图 ----------
old = '''    def _ocr(self, box=None, scale=None):
        """截一帧并识别指定区域，返回 OCR 块或 None（失败）。"""'''
new = '''    def _ocr(self, box=None, scale=None, shot=None):
        """截一帧并识别指定区域，返回 OCR 块或 None（失败）。"""'''
assert old in s
s = s.replace(old, new)

old = '''            path = SHOT_HOOK(self.ui) if SHOT_HOOK else _default_shot(self.ui)
            if OCR_HOOK:
                return OCR_HOOK(path)
            if not path:
                return None
            res = ocr_panel_items(path, box, scale)'''
new = '''            path = shot or (SHOT_HOOK(self.ui) if SHOT_HOOK
                            else _default_shot(self.ui))
            if OCR_HOOK:
                return OCR_HOOK(path)
            if not path:
                return None
            res = ocr_panel_items(path, box, scale)'''
assert old in s
s = s.replace(old, new)

# ---------- 4. _panel_there / _panel_frame 改成像素优先 ----------
a = s.index("    def _panel_there(self):")
b = s.index("    def _probe(self, panel_first=None, force_xml=False):")
NEW = '''    def _shot(self):
        return SHOT_HOOK(self.ui) if SHOT_HOOK else _default_shot(self.ui)

    def _panel_there(self, shot=None):
        """面板在不在：像素补丁比对（≈1.0s），没有参照时退化为标题条 OCR。

        面板头部（做任务得奖励 / 每日最高可领1000京豆 / 我的奖励）是静态的，
        和「面板不在时那块背景」差得很远，比 OCR 便宜一倍。
        注入 SHOT_HOOK/OCR_HOOK 的离线回归走 OCR 通道，保证可复现。
        """
        shot = shot or self._shot()
        if shot is None:
            return None
        if OCR_HOOK is not None or self.panel_ref is None:
            items = self._ocr(OCR_TITLE_BOX, OCR_TITLE_SCALE, shot=shot)
            if items is None:
                return None
            return ocr_panel_visible(items)
        return patch_diff(patch_vec(shot), self.panel_ref) < PANEL_DIFF_MAX

    def _panel_frame(self):
        """整块面板 OCR：返回 {'panel','items','rows','sig'}，None=识别失败。"""
        shot = self._shot()
        items = self._ocr(shot=shot)
        if items is None:
            return None
        if not ocr_panel_visible(items):
            return {"panel": False, "items": items, "rows": [], "sig": ()}
        self.panel_ref = patch_vec(shot)
        return {"panel": True, "items": items,
                "rows": parse_ocr_rows(items), "sig": ocr_sig(items)}

'''
s = s[:a] + NEW + s[b:]

# ---------- 5. _left_panel / _row_ready / _do_one ----------
a = s.index("    def _left_panel(self, tries=4):")
b = s.index("    def _dwell(self):")
NEW = '''    def _left_panel(self, tries=4):
        """点完任务按钮后确认已经离开面板。

        True=已离开 / False=面板还在（点击被吞）/ None=判不出来。
        慢页面要 2~3s 才换页，所以最多看 4 次；真机 21:44 就是因为
        只看两次，把「还在动画」误判成「点击被吞」，连丢 3 个任务。
        """
        self.ui.sleep(1.0)             # 先给页面 1s 开始跳转
        for i in range(tries):
            there = self._panel_there()
            if there is None:
                return None
            if not there:
                return True
            self.ui.sleep(1.2 if i < 2 else 1.8)
        return False

    def _row_ready(self, row, shot=None):
        """轻量校验：这一行的红按钮还在不在原坐标（≈1.0s）。

        整帧 OCR 要 8~19s，每个任务都重来太慢；但做满的行会被换成
        【已完成】灰按钮、后面的行整体上移，按缓存坐标点就会点到别的任务。
        红按钮的红色占比是最便宜的「还在原位」判据；拿不准时再退回整行 OCR。
        """
        b = row.get("bounds")
        if not valid(b):
            return False
        shot = shot or self._shot()
        if shot is None:
            return True
        there = self._panel_there(shot)
        if there is False:
            return False
        if OCR_HOOK is None:
            ratio = red_ratio(shot, (max(0, b[0] - 30), b[1],
                                     min(self.ui.W, b[2] + 30), b[3]))
            if ratio >= RED_MIN:
                return True
            self._say(u"这一行的红按钮不见了（%s），重读整帧" % row["key"],
                      "DEBUG")
            return False
        # 离线回归：走 OCR 通道，按 key 精确比对
        items = self._ocr((40, max(0, b[1] - 45), min(self.ui.W, 1065),
                           min(self.ui.H, b[1] + 135)), 1.0, shot=shot)
        if items is None:
            return True
        nodes = [{"text": it.get("text", ""),
                  "bounds": (int(it["x1"]), int(it["y1"]),
                             int(it["x2"]), int(it["y2"])),
                  "clickable": True, "class": "TextView"}
                 for it in items]
        for r in _rows_from_nodes(nodes):
            if r["key"] == row["key"]:
                return True
        self._say(u"这一行已变化（%s 不在原位），重读整帧" % row["key"], "DEBUG")
        return False

'''
s = s[:a] + NEW + s[b:]

# _do_one 返回 (ok, shot)
old = '''        if not left:
            self._say(u"点了按钮页面没动，本次点击可能被吞", "WARN")
            return False'''
new = '''        if not left:
            self._say(u"点了按钮页面没动，本次点击可能被吞", "WARN")
            return False, None'''
assert old in s
s = s.replace(old, new)

old = '''        if not self.ui.sleep(secs):
            return False
        self._back(pause=0.7)
        for _ in range(3):
            there = self._panel_there()
            if there is None:
                break
            if there:
                self.panel_believed = True
                return True
            self.ui.sleep(0.8)
        self._say(u"浏览后没回到任务弹窗，重建入口", "WARN")
        self.panel_believed = False
        return self._open_panel()'''
new = '''        if not self.ui.sleep(secs):
            return False, None
        self._back(pause=0.7)
        shot = None
        for _ in range(3):
            shot = self._shot()
            there = self._panel_there(shot)
            if there is None:
                break
            if there:
                self.panel_believed = True
                return True, shot
            self.ui.sleep(0.8)
        self._say(u"浏览后没回到任务弹窗，重建入口", "WARN")
        self.panel_believed = False
        return self._open_panel(), None'''
assert old in s
s = s.replace(old, new)

# 主循环：复用 back 后那张图 + 适配二元组返回
old = '''                    while left > 0 and not self._stopped() and total < MAX_TASKS:
                        if not self._row_ready(row):
                            break          # 行上移了，跳出重读整帧
                        ok = self._do_one(row)'''
new = '''                    shot = None
                    while left > 0 and not self._stopped() and total < MAX_TASKS:
                        if not self._row_ready(row, shot):
                            break          # 行上移了，跳出重读整帧
                        ok, shot = self._do_one(row)'''
assert old in s
s = s.replace(old, new)

tmp = os.path.join(os.path.dirname(P), "_tmp_%s.py" % uuid.uuid4().hex[:8])
io.open(tmp, "w", encoding="utf-8").write(s)
os.remove(P)
os.rename(tmp, P)
print("patched, lines =", len(s.split("\n")))
