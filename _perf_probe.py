# -*- coding: utf-8 -*-
"""测真机各环节耗时：截图 / page_source / OCR 不同缩放。"""
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
ADB = "adb"


def t(fn, *a, **k):
    s = time.time()
    r = fn(*a, **k)
    return time.time() - s, r


def shot(path):
    if os.path.isfile(path):
        os.remove(path)
    with open(path, "wb") as f:
        subprocess.call([ADB, "exec-out", "screencap", "-p"], stdout=f)
    return path


def main():
    print("adb devices:")
    print(subprocess.check_output([ADB, "devices"]).decode("utf-8", "ignore"))

    dt, p = t(shot, os.path.join(ROOT, "_perf_shot.png"))
    print("screencap exec-out: %.2fs -> %s (%d bytes)" % (dt, p, os.path.getsize(p)))

    from PIL import Image
    dt, im = t(Image.open, p)
    print("PIL open: %.2fs %s" % (dt, im.size))

    # page_source 走 Appium
    try:
        import utils.driver as driver
        dt, d = t(driver.get_driver)
        print("get_driver: %.2fs" % dt)
        dt, xml = t(lambda: d.page_source)
        print("page_source: %.2fs (%d chars)" % (dt, len(xml or "")))
        open(os.path.join(ROOT, "_perf_dump.xml"), "w", encoding="utf-8").write(xml or "")
    except Exception as e:
        print("appium 读数失败: %s" % e)

    from modules.task5_joy_trip import get_ocr
    dt, ocr = t(get_ocr)
    print("get_ocr(加载模型): %.2fs" % dt)

    from modules.task14_coupons import ocr_panel_items, OCR_BOX
    for scale in (0.45, 0.35, 0.30):
        dt, items = t(ocr_panel_items, p, OCR_BOX, scale)
        print("OCR box=%s scale=%.2f: %.2fs, %d 块" % (OCR_BOX, scale, dt, len(items or [])))
        for it in (items or [])[:6]:
            print("    %s @(%d,%d)" % (it["text"][:24], it["x1"], it["y1"]))


if __name__ == "__main__":
    main()
