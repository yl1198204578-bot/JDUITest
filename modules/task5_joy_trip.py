# -*- coding: utf-8 -*-
"""任务5【JOY游记】：进 JOY 页 -> 【去赚奖励】-> 做【浏览Xs】任务 -> 没有可做任务就结束。

入口（三级，与需求一致）：
  1. 京东首页金刚区第 1 页，节点 desc="JOY游记"
  2. 金刚区第 2 页（左滑一次）再找
  3. 第 2 页的【全部频道】->【互动游戏】->【JOY游记】

为什么这个模块必须用 OCR：
  JOY 页和任务面板都是自绘容器（page_source 里 class="d6.core.e40"，
  整页 21 个节点、0 个文本、只有 3 个 clickable 外壳），无障碍树拿不到
  「浏览10s」「逛一逛」。实测 PaddleOCR 2.7（本机已装）对面板截图识别
  准确，用「右侧按钮 + 同行【浏览Ns】小字」配对即可定位每一行。

任务判定（需求原文）：
  可做 = 描述含【浏览Xs】且按钮是【逛一逛】或【去完成】；
  停留 (X+4) 秒；循环到列表里没有可做任务为止。

实测（2026-11-12，1080x2340 / Appium 3.9 / uiautomator2）：
- 面板是底部弹层，标题【做任务赚晶石】固定在顶部，列表在其下滚动。
- 每行结构：图标 | 描述(N/M) + 【浏览10s +X】 | 右侧红按钮【逛一逛】/【去完成】。
- 【完成访问 +15】这类不是浏览任务，必须排除（用户明确要求）。
- 做完一个任务返回后，该行从可做列表消失，下面的行整体上移。
"""
import hashlib
import os
import re
import subprocess
import time

from modules.base import BaseModule
import utils.driver as driver
from utils.jd_ui import JDUI

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BROWSE_EXTRA = 4          # 停留 = X + 4 秒（用户 2026-11-12 定的规则）
BROWSE_BUTTON_TEXTS = (u"逛一逛", u"去完成")
PANEL_TITLE_KEY = u"做任务"       # 面板标题【做任务赚晶石】
JOY_PAGE_KEYS = (u"去赚奖励", u"领红包")   # JOY 页底栏固定文案
DET_LIMIT = 960           # OCR 检测边长：960 比默认快 ~2s，识别仍准确
BTN_MIN_X = 700           # 按钮必须贴右（左边是描述文字）
ROW_TOL = 130             # 同一行的按钮与小字，y 方向允许的偏差

MAX_TASKS = 40            # 最多做多少个浏览任务
MAX_SCROLLS = 12          # 列表最多滚几次
MAX_NO_PROGRESS = 3       # 连续几次「可做任务数没减少」就换一批
MAX_REENTER = 3           # 掉出面板后最多重进几次

# 兜底坐标（1080x2340 实测）：【去赚奖励】文字中心 (959,2203)
REWARD_BTN_RATIO = (0.888, 0.941)

_DEVNULL = subprocess.DEVNULL
_OCR = None


# ---------------------------------------------------------------- adb / OCR
def _adb_path():
    import shutil
    p = shutil.which("adb")
    if p:
        return p
    for env in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        base = os.environ.get(env)
        if base:
            cand = os.path.join(base, "platform-tools", "adb.exe")
            if os.path.isfile(cand):
                return cand
    return "adb"


def screencap(tag=None, tries=3):
    """adb screencap + pull，返回本地 png 路径；三次都失败返回 None。

    必须先删本地文件再 pull：adb 偶发超时（实测出现过 input tap 超时 8s），
    旧实现会静默把**上一张旧图**当成本次画面，于是 OCR 看到的是 JOY 首页、
    误判「任务面板没打开」，白白重试到失败。
    """
    adb = _adb_path()
    remote = "/sdcard/_joy_screen.png"
    local = os.path.join(PROJECT_ROOT, "_joy_screen.png")
    ok = False
    for i in range(tries):
        if os.path.isfile(local):
            try:
                os.remove(local)
            except Exception:
                pass
        try:
            subprocess.call([adb, "shell", "screencap", "-p", remote],
                            stdout=_DEVNULL, stderr=_DEVNULL, timeout=20)
            subprocess.call([adb, "pull", remote, local],
                            stdout=_DEVNULL, stderr=_DEVNULL, timeout=20)
        except Exception:
            pass
        if os.path.isfile(local) and os.path.getsize(local) > 1000:
            ok = True
            break
        time.sleep(1.0)
    if not ok:
        return None
    if tag and os.path.isfile(local):
        try:
            shots = os.path.join(PROJECT_ROOT, "debug_shots")
            if not os.path.isdir(shots):
                os.makedirs(shots)
            import shutil as _sh
            _sh.copyfile(local, os.path.join(shots, "joy_%s.png" % tag))
        except Exception:
            pass
    return local


