# 已下载英文教学测试片：MIT OCW

日期：2026-11-07。用户同意使用可下载、可改编的英文教学视频替代 TED 后，选择了 MIT OCW 的真实课堂片段。

后续进展：已经完成本地 ASR，见 [真实转写与人工核对入口](B-ASR-review-20261107.md)。下文“未运行 ASR”为下载验证阶段的历史状态；自动说话人区分和人工正确性核验仍未完成。

## 素材与许可

- 标题：Lecture 1: What is Computation?
- 课程：6.0001 Introduction to Computer Science and Programming in Python, Fall 2016。
- 讲师：Dr. Ana Bell；发布方：Massachusetts Institute of Technology / MIT OpenCourseWare。
- [官方课程视频页](https://ocw.mit.edu/courses/6-0001-introduction-to-computer-science-and-programming-in-python-fall-2016/resources/lecture-1-what-is-computation/)。页面的 download the video 指向 Internet Archive 原片。
- 原片链接：https://archive.org/download/MIT6.0001F16/MIT6_0001F16_Lecture_01_300k.mp4
- [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/)，课程页许可链接与原片内嵌版权元数据一致。复用需署名、注明修改、非商业；发布改编内容需按相同许可。参见 [MIT 复用说明](https://mitocw.zendesk.com/hc/en-us/articles/5093047407771-Reusing-MIT-OpenCourseWare-Content)。

这是 MIT 教学视频，不是 TED。只截取原课约 00:01:00–00:01:45 并转码；没有下载保存完整课程。名义 45 秒，实际视频流 45.011633 秒（约 45.012 秒），帧边界产生的细小差异已保留，没有伪写成精确 45.000 秒。

## 本机文件

- [测试视频](../media/mit_ocw_6_0001_lecture1/mit_lecture1_0060_0105.mp4)
- [配套署名与许可说明](../media/mit_ocw_6_0001_lecture1/ATTRIBUTION.txt)
- [实际素材登记](../media/mit_ocw_6_0001_lecture1/asset-register.csv)
- [下载与裁剪记录](../media/mit_ocw_6_0001_lecture1/acquisition.json)
- [基础验证记录](../media/mit_ocw_6_0001_lecture1/validation.json)
- [识别用 WAV](../jobs/B-MIT-sample-20261107/prepared/audio.wav)
- [媒体处理报告](../jobs/B-MIT-sample-20261107/prepared/media-report.json)

media/ 与 jobs/ 已忽略，文件保留在本地，不自动上传到 GitHub。将视频发给队友时同时附带 ATTRIBUTION.txt，不能仅传脱离署名的片段。

## 实际完成与限制

MP4 为 H.264 视频 + AAC 双声道音频，1,452,225 字节。抽帧解码成功，画面为讲师在黑板前授课。源文件 SHA-256：`9d1df44862a0e0abe7cd3d561e768c84ea17e47022b07c7f33a08c544a236760`。

已运行独立本地提取工具，生成 16000 Hz 单声道、16-bit PCM WAV，共 720192 帧，匹配工具规范中的 45012 ms。音频峰值为 23212，RMS 为 3262.58（PCM16 单位），不是全静音。提取耗时约 0.472 秒；网络读取与裁剪约 12.477 秒。网络传输总字节数 unknown，不能用最终片段文件大小代替下载流量。

这里只验证媒体读取、音频存在与格式；未人工听写、未进行 ASR、词时间对齐或说话人识别，不能宣称识别准确率或人工同步验收通过。无付费模型/API 调用，DeepSeek 未参与。

## 后续测试命令

在仓库根目录执行：

```powershell
.\.venv\Scripts\python.exe tools/b_media.py inspect --input .\media\mit_ocw_6_0001_lecture1\mit_lecture1_0060_0105.mp4
```

下载裁剪脚本为 tools/fetch_mit_sample.py，已有文件时拒绝覆盖。后续 ASR 使用上面的 WAV，样片局部时间 0 秒对应原课约 60 秒；若将结果映射回原课，需要加回 60000 ms，不能与样片时间混用。
