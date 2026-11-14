# -*- coding: utf-8 -*-
"""任务4【种豆得豆】：截图驱动的【逛一逛】浏览任务循环。

真机实测 2026-11-11 22:00（1080x2340 / 京东 BabelActivity、WebActivity）：
- 活动页与任务弹窗都是持续动画的 H5。`adb shell uiautomator dump` exit=137
  被杀、远端文件不生成；Appium page_source 同样挂死。=> **XML 通道完全不可用**，
  旧版「dump -> 找节点 -> 同行配对」在真机上等于空转，21:52 实跑证实
  （连 _beans_activity_*.xml 都没生成）。
- 可用通道：adb shell screencap -p + pull、adb shell input tap、keyevent 4(back)。
- 【赚收获值】黄色圆角按钮 bounds (885,1481)-(1056,1631)，中心 (971,1556)。
- 任务弹窗右侧橙色按钮 x=840~1024，y 从 1092 起、行距 224px、一屏 6 行。
  【逛一逛】与【去完成】同色(#FF852E)；按钮灰度模板差异：同类 1.4~4.3，
  异类 8.6~9.3 -> 阈值 5.0 可区分（模板 assets/beans_browse_btn.png）。
- 现场反例：逛百度地图领现金(0/1) 描述「天天可提现最高领20元」+【去完成】，不点。
- 点【逛一逛】进 WebActivity 浏览页，实测需 6~7 步 back 才回任务弹窗。
- 浏览秒数 X **每行不同**（2026-11-12 真机同一屏同时出现 5s 和 15s）。
  X 从弹窗无障碍树里的「浏览页面Xs可得」文本读（H5 现在会吐文本），按
  「按钮中心最近的浏览文本」配对；XML 读不到时用 OCR 兜底；都失败才退回
  BROWSE_X=5。实际停留 = X + BROWSE_EXTRA(4)。

用户 21:15 给出的流程仍是判定依据：金刚区/【全部频道】-【互动游戏】进活动页
-> 点【赚收获值】出任务列表 -> 未做任务 = 「浏览页面Xs可得 + 逛一逛」
-> 点进去停留 (X+4)s（X 逐行读，不是写死的） -> 返回弹窗继续
-> 列表里再无该组合即结束。
"""
import os
import re
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET
from collections import deque

from PIL import Image, ImageChops, ImageStat

from modules.base import BaseModule
import utils.driver as driver
from utils.jd_ui import JDUI

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ---- 入口（原生页，仍走 JDUI.source()/nodes()）----
ENTRY_MAX_SWIPES = 2
ENTRY_DESC = "种豆得豆"
MIN_ICON_HEIGHT = 80
CHANNEL_TAB = "互动游戏"
GAME_LABEL = "种豆得豆"
PAGE_RENDER_WAIT = 5

# ---- 截图驱动（全部按 1080x2340 基准标定，运行时按图片尺寸等比缩放）----
BASE_W, BASE_H = 1080, 2340
EARN_BUTTON = (971, 1555)                 # 【赚收获值】兜底坐标（1080x2340 实测中心）
# 黄色按钮位置随活动页高度浮动（实测 y 中心 1290~1560 都出现过），
# 因此不能再用固定 ROI，改为全屏扫描 + 结构筛选。
EARN_ROI = (600, 700, 1080, 2200)         # 黄色元素粗筛区
EARN_MIN_W, EARN_MIN_H = 90, 80           # 排除"+10"之类小气泡
EARN_RIGHT_EDGE = 780                     # 按钮必须贴右（左边缘 > 该值 / 中心偏右）
EARN_TOPBAND = 900                        # 顶部奖励条区域上限，按钮必须在它下面
BTN_ROI = (820, 500, 1040, 2310)          # 橙色任务按钮搜索区
BTN_MIN_W, BTN_MIN_H = 120, 50            # 排除 +10 之类小图标
BTN_MIN_AREA = 60                         # step=3 采样下的连通块像素数
TEMPLATE_MAX_DIFF = 5.0                   # 单按钮 / sanity check 用
CLUSTER_MAX_DIFF = 5.0                    # 按钮两两单链接聚类阈值（跨分辨率稳定）
TEMPLATE_PATH = os.path.join(PROJECT_ROOT, "assets", "beans_browse_btn.png")
SCREEN_PATH = os.path.join(PROJECT_ROOT, "_beans_screen.png")
SCREENCAP_TIMEOUT = 15

