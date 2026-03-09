# 转录

口播视频转录。生成生成精剪任务清单。触发词：转录、剪口播、处理视频

## 文件清单

| 文件 | 用途 |
|------|------|
| `SKILL.md` | skill 定义（剪口播） |
| `scripts/extract_audio.py` | 音频抽取 |
| `scripts/transcribe.py` | 转录 |
| `scripts/volcengine_result_to_markdown.py` | 转录json 转为markdown |
| `README.md` | 本文件 |

## 依赖

- FFmpeg（`brew install ffmpeg`）

## 输入输出

- **输入**：片段x.md + 原始视频
- **输出**：剪辑后视频 (片段x.mp4)

## 转录结果转 Markdown

基础用法：

```bash
python3 scripts/volcengine_result_to_markdown.py transcribe_result.json 转录.md
```

静音配置从 `scripts/.env` 读取：

```bash
SILENCE_THRESHOLD=500
SILENCE_BOUNDARY=120
```

- `SILENCE_THRESHOLD`：当前句与前后句的间隔大于等于该值时，才视为静音段，单位毫秒。
- `SILENCE_BOUNDARY`：命中静音段后，当前句起止时间向静音区扩展的毫秒数。
