# -*- coding: utf-8 -*-
"""任务3【东东农场-领水滴】。

入口（复用 task2 FarmUI.open_farm）-> 农场页 -> 点击【领水滴】(expo_task_icon)
-> 弹窗【做任务 领水滴】-> 浏览任务 + 领取奖励。

用户 2026-11-11 明确的业务规则：
  1. 只有「任务描述展示【浏览6秒，奖励】」且「任务栏按钮为【去完成】或
     【逛一逛】」的才算未做任务，点这两个按钮去做（停留 10 秒）。
  2. 弹窗是长列表，必须逐屏下滑，把全部这类任务都做完，不能只做首屏。
  3. 全部做完后，从第一个【去领奖】开始逐个领取，直到没有为止。
  4. 浏览任务跳出去之后可能被系统弹窗/浮层/H5 断连页拦住，必须能自己
     回到任务面板继续把剩下的任务做完，不能因为一次 back 失败就整轮停摆。

真机 XML 实测约束（1080x2340 / Appium 3.9 / uiautomator2）：
- 弹窗任务列表一次性全在无障碍树里（y 从 805 一直排到 7375），
  但**屏幕外节点的 bounds 被裁成无效值**（例如 [189,2431][770,2341]，
  y1 > y2，parse_bounds 返回 None）。所以只能处理「当前屏 bounds 有效
  + displayed=true」的行，必须靠滑动把后面的任务带进屏幕。
- 按钮（去完成/逛一逛/去领奖）都是 TextView、clickable=false，
  必须按 text + 有效 bounds + displayed 定位，再用 adb 坐标点击。
- 任务行：左侧描述 text 含「浏览6秒，奖励」(x 约 189~770)，
  右侧按钮 text 为 去完成/逛一逛/去领奖 (x 约 838~1025)；按钮 cy 比
  描述 cy 小约 30~50px，用 90px 容差配成同一行。
- 列表里【浏览6秒…奖励】描述在 XML 中的**文档顺序恒定**（实测
  dialog5.xml 与滚动后的 mid.xml 都是 12 条、顺序一致），据此生成
  row_id，跨滚动/跨弹窗重建都能稳定标识同一任务行。
- 返回链路是多级的：弹窗 -> 商品详情/直播页 -> 系统跳转确认弹窗
  -> 农场 H5 断连页 -> 首页。一次 back 远远不够。
"""
import re
import time
import xml.etree.ElementTree as ET

from modules.base import BaseModule
import utils.driver as driver
from modules.task2_farm import FarmUI

BROWSE_SECONDS = 10         # 浏览停留秒数。页面写 6 秒，但实测 7 秒仍算未完成，
                            # 用户 2026-11-12 确认要拉到 10 秒。
MAX_BROWSE_TASKS = 40       # 单次执行浏览任务上限（列表很长）
MAX_SCROLLS = 30            # 弹窗内单向滚动的屏数上限
MAX_CLAIMS = 40             # 单次领奖次数上限
MAX_CYCLES = 3              # 「做任务 -> 领奖 -> 再做任务」最大轮次
MAX_CLAIM_IDLE_SCROLLS = 12 # 领奖阶段连续多少屏没找到【去领奖】就收尾（安全兜底）
FARM_WAIT = 25              # 农场页等内部节点渲染的秒数（H5 很慢）
DROPS_DIALOG_RETRIES = 6    # 点击【领水滴】打开弹窗的重试次数
TOP_SWIPES = 20             # 回列表顶部最多回滑次数

# ---- 返回/恢复参数（2026-11-11 追加） ----
RETURN_MAX_STEPS = 14       # 单个浏览任务返回弹窗的最大动作步数
MAX_REENTERS = 4            # 单次运行最多重建入口（首页->农场->弹窗）次数
MAX_REENTER_FAILS = 3       # 连续恢复失败达到该值才彻底放弃

# 「未做」任务：描述展示【浏览6秒，奖励】且按钮是【去完成】或【逛一逛】
BROWSE_DESC_KEY = "浏览6秒"
BROWSE_BUTTON_TEXTS = ("去完成", "逛一逛")
# 「已完成待领取」按钮：真机为【去领奖】，兼容用户口述的【去领取】
CLAIM_BUTTON_TEXTS = ("去领奖", "去领取")
ALL_TASK_BUTTONS = BROWSE_BUTTON_TEXTS + CLAIM_BUTTON_TEXTS
ROW_Y_TOLERANCE = 90        # 描述与按钮配成同一行的 y 容差（真机差 30~50px）

