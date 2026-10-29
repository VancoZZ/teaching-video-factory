# -*- coding: utf-8 -*-
"""build_chem.py — 高中化学习题讲解：从 lesson_data_4N 生成工程（script.py + 分镜.md）
用法：python build_chem.py [41|42|43|44|all]
"""
import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).parent.resolve()

DIRS = {
    "41": "题1_滴定曲线综合题",
    "42": "题2_Ka表格多选",
    "43": "题3_守恒综合题",
    "44": "题4_滴定曲线选择题",
}

SCRIPT_TMPL = '''"""
{title} —— 习题讲解视频（由 build_chem.py 生成，请勿手改）
{chapter}
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lessonlib import *  # noqa: F401,F403
from lessonlib import AUDIO_DIR, TIMELINE, present
from lesson_data_{no} import SCENES, ASSERTS

import json


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
        ASSERTS()

    def define_elements(self):
        return {{}}

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

KIND_DESC = {"title": "标题页", "bullets": "要点页", "shapes": "实物图形页",
             "fig": "图示页", "problem": "例题页", "steps": "解题步骤页",
             "twocol": "双栏对照页", "warn": "易错对比页", "summary": "小结页"}


def gen_storyboard(mod):
    L = mod.LESSON
    lines = [f"# 分镜脚本 - {L['title']}", "",
             "## 基本信息",
             f"- 教材：{L['chapter']}",
             f"- 场景数：{len(mod.SCENES)}",
             "- 配音：clone（我的声线）", "",
             "## 数学/化学断言",
             "- 渲染前执行 ASSERTS()，有错即中止", "",
             "---", "", "## 分镜设计", ""]
    for i, s in enumerate(mod.SCENES, start=1):
        topic = f"（{s['topic']}）" if s.get("topic") else ""
        lines.append(f"### 第{i}幕：{s['name']}{topic}")
        lines.append(f"**画面**: {KIND_DESC.get(s['vis']['kind'], s['vis']['kind'])}")
        lines.append(f"**读白**: {s['narr']}")
        lines.append("")
    lines += ["---", "", "## 音频生成清单", "",
              "| 幕号 | 文件名 | 读白文本 | 时长 | 说话人 |",
              "|------|--------|----------|------|--------|"]
    for i, s in enumerate(mod.SCENES, start=1):
        fname = f"audio_{i:03d}_{s['name'].replace(' ', '_')}.mp3"
        narr = s["narr"].replace("|", "，")
        lines.append(f'| {i} | {fname} | "{narr}" |  | clone |')
    lines.append("")
    return "\n".join(lines)


def main():
    targets = sys.argv[1:] if len(sys.argv) > 1 else ["all"]
    if targets == ["all"]:
        targets = list(DIRS)
    for no in targets:
        mod = importlib.import_module(f"lesson_data_{no}")
        mod.ASSERTS()
        proj = ROOT / DIRS[no]
        proj.mkdir(parents=True, exist_ok=True)
        import shutil
        shutil.copy2(ROOT / "lessonlib.py", proj / "lessonlib.py")
        shutil.copy2(ROOT / f"lesson_data_{no}.py", proj / f"lesson_data_{no}.py")
        script = SCRIPT_TMPL.format(title=mod.LESSON["title"],
                                    chapter=mod.LESSON["chapter"],
                                    no=no, scene_cls=f"Chem{no}Scene")
        (proj / "script.py").write_text(script, encoding="utf-8")
        (proj / "分镜.md").write_text(gen_storyboard(mod), encoding="utf-8")
        chars = sum(len(s["narr"]) for s in mod.SCENES)
        print(f"[OK] {no} {DIRS[no]}：{len(mod.SCENES)} 幕，读白 {chars} 字，"
              f"预计口播约 {chars / 3.6 / 60:.1f} 分钟")


if __name__ == "__main__":
    main()
