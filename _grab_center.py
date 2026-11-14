# -*- coding: utf-8 -*-
"""抓一份「领券中心」底页的新布局夹具（入口卡片文案已改成【立即领奖】）。"""
import io
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, ".")

import utils.driver as drv_mod
from utils.jd_ui import JDUI
from modules.task14_coupons import adb_path, _default_shot

ADB = adb_path()
print("adb", ADB)
subprocess.call([ADB, "shell", "am", "start", "-n",
                 "com.jingdong.app.mall/.MainFrameActivity"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(8)

d = drv_mod.get_driver()
ui = JDUI(d, None, None)
xml = ui.source(fresh=True)
print("home xml len", len(xml))
print("有【特价】", u"特价" in xml)

# 点顶部【特价】→ 二级【领券中心】
ui.adb_tap((100, 126), pause=1.5, settle=0)
time.sleep(1.5)
ui.invalidate()
xml = ui.source(fresh=True)
print("tejia xml len", len(xml))
io.open("_fixture_coupon_tejia2.xml", "w", encoding="utf-8").write(xml)

ui.adb_tap((520, 468), pause=1.5, settle=0)
time.sleep(2.0)
ui.invalidate()
xml = ui.source(fresh=True)
print("center xml len", len(xml))
io.open("_fixture_coupon_center2.xml", "w", encoding="utf-8").write(xml)
p = _default_shot(ui)
if p:
    import shutil
    shutil.copyfile(p, "_fixture_coupon_center2.png")
print("shot", p)
