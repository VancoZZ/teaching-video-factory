# 课堂数据规范（lesson_data_NN.py）

课堂数据是整条管线的单一事实来源：视频分镜、配音读白、讲义内容全部由它驱动。

## 文件结构

```python
LESSON = {"file_no": "22", "title": "2.2 数轴",
          "chapter": "鲁教版（五四制）六年级上册 第二章",
          "duration_hint": "约 20 分钟", "out_name": "成片_2.2数轴.mp4"}

def ASSERTS():
    # 渲染前的数值断言：必须真验算（check.py 拒绝空壳断言）
    assert abs(0.1 * 10 / 30 - 1 / 30) < 1e-12
    print("✅ 断言通过")

SCENES = [dict(...), ...]
```

## 幕字段

| 字段 | 必填 | 说明 |
|---|---|---|
| name | ✓ | 幕名。禁空格、①②③、「第(2)问」类括号；用「第1空」「问题2a」 |
| kind | ✓ | title/bullets/steps/twocol/warn/summary/problem/fig/shapes |
| narr | ✓ | 配音读白（也是字幕来源；`\|` 会被替换为逗号） |
| doc / topic / dockind | - | 讲义用 |

## 各 kind 的 vis

- title: main, sub
- bullets: title, lines[], hl[]
- steps: title, lines[], result
- problem: tag, title, lines[]
- twocol: title, left{head,lines[]}, right{head,lines[]}
- warn: title, bad(str|list), good(str|list), note?
- summary: lines[], hw
- fig: title, fig（FIGS 注册名）
- shapes: title, items[[label, key]], note

## 化学内容书写约定（字体兼容）

- 下标平写：CH3COOH、Na2CO3（雅黑缺 ₂，会丢字）
- ⇌、上标 ⁻ ⁺ 可用（Pango 回退）；负号统一 U+2212「−」

## 幕名铁律 / 断言

- 幕名不含空格（音频文件名正则截断→整段静默跳过）、不含 ①②③/括号（回填 int() 崩）、唯一
- 断言真验算：把视频里每个结论算一遍；check.py 拒绝空壳 assert
