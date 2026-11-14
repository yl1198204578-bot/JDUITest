# -*- coding: utf-8 -*-
"""v2.1：整帧 OCR 只在换屏时做，逐行做任务靠「小裁剪校验 + 标题条确认」。

真机 21:44 实测：整帧 OCR ≈5~7s，做每个任务都重来一遍 → 22s/任务；
改成每屏识别一次、每行按 (M-N) 连做，单任务回到 ~14s（停留 9~10s 为大头）。
"""
import io
import os
import uuid

P = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 "modules", "task14_coupons_v2.py")
s = io.open(P, encoding="utf-8").read()

# ---------- 1. _ocr 加耗时日志 ----------
old = '''        try:
            path = SHOT_HOOK(self.ui) if SHOT_HOOK else _default_shot(self.ui)
            if OCR_HOOK:
                return OCR_HOOK(path)
            if not path:
                return None
            return ocr_panel_items(path, box, scale)
'''
new = '''        t0 = time.time()
        try:
            path = SHOT_HOOK(self.ui) if SHOT_HOOK else _default_shot(self.ui)
            if OCR_HOOK:
                return OCR_HOOK(path)
            if not path:
                return None
            res = ocr_panel_items(path, box, scale)
            self._say(u"OCR %s 块=%d 用时 %.1fs"
                      % (u"标题条" if box == OCR_TITLE_BOX else u"面板",
                         len(res or []), time.time() - t0), "DEBUG")
            return res
'''
assert old in s
s = s.replace(old, new)

# ---------- 2. __init__ 新增状态 ----------
old = '        self.scrolled = False           # 面板列表是否被滑动过（决定要不要回顶）\n'
new = ('        self.scrolled = False           # 面板列表是否被滑动过（决定要不要回顶）\n'
       '        self.attempts = {}              # 每个任务已做次数\n'
       '        self.failures = {}\n'
       '        self.attempts_since = {}         # 上一整帧之后每个任务做了几次\n'
       '        self._prev_progress = {}         # 上一整帧的 (key -> N)\n')
assert old in s
s = s.replace(old, new, 1)

# ---------- 3. run() 重置 ----------
old = '''        self.scrolled = False
        self._verify_hit = False
        self._say(u"设备分辨率 %dx%d"'''
new = '''        self.scrolled = False
        self.attempts = {}
        self.failures = {}
        self.attempts_since = {}
        self._prev_progress = {}
        self._verify_hit = False
        self._say(u"设备分辨率 %dx%d"'''
assert old in s
s = s.replace(old, new)

# ---------- 4. 替换 _left_panel.._refresh_panel 之前的一段 ----------
NEW_DO = '''    # ---------- 做任务 ----------
    def _left_panel(self, tries=4):
        """点完任务按钮后确认已经离开面板。

        True=已离开 / False=面板还在（点击被吞）/ None=判不出来。
        慢页面要 2~3s 才换页，所以最多看 4 次（每次 ≈1.2s）；
        真机 21:44 就是因为只看两次，把「还在动画」误判成「点击被吞」，
        连丢 3 个任务。
        """
        for i in range(tries):
            there = self._panel_there()
            if there is None:
                return None
            if not there:
                return True
            self.ui.sleep(1.0 if i == 0 else 1.5)
        return False

    def _row_ready(self, row):
        """轻量校验：按钮还在不在原坐标（≈0.5s）。

        整帧 OCR 要 5~7s，每个任务都重来太慢；但做满的行一旦被撤下，
        后面的行会整体上移，按缓存坐标点就会点错行。所以点之前只 OCR
        按钮那一小块，确认还是白名单按钮。
        """
        b = row.get("bounds")
        if not valid(b):
            return False
        box = (max(0, b[0] - 40), max(0, b[1] - 30),
               min(self.ui.W, b[2] + 40), min(self.ui.H, b[3] + 30))
        items = self._ocr(box, 1.0)
        if items is None:
            return True                # 识别失败就信缓存，别把整轮卡死
        for it in items:
            if norm(it.get("text")) in ALL_BTN_TEXTS and \\
                    abs(int(it["y1"]) - b[1]) <= 100:
                return True
        self._say(u"按钮坐标已失效（行上移或被撤下），重读整帧", "WARN")
        return False

    def _dwell(self):
        secs = dwell_seconds() + self.dwell_bonus
        return min(DWELL_CAP, secs)

    def _sync_progress(self, rows):
        """两次整帧之间比进度：没涨说明停留没被算数，把停留时间加长。"""
        now = {}
        for r in rows or []:
            if progress_total(r["title"]) > 0:
                now[r["key"]] = progress_current(r["title"])
        for key, prev in (self._prev_progress or {}).items():
            if key not in now or not self.attempts_since.get(key):
                continue
            if now[key] <= prev:
                self.dwell_bonus = min(DWELL_BONUS_MAX,
                                       self.dwell_bonus + DWELL_BONUS_STEP)
                self._say(u"任务【%s】进度 %d → %d 没涨，停留加到 %ds"
                          % (key, prev, now[key], self._dwell()), "WARN")
        if now:
            self._prev_progress = now
        self.attempts_since = {}

    def _plan(self, row):
        """这一行本次还要做几次：带进度按 M-N，没进度的按剩余次数。"""
        key = row["key"]
        used = self.attempts.get(key, 0)
        total = progress_total(row["title"])
        if total > 0:
            cap = min(total, MAX_PER_TASK_PROGRESS)
            if used >= cap + MAX_PROGRESS_EXTRA:
                return 0
            return max(0, total - progress_current(row["title"]))
        return max(0, MAX_PER_TASK - used)

    def _do_one(self, row):
        """点按钮 → 确认离场 → 停留 9~10s → back 一次回面板。

        这里不做整帧 OCR：只 OCR 标题条确认面板回来了（≈1s）。
        """
        pt = row.get("center") or center(row["bounds"])
        self.ui.adb_tap(pt, pause=0.45)
        self.ui.sleep(0.6)
        left = self._left_panel()
        if left is None:
            p = self._probe(panel_first=True, force_xml=True)
            left = p["state"] != "panel"
        if not left:
            self._say(u"点了按钮页面没动，本次点击可能被吞", "WARN")
            return False
        secs = self._dwell()
        self._say(u"任务【%s】%s 按钮【%s】%s，停留 %ds"
                  % (row["title"] or row["key"], row["reward"],
                     row["text"], pt, secs))
        if not self.ui.sleep(secs):
            return False
        self._back(pause=0.7)
        for _ in range(3):
            there = self._panel_there()
            if there is None:
                break
            if there:
                self.panel_believed = True
                return True
            self.ui.sleep(0.8)
        self._say(u"浏览后没回到任务弹窗，重建入口", "WARN")
        self.panel_believed = False
        return self._open_panel()

'''
a = s.index("    # ---------- 做任务 ----------")
b = s.index("    def _refresh_panel(self):")
s = s[:a] + NEW_DO + s[b:]

