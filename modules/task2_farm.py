# -*- coding: utf-8 -*-
"""任务2【东东农场】：金刚区/全部频道 -> 农场幸运转盘 -> 逛一逛 + 抽奖。

流程（与需求一致）：
  1. 京东【首页】金刚区找【东东农场】：第一页、左滑后的第二页都按
     content-desc 节点扫；两页都没命中就走兜底
     【全部频道】->【互动游戏】->【东东农场】。
  2. 农场页等气泡渲染，点右侧【抽10京豆】进入【农场幸运转盘】。
  3. 逐个点击【逛一逛】，进入浏览页停留 15 秒后返回；重复直到页面里
     再也数不到【逛一逛】（所有任务都变成【继续逛】）。
  4. 点【开始抽奖】直到按钮下方的【剩余N次】变成 0。

实测约束（2026-11-11，1080x2340 / Appium 3.9 / uiautomator2）：
- 金刚区、【全部频道】页、转盘页都透出原生无障碍节点，可以按 text/desc
  精确定位；只有农场页气泡和【开始抽奖】按钮没有文字，用「气泡顺序 +
  标定坐标 + 点击后校验页面」处理。
- 转盘页 WebView 的 text 是空的，页面标识用文本节点 `剩余N次`。
- 任务列表在无障碍树里是完整的（含 displayed=false 的屏外节点，bounds
  退化为 [816,2384][1003,2341]），所以统计全文 `逛一逛` 的个数就能判断
  全局是否做完；屏外节点点不到，需要把列表滚进视口再点。
- 每完成一个浏览任务：逛一逛 -1、继续逛 +1、剩余抽奖次数 +1。
- 抽奖后弹「特别奖励已到账」，需点【开心收下】关闭才能继续抽。

本模块不修改任务1 的任何代码，只继承 JDUI 复用公共能力。
"""
import re
import time
import xml.etree.ElementTree as ET

from modules.base import BaseModule
import utils.driver as driver
from utils.jd_ui import JDUI

BROWSE_SECONDS = 15       # 每个【逛一逛】任务停留秒数。
                          # 页面写的是 6s，但实测 7s 仍算未完成（不加抽奖次数）；
                          # 2026-11-12 先拉到 10s，2026-11-13 用户又要求 15s
                          # （点【逛一逛】后【抽奖】入口/转盘加载本身要吃掉几秒，
                          #  10s 里净浏览时间不够，任务会不计数）。
FARM_WAIT = 18            # 农场页气泡渲染最长等待
WHEEL_WAIT = 15           # 转盘页加载最长等待
MAX_BROWSE_TASKS = 40     # 浏览任务总数上限
MAX_NO_PROGRESS = 3       # 连续几次浏览后「逛一逛」不减少就刹车
MAX_EMPTY_SCROLLS = 3     # 连续几次滚动都找不到可见【逛一逛】就收尾
MAX_SCROLLS = 20          # 浏览阶段滚动次数上限
MAX_DRAWS = 40            # 抽奖次数上限
MAX_DRAW_NO_PROGRESS = 3  # 连续几次抽奖后剩余次数不减就刹车

# 参考分辨率 1080x2340 下无文字控件的标定坐标（运行时按实际分辨率缩放）
POINTS = {
    "bubble_draw": (987, 677),   # 农场页右侧第 2 个气泡【抽10京豆】
    "start_draw": (540, 1336),   # 转盘页【开始抽奖】按钮
    "prize_ok": (357, 1480),     # 中奖弹窗【开心收下】
    "prize_close": (988, 577),   # 中奖弹窗右上角 X
}
SWIPES = {
    "task_up": ((540, 2050), (540, 1380)),   # 任务列表上滑，看后面的任务
    "task_down": ((540, 600), (540, 2050)),  # 滑回顶部
}
# 金刚区左右滑不再用固定 y：JDUI.swipe_kingkong() 会先找【秒杀】这类
# 小图标算出这一排的 y，再在该 y 上滑动（位置随首页改版变动也不怕）。
REMAINING_RE = "剩余"


