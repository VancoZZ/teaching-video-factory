#!/usr/bin/env python3
"""
script.py 结构检查  （补齐上游仓库缺失的脚本）

渲染前跑一遍，把「渲染完才发现忘加 add_sound」这类问题提前到秒级暴露。

检查项：
  1. 是否继承 Scene
  2. calculate_geometry() 是否存在且非空
  3. assert_geometry() 是否存在
  4. define_elements() 是否存在
  5. 是否调用 add_sound
  6. 是否读取 audio 路径（add_sound 参数含 audio/）
  7. 是否有无保护的 MathTex（无 LaTeX 环境会直接崩）
  8. 字幕是否有退场安排（FadeOut / → 标记）
  9. 硬编码路径含中文或空格

退出码：0 = 通过（可有警告），1 = 有错误
"""

import ast
import re
import sys
from pathlib import Path

ERRORS, WARNS = [], []


def err(msg):
    ERRORS.append(msg)


def warn(msg):
    WARNS.append(msg)


def method_names(tree):
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
    return names


def has_scene_subclass(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for b in node.bases:
                src = ast.unparse(b) if hasattr(ast, "unparse") else ""
                if "Scene" in src:
                    return node.name
    return None


def body_of(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    return None


def method_is_stub(node):
    """函数体里只有 pass / TODO 注释 -> 视为未实现。"""
    real = []
    for stmt in node.body:
        if isinstance(stmt, ast.Pass):
            continue
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
            continue
        real.append(stmt)
    return len(real) == 0


def check(path: Path):
    src = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        err(f"语法错误 第 {e.lineno} 行: {e.msg}")
        return

    scene = has_scene_subclass(tree)
    if scene:
        print(f"  [OK] Scene 子类: {scene}")
    else:
        err("找不到继承 Scene 的类")

    names = method_names(tree)

    for fn in ("calculate_geometry", "define_elements"):
        node = body_of(tree, fn)
        if node is None:
            err(f"缺少函数 {fn}()")
        elif method_is_stub(node):
            err(f"{fn}() 仍是空壳（只有 pass），无法渲染出正确图形")
        else:
            print(f"  [OK] {fn}() 已实现")

    # 几何验证：允许叫 assert_geometry，也可拆成 assert_conditions / assert_canvas
    verifiers = [n for n in names if n.startswith("assert") or n == "check_geometry"]
    real_v = [n for n in verifiers if not method_is_stub(body_of(tree, n))]
    if not verifiers:
        err("缺少几何验证函数（assert_geometry / assert_conditions / assert_canvas）")
    elif not real_v:
        err("几何验证函数全是空壳（只有 pass）—— 条件写错时无法在渲染前发现")
    else:
        print(f"  [OK] 几何验证: {', '.join(real_v)}")

    # calculate_geometry 内部应真正调用了验证函数
    cg = body_of(tree, "calculate_geometry")
    if cg is not None:
        called = any(
            isinstance(nd, ast.Call)
            and isinstance(nd.func, ast.Attribute)
            and nd.func.attr in ("assert_geometry", "assert_conditions", "assert_canvas")
            for nd in ast.walk(cg)
        )
        if real_v and not called:
            err("calculate_geometry() 里没有调用几何验证函数，断言形同虚设")

    if "add_sound" in src:
        print("  [OK] 检测到 add_sound()")
    else:
        err("没有 add_sound() 调用 —— 最终视频将没有声音")

    if re.search(r"add_sound\(\s*f?[\"']audio[\\/]", src):
        print("  [OK] 音频路径指向 audio/ 目录")
    else:
        warn("add_sound() 的路径不像 audio/xxx.wav，请确认与实际文件一致")

    # MathTex 需要 LaTeX，本项目默认用 Text+Unicode
    mathtex = re.findall(r"MathTex\(", src)
    if mathtex:
        warn(f"发现 {len(mathtex)} 处 MathTex，若环境无 LaTeX 会渲染失败，建议改 Text + Unicode")

    # 从音频列表动态读取时长
    if re.search(r"audio_info\.json|timeline\.json|json\.load", src):
        print("  [OK] 音频时长从 json 动态读取")
    else:
        warn("未发现读取 json 时长的代码，硬编码时长极易音画不同步")

    # 字幕退场
    if "FadeOut" in src or "fadeout" in src.lower():
        print("  [OK] 存在字幕退场动画")
    elif re.search(r"(Text|Subtitle|TextMobject)\(", src):
        warn("创建了文字对象但没看到 FadeOut，字幕可能残留在下一幕")

    # 画面时长需等待音频
    wfa_calls = len(re.findall(r"wait_for_audio\(", src))
    if wfa_calls == 0:
        if re.search(r"self\.wait\(", src):
            print("  [OK] 存在等待音频的逻辑")
        else:
            warn("没有 wait() 或 wait_for_audio()，画面可能短于音频导致配音截断")

    # 检查 wait_for_audio 是否在循环里被重复调用（实测会导致视频严重超时）
    for node in ast.walk(tree):
        if isinstance(node, (ast.For, ast.While)):
            body_src = "\n".join(ast.unparse(s) for s in node.body)
            if "wait_for_audio(" in body_src:
                err("wait_for_audio() 在循环内被调用，会导致重复等待音频、视频时长严重超时")
            # add_sound 放进循环会不断叠加音轨
            if "add_sound(" in body_src:
                err("add_sound() 在循环内被调用，会不断叠加音轨，应移到循环外或改用 self.add_sound 一次")

    if re.search(r'["\']([A-Za-z]:\\\\|[^"\']*[\u4e00-\u9fff][^"\']*)[\'"]', src):
        warn("代码含绝对路径或中文路径，可能在渲染时出错")


def main():
    target = Path(sys.argv[1]) if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else Path("script.py")

    if not target.exists():
        print(f"[错误] 找不到 {target}")
        sys.exit(1)

    print("=" * 56)
    print(f"代码结构检查: {target}")
    print("=" * 56)

    check(target)

    print("-" * 56)
    for w in WARNS:
        print(f"  [警告] {w}")
    for e in ERRORS:
        print(f"  [错误] {e}")

    if ERRORS:
        print("=" * 56)
        print(f"[不通过] {len(ERRORS)} 个错误 / {len(WARNS)} 个警告 —— 请修复后重试")
        sys.exit(1)
    print("=" * 56)
    print(f"[通过] 0 错误 / {len(WARNS)} 个警告")


if __name__ == "__main__":
    main()