import threading
import uuid

from utils.log_stream import LogStream

_runners = {}


def start_module(module):
    run_id = str(uuid.uuid4())[:8]
    log_stream = LogStream(run_id)
    stop_event = threading.Event()

    def target():
        try:
            module.run(log_stream, stop_event)
            if not log_stream.is_done():
                log_stream.done()
        except Exception as e:
            log_stream.error("运行异常: {}".format(e))
        finally:
            module.status = "idle"

    t = threading.Thread(target=target, daemon=True)
    _runners[run_id] = {
        "thread": t,
        "log_stream": log_stream,
        "module": module,
        "stop_event": stop_event,
    }
    module.status = "running"
    t.start()
    return run_id


def stop_module(module_name):
    for run_id, info in _runners.items():
        if info["module"].name == module_name:
            info["stop_event"].set()
            return True
    return False


def get_log_stream(run_id):
    info = _runners.get(run_id)
    if info:
        return info["log_stream"]
    return None
