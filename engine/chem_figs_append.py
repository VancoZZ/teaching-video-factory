# -*- coding: utf-8 -*-
"""chem_figs_append.py — 化学滴定曲线图库（追加到高中化学习题讲解/lessonlib.py）
注意：每次从第一单元同步 lessonlib 后，都需要重跑本文件！"""

# ================= 高中化学图库：滴定曲线 =================

FONT_C = "Microsoft YaHei"


def _tc(txt, size=26, color=C_TXT):
    return Text(txt, font=FONT_C, font_size=size, color=color)


def _titration_axes(width=9.6, height=4.8, pos=(0.6, -0.3, 0)):
    ax = Axes(
        x_range=[0, 26, 5], y_range=[0, 13, 1],
        x_length=width, y_length=height,
        tips=False,
        axis_config={"stroke_width": 2.2, "include_ticks": False},
    )
    ax.shift(pos)
    ylab = _tc("pH", 22).next_to(ax.y_axis.get_end(), UP, buff=0.1)
    xlab = _tc("V(NaOH)/mL", 20).next_to(ax.x_axis.get_end(), RIGHT, buff=0.1)
    return ax, VGroup(ylab, xlab)


def _curve(ax, xs, ys, color, sw=3.2):
    pts = [ax.c2p(x, y) for x, y in zip(xs, ys)]
    m = VMobject(color=color, stroke_width=sw)
    m.set_points_smoothly(pts)
    return m


X_HCL = [0, 5, 10, 15, 18, 19.3, 19.8]
Y_HCL = [1.0, 1.2, 1.5, 2.1, 3.1, 4.8, 6.6]
X_HCL_BASE = [19.8, 20.1, 21, 23, 26]
Y_HCL_BASE = [7.0, 10.8, 11.2, 11.5, 11.8]

X_HAC = [0, 2, 5, 10, 15, 18, 19.4, 19.8]
Y_HAC = [2.9, 3.5, 4.2, 4.76, 5.6, 6.5, 6.9, 7.0]
X_HAC_BASE = [19.8, 20.1, 21, 23, 26]
Y_HAC_BASE = [7.0, 9.8, 10.1, 10.3, 10.5]

X_HA = [0, 2, 5, 10, 15, 18, 19.3, 19.9]
Y_HA = [2.9, 3.5, 4.2, 4.76, 5.6, 6.5, 6.4, 7.0]
X_HA_BASE = [19.9, 20.3, 21, 22, 26]
Y_HA_BASE = [7.0, 8.3, 8.7, 9.0, 9.8]


def _dot_label(ax, x, y, label, color, dx=0.35, dy=0.35):
    d = Dot(ax.c2p(x, y), color=color, radius=0.07)
    lb = _tc(label, 24, color).next_to(d, RIGHT, buff=0.12).shift([dx, dy, 0])
    return VGroup(d, lb)


def fig_titration_pair():
    """双曲线：I 盐酸 + II 醋酸，标注 M/N/Q 与 pH=7、V=20 虚线。"""
    ax, axlabs = _titration_axes()
    hcl = VGroup(
        _curve(ax, X_HCL, Y_HCL, C_MAIN),
        _curve(ax, X_HCL_BASE, Y_HCL_BASE, C_MAIN),
    )
    hac = VGroup(
        _curve(ax, X_HAC, Y_HAC, C_AUX),
        _curve(ax, X_HAC_BASE, Y_HAC_BASE, C_AUX),
    )
    lab_i = _tc("I（盐酸）", 26, C_MAIN).next_to(ax.c2p(25.5, 11.8), UP, buff=0.15)
    lab_ii = _tc("II（醋酸）", 26, C_AUX).next_to(ax.c2p(25.5, 10.5), DOWN, buff=0.15)
    hline = DashedLine(ax.c2p(0, 7), ax.c2p(26, 7), color=C_HL, stroke_width=2)
    vline = DashedLine(ax.c2p(20, 0), ax.c2p(20, 13), color=C_HL, stroke_width=2)
    ph7 = _tc("pH=7", 22, C_HL).next_to(ax.c2p(0, 7), LEFT, buff=0.15)
    v20 = _tc("20.00", 22, C_HL).next_to(ax.c2p(20, 0), DOWN, buff=0.15)
    dm = _dot_label(ax, 10, 1.5, "M", C_TXT, dy=0.3)
    dn = _dot_label(ax, 10, 4.76, "N", C_TXT, dx=-1.0, dy=0.3)
    dq = _dot_label(ax, 19.8, 7.0, "Q", C_TXT, dx=-1.1, dy=0.4)
    note = _tc("示意图：实线为主曲线，虚线为 pH=7 与 V=20.00 参考线", 20, C_FIX).to_edge(DOWN, buff=0.35)
    return [
        _g(ax, 0.9), _g(axlabs, 0.3),
        _g(hcl, 1.0), _g(lab_i, 0.3),
        _g(hac, 1.0), _g(lab_ii, 0.3),
        _g(VGroup(hline, vline, ph7, v20), 0.8),
        _g(VGroup(dm, dn, dq), 0.9),
        _g(note, 0.4),
    ]


def fig_titration_ha():
    """单曲线：HA 滴定，标注 a/b/c/d 四点。"""
    ax, axlabs = _titration_axes()
    curve = VGroup(
        _curve(ax, X_HA, Y_HA, C_MAIN),
        _curve(ax, X_HA_BASE, Y_HA_BASE, C_MAIN),
    )
    hline = DashedLine(ax.c2p(0, 7), ax.c2p(26, 7), color=C_HL, stroke_width=2)
    ph7 = _tc("pH=7", 22, C_HL).next_to(ax.c2p(0, 7), LEFT, buff=0.15)
    da = _dot_label(ax, 0.1, 2.9, "a", C_MAIN, dx=0.2, dy=0.15)
    db = _dot_label(ax, 10, 4.76, "b", C_AUX, dy=0.35)
    dc = _dot_label(ax, 19.9, 7.0, "c", C_HL, dx=-0.9, dy=0.35)
    dd = _dot_label(ax, 21, 8.7, "d", C_BLUE, dx=0.25, dy=0.3)
    note = _tc("示意图：a 起点（pH≈3）｜b 半中和｜c pH=7｜d 碱过量", 20, C_FIX).to_edge(DOWN, buff=0.35)
    return [
        _g(ax, 0.9), _g(axlabs, 0.3),
        _g(curve, 1.2), _g(VGroup(hline, ph7), 0.5),
        _g(VGroup(da, db, dc, dd), 1.1),
        _g(note, 0.4),
    ]


if "titration_pair" not in FIGS:
    FIGS.update({
        "titration_pair": fig_titration_pair,
        "titration_ha": fig_titration_ha,
    })
