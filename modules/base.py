class BaseModule:
    name = "未命名"
    description = ""
    icon = "📦"
    status = "idle"

    def run(self, log, stop_event):
        raise NotImplementedError
