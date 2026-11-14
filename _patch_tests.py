# -*- coding: utf-8 -*-
"""把旧回归脚本改造成 v2（新 OCR 主通道 + 进度驱动）。"""
import io
import os

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "_view__test_task14_coupons.py.txt")
DST = os.path.join(ROOT, "_test_task14_coupons_v2.py")

s = io.open(SRC, encoding="utf-8").read()


def cut(s, start, end, new):
    i = s.index(start)
    j = s.index(end, i) + len(end)
    return s[:i] + new + s[j:]


# ---------- 1. import 常量 ----------
old_imp = """    OCR_BOX, OCR_SCALE, MAX_STALE,
    PROGRESS_RE, REWARD_RE, PRICE_RE,
    MAX_TASKS, MAX_CYCLES, MAX_STEPS, MAX_SCROLLS, MAX_PER_TASK,
    MAX_RETRY, MAX_READ_FAILS, MAX_TO_TOP, MAX_ENTER_STEPS,
    MAX_OPEN_STEPS, MAX_OCR, OCR_GRACE, MAX_PER_TASK_PROGRESS,
    progress_total, task_limit,
)"""
new_imp = """    OCR_BOX, OCR_SCALE, OCR_TITLE_BOX, OCR_TITLE_SCALE,
    DWELL_CAP, DWELL_BONUS_MAX, DWELL_BONUS_STEP,
    PROGRESS_RE, REWARD_RE, PRICE_RE,
    MAX_TASKS, MAX_SCROLLS, MAX_PER_TASK, MAX_PASSES, MAX_PER_SCREEN,
    MAX_RETRY, MAX_TO_TOP, MAX_ENTER_STEPS, MAX_PROGRESS_EXTRA,
    MAX_OPEN_STEPS, MAX_OCR, MAX_PER_TASK_PROGRESS,
    progress_total, progress_current, task_limit,
)"""
assert old_imp in s
s = s.replace(old_imp, new_imp)

# ---------- 2. A20b / A20c / A21 ----------
old_a = """check("A20b 面板区裁剪 + 0.45 降采样（提速主力，23s -> 10s）",
      OCR_BOX == (0, 860, 1080, 2180) and OCR_SCALE == 0.45)
check("A20d 裁剪区必须包含弹窗标题（裁太高会认不出【做任务得奖励】）",
      OCR_BOX[1] <= 900)
check("A20c 面板结果复用上限存在", MAX_STALE == 6)
check("A21 五重上限保护齐全",
      (MAX_TASKS, MAX_CYCLES, MAX_STEPS, MAX_SCROLLS, MAX_PER_TASK,
       MAX_RETRY, MAX_READ_FAILS, MAX_TO_TOP, MAX_ENTER_STEPS,
       MAX_OPEN_STEPS, MAX_OCR) ==
      (40, 8, 180, 12, 3, 2, 4, 8, 14, 12, 40))"""
new_a = """check("A20b 面板区裁剪 + 0.45 降采样（提速主力，模型预热后 ≈0.6s）",
      OCR_BOX == (0, 860, 1080, 2180) and OCR_SCALE == 0.45)
check("A20d 裁剪区必须包含弹窗标题（裁太高会认不出【做任务得奖励】）",
      OCR_BOX[1] <= 900)
check("A20c 只判面板在场时用更小的标题条（≈1s，替代 dump）",
      OCR_TITLE_BOX[1] <= 900 and OCR_TITLE_BOX[2] <= 700 and
      OCR_TITLE_BOX[3] - OCR_TITLE_BOX[1] <= 200 and
      OCR_TITLE_SCALE >= OCR_SCALE,
      "%s x%.2f" % (OCR_TITLE_BOX, OCR_TITLE_SCALE))
check("A21 多重上限保护齐全",
      (MAX_TASKS, MAX_PASSES, MAX_PER_SCREEN, MAX_SCROLLS, MAX_PER_TASK,
       MAX_RETRY, MAX_TO_TOP, MAX_ENTER_STEPS,
       MAX_OPEN_STEPS, MAX_OCR) ==
      (40, 8, 30, 12, 3, 2, 5, 14, 12, 400),
      "%s" % ((MAX_TASKS, MAX_PASSES, MAX_PER_SCREEN, MAX_SCROLLS,
               MAX_PER_TASK, MAX_RETRY, MAX_TO_TOP, MAX_ENTER_STEPS,
               MAX_OPEN_STEPS, MAX_OCR),))
check("A21b 停留自适应上限（进度不涨才加时）",
      (DWELL_CAP, DWELL_BONUS_MAX, DWELL_BONUS_STEP) == (15, 6, 3))
check("A21c 进度漏涨容忍次数", MAX_PROGRESS_EXTRA == 2)"""
assert old_a in s
s = s.replace(old_a, new_a)

