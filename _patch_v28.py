# -*- coding: utf-8 -*-
"""v2.8：领券中心页可能停在下方商品列表 → 找不到入口先往上滑；入口循环改回自动探针。

真机 22:15 那次：进页面后 H5 停在上次滚动位置，【天天领豆】卡片在屏幕上方，
_find_entry 找不到，12 步全是 8s 的无效 OCR（12 × 8s 白跑）。
"""
import io
import os
import uuid

P = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 "modules", "task14_coupons_v2.py")
s = io.open(P, encoding="utf-8").read()

# 1) 入口探针不再强制 OCR 优先（没有理由相信面板在场时，dump 比 8s OCR 便宜）
old = """            p = self._probe(panel_first=True)
            state = p["state"]
            self._say(u"入口第 %d 步：state=%s src=%s rows=%d\""""
new = """            p = self._probe()
            state = p["state"]
            self._say(u"入口第 %d 步：state=%s src=%s rows=%d\""""
assert old in s
s = s.replace(old, new)

# 2) 找不到入口 → 先把页面滑回顶部
old = """            b = self._find_entry(p["nodes"])
            if not b:
                if k % 3 == 2:
                    self._say(u"第 %d 次没找到【天天领豆/领更多】入口，"
                              u"等页面稳定" % (k + 1), "WARN")
                self.ui.sleep(1.0)
                continue"""
new = """            b = self._find_entry(p["nodes"])
            if not b:
                # 领券中心是 H5，会记住上次的滚动位置：卡片很可能在屏幕上方
                if miss < MAX_ENTRY_SCROLLS:
                    miss += 1
                    self._say(u"没看到【天天领豆/领更多】，先把页面滑回顶部"
                              u"（第 %d 次）" % miss)
                    self.ui.adb_swipe(self.ui.sx(540), self.ui.sy(900),
                                      self.ui.sx(540), self.ui.sy(1750), 600)
                    self.ui.sleep(1.2)
                else:
                    self._say(u"第 %d 次没找到入口，等页面稳定" % (k + 1), "WARN")
                    self.ui.sleep(1.0)
                continue"""
assert old in s
s = s.replace(old, new)

# 3) 计数器
old = """        last_entry, same_entry = None, 0
        for k in range(MAX_OPEN_STEPS):"""
new = """        last_entry, same_entry = None, 0
        miss = 0
        for k in range(MAX_OPEN_STEPS):"""
assert old in s
s = s.replace(old, new)

# 4) 常量
old = "MAX_ENTER_STEPS = 14"
new = "MAX_ENTER_STEPS = 14\nMAX_ENTRY_SCROLLS = 4        # 找不到入口时最多往上滑几次"
assert old in s
s = s.replace(old, new)

tmp = os.path.join(os.path.dirname(P), "_tmp_%s.py" % uuid.uuid4().hex[:8])
io.open(tmp, "w", encoding="utf-8").write(s)
os.remove(P)
os.rename(tmp, P)
print("ok")