def get_ocr():
    """懒加载 PaddleOCR。缺库时明确报错，绝不静默跳过（否则会假装做完了）。"""
    global _OCR
    if _OCR is None:
        try:
            from paddleocr import PaddleOCR
        except Exception as e:
            raise RuntimeError(
                "【JOY游记】页面是自绘容器（page_source 里没有任何文本），"
                "只能靠 OCR 识别；但导入 paddleocr 失败：%s。"
                "请先 pip install paddleocr paddlepaddle" % e)
        _OCR = PaddleOCR(use_angle_cls=False, lang="ch", show_log=False,
                         det_limit_side_len=DET_LIMIT)
    return _OCR


def ocr_items(img_path, crop_top=0):
    """OCR 一张图，返回 [{'text','cx','cy','x1','y1','x2','y2'}]。

    crop_top > 0 时先裁掉顶部（只识别任务面板区域），返回坐标已换算回全屏。
    截图失败（路径为 None）时返回 None，不要拿旧图凑数。
    """
    if not img_path or not os.path.isfile(img_path):
        return None
    from PIL import Image

    path = img_path
    if crop_top:
        im = Image.open(img_path)
        path = img_path[:-4] + "_crop.png"
        im.crop((0, int(crop_top), im.size[0], im.size[1])).save(path)
    res = get_ocr().ocr(path, cls=False)
    out = []
    for box, (txt, score) in (res[0] if res and res[0] else []):
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        out.append({
            "text": (txt or "").strip(),
            "cx": int(sum(xs) / 4),
            "cy": int(sum(ys) / 4) + int(crop_top),
            "x1": int(min(xs)),
            "y1": int(min(ys)) + int(crop_top),
            "x2": int(max(xs)),
            "y2": int(max(ys)) + int(crop_top),
        })
    return out


# ---------------------------------------------------------------- 纯逻辑（可离线测）
_CJK_RE = re.compile(u"[一-龥]")


def find_text(items, kw):
    """返回第一个文本包含 kw 的 OCR 块。"""
    for it in (items or []):
        if kw in it["text"]:
            return it
    return None


def panel_visible(items):
    """任务面板是否在场：标题【做任务赚晶石】。"""
    return any(PANEL_TITLE_KEY in it["text"] for it in (items or []))


def browse_seconds(x):
    """页面要求 X 秒 -> 实际停留 X + BROWSE_EXTRA。"""
    return int(x) + BROWSE_EXTRA


_BROWSE_RE = re.compile(u"浏览[^0-9]{0,3}(\\d+)\\s*[sS\u79d2]")


def parse_rows(items, btn_min_x=BTN_MIN_X, row_tol=ROW_TOL):
    """把 OCR 块配对成任务行。

    只有「右侧按钮（逛一逛/去完成）+ 同一行的【浏览Ns】小字」才算可做任务，
    所以【完成访问】那类行天然被排除（没有 浏览Ns）。
    返回 [{'text','secs','cx','cy','btn','title'}]，按 cy 升序（从上到下）。
    title 是这一行的描述（带 (N/M) 计数），用来判断「做完一步」而不是「整行消失」。
    """
    items = items or []
    btns = [i for i in items
            if i["text"] in BROWSE_BUTTON_TEXTS and i["cx"] >= btn_min_x]
    subs = []
    for i in items:
        m = _BROWSE_RE.search(i["text"])
        if m:
            subs.append((int(m.group(1)), i))
    rows = []
    for b in btns:
        cand = [(abs(s["cy"] - b["cy"]), secs, s) for secs, s in subs
                if abs(s["cy"] - b["cy"]) <= row_tol]
        if not cand:
            continue
        cand.sort(key=lambda t: t[0])
        _, secs, s = cand[0]
        rows.append({"text": s["text"], "secs": secs,
                     "cx": b["cx"], "cy": b["cy"], "btn": b["text"],
                     "title": row_title(items, b, btn_min_x)})
    rows.sort(key=lambda r: r["cy"])
    return rows


