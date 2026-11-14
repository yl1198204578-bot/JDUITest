# -*- coding: utf-8 -*-
"""跑 v2 模块（不经 Flask），日志带时间戳；--seconds 到点自动停。"""
import io
import sys
import threading
import time

sys.stdout.reconfigure(encoding="utf-8")

import modules.task14_coupons as M

LOG_PATH = "_coupon_v2.log"
T0 = time.time()
NL = chr(10)


class FileLog(object):
    def __init__(self, path):
        self.f = io.open(path, "w", encoding="utf-8", buffering=1)

    def _w(self, level, msg):
        self.f.write("[%6.1fs %s] %s%s" % (time.time() - T0, level, msg, NL))

    def write_log(self, msg, level="INFO"):
        self._w(level, msg)

    def done(self, msg=""):
        self._w("DONE", msg)

    def error(self, msg=""):
        self._w("ERROR", msg)


def main():
    seconds = 300
    if len(sys.argv) > 1:
        seconds = int(sys.argv[1])
    stop = threading.Event()
    log = FileLog(LOG_PATH)

    def _kill():
        time.sleep(seconds)
        log.write_log("到点，发停止信号", "WARN")
        stop.set()

    t = threading.Thread(target=_kill)
    t.daemon = True
    t.start()
    try:
        M.Task14Coupons().run(log, stop)
    except Exception as e:
        import traceback
        log.error("运行异常: %s" % e)
        log.f.write(traceback.format_exc())
    log.f.write("--- 用时 %.1f 分钟 ---%s" % ((time.time() - T0) / 60.0, NL))
    log.f.close()


if __name__ == "__main__":
    main()
