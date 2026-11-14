# -*- coding: utf-8 -*-
"""诊断：为什么红按钮判据不通过（打印行坐标与多种红色阈值占比）。"""
import os
import sys
import threading
import time

sys.stdout.reconfigure(encoding="utf-8")

import modules.task14_coupons_v2 as M
import utils.driver as driver
from utils.jd_ui import JDUI
from PIL import Image


class Log(object):
    def write_log(self, msg, level="INFO"):
        print("  [%s] %s" % (level, msg))

    def done(self, msg=""):
        pass

    def error(self, msg=""):
        pass


def ratio(path, box, t=(170, 110, 110)):
    im = Image.open(path).crop(box).convert("RGB")
    px = list(im.getdata())
    hit = sum(1 for r, g, b in px if r > t[0] and g < t[1] and b < t[2])
    return hit / float(len(px) or 1)


def main():
    m = M.Task14Coupons()
    m.log = Log()
    m.stop = threading.Event()
    m._warm_ocr()
    m.ui = JDUI(driver.get_driver(), m.log, m.stop)
    if not m._reach_center() or not m._open_panel():
        print("进不去面板")
        return
    f = m._panel_frame()
    rows = (f or {}).get("rows") or []
    print("rows:", len(rows))
    shot = m._shot()
    for r in rows:
        b = r["bounds"]
        print("key=%s bounds=%s center=%s"
              % (r["key"], b, r["center"]))
        for name, box in (("text", (b[0] - 30, b[1], b[2] + 30, b[3])),
                          ("btn", (855, b[1] - 25, 970, b[1] + 40)),
                          ("big", (820, b[1] - 40, 1010, b[1] + 55))):
            print("   %-5s %s ratio(170/110)=%.2f ratio(140/120)=%.2f"
                  % (name, box, ratio(shot, box),
                     ratio(shot, box, (140, 120, 120))))
    print("panel_there:", m._panel_there(shot), "ref:", bool(m.panel_ref))
    print("row_ready:", [m._row_ready(r) for r in rows])


if __name__ == "__main__":
    main()
