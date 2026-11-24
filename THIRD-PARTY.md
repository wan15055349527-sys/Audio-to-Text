# 第三方组件和模型

`licenses/` 收录当前构建环境中 Python 包随附的许可文件及声明。以下链接提供上游源代码或模型来源。

- [OpenAI Whisper](https://github.com/openai/whisper) 与 [Systran CTranslate2 转换版 Base](https://huggingface.co/Systran/faster-whisper-base)。Whisper 的代码及模型权重以 MIT 许可发布。[faster-whisper](https://github.com/SYSTRAN/faster-whisper) 与 [CTranslate2](https://github.com/OpenNMT/CTranslate2) 提供本地推理。
- [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) 与 [Paraformer 小模型转换版](https://huggingface.co/csukuangfj/sherpa-onnx-paraformer-zh-small-2024-03-09)。该转换仓库指向 [ModelScope 源模型](https://www.modelscope.cn/models/crazyant/speech_paraformer_asr_nat-zh-cn-16k-common-vocab8358-onnx/summary)。公开再分发前，应核对这个模型版本的上游权重条款。
- [PyAV](https://github.com/PyAV-Org/PyAV) 使用 [FFmpeg](https://ffmpeg.org/)，用于媒体解码和生成试听音轨。上游源代码及构建说明可从各自仓库取得。
- [pywebview](https://github.com/r0x0r/pywebview)、[Python.NET](https://github.com/pythonnet/pythonnet) 与 [Microsoft Edge WebView2](https://developer.microsoft.com/microsoft-edge/webview2/) 提供窗口和系统文件对话框。程序通过 [PyInstaller](https://github.com/pyinstaller/pyinstaller) 构建。
- 示例为本项目编写的文本与 Windows 中文合成朗读。

