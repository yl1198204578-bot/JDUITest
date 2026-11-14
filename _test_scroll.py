# -*- coding: utf-8 -*-
"""真机验证：面板内短滑动到底能不能滚动列表（用 OCR 按钮坐标对比）。"""
import io
import os
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.abspath(__file__))
ADB = os.path.join(os.environ.get("ANDROID_HOME", "D:/Android"),
                   "platform-tools", "adb.exe")

from PIL import Image
from modules.task14_coupons_v2 import ocr_panel_items, OCR_BOX, SWIPE_UP


def shot(name):
    p = os.path.join(ROOT, name)
    if os.path.isfile(p):
        os.remove(p)
    with open(p, "wb") as f:
        subprocess.call([ADB, "exec-out", "screencap", "-p"], stdout=f)
    return p


def rows(p):
    items = ocr_panel_items(p, OCR_BOX, 0.45) or []
    return [(it["text"], it["y1"]) for it in items
            if it["text"] in (u"去完成", u"去浏览", u"逛一逛", u"已完成")]


def main():
    a = shot("_scroll_a.png")
    t0 = time.time()
    ra = rows(a)
    print("A: %d 个按钮 %s  (%.1fs)" % (len(ra), ra[:8], time.time() - t0))
    if not ra:
        print("当前不在任务面板，先手动打开再跑")
        return
    x1, y1, x2, y2 = SWIPE_UP
    subprocess.call([ADB, "shell", "input", "swipe",
                     str(x1), str(y1), str(x2), str(y2), "450"])
    time.sleep(1.0)
    b = shot("_scroll_b.png")
    t0 = time.time()
    rb = rows(b)
    print("B: %d 个按钮 %s  (%.1fs)" % (len(rb), rb[:8], time.time() - t0))
    moved = [y for _, y in ra] != [y for _, y in rb]
    print("滑动后坐标变化:", moved)
    if not moved:
        # 换一种滑法：起点更低，时长更长
        subprocess.call([ADB, "shell", "input", "swipe",
                         "540", "1800", "540", "1200", "600"])
        time.sleep(1.0)
        c = shot("_scroll_c.png")
        rc = rows(c)
        print("C: %d 个按钮 %s" % (len(rc), rc[:8]))
        print("第二种滑法是否变化:", [y for _, y in ra] != [y for _, y in rc])


if __name__ == "__main__":
    main()
