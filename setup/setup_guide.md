# 环境配置指南

## 1. 安装 Android Platform-Tools (adb)

1. 下载 [platform-tools](https://developer.android.com/studio/releases/platform-tools)
2. 解压到 `D:\Android\platform-tools`
3. 添加到系统 PATH：
   - 设置 → 系统 → 关于 → 高级系统设置 → 环境变量
   - 编辑 `Path` 变量，添加 `D:\Android\platform-tools`
4. 验证：打开新终端执行 `adb devices`

## 2. 手机设置（小米/红米 MIUI）

### USB 调试
1. 设置 → 我的设备 → 全部参数 → 连续点击 MIUI 版本 7 次 → 开启开发者模式
2. 设置 → 更多设置 → 开发者选项 → USB 调试 → 开启
3. 连接 USB 数据线到电脑，手机上授权

### 关闭 MIUI 优化（可选）
- 开发者选项 → 启用 MIUI 优化 → 关闭（解决一些UI定位问题）

### 防止后台被杀死
- 最近任务 → 长按京东 App → 锁定
- 设置 → 应用设置 → 应用管理 → 京东 → 省电策略 → 无限制

### 禁止自动锁屏（运行期间）
- 设置 → 显示 → 休眠 → 30分钟 或 永不

## 3. 安装 Appium Driver

```bash
# 安装 uiautomator2 driver
npx appium driver install uiautomator2

# 验证 driver 已安装
npx appium driver list
```

## 4. 验证环境

```bash
# 检查 adb
adb devices
# 输出应有: xxxxxx device

# 检查 JD App 已安装
adb shell pm list packages | grep jingdong

# 启动 Appium 服务（新开终端）
npx appium

# 回到项目目录运行
cd D:/AI_work/JDUItest
python app.py
```

浏览器打开 http://localhost:5000

## 5. 获取京东 App Activity（如果需要）

```bash
# 在手机上打开京东App，然后执行：
adb shell dumpsys window windows | grep -E mCurrentFocus
```

## 常见问题

| 问题 | 解决方法 |
|------|---------|
| `adb: command not found` | 未安装 platform-tools 或未添加到 PATH |
| `no devices/emulators found` | 检查 USB 线、手机是否授权调试 |
| Appium 连接失败 | 确认 `npx appium` 正在运行 |
| MIUI 弹窗遮挡 | 已内置自动关闭逻辑 |
| JD App 开屏广告 | 已内置跳过逻辑 |
