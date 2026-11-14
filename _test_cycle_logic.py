# -*- coding: utf-8 -*-
"""离线校验多轮刮卡循环的终止条件（不连手机、不消耗刮卡机会）。

用 FakeUI 替换 JDUI，只验证 modules/task1_seckill.py 的循环控制：
  A 有多张卡 -> 应逐个刮完并正常结束
  B 按钮永远在但余额不变 -> 必须靠 MAX_NO_CHANGE 退出，不能死点
  C 刷新后始终有解锁按钮且无进展 -> 必须靠 idle_rounds 退出
"""
import io
import sys
import threading
import unittest.mock as mock

sys.stdout.reconfigure(encoding="utf-8")

import modules.task1_seckill as t1

OUT = []
ALL = []


class FileLog(object):
    def _w(self, line):
        OUT.append(line)
        ALL.append(line)

    def write_log(self, m, level="INFO"):
        self._w("[%s] %s" % (level, m))

    def done(self, m="完成"):
        self._w("[DONE] " + m)

    def error(self, m="出错"):
        self._w("[ERROR] " + m)


class FakeUI(object):
    W, H = 1080, 2340

    def __init__(self, balance_seq, unlock_after_refresh, browse_per_round,
                 card_button_always=False):
        # balance_seq: 每次点击【立即刮卡】后返回的新余额；None 表示不变
        self.balance_seq = list(balance_seq)
        self.bal = "47.70"
        self.clicks = 0
        self.refreshes = 0
        self.unlock_after_refresh = unlock_after_refresh
        self.browse_per_round = browse_per_round
        self.card_button_always = card_button_always
        self.swipes = 0
        self.browse_rounds = 0

    # --- 导航（离线全部视为成功） ---
    def to_all_channels(self):
        return True

    def restart_to_home(self):
        # task1 入口已改成 restart_to_home + 金刚区直达（不再强制绕全部频道）
        return True

    def to_seckill_page(self):
        return True

    def to_beans_page(self):
        return True

    def ensure_beans_page(self):
        return True

    def open_task_dialog(self):
        return True

    def ensure_task_dialog(self):
        return True

    def browse_buttons(self):
        return []

    def nodes(self):
        return []

    def first_scratch_button(self):
        return {"bounds": (1, 1, 2, 2)}

    def center(self, n):
        return (0, 0)

    def tap(self, *a, **kw):
        return None

    def back(self, *a, **kw):
        return None

    def snapshot(self, *a, **kw):
        return None

    # --- 刮卡 ---
    def scratch_now_button(self):
        if self.card_button_always:
            return {"bounds": (247, 762, 833, 880)}
        return ({"bounds": (247, 762, 833, 880)}
                if self.clicks < len(self.balance_seq) else None)

    def bean_balance(self):
        return self.bal

    def wait_balance_change(self, before, timeout=8):
        self.clicks += 1
        if self.clicks <= len(self.balance_seq):
            nxt = self.balance_seq[self.clicks - 1]
            if nxt is not None:
                self.bal = nxt
                return nxt
        return None

    def swipe_task_cards(self, *a, **kw):
        self.swipes += 1

    def refresh_beans_page(self):
        self.refreshes += 1
        return True

    def unlock_button(self):
        if isinstance(self.unlock_after_refresh, list):
            return ({"bounds": (1, 1, 2, 2)}
                    if self.refreshes <= self.unlock_after_refresh[0] else None)
        return ({"bounds": (1, 1, 2, 2)}
                if self.refreshes <= self.unlock_after_refresh else None)


def run_case(name, fake):
    OUT[:] = []
    log = FileLog()
    stop = threading.Event()
    mod = t1.Task1Seckill()
    # 跳过真实浏览：让 _browse_round 直接返回 0，_click_first_scratch 直接成功
    with mock.patch.object(t1, "JDUI", return_value=fake), \
         mock.patch.object(t1.driver, "get_driver", return_value=object()), \
         mock.patch.object(t1.Task1Seckill, "_browse_round",
                           side_effect=lambda *a: fake.browse_per_round), \
         mock.patch.object(t1.Task1Seckill, "_click_first_scratch",
                           return_value=None):
        mod.run(log, stop)
    print("=== %s ===" % name, flush=True)
    ALL.append("=== %s ===" % name)
    for l in OUT:
        if any(k in l for k in ("刮卡", "刷新", "解锁", "轮", "DONE", "ERROR", "累计")):
            print("  " + l, flush=True)
    print("  >> clicks=%d refreshes=%d swipes=%d" %
          (fake.clicks, fake.refreshes, fake.swipes), flush=True)
    return OUT


# A：3 张卡，刮完刷新后没有解锁按钮 -> 应 3 次点击、1 次刷新、正常 DONE
a = run_case("A 多张卡正常结束",
             FakeUI(["47.71", "47.72", "47.73"], 0, 0))
assert any("DONE" in l for l in a), "A 未正常结束"
assert not any("ERROR" in l for l in a), "A 报错: %s" % a
assert "刮卡 3 次" in " ".join(a), "A 刮卡次数不对"

# B：按钮永远显示【立即刮卡】但余额不变 -> 必须刹车，不能无限点击
b = run_case("B 余额不变防死点",
             FakeUI([], 0, 0, card_button_always=True))
assert any("DONE" in l for l in b), "B 未结束（死循环）"
assert not any("ERROR" in l for l in b), "B 报错"

# C：刷新后一直有解锁按钮，但无任何进展 -> idle_rounds 必须刹车
c = run_case("C 一直有解锁按钮防死循环",
             FakeUI([], 99, 0))
assert any("DONE" in l for l in c), "C 未结束（死循环）"
assert any("连续两轮" in l for l in c), "C 不是靠 idle 刹车退出的"

print("\n=== 全部离线用例通过 ===", flush=True)
with io.open("_test_cycle_logic_result.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(ALL))
