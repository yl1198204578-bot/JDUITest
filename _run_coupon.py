# -*- coding: utf-8 -*-
"""触发平台上的【领券中心·天天领豆】模块并把 SSE 日志落盘，便于命令行盯进度。"""
import io
import json
import sys
import threading
import time
import urllib.parse
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")

BASE = "http://127.0.0.1:5000"
NAME = u"领券中心·天天领豆"
LOG = "_coupon_run.log"


def post(path):
    req = urllib.request.Request(BASE + path, data=b"", method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    run_id = post("/api/run/" + urllib.parse.quote(NAME))["run_id"]
    print("run_id=%s" % run_id)
    buf = io.open(LOG, "w", encoding="utf-8", buffering=1)
    url = BASE + "/api/logs/" + run_id
    try:
        with urllib.request.urlopen(url, timeout=1800) as r:
            for raw in r:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                ev = json.loads(line[5:].strip())
                if ev.get("type") == "log":
                    buf.write("[%s] %s\n" % (ev.get("level"), ev.get("message")))
                elif ev.get("type") == "done":
                    buf.write("[DONE] %s\n" % ev.get("message"))
                    print("DONE:", ev.get("message"))
                    break
                elif ev.get("type") == "error":
                    buf.write("[ERROR] %s\n" % ev.get("message"))
                    print("ERROR:", ev.get("message"))
                    break
    finally:
        buf.close()


if __name__ == "__main__":
    main()
