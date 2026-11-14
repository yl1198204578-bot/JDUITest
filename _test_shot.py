# -*- coding: utf-8 -*-
"""测截图方式与像素校验的耗时：png / raw + PIL。"""
import os
import struct
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.abspath(__file__))
ADB = os.path.join(os.environ.get("ANDROID_HOME", "D:/Android"),
                   "platform-tools", "adb.exe")
from PIL import Image


def png_shot(path):
    if os.path.isfile(path):
        os.remove(path)
    with open(path, "wb") as f:
        subprocess.call([ADB, "exec-out", "screencap", "-p"], stdout=f)
    return path


def raw_shot(path):
    if os.path.isfile(path):
        os.remove(path)
    with open(path, "wb") as f:
        subprocess.call([ADB, "exec-out", "screencap"], stdout=f)
    return path


def patch(im, box=(0, 860, 700, 1010), size=(24, 8)):
    g = im.crop(box).convert("L").resize(size)
    return list(g.getdata())


def main():
    for name, fn in (("png", png_shot), ("raw", raw_shot)):
        for i in range(2):
            t = time.time()
            p = fn(os.path.join(ROOT, "_shot_%s.bin" % name))
            dt = time.time() - t
            print("%s 截图 %.2fs  %d bytes" % (name, dt, os.path.getsize(p)))

    t = time.time()
    im = Image.open(os.path.join(ROOT, "_shot_png.bin"))
    im.load()
    print("PNG 解码 %.2fs %s" % (time.time() - t, im.size))
    t = time.time()
    patch(im)
    print("PNG 取补丁 %.2fs" % (time.time() - t))

    # raw: 头 12~16 字节后是 RGBA
    raw = open(os.path.join(ROOT, "_shot_raw.bin"), "rb").read()
    w, h = struct.unpack("<II", raw[0:8])
    print("raw 头 %dx%d 总长 %d" % (w, h, len(raw)))
    t = time.time()
    im2 = Image.frombytes("RGBA", (w, h), raw[12:12 + w * h * 4])
    print("raw 转图 %.2fs" % (time.time() - t))
    t = time.time()
    p2 = patch(im2)
    print("raw 取补丁 %.2fs" % (time.time() - t))
    p1 = patch(im)
    diff = sum(abs(a - b) for a, b in zip(p1, p2)) / float(len(p1))
    print("两种截图补丁平均差 %.1f" % diff)


if __name__ == "__main__":
    main()