def _area(b):
    return max(0, b[2] - b[0]) * max(0, b[3] - b[1])


def _contains(outer, inner):
    return (outer[0] <= inner[0] and outer[1] <= inner[1]
            and outer[2] >= inner[2] and outer[3] >= inner[3])


class FarmUI(JDUI):
    """东东农场专用 UI 层：页面识别、节点枚举、导航收敛。"""

    # ---------- 通用 XML 读取 ----------
    def all_texts(self, xml=None):
        """返回页面里所有 text / content-desc，含屏外（displayed=false）节点。

        WebView 把整张任务列表都放进了无障碍树，只是屏外节点 bounds 退化成
        无效值；JDUI.nodes() 会丢掉它们，所以判「还有几个任务」必须直接读 XML。
        """
        xml = xml if xml is not None else self.source()
        if not xml:
            return []
        try:
            root = ET.fromstring(xml.encode("utf-8"))
        except Exception:
            return []
        out = []
        for n in root.iter():
            for key in ("text", "content-desc"):
                v = (n.get(key) or "").strip()
                if v:
                    out.append(v)
        return out

    def find_text_node(self, text, xml=None):
        """找带有效 bounds 且可见的精确文本节点。"""
        for n in self.nodes(xml):
            if n["text"] == text and self.visible(n):
                return n
        return None

    def is_farm_page(self, xml=None):
        xml = xml if xml is not None else self.source()
        return bool(xml) and bool(re.search(
            r'<android\.webkit\.WebView[^>]*\btext="东东农场"', xml))

    def remaining(self, xml=None):
        """当前【剩余N次】，不在转盘页返回 None。"""
        xml = xml if xml is not None else self.source()
        for t in self.all_texts(xml):
            m = re.match(r"^剩余\s*(\d+)\s*次$", t)
            if m:
                return int(m.group(1))
        return None

    def on_wheel(self, xml=None):
        return self.remaining(xml) is not None

    def count_button(self, text, xml=None):
        """统计全文（含屏外）某个任务按钮的个数。"""
        return sum(1 for t in self.all_texts(xml) if t == text)

    # ---------- 农场页 ----------
    def wait_farm_ready(self, timeout=FARM_WAIT):
        """农场页 H5 要几秒才把右侧气泡渲染出来，等气泡至少 2 个。"""
        end = time.time() + timeout
        while time.time() < end:
            if self.stop is not None and self.stop.is_set():
                return False
            self.invalidate()
            if self.is_farm_page() and len(self.farm_bubbles()) >= 2:
                return True
            self.sleep(1)
        return self.is_farm_page() and len(self.farm_bubbles()) >= 2

    def farm_bubbles(self, xml=None):
        """农场页右侧一列气泡（节点无文字，text='图片'），按 y 排序去重。"""
        ns = self.nodes(xml)
        seen = set()
        out = []
        for n in ns:
            b = n["bounds"]
            if b in seen:
                continue
            if (n["text"] == "图片" and 850 <= b[0] <= 1000
                    and 380 <= b[1] <= 1250 and self.visible(n)):
                seen.add(b)
                out.append(n)
        return sorted(out, key=lambda n: n["bounds"][1])

    def wait_wheel(self, timeout=WHEEL_WAIT):
        end = time.time() + timeout
        while time.time() < end:
            if self.stop is not None and self.stop.is_set():
                return False
            self.invalidate()
            if self.on_wheel():
                self.sleep(1)  # 等任务列表渲染完再开始点
                return True
            self.sleep(1)
        return self.on_wheel()

    def enter_wheel(self, retries=2):
        """点【抽10京豆】进入转盘页；点完校验页面，没进就换下一个气泡。"""
        for _ in range(retries):
            if not self.wait_farm_ready():
                self.say("农场页气泡未渲染，稍后重试", "WARN")
                continue
            bubbles = self.farm_bubbles()
            # 实测顺序：限时水滴 / 抽10京豆 / 200京豆 / 点我到账水滴。
            # 优先第 2 个，失败时依次试其它气泡，最后用标定坐标兜底。
            centers = [self.center(n) for n in bubbles]
            order = []
            if len(centers) >= 2:
                order.append(centers[1])
            order += [c for i, c in enumerate(centers) if i != 1]
            order.append((self.sx(POINTS["bubble_draw"][0]),
                          self.sy(POINTS["bubble_draw"][1])))
            tried = set()
            for pos in order:
                if pos in tried:
                    continue
                tried.add(pos)
                self.say("点击农场气泡 %s（目标【抽10京豆】）" % (pos,))
                self.tap(pos, pause=2.5)
                if self.wait_wheel(timeout=6):
                    self.say("已进入【农场幸运转盘】页，剩余 %d 次" %
                             self.remaining())
                    return True
                # 没进转盘页：可能点到了领水滴等弹层，退回去再试
                if not self.is_farm_page():
                    self.back(1.5)
                self.invalidate()
            self.say("本轮未进入转盘页，刷新农场页后重试", "WARN")
            self.back(2)
            self.sleep(1)
        return False

    # ---------- 入口 ----------
    def farm_kingkong_node(self):
        """当前屏金刚区里可点的【东东农场】格子（原生节点，位置无关）。"""
        hits = [n for n in self.nodes()
                if n["desc"] == "东东农场" and n["clickable"] and self.visible(n)]
        if not hits:
            return None
        # 优先返回完整的格子；第一页右边缘半露的节点宽度只有 ~120
        return sorted(hits, key=lambda n: -_area(n["bounds"]))[0]

    def in_farm_page(self, timeout=12):
        """只判断「是否进了农场 H5」，气泡渲染交给 enter_wheel() 等。

        真机实测：金刚区点击后 WebView 标题先出现，气泡要再等几秒；把两件事
        分开判断，才不会因为气泡慢而误以为入口没点中、白滑一次金刚区。
        """
        end = time.time() + timeout
        while time.time() < end:
            if self.stop is not None and self.stop.is_set():
                return False
            self.invalidate()
            if self.is_farm_page():
                return True
            self.sleep(1)
        return self.is_farm_page()

    def tap_farm_node(self, node):
        """点金刚区【东东农场】格子；adb 点击偶发被吞，失败重试一次。"""
        for i in range(2):
            if i:
                self.say("点击【东东农场】未生效，重试一次", "WARN")
            self.tap(self.center(node), pause=3)
            if self.in_farm_page(timeout=12):
                return True
            if self.is_farm_page():
                return True
        return False

    def open_farm(self):
        """首页 -> 东东农场。先扫金刚区两页，失败再走全部频道/互动游戏。"""
        self.say("【入口】冷启动京东，确保从干净首页开始")
        if not self.restart_to_home():
            self.say("冷启动后未识别到首页，继续尝试", "WARN")
        self._restarted = True  # 兜底里的 to_all_channels 不再重复冷启动

        first_page = self.farm_kingkong_node()
        if first_page and _area(first_page["bounds"]) >= 20000:
            self.say("【入口】金刚区第 1 页命中【东东农场】%s" %
                     (first_page["bounds"],))
            if self.tap_farm_node(first_page):
                return True

        self.say("【入口】左滑金刚区到第 2 页继续找")
        self.swipe("kingkong")
        node = self.farm_kingkong_node()
        if node:
            self.say("【入口】金刚区第 2 页命中【东东农场】%s" % (node["bounds"],))
            if self.tap_farm_node(node):
                return True

        # 第 2 页没有时，回到第 1 页点之前记下的格子
        if first_page:
            self.say("【入口】回到金刚区第 1 页点半露的【东东农场】")
            self.swipe_kingkong("right", pause=1.2)
            if self.tap_farm_node(first_page):
                return True

        self.say("【入口】金刚区两页都没找到，改走【全部频道】-【互动游戏】",
                 "WARN")
        return self.open_farm_via_channels()

    def open_farm_via_channels(self):
        """兜底入口：全部频道 -> 互动游戏 -> 东东农场（同样按节点定位）。"""
        self.to_all_channels()
        self.sleep(2)
        tabs = [n for n in self.nodes()
                if n["text"] == "互动游戏" and n["clickable"] and self.visible(n)]
        if not tabs:
            raise RuntimeError("【全部频道】页未找到【互动游戏】tab")
        tab = sorted(tabs, key=lambda n: n["bounds"][1])[0]
        self.say("【入口】点击【互动游戏】tab %s" % (tab["bounds"],))
        self.tap(self.center(tab), pause=2.5)

        labels = [n for n in self.nodes() if n["text"] == "东东农场"]
        if not labels:
            self.sleep(2)
            labels = [n for n in self.nodes() if n["text"] == "东东农场"]
        if not labels:
            raise RuntimeError("【互动游戏】分区未找到【东东农场】")
        label = sorted(labels, key=lambda n: n["bounds"][1])[0]
        # 文字节点本身不可点，取包含它的最小可点击父格子
        parents = [n for n in self.nodes()
                   if n["clickable"] and _contains(n["bounds"], label["bounds"])]
        target = min(parents, key=lambda n: _area(n["bounds"])) if parents else None
        pos = self.center(target) if target else (label["bounds"][0] +
                                                  (label["bounds"][2] - label["bounds"][0]) // 2,
                                                  label["bounds"][1] - 30)
        self.say("【入口】点击【东东农场】%s" % (pos,))
        self.tap(pos, pause=3)
        if not self.in_farm_page():
            raise RuntimeError("未进入【东东农场】页，请查看 debug_shots 校准")
        return True

    # ---------- 转盘页 ----------
    def _raw_swipe(self, key, pause=1.2):
        (x1, y1), (x2, y2) = SWIPES[key]
        self.d.swipe(self.sx(x1), self.sy(y1), self.sx(x2), self.sy(y2), 600)
        self.sleep(pause)
        self.invalidate()

    def browse_buttons(self, xml=None):
        """当前可点的【逛一逛】文本节点，按 y 排序。

        文本节点 clickable=false，但其父按钮可点；adb 坐标点击会落到父按钮上，
        所以点文本中心即可。排除底部被裁切的半截按钮。
        """
        out = []
        for n in self.nodes(xml):
            if n["text"] != "逛一逛":
                continue
            b = n["bounds"]
            if not self.visible(n, top=200) or b[3] > self.H - 60:
                continue
            out.append(n)
        return sorted(out, key=lambda n: n["bounds"][1])

    def wheel_scroll(self, up=True):
        self._raw_swipe("task_up" if up else "task_down")

    def ensure_wheel_top(self, max_swipes=5):
        """把页面滑回顶部，保证【开始抽奖】按钮在视口内。"""
        for _ in range(max_swipes):
            node = None
            for n in self.nodes():
                if n["text"] and n["text"].startswith(REMAINING_RE) \
                        and "次" in n["text"] and self.visible(n):
                    node = n
                    break
            if node and node["bounds"][1] >= 1200:
                return True
            self.wheel_scroll(up=False)
        return True

    def prize_dialog_open(self, xml=None):
        texts = self.all_texts(xml)
        return any(t in texts for t in ("开心收下", "去浇水", "特别奖励已到账"))

    def dismiss_prize_dialog(self):
        """关闭中奖弹窗（【开心收下】优先，其次右上 X，最后坐标兜底）。"""
        for _ in range(3):
            if not self.prize_dialog_open():
                return True
            ok = [n for n in self.nodes()
                  if n["text"] == "开心收下" and n["clickable"] and self.visible(n)]
            if ok:
                self.tap(self.center(ok[0]), pause=1.5)
                continue
            x = [n for n in self.nodes()
                 if n["clickable"] and self.visible(n)
                 and 930 <= n["bounds"][0] <= 1010 and 500 <= n["bounds"][1] <= 650]
            if x:
                self.tap(self.center(x[0]), pause=1.5)
                continue
            self.tap((self.sx(POINTS["prize_ok"][0]),
                      self.sy(POINTS["prize_ok"][1])), pause=1.5)
        return not self.prize_dialog_open()

    def ensure_wheel(self, max_attempts=5):
        """浏览返回后把页面收敛回【农场幸运转盘】。"""
        for _ in range(max_attempts):
            self.invalidate()
            if self.on_wheel():
                return True
            if self.is_farm_page():
                self.say("落在农场页，重新点【抽10京豆】", "WARN")
                if self.enter_wheel(retries=1):
                    return True
            else:
                self.back(1.5)
        return self.on_wheel()


