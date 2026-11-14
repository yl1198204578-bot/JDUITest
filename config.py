import os

APPIUM_HOST = "http://127.0.0.1:4723"
DEVICE_NAME = "Android"
PLATFORM_VERSION = ""
UDID = ""
JD_PACKAGE = "com.jingdong.app.mall"
JD_ACTIVITY = ".MainFrameActivity"
FLASK_HOST = "0.0.0.0"
FLASK_PORT = 5000
FLASK_DEBUG = False


def get_capabilities():
    caps = {
        "platformName": "Android",
        "appium:deviceName": DEVICE_NAME,
        "appium:automationName": "UiAutomator2",
        "appium:appPackage": JD_PACKAGE,
        "appium:appActivity": JD_ACTIVITY,
        "appium:noReset": True,
        "appium:fullReset": False,
        "appium:ensureWebviewsHavePages": True,
        "appium:newCommandTimeout": 600,
        "appium:uiautomator2ServerInstallTimeout": 30000,
        "appium:adbExecTimeout": 120000,
    }
    if UDID:
        caps["appium:udid"] = UDID
    if PLATFORM_VERSION:
        caps["appium:platformVersion"] = PLATFORM_VERSION
    return caps