# 页面状态
ST_DIALOG = "dialog"          # 做任务 领水滴 弹窗
ST_JUMP = "jump_confirm"      # 系统「想要打开 XX，是否允许？」
ST_OVERLAY = "overlay"        # 浮层活动 / 直播间浮层
ST_HOME = "home"              # 京东首页
ST_FARM_ERR = "farm_error"    # 农场 H5「哎呀，出了点问题」
ST_FARM = "farm"              # 农场主页（弹窗已关）
ST_BROWSE = "browse"          # 商品详情 / 直播等浏览页
ST_OTHER = "other"

# 拦截层上「一律点掉」的文案。绝不把 允许/始终允许/确定/去使用 放进来——
# 那会跳出京东或触发业务动作。这些文案在任务弹窗正常状态下都不存在。
DISMISS_TEXTS = ("拒绝", "关闭浮层活动", "我知道了", "知道了", "取消")
DISMISS_DESCS = ("关闭浮层活动", "关闭直播间")


class Task3FarmDrops(BaseModule):
    name = "东东农场-领水滴"
    description = "进入东东农场，完成【做任务 领水滴】弹窗内的浏览任务并领取奖励"
    icon = u"\U0001F4A7"

    def run(self, log, stop_event):
        ui = None
        try:
            ui = FarmUI(driver.get_driver(), log, stop_event)
            log.write_log("设备分辨率 %dx%d（坐标按 1080x2340 等比缩放）" % (ui.W, ui.H))

            # ===== 1. 进入东东农场（复用 task2 入口） =====
            if not ui.open_farm():
                raise RuntimeError("无法进入【东东农场】页")
            if stop_event.is_set():
                return
            log.write_log("已进入【东东农场】页")

            # ===== 2. 等农场页完全渲染 -> 找到并点击【领水滴】按钮 =====
            if not self._open_drops_dialog(ui, log, stop_event):
                raise RuntimeError("无法打开【做任务 领水滴】弹窗")
            if stop_event.is_set():
                return

            # ===== 3. 逐屏完成浏览任务 + 回顶部逐个领奖 =====
            total_browse, total_claim = self._process_tasks(ui, log, stop_event)

            log.write_log("共完成 %d 个浏览任务、%d 次领奖" % (total_browse, total_claim))
            if not stop_event.is_set():
                log.done("东东农场-领水滴 完成：浏览 %d 个任务、领取 %d 次奖励" %
                         (total_browse, total_claim))

        except Exception as e:
            if ui is not None:
                ui.snapshot("task3_error")
            log.error("运行异常：%s: %s" % (type(e).__name__, e))

    # ==================================================================
    #  等待农场页完全渲染（领水滴按钮出现）
    # ==================================================================
    def _wait_farm_ready(self, ui, log, timeout=FARM_WAIT):
        """等待农场页内部节点完全渲染（expo_task_icon 出现且 bounds 有效）。"""
        log.write_log("等待农场页完全加载...（最多 %d 秒）" % timeout)
        end = time.time() + timeout
        while time.time() < end:
            if ui.stop is not None and ui.stop.is_set():
                return False
            ui.invalidate()
            btn = self._find_drops_button(ui)
            if btn is not None:
                log.write_log("领水滴按钮已就绪 %s" % (btn["bounds"],))
                return True
            time.sleep(1)
        log.write_log("领水滴按钮未能在页面中检测到", "WARN")
        return False

    # ==================================================================
    #  打开【做任务 领水滴】弹窗
    # ==================================================================
    def _open_drops_dialog(self, ui, log, stop_event):
        """在农场页找到【领水滴】按钮并点击，进入任务弹窗。"""
        self._wait_farm_ready(ui, log)

        for i in range(DROPS_DIALOG_RETRIES):
            if stop_event.is_set():
                return False
            if self._is_drops_dialog(ui):
                log.write_log("【领水滴】弹窗已打开")
                return True

            btn = self._find_drops_button(ui)
            if btn is None:
                log.write_log("未找到【领水滴】按钮，等待页面加载（第 %d 次）" % (i + 1))
                ui.sleep(3)
                ui.invalidate()
                continue

            log.write_log("点击【领水滴】按钮 %s（第 %d 次）" % (btn["bounds"], i + 1))
            ui.tap(ui.center(btn), pause=3)

            if self._is_drops_dialog(ui):
                log.write_log("【领水滴】弹窗已打开")
                return True
            ui.sleep(2)
            ui.invalidate()

        return self._is_drops_dialog(ui)

    def _find_drops_button(self, ui):
        """在农场页找【领水滴】按钮（resource-id=expo_task_icon）。

        完全渲染后：Button / clickable=true / displayed=true / bounds 有效。
        未渲染时 bounds=[0,0][1083,0] 或 displayed=false，必须排除。
        """
        xml = ui.source()
        if not xml:
            return None
        try:
            root = ET.fromstring(xml.encode("utf-8"))
        except Exception:
            return None

        for n in root.iter():
            rid = (n.get("resource-id") or "").strip()
            if rid != "expo_task_icon":
                continue
            b = ui.parse_bounds(n.get("bounds"))
            if not b:
                continue
            # 部分 dump 不带 displayed 属性，缺省视为可见
            if n.get("displayed") == "false":
                continue
            x1, y1, x2, y2 = b
            if not (0 <= x1 < x2 <= ui.W and 0 <= y1 < y2 <= ui.H):
                continue
            return {
                "bounds": b,
                "text": (n.get("text") or "").strip(),
                "clickable": n.get("clickable") == "true",
                "class": (n.get("class") or "").rsplit(".", 1)[-1],
            }
        return None

    def _is_drops_dialog(self, ui):
        """检测是否在【做任务 领水滴】弹窗。

        系统跳转确认弹窗可能盖在任务弹窗之上，此时不能算「在弹窗」。
        """
        xml = ui.source(fresh=True)
        if not xml:
            return False
        if "想要打开" in xml or ("拒绝" in xml and "始终允许" in xml):
            return False
        if "关闭任务面板" in xml:
            return True
        if "做任务 领水滴" in xml:
            return True
        has_button = any(('text="%s"' % t) in xml for t in ALL_TASK_BUTTONS)
        has_browse = BROWSE_DESC_KEY in xml
        return has_button and has_browse

    # ==================================================================
    #  节点扫描
    # ==================================================================
    def _visible_nodes(self, ui, xml=None):
        """当前屏所有 displayed 不为 false 且 bounds 有效、落在屏幕内的节点。"""
        xml = xml if xml is not None else ui.source(fresh=True)
        if not xml:
            return []
        try:
            root = ET.fromstring(xml.encode("utf-8"))
        except Exception:
            return []
        out = []
        for n in root.iter():
            # 部分 dump 不带 displayed 属性，缺省视为可见；只有显式 false 才排除
            if n.get("displayed") == "false":
                continue
            b = ui.parse_bounds(n.get("bounds"))
            if not b:
                continue
            x1, y1, x2, y2 = b
            if not (0 <= x1 < x2 <= ui.W and 0 <= y1 < y2 <= ui.H):
                continue
            out.append({
                "text": (n.get("text") or "").strip(),
                "desc": (n.get("content-desc") or "").strip(),
                "bounds": b,
                "clickable": n.get("clickable") == "true",
            })
        return out

    def _collect_visible(self, ui, xml=None):
        """解析当前 XML，返回 (descs, browse_btns, claim_btns)。

        屏幕外节点 bounds 被裁成 y2 <= y1 的无效值，parse_bounds 会丢弃；
        这一步是「只处理当前屏」的关键。

        同时给任务行生成稳定的 row_id：按【浏览6秒…奖励】描述在 XML 中的
        文档序号编号。实测滚动前后（dialog5.xml / mid.xml）都是 12 条且
        顺序一致，所以 row_id 跨滚动、跨弹窗重建都稳定，用它做「已尝试」
        台账，不会因为 bounds 变化而重复点或漏点。
        """
        xml = xml if xml is not None else ui.source(fresh=True)
        if not xml:
            return [], [], []
        try:
            root = ET.fromstring(xml.encode("utf-8"))
        except Exception:
            return [], [], []

        descs, browse_btns, claim_btns = [], [], []
        desc_seq = 0
        claim_seq = 0
        for n in root.iter():
            t = (n.get("text") or "").strip()
            if not t:
                continue
            # 序号对屏幕外节点也计数（它们仍在树里）
            if BROWSE_DESC_KEY in t and "奖励" in t:
                desc_seq += 1
            if t in CLAIM_BUTTON_TEXTS:
                claim_seq += 1

            # 部分 dump 不带 displayed 属性，缺省视为可见
            if n.get("displayed") == "false":
                continue
            b = ui.parse_bounds(n.get("bounds"))
            if not b:
                continue
            x1, y1, x2, y2 = b
            if not (0 <= x1 < x2 <= ui.W and 0 <= y1 < y2 <= ui.H):
                continue
            item = {"bounds": b, "text": t, "cy": (y1 + y2) // 2, "y1": y1}
            if BROWSE_DESC_KEY in t and "奖励" in t and x1 < 800:
                d = dict(item)
                d["row_id"] = "D%d" % desc_seq
                descs.append(d)
            if t in BROWSE_BUTTON_TEXTS and x1 > 700:
                browse_btns.append(item)
            if t in CLAIM_BUTTON_TEXTS and x1 > 700:
                c = dict(item)
                c["row_id"] = "C%d" % claim_seq
                claim_btns.append(c)
        return descs, browse_btns, claim_btns

    def _pair_browse_rows(self, descs, btns):
        """把【浏览6秒，奖励】描述与右侧未做按钮配成任务行。

        每个按钮最多被用一次（used 集合），避免非浏览任务的「去完成」
        被相邻描述抢走；按 y 从上到下返回全部行。
        """
        rows = []
        used = set()
        for d in sorted(descs, key=lambda i: i["y1"]):
            best = None
            for idx, b in enumerate(btns):
                if idx in used:
                    continue
                gap = abs(b["cy"] - d["cy"])
                if gap > ROW_Y_TOLERANCE:
                    continue
                if best is None or gap < abs(btns[best]["cy"] - d["cy"]):
                    best = idx
            if best is None:
                continue
            used.add(best)
            b = btns[best]
            rows.append({
                "bounds": b["bounds"],
                "btn_text": b["text"],
                "desc": d["text"],
                "row_id": d.get("row_id"),
                "key": (b["text"], b["bounds"]),
            })
        return sorted(rows, key=lambda r: r["bounds"][1])

    def _find_browse_rows(self, ui):
        """当前屏全部「未做」浏览任务行。"""
        descs, btns, _ = self._collect_visible(ui)
        return self._pair_browse_rows(descs, btns)

    def _find_next_browse_task(self, ui):
        """兼容旧接口：当前屏第一个未做浏览任务。"""
        rows = self._find_browse_rows(ui)
        return rows[0] if rows else None

    def _find_claim_buttons(self, ui):
        """当前屏全部【去领奖】/【去领取】按钮，按 y 从上到下。"""
        _, _, claims = self._collect_visible(ui)
        return sorted(claims, key=lambda n: n["y1"])

    def _find_claim_button(self, ui):
        """兼容旧接口：当前屏第一个可领取按钮。"""
        btns = self._find_claim_buttons(ui)
        return btns[0] if btns else None

    # ==================================================================
    #  列表滚动与到底/到顶判定
    # ==================================================================
    def _fingerprint(self, ui):
        """当前屏可见任务行的 (text, y1) 指纹。"""
        xml = ui.source(fresh=True)
        if not xml:
            return ()
        try:
            root = ET.fromstring(xml.encode("utf-8"))
        except Exception:
            return ()
        fp = []
        for n in root.iter():
            t = (n.get("text") or "").strip()
            if not t or n.get("displayed") == "false":
                continue
            b = ui.parse_bounds(n.get("bounds"))
            if not b:
                continue
            x1, y1, x2, y2 = b
            if not (0 <= x1 < x2 <= ui.W and 0 <= y1 < y2 <= ui.H):
                continue
            if any(k in t for k in ("奖励", "去完成", "逛一逛", "去领奖",
                                    "去领取", "继续逛", "登录", "邀请")):
                fp.append((t[:24], y1))
        return tuple(sorted(fp))

    def _scroll_down(self, ui, log):
        """向下滚一屏；返回 False 表示已经到底（内容不再变化）。

        指纹不变有两种可能：真的到底，或者滑动被浮层/弹窗吞了。
        所以先尝试清掉拦截层再滑一次确认，避免把「滑不动」误判成「到底」
        而提前结束、留下没做完的任务。
        """
        before = self._fingerprint(ui)
        ui.swipe("task_list", pause=1.2)
        ui.invalidate()
        after = self._fingerprint(ui)
        if before != after:
            return True
        if self._clear_blockers(ui, log):
            ui.swipe("task_list", pause=1.2)
            ui.invalidate()
            return self._fingerprint(ui) != after
        return False

    def _scroll_to_top(self, ui, log):
        """连续回滑到列表顶部，返回实际滑动次数。"""
        used = 0
        for _ in range(TOP_SWIPES):
            before = self._fingerprint(ui)
            ui.swipe("task_list_down", pause=0.8)
            ui.invalidate()
            used += 1
            if self._fingerprint(ui) == before:
                break
        return used

    # ==================================================================
    #  页面分类 + 拦截层清理 + 返回/重建（问题 4 的核心）
    # ==================================================================
    def _classify(self, ui):
        """按当前 XML 判断页面状态。顺序不能乱：

        首页也带 text="东东农场"（金刚区标签），所以 ST_HOME 必须排在
        ST_FARM 前面；系统跳转确认弹窗可能盖在任务弹窗之上，所以 ST_JUMP
        必须排在最前。
        """
        xml = ui.source(fresh=True)
        if not xml:
            return ST_OTHER
        nodes = self._visible_nodes(ui, xml)
        texts = [n["text"] for n in nodes if n["text"]]
        descs = [n["desc"] for n in nodes if n["desc"]]
        blob = "\n".join(texts + descs)
        # 京东商品页把「继续滑动查看图文详情」渲染成竖排文字，
        # 节点 text 是 继\n续\n滑\n动... ，直接子串匹配会漏；
        # 去掉所有空白后再判关键字。
        flat = re.sub(r"\s+", "", blob)

        if "想要打开" in blob or ("拒绝" in texts and "始终允许" in texts):
            return ST_JUMP
        if "关闭任务面板" in blob or "做任务 领水滴" in blob:
            return ST_DIALOG
        if BROWSE_DESC_KEY in blob and any(t in ALL_TASK_BUTTONS for t in texts):
            return ST_DIALOG
        if "浮层活动" in blob:
            return ST_OVERLAY
        if (any("首页" in d and "已选中" in d for d in descs)
                or 'content-desc="首页, 已选中"' in xml):
            return ST_HOME
        if "哎呀，出了点问题" in blob or "重新连接" in blob:
            return ST_FARM_ERR
        # 首页金刚区也有 text="东东农场"，必须用 WebView 根节点标题区分
        if re.search(r'<android\.webkit\.WebView[^>]*\btext="东东农场"', xml):
            return ST_FARM
        if any(k in flat for k in ("继续浏览", "继续滑动查看图文详情",
                                    "京东直播", "加入购物车", "立即购买",
                                    "关闭直播间", "聊一聊", "图文详情")):
            return ST_BROWSE
        if "返回" in descs or "返回" in texts:
            return ST_BROWSE
        return ST_OTHER

    def _clear_blockers(self, ui, log):
        """点掉挡路的拦截层，返回是否点过。

        白名单严格：只点「拒绝/关闭浮层活动/我知道了/知道了/取消」和
        「关闭浮层活动/关闭直播间」。绝不点 始终允许/允许/确定。
        """
        nodes = self._visible_nodes(ui)
        for want in DISMISS_TEXTS:
            for n in nodes:
                if n["text"] == want:
                    log.write_log("清掉拦截层【%s】%s" % (want, n["bounds"]), "WARN")
                    ui.tap(ui.center(n), pause=1.2)
                    ui.invalidate()
                    return True
        for want in DISMISS_DESCS:
            for n in nodes:
                if n["desc"] == want:
                    log.write_log("清掉拦截层【%s】%s" % (want, n["bounds"]), "WARN")
                    ui.tap(ui.center(n), pause=1.2)
                    ui.invalidate()
                    return True
        return False

    def _ensure_dialog(self, ui, log, stop_event):
        """分步把界面拉回任务弹窗。返回 "ok" / "home" / "fail"。

        真机返回链路（多级，一次 back 不够）：
          弹窗 -> 商品详情/直播页 -> 系统跳转确认 -> 农场 H5 断连页 -> 首页
        """
        for step in range(RETURN_MAX_STEPS):
            if stop_event.is_set():
                return "fail"
            ui.invalidate()
            state = self._classify(ui)
            if state == ST_DIALOG:
                return "ok"
            log.write_log("返回任务面板：第 %d 步，页面=%s" % (step + 1, state), "WARN")

            if state in (ST_JUMP, ST_OVERLAY):
                if self._clear_blockers(ui, log):
                    ui.sleep(1.0)
                    continue
                ui.back(1.2)
                continue

            if state == ST_FARM_ERR:
                if step < 3:
                    btns = [n for n in self._visible_nodes(ui)
                            if n["text"] == "重新连接"]
                    if btns:
                        log.write_log("农场 H5 断连，点【重新连接】")
                        ui.tap(ui.center(btns[0]), pause=3)
                        ui.invalidate()
                        continue
                ui.back(1.5)
                continue

            if state == ST_FARM:
                # 农场主页但任务面板没了：直接再点一次【领水滴】
                if self._open_drops_dialog(ui, log, stop_event):
                    return "ok"
                ui.back(1.5)
                continue

            if state == ST_HOME:
                return "home"

            # ST_BROWSE / ST_OTHER：按返回键继续退
            ui.back(1.5)

        log.write_log("连续 %d 步仍未回到任务面板" % RETURN_MAX_STEPS, "WARN")
        return "fail"

    def _reenter_dialog(self, ui, log, stop_event):
        """任务面板彻底丢失时重建入口：首页 -> 东东农场 -> 领水滴。"""
        log.write_log("任务面板已丢失：重建入口（首页 -> 东东农场 -> 领水滴）", "WARN")
        ui.invalidate()
        try:
            ui.goto_home()
        except Exception as e:
            log.write_log("回首页异常：%s" % e, "WARN")
        ui.invalidate()
        try:
            if not ui.open_farm():
                raise RuntimeError("open_farm 返回 False")
        except Exception as e:
            log.write_log("重新进入【东东农场】失败：%s" % e, "WARN")
            return False
        if not self._open_drops_dialog(ui, log, stop_event):
            log.write_log("重新打开【做任务 领水滴】弹窗失败", "WARN")
            return False
        used = self._scroll_to_top(ui, log)
        log.write_log("已重建任务面板，回到列表顶部（%d 次回滑）" % used)
        return True

    def _recover_dialog(self, ui, log, stop_event):
        """统一恢复入口。返回 (ok, reentered)。"""
        res = self._ensure_dialog(ui, log, stop_event)
        if res == "ok":
            return True, False
        ok = self._reenter_dialog(ui, log, stop_event)
        return ok, True

    # ==================================================================
    #  单个浏览任务
    # ==================================================================
    def _do_one_browse(self, ui, log, stop_event, row, index):
        """点击一个未做任务、浏览 7 秒、分步返回弹窗。

        返回 done / reentered / skipped / stopped / lost。
        关键：不再因为一次 back 失败就返回 stopped 掐断整个列表。
        """
        log.write_log("第 %d 个浏览任务【%s】%s row=%s" %
                      (index, row["btn_text"], row["bounds"], row.get("row_id")))
        ui.tap(ui.center(row), pause=2)

        # 确认已离开弹窗（进入浏览页），否则重试一次
        if self._is_drops_dialog(ui):
            log.write_log("点击未生效（仍在弹窗），重试一次", "WARN")
            ui.tap(ui.center(row), pause=2)
        if self._is_drops_dialog(ui):
            log.write_log("点击被吞，跳过此任务", "WARN")
            return "skipped"

        if not ui.sleep(BROWSE_SECONDS):
            return "stopped"

        if self._is_drops_dialog(ui):
            log.write_log("浏览期间未跳出弹窗，任务可能未被计入", "WARN")

        ui.invalidate()
        ok, reentered = self._recover_dialog(ui, log, stop_event)
        if not ok:
            log.write_log("未能返回任务面板，重建入口也失败", "WARN")
            return "lost"
        return "reentered" if reentered else "done"

    # ==================================================================
    #  核心：逐屏完成浏览任务 + 回顶部逐个领奖
    # ==================================================================
    def _global_counts(self, ui, xml=None):
        """整个任务列表（含屏幕外节点）里的【去领奖】/已完成按钮个数。

        弹窗 XML 一次就把整张列表塞进无障碍树，屏幕外节点只是 bounds 被裁成
        y2 <= y1 的无效值，text 仍然在。所以不用滚动就能知道「还有没有
        【去领奖】」——列表只有 4~5 屏却白滑 8 次，就是缺这一步判断。
        """
        xml = xml if xml is not None else ui.source(fresh=True)
        if not xml:
            return {"claim": 0, "done": 0}
        try:
            root = ET.fromstring(xml.encode("utf-8"))
        except Exception:
            return {"claim": 0, "done": 0}
        claim = done = 0
        for n in root.iter():
            t = (n.get("text") or "").strip()
            if not t:
                continue
            if t in CLAIM_BUTTON_TEXTS:
                claim += 1
            elif t in ("已领取", "已完成"):
                done += 1
        return {"claim": claim, "done": done}

    def _phase_browse(self, ui, log, stop_event, attempted, reenters):
        """Phase 1：逐屏下滑，把全部未做浏览任务做完。

        返回 (本轮完成数, reenters, aborted)。
        attempted 跨轮次保留，避免同一行被反复点。
        """
        total_browse = 0
        consecutive_fail = 0
        resync = False

        used = self._scroll_to_top(ui, log)
        log.write_log("先回到任务列表顶部（%d 次回滑）" % used)

        scrolls = 0
        while scrolls < MAX_SCROLLS and total_browse < MAX_BROWSE_TASKS:
            if stop_event.is_set():
                return total_browse, reenters, True

            if not self._is_drops_dialog(ui):
                ok, reentered = self._recover_dialog(ui, log, stop_event)
                if reentered:
                    reenters += 1
                if not ok:
                    consecutive_fail += 1
                    log.write_log("恢复任务面板失败（连续 %d 次）" % consecutive_fail,
                                  "WARN")
                    if consecutive_fail >= MAX_REENTER_FAILS:
                        return total_browse, reenters, True
                    continue
                consecutive_fail = 0
                resync = True

            if resync:
                scrolls = 0
                self._scroll_to_top(ui, log)
                resync = False

            rows = [r for r in self._find_browse_rows(ui)
                    if (r.get("row_id") or r["key"]) not in attempted]
            if rows:
                row = rows[0]
                attempted.add(row.get("row_id") or row["key"])
                total_browse += 1
                state = self._do_one_browse(ui, log, stop_event, row, total_browse)

                if state == "stopped":
                    return total_browse, reenters, True
                if state == "lost":
                    consecutive_fail += 1
                    if consecutive_fail >= MAX_REENTER_FAILS:
                        log.write_log("连续恢复失败，停止浏览阶段", "WARN")
                        return total_browse, reenters, True
                    ok, reentered = self._recover_dialog(ui, log, stop_event)
                    if reentered:
                        reenters += 1
                    if ok:
                        resync = True
                        consecutive_fail = 0
                    continue
                if state == "reentered":
                    reenters += 1
                    resync = True
                consecutive_fail = 0
                ui.invalidate()
                continue

            # 当前屏没有未做浏览任务了 -> 向下滚一屏继续找
            if not self._scroll_down(ui, log):
                log.write_log("已滚动到列表底部，浏览阶段结束")
                break
            scrolls += 1
            log.write_log("下滑第 %d 屏继续找未做任务（累计完成 %d 个）" %
                          (scrolls, total_browse))

        if scrolls >= MAX_SCROLLS:
            log.write_log("达到最大滚动屏数 %d，主动停止浏览阶段" % MAX_SCROLLS, "WARN")
        return total_browse, reenters, False

    def _phase_claim(self, ui, log, stop_event, reenters):
        """Phase 2：从第一个【去领奖/去领取】开始逐个领取。

        返回 (本轮领取次数, reenters, aborted)。
        """
        total_claim = 0
        consecutive_fail = 0
        resync = False
        claim_skipped = set()

        if not self._is_drops_dialog(ui):
            ok, reentered = self._recover_dialog(ui, log, stop_event)
            if reentered:
                reenters += 1
            if not ok:
                log.write_log("领奖阶段开始前任务面板不可用，跳过领奖", "WARN")
                return 0, reenters, False
            resync = True

        counts = self._global_counts(ui)
        if counts["claim"] == 0 and counts["done"] > 0:
            log.write_log("全列表没有【去领奖/去领取】（已完成 %d 个），"
                          "跳过领奖、不再空滑" % counts["done"])
            return 0, reenters, False
        log.write_log("列表里还有 %d 个【去领奖】待领" % counts["claim"])
        remaining = counts["claim"]

        if not resync:
            used = self._scroll_to_top(ui, log)
            log.write_log("回到列表顶部（%d 次回滑）" % used)

        scrolls = 0
        idle = 0
        while scrolls < MAX_SCROLLS and total_claim < MAX_CLAIMS:
            if stop_event.is_set():
                return total_claim, reenters, True

            if not self._is_drops_dialog(ui):
                ok, reentered = self._recover_dialog(ui, log, stop_event)
                if reentered:
                    reenters += 1
                if not ok:
                    consecutive_fail += 1
                    if consecutive_fail >= MAX_REENTER_FAILS or reenters >= MAX_REENTERS:
                        log.write_log("领奖阶段恢复面板失败，停止领奖", "WARN")
                        return total_claim, reenters, True
                    continue
                resync = True
                consecutive_fail = 0

            if resync:
                scrolls = 0
                idle = 0
                claim_skipped.clear()
                self._scroll_to_top(ui, log)
                resync = False

            btns = [b for b in self._find_claim_buttons(ui)
                    if (b["text"], b["bounds"]) not in claim_skipped]
            if btns:
                idle = 0
                b = btns[0]
                total_claim += 1
                log.write_log("第 %d 次领奖【%s】%s" %
                              (total_claim, b["text"], b["bounds"]))
                ui.tap(ui.center(b), pause=2)
                ui.sleep(1.5)
                ui.invalidate()
                # 领取后可能弹「领取成功」浮层，先清掉再确认
                self._clear_blockers(ui, log)
                ui.invalidate()
                if not self._is_drops_dialog(ui):
                    ok, reentered = self._recover_dialog(ui, log, stop_event)
                    if reentered:
                        reenters += 1
                    if ok:
                        resync = True
                    else:
                        consecutive_fail += 1
                        if consecutive_fail >= MAX_REENTER_FAILS:
                            return total_claim, reenters, True
                        continue
                same = [x for x in self._find_claim_buttons(ui)
                        if x["text"] == b["text"] and x["bounds"] == b["bounds"]]
                if same:
                    log.write_log("领奖点击未生效，跳过该按钮", "WARN")
                    claim_skipped.add((b["text"], b["bounds"]))
                consecutive_fail = 0
                # 每次领完重新数一遍全表，别用「初始计数 -1」这种一厢情愿的账：
                # XML 偶发少报一个就会提前收尾、漏领。
                remaining = self._global_counts(ui)["claim"]
                if remaining <= 0:
                    log.write_log("列表里已没有【去领奖】，领奖完成")
                    break
                continue

            # 当前屏没有【去领奖】：连续多屏都没有才收尾，别把「还没滚到」当没有
            idle += 1
            if idle >= MAX_CLAIM_IDLE_SCROLLS:
                log.write_log("连续 %d 屏没有【去领奖】，领奖收尾" % idle, "WARN")
                break
            if not self._scroll_down(ui, log):
                log.write_log("已到列表底部、没有更多【去领奖】，领奖完成")
                break
            scrolls += 1
            log.write_log("下滑第 %d 屏继续找【去领奖】（累计领取 %d 次、"
                          "预计还剩 %d 个）" %
                          (scrolls, total_claim, max(0, remaining)))

        if scrolls >= MAX_SCROLLS:
            log.write_log("达到最大滚动屏数 %d，主动停止领奖阶段" % MAX_SCROLLS, "WARN")
        return total_claim, reenters, False

    def _process_tasks(self, ui, log, stop_event):
        """「做浏览任务 -> 领奖励 -> 再做任务」交替循环。

        用户 2026-11-13 反馈两点，对应下面两处改动：
          1. 列表只有 4~5 屏却为了找【去领奖】滑了 8 次、累计领取次数不变
             -> 领奖阶段先用 _global_counts() 判断全表有没有【去领奖】，
                一个都没有就直接跳过（0 次滑动）；
          2. 「没找到去领取，不能再去完成浏览任务吗」
             -> 领完奖回到浏览阶段再扫一遍（领取后常会放出新的浏览任务），
                直到某一轮「既没做任务、也没领到奖励」才收尾。
        """
        total_browse = 0
        total_claim = 0
        reenters = 0
        attempted = set()       # row_id 台账：跨滚动/跨弹窗重建/跨轮次都稳定

        for cycle in range(1, MAX_CYCLES + 1):
            if stop_event.is_set():
                break

            log.write_log("===== 第 %d 轮：逐屏完成所有【浏览6秒，奖励】的未做任务 "
                          "=====" % cycle)
            b, reenters, aborted = self._phase_browse(
                ui, log, stop_event, attempted, reenters)
            total_browse += b
            if aborted:
                break

            log.write_log("===== 第 %d 轮：从第一个【去领奖/去领取】开始逐个领取 "
                          "=====" % cycle)
            c, reenters, aborted = self._phase_claim(ui, log, stop_event, reenters)
            total_claim += c
            if aborted:
                break

            if b == 0 and c == 0:
                log.write_log("第 %d 轮既没有可做任务也没有可领奖励，结束" % cycle)
                break
            if c == 0:
                log.write_log("第 %d 轮没领到奖励，回到浏览任务再确认一次" % cycle)
                continue
            log.write_log("第 %d 轮：浏览 %d 个、领取 %d 次，继续下一轮" %
                          (cycle, b, c))

        return total_browse, total_claim
