# 踩坑清单（实战浓缩）

## 环境 / 子进程
1. PYTHONPATH 污染让 manim/venv 崩：子进程加 `env -u PYTHONPATH CODEBUDDY_SAFE_DELETE_SANDBOX=0`
2. 宿主 safe-delete 拦截 PyInstaller/清理：同样豁免
3. CUDA 不可用时 F5-TTS 静默回退 CPU（慢 10 倍+）：查「CUDA 不可用」警告；单幕耗时翻倍先查 GPU
4. 参考音频转写缓存放 ref 文件旁（声线参考/clean_24k.txt）；放临时目录会触发 ASR 联网下载超时

## 文本 / 字体
5. 雅黑缺 ₂ ⁻ ⁺ ⇌：manim Text 的 Pango 回退补 ⇌ 与上标；下标 ₂ 直接丢字 → 化学式平写
6. 字体覆盖用 fontTools 查 msyh.ttc 的 cmap，先测再写

## 分镜 / 数据
7. 幕名含空格 → 表格解析正则在空格截断，整段配音静默跳过；validate 只报幕数不匹配
8. TTS 静默失败判据：成片时长与旧版完全一致 = 没用上新音频；批处理 grep 会吞失败日志
9. audio_info.json 的 engine 字段判别配音版本（F5-TTS-expressive / F5-TTS）
10. 读白里的 | 会被表格解析吃掉，写数据时替换为逗号
11. validate 回填对「### 第N幕」做 int()，幕名带非数字后缀（①/括号）会崩

## Manim / 渲染
12. run_scene 三件套：begin_scene(挂音频+快照) → present → show_subtitles → end_scene
13. scene 快照用 id(m)；mobjects 不跨幕复用同一实例
14. 图库函数所有 shift/坐标用三维 (x,y,0)，二维元组触发 broadcast ValueError
15. lessonlib 多副本同步会覆盖专属图库——图库做成追加式（幂等 if key not in FIGS），同步后重跑

## 打包 / GUI
16. PyInstaller --noconsole 崩溃无 traceback：冒烟用进程存活+窗口标题判断（tasklist 对中文名不可靠，改用 Get-Process）
17. ctypes 窗口子类化：Get/SetWindowLongPtrW、CallWindowProcW 必须声明 argtypes；SetWindowLongPtrW 第三参 c_void_p
18. windnd 类第三方镜像源可能缺——ctypes 自实现 WM_DROPFILES（约 40 行）
19. exe 配置 json 放 exe 同目录（便携）；lessonlib.py 运行时 copy 进工程目录
20. bash 传 /d/... 路径给原生 python 失真 → cd 后用相对路径或 cygpath -m
