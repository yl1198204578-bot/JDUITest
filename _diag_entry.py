# -*- coding: utf-8 -*-
"""诊断：领券中心新布局下，入口卡片到底在不在无障碍树里。"""
import io
import re
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, ".")

import utils.driver as drv_mod
from utils.jd_ui import JDUI

t0 = time.time()
d = drv_mod.get_driver()
ui = JDUI(d, None, None)
xml = ui.source(fresh=True)
print("xml len", len(xml))
for k in (u"天天领豆", u"更多任务", u"领更多", u"去完成", u"惊喜奖励",
          u"领券中心", u"做任务得奖励", u"最高1000京豆"):
    print("  %s : %d" % (k, xml.count(k)))

nodes = ui.nodes(xml)
print("nodes", len(nodes))
for n in nodes:
    t = (n.get("text") or "") + "|" + (n.get("desc") or "")
    if any(k in t for k in (u"豆", u"惊喜", u"去完成", u"任务", u"领")):
        print("  ", n.get("bounds"), "click=", n.get("clickable"),
              n.get("class", "")[-18:], repr(t[:40]))

# OCR 顶部卡片区
from modules.task14_coupons import _default_shot, ocr_panel_items

p = _default_shot(ui)
print("shot", p)
for box, sc in (((0, 300, 1080, 1260), 0.5), ((0, 60, 1080, 620), 0.6)):
    t = time.time()
    items = ocr_panel_items(p, box, sc) or []
    print("OCR %s scale=%s %.1fs blocks=%d" % (box, sc, time.time() - t, len(items)))
    for it in items:
        print("   y=%4d x=%4d %r" % (it["y1"], it["x1"], it["text"]))
print("total %.1fs" % (time.time() - t0))
