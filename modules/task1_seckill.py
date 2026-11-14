# -*- coding: utf-8 -*-
"""任务1【秒杀】：公共导航 -> 优惠权益/秒杀 -> 秒杀x天天刮京豆 -> 多轮任务 + 刮卡。

流程（与需求一致）：
  公共模块：京东首页 -> 金刚区滑到第二页 -> 【全部频道】列表
  任务1  ：【优惠权益】tab -> 【秒杀】 -> 【赚更多京豆】 -> 【全部任务】弹窗
            逐个点击【去浏览】，每次停留 16 秒后返回，直到列表里没有【去浏览】；
            点弹窗第一条【去刮卡】进入刮卡页，把【立即刮卡】全部刮完
            （每刮一张都左滑【任务卡】检查是否还有可刮的卡）；
            刷新【天天领豆】，若还有【做任务解锁刮卡】就再来一轮做任务+刮卡，
            直到刷新后不再出现【做任务解锁刮卡】。

实现要点见 utils/jd_ui.py 顶部说明：H5 页用标定坐标，任务弹窗用原生节点精确定位。
"""
import time

from modules.base import BaseModule
import utils.driver as driver
from utils.jd_ui import JDUI

BROWSE_SECONDS = 16       # 每个浏览任务停留秒数（任务要求 15 秒，留 1 秒余量）
MAX_ROUNDS = 40           # 单轮弹窗内浏览循环上限
MAX_SCAN_SWIPES = 2       # 找未处理任务最多滚动 2 次；无任务时快速退出
MAX_CARD_ROUNDS = 12      # 「浏览 -> 刮卡」外层轮次上限
MAX_CARD_CLICKS = 30      # 单轮点击【立即刮卡】上限
MAX_EMPTY_SWIPES = 2      # 连续几次左滑都找不到【立即刮卡】就判定本轮刮完
MAX_NO_CHANGE = 4         # 连续几次点击后余额不变，才停止点击、改为只左滑找新卡
MAX_SEARCH_SWIPES = 3     # 只左滑模式下连续几次仍只看到失效按钮就收尾


