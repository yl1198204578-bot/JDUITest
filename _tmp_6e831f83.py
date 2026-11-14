# -*- coding: utf-8 -*-
"""任务14：【领券中心】天天领豆 —— 只做「完成得Y京豆」的浏览任务。

入口（用户指定）：
  打开京东 → 顶部一级 tab【特价】→ 二级 tab【领券中心】
  → 页面里【天天领豆 / 最高1000京豆 / 领更多】卡片（XML 里节点叫【更多任务】）
  → 点【领更多】弹出【做任务得奖励】任务面板

可做任务（严格按需求字面）：
  一行必须同时满足
    1) 奖励小字含【完成得Y京豆】（实测 浏览完成得2京豆 / 完成得2京豆）
    2) 右侧按钮是【去浏览 / 逛一逛 / 去完成】
  「完成任务获得抽奖机会」「浏览6S获得抽奖机会」「享券后超低价」
  「SK-II洗面奶13.9元限时抢」等一律排除，哪怕按钮也是【去完成】。
  每个任务停留 9~10 秒（可自适应加到 15s），back 一次回弹窗；
  循环扫描到整张任务列表（含向下滚动后的屏幕）没有可做任务为止。

提速（2026-11-13 真机实测，v2）：
  * 面板不在无障碍树里，XML 通道永远是空 → 之前靠「缓存命中」硬撑，
    缓存一过期就要重开弹窗 + OCR，单任务 30s 以上，还会在「面板其实开着」
    的帧里把【领更多】再点一次（点到面板后面的背景页），所以进度做不动。
  * 实测耗时：adb exec-out screencap 0.9s、page_source 0.2~9s（H5 动画面很慢）、
    裁面板 + 0.45 降采样 OCR 0.6s（模型加载 11s 单独预热，不进任务循环）。
  * 因此 v2 改成「截图 + OCR 判面板」为主通道：一帧 ≈1.6s，比 dump 快 1~5 倍，
    而且每帧都是真实画面，不需要任何缓存兜底。
  * 判「点击是否跳走」只 OCR 标题那一条 (0,845)-(600,1010)，≈1.1s。
  * 模型在 run() 一开始就后台预热，与冷启动/切页并行，任务循环里 0 等待。

真机踩坑（2026-11-13 实测，夹具见 _fixture_coupon_*）：
  * 首次进【领券中心】常弹「恭喜获得 ¥15 满30元可用」浮层；
    关闭按钮的 XML bounds 是 [1080,337][1068,314]（y2<=y1 退化），
    parse_bounds 会直接丢掉，只能按参考坐标 (540,2050) 点白色 X。
  * H5 弹窗节点时有时无：有的帧 page_source 完全没有【做任务得奖励】
    和【去完成】，但截图里弹窗好好的（_fixture_coupon_panel_no_nodes.xml）。
  * 【去完成】在 XML 里是 clickable=false 的 TextView，可点的是外层 View
    (811,1099,1012,1195)；所以按钮判据不能要求 clickable，
    只能靠「弹窗页面标记 + 可视安全区 + 贴右 x 区间」。
  * 弹窗叠在【领券中心】之上，XML 里两页节点混在一起；滚动后被弹窗顶部
    裁掉的行（y=532/728/926）bounds 依然合法、displayed=true，
    必须用 SAFE_TOP=1050 / SAFE_BOTTOM=2168 圈出弹窗可视区，否则点到背景页；
    SAFE_BOTTOM 还要避开 y>=2169 的系统底部导航栏（首页/购物车/我的）。
  * 长滑动 2050→1200 会把整个弹窗滚掉变成外层商品列表，
    弹窗内部列表只能用 1600→1100 的短滑动。
  * 任务池会补位、行标题带 (N/M) 进度；台账 key 必须去掉进度，
    并加 总次数 / 轮次 / 步数 / 滑动数 / 单任务次数 五重硬上限。
"""
import os
import random
import re
import shutil
import subprocess
import time

import utils.driver as driver
from modules.base import BaseModule
from utils.jd_ui import JDUI

# ---------------- 页面标记与按钮常量 ----------------
TAB_TEJIA = u"特价"
TAB_COUPON = u"领券中心"
PANEL_MARK = u"做任务得奖励"
PANEL_SUB_MARK = u"每日最高可领"
ENTRY_TEXTS = (u"更多任务", u"领更多", u"天天领豆")
FLOAT_MARKS = (u"满30元可用", u"整点再来")
# 浏览任务的商品落地页：只认商品列表专属文案。
# 千万别用「到手价」——领券中心底页的商品卡里也有它。
LANDING_MARKS = (u"条评价", u"好评率", u"继续浏览", u"好物清单")
VERIFY_MARKS = (u"京东验证", u"快速验证", u"验证一下")
BTN_TEXTS = (u"去浏览", u"逛一逛", u"去完成")
ALL_BTN_TEXTS = BTN_TEXTS + (u"已完成", u"已领取", u"领取奖励")

# 弹窗任务列表可视区（标题 y=882~1000，首行按钮 y=1115，底栏 y>=2169）
SAFE_TOP = 1050
SAFE_BOTTOM = 2168
BTN_MIN_X = 800
BTN_MAX_X = 1060
LEFT_MIN_X = 170              # 标题/奖励小字统一左对齐 x≈217
LEFT_MAX_X = 330
TITLE_MAX_DY = 85             # 标题 y1 比按钮 y1 早 24~32px
REWARD_MAX_DY = 95            # 奖励小字 y1 比按钮 y1 晚 34~44px

DWELL_MIN = 9
DWELL_MAX = 10                # 需求侧：9~10s；进度不涨时自适应加到 DWELL_CAP
DWELL_CAP = 15
DWELL_BONUS_STEP = 3
DWELL_BONUS_MAX = 6

