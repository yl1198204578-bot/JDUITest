# -*- coding: utf-8 -*-
"""v3.2 提速：真机 10 分钟只做了 15 次浏览，时间烧在这三处：

1. 每轮开头「滑回顶部」用整帧 OCR 判是否到顶：5 次 × 6s = 30s
   → 改成滑完截一帧比像素（0.3s），没动就是到顶
2. 浏览完 back 常常把半屏 sheet 一起关掉，`_open_panel` 要从头探一遍
   （最先那个探针就是 6s OCR）→ 记住入口卡坐标直接点，1.5s 确认
3. 收尾把「本轮新下发、还没开始做」的行说成「未做满」，误导判断
"""
import io
import os
import uuid

ROOT = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.join(ROOT, "modules", "task14_coupons.py")
s = io.open(MOD, encoding="utf-8").read()


def rep(old, new, tag):
    global s
    assert old in s, "MISS " + tag
    s = s.replace(old, new, 1)


# ---- 常量：行区像素签名
rep("PATCH_BOX = (44, 876, 292, 958)",
    '''ROWS_BOX = (0, 1030, 1080, 2160)   # 任务行区（判「滑到底没有」）
ROWS_SIZE = (18, 24)
PATCH_BOX = (44, 876, 292, 958)''',
    "ROWS_BOX")

# ---- __init__ 记住入口坐标
rep("        self._ever_panel = False",
    "        self._entry_bounds = None        # 上次点开的入口卡坐标\n"
    "        self._ever_panel = False",
    "_entry_bounds")

# ---- _open_panel 记坐标
rep("""            self._say(u"点【领更多/更多任务】%s（第 %d 次）" % (b, k + 1))
            self._tap_entry(b)""",
    """            self._say(u"点【领更多/更多任务】%s（第 %d 次）" % (b, k + 1))
            self._entry_bounds = b
            self._tap_entry(b)""",
    "cache entry")

# ---- _to_top 改像素判顶
old_top = s[s.index("    def _to_top(self):"):
            s.index("    # ---------- 做任务 ----------")]
new_top = '''    def _to_top(self):
        """面板列表滑回顶部。只在真滑过之后才做，避免把半屏 sheet 拖关掉。

        判「到顶没有」不读整帧 OCR（一次 6s，5 次就是 30s）：
        滑完截一帧，把任务行区压成像素签名，跟上一帧一样就说明滑不动了。
        """
        if not self.scrolled:
            return
        self._say(u"先把任务列表滑回顶部再扫")
        prev = None
        for _ in range(MAX_TO_TOP):
            if self._stopped():
                return
            self._scroll_down()
            shot = self._shot()
            if shot is None:
                return
            sig = patch_vec(shot, ROWS_BOX, ROWS_SIZE)
            if sig is not None and prev is not None and patch_diff(sig, prev) < 2:
                break            # 这一下没滑动 = 已经到顶
            prev = sig
        self.scrolled = False

    def _reopen_fast(self):
        """浏览回来发现弹窗被带关了：直接点上次那张入口卡。

        比 `_open_panel` 从头状态机省一个 6s 的 OCR 探针，真机每 5 个任务
        就会走一次这条路（back 会把半屏 sheet 一起退掉）。
        """
        b = self._entry_bounds
        if b:
            self._say(u"直接点上次的入口卡 %s 重开弹窗" % (b,), "DEBUG")
            self._tap_entry(b)
            self.expect_panel = True
            self.panel_believed = True
            for _ in range(3):
                there = self._panel_there()
                if there is True:
                    self.scrolled = False
                    return True
                if there is None:
                    break
                self.ui.sleep(0.8)
        return self._open_panel()

'''
s = s.replace(old_top, new_top, 1)

# ---- _do_one 走快速重开
rep("""        self._say(u"浏览后没回到任务弹窗，重建入口", "WARN")
        self.panel_believed = False
        return self._open_panel(), None""",
    """        self._say(u"浏览后没回到任务弹窗，重建入口", "WARN")
        self.panel_believed = False
        return self._reopen_fast(), None""",
    "do_one reopen")

# ---- _report_left 分「没开始」和「没做满」
old_rep = s[s.index("    def _report_left(self, rows):"):
            s.index("    # ---------- 入口 ----------")]
new_rep = '''    def _report_left(self, rows):
        """收尾时说清楚还剩什么：让「没做完」看得见，而不是静默结束。"""
        fresh, left = [], []
        for r in rows or []:
            total = progress_total(r["title"])
            cur = progress_current(r["title"])
            name = PROGRESS_RE.sub(u"", r["title"])
            if not self.attempts.get(r["key"]):
                fresh.append(u"%s(0/%d)" % (name, total) if total else name)
            elif total > 0 and cur < total:
                left.append(u"%s(%d/%d)" % (name, cur, total))
            elif total == 0:
                left.append(name)
        if left:
            self._say(u"收尾检查：%d 个任务做了但没做满：%s"
                      % (len(left), u" / ".join(left[:8])), "WARN")
        if fresh:
            self._say(u"收尾检查：本屏还有 %d 个任务一次都没做（本轮时间用完/列表刚刷新）："
                      u"%s" % (len(fresh), u" / ".join(fresh[:8])), "WARN")
        if not left and not fresh:
            self._say(u"收尾检查：本屏已没有【完成得Y京豆】任务")

'''
s = s.replace(old_rep, new_rep, 1)

tmp = os.path.join(ROOT, "_tmp_%s.py" % uuid.uuid4().hex[:8])
io.open(tmp, "w", encoding="utf-8", newline="\n").write(s)
os.rename(MOD, os.path.join(ROOT, "_archive", "task14_prev4_%s.txt"
                            % uuid.uuid4().hex[:6]))
os.rename(tmp, MOD)
print("patched")