BROWSE_X = 5                              # 读不到秒数时的兜底 X（现场最常见 5s）
BROWSE_EXTRA = 4                          # 统一停留 X+4 秒（与 task7/8/9/10 一致）
BROWSE_SECONDS = BROWSE_X + BROWSE_EXTRA  # = 9，仅作兜底/日志参考
ROW_TEXT_TOL = 110                        # 按钮中心与副标题中心的最大 y 差（行距 224）
READ_X_TRIES = 3                          # 读 X 时 page_source 的尝试次数（会偶发超时）
PANEL_SETTLE = 1.5                        # 回到弹层后等它稳定，再判下一帧
MAX_BROWSE_TASKS = 20
MAX_SCROLLS = 8
RETURN_MAX_STEPS = 12                     # 实测 6~7 步 back
MAX_NO_PROGRESS = 3
MAX_REENTERS = 3


# ==================================================================
#  截图 / 像素工具
# ==================================================================
def _adb_path():
    adb = shutil.which("adb")
    if adb:
        return adb
    for env in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        p = os.path.join(os.environ.get(env, ""), "platform-tools", "adb.exe")
        if os.path.isfile(p):
            return p
    return "adb"


def screencap(tag=None):
    """adb screencap + pull。固定覆盖 _beans_screen.png；给 tag 时另存 debug_shots 留证。

    走 adb 而不是 Appium get_screenshot_as_file：H5 页上 Appium session 不稳。
    """
    adb = _adb_path()
    remote = "/sdcard/_wb_beans_screen.png"
    devnull = subprocess.DEVNULL
    try:
        subprocess.call([adb, "shell", "screencap", "-p", remote],
                        stdout=devnull, stderr=devnull, timeout=SCREENCAP_TIMEOUT)
        subprocess.call([adb, "pull", remote, SCREEN_PATH],
                        stdout=devnull, stderr=devnull, timeout=SCREENCAP_TIMEOUT)
        if not (os.path.isfile(SCREEN_PATH) and os.path.getsize(SCREEN_PATH) > 1000):
            return ""
        if tag:
            folder = os.path.join(PROJECT_ROOT, "debug_shots")
            if not os.path.isdir(folder):
                os.makedirs(folder)
            shutil.copyfile(SCREEN_PATH, os.path.join(folder, "task4_%s.png" % tag))
        return SCREEN_PATH
    except Exception:
        return ""


