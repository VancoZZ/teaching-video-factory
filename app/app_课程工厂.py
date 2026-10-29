# -*- coding: utf-8 -*-
"""
课程工厂 —— 教学视频一键生成（拖拽上传 → 文字稿件 → 声线克隆视频）

依赖（打包后内置）：tkinter、pypdf、python-docx、windnd(可选，拖拽)
外部依赖（本机已有，路径可在设置中改）：
  - 教学视频工具包：.venv（manim 渲染）、.venv-tts（F5-TTS 声线克隆）、声线参考
  - lessonlib.py（动画引擎，需与本程序同目录或在其旁）

用法：python app_课程工厂.py [--selftest]
"""
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

APP_TITLE = "课程工厂 · 教学视频一键生成"
APP_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)).resolve()
EXE_DIR = Path(sys.executable).parent.resolve() if getattr(sys, "frozen", False) else APP_DIR
CFG_PATH = EXE_DIR / "课程工厂_配置.json"

DEFAULT_CFG = {
    "tool_root": r"D:\视频生成\教学视频工具包",
    "lessonlib": "",            # 留空 = EXE 同目录的 lessonlib.py
    "output_root": r"D:\视频生成\AI生成",
    "ref_wav": r"D:\视频生成\教学视频工具包\声线参考\clean_24k.wav",
    "tts_speed": 0.85,
    "quality": "m",
    "ai_base": "https://api.deepseek.com/v1",
    "ai_key": "",
    "ai_model": "deepseek-chat",
}


def load_cfg():
    cfg = dict(DEFAULT_CFG)
    if CFG_PATH.exists():
        try:
            cfg.update(json.loads(CFG_PATH.read_text(encoding="utf-8")))
        except Exception:
            pass
    return cfg


