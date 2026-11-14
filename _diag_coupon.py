# -*- coding: utf-8 -*-
"""诊断：把当前页面 dump 下来，看模块的 classify / 入口定位到底看到什么。"""
import io
import sys
import threading

sys.stdout.reconfigure(encoding="utf-8")

import utils.driver as driver
from utils.jd_ui import JDUI
import modules.task14_coupons as M


class L(object):
    def write_log(self, m, level="INFO"):
        print("[%s] %s" % (level, m))

    def done(self, m=""):
        print("[DONE]", m)


ui = JDUI(driver.get_driver(), L(), threading.Event())
print("W/H", ui.W, ui.H)
xml = ui.source(fresh=True)
io.open("_coupon_diag.xml", "w", encoding="utf-8").write(xml or u"")
nodes = ui.nodes(xml) if xml else []
print("nodes", len(nodes))
print("classify ->", M.classify(nodes))
print("rows ->", [(r["title"], r["reward"], r["text"], r["bounds"]) for r in M.parse_rows(nodes)])

WANT = (u"更多任务", u"领更多", u"天天领豆", u"领券中心", u"特价", u"京豆")
SEEN = set()
for n in nodes:
    t = M.norm(n.get("text"))
    d = M.norm(n.get("desc"))
    for w in WANT:
        if w and (w in t or w in d):
            k = (t, n.get("bounds"))
            if k in SEEN:
                continue
            SEEN.add(k)
            print("HIT %-6s text=%-16s desc=%-12s bounds=%s clk=%s cls=%s"
                  % (w, t[:16], d[:12], n.get("bounds"),
                     n.get("clickable"), n.get("class")))
            break

print("---- 布局快照（前 40 个有文字的节点，按 y 排序）----")
rows = []
for n in nodes:
    t = M.norm(n.get("text"))
    b = n.get("bounds")
    if t and M.valid(b):
        rows.append((b[1], b[0], t[:20], tuple(b), n.get("clickable")))
rows.sort()
for r in rows[:40]:
    print(r)