# 参考分辨率 1080x2340 下的硬编码坐标 / 滑动（运行时用 sx/sy 缩放）
FLOAT_CLOSE_XY = (540, 2050)
SWIPE_UP = (540, 1600, 540, 1100)
SWIPE_DOWN = (540, 1100, 540, 1600)
SWIPE_MS = 450
OCR_CROP_TOP = 840                # 兜底路径：整屏下半部
# 面板固定在屏幕下半部，整屏 OCR 有一半算力花在没用的背景上。
# 裁到面板可视区 + 0.45 倍降采样：真机实测 23.4s -> 0.6s（模型预热后）。
OCR_BOX = (0, 860, 1080, 2180)
OCR_SCALE = 0.45
# 只判「面板在不在」时用更狠的裁剪：标题一条，0.6 倍，≈0.2s
OCR_TITLE_BOX = (0, 845, 620, 1015)
OCR_TITLE_SCALE = 0.6

MAX_TASKS = 40
MAX_PASSES = 8            # 从顶到底扫一遍算一轮
MAX_PER_SCREEN = 30
MAX_SCROLLS = 12
MAX_PER_TASK = 3          # 无进度信息的任务：最多做 3 次
MAX_PER_TASK_PROGRESS = 12  # 带 (N/M) 进度的任务：跟到 M 次，M 超过 12 封顶
MAX_PROGRESS_EXTRA = 2     # 进度不涨时，多给 2 次机会就放弃这一行
MAX_RETRY = 2
MAX_TO_TOP = 5
MAX_ENTER_STEPS = 14
MAX_ENTRY_SCROLLS = 4        # 找不到入口时最多往上滑几次
MAX_OPEN_STEPS = 12
MAX_OCR = 400
MAX_REVIVE = 2                # Appium 整轮最多重连 2 次
REVIVE_ADB_WAIT = 6.0         # 断连后等 adb 回来的秒数
PANEL_DIFF_MAX = 20          # 标题条补丁的平均灰度差上限（>20 认为面板没了）
RED_MIN = 0.30               # 按钮区「京东红」像素占比下限（去完成 vs 已完成）
PATCH_BOX = (44, 876, 292, 958)   # 只框【做任务得奖励】文字，避开会动的 ￥ 图标
PATCH_SIZE = (24, 8)
PANEL_CLOSE_XY = (1015, 895)      # 弹窗右上角 X（back 关不掉这个半屏 sheet）
                # 一帧 OCR ≈0.6s，预算只用来防失控

PROGRESS_RE = re.compile(u"[（(]\\s*\\d+\\s*/\\s*\\d+\\s*[）)]")
REWARD_RE = re.compile(u"完成得\\s*(\\d+)\\s*京豆")
PRICE_RE = re.compile(u"[¥￥]|到手价|^\\d+\\.\\d+$")

# 回归时可注入，避免加载 PaddleOCR / 真机截图
SHOT_HOOK = None             # callable(ui) -> png path
OCR_HOOK = None              # callable(png_path) -> ocr items

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHOT_PATH = os.path.join(PROJECT_ROOT, "_coupon_screen.png")


# ---------------- 纯函数：解析与判定 ----------------
def norm(t):
    """H5 会把文字渲染成竖排 / OCR 带噪声，关键字匹配前压掉空白。"""
    return re.sub(r"\s+", "", t or u"")


def valid(b):
    return bool(b) and len(b) == 4 and b[2] > b[0] and b[3] > b[1]


