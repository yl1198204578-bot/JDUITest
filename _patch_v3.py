# -*- coding: utf-8 -*-
"""补丁：OCR 预热改到主线程；顺手修 typo。无 assert，改完打印校验信息。"""
import io
import os
import uuid

P = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 "modules", "task14_coupons_v2.py")
s = io.open(P, encoding="utf-8").read()
orig = s

# 1) 不再需要 threading
s = s.replace("import subprocess\nimport threading\n",
              "import subprocess\nimport time\n")

# 2) 常量表里的预热等待去掉
s = s.replace("OCR_WARM_WAIT = 60           # 后台预热模型的最长等待\n", "")

# 3) _warm_ocr 换成主线程加载
a = s.index("    def _warm_ocr(self):")
b = s.index("    def _ocr(self, box=None, scale=None):")
NEW = (
    '    def _warm_ocr(self):\n'
    '        """先把 PaddleOCR 模型加载好（约 11s）。\n'
    '\n'
    '        必须在主线程加载：实测在后台线程 init PaddleOCR、再回主线程调\n'
    '        ocr()，解释器会直接段错误（真机 21:39 那次就是这么崩的）。\n'
    '        这 11s 只花一次，且发生在冷启动之前，比每个任务重载便宜得多。\n'
    '        """\n'
    '        if OCR_HOOK is not None:\n'
    '            return\n'
    '        t0 = time.time()\n'
    '        try:\n'
    '            from modules.task5_joy_trip import get_ocr\n'
    '            get_ocr()\n'
    '            self._say(u"OCR 模型预热 %.1fs" % (time.time() - t0), "DEBUG")\n'
    '        except Exception as e:\n'
    '            self._say(u"OCR 模型预热失败（退化为 XML 通道）：%s" % e, "WARN")\n'
    '\n'
)
s = s[:a] + NEW + s[b:]

# 4) _ocr 里等预热的代码去掉
s = s.replace(
    '        if self._warm is not None and not self._warm_done.is_set():\n'
    '            # 别在模型还在加载时再 new 一个 PaddleOCR 实例\n'
    '            self._warm_done.wait(OCR_WARM_WAIT)\n', '')

# 5) __init__ 里的线程字段去掉
s = s.replace(
    '        self._warm = None\n'
    '        self._warm_done = threading.Event()\n'
    '        self._warm_done.set()\n', '')

# 6) typo
s = s.replace(u"风控页，群轮停止", u"风控页，整轮停止")

tmp = os.path.join(os.path.dirname(P), "_tmp_%s.py" % uuid.uuid4().hex[:8])
io.open(tmp, "w", encoding="utf-8").write(s)
os.remove(P)
os.rename(tmp, P)

print("changed:", s != orig)
print("threading:", "threading" in s)
print("OCR_WARM_WAIT:", "OCR_WARM_WAIT" in s)
print("_warm_ocr:", s.count("_warm_ocr"))
print("main-thread load:", "get_ocr()" in s)
print("_warm_done:", "_warm_done" in s)
