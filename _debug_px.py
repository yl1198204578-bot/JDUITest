# -*- coding: utf-8 -*-
"""真机验证像素校验：面板在场 / 面板关掉 / 红按钮识别 / 各步耗时。"""
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


def main():
    log = Log()
    stop = threading.Event()
    m = M.Task14Coupons()
    m.log = log
    m.stop = stop
    m._warm_ocr()
    m.ui = JDUI(driver.get_driver(), log, stop)
    if not m._reach_center() or not m._open_panel():
        print("进不去面板")
        return

    t = time.time()
    print("面板在场:", m._panel_there(), "%.2fs" % (time.time() - t))
    t = time.time()
    f = m._panel_frame()
    print("整帧 OCR %.1fs 行=%d 参照=%s"
          % (time.time() - t, len((f or {}).get("rows", [])),
             bool(m.panel_ref)))

    # 用 OCR 出来的按钮位置验证红按钮判据
    items = (f or {}).get("items") or []
    btns = [it for it in items if M.norm(it["text"]) in M.ALL_BTN_TEXTS]
    for it in btns[:4]:
        shot = m._shot()
        box = (it["x1"] - 10, it["y1"], it["x2"] + 10, it["y2"])
        print("  按钮 %s @y=%d 红色占比 %.2f"
              % (it["text"], it["y1"], M.red_ratio(shot, box)))

    for i in range(3):
        t = time.time()
        print("面板在场(第%d次): %s  %.2fs"
              % (i + 1, m._panel_there(), time.time() - t))

    print("-- back 关掉面板 --")
    m._back(pause=1.0)
    t = time.time()
    print("面板在场:", m._panel_there(), "%.2fs" % (time.time() - t))

    print("-- 重新打开 --")
    m.expect_panel = False
    m.panel_believed = False
    print("open:", m._open_panel())
    t = time.time()
    print("面板在场:", m._panel_there(), "%.2fs" % (time.time() - t))

    print("-- 整屏截图 + 补丁耗时 --")
    t = time.time()
    shot = m._shot()
    print("截图 %.2fs" % (time.time() - t))
    t = time.time()
    M.patch_vec(shot)
    print("补丁 %.2fs" % (time.time() - t))


if __name__ == "__main__":
    main()