def save_cfg(cfg):
    CFG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def clean_env():
    """子进程环境：剥 PYTHONPATH（防 venv 污染）、关 safe-delete 拦截。"""
    env = {k: v for k, v in os.environ.items()
           if k not in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP")}
    env["CODEBUDDY_SAFE_DELETE_SANDBOX"] = "0"
    return env


# ================= 文本提取 =================

def extract_text(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in (".txt", ".md"):
        return path.read_text(encoding="utf-8", errors="ignore")
    if ext == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        pages = []
        for i, pg in enumerate(reader.pages):
            t = (pg.extract_text() or "").strip()
            if t:
                pages.append(t)
        return "\n\n".join(pages)
    if ext == ".docx":
        import docx
        d = docx.Document(str(path))
        parts = [p.text.strip() for p in d.paragraphs if p.text.strip()]
        for tb in d.tables:
            for row in tb.rows:
                cells = [c.text.strip() for c in row.cells if c.text.strip()]
                if cells:
                    parts.append(" ｜ ".join(cells))
        return "\n\n".join(parts)
    if ext in (".png", ".jpg", ".jpeg", ".bmp", ".webp"):
        return ""  # 图片无法本地 OCR；提示用户配 AI 或另附文字
    raise ValueError(f"暂不支持的文件类型：{ext}")


# ================= 稿件生成（本地模板引擎） =================

def _split_sentences(text, maxlen=60):
    text = re.sub(r"\s+", " ", text.strip())
    sents = re.split(r"(?<=[。！？；!?;])", text)
    out, buf = [], ""
    for s in sents:
        if not s:
            continue
        if len(buf) + len(s) <= maxlen:
            buf += s
        else:
            if buf:
                out.append(buf)
            buf = s
    if buf:
        out.append(buf)
    return out


def gen_scenes_local(title, text):
    """无 AI：按段落切成 bullets 页，首尾加标题页与总结页。"""
    scenes = [{"name": "开场", "kind": "title", "main": title,
               "sub": "根据你上传的资料生成",
               "narr": f"同学们好，今天我们一起来学习{title}。本节课的讲稿根据你上传的资料整理而成，我们开始。"}]
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    idx = 0
    for para_text in paras:
        lines = _split_sentences(para_text, 52)
        for i in range(0, len(lines), 5):
            chunk = lines[i:i + 5]
            idx += 1
            scenes.append({
                "name": f"要点{idx}",
                "kind": "bullets",
                "title": title[:16] if idx == 1 else f"{title[:14]}（续）",
                "lines": chunk,
                "narr": "。".join(chunk) + "。" if not chunk[-1].endswith("。") else "。".join(chunk),
            })
        if len(scenes) >= 25:   # 防爆量
            break
    key_pts = [p.strip()[:18] for p in paras[:3] if p.strip()]
    scenes.append({
        "name": "课堂小结", "kind": "summary",
        "lines": key_pts or [title],
        "hw": "完成课后练习，并向家人复述今天的内容",
        "narr": "本节课的主要内容就到这里。关键内容刚才已经逐条讲过，"
                "请你课后完成配套练习，并把今天学到的内容讲给家人听。讲得出来，才是真的学会了。",
    })
    return scenes


AI_SYSTEM = (
    "你是经验丰富的初中数学老师兼课程设计师。根据用户上传的资料文本，产出一份教学视频分镜稿。"
    "严格输出 JSON 数组（不要多余文字），每幕格式："
    '{"name":"幕名(不含空格)","kind":"title|bullets|steps|summary",'
    '"narr":"配音读白(口语化,100~180字)","lines":["页面上的要点行"],'
    '"main":"标题页主标题(kind=title时)","sub":"副标题(kind=title时)",'
    '"result":"结论行(kind=steps时)","hw":"作业(kind=summary时)"}'
    "要求：4~12 幕；第 1 幕 kind=title；最后 1 幕 kind=summary；"
    "中间 幕用 bullets（知识要点）或 steps（例题步骤）；读白面向六年级学生，老师口吻，直接可配音。"
)


def call_ai(cfg, messages, timeout=120):
    base = cfg["ai_base"].rstrip("/")
    url = f"{base}/chat/completions"
    body = json.dumps({"model": cfg["ai_model"], "messages": messages, "temperature": 0.4}).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": "application/json",
                                          "Authorization": f"Bearer {cfg['ai_key']}"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"]


def gen_scenes_ai(cfg, title, text):
    content = f"课程标题：{title}\n\n资料文本：\n{text[:12000]}"
    out = call_ai(cfg, [{"role": "system", "content": AI_SYSTEM},
                        {"role": "user", "content": content}])
    m = re.search(r"\[.*\]", out, re.S)
    scenes = json.loads(m.group(0))
    assert isinstance(scenes, list) and len(scenes) >= 3
    return scenes


AI_SYSTEM_VISION = (
    "你是经验丰富的老师兼课程设计师。用户上传了题目或资料的【图片】，请先仔细读图"
    "（题目文字、图象、表格、数据），然后产出一份讲解视频分镜稿。"
    "严格输出 JSON 数组（不要多余文字），每幕格式："
    '{"name":"幕名(不含空格)","kind":"title|bullets|steps|summary",'
    '"narr":"配音读白(口语化,100~180字)","lines":["页面上的要点行"],'
    '"main":"标题页主标题(kind=title时)","sub":"副标题(kind=title时)",'
    '"result":"结论行(kind=steps时)","hw":"作业(kind=summary时)"}'
    "要求：5~14 幕；第 1 幕 kind=title（main=题目考点，sub=来源）；"
    "第 2 幕 kind=bullets 完整转写题干（数值、图形信息一个不能漏）；"
    "之后每小问/每步骤一幕 kind=steps（先审题分析，再给出答案，多空题逐空讲）；"
    "最后两幕：kind=warn（易错盘点）与 kind=summary（小结+hw 作业）。"
    "读白面向中学生，老师口吻，可直接配音。"
)


def _image_to_data_url(path, max_side=1500, quality=85):
    """图片压缩后转 base64 data URL（供视觉 API 使用）。"""
    import base64
    import io
    try:
        from PIL import Image
    except ImportError:
        raise RuntimeError("缺少 Pillow，无法处理图片（重新打包时需包含 Pillow）")
    img = Image.open(str(path))
    img = img.convert("RGB")
    w, h = img.size
    scale = max_side / max(w, h)
    if scale < 1:
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{b64}"


def gen_scenes_ai_vision(cfg, title, image_paths, text=""):
    """图片题目 → 视觉模型读图 → 分镜稿。需要支持视觉的模型（如 gpt-4o、qwen-vl、glm-4v）。"""
    content = [{"type": "text",
                "text": f"课程标题：{title}\n"
                        + (f"配套文字资料：\n{text[:6000]}\n" if text.strip() else "")
                        + "请根据以上图片生成讲解视频分镜稿。"}]
    n = 0
    for p in image_paths:
        if n >= 4:   # 控制体积
            break
        content.append({"type": "image_url",
                        "image_url": {"url": _image_to_data_url(p)}})
        n += 1
    out = call_ai(cfg, [{"role": "system", "content": AI_SYSTEM_VISION},
                        {"role": "user", "content": content}])
    m = re.search(r"\[.*\]", out, re.S)
    scenes = json.loads(m.group(0))
    assert isinstance(scenes, list) and len(scenes) >= 3
    return scenes


def revise_scenes_ai(cfg, scenes, feedback):
    out = call_ai(cfg, [
        {"role": "system", "content": AI_SYSTEM + " 你将收到现有分镜 JSON 和修改需求，输出修改后的完整 JSON 数组。"},
        {"role": "user", "content": "现有分镜：\n" + json.dumps(scenes, ensure_ascii=False)
         + "\n\n修改需求：" + feedback}])
    m = re.search(r"\[.*\]", out, re.S)
    return json.loads(m.group(0))


def revise_scenes_local(scenes, feedback):
    """无 AI 的本地调整规则。"""
    fb = feedback.strip()
    n = len(scenes)
    m = re.search(r"删除第(\d+)幕", fb)
    if m and 2 <= int(m.group(1)) <= n:
        del scenes[int(m.group(1)) - 1]
        return scenes, f"已删除第 {m.group(1)} 幕"
    m = re.search(r"在第(\d+)幕(?:后|后面|之后)加一页总结", fb)
    if m:
        i = int(m.group(1))
        scenes.insert(i, {"name": "补充总结", "kind": "summary",
                          "lines": [s.get("title", "") or s["name"] for s in scenes[max(0, i-3):i]],
                          "hw": "完成配套练习",
                          "narr": "我们把刚才讲的内容再梳理一遍，请对照屏幕上的要点自查掌握情况。"})
        return scenes, f"已在第 {i} 幕后插入总结页"
    return None, ("本地模式支持的调整：\n・删除第N幕\n・在第N幕后加一页总结\n"
                  "・语速请在「设置」里改\n更多调整请在「设置」里填入 AI API Key")


# ================= 工程生成 =================

SCRIPT_TMPL = '''"""
自动生成的讲解视频脚本 — {title}
来源：课程工厂（基于 lessonlib 动画引擎）
"""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lessonlib import *  # noqa: F401,F403
from lessonlib import AUDIO_DIR, TIMELINE, present

SCENES = json.loads(Path(__file__).resolve().parent.joinpath("scenes.json").read_text(encoding="utf-8"))


class {scene_cls}(Scene):
    SCENES_META = [(i + 1, s["name"]) for i, s in enumerate(SCENES)]

    def load_timeline(self):
        if not TIMELINE.exists():
            print("[警告] 无 timeline.json")
            return {{}}
        data = json.loads(TIMELINE.read_text(encoding="utf-8"))
        return {{
            int(s["index"]): {{"file": s["file"], "duration": float(s["duration"])}}
            for s in data.get("scenes", [])
        }}

    def sd(self, n):
        return getattr(self, "_tl", {{}}).get(n, {{}}).get("duration", 0.0)

    def add_audio(self, n):
        f = getattr(self, "_tl", {{}}).get(n, {{}}).get("file", "")
        if not f:
            return
        p = AUDIO_DIR / f
        if p.exists():
            self.add_sound(str(p).replace("\\\\", "/"))
        else:
            print(f"[警告] 音频缺失 {{p}}")

    def wait_for_audio(self, used, audio):
        remain = audio - used
        if remain > 0.05:
            self.wait(remain)

    def begin_scene(self, n):
        self.add_audio(n)
        self._scene_snapshot = set(id(m) for m in self.mobjects)

    def end_scene(self, keep=()):
        keep_ids = {{id(m) for m in keep}}
        new = [m for m in self.mobjects
               if id(m) not in self._scene_snapshot and id(m) not in keep_ids]
        if new:
            self.play(FadeOut(Group(*new)), run_time=0.4)
        return 0.4

    def calculate_geometry(self):
        self.assert_conditions(None)
        return {{}}

    def assert_conditions(self, g):
        kinds = ("title", "bullets", "steps", "summary", "twocol", "warn", "fig")
        for i, s in enumerate(SCENES, 1):
            assert s.get("kind") in kinds, f"幕{{i}} kind 非法：{{s.get('kind')}}"
            assert str(s.get("narr", "")).strip(), f"幕{{i}} 读白为空"
        print("✅ 断言通过（分镜结构与读白完整性）")

    def define_elements(self):
        return {{}}

    def run_scene(self, i, s):
        self.begin_scene(i)
        vis = {{k: v for k, v in s.items() if k not in ("name", "narr")}}
        used = present(self, vis)
        show_subtitles(self, s.get("narr", ""), used, self.sd(i))
        self.end_scene()

    def construct(self):
        self._tl = self.load_timeline()
        self.calculate_geometry()
        for i, s in enumerate(SCENES, start=1):
            self.run_scene(i, s)


if __name__ == "__main__":
    {scene_cls}().render()
'''


def build_project(cfg, title, scenes):
    """写 scenes.json / script.py / 分镜.md，返回工程目录。"""
    out_root = Path(cfg["output_root"])
    stamp = time.strftime("%Y%m%d_%H%M%S")
    proj = out_root / f"课程_{stamp}"
    proj.mkdir(parents=True, exist_ok=True)
    (proj / "scenes.json").write_text(json.dumps(scenes, ensure_ascii=False, indent=1),
                                      encoding="utf-8")
    scene_cls = "CourseScene"
    (proj / "script.py").write_text(
        SCRIPT_TMPL.format(title=title, scene_cls=scene_cls), encoding="utf-8")
    # lessonlib 复制到工程目录（script.py 的 sys.path 含工程目录）
    lib_src = Path(cfg["lessonlib"]) if cfg.get("lessonlib") else (APP_DIR / "lessonlib.py")
    if not lib_src.exists():
        lib_src = Path(r"D:\视频生成\六年级上册第一单元\lessonlib.py")
    lib_dst = proj / "lessonlib.py"
    if lib_src.exists():
        shutil.copy2(lib_src, lib_dst)
    # 分镜.md（含音频清单）
    rows = ["## 音频生成清单", "",
            "| 幕号 | 文件名 | 读白文本 | 时长 | 说话人 |",
            "|------|--------|----------|------|--------|"]
    for i, s in enumerate(scenes, start=1):
        fname = f"audio_{i:03d}_{s['name'].replace(' ', '_')}.mp3"
        narr = s["narr"].replace("|", "，")
        rows.append(f'| {i} | {fname} | "{narr}" |  | clone |')
    (proj / "分镜.md").write_text("\n".join(rows), encoding="utf-8")
    # 稿件.md（人读版）
    md = [f"# 文字稿件：{title}", ""]
    for i, s in enumerate(scenes, start=1):
        md.append(f"## 第{i}幕：{s['name']}（{s['kind']}）")
        if s.get("main"):
            md.append(f"**{s['main']}**　{s.get('sub','')}")
        for ln in s.get("lines", []):
            md.append(f"- {ln}")
        md.append(f"> 读白：{s['narr']}")
        md.append("")
    (proj / "稿件.md").write_text("\n".join(md), encoding="utf-8")
    return proj


# ================= 视频管线 =================

def run_pipeline(cfg, proj: Path, log):
    tool = Path(cfg["tool_root"])
    tts_py = tool / ".venv-tts/Scripts/python.exe"
    ven_py = tool / ".venv/Scripts/python.exe"
    tools = tool / "工具脚本"
    ref = cfg["ref_wav"]
    scene_cls = "CourseScene"

    def run(cmd_list, tail=3):
        log("$ " + " ".join(Path(c).name if i == 1 else str(c)
                            for i, c in enumerate(cmd_list[:4])))
        r = subprocess.run(cmd_list, capture_output=True, text=True,
                           env=clean_env(), cwd=str(proj),
                           errors="ignore", encoding="utf-8")
        for ln in (r.stdout or "").splitlines()[-tail:]:
            log("  " + ln)
        if r.returncode != 0:
            for ln in (r.stderr or "").splitlines()[-6:]:
                log("  ! " + ln)
            raise RuntimeError("步骤失败，见日志")
        return r

    # 1 配音
    log("步骤 1/4 生成声线克隆配音…")
    tts_cmd = [str(tts_py), str(tools / "expressive_tts.py"), "分镜.md", "audio",
               "--ref", ref, "--base-speed", str(cfg["tts_speed"])]
    if cfg.get("ai_key"):
        tts_cmd += ["--ai-key", cfg["ai_key"], "--ai-base", cfg.get("ai_base", ""),
                    "--ai-model", cfg.get("ai_model", "")]
    run(tts_cmd, tail=4)
    # 2 校验
    log("步骤 2/4 校验音频并回填时长…")
    run([str(ven_py), str(tools / "validate_audio.py"), "分镜.md", "audio"])
    # 3 检查
    log("步骤 3/4 代码结构检查…")
    run([str(ven_py), str(tools / "check.py"), "script.py"])
    # 4 渲染
    log(f"步骤 4/4 渲染（{cfg['quality']} 画质）…")
    run([str(ven_py), str(tools / "render.py"), "-f", "script.py",
         "-s", scene_cls, "-q", cfg["quality"], "--no-check"], tail=6)
    # 收集
    found = list(proj.rglob("最终视频_*.mp4")) + list((proj / "media" / "videos").rglob(f"{scene_cls}.mp4"))
    if not found:
        raise RuntimeError("渲染完成但未找到成片")
    src = max(found, key=lambda p: p.stat().st_mtime)
    dst = proj / "成片.mp4"
    shutil.copy2(src, dst)
    log(f"完成：{dst}")
    return dst


# ================= GUI =================

# ================= 拖拽支持（ctypes 实现，零第三方依赖） =================

def hook_drop(widget, callback):
    """给 tk 控件挂 Windows 文件拖拽。callback 收到 [Path, ...]。"""
    import ctypes
    from ctypes import wintypes
    u32 = ctypes.windll.user32
    sh32 = ctypes.windll.shell32
    WM_DROPFILES = 0x0233
    GWLP_WNDPROC = -4

    hwnd = widget.winfo_id()
    sh32.DragAcceptFiles(hwnd, True)

    GWLP_WNDPROC = -4
    u32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    u32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    u32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    u32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
    u32.CallWindowProcW.restype = ctypes.c_ssize_t
    u32.CallWindowProcW.argtypes = [ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT,
                                    wintypes.WPARAM, wintypes.LPARAM]
    OLD_WNDPROC = u32.GetWindowLongPtrW(hwnd, GWLP_WNDPROC)
    WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t,
                                 wintypes.HWND, wintypes.UINT,
                                 wintypes.WPARAM, wintypes.LPARAM)
    old_ref = WNDPROC(OLD_WNDPROC)

    def new_wndproc(h, msg, wp, lp):
        if msg == WM_DROPFILES:
            try:
                count = sh32.DragQueryFileW(wp, 0xFFFFFFFF, None, 0)
                files = []
                buf = ctypes.create_unicode_buffer(260)
                for i in range(count):
                    sh32.DragQueryFileW(wp, i, buf, 260)
                    files.append(Path(buf.value))
                sh32.DragFinish(wp)
                widget.after(0, lambda: callback(files))
                return 0
            except Exception:
                pass
        return u32.CallWindowProcW(OLD_WNDPROC, h, msg, wp, lp)

    new_ref = WNDPROC(new_wndproc)
    u32.SetWindowLongPtrW(hwnd, GWLP_WNDPROC, ctypes.cast(new_ref, ctypes.c_void_p))
    # 防 GC
    widget._drop_refs = (new_ref, old_ref)


def gui_main(cfg):
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    HAS_DND = os.name == "nt"

    root = tk.Tk()
    root.title(APP_TITLE)
    root.geometry("980x760")
    state = {"files": [], "scenes": None, "title": "", "proj": None, "video": None,
             "busy": False}

    def log(msg):
        logbox.configure(state="normal")
        logbox.insert("end", f"[{time.strftime('%H:%M:%S')}] {msg}\n")
        logbox.see("end")
        logbox.configure(state="disabled")

    def refresh_status():
        tool = Path(cfg["tool_root"])
        ok_tool = (tool / ".venv-tts/Scripts/python.exe").exists() and (tool / ".venv/Scripts/python.exe").exists()
        ok_ref = Path(cfg["ref_wav"]).exists()
        lib = Path(cfg["lessonlib"]) if cfg.get("lessonlib") else (APP_DIR / "lessonlib.py")
        ok_lib = lib.exists()
        ai = "已配置" if cfg.get("ai_key") else "未配置（用本地模板生成稿件）"
        stat.set(f"工具包：{'✓' if ok_tool else '✗ 找不到'}   声线：{'✓' if ok_ref else '✗'}   "
                 f"动画引擎：{'✓' if ok_lib else '✗ 缺 lessonlib.py'}   AI：{ai}")

    # ---- 顶部状态 ----
    stat = tk.StringVar()
    ttk.Label(root, textvariable=stat, relief="groove", padding=6).pack(fill="x")
    refresh_status()

    nb = ttk.Notebook(root)
    nb.pack(fill="both", expand=True)

    # ================= Tab 1：生产流程 =================
    tab1 = ttk.Frame(nb, padding=8)
    nb.add(tab1, text="① 上传 → ② 稿件 → ③ 视频")

    tip = ("把文件拖到这里（Word / PDF / TXT / MD 直接生成；图片需在「设置」里配置"
           "支持视觉的 AI API Key 才能读图出题），或点下方按钮选择。")
    drop = tk.Listbox(tab1, height=6, relief="groove")
    drop.insert("end", tip)
    drop.pack(fill="x")
    if HAS_DND:
        def on_drop(files):
            for p in files:
                if p.suffix.lower() not in (".pdf", ".docx", ".txt", ".md",
                                            ".png", ".jpg", ".jpeg", ".bmp", ".webp"):
                    messagebox.showwarning("不支持的类型", f"跳过：{p.name}")
                    continue
                state["files"].append(p)
                drop.insert("end", f"＋ {p}")
        hook_drop(drop, on_drop)
    else:
        drop.insert("end", "（拖拽不可用，请用「添加文件」按钮）")

    frow = ttk.Frame(tab1); frow.pack(fill="x", pady=4)
    def add_files():
        for f in filedialog.askopenfilenames(
                filetypes=[("支持的文件", "*.pdf *.docx *.txt *.md *.png *.jpg *.jpeg")]):
            state["files"].append(Path(f))
            drop.insert("end", f"＋ {f}")
    ttk.Button(frow, text="添加文件", command=add_files).pack(side="left")
    ttk.Button(frow, text="清空", command=lambda: (state["files"].clear(), drop.delete(1, "end"))).pack(side="left", padx=6)

    # 稿件预览
    ttk.Label(tab1, text="文字稿件（生成后可在此直接微调文字，点「应用稿件修改」生效）：").pack(anchor="w")
    draft = tk.Text(tab1, height=14, wrap="word")
    draft.pack(fill="both", expand=True)

    arow = ttk.Frame(tab1); arow.pack(fill="x", pady=4)

    def do_gen_draft():
        if state["busy"]:
            return
        if not state["files"]:
            messagebox.showwarning("提示", "请先拖入或添加文件")
            return
        state["busy"] = True
        def work():
            try:
                IMG_EXT = (".png", ".jpg", ".jpeg", ".bmp", ".webp")
                text_files = [p for p in state["files"]
                              if p.suffix.lower() not in IMG_EXT]
                img_files = [p for p in state["files"]
                             if p.suffix.lower() in IMG_EXT]
                title = state["files"][0].stem
                texts = []
                for p in text_files:
                    t = extract_text(p)
                    log(f"已读取：{p.name}（{len(t)} 字）" if t else f"警告：{p.name} 未能提取文字")
                    if t:
                        texts.append(t)
                full = "\n\n".join(texts).strip()
                if img_files:
                    log(f"检测到 {len(img_files)} 张图片")
                    if not cfg.get("ai_key"):
                        raise RuntimeError(
                            "图片生成视频需要 AI 帮你「读图出题」（本地无法 OCR）。\n"
                            "请在「设置」→ AI 设置里填写 API Key（需支持视觉的模型，\n"
                            "如 gpt-4o / qwen-vl-plus / glm-4v），保存后重新点「① 生成文字稿件」。")
                    scenes = gen_scenes_ai_vision(cfg, title, img_files, full)
                    src = "AI 视觉读图"
                elif full:
                    if cfg.get("ai_key"):
                        log("使用 AI 生成稿件…")
                        scenes = gen_scenes_ai(cfg, title, full)
                        src = "AI"
                    else:
                        log("未配置 AI，使用本地模板引擎生成稿件…")
                        scenes = gen_scenes_local(title, full)
                        src = "本地模板"
                else:
                    raise RuntimeError("没有提取到任何内容，请检查上传的文件。")
                state["scenes"] = scenes
                state["title"] = title
                draft.delete("1.0", "end")
                for i, s in enumerate(scenes, 1):
                    draft.insert("end", f"◆ 第{i}幕【{s['name']}｜{s['kind']}】\n")
                    for ln in s.get("lines", []):
                        draft.insert("end", f"   · {ln}\n")
                    if s.get("main"):
                        draft.insert("end", f"   ★ {s['main']} {s.get('sub','')}\n")
                    if s.get("result"):
                        draft.insert("end", f"   ⇒ {s['result']}\n")
                    draft.insert("end", f"   〔读白〕{s['narr']}\n\n")
                log(f"稿件生成完成（{len(scenes)} 幕，来源：{src}）。可直接在上方文本框修改文字，"
                    f"或用「按需求调整稿件」。")
                draftbox.set(f"稿件已生成：{len(scenes)} 幕（{src}）。确认内容后点「③ 生成视频」。")
            except Exception as e:
                messagebox.showerror("生成稿件失败", str(e))
                log(f"错误：{e}")
            finally:
                state["busy"] = False
        threading.Thread(target=work, daemon=True).start()

    def do_apply_draft():
        """把文本框的手工修改回写 scenes（按幕块解析）。"""
        if state["busy"] or state["scenes"] is None:
            return
        try:
            content = draft.get("1.0", "end")
            blocks = re.split(r"◆\s*第(\d+)幕【([^｜\]]+)｜(\w+)】", content)
            new_scenes = []
            it = iter(blocks[1:])
            for idx, (num, name, kind) in enumerate(zip(it, it, it), 1):
                body = next(it, "")
                narr = ""
                m = re.search(r"〔读白〕(.+)", body)
                if m:
                    narr = m.group(1).strip()
                    body = body[:m.start()]
                lines = [ln.strip().lstrip("·★⇒ ").strip() for ln in body.splitlines()
                         if ln.strip() and not ln.strip().startswith("读白")]
                s = dict(state["scenes"][idx - 1])
                s["name"] = name.strip()
                s["kind"] = kind.strip()
                if lines:
                    s["lines"] = lines
                if narr:
                    s["narr"] = narr
                new_scenes.append(s)
            if len(new_scenes) == len(state["scenes"]):
                state["scenes"] = new_scenes
                log("已应用你在文本框中的修改。")
                messagebox.showinfo("完成", "修改已应用")
            else:
                messagebox.showwarning("未应用", f"解析到 {len(new_scenes)} 幕，与原稿 {len(state['scenes'])} 幕不一致，"
                                                 "请勿增删『◆ 第N幕』行，只改行内文字。")
        except Exception as e:
            messagebox.showerror("应用失败", str(e))

    def do_feedback_draft():
        """对话框：输入需求调整稿件。"""
        if state["scenes"] is None:
            messagebox.showwarning("提示", "请先生成稿件")
            return
        win = tk.Toplevel(root); win.title("调整稿件"); win.geometry("520x220")
        ttk.Label(win, text="输入你的调整需求（例：语气更活泼／加一页关于XX的总结／删除第3幕／每幕更简短）"
                ).pack(anchor="w", padx=10, pady=(10, 2))
        txt = tk.Text(win, height=5); txt.pack(fill="both", expand=True, padx=10)
        def apply_fb():
            fb = txt.get("1.0", "end").strip()
            if not fb:
                return
            if cfg.get("ai_key"):
                def work():
                    try:
                        scenes = revise_scenes_ai(cfg, state["scenes"], fb)
                        state["scenes"] = scenes
                        draft.delete("1.0", "end")
                        for i, s in enumerate(scenes, 1):
                            draft.insert("end", f"◆ 第{i}幕【{s['name']}｜{s['kind']}】\n")
                            for ln in s.get("lines", []):
                                draft.insert("end", f"   · {ln}\n")
                            draft.insert("end", f"   〔读白〕{s['narr']}\n\n")
                        log("稿件已按需求调整（AI）。")
                        win.destroy()
                    except Exception as e:
                        messagebox.showerror("调整失败", str(e))
                threading.Thread(target=work, daemon=True).start()
            else:
                new, msg = revise_scenes_local(state["scenes"], fb)
                if new is None:
                    messagebox.showinfo("本地模式", msg)
                else:
                    state["scenes"] = new
                    log(f"稿件已调整：{msg}")
                    win.destroy()
        ttk.Button(win, text="应用调整", command=apply_fb).pack(pady=6)

    ttk.Button(arow, text="① 生成文字稿件", command=do_gen_draft).pack(side="left")
    ttk.Button(arow, text="应用稿件修改", command=do_apply_draft).pack(side="left", padx=6)
    ttk.Button(arow, text="按需求调整稿件…", command=do_feedback_draft).pack(side="left")
    draftbox = tk.StringVar()
    ttk.Label(tab1, textvariable=draftbox, foreground="#1565c0").pack(anchor="w")

    vrow = ttk.Frame(tab1); vrow.pack(fill="x", pady=6)
    def do_video():
        if state["busy"] or state["scenes"] is None:
            messagebox.showwarning("提示", "请先生成（或调整）稿件")
            return
        state["busy"] = True
        btnv.configure(state="disabled")
        def work():
            try:
                proj = build_project(cfg, state["title"], state["scenes"])
                state["proj"] = proj
                log(f"工程目录：{proj}")
                video = run_pipeline(cfg, proj, log)
                state["video"] = video
                draftbox.set(f"视频已完成：{video}")
                messagebox.showinfo("完成", f"视频已生成：\n{video}")
            except Exception as e:
                log(f"错误：{e}")
                messagebox.showerror("生成视频失败", str(e))
            finally:
                state["busy"] = False
                btnv.configure(state="normal")
        threading.Thread(target=work, daemon=True).start()

    def do_video_feedback():
        """对话框：视频产出后调整（改读白/语速/重渲）。"""
        if state["proj"] is None:
            messagebox.showwarning("提示", "请先生成视频")
            return
        win = tk.Toplevel(root); win.title("调整视频"); win.geometry="520x260"
        win.geometry("520x260")
        ttk.Label(win, text="选择调整方式：").pack(anchor="w", padx=10, pady=8)
        v = tk.StringVar(value="text")
        ttk.Radiobutton(win, text="修改某一幕的文字（在下面选幕并编辑读白）", variable=v, value="text").pack(anchor="w", padx=20)
        ttk.Radiobutton(win, text="只改语速（重新配音+重渲染）", variable=v, value="speed").pack(anchor="w", padx=20)
        ttk.Radiobutton(win, text="用 AI 按需求重写稿件并重渲染", variable=v, value="ai").pack(anchor="w", padx=20)
        rowf = ttk.Frame(win); rowf.pack(fill="x", padx=10)
        scenes = state["scenes"]
        combo = ttk.Combobox(rowf, values=[f"第{i+1}幕 {s['name']}" for i, s in enumerate(scenes)],
                             state="readonly", width=28)
        if scenes:
            combo.current(0)
        combo.pack(side="left")
        txt = tk.Text(win, height=6); txt.pack(fill="both", expand=True, padx=10, pady=4)
        if scenes:
            txt.insert("1.0", scenes[0]["narr"])
        def on_combo(evt):
            i = combo.current()
            txt.delete("1.0", "end"); txt.insert("1.0", scenes[i]["narr"])
        combo.bind("<<ComboboxSelected>>", on_combo)
        def rerender():
            try:
                if v.get() == "text":
                    i = combo.current()
                    state["scenes"][i]["narr"] = txt.get("1.0", "end").strip()
                elif v.get() == "ai":
                    fb = txt.get("1.0", "end").strip()
                    if cfg.get("ai_key") and fb:
                        state["scenes"] = revise_scenes_ai(cfg, state["scenes"], fb)
                    else:
                        messagebox.showwarning("提示", "AI 未配置或需求为空"); return
                # 重建工程（语速从设置读取）
                proj = build_project(cfg, state["title"], state["scenes"])
                state["proj"] = proj
                video = run_pipeline(cfg, proj, log)
                state["video"] = video
                messagebox.showinfo("完成", f"新视频已生成：\n{video}")
                win.destroy()
            except Exception as e:
                messagebox.showerror("失败", str(e))
        ttk.Button(win, text="重新配音并渲染", command=rerender).pack(pady=6)

    btnv = ttk.Button(vrow, text="③ 生成视频", command=do_video)
    btnv.pack(side="left")
    ttk.Button(vrow, text="调整视频…", command=do_video_feedback).pack(side="left", padx=6)
    ttk.Button(vrow, text="打开输出文件夹", command=lambda: os.startfile(cfg["output_root"])).pack(side="left")

    # 日志
    ttk.Label(tab1, text="运行日志：").pack(anchor="w")
    logbox = tk.Text(tab1, height=8, state="disabled", background="#111", foreground="#cfc")
    logbox.pack(fill="x")

    # ================= Tab 2：设置 =================
    tab2 = ttk.Frame(nb, padding=12)
    nb.add(tab2, text="设置")
    vars_cfg = {}
    fields = [
        ("tool_root", "教学视频工具包路径", 70),
        ("ref_wav", "声线参考音频（本任务声线）", 70),
        ("lessonlib", "lessonlib.py 路径（留空=程序同目录）", 70),
        ("output_root", "输出根目录", 70),
        ("tts_speed", "配音语速（0.7~1.2，越小越慢）", 8),
        ("quality", "画质：l=480p / m=720p / h=1080p", 8),
    ]
    for key, label, width in fields:
        row = ttk.Frame(tab2); row.pack(fill="x", pady=3)
        ttk.Label(row, text=label, width=36).pack(side="left")
        v = tk.StringVar(value=str(cfg[key]))
        ttk.Entry(row, textvariable=v, width=width).pack(side="left")
        vars_cfg[key] = v
    ttk.Separator(tab2).pack(fill="x", pady=8)
    ttk.Label(tab2, text="AI 设置（可选；不填则用本地模板生成稿件。支持 OpenAI 兼容接口）").pack(anchor="w")
    ttk.Label(tab2, text="※ 图片→视频：必须配置支持视觉的模型（如 gpt-4o / qwen-vl-plus / glm-4v）",
              foreground="#b26a00").pack(anchor="w")
    for key, label, width in [("ai_base", "API 地址（base_url）", 50),
                              ("ai_key", "API Key", 50),
                              ("ai_model", "模型名", 30)]:
        row = ttk.Frame(tab2); row.pack(fill="x", pady=3)
        ttk.Label(row, text=label, width=36).pack(side="left")
        v = tk.StringVar(value=str(cfg.get(key, "")))
        ttk.Entry(row, textvariable=v, width=width, show="*" if key == "ai_key" else "").pack(side="left")
        vars_cfg[key] = v

    def save_settings():
        for k, v in vars_cfg.items():
            val = v.get().strip()
            if k == "tts_speed":
                val = float(val)
            cfg[k] = val
        save_cfg(cfg)
        refresh_status()
        messagebox.showinfo("完成", "设置已保存")
    ttk.Button(tab2, text="保存设置", command=save_settings).pack(anchor="w", pady=8)

    def test_ai():
        cfg_tmp = {k: v.get().strip() for k, v in vars_cfg.items()}
        if not cfg_tmp.get("ai_key"):
            messagebox.showwarning("提示", "请先填写 API Key")
            return
        try:
            out = call_ai(cfg_tmp, [{"role": "user", "content": "回复：连接成功"}], timeout=30)
            messagebox.showinfo("成功", f"AI 返回：{out[:80]}")
        except Exception as e:
            messagebox.showerror("失败", str(e))
    ttk.Button(tab2, text="测试 AI 连接", command=test_ai).pack(anchor="w")

    stat.set(stat.get() + f"   配置文件：{CFG_PATH}")
    log("欢迎使用课程工厂。流程：拖入文件 → ①生成稿件（可调整）→ ③生成视频（可再调整）。")
    root.mainloop()


def selftest(cfg):
    """无界面端到端自测。"""
    print("== selftest: 生成稿件")
    text = ("有理数的加法法则。同号相加，符号不变，绝对值相加。"
            "例如负二加负三等于负五。\n\n"
            "异号相加，符号随绝对值大的一方，绝对值相减。"
            "例如负七加正三等于负四。\n\n"
            "减去一个数，等于加上它的相反数。"
            "例如三减七等于负四。减去负数等于加正数，结果反而变大。")
    scenes = gen_scenes_local("有理数的加减法", text)
    print(f"scenes: {len(scenes)} 幕")
    proj = build_project(cfg, "有理数的加减法", scenes)
    print("proj:", proj)
    print("== selftest: 渲染管线")
    out = run_pipeline(cfg, proj, lambda m: print("  " + m))
    assert Path(out).exists() and Path(out).stat().st_size > 1_000_000
    print("SELFTEST OK:", out)


if __name__ == "__main__":
    cfg = load_cfg()
    if "--selftest" in sys.argv:
        selftest(cfg)
    else:
        gui_main(cfg)