class Task1Seckill(BaseModule):
    name = "秒杀任务"
    description = "公共导航后循环完成【去浏览】并刮完所有【立即刮卡】，直到没有【做任务解锁刮卡】"
    icon = "⚡"

    def run(self, log, stop_event):
        ui = None
        try:
            ui = JDUI(driver.get_driver(), log, stop_event)
            log.write_log("设备分辨率 %dx%d（坐标按 1080x2340 等比缩放）" % (ui.W, ui.H))

            # ===== 公共模块 =====
            # 【秒杀】在首页金刚区就是原生可点节点，直接走金刚区一次点击；
            # 不再强制先绕【全部频道】（那条链路只作 to_seckill_page 的兜底）。
            if not ui.restart_to_home():
                raise RuntimeError("冷启动后未识别到京东首页，无法定位金刚区【秒杀】")
            ui._restarted = True
            if stop_event.is_set():
                return

            # ===== 任务1 入口 =====
            ui.to_seckill_page()
            ui.to_beans_page()

            total_browse = 0
            total_scratch = 0

            # ===== 第 1 轮：浏览全部【去浏览】-> 第一条【去刮卡】=====
            total_browse += self._browse_round(ui, log, stop_event)
            self._click_first_scratch(ui, log)

            # ===== 循环：刮完所有卡 -> 刷新 -> 还有解锁按钮就再做一轮 =====
            idle_rounds = 0
            for cycle in range(1, MAX_CARD_ROUNDS + 1):
                if stop_event.is_set():
                    break
                log.write_log("===== 刮卡第 %d 轮 =====" % cycle)

                scratched = self._consume_cards(ui, log, stop_event)
                total_scratch += scratched

                if stop_event.is_set():
                    break
                if not ui.refresh_beans_page():
                    log.write_log("刷新后未回到【天天领豆】页，停止循环", "WARN")
                    break

                if ui.unlock_button() is None:
                    log.write_log("刷新后没有【做任务解锁刮卡】，全部刮卡完成")
                    break

                log.write_log("仍有【做任务解锁刮卡】，继续做任务解锁新卡")
                browsed = self._browse_round(ui, log, stop_event)
                total_browse += browsed
                if stop_event.is_set():
                    break
                self._click_first_scratch(ui, log)

                if scratched == 0 and browsed == 0:
                    idle_rounds += 1
                    if idle_rounds >= 2:
                        log.write_log("连续两轮既无可刮卡也无浏览任务，结束", "WARN")
                        break
                else:
                    idle_rounds = 0
            else:
                log.write_log("达到最大刮卡轮数 %d，主动停止" % MAX_CARD_ROUNDS, "WARN")

            log.write_log("累计完成 %d 个【去浏览】任务、%d 次刮卡" %
                          (total_browse, total_scratch))
            if not stop_event.is_set():
                log.done("秒杀任务完成：浏览 %d 个任务、刮卡 %d 次" %
                         (total_browse, total_scratch))

        except Exception as e:
            if ui is not None:
                ui.snapshot("task1_error")
            log.error("运行异常：%s: %s" % (type(e).__name__, e))

    # ---------- 单轮：弹窗里浏览完所有【去浏览】 ----------
    def _browse_round(self, ui, log, stop_event):
        if not ui.open_task_dialog():
            raise RuntimeError("点击【全部任务】后未出现任务列表弹窗")
        log.write_log("任务列表已打开")

        processed = set()
        done = 0
        for _ in range(MAX_ROUNDS):
            if stop_event.is_set():
                break
            if not ui.ensure_task_dialog():
                log.write_log("无法回到任务列表弹窗，尝试重进天天领豆页恢复", "WARN")
                if not (ui.ensure_beans_page() and ui.open_task_dialog()):
                    log.write_log("仍无法恢复任务弹窗，本轮浏览提前结束", "WARN")
                    break

            # 弹窗里没有【去浏览】就直接跳出，不空转（用户明确要求）
            if not ui.browse_buttons():
                log.write_log("任务弹窗没有【去浏览】，直接点第一个【去刮卡】")
                break

            picked = None
            for scan in range(MAX_SCAN_SWIPES):
                if stop_event.is_set():
                    break
                all_nodes = ui.nodes()
                for btn in ui.browse_buttons():
                    key = ui.task_key(btn, all_nodes)
                    if key not in processed:
                        picked = (btn, key)
                        break
                if picked:
                    break
                if scan < MAX_SCAN_SWIPES - 1:
                    ui.swipe("task_list", pause=1.2)

            if stop_event.is_set():
                break
            if not picked:
                log.write_log("任务列表已无可处理的【去浏览】，直接执行刮卡收尾")
                break

            btn, key = picked
            processed.add(key)
            log.write_log("点击【去浏览】：%s %s" % (key, btn["bounds"]))
            ui.tap(ui.center(btn), pause=2)

            # 必须确认真的离开了弹窗。adb 点击偶发超时/被吞时，若仍按
            # 「已进入浏览页」等 16 秒再 back，会把任务弹窗直接关掉。
            if ui.page_state() == "dialog":
                log.write_log("点击未生效（仍在弹窗），重试一次", "WARN")
                ui.tap(ui.center(btn), pause=2)
            if ui.page_state() == "dialog":
                log.write_log("【去浏览】仍未生效，跳过该任务以免破坏弹窗状态", "WARN")
                continue
            done += 1
            log.write_log("第 %d 个【去浏览】已进入浏览页：%s" % (done, key))

            if ui.page_state() == "verify":
                if not ui.handle_verify():
                    raise RuntimeError("京东安全验证未能自动通过，请手动完成后重试")

            log.write_log("停留 %d 秒…" % BROWSE_SECONDS)
            for sec in range(BROWSE_SECONDS):
                if stop_event.is_set():
                    break
                time.sleep(1)
                if (sec + 1) % 4 == 0:
                    log.write_log("   %d/%d 秒" % (sec + 1, BROWSE_SECONDS))
            if stop_event.is_set():
                break

            log.write_log("返回任务列表")
            ui.back(2)
        else:
            log.write_log("达到单轮最大浏览数 %d，主动停止" % MAX_ROUNDS, "WARN")
        return done

    # ---------- 点弹窗第一条【去刮卡】 ----------
    def _click_first_scratch(self, ui, log):
        log.write_log("点击弹窗第一条【去刮卡】")
        if not ui.ensure_task_dialog():
            log.write_log("无法重新打开任务列表弹窗，尝试重进天天领豆页", "WARN")
            if not (ui.ensure_beans_page() and ui.open_task_dialog()):
                log.write_log("弹窗不可用，本轮跳过【去刮卡】", "WARN")
                ui.ensure_beans_page()
                return
        first = ui.first_scratch_button()
        if first is None:
            ui.snapshot("no_scratch_button")
            log.write_log("任务列表里没有【去刮卡】按钮，本轮跳过", "WARN")
            ui.ensure_beans_page()
            return
        log.write_log("点击【去刮卡】%s" % (first["bounds"],))
        ui.tap(ui.center(first), pause=2.5)
        ui.ensure_beans_page()

    # ---------- 把当前所有【立即刮卡】刮完 ----------
    def _consume_cards(self, ui, log, stop_event):
        """刮完当前所有可刮卡。

        实测刮完一张后主按钮可能仍是【立即刮卡】——页面自动切到下一张待刮卡，
        并不会变回【做任务解锁刮卡】。所以以「可抵金额变化」判到账；余额不变
        时左滑【任务卡】继续找下一张卡，直到连续左滑都看不到【立即刮卡】才收尾。

        一次点击未到账只说明「这一张卡失效」，不能据此结束本轮：实测存在
        「未到账 -> 左滑 -> 下一张卡刮成功」的序列。只有连续多次点击都未到账，
        才停止重复点击同一个按钮，改为只左滑找新卡，避免原地死点。
        """
        if not ui.ensure_beans_page():
            raise RuntimeError("不在【天天领豆】页，无法刮卡")
        count = 0
        empty_swipes = 0
        no_change = 0
        search_swipes = 0
        skip_click = False          # 连续未到账后不再点，只左滑找新卡
        for _ in range(MAX_CARD_CLICKS):
            if stop_event.is_set():
                break
            btn = ui.scratch_now_button()
            if btn is None:
                empty_swipes += 1
                if empty_swipes >= MAX_EMPTY_SWIPES:
                    break
                search_swipes = 0
                log.write_log("没有【立即刮卡】，左滑【任务卡】查找（%d/%d）" %
                              (empty_swipes, MAX_EMPTY_SWIPES))
                ui.swipe_task_cards()
                continue

            empty_swipes = 0
            if skip_click:
                search_swipes += 1
                if search_swipes >= MAX_SEARCH_SWIPES:
                    log.write_log("连续 %d 次左滑仍只有失效的【立即刮卡】，结束本轮" %
                                  search_swipes, "WARN")
                    break
                log.write_log("已连续 %d 次刮卡未到账，跳过该按钮继续左滑找新卡（%d/%d）" %
                              (no_change, search_swipes, MAX_SEARCH_SWIPES), "WARN")
                ui.swipe_task_cards()
                continue

            before = ui.bean_balance()
            log.write_log("点击【立即刮卡】%s（刮卡前可抵 %s 元）" %
                          (btn["bounds"], before))
            ui.tap(ui.center(btn), pause=1.5)
            # 重试时缩短到账轮询，避免在失效卡上反复干等 8 秒
            after = ui.wait_balance_change(before, timeout=8 if no_change == 0 else 5)
            if after is None:
                no_change += 1
                log.write_log("可抵金额未变化（%d/%d），左滑【任务卡】换一张" %
                              (no_change, MAX_NO_CHANGE), "WARN")
                ui.swipe_task_cards()
                if no_change >= MAX_NO_CHANGE:
                    log.write_log("连续 %d 次刮卡未到账，停止重复点击，改为只左滑找新卡" %
                                  no_change, "WARN")
                    skip_click = True
                continue

            no_change = 0
            search_swipes = 0
            skip_click = False
            count += 1
            log.write_log("刮卡完成 #%d（可抵 %s 元 -> %s 元）" %
                          (count, before, after))
        log.write_log("本轮共刮 %d 张卡" % count)
        return count