def center(b):
    return ((b[0] + b[2]) // 2, (b[1] + b[3]) // 2)


def in_list(b):
    """按钮是否真的落在当前屏弹窗任务列表的可视区。"""
    return (valid(b)
            and SAFE_TOP <= b[1]
            and b[3] <= SAFE_BOTTOM
            and b[0] >= BTN_MIN_X
            and b[2] <= BTN_MAX_X)


def is_button(n):
    """贴右 + 白名单文案 + 可视安全区。注意 XML 里 clickable=false。"""
    return norm(n.get("text")) in BTN_TEXTS and in_list(n.get("bounds"))


def classify(nodes):
    """页面状态：verify / panel / float / center / tejia / home / other。"""
    if not nodes:
        return "other"
    texts = set(norm(n.get("text")) for n in nodes)
    descs = set(norm(n.get("desc")) for n in nodes)
    blob = texts | descs
    if any(v in t for t in blob for v in VERIFY_MARKS):
        return "verify"
    # 弹窗是第一优先级：它叠在 center 之上，两页节点同时存在
    if any(PANEL_MARK in t or PANEL_SUB_MARK in t for t in texts):
        return "panel"
    if any(any(f in t for f in FLOAT_MARKS) for t in texts):
        return "float"
    # 落地页必须在 center 之前判：H5 会在同一个 WebView 里换页，
    # 商品页那帧的 XML 还残留着【领券中心】标题，只按 center 判会一直
    # 对着商品卡点【领更多】的坐标（真机 18:0x 那次就是这么空转的）。
    if any(any(m in t for m in LANDING_MARKS) for t in texts):
        return "landing"
    if any(norm(n.get("text")) == TAB_COUPON and n.get("class") == "WebView"
           for n in nodes):
        return "center"
    selected_tejia = any(TAB_TEJIA in d and u"已选中" in d for d in descs)
    selected_home = any(u"首页" in d and u"已选中" in d for d in descs)
    if selected_tejia and TAB_COUPON in texts:
        return "tejia"
    if selected_home:
        return "home"
    return "other"


def reward_of(nodes, b):
    """给按钮配同一行的【完成得Y京豆】奖励小字，返回 (京豆数, 原文)。"""
    cands = []
    for n in nodes:
        t = norm(n.get("text"))
        m = REWARD_RE.search(t)
        if not m:
            continue
        nb = n.get("bounds")
        if not valid(nb) or not (LEFT_MIN_X <= nb[0] <= LEFT_MAX_X):
            continue
        dy = nb[1] - b[1]
        if not (10 <= dy <= REWARD_MAX_DY):
            continue
        cands.append((abs(dy - 40), int(m.group(1)), t))
    if not cands:
        return (0, u"")
    cands.sort()
    return (cands[0][1], cands[0][2])


def row_title(nodes, b):
    """给右侧按钮配同行标题：带 (N/M) 进度的优先，其次纵向最近。"""
    cands = []
    for n in nodes:
        t = norm(n.get("text"))
        if not t or len(t) < 3 or t in ALL_BTN_TEXTS:
            continue
        if PRICE_RE.search(t) or REWARD_RE.search(t):
            continue
        nb = n.get("bounds")
        if not valid(nb) or not (LEFT_MIN_X <= nb[0] <= LEFT_MAX_X):
            continue
        dy = b[1] - nb[1]
        if not (-5 <= dy <= TITLE_MAX_DY):
            continue
        prog = bool(PROGRESS_RE.search(t))
        cands.append((0 if prog else 1, abs(dy - 27), nb[0], -len(t), t))
    if not cands:
        return u""
    cands.sort()
    return cands[0][4]


def task_key(title, btn_text, reward_text=u""):
    """台账 key 去掉 (N/M) 进度，任务做完进度 +1 时仍是同一个任务。"""
    base = PROGRESS_RE.sub(u"", title or u"")
    if not base:
        base = u"#" + norm(reward_text)[:12]
    return base + u"|" + norm(btn_text)


def _rows_from_nodes(nodes):
    out = []
    for n in nodes:
        if not is_button(n):
            continue
        b = n["bounds"]
        beans, reward_text = reward_of(nodes, b)
        if beans <= 0:
            continue                     # 非「完成得Y京豆」的行一律排除
        title = row_title(nodes, b)
        out.append({
            "text": norm(n.get("text")),
            "title": title,
            "reward": reward_text,
            "beans": beans,
            "bounds": tuple(b),
            "center": center(b),
            "key": task_key(title, n.get("text"), reward_text),
        })
    out.sort(key=lambda r: (r["bounds"][1], r["bounds"][0]))
    return out


def parse_rows(nodes):
    """XML 通道：解析当前屏可做任务。"""
    if classify(nodes) != "panel":
        return []
    return _rows_from_nodes(nodes)


def ocr_panel_visible(items):
    return any(PANEL_MARK in norm(it.get("text")) for it in (items or []))


def parse_ocr_rows(items):
    """OCR 通道：把 OCR 块伪装成 nodes 后复用同一套配对逻辑。"""
    if not ocr_panel_visible(items):
        return []
    nodes = []
    for it in (items or []):
        b = (int(it["x1"]), int(it["y1"]), int(it["x2"]), int(it["y2"]))
        nodes.append({"text": it.get("text", ""), "bounds": b,
                      "clickable": True, "class": "TextView"})
    return _rows_from_nodes(nodes)


def panel_sig(nodes):
    """当前屏所有按钮的坐标签名，用于判「滑到底 / 回到顶部」。"""
    items = []
    for n in nodes:
        t = norm(n.get("text"))
        b = n.get("bounds")
        if t in ALL_BTN_TEXTS and valid(b) and b[0] >= BTN_MIN_X:
            items.append((t, tuple(b)))
    items.sort()
    return tuple(items)


def ocr_sig(items):
    out = []
    for it in (items or []):
        t = norm(it.get("text"))
        if t in ALL_BTN_TEXTS:
            out.append((t, int(it["x1"]), int(it["y1"])))
    out.sort()
    return tuple(out)


def dwell_seconds(rnd=None):
    """每次浏览停留 9~10 秒（原来 12~15，提速后按需求压到 9 秒起）。"""
    r = rnd if rnd is not None else random
    return r.randint(DWELL_MIN, DWELL_MAX)


def progress_total(title):
    """标题里 (N/M) 的 M；没有进度返回 0。"""
    m = PROGRESS_RE.search(title or u"")
    if not m:
        return 0
    nums = re.findall(r"\d+", m.group(0))
    return int(nums[1]) if len(nums) >= 2 else 0


def progress_current(title):
    """标题里 (N/M) 的 N；没有进度返回 0。"""
    m = PROGRESS_RE.search(title or u"")
    if not m:
        return 0
    nums = re.findall(r"\d+", m.group(0))
    return int(nums[0]) if len(nums) >= 2 else 0


def task_limit(row, max_per_task=MAX_PER_TASK):
    """单任务允许做的次数：带 (N/M) 进度的跟到 M/M，无进度的用默认上限。"""
    total = progress_total(row.get("title"))
    if total <= 0:
        return max_per_task
    return max(max_per_task, min(total, MAX_PER_TASK_PROGRESS))


def pick_target(rows, blacklist, attempts, max_per_task=MAX_PER_TASK):
    """挑下一个可做任务。

    带 (N/M) 进度的行以「N 有没有到 M」为准（截图里 (4/5)、(3/6) 这种
    半截任务必须继续做到满），没进度的行才用次数上限兜底；另加
    「做了 M+2 次进度还不涨就放弃」防死循环。
    """
    for r in rows:
        key = r["key"]
        if key in blacklist:
            continue
        total = progress_total(r.get("title"))
        if total > 0:
            cap = min(total, MAX_PER_TASK_PROGRESS)
            if progress_current(r.get("title")) >= cap:
                continue
            if attempts.get(key, 0) >= cap + MAX_PROGRESS_EXTRA:
                continue
        elif attempts.get(key, 0) >= max_per_task:
            continue
        return r
    return None


def ocr_panel_items(img_path, box=None, scale=None):
    """只识别底部面板区域并降采样（真机实测 23.4s -> 0.6s）。

    面板是固定在屏幕下半部的半屏 sheet，整屏 OCR 有一半算力浪费在背景上；
    裁到 OCR_BOX 再缩到 0.45 倍后【做任务得奖励】【完成得2京豆】【去浏览】
    仍然能读全（28 块 vs 39 块文本，行配对结果一致）。
    返回的坐标已换算回全屏，调用方不需要知道裁剪/缩放。
    """
    if not img_path or not os.path.isfile(img_path):
        return None
    from PIL import Image
    from modules.task5_joy_trip import get_ocr

    im = Image.open(img_path)
    W, H = im.size
    box = box or OCR_BOX
    scale = OCR_SCALE if scale is None else float(scale)
    x0, y0 = max(0, int(box[0])), max(0, int(box[1]))
    x1, y1 = min(W, int(box[2])), min(H, int(box[3]))
    if x1 - x0 < 120 or y1 - y0 < 120:
        # 换了分辨率 / box 不合身：退回整屏下半部，别把整轮任务搞崩
        x0, y0, x1, y1 = 0, OCR_CROP_TOP, W, H
    crop = im.crop((x0, y0, x1, y1))
    if scale != 1.0:
        crop = crop.resize((max(1, int(crop.size[0] * scale)),
                            max(1, int(crop.size[1] * scale))))
    path = img_path[:-4] + "_panel.png"
    crop.save(path)

    res = get_ocr().ocr(path, cls=False)
    k = 1.0 / scale
    out = []
    for quad, (txt, _score) in (res[0] if res and res[0] else []):
        xs = [p[0] for p in quad]
        ys = [p[1] for p in quad]
        out.append({
            "text": (txt or "").strip(),
            "cx": int(sum(xs) / 4 * k) + x0,
            "cy": int(sum(ys) / 4 * k) + y0,
            "x1": int(min(xs) * k) + x0,
            "y1": int(min(ys) * k) + y0,
            "x2": int(max(xs) * k) + x0,
            "y2": int(max(ys) * k) + y0,
        })
    return out


def patch_vec(shot, box=None, size=None):
    """把标题条压成 24x8 灰度向量，用于判「面板还在不在」（≈0.15s）。"""
    if not shot or not os.path.isfile(shot):
        return None
    try:
        from PIL import Image
        im = Image.open(shot)
        g = im.crop(box or PATCH_BOX).convert("L").resize(size or PATCH_SIZE)
        return list(g.getdata())
    except Exception:
        return None


def patch_diff(a, b):
    if not a or not b or len(a) != len(b):
        return 999.0
    return sum(abs(x - y) for x, y in zip(a, b)) / float(len(a))


def red_ratio(shot, box):
    """按钮区里「京东红」像素占比：0.3 以上基本就是【去完成】红按钮。"""
    if not shot or not os.path.isfile(shot):
        return 0.0
    try:
        from PIL import Image
        im = Image.open(shot).crop(box)
        px = im.convert("RGB").getdata()
        n = 0
        hit = 0
        for r, g, b in px:
            n += 1
            if r > 170 and g < 110 and b < 110:
                hit += 1
        return hit / float(n or 1)
    except Exception:
        return 0.0


def adb_path():
    """定位 adb（adb exec-out screencap 比 Appium 截图快且不占 session）。"""
    adb = shutil.which("adb")
    if adb:
        return adb
    for env in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        root = os.environ.get(env)
        if root:
            p = os.path.join(root, "platform-tools", "adb.exe")
            if os.path.isfile(p):
                return p
            p = os.path.join(root, "platform-tools", "adb")
            if os.path.isfile(p):
                return p
    return None


def _device_online(adb):
    """adb devices 里有没有一台 state=device 的机器（≈0.3s）。"""
    if not adb:
        return False
    try:
        out = subprocess.check_output([adb, "devices"], stderr=subprocess.STDOUT,
                                      timeout=8)
    except Exception:
        return False
    if not isinstance(out, str):
        out = out.decode("utf-8", "replace")
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            return True
    return False


def _adb_reconnect(adb, wait=REVIVE_ADB_WAIT):
    """USB 偶发掉线：reconnect offline + 等一会儿，比重建 session 便宜得多。"""
    try:
        subprocess.call([adb, "reconnect", "offline"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        timeout=10)
    except Exception:
        pass
    deadline = time.time() + wait
    while time.time() < deadline:
        if _device_online(adb):
            return True
        time.sleep(1.0)
    return False


def _default_shot(ui):
    """真机截图：优先 adb exec-out（0.9s），失败再退回 Appium。

    不做「先删后写」——一轮下来 50+ 次删文件会触发环境的安全守卫
    （SAFE_DELETE_BULK_CONFIRM_REQUIRED，真机 22:04 那次就是这么被打断的）。
    直接截断重写，再用 PNG 头 + 文件大小校验这一帧是不是真的。
    """
    path = SHOT_PATH
    adb = adb_path()
    if adb:
        try:
            with open(path, "wb") as f:
                subprocess.call([adb, "exec-out", "screencap", "-p"],
                                stdout=f,
                                stderr=subprocess.DEVNULL, timeout=12)
        except Exception:
            pass
        if _png_ok(path):
            return path
    try:
        ui.d.get_screenshot_as_file(path)
    except Exception:
        return None
    return path if _png_ok(path) else None


def _png_ok(path):
    try:
        if not os.path.isfile(path) or os.path.getsize(path) < 5000:
            return False
        with open(path, "rb") as f:
            return f.read(8) == b"\x89PNG\r\n\x1a\n"
    except Exception:
        return False


# ---------------- 模块主体 ----------------
class Task14Coupons(BaseModule):
    name = u"领券中心·天天领豆"
    description = (u"京东首页切【特价】→【领券中心】→【天天领豆/领更多】"
                   u"→ 只做带【完成得Y京豆】且按钮为"
                   u"【去浏览/逛一逛/去完成】的任务，每次停留 9~10 秒，"
                   u"循环到列表没有可做任务为止")
    icon = u"\U0001F3AB"

    def __init__(self):
        self.ui = None
        self.log = None
        self.stop = None
        self.expect_panel = False       # 本轮的弹窗是否已经打开过
        self.panel_believed = False     # 上一帧面板是否在场（决定先 OCR 还是先 dump）
        self.ocr_budget = MAX_OCR
        self.ocr_calls = 0
        self.dwell_bonus = 0            # 进度不涨时把停留时间加长
        self.scrolled = False           # 面板列表是否被滑动过（决定要不要回顶）
        self.attempts = {}              # 每个任务已做次数
        self.failures = {}
        self.attempts_since = {}         # 上一整帧之后每个任务做了几次
        self._prev_progress = {}         # 上一整帧的 (key -> N)
        self.panel_ref = None            # 面板标题条像素参照
        self._verify_hit = False
        self.revives = 0                 # 已重连次数
        self._dead = False               # Appium 彻底不可用：整个模块转纯 adb

    # ---------- 基础封装 ----------
    def _say(self, msg, level="INFO"):
        if self.log is not None:
            self.log.write_log(msg, level)

    def _stopped(self):
        return self.stop is not None and self.stop.is_set()

    def _revive(self):
        """uiautomator2 instrumentation 崩了（ECONNREFUSED 8201）时重建 session。

        真机实测两个坑：
        1. 手机掉 usb 后 create session 会干等 20s 才报「找不到设备」，
           连试 8 次就是 160s 白扔 —— 先用 adb devices 探活，断了立刻退。
        2. 重连也救不回来时，继续在每个探针里重试只会把整轮时间吃光，
           所以整轮最多 2 次，之后置 _dead 让上层快速收尾。
        """
        if self._dead:
            return False
        if self.revives >= MAX_REVIVE:
            self._dead = True
            self._say(u"Appium 重连 %d 次仍不可用，收尾" % self.revives, "WARN")
            return False
        adb = adb_path()
        if adb and not _device_online(adb):
            self._say(u"adb 里没有设备（USB 掉线？），等 %.0fs 看能不能回来"
                      % REVIVE_ADB_WAIT, "WARN")
            if not _adb_reconnect(adb):
                self._dead = True
                self._say(u"手机已断开：请重新插 USB / 确认「允许 USB 调试」，"
                          u"再点一次运行", "ERROR")
                return False
            self._say(u"adb 已恢复，继续重建 session", "WARN")
        self.revives += 1
        try:
            d = driver.get_driver()
        except Exception as e:
            self._say(u"重连 Appium 失败：%s" % e, "WARN")
            return False
        self.ui.d = d
        self.ui.invalidate()
        self._say(u"Appium session 已重建（第 %d 次），继续跑" % self.revives, "WARN")
        return True

    def _snap(self):
        if self._dead:
            return "other", []
        self.ui.invalidate()
        xml = self.ui.source(fresh=True)
        if not xml and self._revive():
            xml = self.ui.source(fresh=True)
        nodes = self.ui.nodes(xml) if xml else []
        return classify(nodes), nodes

    def _back(self, pause=1.0):
        try:
            self.ui.back(pause=pause)
        except Exception:
            if self._revive():
                try:
                    self.ui.back(pause=pause)
                except Exception:
                    pass

    def _tap(self, b, pause=1.0, settle=None):
        # b 来自 XML/OCR，已经是设备像素，不再 sx/sy 缩放
        self.ui.adb_tap(center(b), pause=pause, settle=settle)

    def _find_text(self, text, nodes=None, x_min=None, x_max=None,
                   y_min=None, y_max=None, clickable=None, exact=True):
        if nodes is None:
            _, nodes = self._snap()
        want = norm(text)
        for n in nodes:
            t = norm(n.get("text"))
            hit = (t == want) if exact else (want in t)
            if not hit:
                continue
            if clickable is not None and bool(n.get("clickable")) != clickable:
                continue
            b = n.get("bounds")
            if not valid(b):
                continue
            if (x_min is not None and b[0] < x_min) or \
               (x_max is not None and b[0] > x_max) or \
               (y_min is not None and b[1] < y_min) or \
               (y_max is not None and b[1] > y_max):
                continue
            return tuple(b)
        return None

    def _clickable_container(self, b, nodes):
        """H5 文本节点常不可点，取包住它的最小可点容器。"""
        cx, cy = center(b)
        hits = []
        for n in nodes:
            nb = n.get("bounds")
            if not n.get("clickable") or not valid(nb):
                continue
            if not (nb[0] <= cx <= nb[2] and nb[1] <= cy <= nb[3]):
                continue
            w, h = nb[2] - nb[0], nb[3] - nb[1]
            if w <= 400 and h <= 400:
                hits.append((w * h, tuple(nb)))
        if not hits:
            return None
        hits.sort()
        return hits[0][1]

    def _scroll(self, spec, pause=1.6):
        x1, y1, x2, y2 = spec
        self.ui.adb_swipe(self.ui.sx(x1), self.ui.sy(y1),
                          self.ui.sx(x2), self.ui.sy(y2), SWIPE_MS)
        self.ui.sleep(pause)      # 滑动有惯性，0.8s 就读帧会抓到中间态
        self.ui.invalidate()

    def _scroll_up(self):
        self.scrolled = True
        self._scroll(SWIPE_UP)

    def _scroll_down(self):
        self._scroll(SWIPE_DOWN)

    # ---------- OCR 主通道 ----------
    def _warm_ocr(self):
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

    def _ocr(self, box=None, scale=None, shot=None):
        """截一帧并识别指定区域，返回 OCR 块或 None（失败）。"""
        if self.ocr_budget <= 0:
            return None
        self.ocr_calls += 1
        self.ocr_budget -= 1
        t0 = time.time()
        try:
            path = shot or (SHOT_HOOK(self.ui) if SHOT_HOOK
                            else _default_shot(self.ui))
            if OCR_HOOK:
                return OCR_HOOK(path)
            if not path:
                return None
            res = ocr_panel_items(path, box, scale)
            self._say(u"OCR %s 块=%d 用时 %.1fs"
                      % (u"标题条" if box == OCR_TITLE_BOX else u"面板",
                         len(res or []), time.time() - t0), "DEBUG")
            return res
        except Exception as e:
            self._say(u"OCR 失败：%s" % e, "WARN")
            try:
                path = SHOT_HOOK(self.ui) if SHOT_HOOK else _default_shot(self.ui)
                from modules.task5_joy_trip import ocr_items
                return ocr_items(path, crop_top=OCR_CROP_TOP)
            except Exception:
                return None

    def _shot(self):
        return SHOT_HOOK(self.ui) if SHOT_HOOK else _default_shot(self.ui)

    def _panel_there(self, shot=None):
        """面板在不在：像素补丁比对（≈1.0s），没有参照时退化为标题条 OCR。

        面板头部（做任务得奖励 / 每日最高可领1000京豆 / 我的奖励）是静态的，
        和「面板不在时那块背景」差得很远，比 OCR 便宜一倍。
        注入 SHOT_HOOK/OCR_HOOK 的离线回归走 OCR 通道，保证可复现。
        """
        shot = shot or self._shot()
        if shot is None:
            return None
        if OCR_HOOK is not None or self.panel_ref is None:
            items = self._ocr(OCR_TITLE_BOX, OCR_TITLE_SCALE, shot=shot)
            if items is None:
                return None
            return ocr_panel_visible(items)
        return patch_diff(patch_vec(shot), self.panel_ref) < PANEL_DIFF_MAX

    def _panel_frame(self):
        """整块面板 OCR：返回 {'panel','items','rows','sig'}，None=识别失败。"""
        shot = self._shot()
        items = self._ocr(shot=shot)
        if items is None:
            return None
        if not ocr_panel_visible(items):
            return {"panel": False, "items": items, "rows": [], "sig": ()}
        self.panel_ref = patch_vec(shot)
        return {"panel": True, "items": items,
                "rows": parse_ocr_rows(items), "sig": ocr_sig(items)}

    def _probe(self, panel_first=None, force_xml=False):
        """统一读帧：面板在场时只走截图 OCR（≈1.6s），不 dump XML。

        返回 {'state','rows','nodes','sig','src'}；rows 永远是「可做任务」。
        """
        if panel_first is None:
            panel_first = self.expect_panel and self.panel_believed
        tried_ocr = bool(panel_first and not force_xml)
        if tried_ocr:
            f = self._panel_frame()
            if f and f["panel"]:
                self.panel_believed = True
                return {"state": "panel", "rows": f["rows"], "nodes": [],
                        "sig": f["sig"], "src": "ocr"}
        state, nodes = self._snap()
        sig = panel_sig(nodes)
        if state == "panel":
            self.panel_believed = True
            return {"state": "panel", "rows": parse_rows(nodes),
                    "nodes": nodes, "sig": sig, "src": "xml"}
        if (state == "center" and self.expect_panel
                and not force_xml and not tried_ocr):
            # XML 说 center，但面板可能不进无障碍树：补一次 OCR 判定（≈1.6s）
            f = self._panel_frame()
            if f and f["panel"]:
                self.panel_believed = True
                return {"state": "panel", "rows": f["rows"], "nodes": nodes,
                        "sig": f["sig"], "src": "ocr"}
        self.panel_believed = False
        return {"state": state, "rows": [], "nodes": nodes,
                "sig": sig, "src": "xml"}

    # ---------- 入口链路 ----------
    def _clear_float(self):
        """关掉「恭喜获得 ¥15」浮层：按参考坐标点 X，再 back 兜底。"""
        for k in range(3):
            state, _ = self._snap()
            if state != "float":
                return True
            x, y = FLOAT_CLOSE_XY
            self.ui.adb_tap((self.ui.sx(x), self.ui.sy(y)), pause=1.0)
            self.ui.sleep(1.0)
            state2, _ = self._snap()
            if state2 != "float":
                self._say(u"浮层已关闭（点 X，第 %d 次）" % (k + 1))
                return True
            self._back(pause=1.0)
            self.ui.sleep(0.8)
        self._say(u"浮层未能关闭，交给入口状态机恢复", "WARN")
        return self._snap()[0] != "float"

    def _top_tab(self, nodes):
        return self._find_text(TAB_TEJIA, nodes, x_max=250, y_max=260)

    def _coupon_tab(self, nodes):
        b = self._find_text(TAB_COUPON, nodes, x_min=700,
                            y_min=300, y_max=650)
        if not b:
            return None
        return self._clickable_container(b, nodes) or b

    def _find_entry(self, nodes):
        """找【天天领豆】卡片：整卡是 Button，文案是【更多任务】/【领更多】。

        y 不要再卡死 600~1400：领券中心页偶发多插一行金刚区或更高的券 banner，
        实测同一天那张卡被顶到 y≈1685，卡死区间会让状态机静默空转。
        """
        for want in ENTRY_TEXTS:
            b = self._find_text(want, nodes, y_min=300, x_max=460,
                                clickable=True)
            if b:
                return b
        for want in ENTRY_TEXTS:
            b = self._find_text(want, nodes, y_min=300, x_max=460,
                                clickable=False)
            if b:
                return self._clickable_container(b, nodes) or b
        return None

    def _tap_entry(self, b):
        """整张卡片是一个 Button，【领更多】在底部，点下缘更稳。"""
        x = (b[0] + b[2]) // 2
        y = b[3] - 48
        if y <= b[1]:
            y = (b[1] + b[3]) // 2
        self.ui.adb_tap((x, y), pause=1.0)

    def _reach_center(self):
        """状态机：不管当前停在哪，用最短路径回到【领券中心】底页。"""
        for step in range(MAX_ENTER_STEPS):
            if self._stopped():
                return False
            state, nodes = self._snap()
            if state in ("center", "panel"):
                return True
            if state == "verify":
                self._say(u"停在【京东验证】风控页，需人工点掉", "WARN")
                return False
            if state == "float":
                self._clear_float()
                continue
            if state == "landing":
                self._say(u"停在商品落地页，back 回频道页")
                self._back(pause=1.2)
                self.ui.sleep(0.8)
                continue
            if state == "home":
                b = self._top_tab(nodes)
                if b:
                    self._say(u"点顶部一级 tab【特价】%s" % (b,))
                    self._tap(b, pause=1.4, settle=0)
                    self.ui.sleep(0.6)
                    continue
            elif state == "tejia":
                b = self._coupon_tab(nodes)
                if b:
                    self._say(u"点二级 tab【领券中心】%s" % (b,))
                    self._tap(b, pause=1.4, settle=0)
                    self.ui.sleep(0.8)
                    continue
            self.ui.sleep(0.8)
            if step % 3 == 2:
                self._back(pause=1.0)
        self._say(u"连续 %d 步没回到【领券中心】" % MAX_ENTER_STEPS, "WARN")
        return False

    def _open_panel(self):
        """保证【做任务得奖励】面板在场。

        v2 里面板判定走「截图 + OCR」，所以「面板其实开着」的帧会立刻
        返回 True —— 以前这种帧会被当成 center，然后把面板后面的
        【领更多】再点一次，越点越乱。
        """
        last_entry, same_entry = None, 0
        miss = 0
        for k in range(MAX_OPEN_STEPS):
            if self._stopped():
                return False
            p = self._probe()
            state = p["state"]
            self._say(u"入口第 %d 步：state=%s src=%s rows=%d"
                      % (k + 1, state, p["src"], len(p["rows"])), "DEBUG")
            if state == "panel":
                self.expect_panel = True
                self.panel_believed = True
                return True
            if state == "verify":
                self._say(u"停在【京东验证】风控页，停止", "WARN")
                return False
            if state == "float":
                self._clear_float()
                continue
            if state in ("home", "tejia", "landing", "other"):
                if not self._reach_center():
                    return False
                continue
            # center：点【天天领豆 - 领更多 / 更多任务】
            b = self._find_entry(p["nodes"])
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
                continue
            if b == last_entry:
                same_entry += 1
            else:
                last_entry, same_entry = b, 1
            if same_entry >= 3:
                self._say(u"同一处【领更多】连点 3 次都没弹窗，"
                          u"先 back 出嵌套页再重进", "WARN")
                self._back(pause=1.2)
                self.ui.sleep(0.8)
                last_entry, same_entry = None, 0
                continue
            self._say(u"点【领更多/更多任务】%s（第 %d 次）" % (b, k + 1))
            self._tap_entry(b)
            self.expect_panel = True
            self.panel_believed = True
            self.scrolled = False
            self.ui.sleep(0.9)
        self._say(u"连续 %d 次没打开任务弹窗" % MAX_OPEN_STEPS, "WARN")
        return False

    def _to_top(self):
        """面板列表滑回顶部。只在真滑过之后才做，避免把半屏 sheet 拖关掉。"""
        if not self.scrolled:
            return
        self._say(u"先把任务列表滑回顶部再扫")
        prev = None
        for _ in range(MAX_TO_TOP):
            if self._stopped():
                return
            p = self._probe(panel_first=True)
            if p["state"] != "panel":
                return
            if p["sig"] == prev:
                break
            prev = p["sig"]
            self._scroll_down()
        self.scrolled = False

    # ---------- 做任务 ----------
    def _left_panel(self, tries=3):
        """点完任务按钮后确认已经离开面板。

        True=已离开 / False=面板还在（点击被吞）/ None=判不出来。
        先等 0.35s 再截图：截图本身要 0.95s，等于替页面争取了近 1.3s 跳转时间，
        比「死等 1s 再截」便宜一半（真机 v2 每任务在这里花 2.2s）。
        """
        self.ui.sleep(0.35)
        for i in range(tries):
            there = self._panel_there()
            if there is None:
                return None
            if not there:
                return True
            self.ui.sleep(0.9 if i < 2 else 1.4)
        return False

    def _row_ready(self, row, shot=None):
        """轻量校验：这一行的红按钮还在不在原坐标（≈1.0s）。

        整帧 OCR 要 8~19s，每个任务都重来太慢；但做满的行会被换成
        【已完成】灰按钮、后面的行整体上移，按缓存坐标点就会点到别的任务。
        红按钮的红色占比是最便宜的「还在原位」判据；拿不准时再退回整行 OCR。
        """
        b = row.get("bounds")
        if not valid(b):
            return False
        shot = shot or self._shot()
        if shot is None:
            return True
        there = self._panel_there(shot)
        if there is False:
            return False
        if OCR_HOOK is None:
            box = (max(0, b[0] - 30), b[1],
                   min(self.ui.W, b[2] + 30), b[3])
            for i in range(2):
                if red_ratio(shot, box) >= RED_MIN:
                    return True
                if i == 0:
                    self.ui.sleep(0.6)
                    shot = self._shot()
                    if shot is None:
                        return True
            self._say(u"这一行的红按钮不见了（%s），重读整帧" % row["key"],
                      "DEBUG")
            return False
        # 离线回归：走 OCR 通道，按 key 精确比对
        items = self._ocr((40, max(0, b[1] - 45), min(self.ui.W, 1065),
                           min(self.ui.H, b[1] + 135)), 1.0, shot=shot)
        if items is None:
            return True
        nodes = [{"text": it.get("text", ""),
                  "bounds": (int(it["x1"]), int(it["y1"]),
                             int(it["x2"]), int(it["y2"])),
                  "clickable": True, "class": "TextView"}
                 for it in items]
        for r in _rows_from_nodes(nodes):
            if r["key"] == row["key"]:
                return True
        self._say(u"这一行已变化（%s 不在原位），重读整帧" % row["key"], "DEBUG")
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

        全程只用「截图 + 像素」，一次 page_source 都不读：
        真机 21:5x 那次就是在这里 dump XML 把 uiautomator2 server 打崩的，
        之后要重建 session，一个任务赔掉 300s。
        """
        pt = row.get("center") or center(row["bounds"])
        self.ui.adb_tap(pt, pause=0.4, settle=0)
        left = self._left_panel()
        if left is None:
            # 像素判不出来就再看一帧；仍判不出就按「已离开」走，
            # 真正的成功判据是停留结束 back 回来时面板还在。（不读 XML）
            left = not (self._panel_there() is True)
        if not left:
            self._say(u"点了按钮页面没动，本次点击可能被吞", "WARN")
            return False, None
        secs = self._dwell()
        self._say(u"任务【%s】%s 按钮【%s】%s，停留 %ds"
                  % (row["title"] or row["key"], row["reward"],
                     row["text"], pt, secs))
        if not self.ui.sleep(secs):
            return False, None
        self._back(pause=0.5)
        shot = None
        for _ in range(3):
            shot = self._shot()
            there = self._panel_there(shot)
            if there is None:
                break
            if there:
                self.panel_believed = True
                return True, shot
            self.ui.sleep(0.7)
        self._say(u"浏览后没回到任务弹窗，重建入口", "WARN")
        self.panel_believed = False
        return self._open_panel(), None

    def _refresh_panel(self):
        """点 X 关掉再重开任务面板，让服务端重新下发任务池。

        真机实测 back 关不掉这个半屏 sheet（只会把背景页一起退掉），
        必须点右上角 X。
        """
        if self._refreshed:
            return False
        self._refreshed = True
        self._say(u"列表里已没有可做任务，关掉弹窗重开刷新一次任务池")
        self.ui.adb_tap(PANEL_CLOSE_XY, pause=0.8)
        self.ui.sleep(0.8)
        self.expect_panel = False
        self.panel_believed = False
        self.panel_ref = None
        for _ in range(2):
            if not self._panel_there():
                break
            self._say(u"X 没关掉，再点一次", "WARN")
            self.ui.adb_tap(PANEL_CLOSE_XY, pause=0.8)
            self.ui.sleep(0.8)
        return self._open_panel()

    def _do_tasks(self):
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
                    shot = None
                    while left > 0 and not self._stopped() and total < MAX_TASKS:
                        if not self._row_ready(row, shot):
                            break          # 行上移了，跳出重读整帧
                        ok, shot = self._do_one(row)
                        self.attempts[key] = self.attempts.get(key, 0) + 1
                        self.attempts_since[key] = \
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
        if self._dead:
            self._say(u"手机/Appium 中途断开，本轮提前结束（已浏览 %d 次）。"
                      u"重新插好 USB 后再跑一次即可接着做。" % total, "ERROR")
        if total >= MAX_TASKS:
            self._say(u"已达总浏览次数上限 %d，收尾" % MAX_TASKS, "WARN")
        return total

    def _report_left(self, rows):
        """收尾时说清楚还剩什么：让「没做完」看得见，而不是静默结束。"""
        left = []
        for r in rows or []:
            total = progress_total(r["title"])
            cur = progress_current(r["title"])
            if total > 0 and cur < total:
                left.append(u"%s(%d/%d)" % (PROGRESS_RE.sub(u"", r["title"]),
                                            cur, total))
            elif total == 0:
                left.append(PROGRESS_RE.sub(u"", r["title"]))
        if not left:
            self._say(u"收尾检查：本屏已没有【完成得Y京豆】任务")
            return
        self._say(u"收尾检查：本屏还有 %d 个京豆任务未做满：%s"
                  % (len(left), u" / ".join(left[:8])), "WARN")

    # ---------- 入口 ----------
    def run(self, log, stop_event):
        self._warm_ocr()
        ui = JDUI(driver.get_driver(), log, stop_event)
        self.ui = ui
        self.log = log
        self.stop = stop_event
        self.expect_panel = False
        self.panel_believed = False
        self.ocr_budget = MAX_OCR
        self.ocr_calls = 0
        self.dwell_bonus = 0
        self.scrolled = False
        self.attempts = {}
        self.failures = {}
        self.attempts_since = {}
        self._prev_progress = {}
        self.panel_ref = None
        self._verify_hit = False
        self._say(u"设备分辨率 %dx%d" % (ui.W, ui.H))
        if not ui.restart_to_home():
            self._say(u"冷启动回首页失败，走 goto_home", "WARN")
            ui.goto_home()
        if not self._reach_center():
            log.done(u"领券中心 未完成（没能进入【领券中心】）")
            return
        if not self._open_panel():
            log.done(u"领券中心 未完成（没能打开任务弹窗）")
            return
        total = self._do_tasks()
        log.done(u"领券中心 完成 %d 次【完成得Y京豆】浏览任务（OCR %d 次）"
                 % (total, self.ocr_calls))
