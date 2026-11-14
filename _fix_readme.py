# -*- coding: utf-8 -*-
"""修复 README 提速章节（上一步反引号被 shell 吃掉）。"""
import io
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")

P = "README.md"
s = io.open(P, encoding="utf-8").read()

start = s.find(u"### 提速")
end = s.find(u"## License")
assert start > 0 and end > start, (start, end)

SEC = u"""### 提速（2026-11-13 晚）

真机实测单个任务从 **60~90s 降到约 15s**，靠四件事：

| 改动 | 收益 |
|---|---|
| 浏览停留 `12~15` → `9~10` 秒 | 每次省 3~6s |
| OCR 只裁面板区 + 0.45 降采样 | 单次 23.4s → 12.7s |
| 面板结果缓存（`panel_rows` + `MAX_STALE`）| 每个任务少 1 次 OCR（10~15s） |
| `_do_one` 把 back 后的读屏结果交给主循环；第 1 轮不再重复开弹窗 | 每个任务少 1~2 次 dump；整轮少 1 次 OCR |

缓存的安全边界（别乱放宽）：只在 `expect_panel and state == "center"` 且连续命中不超过
`MAX_STALE = 6` 次时生效；`_open_panel` 内部、点击按钮后的生效判定一律 `allow_stale=False`
真实读屏，避免「面板其实已经关了」时对着底页商品卡误点。

顺带修的坑：

10. **点击判定不能只看「弹窗是否消失」** —— 面板不进无障碍树时，面板开着 `state` 也是
    `center`。点完按钮再多等一帧：两帧都是 `panel/center` 才算点击被吞，且**不重复点**
    （否则第二次点击会落在商品页上）。
11. **`run()` 和 `_do_tasks()` 各开一次弹窗** —— 第 1 轮直接复用，省一次 10~20s 的 OCR。

回归：`_test_task14_coupons.py`（**225 例，全绿**），不连手机、不连 Appium、不加载 PaddleOCR。

"""

s = s[:start] + SEC + s[end:]

NEW = P + ".new"
io.open(NEW, "w", encoding="utf-8").write(s)
BAK = "_readme_prev2.bak"
if os.path.exists(BAK):
    os.remove(BAK)
os.rename(P, BAK)
os.rename(NEW, P)
print("readme fixed, len=%d" % len(s))
