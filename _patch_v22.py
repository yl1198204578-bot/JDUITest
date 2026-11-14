# -*- coding: utf-8 -*-
"""v2.2：行校验改为「整行 OCR 比对 key」，避免行上移后点到别的任务。"""
import io
import os
import uuid

P = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 "modules", "task14_coupons_v2.py")
s = io.open(P, encoding="utf-8").read()

a = s.index("    def _row_ready(self, row):")
b = s.index("    def _dwell(self):")
NEW = '''    def _row_ready(self, row):
        """轻量校验：这一行还是不是原来那个任务（≈0.4s）。

        整帧 OCR 要 5~7s，每个任务都重来太慢；但做满的行会被换成
        【已完成/领取奖励】，后面的行整体上移，按缓存坐标点就会点到别的
        任务上。所以点之前只 OCR 这一行（标题 + 奖励 + 按钮），
        用同一套配对逻辑算 key，和缓存 key 对上才点。
        """
        b = row.get("bounds")
        if not valid(b):
            return False
        box = (40, max(0, b[1] - 45),
               min(self.ui.W, 1065), min(self.ui.H, b[1] + 135))
        items = self._ocr(box, 1.0)
        if items is None:
            return True                # 识别失败就信缓存，别把整轮卡死
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

tmp = os.path.join(os.path.dirname(P), "_tmp_%s.py" % uuid.uuid4().hex[:8])
io.open(tmp, "w", encoding="utf-8").write(s)
os.remove(P)
os.rename(tmp, P)
print("patched, lines =", len(s.split("\n")))
