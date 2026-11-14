# -*- coding: utf-8 -*-
"""把 v2 提升为正式模块（改名搬移，不用 os.remove：安全删除 shim 会拦）。"""
import io
import os
import shutil

ROOT = os.path.dirname(os.path.abspath(__file__))
MODS = os.path.join(ROOT, "modules")
V1 = os.path.join(MODS, "task14_coupons.py")
V2 = os.path.join(MODS, "task14_coupons_v2.py")
ARCH = os.path.join(ROOT, "_archive")


def move(src, dst):
    if os.path.exists(dst):
        os.rename(dst, dst + ".old")
    os.rename(src, dst)


if not os.path.isdir(ARCH):
    os.makedirs(ARCH)

if os.path.isfile(V2):
    shutil.copyfile(V1, os.path.join(ARCH, "task14_coupons_v1.txt"))
    s = io.open(V2, encoding="utf-8").read().replace("task14_coupons_v2",
                                                     "task14_coupons")
    tmp = os.path.join(ROOT, "_tmp_promote.py")
    io.open(tmp, "w", encoding="utf-8", newline="\n").write(s)
    os.rename(V1, os.path.join(ARCH, "task14_coupons_v1.bak.txt"))
    os.rename(tmp, V1)
    move(V2, os.path.join(ARCH, "task14_coupons_v2_done.txt"))
    print("promoted")

t2 = os.path.join(ROOT, "_test_task14_coupons_v2.py")
if os.path.isfile(t2):
    t = io.open(t2, encoding="utf-8").read()
    t = t.replace("modules.task14_coupons_v2", "modules.task14_coupons")
    t = t.replace("modules/task14_coupons_v2.py", "modules/task14_coupons.py")
    tmp = os.path.join(ROOT, "_tmp_promote_t.py")
    io.open(tmp, "w", encoding="utf-8", newline="\n").write(t)
    os.rename(os.path.join(ROOT, "_test_task14_coupons.py"),
              os.path.join(ARCH, "test_task14_v1.txt"))
    os.rename(tmp, os.path.join(ROOT, "_test_task14_coupons.py"))
    move(t2, os.path.join(ARCH, "test_task14_v2_done.txt"))
    print("tests promoted")

r2 = os.path.join(ROOT, "_run_coupon_v2.py")
if os.path.isfile(r2):
    r = io.open(r2, encoding="utf-8").read().replace("modules.task14_coupons_v2",
                                                     "modules.task14_coupons")
    io.open(os.path.join(ROOT, "_run_coupon_direct.py"), "w",
            encoding="utf-8", newline="\n").write(r)
    move(r2, os.path.join(ARCH, "run_coupon_v2_done.txt"))
    print("runner promoted")

print("modules:", [f for f in sorted(os.listdir(MODS)) if f.startswith("task14")])
