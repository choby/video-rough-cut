# 视频粗剪 skill
本 skill 适用于将长视频粗剪为多个精华片段
------
# 前置条件
- 本项目所使用的转录方式为[火山引擎语音识别](https://www.volcengine.com/product/asr)，需要先注册火山引擎账号，获取 API Key。
- 视频文件抽取的音频文件需要先上传到阿里 OSS 存储桶中，且需要配置好 OSS 访问密钥 ID 和 Secret。
------
# 使用方式
1. 配置环境变量（`/转录/scripts/.env`）
   - `OSS_ACCESS_KEY_ID`：OSS 访问密钥 ID
   - `OSS_ACCESS_KEY_SECRET`：OSS 访问密钥 Secret
   - `OSS_BUCKET`：OSS 存储桶名称
   - `OSS_REGION`：OSS 区域
   - `OSS_ENDPOINT`：OSS 终端节点
   - `OSS_OBJECT_PREFIX`：OSS 对象前缀
   - `OSS_SIGN_SECONDS`：OSS 签名有效期（秒）
   - `VOLCENGINE_API_KEY`：火山引擎 API Key
   - `SILENCE_THRESHOLD`：静音阈值（毫秒）
   - `SILENCE_BOUNDARY`：静音边界（毫秒）
2. 新建一个文件夹，准备视频文件， 将文件放在该文件夹下
3. 将本项目所有 skill 放置在正确的目录下，根据使用的工具决定，例如：
   - `/.agents/skills/`
   - `/.claude/skills/`
4. 执行转录`转录`,生成口播逐字稿`转录.md`,带时间戳`- (5.800-15.520) 口播内容`
5. 使用转录逐字稿`转录.md`,手动编辑删除无关内容,保留精华片段, 这里可以将逐字稿交给大模型处理，提取你想要的精华内容
6. 使用`提取关键帧：「精华内容」`生成`片段{x}.md`
7. 执行剪辑`剪辑片段{x}`,生成剪辑后视频`片段{x}.mp4`

# 支持的工具
所有支持 skill 的客户端工具理论上都可以使用，例如：
- Google Antigravity
- Claude Code
- Codex Cli
- Vs Code + AI插件（插件需支持 Skill）