# -*- coding: utf-8 -*-
"""直接跑 家电家居 模块（不经 Flask），把日志打到 stdout 方便回看。"""
import sys
import threading

sys.path.insert(0, r"D:\AI_work\JDUItest")

from modules.task6_home_appliance import Task6HomeAppliance


class Log(object):
    def write_log(self, msg, level="INFO"):
        print("[%s] %s" % (level, msg))
        sys.stdout.flush()

    def done(self, msg=""):
        print("[DONE] %s" % msg)
        sys.stdout.flush()

    def error(self, msg):
        print("[ERROR] %s" % msg)
        sys.stdout.flush()


m = Task6HomeAppliance()
try:
    m.run(Log(), threading.Event())
except Exception as e:
    print("[FATAL] %s: %s" % (type(e).__name__, e))
    import traceback
    traceback.print_exc()
    sys.exit(1)