def row_title(items, btn, btn_min_x, up_min=6, up_max=75):
    """按钮正上方、左半边的文字就是这一行的描述。

    实测：描述 y=1325、按钮 y=1358（差 33）；下方的「浏览Ns」小字在 y=1390，
    所以只取按钮上方 6~75px。没找到返回空串。
    """
    best = None
    for it in items or []:
        if it["cx"] >= btn_min_x:
            continue
        dy = btn["cy"] - it["cy"]
        if dy < up_min or dy > up_max:
            continue
        txt = it["text"]
        if _BROWSE_RE.search(txt):
            continue
        # 实测面板里夹杂「￥」「0」之类的图标残片，
        # 它们比真正的描述更靠近按钮，会把标题抢走。
        if len(_CJK_RE.findall(txt)) < 2:
            continue
        if best is None or dy < best[0]:
            best = (dy, txt)
    return best[1] if best else u""


def row_sig(rows):
    """任务行签名。标题里带 (N/M)，所以「做完一步」会使签名变化。"""
    return tuple(sorted((r.get("title") or r["text"]) for r in (rows or [])))


def panel_crop_top(screen_h):
    """面板标题在 y≈683（1080x2340），裁 620 以上即可；按屏幕高度等比换算。"""
    return int(round(screen_h * 620.0 / 2340.0))


