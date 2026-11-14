# -*- coding: utf-8 -*-
"""让 SimUI 更贴近真机：任务行做满后不消失，而是按钮变【已完成】。

真机（21:28 截图）里即使做到 (4/5) 行也一直在原位，做满才变已完成；
旧替身是「做完就把行删掉」，行会整体上移，已经不是真机行为。
"""
import io
import os
import uuid

P = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 "_test_task14_coupons_v2.py")
s = io.open(P, encoding="utf-8").read()

# 1) 构造参数加 task_total
old = ("    def __init__(self, bases=None, float_on_enter=False, blind=False,\n"
       "                 refill=False, verify_on_tap=False, lost_on_back=False,\n"
       "                 no_tasks=False, stop=None, stop_after=0):\n")
new = ("    def __init__(self, bases=None, float_on_enter=False, blind=False,\n"
       "                 refill=False, verify_on_tap=False, lost_on_back=False,\n"
       "                 no_tasks=False, stop=None, stop_after=0, task_total=1):\n")
assert old in s
s = s.replace(old, new)

old = "        self.progress = {}\n"
new = "        self.progress = {}\n        self.task_total = task_total\n"
assert old in s
s = s.replace(old, new, 1)

# 2) 行渲染：进度用 task_total，做满后按钮变已完成
old = ('            title = t + u" (%d/5)" % self.progress.get(t, 0)\n'
       '            reward = (u"浏览完成得2京豆" if t in self.tasks\n'
       '                      else u"浏览6S获得抽奖机会")\n'
       '            out += [nd(title, 217, y - 24, 781, y + 20),\n'
       '                    nd(reward, 217, y + 44, 481, y + 83),\n'
       '                    nd(u"去完成", 855, y, 970, y + 61),\n')
new = ('            done = self.progress.get(t, 0)\n'
       '            title = t + u" (%d/%d)" % (done, self.task_total)\n'
       '            reward = (u"浏览完成得2京豆" if t in self.tasks\n'
       '                      else u"浏览6S获得抽奖机会")\n'
       '            full = t in self.tasks and done >= self.task_total\n'
       '            out += [nd(title, 217, y - 24, 781, y + 20),\n'
       '                    nd(reward, 217, y + 44, 481, y + 83),\n'
       '                    nd(u"已完成" if full else u"去完成",\n'
       '                       855, y, 970, y + 61),\n')
assert old in s
s = s.replace(old, new)

# 3) 做满不删行（真机行为：行留在原位，按钮变已完成）
old = ('        self.progress[t] = self.progress.get(t, 0) + 1\n'
       '        if not self.refill and t in self.tasks:\n'
       '            self.tasks.remove(t)\n')
new = ('        self.progress[t] = self.progress.get(t, 0) + 1\n'
       '        # 真机不做删除：行留在原位，做满后按钮变【已完成】\n')
assert old in s
s = s.replace(old, new)

# 4) refill 场景改成 (0/5) 的多步任务
old = 'sim_r = SimUI(refill=True)\n'
new = 'sim_r = SimUI(refill=True, task_total=5)\n'
assert old in s
s = s.replace(old, new)

# 5) K17 说明改成按 M 做满
old = '''check("K17 任务池无限补位时由进度上限收尾（不会死循环）",
      # SimUI 的行标题都带 (N/5)，进度上限把单任务放到 5 次
      sim_r.browses == len(sim_r.bases) * 5,
      "%d" % sim_r.browses)'''
new = '''check("K17 带 (N/5) 进度的任务会做到 5/5，且不会死循环",
      sim_r.browses == len(sim_r.bases) * 5,
      "%d" % sim_r.browses)'''
assert old in s
s = s.replace(old, new)

# 6) K4 说明：每行 (0/1) 做一次即满
old = 'check("K4 3 个可做任务全做完", sim.browses == 3, "%d" % sim.browses)'
new = 'check("K4 3 个可做任务全做完（(0/1) 各做 1 次）",\n      sim.browses == 3, "%d" % sim.browses)'
assert old in s
s = s.replace(old, new)

tmp = os.path.join(os.path.dirname(P), "_tmp_%s.py" % uuid.uuid4().hex[:8])
io.open(tmp, "w", encoding="utf-8").write(s)
os.remove(P)
os.rename(tmp, P)
print("patched")