# ---------- 3. J5 ~ J11d 区块 ----------
old_j = s[s.index('check("J5 _need_ocr 未点入口时关闭"'):s.index("MOD.SHOT_HOOK, MOD.OCR_HOOK = _old_shot, _old_ocr") + len("MOD.SHOT_HOOK, MOD.OCR_HOOK = _old_shot, _old_ocr")]
new_j = '''# J5~J11 注入 OCR 替身，避免回归去加载 PaddleOCR / 真机截图
_old_shot, _old_ocr = MOD.SHOT_HOOK, MOD.OCR_HOOK
MOD.SHOT_HOOK = lambda ui: "_fixture_coupon_panel.png"
MOD.OCR_HOOK = lambda path: sim0.ocr_items()
sim0.state = "center"
m.expect_panel = False
m.panel_believed = False
m.ocr_calls = 0
p0 = m._probe()
check("J5 未点入口的 center 帧不误判成弹窗，也不跑 OCR",
      p0["state"] == "center" and p0["rows"] == [] and
      p0["src"] == "xml" and m.ocr_calls == 0,
      "%s / %d" % (p0["src"], m.ocr_calls))
m.expect_panel = True
m.panel_believed = True
sim0.state = "blind"
p1 = m._probe()
check("J6 面板不进无障碍树（盲帧）时靠截图 OCR 判成 panel",
      p1["state"] == "panel" and p1["src"] == "ocr", p1["src"])
check("J7 盲帧 OCR 拿到 3 个可做任务", len(p1["rows"]) == 3,
      "%d" % len(p1["rows"]))
check("J8 面板在场时不 dump XML（nodes 为空，省 2~9s）", p1["nodes"] == [])
p2 = m._probe()
check("J9 下一帧仍然只花 1 次 OCR（不靠会过期的缓存）",
      m.ocr_calls == 2 and p2["src"] == "ocr",
      "%d %s" % (m.ocr_calls, p2["src"]))
check("J10 每帧都重新截图 OCR，行数据永远是最新的",
      [r["key"] for r in p2["rows"]] == [r["key"] for r in p1["rows"]])
check("J11 OCR 预算被扣减", m.ocr_budget == MAX_OCR - 2,
      "%d" % m.ocr_budget)
sim0.state = "center"
p3 = m._probe()
check("J11b 面板关掉后立刻判 center（不会把面板当还在）",
      p3["state"] == "center" and p3["rows"] == [] and
      m.panel_believed is False, p3["state"])
sim0.state = "panel"
m.panel_believed = True
p4 = m._probe()
check("J11c 面板重新在场又能立刻认回来", p4["state"] == "panel",
      p4["state"])
check("J11d 面板不在时 _probe 不浪费 OCR（center 才补一次判定）",
      m.ocr_calls == 4, "%d" % m.ocr_calls)
MOD.SHOT_HOOK, MOD.OCR_HOOK = _old_shot, _old_ocr'''
s = s.replace(old_j, new_j)

# ---------- 4. K5 / K6 ----------
s = s.replace(
    '''check("K5 每个任务恰好一次 back", sim.backs == sim.browses,
      "%d vs %d" % (sim.backs, sim.browses))
check("K6 只打开了 1 次面板（没被反复重建）", sim.panel_opens == 1,
      "%d" % sim.panel_opens)''',
    '''check("K5 每个任务恰好一次 back（收尾刷新最多多 1 次）",
      0 <= sim.backs - sim.browses <= 1,
      "%d vs %d" % (sim.backs, sim.browses))
check("K6 面板只在开局开 1 次 + 收尾刷新 1 次（不是每个任务都重建）",
      sim.panel_opens <= 2, "%d" % sim.panel_opens)''')

# ---------- 5. L4 ----------
s = s.replace(
    '''check("L4 点击后只 back 一次再回弹窗",
      sim.events.count("tap_task") == sim.events.count("browse") ==
      sim.backs)''',
    '''check("L4 点击后只 back 一次再回弹窗（收尾刷新除外）",
      sim.events.count("tap_task") == sim.events.count("browse") and
      0 <= sim.backs - sim.browses <= 1)''')

# ---------- 6. 头部说明补 v2 ----------
s = s.replace("""  L. 需求合规：只做京豆任务、12~15s 随机、一次 back、循环到无可做任务""",
              """  L. 需求合规：只做京豆任务、9~10s 随机、一次 back、循环到无可做任务
  M. v2 提速：截图 OCR 主通道、面板不在树也每帧可判、进度驱动做到 M/M""")

io.open(DST, "w", encoding="utf-8").write(s)
print("written", DST, len(s))