def adb_back():
    """adb keyevent 4。不用 JDUI.back()：它走 Appium press_keycode，H5 上不稳。"""
    try:
        subprocess.call([_adb_path(), "shell", "input", "keyevent", "4"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        timeout=8)
        return True
    except Exception:
        return False


def _is_orange(r, g, b):
    # 实测按钮主色 (255,133,46)；下限放宽以覆盖渐变与抗锯齿
    return r > 205 and 55 < g < 180 and b < 115 and (r - g) > 65


def _is_yellow(r, g, b):
    """【赚收获值】浅黄底。

    实测为竖向渐变：顶部 (255,237,169) -> 底部 (255,228,125)，按钮内还有
    绿色豆子图标 (173,243,8)。旧判据 b<175 在真机截图上直接全灭，这是
    "找不到黄色按钮"的直接原因之一。
    """
    return (r > 230 and g > 200 and b < 210
            and (r - b) > 40 and (g - b) > 20)


def _blocks(img, roi, pred, min_w, min_h, min_area, step=3):
    """在 ROI 里找满足颜色谓词的连通块，返回 [(x1,y1,x2,y2)]，按 y,x 排序。"""
    W, H = img.size
    px = img.load()
    sx, sy = W / float(BASE_W), H / float(BASE_H)
    x1, x2 = int(roi[0] * sx), int(roi[2] * sx)
    y1, y2 = int(roi[1] * sy), int(roi[3] * sy)
    seen = set()
    out = []
    for y in range(y1, y2, step):
        for x in range(x1, x2, step):
            if (x, y) in seen:
                continue
            if not pred(*px[x, y]):
                continue
            q = deque([(x, y)])
            seen.add((x, y))
            xs, ys, n = [], [], 0
            while q:
                cx, cy = q.popleft()
                xs.append(cx); ys.append(cy); n += 1
                for dx, dy in ((step, 0), (-step, 0), (0, step), (0, -step)):
                    nx, ny = cx + dx, cy + dy
                    if nx < x1 or nx >= x2 or ny < y1 or ny >= y2 or (nx, ny) in seen:
                        continue
                    if pred(*px[nx, ny]):
                        seen.add((nx, ny)); q.append((nx, ny))
            if n < min_area:
                continue
            b = (min(xs), min(ys), max(xs), max(ys))
            if (b[2] - b[0]) < min_w * sx or (b[3] - b[1]) < min_h * sy:
                continue
            out.append(b)
    out.sort(key=lambda b: (b[1], b[0]))
    return out


def detect_buttons(path):
    """任务弹窗右侧的橙色按钮 bbox 列表。"""
    try:
        img = Image.open(path).convert("RGB")
    except Exception:
        return []
    return _blocks(img, BTN_ROI, _is_orange, BTN_MIN_W, BTN_MIN_H, BTN_MIN_AREA)


def detect_earn_button(path):
    """活动页【赚收获值】黄色按钮 bbox，找不到返回 None。

    只靠颜色会同时命中顶部【+10 每日领钱】气泡与任务栏按钮，所以做三层筛选：
      1) 尺寸门槛（宽>=90、高>=80 @1080x2340），干掉小气泡；
      2) 位置门槛：必须在页面右侧、且位于顶部奖励条之下；
      3) 多个候选时取最靠下的那个（按钮贴底，气泡在顶部）。
    """
    try:
        img = Image.open(path).convert("RGB")
    except Exception:
        return None
    W, H = img.size
    sx, sy = W / float(BASE_W), H / float(BASE_H)
    bs = _blocks(img, EARN_ROI, _is_yellow, EARN_MIN_W, EARN_MIN_H, 80)
    cands = []
    for b in bs:
        left, top, right, bottom = b[0] / sx, b[1] / sy, b[2] / sx, b[3] / sy
        if left < EARN_RIGHT_EDGE:
            continue
        if top < EARN_TOPBAND:
            continue
        if (right - left) < EARN_MIN_W or (bottom - top) < EARN_MIN_H:
            continue
        cands.append((top, b))
    if not cands:
        return None
    cands.sort(key=lambda t: t[0])
    return cands[-1][1]


def load_template():
    try:
        return Image.open(TEMPLATE_PATH).convert("L")
    except Exception:
        return None


def template_diff(gray, bbox, tpl):
    """按钮裁剪与【逛一逛】模板的平均灰度绝对差。"""
    c = gray.crop(bbox)
    if c.size != tpl.size:
        c = c.resize(tpl.size)
    return ImageStat.Stat(ImageChops.difference(c, tpl)).mean[0]


def pick_browse_buttons(gray, btns, tpl=None):
    """从橙色按钮里挑出【逛一逛】。

    主判据是「按钮两两单链接聚类」：同一屏里【逛一逛】是多数且彼此相似，
    【去完成】是离群点。实测 1080x2340 与 720x1560 两种分辨率下矩阵几乎一致
    ——逛一逛彼此 0~3.7，去完成与所有按钮 8.5~9.3，阈值 5.0 干净分开。
    这比固定模板的绝对 diff 抗缩放（插值会把 1.7 抬到 6.7）。

    模板只用于两处：最大簇的 sanity check（防止把去完成簇当主簇）、
    以及单按钮/全是孤点时无法聚类的退化情形。
    """
    n = len(btns)
    if n == 0:
        return []
    if tpl is None:
        tpl = load_template()
    ref = tpl.size if tpl is not None else (184, 78)
    crops = []
    for b in btns:
        c = gray.crop(b)
        if c.size != ref:
            c = c.resize(ref)
        crops.append(c)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(n):
        for j in range(i + 1, n):
            try:
                d = ImageStat.Stat(ImageChops.difference(crops[i], crops[j])).mean[0]
            except Exception:
                continue
            if d <= CLUSTER_MAX_DIFF:
                ri, rj = find(i), find(j)
                if ri != rj:
                    parent[ri] = rj

    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    root = max(groups, key=lambda r: len(groups[r]))
    largest = groups[root]
    others = [i for r, g in groups.items() if r != root for i in g]

    if len(largest) >= 2:
        if tpl is not None:
            def score(idx):
                return min(template_diff(gray, btns[i], tpl) for i in idx)
            if others and score(others) + 1.0 < score(largest):
                return [b for b in btns
                        if template_diff(gray, b, tpl) <= TEMPLATE_MAX_DIFF]
            # 防止纯【去完成】簇或购物页橙色促销标签簇（diff>=8.5）被当成【逛一逛】
            if score(largest) > 8.0:
                return []
        return [btns[i] for i in sorted(largest)]

    # 退化：只有 1 个按钮，或全是孤点 -> 模板绝对阈值
    if tpl is None:
        return []
    return [b for b in btns if template_diff(gray, b, tpl) <= TEMPLATE_MAX_DIFF]


def _are_modal_buttons(btns, W, H):
    """检查橙色按钮是否符合任务弹窗右侧统一规格胶囊按钮（x 对齐且尺寸一致）。"""
    if len(btns) < 2:
        return False
    sx, sy = W / float(BASE_W), H / float(BASE_H)
    aligned_xs = []
    for b in btns:
        w = (b[2] - b[0]) / sx
        h = (b[3] - b[1]) / sy
        if 140 <= w <= 220 and 55 <= h <= 105:
            aligned_xs.append(b[0] / sx)
    if len(aligned_xs) < 2:
        return False
    return (max(aligned_xs) - min(aligned_xs)) <= 30


def _looks_like_dialog_sheet(img):
    """判断截图是否具备种豆任务底部弹窗特征（上方压暗遮罩 + 下方白底卡片）。"""
    W, H = img.size
    px = img.load()
    sx, sy = W / float(BASE_W), H / float(BASE_H)
    top_vals = []
    for y_base in (280, 350, 430):
        y = int(y_base * sy)
        for x_base in (120, 540, 960):
            x = int(x_base * sx)
            if 0 <= x < W and 0 <= y < H:
                r, g, b = px[x, y]
                top_vals.append((r + g + b) / 3.0)
    white_hits = 0
    total_pts = 0
    for y_base in (680, 760):
        y = int(y_base * sy)
        for x_base in (80, 540, 1000):
            x = int(x_base * sx)
            if 0 <= x < W and 0 <= y < H:
                total_pts += 1
                r, g, b = px[x, y]
                if r > 235 and g > 235 and b > 235:
                    white_hits += 1
    if not top_vals or not total_pts:
        return False
    top_mean = sum(top_vals) / len(top_vals)
    return top_mean < 165 and white_hits >= max(4, total_pts - 1)


def classify(path, tpl=None):
    """判当前屏状态，返回 (state, browse_btns, earn_bbox)。

    state = "dialog"（任务弹窗） / "activity"（活动页，有赚收获值） / "other"。
    """
    if not path:
        return "other", [], None
    try:
        rgb = Image.open(path).convert("RGB")
    except Exception:
        return "other", [], None
    gray = rgb.convert("L")
    btns = detect_buttons(path)
    earn = detect_earn_button(path)
    if tpl is None:
        tpl = load_template()
    browse = pick_browse_buttons(gray, btns, tpl)
    if browse:
        return "dialog", browse, earn
    if tpl is None and len(btns) >= 2:
        return "dialog", [], earn
    if _are_modal_buttons(btns, rgb.size[0], rgb.size[1]):
        return "dialog", [], earn
    if earn:
        return "activity", [], earn
    if _looks_like_dialog_sheet(rgb):
        return "dialog", [], earn
    return "other", [], earn

def _key(b):
    """按钮位置指纹（10px 容差），用于本屏去重。"""
    return (b[0] // 10, b[1] // 10)


def _center(b):
    return ((b[0] + b[2]) // 2, (b[1] + b[3]) // 2)


def _contains(outer, inner):
    return (outer[0] <= inner[0] and outer[1] <= inner[1]
            and outer[2] >= inner[2] and outer[3] >= inner[3])


def _area(b):
    return (b[2] - b[0]) * (b[3] - b[1])


# ------------------------------------------------------------------
#  逐行读【浏览Xs可得】里的 X（真机 2026-11-12：同一屏有 5s 也有 15s）
# ------------------------------------------------------------------
_BROWSE_X_RE = re.compile(u"浏览\\D{0,8}?(\\d+)\\s*[sS\u79d2]")
# 任务行右侧按钮的文案（含做完后的态），用来确认 XML 与截图是同一屏
_ROW_BTN_RE = re.compile(u"^(逛一逛|继续逛|去完成|去邀请|去下单|去采摘|"
                        u"已完成|已领取|已结束|去领取)$")
_OCR = None


def browse_seconds(x):
    """页面要求 X 秒 -> 实际停留 X + BROWSE_EXTRA。"""
    return int(x) + BROWSE_EXTRA


def read_row_seconds(nodes, btn_cy, tol=ROW_TEXT_TOL):
    """读按钮所在行「浏览页面Xs可得」的 X；读不到返回 None。

    真机实测（_t4_dialog.xml）：副标题在按钮正下方约 34px，行距 224px。
    按「按钮中心 cy 最近的浏览文本」配对，容差 110px 既不串到相邻行，
    也不会漏掉本行。
    """
    best = None
    for n in nodes or []:
        b = n.get("bounds") or (0, 0, 0, 0)
        if b[3] <= b[1]:
            continue
        m = _BROWSE_X_RE.search(re.sub(r"\s+", "", n.get("text") or ""))
        if not m:
            continue
        d = abs((b[1] + b[3]) / 2.0 - btn_cy)
        if d <= tol and (best is None or d < best[0]):
            best = (d, int(m.group(1)))
    return best[1] if best else None


def xml_has_button_at(nodes, cy, tol=ROW_TEXT_TOL):
    """该 y 附近有没有任务行按钮节点。

    用来判断「page_source 和截图是不是同一屏」：H5 弹窗会自己滚动，
    page_source 偶发拿到的是上一帧，光按 y 配对会配到隔壁行（差一行
    224px 刚好越过容差，配错就是少逛或多逛）。
    """
    for n in nodes or []:
        b = n.get("bounds") or (0, 0, 0, 0)
        if b[3] <= b[1]:
            continue
        if not _ROW_BTN_RE.match((n.get("text") or "").strip()):
            continue
        if abs((b[1] + b[3]) / 2.0 - cy) <= tol:
            return True
    return False


def looks_like_dialog_xml(nodes, min_btns=2):
    """XML 里任务行按钮 >= min_btns 个就算弹窗还在。

    用于截图判非弹窗时的复核：H5 弹窗转场那一两帧会被像素判定为
    other，旧逻辑立刻走 12 步 back，结果把整个活动页退掉、白花几分钟。
    """
    cnt = 0
    for n in nodes or []:
        if _ROW_BTN_RE.match((n.get("text") or "").strip()):
            cnt += 1
            if cnt >= min_btns:
                return True
    return False


def read_row_seconds_ocr(png, btn_cy, tol=ROW_TEXT_TOL):
    """XML 读不到时的 OCR 兜底（H5 万一又不吐文本）。

    只在截图文件真实存在时才尝试，缺 paddleocr 直接返回 None，绝不抛错。
    """
    global _OCR
    if not png or not os.path.exists(png):
        return None
    try:
        from paddleocr import PaddleOCR
    except Exception:
        return None
    try:
        if _OCR is None:
            _OCR = PaddleOCR(use_angle_cls=False, lang="ch", show_log=False,
                             det_limit_side_len=960)
        res = _OCR.ocr(png, cls=False)
    except Exception:
        return None
    boxes = []
    for box, (txt, _score) in (res[0] if res and res[0] else []):
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        boxes.append({"text": txt,
                      "bounds": (int(min(xs)), int(min(ys)),
                                 int(max(xs)), int(max(ys)))})
    return read_row_seconds(boxes, btn_cy, tol)


# ==================================================================
#  入口（原生页，沿用已验证的动态金刚区 / 全部频道兜底）
# ==================================================================
def find_bean_icon(ui, xml):
    """首页 XML 里找金刚区【种豆得豆】格子，返回有效 bounds 或 None。"""
    if not xml:
        return None
    try:
        root = ET.fromstring(xml.encode("utf-8"))
    except Exception:
        return None
    parent = {}
    for p in root.iter():
        for c in p:
            parent[c] = p
    cands = []
    for n in root.iter():
        if (n.get("content-desc") or "").strip() != ENTRY_DESC:
            continue
        cur, b = n, None
        while cur is not None:
            b = ui.parse_bounds(cur.get("bounds"))
            if b:
                break
            cur = parent.get(cur)
        if not b:
            continue
        x1, y1, x2, y2 = b
        if not (0 <= x1 < x2 <= ui.W and 0 <= y1 < y2 <= ui.H):
            continue
        if (y2 - y1) < MIN_ICON_HEIGHT:
            continue
        cands.append(b)
    if not cands:
        return None
    cands.sort(key=lambda b: (-(b[3] - b[1]), b[1]))
    return cands[0]


# ==================================================================
#  模块主体
# ==================================================================
class Task4Beans(BaseModule):
    name = "种豆得豆"
    description = "进【种豆得豆】点【赚收获值】，循环完成【浏览页面Xs可得 + 逛一逛】浏览任务"
    icon = "\U0001fad8"

    def run(self, log, stop_event):
        ui = None
        try:
            ui = JDUI(driver.get_driver(), log, stop_event)
            log.write_log("设备分辨率 %dx%d（坐标按 1080x2340 等比缩放）" %
                          (ui.W, ui.H))
            summary = self._execute(ui, log, stop_event)
            log.done("种豆得豆完成：%s" % summary)
        except Exception as e:
            log.write_log("运行异常: %s: %s" % (type(e).__name__, e), "ERROR")
            if ui is not None:
                ui.snapshot("task4_beans_error")
            log.error("种豆得豆运行失败: %s" % e)

    # ------------------------------------------------------------------
    # 主流程
    # ------------------------------------------------------------------
    def _require_template(self):
        """模板是硬门槛：缺了就无法区分【逛一逛】和【去完成】。

        以前缺失时 browse 为空 -> 空滑 8 屏 -> log.done("完成")，属于假绿灯。
        现在直接抛错，走 run() 的 ERROR 分支。
        """
        tpl = load_template()
        if tpl is None:
            raise RuntimeError("缺少【逛一逛】按钮模板 %s，无法区分逛一逛/去完成，"
                               "拒绝盲点" % TEMPLATE_PATH)
        return tpl

    def _execute(self, ui, log, stop_event):
        self._require_template()
        log.write_step(1, 5, "冷启动京东，回到干净首页")
        if not ui.restart_to_home():
            raise RuntimeError("冷启动后未识别到京东首页，无法定位金刚区")
        ui._restarted = True
        if stop_event.is_set():
            return "已停止"
        if not ui.ensure_kingkong_visible():
            raise RuntimeError("首页未找到金刚区小图标")

        log.write_step(2, 5, "进入【种豆得豆】活动页（金刚区 / 全部频道-互动游戏）")
        if not self._open_activity(ui, log, stop_event):
            return "已停止"
        if stop_event.is_set():
            return "已停止"
        if not ui.sleep(PAGE_RENDER_WAIT):
            return "已停止"
        screencap("activity")

        log.write_step(3, 5, "点击【赚收获值】打开任务列表")
        if not self._open_task_dialog(ui, log, stop_event):
            screencap("no_dialog")
            return ("已进入活动页；未能打开任务列表，现场截图已保存。"
                    "该 H5 页 XML 不可用（adb uiautomator dump exit 137），仅靠像素识别")

        log.write_step(4, 5, "循环完成【浏览页面Xs可得 + 逛一逛】任务")
        summary, done = self._browse_loop(ui, log, stop_event)

        log.write_step(5, 5, "任务列表已无未做任务，结束")
        screencap("done")
        return summary

    # ------------------------------------------------------------------
    # 入口：金刚区直达 -> 兜底【全部频道】-【互动游戏】-【种豆得豆】
    # ------------------------------------------------------------------
    def _open_activity(self, ui, log, stop_event):
        for i in range(ENTRY_MAX_SWIPES + 1):
            if stop_event.is_set():
                return False
            xml = ui.source(fresh=True)
            bounds = find_bean_icon(ui, xml)
            if bounds:
                cx, cy = ((bounds[0] + bounds[2]) // 2, (bounds[1] + bounds[3]) // 2)
                log.write_log("金刚区第 %d 页命中【种豆得豆】%s，点击 (%d,%d)" %
                              (i + 1, bounds, cx, cy))
                ui.tap((cx, cy), pause=3)
                return True
            if i < ENTRY_MAX_SWIPES:
                log.write_log("金刚区第 %d 页未见【种豆得豆】，左滑翻页" % (i + 1))
                ui.swipe_kingkong("left")
        log.write_log("金刚区 %d 页都没有【种豆得豆】，改走【全部频道】-【互动游戏】" %
                      (ENTRY_MAX_SWIPES + 1), "WARN")
        return self._open_via_channels(ui, log)

    def _open_via_channels(self, ui, log):
        """复用 JDUI.to_all_channels() + task2 已验证的【互动游戏】格子定位。"""
        ui.to_all_channels()
        ui.sleep(2)
        tabs = [n for n in ui.nodes()
                if n["text"] == CHANNEL_TAB and n["clickable"] and ui.visible(n)]
        if not tabs:
            raise RuntimeError("【全部频道】页未找到【互动游戏】tab")
        tab = sorted(tabs, key=lambda n: n["bounds"][1])[0]
        log.write_log("点击【互动游戏】tab %s" % (tab["bounds"],))
        ui.tap(ui.center(tab), pause=2.5)

        labels = [n for n in ui.nodes() if n["text"] == GAME_LABEL and ui.visible(n)]
        if not labels:
            ui.sleep(2)
            ui.invalidate()
            labels = [n for n in ui.nodes() if n["text"] == GAME_LABEL and ui.visible(n)]
        if not labels:
            ui.tap(ui.center(tab), pause=2.5)
            ui.invalidate()
            labels = [n for n in ui.nodes() if n["text"] == GAME_LABEL and ui.visible(n)]
        if not labels:
            raise RuntimeError("【互动游戏】分区未找到【种豆得豆】")
        label = sorted(labels, key=lambda n: n["bounds"][1])[0]
        parents = [n for n in ui.nodes()
                   if n["clickable"] and _contains(n["bounds"], label["bounds"])]
        if parents:
            target = min(parents, key=lambda n: _area(n["bounds"]))
            pos = ui.center(target)
        else:
            pos = ((label["bounds"][0] + label["bounds"][2]) // 2,
                   max(0, label["bounds"][1] - 30))
        log.write_log("点击【种豆得豆】格子 %s（文字 %s）" % (pos, label["bounds"]))
        ui.tap(pos, pause=3)
        return True

    # ------------------------------------------------------------------
    # 打开任务弹窗（截图驱动）
    # ------------------------------------------------------------------
    def _open_task_dialog(self, ui, log, stop_event):
        tpl = load_template()
        if tpl is None:
            log.write_log("未找到【逛一逛】按钮模板 %s，只能靠坐标与颜色" %
                          TEMPLATE_PATH, "WARN")
        for attempt in range(3):
            if stop_event.is_set():
                return False
            png = screencap("pre_dialog")
            if png:
                state, browse, earn = classify(png, tpl)
                if state == "dialog":
                    log.write_log("任务列表弹窗已打开（%d 个【逛一逛】）" % len(browse))
                    return True
                cx, cy = None, None
                if earn:
                    cx, cy = _center(earn)
                    log.write_log("识别到【赚收获值】黄色按钮 %s，点击 (%d,%d)" %
                                  (earn, cx, cy))
                elif attempt >= 1:
                    cx, cy = ui.sx(EARN_BUTTON[0]), ui.sy(EARN_BUTTON[1])
                    log.write_log("黄色按钮未识别，按标定坐标点【赚收获值】(%d,%d)" %
                                  (cx, cy), "WARN")
                if cx is not None:
                    ui.tap((cx, cy), pause=3)
                    if not ui.sleep(2):
                        return False
                    st2, br2, _ = classify(screencap("dialog_check"), tpl)
                    if st2 == "dialog":
                        log.write_log("任务列表弹窗已打开（%d 个【逛一逛】）" % len(br2))
                        return True
            if not ui.sleep(2):
                return False
        return False

    # ------------------------------------------------------------------
    # 浏览任务主循环（截图驱动）
    # ------------------------------------------------------------------
    def _browse_loop(self, ui, log, stop_event):
        tpl = self._require_template()
        done = 0
        scrolls = 0
        reenters = 0
        idle = 0
        last_sig = None
        tried = set()
        total_ticks = MAX_BROWSE_TASKS * 3 + MAX_SCROLLS + 10

        for tick in range(total_ticks):
            if stop_event.is_set():
                return "已停止", done
            png = screencap("loop")
            if not png:
                break
            state, browse, earn = classify(png, tpl)

            if state != "dialog":
                # 先问 XML：弹窗其实还在（截图抓到转场帧）就别乱 back
                if looks_like_dialog_xml(self._safe_nodes(ui)):
                    log.write_log("截图判非弹窗但 XML 里弹窗还在，按弹窗继续", "WARN")
                    state = "dialog"
                    browse = []
                else:
                    res = self._return_to_dialog(ui, log, stop_event, tpl)
                    if res == "stopped":
                        return "已停止", done
                    if res == "fail":
                        if reenters >= MAX_REENTERS:
                            break
                        reenters += 1
                        if not self._reenter(ui, log, stop_event):
                            break
                    continue

            if not browse:
                if scrolls < MAX_SCROLLS:
                    self._scroll_task_list(ui)
                    scrolls += 1
                    tried.clear()
                    continue
                return "浏览任务 %d 个（下滑 %d 屏，无未做任务）" % (done, scrolls), done

            sig = tuple(browse)
            cand = [b for b in browse if _key(b) not in tried]
            if not cand:
                if scrolls < MAX_SCROLLS:
                    self._scroll_task_list(ui)
                    scrolls += 1
                    tried.clear()
                    continue
                return "浏览任务 %d 个（本屏已处理完）" % done, done

            idle = idle + 1 if sig == last_sig else 0
            last_sig = sig
            if idle >= MAX_NO_PROGRESS:
                self._scroll_task_list(ui)
                scrolls += 1
                tried.clear()
                idle = 0
                continue

            b = cand[0]
            tried.add(_key(b))
            cx, cy = _center(b)
            x_secs = self._read_x_seconds(ui, png, cy, log)
            dwell = browse_seconds(x_secs)
            log.write_log(
                "第 %d 个浏览任务【逛一逛】(%d,%d)，页面要求浏览 %ds -> 停留 %d 秒（X+%d）"
                % (done + 1, cx, cy, x_secs, dwell, BROWSE_EXTRA))
            ui.tap((cx, cy), pause=2)
            if not ui.sleep(dwell):
                return "已停止", done
            res = self._return_to_dialog(ui, log, stop_event, tpl)
            if res == "stopped":
                return "已停止", done
            if res == "ok":
                ui.sleep(PANEL_SETTLE)
            done += 1
            if done >= MAX_BROWSE_TASKS:
                return "达到浏览任务上限 %d 个" % done, done
            if res == "fail":
                if reenters >= MAX_REENTERS:
                    break
                reenters += 1
                if not self._reenter(ui, log, stop_event):
                    break

        return "浏览任务 %d 个" % done, done

    # ------------------------------------------------------------------
    # 返回链 / 滚动 / 重进
    # ------------------------------------------------------------------
    def _return_to_dialog(self, ui, log, stop_event, tpl):
        """从浏览页分步 back 回任务弹窗；若退回到活动主页则重开弹窗。"""
        for step in range(RETURN_MAX_STEPS):
            if stop_event.is_set():
                return "stopped"
            png = screencap("return")
            if png:
                state, _, _ = classify(png, tpl)
                if state == "dialog":
                    log.write_log("返回任务面板：第 %d 步" % (step + 1))
                    return "ok"
                if state == "activity":
                    log.write_log("返回至活动主页（第 %d 步），重新打开任务弹窗" % (step + 1))
                    if self._open_task_dialog(ui, log, stop_event):
                        return "ok"
                    return "fail"
            adb_back()
            ui.sleep(1.0)
        log.write_log("连续 %d 步 back 仍未回到任务面板" % RETURN_MAX_STEPS, "WARN")
        return "fail"

    def _safe_nodes(self, ui):
        """读当前页节点；失败/超时一律返回 []，绝不抛错。"""
        try:
            ui.invalidate()
        except Exception:
            pass
        try:
            return ui.nodes() or []
        except Exception:
            return []

    def _read_x_seconds(self, ui, png, btn_cy, log):
        """读本行要求的浏览秒数 X：XML 优先，OCR 兜底，最后用 BROWSE_X。"""
        x = None
        for i in range(READ_X_TRIES):
            nodes = []
            try:
                ui.invalidate()
            except Exception:
                pass
            try:
                nodes = ui.nodes() or []
            except Exception as e:
                log.write_log("读弹窗节点失败（%s）" % e, "WARN")
            x = read_row_seconds(nodes, btn_cy)
            if x is not None and not xml_has_button_at(nodes, btn_cy):
                log.write_log("XML 与截图不同屏（该行没有按钮节点），重读", "WARN")
                x = None
            if x is not None:
                break
            if i + 1 < READ_X_TRIES:
                ui.sleep(1.0)
        if x is None:
            x = read_row_seconds_ocr(png, btn_cy)
            if x is not None:
                log.write_log("XML 没读到浏览秒数，OCR 兜底读到 X=%d" % x, "WARN")
        if x is None:
            log.write_log("未读到【浏览Xs可得】，按默认 X=%d" % BROWSE_X, "WARN")
            return BROWSE_X
        return x

    def _scroll_task_list(self, ui):
        ui.adb_swipe(ui.sx(540), ui.sy(1900), ui.sx(540), ui.sy(900), 600)
        ui.sleep(1.2)
        ui.invalidate()

    def _reenter(self, ui, log, stop_event):
        """面板彻底丢失：回首页 -> 重走入口 -> 重点【赚收获值】。"""
        try:
            ui.goto_home()
        except Exception as e:
            log.write_log("回首页异常：%s" % e, "WARN")
        ui.invalidate()
        try:
            if not self._open_activity(ui, log, stop_event):
                return False
        except Exception as e:
            log.write_log("重新进入【种豆得豆】失败：%s" % e, "WARN")
            return False
        if not ui.sleep(PAGE_RENDER_WAIT):
            return False
        return self._open_task_dialog(ui, log, stop_event)
