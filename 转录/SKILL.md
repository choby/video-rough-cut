---
name: 转录
description: 口播视频转录。生成转录结果。触发词：转录、剪口播、处理视频、
---

<!--
input: 视频文件 (*.mp4)
output: 转录JSON、生成转录结果毫秒时间戳驱动
pos: 转录+识别
-->

# 剪口播

> 转录 + 静音识别 → 生成转录结果

## 快速使用

```
用户：转录
用户：剪口播
用户: 帮我剪这个口播视频
用户: 处理一下这个视频
```

## 流程

```
1. 使用extract_audio.py脚本抽取音频
    ↓
2. 使用transcribe.py脚本将音频文件上传至火山引擎转录
    ↓
3. 使用volcengine_result_to_markdown.py将转录 json 转换为 markdown 片段

```

### 抽取音频

执行命令，将 `{video}` 替换为实际视频文件名（不带扩展名）：

```
python3 extract_audio.py {vedio}.mp4 -o audio.wav --codec pcm_s16le --sample-rate 16000 --channels 1 
```
或者

```
python extract_audio.py {vedio}.mp4 -o audio.wav --codec pcm_s16le --sample-rate 16000 --channels 1 
```


### 音频抽取完成后，执行转录命令：

```
python3 transcribe.py audio.wav
```
或者
```python
python transcribe.py audio.wav
```

### 转录完成后，执行以下命令将转录结果转换为 markdown 片段：

```
python3 volcengine_result_to_markdown.py transcribe_result.json
```
或者
```
python volcengine_result_to_markdown.py transcribe_result.json
```


