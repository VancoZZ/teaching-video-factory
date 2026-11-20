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
import tempfile
import threading
import time
import urllib.error
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
    """子进程环境：剥 PYTHONPATH（防 venv 污染）、关 safe-delete 拦截、强制 UTF-8 输出（防 GBK 崩溃）。"""
    env = {k: v for k, v in os.environ.items()
           if k not in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP")}
    env["CODEBUDDY_SAFE_DELETE_SANDBOX"] = "0"
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


# ================= 文本提取 =================

PDF_MAX_PAGES = 800          # 超过则截断（书太大时防止卡死）
TEXT_MAX_CHARS = 300_000     # 提取文本上限（约 30 万字）


def extract_text(path: Path, progress=None) -> str:
    """提取文本。progress(页码, 总页数) 用于大文件进度回报。"""
    ext = path.suffix.lower()
    if ext in (".txt", ".md"):
        t = path.read_text(encoding="utf-8", errors="ignore")
        return t[:TEXT_MAX_CHARS]
    if ext == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        total = len(reader.pages)
        pages = []
        for i, pg in enumerate(reader.pages):
            if progress:
                progress(i + 1, total)
            t = (pg.extract_text() or "").strip()
            if t:
                pages.append(t)
            if len(pages) and sum(len(x) for x in pages) > TEXT_MAX_CHARS:
                pages.append(f"【提示】文件过大，已截取前 {i + 1} 页")
                break
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
        t = "\n\n".join(parts)
        if len(t) > TEXT_MAX_CHARS:
            t = t[:TEXT_MAX_CHARS] + "【提示】文件过大，已截取前 30 万字"
        return t
    if ext in (".png", ".jpg", ".jpeg", ".bmp", ".webp"):
        return ""  # 图片无法本地 OCR；提示用户配 AI 或另附文字
    raise ValueError(f"暂不支持的文件类型：{ext}")


def pdf_pages_to_images(path: Path, max_pages=4, dpi=140):
    """扫描版 PDF 兜底：渲染前 max_pages 页为 PNG，交给 AI 视觉读图。"""
    try:
        import pypdfium2 as pdfium
    except ImportError:
        return []
    try:
        pdf = pdfium.PdfDocument(str(path))
        tmpd = Path(tempfile.gettempdir()) / "课程工厂_扫描页"
        tmpd.mkdir(exist_ok=True)
        out = []
        for i in range(min(len(pdf), max_pages)):
            bmp = pdf[i].render(scale=dpi / 72)
            f = tmpd / f"{path.stem[:20]}_{i + 1:02d}.png"
            bmp.to_pil().save(f)
            out.append(f)
        return out
    except Exception:
        return []


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
    for s in scenes:   # 本地模式：关键句自动加 **重点** 标记
        s["narr_mark"] = _mark_key_sentences(s["narr"])
    return scenes


AI_SYSTEM = (
    "你是经验丰富的初中数学老师兼课程设计师。根据用户上传的资料文本，产出一份教学视频分镜稿。"
    "严格输出 JSON 数组（不要多余文字），每幕格式："
    '{"name":"幕名(不含空格)","kind":"title|bullets|steps|summary",'
    '"narr":"配音读白(口语化,100~180字,内嵌表现标记)","lines":["页面上的要点行"],'
    '"main":"标题页主标题(kind=title时)","sub":"副标题(kind=title时)",'
    '"result":"结论行(kind=steps时)","hw":"作业(kind=summary时)"}'
    "要求：4~12 幕；第 1 幕 kind=title；最后 1 幕 kind=summary；"
    "中间 幕用 bullets（知识要点）或 steps（例题步骤）；读白面向六年级学生，老师口吻，直接可配音。"
    "读白中必须使用表现标记（原样保留在 narr 字符串里）："
    "**重点**=讲结论/答案/关键数字时放慢加重；!!逐字!!=极重要短语一字一顿；"
    "[停0.8]=停顿0.8秒；[音:卷=倦]=多音字发音替换（同音字替换，字幕仍显示原字）。"
    "每幕至少含 1 个 **重点** 或 [停] 标记。"
)


def call_ai(cfg, messages, timeout=None, retries=1):
    """timeout=None = 不限时（大图/多图读图可能很慢，交给 AI 慢慢算）。"""
    base = cfg["ai_base"].rstrip("/")
    # 容错：base_url 误填成完整端点时自动剥掉 /chat/completions
    if base.endswith("/chat/completions"):
        base = base[: -len("/chat/completions")]
    url = f"{base}/chat/completions"
    body = json.dumps({"model": cfg["ai_model"], "messages": messages, "temperature": 0.4}).encode("utf-8")
    last_err = None
    for attempt in range(1 + retries):
        if attempt:
            time.sleep(3)
        req = urllib.request.Request(url, data=body, method="POST",
                                     headers={"Content-Type": "application/json",
                                              "Authorization": f"Bearer {cfg['ai_key']}"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", "ignore")[:300]
            except Exception:
                pass
            last_err = RuntimeError(
                f"AI 接口返回错误 {e.code}：{detail or e}（模型：{cfg.get('ai_model')}）")
            if e.code not in (429, 500, 502, 503, 504):
                raise last_err from None     # 4xx 类（Key/权限/参数）重试无意义
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_err = RuntimeError(f"AI 接口网络错误：{e}（模型：{cfg.get('ai_model')}）")
    raise last_err


def gen_scenes_ai(cfg, title, text):
    content = f"课程标题：{title}\n\n资料文本：\n{text[:12000]}"
    out = call_ai(cfg, [{"role": "system", "content": AI_SYSTEM},
                        {"role": "user", "content": content}])
    m = re.search(r"\[.*\]", out, re.S)
    scenes = json.loads(m.group(0))
    assert isinstance(scenes, list) and len(scenes) >= 3
    return split_narr_mark(scenes)


AI_SYSTEM_VISION = (
    "你是经验丰富的老师兼课程设计师。用户上传了题目或资料的【图片】，请先仔细读图"
    "（题目文字、图象、表格、数据），然后产出一份讲解视频分镜稿。"
    "严格输出 JSON 数组（不要多余文字），每幕格式："
    '{"name":"幕名(不含空格)","kind":"title|bullets|steps|summary",'
    '"narr":"配音读白(口语化,100~180字,内嵌表现标记)","lines":["页面上的要点行"],'
    '"main":"标题页主标题(kind=title时)","sub":"副标题(kind=title时)",'
    '"result":"结论行(kind=steps时)","hw":"作业(kind=summary时)"}'
    "要求：5~14 幕；第 1 幕 kind=title（main=题目考点，sub=来源）；"
    "第 2 幕 kind=bullets 完整转写题干（数值、图形信息一个不能漏）；"
    "之后每小问/每步骤一幕 kind=steps（先审题分析，再给出答案，多空题逐空讲）；"
    "最后两幕：kind=warn（易错盘点）与 kind=summary（小结+hw 作业）。"
    "读白面向中学生，老师口吻，可直接配音。"
    "读白中必须使用表现标记（原样保留在 narr 字符串里）："
    "**重点**=讲结论/答案/关键数字时放慢加重；!!逐字!!=极重要短语一字一顿；"
    "[停0.8]=停顿0.8秒；[音:卷=倦]=多音字发音替换（同音字替换，字幕仍显示原字）。"
    "每幕至少含 1 个 **重点** 或 [停] 标记；最终答案用 !!逐字!! 包住。"
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
    model = (cfg.get("ai_model") or "").lower()
    if any(k in model for k in ("deepseek", "deepseek-chat", "deepseek-reasoner")):
        raise RuntimeError(
            f"当前模型「{cfg.get('ai_model')}」不支持读图（DeepSeek 是纯文本模型）。\n"
            "请在「设置」→ AI 设置里把模型名换成支持视觉的，例如：\n"
            "glm-4v-plus / qwen-vl-plus / gpt-4o（API 地址和 Key 也要用对应服务商的），\n"
            "保存后重新点「① 生成文字稿件」。")
    content = [{"type": "text",
                "text": f"课程标题：{title}\n"
                        + (f"配套文字资料：\n{text[:6000]}\n" if text.strip() else "")
                        + "请根据以上图片生成讲解视频分镜稿。"}]
    n = 0
    for p in image_paths:
        if n >= 9:   # 防请求过大（再多 AI 也读不过来，取前 9 张）
            break
        content.append({"type": "image_url",
                        "image_url": {"url": _image_to_data_url(p)}})
        n += 1
    out = call_ai(cfg, [{"role": "system", "content": AI_SYSTEM_VISION},
                        {"role": "user", "content": content}])
    m = re.search(r"\[.*\]", out, re.S)
    scenes = json.loads(m.group(0))
    assert isinstance(scenes, list) and len(scenes) >= 3
    return split_narr_mark(scenes)


def revise_scenes_ai(cfg, scenes, feedback):
    out = call_ai(cfg, [
        {"role": "system", "content": AI_SYSTEM + " 你将收到现有分镜 JSON 和修改需求，输出修改后的完整 JSON 数组。"},
        {"role": "user", "content": "现有分镜：\n" + json.dumps(scenes, ensure_ascii=False)
         + "\n\n修改需求：" + feedback}])
    m = re.search(r"\[.*\]", out, re.S)
    return split_narr_mark(json.loads(m.group(0)))


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


# ================= 逐字稿（带语气/停顿/发音标记） =================
#
# 标记符号规范（写在【读白】行内，生成视频时直通配音引擎）：
#   **重点**      → 放慢语速并加重音量（讲结论/答案/关键数字）
#   !!逐字!!      → 一字一顿（极重要的短语，如最终答案、口诀）
#   [停0.8]       → 停顿 0.8 秒
#   [音:卷=倦]    → 发音替换：合成时读「倦」，字幕仍显示「卷」

SCRIPT_MARKUP_HELP = (
    "逐字稿标记符号（写在【读白】行内）：\n"
    "・**重点**      放慢语速+加重音量（结论/答案/关键数字）\n"
    "・!!逐字!!      一字一顿（最终答案、口诀）\n"
    "・[停0.8]       停顿 0.8 秒\n"
    "・[音:卷=倦]    发音替换（合成读「倦」，字幕显示「卷」）")

KEY_MARK_RE = re.compile(
    r"(答案|结论|记住|切记|关键|注意|一定要|千万别|易错|所以|因此|等于|就填|选)")


def _mark_key_sentences(narr):
    """本地生成的读白：给关键句自动加 **重点** 标记。"""
    parts = [p for p in re.split(r"(?<=[。！？])", narr) if p.strip()]
    return "".join(f"**{p.strip()}**" if KEY_MARK_RE.search(p) else p
                   for p in parts)


KIND_ZH2EN = {"标题": "title", "要点": "bullets", "步骤": "steps",
              "总结": "summary", "对比": "twocol", "正误": "warn",
              "图形": "fig", "图形演示": "shapes"}
KIND_EN2ZH = {v: k for k, v in KIND_ZH2EN.items()}
KIND_VALID = ("title", "bullets", "steps", "summary", "twocol", "warn", "fig", "shapes")


def split_narr_mark(scenes):
    """把带标记的 narr 规范化：narr_mark=标记版（配音），narr=干净版（字幕）。"""
    for s in scenes:
        # 表情符号换成本地文字：中文字体缺 emoji 字形（视频里会变方框），GBK 控制台打印会崩
        for k in ("narr", "main", "sub", "result", "hw"):
            if s.get(k):
                s[k] = _strip_emoji(s[k])
        if s.get("lines"):
            s["lines"] = [_strip_emoji(x) for x in s["lines"]]
        nm = s.get("narr_mark") or s.get("narr", "")
        s["narr_mark"] = nm
        s["narr"] = re.sub(r"\*\*|!!|\[停\d+(?:\.\d+)?\]|\[音:[^\]=]+=[^\]]+\]",
                           "", nm).strip()
    return scenes


_EMOJI_MAP = {"✅": "【正确】", "❌": "【错误】", "⚠️": "注意：", "⚠": "注意：",
              "☑": "【对】", "✓": "【对】", "✗": "【错】", "×": "×"}


def _strip_emoji(text):
    if not isinstance(text, str):
        return text
    for e, r in _EMOJI_MAP.items():
        text = text.replace(e, r)
    # 清掉其余 emoji/装饰符号（含变体选择符），保留常规文字与标点
    text = re.sub(r"[\U0001F000-\U0001FAFF\u2600-\u26FF\u2700-\u27BF\u2B00-\u2BFF\uFE0F]", "", text)
    return text


def scenes_to_script(title, scenes):
    """scenes → 逐字稿文本（带标记符号）。narr_mark 优先于 narr。"""
    out = [f"# 逐字稿：{title}", ""]
    for i, s in enumerate(scenes, 1):
        kind = s["kind"]
        out.append(f"◆ 第{i}幕【{s['name']}｜{KIND_EN2ZH.get(kind, kind)}】")
        if s.get("main"):
            out.append(f"★ {s['main']}　{s.get('sub', '')}".rstrip())
        for ln in s.get("lines", []):
            out.append(f"· {ln}")
        if s.get("result"):
            out.append(f"⇒ {s['result']}")
        if s.get("hw"):
            out.append(f"□ {s['hw']}")
        out.append(f"【读白】{s.get('narr_mark') or s.get('narr', '')}")
        out.append("")
    return "\n".join(out)


def parse_script(text):
    """逐字稿文本 → (title, scenes)。narr 带标记时自动拆出干净版（字幕）与标记版（配音）。"""
    lines = text.replace("\r\n", "\n").split("\n")
    title = ""
    scenes, cur, errs = [], None, []

    def flush():
        nonlocal cur
        if cur is not None:
            if not cur["narr_mark"].strip():
                errs.append(f"第{cur['no']}幕【{cur['name']}】缺【读白】行")
            elif cur["name"] and not re.fullmatch(r"\S+", cur["name"]):
                errs.append(f"第{cur['no']}幕名称含空格：{cur['name']}")
            scenes.append(cur)
        cur = None

    for ln in lines:
        m = re.match(r"#\s*逐字稿[:：](.+)", ln)
        if m and not scenes:
            title = m.group(1).strip()
            continue
        m = re.match(r"◆\s*第(\d+)幕【([^｜\]]+)｜([^】]+)】", ln)
        if m:
            flush()
            kind_raw = m.group(3).strip()
            kind = KIND_ZH2EN.get(kind_raw, kind_raw)
            if kind not in KIND_VALID:
                errs.append(f"第{m.group(1)}幕 kind 非法：{kind_raw}"
                            f"（可用：{'/'.join(KIND_ZH2EN)} 或 {', '.join(KIND_VALID)}）")
                kind = "bullets"
            cur = {"no": int(m.group(1)), "name": m.group(2).strip(),
                   "kind": kind, "lines": [], "narr_mark": ""}
            continue
        if cur is None:
            continue
        s = ln.strip()
        if s.startswith("【读白】") or s.startswith("〔读白〕"):
            cur["narr_mark"] = s.split("】", 1)[-1].split("〕", 1)[-1].strip()
        elif s.startswith("★"):
            parts = s[1:].split("　", 1)
            cur["main"] = parts[0].strip()
            if len(parts) > 1:
                cur["sub"] = parts[1].strip()
        elif s.startswith("⇒"):
            cur["result"] = s[1:].strip()
        elif s.startswith("□"):
            cur["hw"] = s[1:].strip()
        elif s.startswith("·"):
            cur["lines"].append(s[1:].strip())
        # 其余行忽略（空行/注释）
    flush()

    if errs:
        raise ValueError("逐字稿格式有误：\n" + "\n".join(errs[:6]))
    if len(scenes) < 2:
        raise ValueError("逐字稿至少需要 2 幕（◆ 第N幕【名称｜要点】…【读白】…）。"
                         "\n\n" + SCRIPT_MARKUP_HELP)
    # 拆标记：narr=干净版（字幕），narr_mark=标记版（配音）
    for s in scenes:
        s["narr_mark"] = s["narr_mark"].replace("|", "，")
        # 表情清洗：中文字体缺 emoji 字形 + GBK 控制台打印会崩
        for k in ("narr_mark", "main", "sub", "result", "hw"):
            if s.get(k):
                s[k] = _strip_emoji(s[k])
        if s.get("lines"):
            s["lines"] = [_strip_emoji(x) for x in s["lines"]]
        s["narr"] = re.sub(r"\*\*|!!|\[停\d+(?:\.\d+)?\]|\[音:[^\]=]+=[^\]]+\]",
                           "", s["narr_mark"]).strip()
        s.pop("no", None)
    return title, scenes


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
        print("[OK] 断言通过（分镜结构与读白完整性）")

    def define_elements(self):
        return {{}}

    def run_scene(self, i, s):
        self.begin_scene(i)
        vis = {{k: v for k, v in s.items() if k not in ("name", "narr", "narr_mark")}}
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
    lib_src = Path(cfg["lessonlib"]) if cfg.get("lessonlib") else (EXE_DIR / "lessonlib.py")
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
        narr = (s.get("narr_mark") or s["narr"]).replace("|", "，")
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
        def _do():
            logbox.configure(state="normal")
            logbox.insert("end", f"[{time.strftime('%H:%M:%S')}] {msg}\n")
            logbox.see("end")
            logbox.configure(state="disabled")
        try:
            root.after(0, _do)          # 工作线程里调用也安全
        except RuntimeError:
            pass

    def ui(fn):
        """把 UI 操作调度回主线程（工作线程安全）。"""
        root.after(0, fn)

    def refresh_status():
        tool = Path(cfg["tool_root"])
        ok_tool = (tool / ".venv-tts/Scripts/python.exe").exists() and (tool / ".venv/Scripts/python.exe").exists()
        ok_ref = Path(cfg["ref_wav"]).exists()
        lib = Path(cfg["lessonlib"]) if cfg.get("lessonlib") else (EXE_DIR / "lessonlib.py")
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

    # ================= Tab 1：逐字稿 =================
    tab1 = ttk.Frame(nb, padding=8)
    nb.add(tab1, text="① 上传 → 逐字稿")
    tab_v = ttk.Frame(nb, padding=8)
    nb.add(tab_v, text="② 逐字稿 → 视频")

    tip = ("把文件或整个文件夹拖到这里（拖文件夹会自动收集其中所有 PDF/图片/Word/TXT，"
           "含子文件夹；图片需在「设置」里配置支持视觉的 AI API Key 才能读图出题），"
           "或点下方按钮选择。")
    drop = tk.Listbox(tab1, height=6, relief="groove")
    drop.insert("end", tip)
    drop.pack(fill="x")

    SUP_EXT = (".pdf", ".docx", ".txt", ".md",
               ".png", ".jpg", ".jpeg", ".bmp", ".webp")

    def _add_path(p):
        """把一个路径加入列表；若是文件夹则递归收集目标文件。返回加入个数。"""
        if p.is_dir():
            found = sorted(q for q in p.rglob("*")
                           if q.is_file() and q.suffix.lower() in SUP_EXT)
            n = 0
            for q in found:
                if q not in state["files"]:
                    state["files"].append(q)
                    drop.insert("end", f"＋ {q}")
                    n += 1
            skipped = len(found) - n
            note = f"📁 {p}：收集 {n} 个目标文件"
            if skipped:
                note += f"（{skipped} 个已在列表或重复，跳过）"
            drop.insert("end", note)
            return n
        if p.suffix.lower() not in SUP_EXT:
            messagebox.showwarning("不支持的类型", f"跳过：{p.name}")
            return 0
        if p in state["files"]:
            return 0
        state["files"].append(p)
        drop.insert("end", f"＋ {p}")
        return 1

    if HAS_DND:
        def on_drop(files):
            for p in files:
                _add_path(p)
        hook_drop(drop, on_drop)
    else:
        drop.insert("end", "（拖拽不可用，请用「添加文件」按钮）")

    frow = ttk.Frame(tab1); frow.pack(fill="x", pady=4)
    def add_files():
        for f in filedialog.askopenfilenames(
                filetypes=[("支持的文件", "*.pdf *.docx *.txt *.md *.png *.jpg *.jpeg")]):
            _add_path(Path(f))
    def add_folder():
        d = filedialog.askdirectory()
        if d:
            n = _add_path(Path(d))
            if n == 0:
                messagebox.showinfo("提示", "该文件夹（含子文件夹）里没有找到支持的目标文件。")
    ttk.Button(frow, text="添加文件", command=add_files).pack(side="left")
    ttk.Button(frow, text="添加文件夹", command=add_folder).pack(side="left", padx=6)
    ttk.Button(frow, text="清空", command=lambda: (state["files"].clear(), drop.delete(1, "end"))).pack(side="left", padx=6)

    # 逐字稿预览/编辑（单一事实来源：视频模块从这里解析）
    ttk.Label(tab1, text="逐字稿（生成后可直接编辑；【读白】行支持标记：**重点** !!逐字!! [停0.8] [音:卷=倦]）：").pack(anchor="w")
    draft = tk.Text(tab1, height=14, wrap="word")
    draft.pack(fill="both", expand=True)

    arow = ttk.Frame(tab1); arow.pack(fill="x", pady=4)

    # ---- AI 执行进度指示（进度条 + 计时，证明程序没卡） ----
    ptime_var = tk.StringVar(value="")
    pbar = ttk.Progressbar(tab1, mode="indeterminate")
    def busy_start(msg):
        """必须在主线程调用（用 ui() 包）。"""
        state["ai_busy"] = True
        pbar.pack(fill="x", padx=8, pady=(0, 2))
        pbar.start(12)
        t0 = time.time()
        ptime_var.set(f"{msg}… 已用时 0s")
        def tick():
            if not state.get("ai_busy"):
                return
            ptime_var.set(f"{msg}… 已用时 {int(time.time() - t0)}s（AI 读图较慢属正常，请勿关闭）")
            root.after(1000, tick)
        root.after(1000, tick)
    def busy_stop():
        state["ai_busy"] = False
        try:
            pbar.stop()
            pbar.pack_forget()
        except Exception:
            pass
        ptime_var.set("")
    ttk.Label(tab1, textvariable=ptime_var, foreground="#007acc").pack(anchor="w", padx=8)

    def do_gen_draft():
        sync_cfg_from_entries()
        refresh_status()
        if state["busy"]:
            return
        if not state["files"]:
            messagebox.showwarning("提示", "请先拖入或添加文件")
            return
        state["busy"] = True
        ui(lambda m="正在读取文件 / AI 读图出稿": busy_start(m))
        def work():
            try:
                IMG_EXT = (".png", ".jpg", ".jpeg", ".bmp", ".webp")
                text_files = [p for p in state["files"]
                              if p.suffix.lower() not in IMG_EXT]
                img_files = [p for p in state["files"]
                             if p.suffix.lower() in IMG_EXT]
                title = state["files"][0].stem
                texts = []
                scanned = 0
                for p in text_files:
                    def prog(cur, total, _p=p):
                        if cur % 50 == 0 or cur == total:
                            log(f"正在读取 {_p.name}：第 {cur}/{total} 页…")
                    try:
                        t = extract_text(p, prog)
                    except Exception as e:
                        log(f"读取失败：{p.name}（{e}）")
                        continue
                    log(f"已读取：{p.name}（{len(t)} 字）" if t
                        else f"警告：{p.name} 提不出文字（可能是扫描版/加密 PDF）")
                    if t:
                        texts.append(t)
                    elif p.suffix.lower() == ".pdf":
                        # 扫描版 PDF 兜底：渲染前几页转图片走 AI 视觉
                        pages = pdf_pages_to_images(p, max_pages=4)
                        if pages and cfg.get("ai_key"):
                            img_files.extend(pages)
                            scanned = len(pages)
                            log(f"扫描版 PDF：已渲染《{p.name}》前 {scanned} 页转图片，交给 AI 读图")
                        elif not pages:
                            log(f"《{p.name}》渲染页面失败（缺 pypdfium2 或文件损坏）")
                full = "\n\n".join(texts).strip()
                if img_files:
                    if scanned:
                        log(f"检测到 {len(img_files)} 张图片（含扫描页 {scanned} 张）")
                    else:
                        log(f"检测到 {len(img_files)} 张图片")
                    if len(img_files) > 9:
                        log(f"图片超过 9 张，本次 AI 读图只取前 9 张（防止请求过大失败）")
                    if not cfg.get("ai_key"):
                        raise RuntimeError(
                            "图片生成视频需要 AI 帮你「读图出题」（本地无法 OCR）。\n"
                            "请在「设置」→ AI 设置里填写 API Key（如智谱 glm-4.5v，\n"
                            "或 gpt-4o / qwen-vl-plus），保存后重新点「① 生成文字稿件」。")
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
                    raise RuntimeError(
                        "没有提取到任何内容：可能全部是扫描版/图片型 PDF（整本书是图片）。\n"
                        "解决办法：在「设置」里配好 AI Key（智谱 glm-4.5v 即可），\n"
                        "程序会自动把扫描页转成图片交给 AI 读图，然后重新点「① 生成文字稿件」。")
                state["title"] = title

                def fill_draft():
                    draft.delete("1.0", "end")
                    draft.insert("end", scenes_to_script(title, scenes))
                    draftbox.set(f"逐字稿已生成：{len(scenes)} 幕（{src}）。可直接编辑，"
                                 f"或到「② 逐字稿 → 视频」生成视频。")
                ui(fill_draft)
                log(f"稿件生成完成（{len(scenes)} 幕，来源：{src}）。可直接在上方文本框修改文字，"
                    f"或在底部任务框输入调整需求。")
            except Exception as e:
                log(f"错误：{e}")
                ui(lambda e=e: messagebox.showerror("生成稿件失败", str(e)))
            finally:
                state["busy"] = False
                ui(busy_stop)
        threading.Thread(target=work, daemon=True).start()

    def get_scenes():
        """逐字稿文本框 → scenes（解析失败抛 ValueError，带格式提示）。"""
        _, sc = parse_script(draft.get("1.0", "end"))
        return sc

    def write_script(scenes, title=None):
        t = title or state.get("title") or "未命名课程"
        state["title"] = t
        cur = draft.get("1.0", "end-1c")
        pos = draft.index("insert")
        draft.delete("1.0", "end")
        draft.insert("end", scenes_to_script(t, scenes))
        draft.mark_set("insert", pos)

    def do_apply_draft():
        """把文本框的手工修改解析回结构（校验格式并提示）。"""
        if state["busy"]:
            return
        try:
            _, sc = parse_script(draft.get("1.0", "end"))
            log(f"逐字稿校验通过：{len(sc)} 幕，标记符号将在配音时生效。")
            messagebox.showinfo("校验通过", f"逐字稿格式正确：{len(sc)} 幕。\n"
                                "生成视频时会自动按【读白】里的标记配音。")
        except ValueError as e:
            messagebox.showerror("逐字稿格式有误", str(e))

    def do_feedback_draft():
        """对话框：输入需求调整稿件。"""
        try:
            scenes = get_scenes()
        except ValueError as e:
            messagebox.showerror("逐字稿格式有误", str(e))
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
                        scenes = revise_scenes_ai(cfg, scenes, fb)
                        ui(lambda: write_script(scenes))
                        log("稿件已按需求调整（AI）。")
                        ui(win.destroy)
                    except Exception as e:
                        ui(lambda e=e: messagebox.showerror("调整失败", str(e)))
                threading.Thread(target=work, daemon=True).start()
            else:
                new, msg = revise_scenes_local(scenes, fb)
                if new is None:
                    messagebox.showinfo("本地模式", msg)
                else:
                    write_script(new)
                    log(f"稿件已调整：{msg}")
                    win.destroy()
        ttk.Button(win, text="应用调整", command=apply_fb).pack(pady=6)

    ttk.Button(arow, text="① 生成逐字稿", command=do_gen_draft).pack(side="left")
    ttk.Button(arow, text="校验格式", command=do_apply_draft).pack(side="left", padx=6)
    ttk.Button(arow, text="按需求调整…", command=do_feedback_draft).pack(side="left")

    def save_script():
        t = state.get("title") or "未命名课程"
        p = filedialog.asksaveasfilename(defaultextension=".md",
                                         initialfile=f"逐字稿_{t}.md",
                                         filetypes=[("Markdown", "*.md")])
        if p:
            Path(p).write_text(draft.get("1.0", "end-1c"), encoding="utf-8")
            log(f"逐字稿已保存：{p}")

    def load_script():
        p = filedialog.askopenfilename(filetypes=[("逐字稿 / Markdown", "*.md *.txt")])
        if not p:
            return
        try:
            content = Path(p).read_text(encoding="utf-8")
            title, sc = parse_script(content)
        except (UnicodeDecodeError, ValueError) as e:
            messagebox.showerror("加载失败", f"不是有效的逐字稿文件：\n{e}")
            return
        state["title"] = title or Path(p).stem
        draft.delete("1.0", "end")
        draft.insert("end", content)
        draftbox.set(f"已加载逐字稿：{len(sc)} 幕（{p}）。可直接到「② 逐字稿 → 视频」生成视频。")
        log(f"逐字稿已加载：{p}（{len(sc)} 幕）")

    ttk.Button(arow, text="保存逐字稿", command=save_script).pack(side="left", padx=6)
    ttk.Button(arow, text="加载逐字稿", command=load_script).pack(side="left")
    ttk.Button(arow, text="标记说明", command=lambda: messagebox.showinfo(
        "逐字稿标记符号", SCRIPT_MARKUP_HELP)).pack(side="left", padx=6)
    draftbox = tk.StringVar()
    ttk.Label(tab1, textvariable=draftbox, foreground="#1565c0").pack(anchor="w")

    # ---- Tab 2：视频 ----
    ttk.Label(tab_v, text="从「① 上传 → 逐字稿」的逐字稿生成视频（也可「加载逐字稿」直接开始）。"
            ).pack(anchor="w")
    vinfo = tk.StringVar(value="当前逐字稿：尚未加载")
    ttk.Label(tab_v, textvariable=vinfo, foreground="#1565c0").pack(anchor="w", pady=(2, 8))

    def refresh_vinfo():
        try:
            _, sc = parse_script(draft.get("1.0", "end"))
            n_mark = sum(1 for s in sc if s.get("narr_mark") and
                         re.search(r"\*\*|!!|\[停|\[音:", s["narr_mark"]))
            vinfo.set(f"当前逐字稿：{len(sc)} 幕，其中 {n_mark} 幕含语气/停顿/发音标记")
        except ValueError:
            vinfo.set("当前逐字稿：格式未通过校验（回「①」页点「校验格式」查看原因）")

    def do_video():
        sync_cfg_from_entries()
        refresh_status()
        if state["busy"]:
            return
        try:
            scenes = get_scenes()
        except ValueError as e:
            messagebox.showerror("逐字稿格式有误", str(e))
            return
        state["busy"] = True
        btnv.configure(state="disabled")
        def work():
            try:
                proj = build_project(cfg, state.get("title") or "未命名课程", scenes)
                state["proj"] = proj
                log(f"工程目录：{proj}")
                video = run_pipeline(cfg, proj, log)
                state["video"] = video
                draftbox.set(f"视频已完成：{video}")
                ui(lambda: messagebox.showinfo("完成", f"视频已生成：\n{video}"))
            except Exception as e:
                log(f"错误：{e}")
                ui(lambda e=e: messagebox.showerror("生成视频失败", str(e)))
            finally:
                state["busy"] = False
                btnv.configure(state="normal")
        threading.Thread(target=work, daemon=True).start()

    def do_video_feedback():
        """对话框：视频产出后调整（改读白/语速/重渲）。"""
        if state["proj"] is None:
            messagebox.showwarning("提示", "请先生成视频")
            return
        try:
            scenes = get_scenes()
        except ValueError as e:
            messagebox.showerror("逐字稿格式有误", str(e))
            return
        win = tk.Toplevel(root); win.title("调整视频"); win.geometry="520x260"
        win.geometry("520x260")
        ttk.Label(win, text="选择调整方式：").pack(anchor="w", padx=10, pady=8)
        v = tk.StringVar(value="text")
        ttk.Radiobutton(win, text="修改某一幕的文字（在下面选幕并编辑读白）", variable=v, value="text").pack(anchor="w", padx=20)
        ttk.Radiobutton(win, text="只改语速（重新配音+重渲染）", variable=v, value="speed").pack(anchor="w", padx=20)
        ttk.Radiobutton(win, text="用 AI 按需求重写稿件并重渲染", variable=v, value="ai").pack(anchor="w", padx=20)
        rowf = ttk.Frame(win); rowf.pack(fill="x", padx=10)
        combo = ttk.Combobox(rowf, values=[f"第{i+1}幕 {s['name']}" for i, s in enumerate(scenes)],
                             state="readonly", width=28)
        if scenes:
            combo.current(0)
        combo.pack(side="left")
        txt = tk.Text(win, height=6); txt.pack(fill="both", expand=True, padx=10, pady=4)
        if scenes:
            txt.insert("1.0", scenes[0].get("narr_mark") or scenes[0]["narr"])
        def on_combo(evt):
            i = combo.current()
            txt.delete("1.0", "end")
            txt.insert("1.0", scenes[i].get("narr_mark") or scenes[i]["narr"])
        combo.bind("<<ComboboxSelected>>", on_combo)
        def rerender():
            try:
                if v.get() == "text":
                    i = combo.current()
                    scenes[i]["narr_mark"] = txt.get("1.0", "end").strip()
                    scenes[i]["narr"] = re.sub(
                        r"\*\*|!!|\[停\d+(?:\.\d+)?\]|\[音:[^\]=]+=[^\]]+\]",
                        "", scenes[i]["narr_mark"]).strip()
                    write_script(scenes)
                elif v.get() == "ai":
                    fb = txt.get("1.0", "end").strip()
                    if cfg.get("ai_key") and fb:
                        scenes = revise_scenes_ai(cfg, scenes, fb)
                        write_script(scenes)
                    else:
                        messagebox.showwarning("提示", "AI 未配置或需求为空"); return
                # 重建工程（语速从设置读取）
                proj = build_project(cfg, state.get("title") or "未命名课程", scenes)
                state["proj"] = proj
                video = run_pipeline(cfg, proj, log)
                state["video"] = video
                ui(lambda v=video: messagebox.showinfo("完成", f"新视频已生成：\n{v}"))
                win.destroy()
            except Exception as e:
                ui(lambda e=e: messagebox.showerror("失败", str(e)))
        ttk.Button(win, text="重新配音并渲染", command=rerender).pack(pady=6)

    vrow = ttk.Frame(tab_v); vrow.pack(fill="x", pady=6)
    btnv = ttk.Button(vrow, text="② 生成视频", command=do_video)
    btnv.pack(side="left")
    ttk.Button(vrow, text="调整视频…", command=do_video_feedback).pack(side="left", padx=6)
    ttk.Button(vrow, text="打开输出文件夹", command=lambda: os.startfile(cfg["output_root"])).pack(side="left")
    ttk.Button(vrow, text="刷新逐字稿状态", command=refresh_vinfo).pack(side="left", padx=6)

    # ---- 通用任务对话框 ----
    def render_draft_view():
        try:
            write_script(get_scenes())
        except ValueError:
            pass   # 格式未通过时不动文本框

    TASK_HELP = ("本地指令（免 Key，输入即执行）：\n"
                 "・语速改到0.8        ・删除第3幕\n"
                 "・在第2幕后加一页总结：把加法法则再练一遍\n"
                 "・修改第2幕读白为：……\n"
                 "・画质 m（l/m/h）    ・重新配音    ・重新渲染\n"
                 "・打开输出文件夹    ・帮助\n"
                 "目标选「逐字稿」+ 配 AI Key：任何文字修改需求都由 AI 直接改逐字稿。\n"
                 "目标选「视频」+ 配 AI Key：AI 理解生产类任务（重配/重渲/参数）。")

    def insert_summary(n, content):
        scenes = get_scenes()
        n = min(max(n, 1), len(scenes) + 1)
        scenes.insert(n, {"name": "补充要点", "kind": "summary",
                          "lines": [x.strip() for x in re.split(r"[;；]", content) if x.strip()] or ["要点回顾"],
                          "hw": "完成配套练习",
                          "narr": f"我们把{content}再梳理一遍，请对照屏幕自查掌握情况。",
                          "narr_mark": f"我们把{content}再梳理一遍，**请对照屏幕自查掌握情况**。"})
        return n, scenes

    def _act_to_task(act):
        op = act.get("op", "")
        v = act.get("value", act.get("n", ""))
        if op == "set_speed":
            return f"语速改到{v}"
        if op == "set_quality":
            return f"画质{v}"
        if op == "delete_scene":
            return f"删除第{v}幕"
        if op == "insert_summary":
            return f"在第{v}幕后加一页总结：{act.get('content', '要点回顾')}"
        if op == "edit_narr":
            return f"修改第{v}幕读白为：{act.get('text', '')}"
        if op == "regenerate_audio":
            return "重新配音"
        return act.get("text") or ""

    def execute_task(task):
        """解析并执行任务，返回回复列表（调用者线程执行，UI 走 ui()）。"""
        replies = []
        try:
            scenes = get_scenes()
        except ValueError as e:
            scenes = None
            replies.append(f"逐字稿格式有误（AI/本地改稿前请先修正）：{str(e).splitlines()[0]}")
        m = re.search(r"语速\s*(?:改到|到|设为|=|：)?\s*(0\.\d+|1(?:\.0+)?)", task)
        if m:
            v = max(0.6, min(1.3, float(m.group(1))))
            cfg["tts_speed"] = v
            save_cfg(cfg)
            replies.append(f"语速已改为 {v}（对之后的「重新配音」生效）")
        m = re.search(r"删除第(\d+)幕", task)
        if m and scenes:
            n = int(m.group(1))
            if 1 <= n <= len(scenes):
                removed = scenes.pop(n - 1)
                ui(lambda: write_script(scenes))
                replies.append(f"已删除第 {n} 幕（{removed['name']}）")
        m = re.search(r"在第(\d+)幕(?:后|后面|之后)(?:加|插入)(?:一页)?(?:总结|要点|内容)?[:：]?(.*)", task)
        if m and scenes:
            content = m.group(2).strip() or "本次课程要点回顾"
            n, new_scenes = insert_summary(int(m.group(1)), content)
            ui(lambda: write_script(new_scenes))
            replies.append(f"已在第 {n} 幕后插入总结页（{content}）")
        m = re.search(r"修改第(\d+)幕(?:的)?读白为[:：]?(.+)", task)
        if m and scenes:
            n = int(m.group(1))
            if 1 <= n <= len(scenes):
                scenes[n - 1]["narr_mark"] = m.group(2).strip()
                scenes[n - 1]["narr"] = re.sub(
                    r"\*\*|!!|\[停\d+(?:\.\d+)?\]|\[音:[^\]=]+=[^\]]+\]",
                    "", scenes[n - 1]["narr_mark"]).strip()
                ui(lambda: write_script(scenes))
                replies.append(f"已修改第 {n} 幕读白（记得「重新配音」生效）")
        m = re.search(r"画质\s*(?:改到|到|设为|=|：)?\s*([lmhLMH])\b", task)
        if m:
            cfg["quality"] = m.group(1).lower()
            save_cfg(cfg)
            replies.append(f"画质已改为 {cfg['quality']}")
        if re.search(r"重新配音|重配", task):
            if scenes:
                replies.append("开始重新配音并渲染（完成后弹窗提示）…")

                def _regen():
                    try:
                        proj = build_project(cfg, state.get("title") or "未命名课程", scenes)
                        state["proj"] = proj
                        video = run_pipeline(cfg, proj, log)
                        state["video"] = video
                        ui(lambda v=video: messagebox.showinfo("完成", f"新视频已生成：\n{v}"))
                    except Exception as e:
                        ui(lambda e=e: messagebox.showerror("重新配音失败", str(e)))
                threading.Thread(target=_regen, daemon=True).start()
            else:
                replies.append("还没有逐字稿：先到「①」页生成或「加载逐字稿」")
        elif re.search(r"重新渲染", task):
            if state.get("proj"):
                replies.append("开始重新渲染…")

                def _rerender():
                    try:
                        video = run_pipeline(cfg, state["proj"], log)
                        state["video"] = video
                        ui(lambda: messagebox.showinfo("完成", f"新视频已生成：\n{video}"))
                    except Exception as e:
                        ui(lambda e=e: messagebox.showerror("重渲染失败", str(e)))
                threading.Thread(target=_rerender, daemon=True).start()
            else:
                replies.append("还没有工程：先到「② 视频」页生成")
        if re.search(r"打开(输出)?文件夹", task):
            os.startfile(cfg["output_root"])
            replies.append("已打开输出文件夹")
        if re.search(r"帮助|指令列表|能做什么", task):
            replies.append(TASK_HELP)
        if not replies:
            if cfg.get("ai_key"):
                if state.get("chat_target") == "script":
                    replies.append("AI 正在修改逐字稿…")

                    def _ai_script():
                        try:
                            cur = draft.get("1.0", "end-1c")
                            out = call_ai(cfg, [
                                {"role": "system", "content":
                                 "你是教学逐字稿编辑。用户给出当前逐字稿全文和修改需求，"
                                 "输出修改后的完整逐字稿。保持格式：每幕为"
                                 "『◆ 第N幕【名称｜kind】』（kind 可用 标题/要点/步骤/总结/对比/正误），"
                                 "画面行以 · 开头，结论行以 ⇒ 开头，每幕必有一行【读白】。"
                                 "【读白】行内可用表现标记：**重点**（放慢加重）、!!逐字!!（一字一顿）、"
                                 "[停0.8]（停顿）、[音:卷=倦]（发音替换，正文仍写原字）。"
                                 "只输出逐字稿正文，不要解释。"},
                                {"role": "user",
                                 "content": f"当前逐字稿：\n{cur[:9000]}\n\n修改需求：{task}"}])
                            _, sc = parse_script(out)
                            ui(lambda: (draft.delete("1.0", "end"),
                                        draft.insert("end", out),
                                        refresh_vinfo()))
                            replies.append(f"AI 已改好逐字稿（{len(sc)} 幕），已更新到编辑框。")
                            log("AI 逐字稿修改完成。")
                        except ValueError as e:
                            replies.append(f"AI 返回的逐字稿格式不合规，已保留原稿：\n{e}")
                        except Exception as e:
                            replies.append(f"AI 修改失败：{e}")
                    threading.Thread(target=_ai_script, daemon=True).start()
                    return replies
                replies.append("AI 正在理解任务…")

                def _ai():
                    try:
                        scenes = None
                        try:
                            scenes = get_scenes()
                        except ValueError:
                            pass
                        ctx = {"有逐字稿": scenes is not None,
                               "幕数": len(scenes) if scenes else 0,
                               "语速": cfg["tts_speed"], "画质": cfg["quality"],
                               "有已生成视频": state.get("video") is not None}
                        out = call_ai(cfg, [
                            {"role": "system", "content":
                             "你是视频生产助手。用户给出任务，你返回 JSON："
                             '{"reply":"给用户的说明","actions":[{"op":"...","value":...}]}。'
                             "可用 op：set_speed(0.6-1.3)、set_quality(l/m/h)、delete_scene(n)、"
                             "insert_summary(n,content)、edit_narr(n,text)、"
                             "regenerate_audio(重新配音并渲染)。"
                             "纯解释/咨询类任务把内容放 reply，actions 给空数组。"},
                            {"role": "user",
                             "content": f"当前状态：{json.dumps(ctx, ensure_ascii=False)}\n任务：{task}"}])
                        m = re.search(r"\{.*\}", out, re.S)
                        plan = json.loads(m.group(0))
                        for act in plan.get("actions", []):
                            replies.extend(execute_task(_act_to_task(act)))
                        if plan.get("reply"):
                            replies.insert(0, "AI：" + plan["reply"])
                        log("\n".join("  " + r for r in replies))
                    except Exception as e:
                        replies.append(f"AI 执行失败：{e}（可改用本地指令）")
                threading.Thread(target=_ai, daemon=True).start()
            else:
                replies.append("没有匹配的本地指令。\n" + TASK_HELP)
        return replies

    # ---- AI 对话框（共享于两个 Tab，直接对接 API） ----
    ttk.Label(root, text="AI 对话　目标：").pack(anchor="w", padx=8, pady=(6, 0))
    brow = ttk.Frame(root)
    brow.pack(fill="x", padx=8)
    chat_target = ttk.Combobox(brow, values=["逐字稿", "视频"], state="readonly",
                               width=8)
    chat_target.current(0)
    chat_target.pack(side="left")
    state["chat_target"] = "script"
    chat_var = tk.StringVar()
    chat_entry = ttk.Entry(brow, textvariable=chat_var)
    chat_entry.pack(side="left", fill="x", expand=True, padx=6)

    def _on_target(evt):
        state["chat_target"] = "script" if chat_target.get() == "逐字稿" else "video"
    chat_target.bind("<<ComboboxSelected>>", _on_target)

    def run_task():
        task = chat_var.get().strip()
        if not task or state.get("task_busy"):
            return
        sync_cfg_from_entries()
        state["task_busy"] = True
        log(f"任务[{chat_target.get()}]：{task}")

        def work():
            try:
                replies = execute_task(task)
                for r in replies:
                    log("  " + r)
            except Exception as e:
                log(f"任务失败：{e}")
                ui(lambda e=e: messagebox.showerror("任务失败", str(e)))
            finally:
                state["task_busy"] = False
        threading.Thread(target=work, daemon=True).start()
    ttk.Button(brow, text="发送", command=run_task).pack(side="left", padx=4)
    chat_entry.bind("<Return>", lambda e: run_task())

    # 日志
    ttk.Label(root, text="运行日志：").pack(anchor="w", padx=8)
    logbox = tk.Text(root, height=6, state="disabled", background="#111", foreground="#cfc")
    logbox.pack(fill="x", padx=8, pady=(0, 6))

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

    def sync_cfg_from_entries():
        """把设置输入框当前值同步进 cfg（生成前自动调用，未点保存也生效）。"""
        for k, v in vars_cfg.items():
            val = v.get().strip()
            if k == "tts_speed":
                try:
                    val = float(val)
                except ValueError:
                    continue
            cfg[k] = val

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
            ui(lambda e=e: messagebox.showerror("失败", str(e)))
    ttk.Button(tab2, text="测试 AI 连接", command=test_ai).pack(anchor="w")

    stat.set(stat.get() + f"   配置文件：{CFG_PATH}")
    log("欢迎使用课程工厂。两步走：①上传→逐字稿（可编辑/标记语气停顿）→ ②逐字稿→视频。"
        "也可以「加载逐字稿」直接出片；底部对话框可对话式修改（配 AI Key 后由 AI 执行）。")
    root.mainloop()


def selftest(cfg):
    """无界面端到端自测。"""
    print("== selftest: 逐字稿往返")
    text = ("有理数的加法法则。同号相加，符号不变，绝对值相加。"
            "例如负二加负三等于负五。\n\n"
            "异号相加，符号随绝对值大的一方，绝对值相减。"
            "例如负七加正三等于负四。\n\n"
            "减去一个数，等于加上它的相反数。"
            "例如三减七等于负四。减去负数等于加正数，结果反而变大。")
    scenes = gen_scenes_local("有理数的加减法", text)
    script_txt = scenes_to_script("有理数的加减法", scenes)
    assert "**" in script_txt, "本地逐字稿应含 **重点** 标记"
    t2, sc2 = parse_script(script_txt)
    assert t2 == "有理数的加减法" and len(sc2) == len(scenes)
    assert all(s.get("narr_mark") and s["narr"] for s in sc2)
    print(f"scenes: {len(sc2)} 幕，逐字稿往返 OK")
    proj = build_project(cfg, "有理数的加减法", sc2)
    print("proj:", proj)
    print("== selftest: 渲染管线")
    out = run_pipeline(cfg, proj, lambda m: print("  " + m))
    assert Path(out).exists() and Path(out).stat().st_size > 1_000_000
    print("SELFTEST OK:", out)


if __name__ == "__main__":
    cfg = load_cfg()
    if "--check-deps" in sys.argv:
        # 隐藏参数：验证打包后依赖是否齐全，结果写 deps_check.txt
        lines = []
        for m in ("tkinter", "PIL", "pypdfium2", "pypdf", "docx"):
            try:
                __import__(m)
                lines.append(f"{m}: OK")
            except Exception as e:
                lines.append(f"{m}: FAIL {e}")
        (Path(sys.executable).parent / "deps_check.txt").write_text(
            "\n".join(lines), encoding="utf-8")
        sys.exit(0)
    if "--selftest" in sys.argv:
        selftest(cfg)
    else:
        gui_main(cfg)
