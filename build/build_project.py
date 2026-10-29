# -*- coding: utf-8 -*-
"""build_project.py — 从 lesson_data_1N 生成各节工程（script.py + 分镜.md）
用法：python build_project.py [11|12|13|14|all]
"""
import importlib
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).parent.resolve()

DIRS = {
    "11": "1.1生活中的立体图形",
    "12": "1.2展开与折叠",
    "13": "1.3截一个几何体",
    "14": "1.4从三个方向看物体的形状",
    "21": "2.1有理数",
    "22": "2.2数轴",
    "23": "2.3绝对值",
    "24": "2.4有理数的加法与减法",
    "25": "2.5有理数的乘法与除法",
    "26": "2.6有理数的乘方",
    "27": "2.7科学记数法",
    "28": "2.8有理数的混合运算",
}


def out_base(no: str) -> Path:
    """第二单元（2x）输出到独立的单元目录。"""
    if no.startswith("2"):
        return ROOT.parent / "六年级上册第二单元"
    return ROOT

SCRIPT_TMPL = '''"""
{title} —— 课件式讲解视频（由 build_project.py 生成，请勿手改）
{chapter}
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, r"{extra}")

from lessonlib import *  # noqa: F401,F403
from lessonlib import AUDIO_DIR, TIMELINE, present
from {data_mod} import SCENES

import json


class {scene_cls}(Scene):
    SCENES_META = [(i + 1, s["name"]) for i, s in enumerate(SCENES)]

    # ---------- 基础设施 ----------
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
            print(f"幕内动画 {{used:.2f}}s → 等待 {{remain:.2f}}s")
            self.wait(remain)
        else:
            print(f"[警告] 动画比音频长 {{-remain:.2f}}s")

    def begin_scene(self, n):
        self.add_audio(n)
        self._scene_snapshot = set(id(m) for m in self.mobjects)
        print(f"▶ 幕 {{n}}  ({{self.SCENES_META[n-1][1]}})  音频 {{self.sd(n):.2f}}s")

    def end_scene(self, keep=()):
        keep_ids = {{id(m) for m in keep}}
        new = [m for m in self.mobjects
               if id(m) not in self._scene_snapshot and id(m) not in keep_ids]
        if new:
            self.play(FadeOut(Group(*new)), run_time=0.4)
        return 0.4

    # ---------- 数学断言 ----------
    def calculate_geometry(self):
        self.assert_conditions(None)
        return {{}}

    def assert_conditions(self, g):
        ASSERTS()

    def define_elements(self):
        return {{}}

    # ---------- 主流程 ----------
    def run_scene(self, i, s):
        self.begin_scene(i)
        used = present(self, s["vis"])
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

KIND_DESC = {
    "title": "标题页", "bullets": "要点页", "shapes": "实物图形页",
    "fig": "图示页", "problem": "例题页", "steps": "解题步骤页",
    "twocol": "双栏对照页", "warn": "易错对比页", "summary": "小结页",
}


def gen_storyboard(mod):
    L = mod.LESSON
    lines = []
    lines.append(f"# 分镜脚本 - {L['title']}")
    lines.append("")
    lines.append("## 基本信息")
    lines.append(f"- 教材：{L['chapter']} {L['title']}")
    lines.append(f"- 场景数：{len(mod.SCENES)}")
    lines.append(f"- 预估时长：{L['duration_hint']}")
    lines.append("- 配音：clone（我的声线）")
    lines.append("")
    lines.append("## 学习目标")
    for g in L["goals"]:
        lines.append(f"- {g}")
    lines.append("")
    lines.append("## 数学事实与断言")
    lines.append("- 渲染前执行数据文件中的 ASSERTS()（公式/计数/一致性断言），有错即中止")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 分镜设计")
    lines.append("")
    for i, s in enumerate(mod.SCENES, start=1):
        topic = f"（{s['topic']}）" if s.get("topic") else ""
        lines.append(f"### 第{i}幕：{s['name']}{topic}")
        lines.append(f"**画面**: {KIND_DESC.get(s['vis']['kind'], s['vis']['kind'])}")
        lines.append(f"**读白**: {s['narr']}")
        lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 音频生成清单（步骤4填写）")
    lines.append("")
    lines.append("| 幕号 | 文件名 | 读白文本 | 时长 | 说话人 |")
    lines.append("|------|--------|----------|------|--------|")
    for i, s in enumerate(mod.SCENES, start=1):
        fname = f"audio_{i:03d}_{s['name']}.mp3"
        narr = s["narr"].replace("|", "，")
        lines.append(f"| {i} | {fname} | \"{narr}\" |  | clone |")
    lines.append("")
    return "\n".join(lines)


def main():
    targets = sys.argv[1:] if len(sys.argv) > 1 else ["all"]
    if targets == ["all"]:
        targets = list(DIRS)
    for no in targets:
        mod = importlib.import_module(f"lesson_data_{no}")
        base = out_base(no)
        base.mkdir(parents=True, exist_ok=True)
        # 确保输出根有 lessonlib.py（第二单元目录共享一份）
        lib_src = ROOT / "lessonlib.py"
        lib_dst = base / "lessonlib.py"
        if not lib_dst.exists():
            import shutil
            shutil.copy2(lib_src, lib_dst)
        proj = base / DIRS[no]
        proj.mkdir(parents=True, exist_ok=True)
        # script.py
        script = SCRIPT_TMPL.format(
            title=mod.LESSON["title"], chapter=mod.LESSON["chapter"],
            data_mod=f"lesson_data_{no}", scene_cls=f"Lesson{no}Scene",
            extra=str(ROOT))
        (proj / "script.py").write_text(script, encoding="utf-8")
        # 分镜.md
        (proj / "分镜.md").write_text(gen_storyboard(mod), encoding="utf-8")
        # 断言注入：script.py 需要引用 ASSERTS
        txt = (proj / "script.py").read_text(encoding="utf-8")
        txt = txt.replace(
            f"from lesson_data_{no} import SCENES",
            f"from lesson_data_{no} import SCENES, ASSERTS")
        (proj / "script.py").write_text(txt, encoding="utf-8")
        # 统计时长
        chars = sum(len(s["narr"]) for s in mod.SCENES)
        est = chars / 3.4 / 60  # 老师语速约 3.4 字/秒
        print(f"[OK] {no} {DIRS[no]}：{len(mod.SCENES)} 幕，读白 {chars} 字，"
              f"预计口播约 {est:.1f} 分钟")


if __name__ == "__main__":
    main()
