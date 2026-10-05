# 第三方来源与许可

听译桌面应用的原创代码以 GPL-3.0-or-later 发布，完整文本见根目录 LICENSE。依赖、上游源码及模型权重分别遵循各自许可，应用许可不替代模型的使用条件。本源码仓库不包含第三方安装包、模型权重、FFmpeg 二进制、语料或任何用户会议材料。

| 组件 | 来源与许可 | 本仓库中的处理 |
|---|---|---|
| WhisperLiveKit 0.2.26 | [QuentinFuxa/WhisperLiveKit](https://github.com/QuentinFuxa/WhisperLiveKit)，Apache-2.0 | 安装脚本获取固定 commit `363e4f6d029694d9c81ae548beddd9d3c88a3637`，完整上游许可和 NOTICE 保留在获取的源码内；许可证副本见 `licenses/WhisperLiveKit-Apache-2.0.txt`。外围兼容层在 `app/` 中，上游文件不被覆盖。 |
| PyQt6 / Qt | [Riverbank PyQt](https://www.riverbankcomputing.com/software/pyqt/)，PyQt GPLv3 或商业许可；Qt 依组件适用各自许可 | 本项目采用 GPL 相容的开源发布方式。通过原发行包安装，保留包内版权和许可；不把 PyQt 当作 LGPL 发行。 |
| Whisper / faster-whisper | [OpenAI Whisper](https://github.com/openai/whisper)、[SYSTRAN/faster-whisper](https://github.com/SYSTRAN/faster-whisper)，MIT | 通过上游与依赖包使用；不在此重新分发权重。 |
| CTranslate2 / NLLW | [OpenNMT/CTranslate2](https://github.com/OpenNMT/CTranslate2)、[NoLanguageLeftWaiting](https://github.com/QuentinFuxa/NoLanguageLeftWaiting)，MIT | 从项目原发行渠道安装，保留各包许可。 |
| PyAudioWPatch | [s0d3s/PyAudioWPatch](https://github.com/s0d3s/PyAudioWPatch)，MIT | 用于 Windows WASAPI 回环与麦克风采集。 |
| imageio-ffmpeg / FFmpeg | [imageio/imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg)，BSD-2-Clause；具体 FFmpeg 构建依其 LGPL/GPL 配置 | 安装时由发行包获取；此仓库不附带 FFmpeg 二进制。另行分发二进制前应核对对应构建和源码义务。 |
| openpyxl / et-xmlfile | [openpyxl](https://openpyxl.readthedocs.io/)及其发行包，MIT | 用于 XLSX 词库；保留依赖包许可。 |
| Python / PyTorch / 其他 Python 包 | 各项目和原发行包；参考 `requirements-public.txt` 与 `requirements.lock.txt` | 不把特定机器的 CUDA 环境当作所有机器的许可或运行保证。 |

## 模型单独下载、单独适用许可

| 可选模型 | 原始来源 | 使用条件 |
|---|---|---|
| Whisper / CT2 Whisper | [OpenAI Whisper](https://github.com/openai/whisper)、[Systran](https://huggingface.co/Systran) | 模型页及原项目许可；在模型管理中由使用者主动获取。 |
| NLLB-200 distilled 600M | [Meta 模型卡](https://huggingface.co/facebook/nllb-200-distilled-600M)，CC-BY-NC-4.0 | 具有非商业限制。转换版 [JustFrederik](https://huggingface.co/JustFrederik/nllb-200-distilled-600M-ct2-int8) 固定 revision `302d78f00e6fdb50a1064059df7c392b735e9d05` 仍遵循原权重许可。`Download-NLLB.ps1` 需要显式选择，环境安装或修复不自动下载。 |
| NVIDIA Streaming Sortformer v2 | [模型卡](https://huggingface.co/nvidia/diar_streaming_sortformer_4spk-v2)，CC-BY-4.0 | 另需隔离 NeMo 环境；保留模型许可与归属。未下载时该功能不能使用。 |
| LM Studio 中的文本模型 | 使用者选择的各模型原始来源 | LM Studio 仅提供模型服务入口，各权重的许可分别核对。 |

## 界面与测试材料

界面、图标及淡云/叶影背景由本项目绘制，不包含 Live Subtitles 或 LiveTranslate 的程序、源码及资源。公开截图使用合成字幕和演示模型状态，不含真实会议、联系人、凭据或本机个人配置。

原验收使用过 LibriSpeech（CC-BY-4.0，Vassil Panayotov 等）与 Google FLEURS（CC-BY-4.0），本源码包不包含这些音频、清单或测试日志。公开测试采用合成数据，安装后需要真实音频测试时应自行取得并保留对应语料许可。
