import json
import queue
import time


class LogStream:
    def __init__(self, run_id):
        self.run_id = run_id
        self._queue = queue.Queue()
        self._done = False

    def write_log(self, message, level="INFO"):
        self._queue.put({
            "type": "log",
            "time": time.time(),
            "level": level,
            "message": message,
        })

    def write_step(self, current, total, label):
        self._queue.put({
            "type": "step",
            "current": current,
            "total": total,
            "label": label,
        })

    def done(self, message="完成"):
        self._queue.put({"type": "done", "message": message})
        self._done = True

    def error(self, message="出错"):
        self._queue.put({"type": "error", "message": message})
        self._done = True

    def is_done(self):
        return self._done

    def iter_events(self, timeout=0.5):
        while not self._done or not self._queue.empty():
            try:
                yield self._queue.get(timeout=timeout)
            except queue.Empty:
                yield None

    def to_sse(self):
        for event in self.iter_events():
            if event is None:
                yield ":\n\n"
            else:
                yield "data: {}\n\n".format(json.dumps(event, ensure_ascii=False))
