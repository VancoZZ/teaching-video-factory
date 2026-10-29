# 管线架构与数据流

```
课堂数据 lesson_data_NN.py
        │  build_project.py / build_chem.py
        ▼
工程目录 project/
├── script.py      ← 模板生成：Scene 类 + load_timeline + run_scene
├── 分镜.md        ← 幕设计 + 音频生成清单（幕号|文件名|读白）
├── lessonlib.py   ← 动画引擎副本
└── (lesson_data_NN.py 副本)

        │  expressive_tts.py（F5-TTS 表达力配音）
        ▼
audio/
├── audio_NNN_幕名.mp3     每幕一个（内部分段合成后拼接）
├── audio_info.json        {files:[{scene,file,text,duration}], engine, ...}
└── timeline.json          {scenes:[{index,file,duration}]} ← 渲染读这个

        │  validate_audio.py  · 幕数 vs 音频数一致性（不一致=有段失败）
        │                     · 时长回填分镜 + 写 timeline.json
        │  check.py           · 静态检查（几何断言空壳、绝对路径 → 渲染前拦截）
        ▼
render.py → manim -qm script.py <SceneClass>
        │   run_scene: begin_scene(挂音频) → present(vis 动画)
        │              → show_subtitles(字幕轮播占满剩余时长) → end_scene(淡出)
        ▼
media/videos/script/720p30/<Scene>.mp4 → 成片_*.mp4
```

## 表达力配音内部

```
narr ──切句──▶ 片段列表 ──标注──▶ [(text, style)]
                                   │ n/k/s
             ┌─────────────────────┘
             ▼
   每段 F5-TTS 合成（speed: n=1.0 k=0.85 s=0.7 × base）
   s 风格：text → 字、字、字（顿号强制一字一顿）
   多音字：POLY_RULES 同音字替换（仅合成文本）
   AI 模式：AI_DIRECTOR 批量返回分段+定音+同音字替换
             ▼
   ffmpeg filter_complex: volume(n=1.0 k=1.32 s=1.2) → concat → mp3
```

- 判别配音版本：audio_info.json 的 `engine` 字段（F5-TTS-expressive / F5-TTS）。
- **判据**：成片时长与旧版完全一致 ⇒ TTS 静默失败，渲染用了旧 timeline。

## 字幕引擎（lessonlib.show_subtitles）

- 切句：标点（。！？；，）切分、合并 ≤18 字。
- 排程：整幕总时长（含动画段）按字数比例分配；动画已耗时间 used 之前的片段跳过。
- 样式：雅黑 26、白色 + 2.0 黑描边、底部贴边；72% 黑色 Rectangle 衬底（13.6 宽）。
- 生命周期：sc.add 即现、换片即换、最后一条由 end_scene 统一淡出。

## 正误实例卡片（lessonlib._present_warn）

- vis: {kind:"warn", title, bad:str|list, good:str|list, note?}
- 渲染：标题 + 左「✗ 错误示例」红卡 + 右「✓ 正确实例」绿卡（多行实例），并排；
  note 可选底部提示；随 end_scene 淡出。

## 化学图库（engine/chem_figs_append.py）

- 追加式注册 FIGS：titration_pair（盐酸/醋酸双曲线 + M/N/Q + pH=7、V=20 虚线）、
  titration_ha（单曲线 a/b/c/d）。幂等：`if "titration_pair" not in FIGS`。
- **同步 lessonlib 到化学根目录后必须重跑本追加**（否则题1/题4 KeyError）。
