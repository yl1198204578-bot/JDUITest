# -*- coding: utf-8 -*-
"""实测：page_source / adb screencap / OCR / tap 各花多久。"""
import io
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")

import utils.driver as driver
from utils.jd_ui import JDUI

t0 = time.time()


def mark(msg):
    print("[%6.2fs] %s" % (time.time() - t0, msg))


d = driver.get_driver()
ui = JDUI(d, None, None)
mark("driver ok %dx%d" % (ui.W, ui.H))

for i in range(3):
    t = time.time()
    xml = ui.source(fresh=True)
    mark("page_source #%d %.2fs len=%d" % (i + 1, time.time() - t, len(xml)))

from modules.task14_coupons_v2 import _default_shot, SHOT_PATH, OCR_BOX, OCR_SCALE, \
    ocr_panel_items, patch_vec, patch_diff, red_ratio

for i in range(3):
    t = time.time()
    p = _default_shot(ui)
    mark("screencap #%d %.2fs %s" % (i + 1, time.time() - t, p))

t = time.time()
patch_vec(SHOT_PATH)
mark("patch_vec %.3fs" % (time.time() - t))
t = time.time()
red_ratio(SHOT_PATH, (700, 2100, 1080, 2200))
mark("red_ratio %.3fs" % (time.time() - t))

t = time.time()
from modules.task5_joy_trip import get_ocr
get_ocr()
mark("ocr warm %.2fs" % (time.time() - t))

for i in range(2):
    t = time.time()
    items = ocr_panel_items(SHOT_PATH, OCR_BOX, OCR_SCALE)
    mark("ocr panel #%d %.2fs blocks=%d" % (i + 1, time.time() - t, len(items or [])))

for i in range(3):
    t = time.time()
    ui.adb_tap((540, 1200), pause=0.0)
    mark("adb_tap pause=0 %.2fs" % (time.time() - t))

t = time.time()
ui.back(pause=0.0)
mark("back pause=0 %.2fs" % (time.time() - t))
