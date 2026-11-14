import socket

try:
    from urllib.parse import urlparse
except ImportError:  # Python 2
    from urlparse import urlparse

from appium import webdriver
import config

_driver = None


def _appium_reachable(host, timeout=3):
    """新建 session 前先探端口，避免 selenium 抛出只有 'Message:' 的空异常。"""
    try:
        u = urlparse(host)
        port = u.port or (443 if u.scheme == "https" else 80)
        sock = socket.socket()
        sock.settimeout(timeout)
        try:
            sock.connect((u.hostname or "127.0.0.1", port))
            return True
        finally:
            sock.close()
    except Exception:
        return False


def get_driver():
    global _driver
    if _driver is not None:
        try:
            # Appium 3.9 + 旧客户端下 current_package / current_activity /
            # get_window_size 都会抛 UnknownMethodException，用 page_source 探活。
            _driver.page_source
            return _driver
        except Exception:
            # Session died, create new one
            try:
                _driver.quit()
            except Exception:
                pass
            _driver = None
    
    if not _appium_reachable(config.APPIUM_HOST):
        raise RuntimeError(
            "Appium 服务不可达（%s）。请先启动：appium --address 127.0.0.1 --port 4723，"
            "并确认 adb devices 里设备状态是 device（不是 offline）。"
            % config.APPIUM_HOST)
    try:
        _driver = webdriver.Remote(config.APPIUM_HOST, config.get_capabilities())
    except Exception as e:
        _driver = None
        raise RuntimeError(
            "创建 Appium session 失败（%s: %s）。请检查 Appium 日志、手机 USB 调试授权"
            "与 uiautomator2 驱动。" % (type(e).__name__, e))
    return _driver


def close_driver():
    global _driver
    if _driver:
        try:
            _driver.quit()
        except Exception:
            pass
        _driver = None
