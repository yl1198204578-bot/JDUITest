# -*- coding: utf-8 -*-
"""离线回归：修掉「两次未到账就整轮退出」后，循环是否真的滑完所有卡。

不连手机、不消耗刮卡机会，直接调 _consume_cards：
  E 未到账 -> 左滑 -> 下一张卡刮成功（复现 _web_verify3 第 1 轮漏刮的缺陷）
  F 按钮永远在且余额永远不变 -> 必须有界退出，不能死点
  G 正常多张卡 -> 逐个刮完，靠「连续左滑没按钮」收敛
"""
import sys
import threading

sys.stdout.reconfigure(encoding="utf-8")

import modules.task1_seckill as t1


class Log(object):
    def __init__(self):
        self.lines = []

    def write_log(self, m, level="INFO"):
        self.lines.append("[%s] %s" % (level, m))


class FakeUI(object):
    """button_seq 按「轮播位置」给出按钮是否可见；change_seq 按「点击序号」给出到账结果。

    左滑或刮卡成功都会让页面切到下一张卡（实测：刮成功主按钮仍是【立即刮卡】，
    但已经是下一张卡）。点击本身不推进轮播。
    """
    def __init__(self, button_seq, change_seq):
        self.button_seq = list(button_seq)
        self.change_seq = list(change_seq)
        self.bal = "53.09"
        self.pos = 0
        self.clicks = 0
        self.swipes = 0

    def _advance(self):
        self.pos = min(self.pos + 1, len(self.button_seq) - 1)

    def ensure_beans_page(self):
        return True

    def scratch_now_button(self):
        show = self.button_seq[self.pos]
        return {"bounds": (247, 762, 833, 880)} if show else None

    def bean_balance(self):
        return self.bal

    def center(self, n):
        return (540, 820)

    def tap(self, *a, **kw):
        return None

    def wait_balance_change(self, before, timeout=8):
        self.clicks += 1
        if self.clicks <= len(self.change_seq):
            nxt = self.change_seq[self.clicks - 1]
            if nxt is not None:
                self.bal = nxt
                self._advance()        # 刮成功后页面自动切到下一张卡
                return nxt
        return None

    def swipe_task_cards(self, *a, **kw):
        self.swipes += 1
        self._advance()


def case(name, buttons, changes, min_count, max_clicks):
    ui = FakeUI(buttons, changes)
    log = Log()
    stop = threading.Event()
    n = t1.Task1Seckill()._consume_cards(ui, log, stop)
    tail = [l for l in log.lines if any(k in l for k in
            ("未变化", "未到账", "结束本轮", "本轮共刮", "没有【立即刮卡】", "刮卡完成"))]
    print("=== %s ===" % name, flush=True)
    for l in tail[-8:]:
        print("  " + l, flush=True)
    print("  >> count=%d clicks=%d swipes=%d" % (n, ui.clicks, ui.swipes), flush=True)
    assert n >= min_count, "%s: 期望至少刮 %d 张，实际 %d" % (name, min_count, n)
    assert ui.clicks <= max_clicks, "%s: 点击次数 %d 超过上限 %d" % (name, ui.clicks, max_clicks)
    assert ui.swipes < t1.MAX_CARD_CLICKS, "%s: 疑似死循环，左滑 %d 次" % (name, ui.swipes)
    assert any("本轮共刮" in l for l in log.lines), "%s: 未正常收尾" % name
    return n


# E：前两次点击未到账，第三次（左滑后的新卡）到账。旧逻辑第 2 次就 break -> 0 张。
case("E 未到账后左滑还能刮到新卡",
     [True, True, True, False, False, False],
     [None, None, "53.10"], min_count=1, max_clicks=t1.MAX_NO_CHANGE)

# F：按钮永远在、余额永远不变 -> 4 次点击后改为只左滑，再有界退出（不原地死点）。
case("F 全是失效卡必须有界退出",
     [True] * 40, [None] * 40, min_count=0, max_clicks=t1.MAX_NO_CHANGE)

# G：3 张正常卡，刮完后连续左滑看不到按钮 -> 靠 empty_swipes 收敛。
case("G 正常多卡逐张刮完",
     [True, True, True, False, False, False],
     ["53.10", "53.11", "53.12"], min_count=3, max_clicks=t1.MAX_CARD_CLICKS)

print("=== 全部离线用例通过 ===", flush=True)
