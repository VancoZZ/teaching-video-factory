# Teaching Video Factory（教学视频工厂）

> 拖入资料（Word / PDF / TXT / 图片）→ 生成文字稿件 → 用你自己的声音（F5-TTS 声线克隆）
> 合成带字幕、带「正误实例对比」的教学讲解视频。全程本机 GPU，无月费。

本项目是一套**经过实战打磨**的教学视频生产线，覆盖：

- 📝 **文字稿件**：课堂数据（分镜+读白）驱动，或 AI 视觉读图/读资料生成
- 🎙️ **表达力配音**：重点段自动放慢 + 加重，关键短语逐字强调，多音字按上下文定音
- 💬 **内嵌字幕**：读白按标点切句、与配音时间轴对齐，白字黑边衬底
- ⚠️ **正误实例卡片**：讲到易错点时屏显「✗ 错误示例 / ✓ 正确实例」并排卡片
- 🎬 **Manim 动画渲染**：720p30（可切 1080p），滴定曲线、数轴等教学图库内置
- 🖥️ **桌面 EXE**：`app/` 内含 Tkinter GUI 源码，PyInstaller 一键打包（拖拽上传 + 反馈调整对话框）

## 仓库结构

```
├── SKILL.md              # WorkBuddy Skill 定义（可复制到 ~/.workbuddy/skills/ 使用）
├── scripts/              # 核心管线（配音/校验/检查/渲染）
│   ├── clone_tts.py      # F5-TTS 声线克隆配音
│   ├── expressive_tts.py # 表达力配音（重点慢+重、逐字、多音字）
│   ├── validate_audio.py # 音频校验 + 回填时长 + timeline.json
│   ├── check.py          # 脚本静态检查（渲染前拦截）
│   └── render.py         # manim 渲染 + 收集成片
├── engine/
│   ├── lessonlib.py      # 动画引擎（字幕引擎、正误卡片、教学图库）
│   └── chem_figs_append.py # 化学滴定曲线图库（追加式，幂等）
├── build/
│   ├── build_project.py  # 从课堂数据生成单元课视频工程
│   └── build_chem.py     # 习题讲解工程生成
├── app/                  # 课程工厂 EXE（GUI：拖拽→稿件→视频→反馈调整）
├── examples/             # 课堂数据样例（数轴 / 化学多选）
└── docs/                 # 架构、课堂数据规范、踩坑清单
```

## 环境要求（较重，请先读）

本管线依赖**本机 NVIDIA GPU** 与以下组件（默认路径均可在程序内配置）：

1. **Python 3.10+**，两个虚拟环境：
   - `.venv`：manim（渲染）+ python-docx + imageio-ffmpeg
   - `.venv-tts`：F5-TTS + torch(CUDA) + transformers（参考音频转写）
2. **F5-TTS 模型**：`ckpts/F5TTS_Base/model_1200000.safetensors` + `ckpts/vocos/`
   （下载：hf-mirror.com 的 SWivid/F5-TTS 与 charactr/vocos-mel-24khz）
3. **一段你自己的参考音频**（24kHz wav，10~20s）+ 对应文本
4. ffmpeg：imageio-ffmpeg 自带，或系统 PATH 里装一份

> 仓库中的脚本默认路径是作者的本机布局（`D:\视频生成\教学视频工具包` 等），
> 可通过环境变量/程序内设置修改，或直接按目录结构摆放。

## 快速开始（三步出片）

```bash
# 1. 生成配音（表达力模式：重点放慢加重、逐字、多音字定音）
python scripts/expressive_tts.py 分镜.md audio --ref 你的声线.wav --base-speed 0.85

# 2. 校验音频并回填时长
python scripts/validate_audio.py 分镜.md audio

# 3. 渲染成片（含字幕与动画）
python scripts/render.py -f script.py -s YourScene -q m --no-check
```

分镜工程从「课堂数据」生成（见 `examples/` 与 `docs/course_data_spec.md`），
或直接用 `app/` 的 GUI：拖入文件 → 生成稿件 → 生成视频 → 对话框里继续调整。

## 表达力配音的规则

| 风格 | 触发 | 效果 |
|---|---|---|
| `n` 正常 | 默认 | base 语速 |
| `k` 重点 | 结论/答案/关键数字/易错提示 | 语速 ×0.85，音量 +32% |
| `s` 逐字 | 超短答案/口诀 | 字间顿号，语速 ×0.7，音量 +20% |

无 AI Key 时用关键词启发式标注；配置 OpenAI 兼容 API 后由「AI 配音导演」
逐段标注，并按上下文为多音字定音（如「卷」在试卷义读 juàn，用同音字强制）。
详见 `docs/pipeline.md`。

## License

MIT
