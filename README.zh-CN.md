# hls-vod-audit 中文说明

上传 HLS 点播文件包之前，离线检查缺失分片、初始化文件、清单引用和字节范围越界。
Python 3.11 及以上，无运行时第三方依赖，不联网，不读取媒体内容或加密密钥，不修改输入。

```sh
git clone https://github.com/KanadeK/hls-vod-audit.git
cd hls-vod-audit
python -m pip install .
python examples/check_example.py
hls-vod-audit package/master.m3u8 --format json
```

默认以入口清单所在目录为根边界；多级清单需要引用上级共享分片时，用 `--root`
显式选择整个文件包目录。所有解析后的引用必须位于该边界内。输出包含清单相对路径、
行号、检查代码和时长统计，不包含原始 URI、查询参数或机器绝对路径。

支持主清单、普通 VOD 媒体清单、替代音视频/字幕清单、初始化段、显式和可推导的
分片字节范围、ENDLIST、目标时长和若干协议版本检查。目标时长按最近整数校验，
恰好半数时向上取整。返回码：`0` 支持范围内的结构检查通过，`1` 已发现缺失文件等
缺陷，`2` 检查不完整或输入错误。未知标签、加密、远程地址、带查询或片段的 URI、
LIVE/EVENT 等均不能获得通过结果。

示例中的 `data.bin` 仅用于验证结构，不假装是可播放视频。若本机有支持 libx264 和
lavfi 的 ffmpeg，可运行 `python examples/check_ffmpeg.py --ffmpeg ffmpeg`，生成并解码
MPEG-TS/fMP4 的独立分片和单文件范围四种真实文件包，再验证缺失/截短问题能被检出。

当前版本 0.1.0 不解码或验证关键帧、编码、音画同步、媒体实际时长、CDN/HTTP 行为；
不能保证视频可播放。非空但内部损坏的分片可能通过。文件大小写规则遵循本机文件系统，
部署到大小写敏感主机时应在 Linux 上复核。完整范围与资源上限见 [英文说明](README.md)。

卸载：`python -m pip uninstall hls-vod-audit`。不会创建后台服务或隐藏数据库。
