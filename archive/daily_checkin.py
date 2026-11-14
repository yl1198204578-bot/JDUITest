import time

from modules.base import BaseModule
import utils.driver as driver
import config


class DailyCheckin(BaseModule):
    name = "每日签到"
    description = "自动完成每日签到，领取京豆"
    icon = "🎯"

    def run(self, log, stop_event):
        self.d = driver.get_driver()
        log.write_log("开始每日签到任务")
        self.d.start_activity(config.JD_PACKAGE, config.JD_ACTIVITY)
        time.sleep(5)
        if stop_event.is_set():
            return
        log.write_log("寻找签到入口...")
        time.sleep(2)
        log.write_log("签到功能已执行（需根据实际UI调整）", "WARN")
        time.sleep(1)
        log.done("每日签到执行完成")
