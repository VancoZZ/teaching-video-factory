"""
数学表达式 → 中文读白转换

背景：Edge TTS 直接读 "11/4" 会读成「十一分之四」，但中文习惯是
「四分之十一」（先分母后分子）。同时数学符号若不转换也会读错。

本模块把数学写法转成 TTS 能正确朗读的中文。
"""

import re

CN_NUM = {
    0: "零", 1: "一", 2: "二", 3: "三", 4: "四",
    5: "五", 6: "六", 7: "七", 8: "八", 9: "九", 10: "十",
}


def cn_int(n: int) -> str:
    """整数转中文（0-99 足够用于初高中题目）。"""
    if n < 0:
        return "负" + cn_int(-n)
    if n <= 10:
        return CN_NUM.get(n, str(n))
    if n < 20:
        return "十" + CN_NUM[n - 10]
    tens, ones = divmod(n, 10)
    return CN_NUM[tens] + "十" + (CN_NUM[ones] if ones else "")


def frac_to_speech(m):
    """a/b -> 「b 分之 a」。这是中文语序，与英文写法相反。"""
    num, den = int(m.group(1)), int(m.group(2))
    if num == 0:
        return cn_int(0)
    sign = "负" if (num < 0) ^ (den < 0) else ""
    return f"{sign}{cn_int(abs(den))}分之{cn_int(abs(num))}"


def convert_math(text: str) -> str:
    """
    把数学写法转成可朗读的中文。

    处理顺序有讲究：
      1. 带负号前置的数字（−10 -> 负10），先固化，避免后面的减号替换误伤
      2. 分数 a/b（必须先处理，否则分子分母会被当独立数字读）
      3. 简单符号替换
    """
    t = text

    # ① 区分「负号」与「减号」—— 这是本模块最容易出错的地方。
    #    可靠判据：数学排版里负号紧贴数字（−10），减号两侧有空格（8t − 16）。
    #    另：等号之后、开头、括号之后出现的负号一定是否号。
    #    先把真正的减号（两侧带空格）保护起来，再处理负号。
    t = re.sub(r"(?<=\s)[−\-](?=\s)", "@MINUS@", t)      # 减号：两边都有空格
    t = re.sub(r"[−\-]\s*(?=\d)", " 负 ", t)              # 其余紧贴数字的 → 负号
    t = re.sub(r"(?<!负 )@MINUS@(?! )", " 减 ", t)          # 兜底还原
    t = t.replace("@MINUS@", " 减 ")

    # ② 分数：a/b -> b分之a
    t = re.sub(r"(?<![\d/])(\d+)\s*/\s*(\d+)", frac_to_speech, t)

    # ③ 数字紧跟字母时补空格：8t -> 8 t（否则 TTS 读成「八t」）
    t = re.sub(r"(?<=[0-9)])\s*(?=[a-zA-Z])", " ", t)

    # ③' 函数记号 f x：TTS 会把 f 和 x 连读成一个词（「夫克斯」）。
    #    用顿号分隔，读成「f、x」。五种分隔符实测（逗号/顿号/句号/省略号/逗号+空格），
    #    顿号是唯一能让 whisper 转写出「f x」分开形式且不引入杂音的（2026-10-15）。
    #    f(−x) 读作「f 负 x」不受影响（f 后面是中文）。
    t = re.sub(r"(?<![A-Za-z])([fg])\s+x(?![A-Za-z])", r"\1、x", t)

    # 根号：√25 -> 根号 25
    t = re.sub(r"√\s*(\d+)", r"根号 \1", t)

    # 常用符号（按长度降序，避免先替换短符号导致长的匹配不上）
    sym_map = [
        (r"\bmod\b", "对"),
        (r"π", "派"),
        (r"≤", "小于等于"),
        (r"≥", "大于等于"),
        (r"≠", "不等于"),
        (r"≈", "约等于"),
        (r"=", "等于"),
        (r"\+", "加"),
        (r"−", "减"),   # U+2212
        (r"×", "乘"),
        (r"÷", "除以"),
        (r"²", "的平方"),
        (r"³", "的立方"),
        (r"°", "度"),
        (r"∠", "角"),
        (r"-", "减"),   # ASCII hyphen（前置负号已在①处理）
    ]
    for pat, rep in sym_map:
        t = re.sub(pat, rep, t)

    # 规整空格与标点，避免 TTS 读出怪异停顿
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"\s*([，。；：！？、])\s*", r"\1", t)
    t = re.sub(r" +", " ", t).strip()

    return t


if __name__ == "__main__":
    import sys

    for s in sys.argv[1:] or ["t = 11/4", "t = 5/4", "√25", "x² + y² = c²",
                              "8t − 16 = 6", "点C表示6，BC = 4", "P = −10 + 4t"]:
        print(f"{s!r:28} -> {convert_math(s)!r}")