class Task2Farm(BaseModule):
    name = "东东农场"
    description = "金刚区/全部频道进东东农场，循环【逛一逛】停留15秒直到全变【继续逛】，再抽转盘到剩余0次"
    icon = "🌳"

    def run(self, log, stop_event):
        ui = None
        try:
            ui = FarmUI(driver.get_driver(), log, stop_event)
            log.write_log("设备分辨率 %dx%d（坐标按 1080x2340 等比缩放）" %
                          (ui.W, ui.H))

            # ===== 1. 入口 =====
            ui.open_farm()
            if stop_event.is_set():
                return
            log.write_log("已进入【东东农场】页")

            # ===== 2. 抽10京豆 -> 农场幸运转盘 =====
            if not ui.enter_wheel():
                raise RuntimeError("未能进入【农场幸运转盘】页，请查看 debug_shots")
            if stop_event.is_set():
                return

            # ===== 3. 逛一逛循环 =====
            browsed = self._browse_all(ui, log, stop_event)
            if stop_event.is_set():
                return

            # ===== 4. 抽到剩余 0 次 =====
            draws = self._draw_all(ui, log, stop_event)
            if stop_event.is_set():
                return

            log.write_log("累计完成 %d 个【逛一逛】、%d 次抽奖" % (browsed, draws))
            log.done("东东农场任务完成：浏览 %d 个任务、抽奖 %d 次（剩余 0 次）" %
                     (browsed, draws))

        except Exception as e:
            if ui is not None:
                ui.snapshot("task2_error")
            log.error("运行异常：%s: %s" % (type(e).__name__, e))

    # ---------- 浏览任务 ----------
    def _browse_all(self, ui, log, stop_event):
        done = 0
        no_progress = 0
        empty_scrolls = 0
        scrolls = 0
        empty_list_retries = 0
        for _ in range(MAX_BROWSE_TASKS):
            if stop_event.is_set():
                break
            if not ui.on_wheel() and not ui.ensure_wheel():
                log.write_log("无法回到【农场幸运转盘】页，浏览阶段提前结束", "WARN")
                break
            ui.invalidate()
            xml = ui.source(fresh=True)
            left = ui.count_button("逛一逛", xml)
            continued = ui.count_button("继续逛", xml)
            log.write_log("任务状态：【逛一逛】%d 个 /【继续逛】%d 个" %
                          (left, continued))

            if left == 0:
                # 复跑实测：转盘页刚加载时会出现 逛一逛=0 / 继续逛=0，
                # 那是任务列表还没渲染，不能当成「全部完成」。先重载确认。
                if continued == 0 and empty_list_retries < 3:
                    empty_list_retries += 1
                    log.write_log("任务列表尚未渲染（【逛一逛】/【继续逛】均为 0），等待重载")
                    ui.sleep(2)
                    ui.invalidate()
                    continue
                if continued:
                    log.write_log("所有任务都已变成【继续逛】，浏览阶段完成")
                else:
                    log.write_log("任务列表为空（今日无浏览任务），浏览阶段完成")
                break

            # 统一滚动刹车：点击被吞时也会滚动换任务，必须同样受限
            if scrolls >= MAX_SCROLLS:
                log.write_log("达到最大滚动次数，浏览阶段结束", "WARN")
                break

            btns = ui.browse_buttons(xml)
            if not btns:
                empty_scrolls += 1
                if empty_scrolls > MAX_EMPTY_SCROLLS:
                    log.write_log("连续 %d 次滚动仍无可见【逛一逛】，浏览阶段结束" %
                                  MAX_EMPTY_SCROLLS, "WARN")
                    break
                log.write_log("当前屏没有可点的【逛一逛】，上滑任务列表")
                ui.wheel_scroll(up=True)
                scrolls += 1
                continue
            empty_scrolls = 0

            btn = btns[0]
            pos = ui.center(btn)
            log.write_log("点击【逛一逛】%s" % (btn["bounds"],))
            ui.tap(pos, pause=1.5)

            # 点击被吞时绝不能傻等 7 秒再 back —— 那会把转盘页直接关掉
            ui.invalidate()
            if ui.on_wheel():
                log.write_log("点击未生效（仍在转盘页），重试一次", "WARN")
                ui.tap(pos, pause=1.5)
                ui.invalidate()
            if ui.on_wheel():
                log.write_log("【逛一逛】仍未生效，滚动换一个任务", "WARN")
                ui.wheel_scroll(up=True)
                scrolls += 1
                continue

            if ui.prize_dialog_open():
                ui.dismiss_prize_dialog()
            log.write_log("已进入浏览页，停留 %d 秒…" % BROWSE_SECONDS)
            if not ui.sleep(BROWSE_SECONDS):
                break

            log.write_log("返回【农场幸运转盘】页")
            ui.back(2)
            if not ui.ensure_wheel():
                log.write_log("返回后未回到转盘页，尝试恢复", "WARN")
                if not ui.ensure_wheel():
                    log.write_log("无法恢复转盘页，浏览阶段提前结束", "WARN")
                    break

            ui.invalidate()
            new_left = ui.count_button("逛一逛", ui.source(fresh=True))
            if new_left < left:
                done += 1
                no_progress = 0
                log.write_log("浏览完成 #%d（【逛一逛】%d -> %d，剩余抽奖 %s 次）" %
                              (done, left, new_left, ui.remaining()))
            else:
                no_progress += 1
                log.write_log("任务状态未变化（%d/%d）" %
                              (no_progress, MAX_NO_PROGRESS), "WARN")
                if no_progress >= MAX_NO_PROGRESS:
                    log.write_log("连续无进展，浏览阶段结束", "WARN")
                    break
        else:
            log.write_log("达到最大浏览任务数 %d，主动停止" % MAX_BROWSE_TASKS,
                          "WARN")
        return done

    # ---------- 抽奖 ----------
    def _draw_all(self, ui, log, stop_event):
        count = 0
        no_progress = 0
        for _ in range(MAX_DRAWS):
            if stop_event.is_set():
                break
            if not ui.on_wheel() and not ui.ensure_wheel():
                log.write_log("无法回到转盘页，抽奖阶段提前结束", "WARN")
                break
            ui.dismiss_prize_dialog()
            ui.ensure_wheel_top()
            ui.invalidate()
            before = ui.remaining(ui.source(fresh=True))
            if before is None:
                log.write_log("未读到【剩余N次】，抽奖阶段提前结束", "WARN")
                break
            if before == 0:
                log.write_log("抽奖次数已为 0，任务结束")
                break

            log.write_log("点击【开始抽奖】（剩余 %d 次）" % before)
            ui.tap((ui.sx(POINTS["start_draw"][0]),
                    ui.sy(POINTS["start_draw"][1])), pause=3)
            ui.dismiss_prize_dialog()

            after = None
            for _ in range(6):
                ui.invalidate()
                after = ui.remaining(ui.source(fresh=True))
                if after is not None and after != before:
                    break
                ui.sleep(1)
            if after is not None and after < before:
                count += 1
                no_progress = 0
                log.write_log("抽奖完成 #%d（剩余 %d -> %d 次）" %
                              (count, before, after))
            else:
                no_progress += 1
                log.write_log("剩余次数未减少（%d/%d，读到 %s）" %
                              (no_progress, MAX_DRAW_NO_PROGRESS, after), "WARN")
                if no_progress >= MAX_DRAW_NO_PROGRESS:
                    log.write_log("连续抽奖无进展，抽奖阶段结束", "WARN")
                    break
        else:
            log.write_log("达到最大抽奖次数 %d，主动停止" % MAX_DRAWS, "WARN")
        return count
