# -*- coding: utf-8 -*-
"""标定：面板标题条像素判据（哪块最稳、阈值多少）。"""
import os
import sys
import threading
import time

sys.stdout.reconfigure(encoding="utf-8")

import modules.task14_coupons_v2 as M
import utils.driver as driver
from utils.jd_ui import JDUI

BOXES = [(40, 878, 320, 958), (40, 878, 430, 1000), (0, 860, 700, 1010)]
CLOSE_XY = (1015, 895)


class Log(object):
    def write_log(self, msg, level="INFO"):
        pass

    def done(self, msg=""):
        pass

    def error(self, msg=""):
        pass


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

    refs = {}
    for i in range(3):
        shot = m._shot()
        for b in BOXES:
            refs.setdefault(b, []).append(M.patch_vec(shot, b))
        print("面板在场，第 %d 张已取" % (i + 1))

    print("== 面板在场时的自比较（越小越稳）==")
    for b in BOXES:
        v = refs[b]
        print("  %-22s %.1f" % (str(b), M.patch_diff(v[0], v[1])))

    print("== 点 X 关掉面板 ==")
    m.ui.adb_tap(CLOSE_XY, pause=1.0)
    m.ui.sleep(1.0)
    print("  标题条 OCR 还在吗:", m._panel_there())
    shot = m._shot()
    print("== 关闭后与参照的差（越大越安全）==")
    for b in BOXES:
        print("  %-22s %.1f" % (str(b), M.patch_diff(refs[b][0],
                                                     M.patch_vec(shot, b))))

    print("== 再截一张，看关闭后两帧之间是否稳定 ==")
    shot2 = m._shot()
    for b in BOXES:
        print("  %-22s %.1f" % (str(b), M.patch_diff(M.patch_vec(shot, b),
                                                     M.patch_vec(shot2, b))))

    print("== 重新打开面板 ==")
    m.expect_panel = False
    m.panel_believed = False
    print("  open:", m._open_panel())
    shot3 = m._shot()
    for b in BOXES:
        print("  重新打开后与参照差 %-22s %.1f"
              % (str(b), M.patch_diff(refs[b][0], M.patch_vec(shot3, b))))


if __name__ == "__main__":
    main()