# ---------- 5. 替换 _do_tasks ----------
NEW_TASKS = '''    def _do_tasks(self):
        total = 0
        blacklist = set()
        self._refreshed = False
        last_rows = []
        for cycle in range(MAX_PASSES):
            if self._stopped() or total >= MAX_TASKS:
                break
            self._say(u"===== 第 %d 轮：整帧识别 + 逐行做 =====" % (cycle + 1))
            if cycle > 0 and not self._open_panel():
                break
            self._to_top()
            done = 0
            stagnant = 0
            last_sig = None
            for _scroll in range(MAX_SCROLLS + 1):
                if self._stopped() or total >= MAX_TASKS:
                    break
                p = self._probe(panel_first=True)
                if p["state"] == "verify":
                    self._verify_hit = True
                    self._say(u"停在【京东验证】风控页，整轮停止", "WARN")
                    return total
                if p["state"] != "panel":
                    if not self._open_panel():
                        break
                    p = self._probe(panel_first=True)
                    if p["state"] != "panel":
                        break
                rows = p["rows"]
                if rows:
                    last_rows = rows
                self._sync_progress(rows)
                self._say(u"本屏 %d 个京豆任务：%s"
                          % (len(rows), u" / ".join(
                              u"%s(%d)" % (PROGRESS_RE.sub(u"", r["title"]),
                                           self._plan(r))
                              for r in rows[:6])), "DEBUG")
                for row in rows:
                    if self._stopped() or total >= MAX_TASKS:
                        break
                    key = row["key"]
                    if key in blacklist:
                        continue
                    left = self._plan(row)
                    while left > 0 and not self._stopped() and total < MAX_TASKS:
                        if not self._row_ready(row):
                            break          # 行上移了，跳出重读整帧
                        ok = self._do_one(row)
                        self.attempts[key] = self.attempts.get(key, 0) + 1
                        self.attempts_since[key] = \\
                            self.attempts_since.get(key, 0) + 1
                        left -= 1
                        if ok:
                            total += 1
                            done += 1
                            self.failures[key] = 0
                            self._say(u"浏览完成 #%d / 本轮 #%d【%s】得 %d 京豆"
                                      % (total, done, row["title"] or key,
                                         row["beans"]))
                            continue
                        if self._verify_hit:
                            self._say(u"撞上【京东验证】风控页，整轮停止", "WARN")
                            return total
                        n = self.failures.get(key, 0) + 1
                        self.failures[key] = n
                        if n >= MAX_RETRY:
                            blacklist.add(key)
                            self._say(u"任务【%s】连续 %d 次没成功，本轮拉黑"
                                      % (key, n), "WARN")
                            break
                # 本屏能做的都做完了 → 往下滑一屏
                if p["sig"] == last_sig:
                    stagnant += 1
                else:
                    stagnant = 0
                last_sig = p["sig"]
                if stagnant >= 2:
                    self._say(u"任务列表已滑到底")
                    break
                self._scroll_up()
            self._say(u"第 %d 轮完成浏览 %d 次（累计 %d 次）"
                      % (cycle + 1, done, total))
            if done == 0:
                if self._refresh_panel():
                    continue
                self._say(u"任务列表已没有可做任务，结束")
                break
        self._report_left(last_rows)
        if total >= MAX_TASKS:
            self._say(u"已达总浏览次数上限 %d，收尾" % MAX_TASKS, "WARN")
        return total

'''
a = s.index("    def _do_tasks(self):")
b = s.index("    def _report_left(self, rows):")
s = s[:a] + NEW_TASKS + s[b:]

tmp = os.path.join(os.path.dirname(P), "_tmp_%s.py" % uuid.uuid4().hex[:8])
io.open(tmp, "w", encoding="utf-8").write(s)
os.remove(P)
os.rename(tmp, P)
print("patched, lines =", len(s.split("\n")))
