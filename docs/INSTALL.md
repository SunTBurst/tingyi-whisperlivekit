# Windows 安装与首次启动

当前公开仓库提供源码，面向已安装 Git for Windows 与 [uv](https://docs.astral.sh/uv/) 的 Windows 用户。脚本使用 uv 管理 Python 3.12，并从官方 WhisperLiveKit 仓库检出固定提交 `363e4f6d029694d9c81ae548beddd9d3c88a3637`。首次安装需要联网获取源代码和 Python 依赖。

在仓库目录打开 PowerShell，运行：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\Setup.ps1
```

脚本创建 `.venv`、安装桌面直接依赖，并按 WhisperLiveKit 的 `cpu` extra 解析其依赖，再检查依赖一致性。它不会下载语音或翻译模型。`cpu` extra 表示所选依赖组；实际安装的 Torch wheel 仍受 uv 源配置、平台和解析结果影响，不能仅凭该 extra 保证安装为 CPU-only wheel。首次启动软件：

```powershell
.\Start.ps1
```

也可双击 `启动听译.vbs`。启动主窗口不要求已有 Whisper 权重，因此可以先查看设置和界面。开始识别前，在“工具 → 模型管理”中显式安装所需的 ASR 模型；模型体积较大，下载耗时与所需磁盘空间随模型而异。当前脚本面向 Windows，但全新环境安装尚未在另一台电脑完成冷启动验收；GPU/CUDA 用户需按本机驱动与硬件单独配置兼容的 Torch wheel。

本地翻译使用 NLLB 权重。NLLB 模型许可为 CC-BY-NC-4.0，仅允许非商业使用并要求署名。阅读[模型卡](https://huggingface.co/facebook/nllb-200-distilled-600M)及许可后，才运行单独下载脚本：

```powershell
.\Download-NLLB.ps1
```

脚本会再次显示许可提醒，并要求输入 `ACCEPT-NONCOMMERCIAL`。也可显式传入 `-AcceptNonCommercialLicense`。`Setup.ps1` 与 `Repair.ps1` 都不会下载这些权重。

修复或补齐同一固定版本的 Python 依赖时运行 `Repair.ps1`。它不会重置设置、记录、已下载权重或已有的正确版本 checkout。若 `upstream` 已存在但提交不同，脚本会停止并保留该目录。

## 边界

- 安装脚本面向 Windows。依赖组合曾在现有环境中完成解析检查，但没有在另一台电脑做完整冷安装；macOS、Linux 和 GPU/CUDA 配置均未由此脚本验证。
- WhisperLiveKit 上游源码会单独检出到 `upstream`，其许可为 Apache-2.0；本应用依赖的 PyQt6 使用 GPLv3 版本。发布许可和第三方许可见仓库根目录的许可证与声明文件。
- 模型权重不包含在源码仓库中。下载前请核对各模型自己的来源、使用条件与许可。
- 应用可在没有权重时打开，但识别、翻译等推理功能须先下载对应模型。
