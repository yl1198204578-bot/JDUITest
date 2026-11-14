# -*- coding: utf-8 -*-
"""把 v2 提升为正式模块 modules/task14_coupons.py，并去掉重复发现。

平台 modules/__init__.py 会 import 目录下所有 .py，v1+v2 同时存在时
会出现两个同名「领券中心·天天领豆」卡片。
"""
import io
import os
import shutil
import uuid

ROOT = os.path.dirname(os.path.abspath(__file__))
V1 = os.path.join(ROOT, "modules", "task14_coupons.py")
V2 = os.path.join(ROOT, "modules", "task14_coupons_v2.py")
ARCH = os.path.join(ROOT, "_archive")


def swap(path, s):
    tmp = os.path.join(ROOT, "_tmp_%s.py" % uuid.uuid4().hex[:8])
    io.open(tmp, "w", encoding="utf-8", newline="\n").write(s)
    os.remove(path)
    os.rename(tmp, path)


if not os.path.isdir(ARCH):
    os.makedirs(ARCH)

# 1) 备份 v1（放 _archive/，不会被 modules 扫到）
shutil.copyfile(V1, os.path.join(ARCH, "task14_coupons_v1.py"))
print("backup v1")

# 2) v2 -> v1
s = io.open(V2, encoding="utf-8").read()
s = s.replace("task14_coupons_v2", "task14_coupons")
swap(V1, s)
os.remove(V2)
print("promoted, v2 removed")

# 3) 测试：v2 测试 -> 正式测试
t = io.open(os.path.join(ROOT, "_test_task14_coupons_v2.py"), encoding="utf-8").read()
t = t.replace("modules.task14_coupons_v2", "modules.task14_coupons")
t = t.replace("modules/task14_coupons_v2.py", "modules/task14_coupons.py")
swap(os.path.join(ROOT, "_test_task14_coupons.py"), t)
os.remove(os.path.join(ROOT, "_test_task14_coupons_v2.py"))
print("tests promoted")

# 4) 直跑脚本
r = io.open(os.path.join(ROOT, "_run_coupon_v2.py"), encoding="utf-8").read()
r = r.replace("modules.task14_coupons_v2", "modules.task14_coupons")
io.open(os.path.join(ROOT, "_run_coupon_direct.py"), "w",
        encoding="utf-8", newline="\n").write(r)
os.remove(os.path.join(ROOT, "_run_coupon_v2.py"))
print("runner promoted")

print("modules now:", [f for f in sorted(os.listdir(os.path.join(ROOT, "modules")))
                       if f.startswith("task14")])
