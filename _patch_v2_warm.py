# -*- coding: utf-8 -*-
"""补丁：OCR 模型改为主线程预热（后台线程 init 会导致段错误）。"""
import io
import os
import uuid

P = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 "modules", "task14_coupons_v2.py")
s = io.open(P, encoding="utf-8").read()

s = s.replace("import shutil\nimport subprocess\nimport threading\n",
              "import shutil\nimport subprocess\nimport time\n")

start = s.index("    def _warm_ocr(self):")
end = s.index("    def _ocr(self, box=None, scale=None):")
NEW_WARM = '''    def _warm_ocr(self):
        """先把 PaddleOCR 模型加载好（约 11s）。

        必须在主线程加载：实测在后台线程 init PaddleOCR、再回主线程调
        ocr()，解释器会直接段错误（真机 21:39 那次就是这么崩的）。
        这 11s 只花一次，且发生在冷启动之前，比每个任务重载便宜得多。
        """
        if OCR_HOOK is not None:
            return
        t0 = time.time()
        try:
            from modules.task5_joy_trip import get_ocr
            get_ocr()
            self._say(u"OCR 模型预热 %.1fs" % (time.time() - t0), "DEBUG")
        except Exception as e:
            self._say(u"OCR 模型预热失败（退化为 XML 通道）：%s" % e, "WARN")

'''
s = s[:start] + NEW_WARM + s[end:]

s = s.replace('''        if self._warm is not None and not self._warm_done.is_set():
            # 别在模型还在加载时再 new 一个 PaddleOCR 实例
            self._warm_done.wait(OCR_WARM_WAIT)
''', "")

s = s.replace('''        self._warm = None
        self._warm_done = threading.Event()
        self._warm_done.set()
''', "")

s = s.replace('''        self._verify_hit = False
        self._say(u"设备分辨率 %dx%d"''',
              '''        self._verify_hit = False
        self._warm_ocr()
        self._say(u"设备分辨率 %dx%d"''')

assert "threading" not in s
assert "OCR_WARM_WAIT" not in s
assert s.count("_warm_ocr") == 2

tmp = os.path.join(os.path.dirname(P), "_tmp_%s.py" % uuid.uuid4().hex[:8])
io.open(tmp, "w", encoding="utf-8").write(s)
os.remove(P)
os.rename(tmp, P)
print("patched ok")
