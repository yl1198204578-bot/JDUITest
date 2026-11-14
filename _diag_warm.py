# -*- coding: utf-8 -*-
"""诊断：看看 _warm_ocr / threading 在 v2 里的分布。"""
import io
import os

P = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 "modules", "task14_coupons_v2.py")
s = io.open(P, encoding="utf-8").read()
for i, line in enumerate(s.split("\n"), 1):
    if "warm" in line or "threading" in line or "OCR_WARM" in line:
        print("%4d| %s" % (i, line))
print("count _warm_ocr =", s.count("_warm_ocr"))
i = s.find("def run(self, log, stop_event)")
print(s[i:i + 700])
