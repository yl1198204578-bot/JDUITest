# -*- coding: utf-8 -*-
"""v2.7：滑动后列表还有惯性（fling），红按钮判据会偶发扑空 → 加一次重试。

真机 22:04 日志：`_scroll_up()` 后 0.8s 就 OCR，抓到的是还在滑动的中间态，
接着三行 `_row_ready` 全部判失败 → 白跑 30s 再重读整帧。
"""
import io
import os
import uuid

P = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 "modules", "task14_coupons_v2.py")
s = io.open(P, encoding="utf-8").read()

# 1) 滑动后多等一点，别在惯性里读帧
old = """    def _scroll(self, spec, pause=1.0):
        x1, y1, x2, y2 = spec
        self.ui.adb_swipe(self.ui.sx(x1), self.ui.sy(y1),
                          self.ui.sx(x2), self.ui.sy(y2), SWIPE_MS)
        self.ui.sleep(pause)"""
new = """    def _scroll(self, spec, pause=1.6):
        x1, y1, x2, y2 = spec
        self.ui.adb_swipe(self.ui.sx(x1), self.ui.sy(y1),
                          self.ui.sx(x2), self.ui.sy(y2), SWIPE_MS)
        self.ui.sleep(pause)      # 滑动有惯性，0.8s 就读帧会抓到中间态"""
assert old in s
s = s.replace(old, new)
s = s.replace("        self._scroll(SWIPE_UP, pause=0.8)", "        self._scroll(SWIPE_UP)")
s = s.replace("        self._scroll(SWIPE_DOWN, pause=0.8)", "        self._scroll(SWIPE_DOWN)")

# 2) 红按钮判据失败时，隔 0.6s 再看一眼（惯性/重绘）
old = """        if shot is None:
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
            return False"""
new = """        if shot is None:
            return True
        there = self._panel_there(shot)
        if there is False:
            return False
        if OCR_HOOK is None:
            box = (max(0, b[0] - 30), b[1],
                   min(self.ui.W, b[2] + 30), b[3])
            for i in range(2):
                if red_ratio(shot, box) >= RED_MIN:
                    return True
                if i == 0:
                    self.ui.sleep(0.6)
                    shot = self._shot()
                    if shot is None:
                        return True
            self._say(u"这一行的红按钮不见了（%s），重读整帧" % row["key"],
                      "DEBUG")
            return False"""
assert old in s
s = s.replace(old, new)

tmp = os.path.join(os.path.dirname(P), "_tmp_%s.py" % uuid.uuid4().hex[:8])
io.open(tmp, "w", encoding="utf-8").write(s)
os.remove(P)
os.rename(tmp, P)
print("ok")