# ---------------------------------------------------------------- 模块
class Task5JoyTrip(BaseModule):
    name = "JOY游记"
    description = "进入【JOY游记】做【浏览Xs】任务（逛一逛/去完成），停留 X+4 秒，直到没有可做任务"
    icon = "🧳"

    # ---------- 主流程 ----------
    def run(self, log, stop_event):
        ui = JDUI(driver.get_driver(), log, stop_event)
        log.write_log("设备分辨率 %dx%d" % (ui.W, ui.H))
        log.write_log("提示：JOY 页与任务面板是自绘容器，本模块用 OCR 识别，"
                      "首次会加载模型（约 10 秒）")

        if not ui.restart_to_home():
            raise RuntimeError("冷启动后未识别到京东首页，无法定位金刚区【JOY游记】")
        ui._restarted = True
        if stop_event.is_set():
            return

        self._open_joy_page(ui, log)
        if stop_event.is_set():
            return

        items = self._open_task_panel(ui, log)
        if stop_event.is_set():
            return

        done = self._process_tasks(ui, log, stop_event, items)
        log.done("JOY游记 完成 %d 个浏览任务" % done)

    # ---------- 入口 ----------
    def _open_joy_page(self, ui, log):
        """金刚区第 1 页 -> 第 2 页 -> 全部频道-互动游戏。"""
        for page in (1, 2):
            icon, stable = ui._stable_kingkong_icon(u"JOY游记")
            if icon is not None:
                if not stable:
                    log.write_log("金刚区【JOY游记】位置在动，按最后一次 %s 点击"
                                  % (icon["bounds"],), "WARN")
                x1, y1, x2, y2 = icon["bounds"]
                pos = ((x1 + x2) // 2, (y1 + y2) // 2)
                log.write_log("金刚区第 %d 页命中【JOY游记】%s，点击 (%d,%d)"
                              % (page, icon["bounds"], pos[0], pos[1]))
                ui.tap(pos, pause=6)
                if self._wait_joy_page(ui, log):
                    log.write_log("已进入【JOY游记】（金刚区第 %d 页）" % page)
                    return True
                log.write_log("点了金刚区【JOY游记】但没进页面，继续下一级入口", "WARN")
            else:
                log.write_log("金刚区第 %d 页没有【JOY游记】" % page)
            if page == 1:
                log.write_log("左滑金刚区到第 2 页")
                ui.swipe_kingkong("left", pause=2)
                ui.invalidate()

        log.write_log("金刚区两页都没有【JOY游记】，走【全部频道】-【互动游戏】", "WARN")
        ui.to_all_channels()
        self._tap_node(ui, log, u"互动游戏", u"全部频道页")
        self._tap_node(ui, log, u"JOY游记", u"互动游戏页")
        if not self._wait_joy_page(ui, log):
            raise RuntimeError("三级入口都失败：金刚区两页与全部频道-互动游戏都没能进入【JOY游记】")
        log.write_log("已进入【JOY游记】（全部频道-互动游戏）")
        return True

    def _tap_node(self, ui, log, kw, where, pause=6):
        """按 text/desc 节点点击（优先 clickable，其次最靠上的）。"""
        cands = []
        for n in ui.nodes():
            v = (n.get("text") or "") + " " + (n.get("desc") or "")
            if kw not in v:
                continue
            b = n["bounds"]
            if b[3] <= b[1] or b[2] <= b[0]:
                continue
            cands.append((0 if n.get("clickable") else 1, b[1], n))
        if not cands:
            raise RuntimeError("%s 未找到【%s】节点" % (where, kw))
        cands.sort(key=lambda t: (t[0], t[1]))
        n = cands[0][2]
        pos = ui.center(n)
        log.write_log("%s 命中【%s】%s，点击 (%d,%d)"
                      % (where, kw, n["bounds"], pos[0], pos[1]))
        ui.tap(pos, pause=pause)
        ui.invalidate()

    def _wait_joy_page(self, ui, log, timeout=25):
        """JOY 页是自绘的，只能靠底栏文案判断。"""
        deadline = time.time() + timeout
        while True:
            items = self._read_screen(ui)
            for kw in JOY_PAGE_KEYS:
                if find_text(items, kw):
                    return True
            if time.time() >= deadline:
                return False
            ui.sleep(3)

    # ---------- 任务面板 ----------
    def _open_task_panel(self, ui, log):
        for i in range(3):
            items = self._read_screen(ui)
            # 面板可能已经开着（上一次点击已生效），别再去点底栏
            if panel_visible(items):
                log.write_log("任务面板已经打开")
                return items
            hit = find_text(items, u"去赚奖励")
            if hit is not None:
                pos = (hit["cx"], hit["cy"])
            else:
                pos = (int(ui.W * REWARD_BTN_RATIO[0]), int(ui.H * REWARD_BTN_RATIO[1]))
                log.write_log("OCR 没读到【去赚奖励】，按标定坐标 %s 兜底" % (pos,), "WARN")
            log.write_log("点击【去赚奖励】(%d,%d)" % pos)
            ui.tap(pos, pause=4)
            items2 = self._read_panel(ui)
            if panel_visible(items2):
                log.write_log("任务面板已打开")
                return items2
            log.write_log("未出现任务面板（第 %d 次），重试" % (i + 1), "WARN")
        raise RuntimeError("点了【去赚奖励】但【做任务赚晶石】面板没打开")

    def _reenter_panel(self, ui, log):
        """掉出面板（返回键把活动页也关了之类）时重新回到任务面板。"""
        for i in range(MAX_REENTER):
            log.write_log("尝试重新进入任务面板（第 %d 次）" % (i + 1), "WARN")
            if self._wait_joy_page(ui, log, timeout=12):
                try:
                    return self._open_task_panel(ui, log)
                except Exception as e:
                    log.write_log("重新打开面板失败：%s" % e, "WARN")
                    return None
            ui.back(2.0)
        return None

    # ---------- 做任务 ----------
    def _process_tasks(self, ui, log, stop_event, items=None):
        done = 0
        scrolls = 0
        no_progress = 0
        stuck = {}          # title -> 连续没进展次数
        if items is None:
            items = self._read_panel(ui)

        while not stop_event.is_set() and done < MAX_TASKS:
            if not panel_visible(items):
                items = self._reenter_panel(ui, log)
                if items is None:
                    log.write_log("无法回到任务面板，提前结束", "WARN")
                    break

            rows = parse_rows(items)
            if not rows:
                if scrolls >= MAX_SCROLLS:
                    log.write_log("已滚动 %d 次仍没有可做任务，结束" % scrolls)
                    break
                log.write_log("当前屏没有可做的【浏览Xs】任务，向下滚动找")
                if not self._scroll_panel(ui):
                    log.write_log("滚动后画面没有变化，判定已到底")
                    break
                scrolls += 1
                items = self._read_panel(ui)
                continue

            cand_rows = [r for r in rows
                         if stuck.get(r.get("title") or r["text"], 0) < 2]
            if not cand_rows:
                if scrolls >= MAX_SCROLLS:
                    log.write_log("可做任务都试过且没进展，结束")
                    break
                log.write_log("当前屏的任务都试过了，滚动换一批")
                if not self._scroll_panel(ui):
                    log.write_log("滚动后画面没有变化，判定已到底")
                    break
                scrolls += 1
                stuck.clear()
                items = self._read_panel(ui)
                continue

            row = cand_rows[0]
            secs = browse_seconds(row["secs"])
            key = row.get("title") or row["text"]
            log.write_log("浏览任务：%s -> 按钮【%s】(%d,%d)，停留 %d 秒"
                          % (key, row["btn"], row["cx"], row["cy"], secs))
            before_sig = row_sig(rows)
            ui.tap((row["cx"], row["cy"]), pause=3)
            if not ui.sleep(secs):
                log.write_log("被停止，中断任务", "WARN")
                break

            log.write_log("返回任务面板")
            ui.back(2.5)
            items = self._read_panel(ui)
            if not panel_visible(items):
                items = self._reenter_panel(ui, log)
                if items is None:
                    log.write_log("返回后无法回到任务面板，提前结束", "WARN")
                    break

            after_rows = parse_rows(items)
            after_sig = row_sig(after_rows)
            if after_sig != before_sig or len(after_rows) < len(rows):
                done += 1
                no_progress = 0
                stuck.pop(key, None)
                log.write_log("浏览完成 #%d（可做任务 %d -> %d）"
                              % (done, len(rows), len(after_rows)))
            else:
                no_progress += 1
                stuck[key] = stuck.get(key, 0) + 1
                log.write_log("该任务计数没有变化，换一个任务", "WARN")
                if no_progress >= MAX_NO_PROGRESS:
                    log.write_log("连续 %d 次没有进展，滚动换一批" % no_progress, "WARN")
                    no_progress = 0
                    if not self._scroll_panel(ui):
                        log.write_log("滚动后画面没有变化，判定已到底")
                        break
                    scrolls += 1
                    if scrolls >= MAX_SCROLLS:
                        break
                    items = self._read_panel(ui)

        return done

    # ---------- 截图 / 滚动 ----------
    def _read_screen(self, ui, tries=3):
        """全屏 OCR。截图失败就重拍，拍不到返回 None（不能拿旧图判断）。"""
        for _ in range(tries):
            path = screencap()
            if path:
                return ocr_items(path)
            ui.sleep(1.0)
        return None

    def _read_panel(self, ui, tries=3):
        for _ in range(tries):
            path = screencap()
            if path:
                return ocr_items(path, crop_top=panel_crop_top(ui.H))
            ui.sleep(1.0)
        return None

    def _panel_hash(self, ui):
        """面板区域画面指纹，用来判断滚动是否真的动了（比 OCR 快很多）。"""
        try:
            from PIL import Image
            path = screencap()
            if not path:
                return None
            im = Image.open(path).convert("L")
            crop = im.crop((0, panel_crop_top(ui.H), im.size[0], im.size[1]))
            return hashlib.md5(crop.tobytes()).hexdigest()
        except Exception:
            return None

    def _scroll_panel(self, ui):
        before = self._panel_hash(ui)
        x = ui.W // 2
        ui.adb_swipe(x, int(ui.H * 0.88), x, int(ui.H * 0.54), duration=500)
        ui.sleep(1.5)
        after = self._panel_hash(ui)
        if before is None or after is None:
            return True
        return before != after
