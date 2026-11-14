# -*- coding: utf-8 -*-
"""真机调试：进面板 → 整帧 OCR → 滑动 → 再 OCR，量各环节耗时。"""
import io
import os
import sys
import threading
import time

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.abspath(__file__))
import modules.task14_coupons_v2 as M
import utils.driver as driver
from utils.jd_ui import JDUI


class Log(object):
    def write_log(self, msg, level="INFO"):
        print("[%5.1fs %s] %s" % (time.time() - T0, level, msg))

    def done(self, msg=""):
        print("[%5.1fs DONE] %s" % (time.time() - T0, msg))

    def error(self, msg=""):
        print("[%5.1fs ERR] %s" % (time.time() - T0, msg))


T0 = time.time()


def timed(label, fn, *a, **k):
    t = time.time()
    r = fn(*a, **k)
    print("  %-22s %5.1fs" % (label, time.time() - t))
    return r


def main():
    log = Log()
    stop = threading.Event()
    m = M.Task14Coupons()
    m.log = log
    m.stop = stop
    m._warm_ocr()
    ui = JDUI(driver.get_driver(), log, stop)
    m.ui = ui
    if not m._reach_center():
        print("没进到领券中心")
        return
    if not m._open_panel():
        print("没打开面板")
        return

    # 面板在顶部时先整帧识别
    f = timed("整帧 OCR", m._panel_frame)
    print("rows:", [(r["title"], r["bounds"][1]) for r in (f or {}).get("rows", [])])
    timed("标题条 OCR", m._panel_there)
    row = (f or {}).get("rows", [None])[0]
    if row:
        timed("行校验 OCR", m._row_ready, row)

    # 滑动是否真的滚动列表
    print("-- 短滑动 1600 -> 1100 --")
    m._scroll_up()
    f2 = timed("整帧 OCR", m._panel_frame)
    print("rows:", [(r["title"], r["bounds"][1]) for r in (f2 or {}).get("rows", [])])
    print("签名变化:", (f or {}).get("sig") != (f2 or {}).get("sig"))

    print("-- 再滑一次 --")
    m._scroll_up()
    f3 = timed("整帧 OCR", m._panel_frame)
    print("rows:", [(r["title"], r["bounds"][1]) for r in (f3 or {}).get("rows", [])])
    print("签名变化:", (f2 or {}).get("sig") != (f3 or {}).get("sig"))

    # 截图耗时
    timed("截图", M._default_shot, ui)


if __name__ == "__main__":
    main()
