# AI BOARD 打包、常驻与发布上线指南

## 1. 日常个人常驻与开机自启设置

1. 双击根目录 [`启动桌面看板.bat`](../启动桌面看板.bat) 运行程序。
2. 点击主面板左上方「AI 账户额度」旁的 **`⚙ 设置`** 按钮（或右键右下角系统托盘图标）：
   - 勾选 **`🚀 开机自动启动`**（基于当前用户注册表 `HKCU\...\Run`，无需管理员权限，随时可开关）。
   - 可选勾选 **`开机自启时默认收起为迷你形态`**，电脑开机后会自动静默以高清圆形悬浮球或窄条贴边显示。

## 2. 待办事项防丢失保障机制

- **独立标准数据目录**：所有待办事项、额度配置与窗口位置均自动保存在系统标准用户目录 `%APPDATA%\AIBoard\dashboard_state.json`（即 `C:\Users\<用户名>\AppData\Roaming\AIBoard`），无论电脑重启、程序目录移动还是后续版本覆盖升级，数据都永久保留。
- **双重断电保护**：每次修改待办或配置时，均通过 `os.fsync` 强制物理落盘，并自动维护上一份完好快照 `dashboard_state.json.bak`；同时监听 Windows 关机/注销会话信号主动刷盘。
- **绿色便携模式（可选）**：若需放在 U 盘随身携带，只需在程序同级目录新建一个空文件 `portable.flag`，数据即改为保存在程序目录下的 `data/` 文件夹。

## 3. 如何打包发布供其他用户下载使用

本项目已剔除任何本机硬编码路径，并排除 Anaconda 冗余科学计算库，支持一键打包为免安装 Python 的独立 Windows 应用：

1. 双击运行 [`packaging/打包独立EXE.bat`](./打包独立EXE.bat)。
2. 打包完成后，会生成 `dist\AIBoard\` 目录（内含带高清专属图标的 `AIBoard.exe`）。
3. **分发方式**：
   - **绿色免安装版**：将 `dist\AIBoard` 打包为 `.zip` 发给其他用户，对方解压后双击 `AIBoard.exe` 即可运行（并在设置中一键开启他自己电脑上的 Codex / Antigravity / Claude Code / DeepSeek Harness 与开机自启）。
   - **安装包版（进阶）**：可使用免费工具 **Inno Setup** 将 `dist\AIBoard\` 封装为单文件 `AIBoard_Setup.exe` 安装向导发布到 GitHub Releases 或个人主页。
