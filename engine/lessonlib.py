"""
lessonlib.py — 六年级上册第一章 课件式讲解视频共享库
供各节 script.py 导入：基础设施 + 伪3D图形 + 图库 + 分幕呈现器。
不定义 Scene 子类（check.py 会在 script.py 里找唯一的 Scene）。
"""

import json
from pathlib import Path

import numpy as np
from manim import *

config.background_color = "#1a1a2e"

C_MAIN = "#4ecca3"
C_AUX = "#e94560"
C_HL = "#ffc107"
C_TXT = "#ffffff"
C_FIX = "#b0bec5"
C_AXIS = "#8d8d8d"
C_BLUE = "#4fc3f7"
FONT = "Microsoft YaHei"


def T(txt, size=28, color=C_TXT):
    return Text(txt, font=FONT, font_size=size, color=color)


def _pick_audio_dir():
    for d in ("audio", "aud"):
        if (Path(d) / "timeline.json").exists():
            return Path(d)
    for d in ("audio", "aud"):
        if Path(d).exists():
            return Path(d)
    return Path("audio")


AUDIO_DIR = _pick_audio_dir()
TIMELINE = AUDIO_DIR / "timeline.json"


# ================= 伪3D 图形 =================

def fig_cuboid(w=2.0, h=1.3, d=0.75, color=C_TXT):
    off = np.array([d * 0.7, d * 0.5, 0])
    pts = [[-w / 2, -h / 2], [w / 2, -h / 2], [w / 2, h / 2], [-w / 2, h / 2]]
    front = Polygon(*[np.array([p[0], p[1], 0]) for p in pts], color=color,
                    stroke_width=2.5)
    back = front.copy().shift(off).set_stroke(width=2, opacity=0.8)
    edges = VGroup(*[Line(np.array([p[0], p[1], 0]),
                          np.array([p[0], p[1], 0]) + off, color=color,
                          stroke_width=2) for p in pts])
    return VGroup(front, back, edges)


def fig_cylinder(r=0.62, h=1.6, color=C_MAIN):
    top = Ellipse(width=2 * r, height=2 * r * 0.36, color=color, stroke_width=2.5)
    top.shift(UP * h / 2)
    bot = Ellipse(width=2 * r, height=2 * r * 0.36, color=color, stroke_width=2)
    bot.shift(DOWN * h / 2)
    left = Line([-r, -h / 2, 0], [-r, h / 2, 0], color=color, stroke_width=2.5)
    right = Line([r, -h / 2, 0], [r, h / 2, 0], color=color, stroke_width=2.5)
    return VGroup(top, bot, left, right)


def fig_cone(r=0.75, h=1.6, color=C_AUX):
    base = Ellipse(width=2 * r, height=2 * r * 0.36, color=color, stroke_width=2)
    base.shift(DOWN * h / 2)
    apex = np.array([0, h / 2, 0])
    left = Line([-r, -h / 2, 0], apex, color=color, stroke_width=2.5)
    right = Line([r, -h / 2, 0], apex, color=color, stroke_width=2.5)
    return VGroup(base, left, right)


def fig_ball(r=0.72, color=C_HL):
    c = Circle(radius=r, color=color, stroke_width=2.5)
    eq = Ellipse(width=2 * r, height=2 * r * 0.28, color=color, stroke_width=1.5)
    eq.set_stroke(opacity=0.6).shift(DOWN * r * 0.25)
    return VGroup(c, eq)


def fig_prism(n=6, r=1.05, h=1.55, color=C_TXT):
    ang = [i * TAU / n + PI / n for i in range(n)]
    pts_b = [np.array([r * np.cos(a), r * np.sin(a) * 0.5 - h / 2, 0]) for a in ang]
    pts_t = [p + np.array([0, h, 0]) for p in pts_b]
    return VGroup(
        Polygon(*pts_b, color=color, stroke_width=2),
        Polygon(*pts_t, color=color, stroke_width=2.5),
        VGroup(*[Line(pts_b[i], pts_t[i], color=color, stroke_width=2)
                 for i in range(n)]),
    )


def fig_pyramid(w=1.9, h=0.9, ph=1.5, color=C_TXT):
    base_pts = [np.array([-w, -h / 2, 0]), np.array([w, -h / 2, 0]),
                np.array([w * 0.62, h / 2, 0]), np.array([-w * 0.62, h / 2, 0])]
    base = Polygon(*base_pts, color=color, stroke_width=2)
    apex = np.array([0, h / 2 + ph, 0])
    edges = VGroup(*[Line(p, apex, color=color, stroke_width=2.5)
                     for p in base_pts])
    return VGroup(base, edges)


# 轴测正方体
CUBE_S = 1.0
CUBE_OX = -3.1
CUBE_OY = -0.1


def cube_v(p):
    x, y, z = p
    return np.array([CUBE_OX + (x - 0.55 * y) * CUBE_S,
                     CUBE_OY + (z + 0.35 * y) * CUBE_S, 0])


CUBE_EDGES = [
    ((0, 0, 0), (1, 0, 0)), ((1, 0, 0), (1, 1, 0)),
    ((1, 1, 0), (0, 1, 0)), ((0, 1, 0), (0, 0, 0)),
    ((0, 0, 1), (1, 0, 1)), ((1, 0, 1), (1, 1, 1)),
    ((1, 1, 1), (0, 1, 1)), ((0, 1, 1), (0, 0, 1)),
    ((0, 0, 0), (0, 0, 1)), ((1, 0, 0), (1, 0, 1)),
    ((1, 1, 0), (1, 1, 1)), ((0, 1, 0), (0, 1, 1)),
]


def fig_cube_wire(color=C_TXT, sw=2.2):
    return VGroup(*[Line(cube_v(a), cube_v(b), color=color, stroke_width=sw)
                    for a, b in CUBE_EDGES])


def cube_pt(p):
    """已在连续坐标上的点 → 画布。"""
    return np.array([CUBE_OX + (p[0] - 0.55 * p[1]) * CUBE_S,
                     CUBE_OY + (p[2] + 0.35 * p[1]) * CUBE_S, 0])


def cube_section(pts, color=C_HL):
    return Polygon(*[cube_pt(p) for p in pts], color=color, stroke_width=3,
                   fill_opacity=0.5, fill_color=color)


def mix3(p, q, t):
    return tuple(p[k] + (q[k] - p[k]) * t for k in range(3))


# ================= 图库（返回 [(mobj, run_time), ...] 分步 Create） =================

def _g(m, rt=1.0):
    return (m, rt)


def fig_hexprism():
    prism = fig_prism(6).move_to([-3.4, 0, 0])
    rows = VGroup(
        T("面：8 个（2 底 + 6 侧）", 26, C_HL),
        T("棱：18 条（12 + 6）", 26, C_HL),
        T("顶点：12 个（6 + 6）", 26, C_HL),
    ).arrange(DOWN, buff=0.32, aligned_edge=LEFT).move_to([1.8, 1.2, 0])
    euler = T("12 − 18 + 8 = 2", 34, C_MAIN).move_to([1.8, -0.9, 0])
    note = T("顶点数 − 棱数 + 面数 = 2", 24, C_FIX).move_to([1.8, -1.8, 0])
    return [_g(prism, 1.0), _g(rows, 1.2), _g(euler, 0.7), _g(note, 0.4)]


def fig_pyramid_counts():
    pyr = fig_pyramid().move_to([-3.4, -0.2, 0])
    rows = VGroup(
        T("四棱锥：面 5 个", 26, C_HL),
        T("棱 8 条", 26, C_HL),
        T("顶点 5 个", 26, C_HL),
    ).arrange(DOWN, buff=0.3, aligned_edge=LEFT).move_to([1.8, 1.0, 0])
    euler = T("5 − 8 + 5 = 2 ✓", 30, C_MAIN).move_to([1.8, -0.8, 0])
    note = T("n 棱锥：面 n+1，棱 2n，顶点 n+1", 24, C_FIX).move_to([1.8, -1.7, 0])
    return [_g(pyr, 1.0), _g(rows, 1.0), _g(euler, 0.6), _g(note, 0.4)]


def fig_cyl_net():
    cyl = fig_cylinder().move_to([-4.3, 0, 0])
    arr = Arrow([-3.2, 0, 0], [-1.9, 0, 0], color=C_HL, stroke_width=4)
    rect = Rectangle(width=3.4, height=1.4, color=C_MAIN, stroke_width=2.5)
    rect.move_to([1.2, 0, 0])
    ct = Circle(radius=0.4, color=C_MAIN, stroke_width=2).move_to([1.2, 1.2, 0])
    cb = Circle(radius=0.4, color=C_MAIN, stroke_width=2).move_to([1.2, -1.2, 0])
    n1 = T("长 = 底面圆的周长", 24, C_HL).move_to([1.2, 2.1, 0])
    n2 = T("宽 = 圆柱的高", 24, C_HL).move_to([4.6, 0, 0])
    n3 = T("共 3 个面", 26, C_MAIN).move_to([1.2, -2.1, 0])
    return [_g(VGroup(cyl, arr), 0.9), _g(VGroup(rect, ct, cb), 0.9),
            _g(VGroup(n1, n2, n3), 0.8)]


def fig_cone_net():
    cone = fig_cone().move_to([-4.3, 0, 0])
    arr = Arrow([-3.2, 0, 0], [-1.9, 0, 0], color=C_HL, stroke_width=4)
    sector = AnnularSector(inner_radius=0.0, outer_radius=1.5, angle=2.2,
                           start_angle=-0.6, color=C_AUX, stroke_width=2.5,
                           fill_opacity=0.25, fill_color=C_AUX).move_to([1.0, 0.7, 0])
    circ = Circle(radius=0.42, color=C_AUX, stroke_width=2).move_to([1.0, -1.5, 0])
    n1 = T("扇形的弧长 = 底面圆的周长", 24, C_HL).move_to([1.0, 2.3, 0])
    n2 = T("共 2 个面", 26, C_MAIN).move_to([4.2, 0.3, 0])
    return [_g(VGroup(cone, arr), 0.9), _g(VGroup(sector, circ), 0.9), _g(VGroup(n1, n2), 0.7)]


def fig_prism3_net():
    sq = 1.05
    rects = VGroup(*[Rectangle(width=sq, height=0.78, color=C_MAIN, stroke_width=2.5)
                     .move_to([-3.4 + i * sq, 0.3, 0]) for i in range(3)])
    tri_u = Polygon([-sq / 2, 0, 0], [sq / 2, 0, 0], [0, 0.75, 0], color=C_HL,
                    stroke_width=2.5, fill_opacity=0.3, fill_color=C_HL)
    tri_u.move_to([-3.4 + sq, 1.1, 0])
    tri_d = Polygon([-sq / 2, 0, 0], [sq / 2, 0, 0], [0, -0.75, 0], color=C_HL,
                    stroke_width=2.5, fill_opacity=0.3, fill_color=C_HL)
    tri_d.move_to([-3.4 + sq, -0.5, 0])
    lab = T("2 个三角形底面 + 3 个长方形侧面", 24).move_to([-3.4 + sq, -1.7, 0])
    note = T("底面贴上、贴下都行 → 展开图不唯一", 26, C_MAIN).move_to([3.4, 0.3, 0])
    return [_g(VGroup(rects, tri_u, tri_d), 1.1), _g(lab, 0.5), _g(note, 0.6)]


def _sq_net(cells, u=0.6, color=C_TXT, origin=(0, 0)):
    """cells: [(col,row), ...] 返回一组正方形。"""
    g = VGroup()
    for c, r in cells:
        g.add(Square(side_length=u, color=color, stroke_width=2)
              .move_to([origin[0] + c * u, origin[1] + r * u, 0]))
    return g


def fig_net_141():
    net = _sq_net([(i, 0) for i in range(4)] + [(1, 1), (1, -1)],
                  origin=(-3.9, -0.1))
    lab = T("一四一型（共 6 种）", 24, C_MAIN).move_to([-2.85, -1.55, 0])
    lines = VGroup(
        T("一四一型：6 种", 26), T("二三一型：3 种", 26),
        T("二二二型：1 种", 26), T("三三型：1 种", 26),
        T("合计 6+3+1+1 = 11 种", 26, C_HL),
    ).arrange(DOWN, buff=0.22, aligned_edge=LEFT).move_to([1.4, 0.9, 0])
    bad = T("田字形 ✗（折叠重叠）", 26, C_AUX).move_to([1.4, -2.0, 0])
    return [_g(net, 0.9), _g(lab, 0.4), _g(lines, 1.2), _g(bad, 0.5)]


def fig_net_faces():
    u = 0.62
    cells = [(0, 0), (1, 0), (2, 0), (3, 0), (1, 1), (1, -1)]
    letters = ["B", "C", "D", "E", "A", "F"]
    net = _sq_net(cells, u=u, origin=(-4.4, -0.1))
    labs = VGroup()
    for (c, r), s in zip(cells, letters):
        labs.add(T(s, 26, C_HL).move_to([-4.4 + c * u, -0.1 + r * u, 0]))
    pairs = VGroup(
        T("对面配对：A—F", 26, C_MAIN),
        T("B—D，C—E", 26, C_MAIN),
        T("口诀：隔一个面是对面", 24, C_HL),
    ).arrange(DOWN, buff=0.3, aligned_edge=LEFT).move_to([1.6, 0.7, 0])
    return [_g(net, 0.8), _g(labs, 0.7), _g(pairs, 0.9)]


def fig_net_options():
    """四选一：哪个不能折成正方体。"""
    groups = []
    # A 一四一
    a = _sq_net([(i, 0) for i in range(4)] + [(1, 1), (1, -1)], u=0.42,
                origin=(-4.9, 0))
    # B 二三一
    b = _sq_net([(0, 0), (1, 0), (2, 0), (2, 1), (0, -1), (0, -2)], u=0.42,
                origin=(-1.6, 0))
    # C 田字形
    c = _sq_net([(0, 0), (0, 1), (1, 0), (1, 1)], u=0.42, origin=(1.2, 0))
    # D 三三
    d = _sq_net([(0, 0), (0, 1), (0, 2), (1, 0), (1, 1), (1, 2)], u=0.42,
                origin=(3.9, 0))
    marks = [("A", -4.9), ("B", -1.6), ("C", 1.2), ("D", 3.9)]
    labs = VGroup(*[T(t, 24, C_HL).move_to([x, 1.35, 0]) for t, x in marks])
    q = T("哪一个折叠后不能围成正方体？", 28).to_edge(UP, buff=0.6)
    return [_g(q, 0.6), _g(VGroup(a, b, c, d, labs), 1.2)]


def fig_cube_tri():
    cube = fig_cube_wire()
    sec = cube_section([mix3((0, 0, 0), (1, 0, 0), 0.3),
                        mix3((0, 0, 0), (0, 1, 0), 0.3),
                        mix3((0, 0, 0), (0, 0, 1), 0.3)])
    lab = T("切一个角 → 三角形", 30, C_HL).move_to([3.2, 1.5, 0])
    note = T("刀痕经过同一个顶点的三条棱", 24, C_FIX).move_to([3.2, 0.3, 0])
    return [_g(cube, 1.0), _g(sec, 0.9), _g(VGroup(lab, note), 0.7)]


def fig_cube_rect():
    cube = fig_cube_wire()
    sec = cube_section([(0.5, 0, 0), (0.5, 1, 0), (0.5, 1, 1), (0.5, 0, 1)],
                       color=C_MAIN)
    lab = T("竖着切 → 长方形", 30, C_MAIN).move_to([3.2, 1.5, 0])
    note = T("位置刚好时，可截出正方形", 24, C_FIX).move_to([3.2, 0.3, 0])
    return [_g(cube, 1.0), _g(sec, 0.9), _g(VGroup(lab, note), 0.7)]


def fig_cube_hex():
    cube = fig_cube_wire()
    sec = cube_section([
        mix3((1, 0, 0), (1, 0, 1), 0.5), mix3((1, 0, 0), (1, 1, 0), 0.5),
        mix3((1, 1, 0), (0, 1, 0), 0.5), mix3((0, 1, 0), (0, 1, 1), 0.5),
        mix3((0, 1, 1), (0, 0, 1), 0.5), mix3((0, 0, 1), (0, 0, 0), 0.5)])
    lab = T("斜穿六条棱中点 → 六边形", 28, C_HL).move_to([3.2, 1.6, 0])
    big = T("最多六边形！", 38, C_MAIN).move_to([3.2, 0.2, 0])
    why = T("截面每条边来自一个面，正方体只有 6 个面", 22, C_FIX).move_to(
        [3.2, -1.2, 0])
    return [_g(cube, 1.0), _g(sec, 1.0), _g(VGroup(lab, big, why), 0.9)]


def fig_cyl_cuts():
    r = 0.55
    h = 1.4
    cyl = VGroup(
        Ellipse(width=2 * r, height=2 * r * 0.36, color=C_TXT,
                stroke_width=2.5).shift(UP * h / 2),
        Ellipse(width=2 * r, height=2 * r * 0.36, color=C_TXT,
                stroke_width=2).shift(DOWN * h / 2),
        Line([-r, -h / 2, 0], [-r, h / 2, 0], color=C_TXT, stroke_width=2.5),
        Line([r, -h / 2, 0], [r, h / 2, 0], color=C_TXT, stroke_width=2.5),
    ).move_to([-4.4, 0, 0])
    panels = [
        ("横着切", Circle(radius=0.42, color=C_MAIN, stroke_width=2.5), C_MAIN),
        ("斜着切", Ellipse(width=1.05, height=0.58, color=C_HL,
                          stroke_width=2.5).rotate(-0.4), C_HL),
        ("竖着切", Rectangle(width=0.58, height=1.05, color=C_AUX,
                            stroke_width=2.5), C_AUX),
    ]
    out = [_g(cyl, 0.8)]
    xs = [-1.7, 1.5, 4.5]
    grp = VGroup()
    for (name, fig, col), x in zip(panels, xs):
        grp.add(T(name, 24, col).move_to([x, 1.5, 0]), fig.move_to([x, 0.2, 0]))
    out.append(_g(grp, 1.1))
    out.append(_g(T("圆柱截不出三角形", 28, C_AUX).to_edge(DOWN, buff=0.6), 0.5))
    return out


def fig_cyl_views():
    r = 0.62
    h = 1.5
    cyl = VGroup(
        Ellipse(width=2 * r, height=2 * r * 0.36, color=C_TXT,
                stroke_width=2.5).shift(UP * h / 2),
        Ellipse(width=2 * r, height=2 * r * 0.36, color=C_TXT,
                stroke_width=2).shift(DOWN * h / 2),
        Line([-r, -h / 2, 0], [-r, h / 2, 0], color=C_TXT, stroke_width=2.5),
        Line([r, -h / 2, 0], [r, h / 2, 0], color=C_TXT, stroke_width=2.5),
    ).move_to([-4.4, 0, 0])
    front = Rectangle(width=1.1, height=1.5, color=C_MAIN, stroke_width=2.5)
    front.move_to([-1.7, 0.3, 0])
    left = Rectangle(width=1.1, height=1.5, color=C_BLUE, stroke_width=2.5)
    left.move_to([1.5, 0.3, 0])
    top = Circle(radius=0.55, color=C_HL, stroke_width=2.5).move_to([4.5, 0.3, 0])
    labels = VGroup(
        T("从正面看", 24, C_MAIN).move_to([-1.7, -1.4, 0]),
        T("从左面看", 24, C_BLUE).move_to([1.5, -1.4, 0]),
        T("从上面看", 24, C_HL).move_to([4.5, -1.4, 0]),
    )
    return [_g(cyl, 0.9), _g(VGroup(front, left, top), 1.1), _g(labels, 0.6)]


def fig_cone_views():
    cone = fig_cone().move_to([-4.4, 0, 0])
    tri1 = Polygon([-0.55, -0.75, 0], [0.55, -0.75, 0], [0, 0.75, 0],
                   color=C_MAIN, stroke_width=2.5).move_to([-1.7, 0.3, 0])
    tri2 = Polygon([-0.55, -0.75, 0], [0.55, -0.75, 0], [0, 0.75, 0],
                   color=C_BLUE, stroke_width=2.5).move_to([1.5, 0.3, 0])
    topg = VGroup(Circle(radius=0.55, color=C_HL, stroke_width=2.5),
                  Dot(ORIGIN, radius=0.05, color=C_HL)).move_to([4.5, 0.3, 0])
    labels = VGroup(
        T("从正面看：三角形", 24, C_MAIN).move_to([-1.7, -1.5, 0]),
        T("从左面看：三角形", 24, C_BLUE).move_to([1.5, -1.5, 0]),
        T("从上面看：带圆心的圆", 24, C_HL).move_to([4.5, -1.5, 0]),
    )
    return [_g(cone, 0.9), _g(VGroup(tri1, tri2, topg), 1.1), _g(labels, 0.7)]


def _mini_cube(x, y, z, u=0.85):
    """伪3D 小方块，z=层数。"""
    w, h, d = u, u, u * 0.5
    base = np.array([x * u * 0.78 - 1.6, z * u * 0.78 - 1.2, 0])
    off = np.array([d * 0.62, d * 0.45, 0])
    pts = [[-w / 2, -h / 2], [w / 2, -h / 2], [w / 2, h / 2], [-w / 2, h / 2]]
    front = Polygon(*[base + np.array([p[0], p[1], 0]) for p in pts],
                    color=C_TXT, stroke_width=2.2)
    back = front.copy().shift(off).set_stroke(width=1.6, opacity=0.75)
    edges = VGroup(*[Line(base + np.array([p[0], p[1], 0]),
                          base + np.array([p[0], p[1], 0]) + off,
                          color=C_TXT, stroke_width=1.8) for p in pts])
    return VGroup(front, back, edges)


def fig_blocks3d():
    cubes = VGroup(_mini_cube(0, 0, 0), _mini_cube(1, 0, 0), _mini_cube(2, 0, 0),
                   _mini_cube(0, 0, 1))
    lab = T("下层一排 3 块，上层左边 1 块，共 4 块", 26, C_HL).move_to(
        [-0.2, -2.6, 0])
    return [_g(cubes, 1.2), _g(lab, 0.5)]


def fig_blocks_front():
    u = 0.7
    cells = [(0, 0), (1, 0), (2, 0), (0, 1)]
    g = _sq_net(cells, u=u, origin=(-1.6, -0.9))
    lab = T("从正面看", 26, C_MAIN).move_to([-1.6, 1.2, 0])
    cnt = T("下行 3 个 + 上行左 1 个", 24, C_FIX).move_to([-1.6, -2.3, 0])
    return [_g(g, 0.9), _g(VGroup(lab, cnt), 0.6)]


def fig_blocks_top():
    u = 0.7
    g = _sq_net([(i, 0) for i in range(3)], u=u, origin=(-1.6, -0.35))
    lab = T("从上面看", 26, C_BLUE).move_to([-1.6, 1.0, 0])
    cnt = T("一排 3 个", 24, C_FIX).move_to([-1.6, -1.9, 0])
    return [_g(g, 0.8), _g(VGroup(lab, cnt), 0.6)]


def fig_blocks_left():
    u = 0.7
    g = _sq_net([(0, 0), (0, 1)], u=u, origin=(-1.6, -1.2))
    lab = T("从左面看", 26, C_HL).move_to([-1.6, 1.0, 0])
    cnt = T("一列 2 个", 24, C_FIX).move_to([-1.6, -2.5, 0])
    return [_g(g, 0.8), _g(VGroup(lab, cnt), 0.6)]


def fig_views_all():
    u = 0.62
    front = _sq_net([(0, 0), (1, 0), (2, 0), (0, 1)], u=u, origin=(-4.6, -0.7))
    top = _sq_net([(0, 0), (1, 0), (2, 0)], u=u, origin=(-0.5, -0.35))
    left = _sq_net([(0, 0), (0, 1)], u=u, origin=(3.4, -0.7))
    labs = VGroup(
        T("从正面看", 24, C_MAIN).move_to([-4.05, 1.1, 0]),
        T("从上面看", 24, C_BLUE).move_to([0.1, 1.1, 0]),
        T("从左面看", 24, C_HL).move_to([3.7, 1.1, 0]),
    )
    return [_g(VGroup(front, top, left), 1.1), _g(labs, 0.6)]


def fig_faces_of_solids():
    s1 = fig_cuboid().move_to([-4.5, 0.6, 0])
    s2 = fig_cylinder().move_to([-1.5, 0.6, 0])
    s3 = fig_cone().move_to([1.5, 0.6, 0])
    s4 = fig_ball().move_to([4.4, 0.6, 0])
    t1 = T("6 个平面", 24).move_to([-4.5, -1.5, 0])
    t2 = T("2 平面 + 1 曲面", 24).move_to([-1.5, -1.5, 0])
    t3 = T("1 平面 + 1 曲面", 24).move_to([1.5, -1.5, 0])
    t4 = T("全是曲面", 24).move_to([4.4, -1.5, 0])
    head = T("面分两种：平面 与 曲面", 30, C_HL).to_edge(UP, buff=0.5)
    return [_g(head, 0.5), _g(VGroup(s1, s2, s3, s4), 1.0), _g(VGroup(t1, t2, t3, t4), 0.8)]




# ================= 第二单元图库：数轴类 =================

def make_numberline(vmin=-5, vmax=5, unit=0.62, y=0.0, step=1,
                    color=C_AXIS, show_labels=True):
    """数轴 → (group, to_x(value))。"""
    def to_x(v):
        return v * unit
    x1, x2 = to_x(vmin), to_x(vmax)
    axis = Line([x1, y, 0], [x2, y, 0], color=color, stroke_width=2.5)
    axis.add_tip(tip_length=0.18)
    grp = VGroup(axis)
    ticks = VGroup()
    labels = VGroup()
    for v in range(int(vmin), int(vmax) + 1, step):
        x = to_x(v)
        big = (v == 0)
        ticks.add(Line([x, y - (0.16 if big else 0.1), 0],
                       [x, y + (0.16 if big else 0.1), 0],
                       color=C_TXT if big else color,
                       stroke_width=2 if big else 1.5))
        if show_labels:
            lab = T(str(v), 22, C_TXT if big else C_FIX)
            lab.next_to(Dot([x, y, 0], radius=0.001), DOWN, buff=0.14)
            labels.add(lab)
    grp.add(ticks, labels)
    return grp, to_x


def fig_numberline_basic():
    grp, to_x = make_numberline(-5, 5)
    head = T("数轴三要素：原点、正方向、单位长度", 30, C_HL).to_edge(UP, buff=0.6)
    marks = VGroup(
        T("原点 O：表示 0", 24, C_MAIN).move_to([-4.0, -2.0, 0]),
        T("正方向：向右为正", 24, C_BLUE).move_to([0, -2.0, 0]),
        T("单位长度：一样间隔", 24, C_HL).move_to([4.0, -2.0, 0]),
    )
    return [_g(VGroup(grp, head), 1.1), _g(marks, 0.9)]


def fig_numberline_points():
    grp, to_x = make_numberline(-5, 5, y=0.3)
    dA = Dot([to_x(-3), 0.3, 0], color=C_MAIN, radius=0.1)
    dB = Dot([to_x(2), 0.3, 0], color=C_AUX, radius=0.1)
    lA = T("A", 26, C_MAIN).next_to(dA, UP, buff=0.15)
    lB = T("B", 26, C_AUX).next_to(dB, UP, buff=0.15)
    note = T("右边的数总比左边大：2 > −3", 28, C_HL).move_to([0, -1.8, 0])
    note2 = T("从 A 到 B：向右移动 5 个单位", 24, C_FIX).move_to([0, -2.7, 0])
    return [_g(grp, 1.0), _g(VGroup(dA, dB, lA, lB), 0.8), _g(VGroup(note, note2), 0.8)]


def fig_abs_distance():
    grp, to_x = make_numberline(-5, 5, y=0.3)
    dA = Dot([to_x(-3), 0.3, 0], color=C_MAIN, radius=0.1)
    lA = T("−3", 24, C_MAIN).next_to(dA, DOWN, buff=0.15)
    arc = ArcBetweenPoints([to_x(-3), 0.75, 0], [to_x(0), 0.75, 0], angle=-1.1,
                           color=C_HL, stroke_width=3)
    arc.add_tip(tip_length=0.15)
    dist = T("距离 = 3", 24, C_HL).move_to([to_x(-1.5), 1.6, 0])
    big = T("|−3| = 3", 40, C_MAIN).move_to([3.6, 0.8, 0])
    note = T("绝对值 = 数轴上到原点的距离", 26, C_FIX).move_to([3.6, -0.4, 0])
    note2 = T("距离永远非负", 26, C_AUX).move_to([3.6, -1.4, 0])
    return [_g(VGroup(grp, dA, lA), 1.0), _g(VGroup(arc, dist), 0.8),
            _g(VGroup(big, note, note2), 0.9)]


def fig_add_move():
    grp, to_x = make_numberline(-6, 4, y=0.3)
    d0 = Dot([to_x(-1), 0.3, 0], color=C_MAIN, radius=0.1)
    start = T("从 −1 出发", 24, C_MAIN).next_to(d0, DOWN, buff=0.15)
    arr = Arrow([to_x(-1), 1.0, 0], [to_x(-4), 1.0, 0], color=C_AUX,
                stroke_width=5)
    mov = T("再向左移 3（加 −3）", 24, C_AUX).move_to([to_x(-2.5), 1.5, 0])
    d1 = Dot([to_x(-4), 0.3, 0], color=C_HL, radius=0.12)
    end = T("到 −4", 24, C_HL).next_to(d1, DOWN, buff=0.15)
    eq = T("(−1) + (−3) = −4", 34, C_MAIN).move_to([0, -2.0, 0])
    return [_g(VGroup(grp, d0, start), 0.9), _g(VGroup(arr, mov), 0.8),
            _g(VGroup(d1, end), 0.5), _g(eq, 0.7)]


def fig_power_expand():
    base = T("(−2)³", 44, C_HL).move_to([-3.6, 0.6, 0])
    eqs = VGroup(
        T("= (−2) × (−2) × (−2)", 30),
        T("= 4 × (−2)", 30),
        T("= −8", 30, C_MAIN),
    ).arrange(DOWN, buff=0.35, aligned_edge=LEFT).move_to([1.6, 0.7, 0])
    note = T("指数 3 = 相同因数 (−2) 的个数", 26, C_FIX).move_to([-3.6, -0.9, 0])
    note2 = T("读作：负二的三次方", 24, C_FIX).move_to([-3.6, -1.8, 0])
    return [_g(base, 0.6), _g(eqs, 1.2), _g(VGroup(note, note2), 0.7)]


def fig_sci_notation():
    big = T("3.5 × 10⁴", 48, C_HL).move_to([0, 0.9, 0])
    a1 = T("a：1 ≤ a < 10（一位整数）", 26, C_MAIN).move_to([-3.2, -0.7, 0])
    a2 = T("n：小数点移动的位数", 26, C_BLUE).move_to([3.2, -0.7, 0])
    demo = VGroup(
        T("35000 = 3.5 × 10⁴（小数点右移 4 位）", 26),
        T("0.00035 = 3.5 × 10⁻⁴（小数点左移 4 位）", 26),
    ).arrange(DOWN, buff=0.3).move_to([0, -2.0, 0])
    return [_g(big, 0.7), _g(VGroup(a1, a2), 0.9), _g(demo, 0.9)]






# ================= 第二单元图库：数轴类 =================

def make_numberline(vmin=-5, vmax=5, unit=0.62, y=0.0, step=1,
                    color=C_AXIS, show_labels=True):
    """数轴 → (group, to_x(value))。"""
    def to_x(v):
        return v * unit
    x1, x2 = to_x(vmin), to_x(vmax)
    axis = Line([x1, y, 0], [x2, y, 0], color=color, stroke_width=2.5)
    axis.add_tip(tip_length=0.18)
    grp = VGroup(axis)
    ticks = VGroup()
    labels = VGroup()
    for v in range(int(vmin), int(vmax) + 1, step):
        x = to_x(v)
        big = (v == 0)
        ticks.add(Line([x, y - (0.16 if big else 0.1), 0],
                       [x, y + (0.16 if big else 0.1), 0],
                       color=C_TXT if big else color,
                       stroke_width=2 if big else 1.5))
        if show_labels:
            lab = T(str(v), 22, C_TXT if big else C_FIX)
            lab.next_to(Dot([x, y, 0], radius=0.001), DOWN, buff=0.14)
            labels.add(lab)
    grp.add(ticks, labels)
    return grp, to_x


def fig_numberline_basic():
    grp, to_x = make_numberline(-5, 5)
    head = T("数轴三要素：原点、正方向、单位长度", 30, C_HL).to_edge(UP, buff=0.6)
    marks = VGroup(
        T("原点 O：表示 0", 24, C_MAIN).move_to([-4.0, -2.0, 0]),
        T("正方向：向右为正", 24, C_BLUE).move_to([0, -2.0, 0]),
        T("单位长度：一样间隔", 24, C_HL).move_to([4.0, -2.0, 0]),
    )
    return [_g(VGroup(grp, head), 1.1), _g(marks, 0.9)]


def fig_numberline_points():
    grp, to_x = make_numberline(-5, 5, y=0.3)
    dA = Dot([to_x(-3), 0.3, 0], color=C_MAIN, radius=0.1)
    dB = Dot([to_x(2), 0.3, 0], color=C_AUX, radius=0.1)
    lA = T("A", 26, C_MAIN).next_to(dA, UP, buff=0.15)
    lB = T("B", 26, C_AUX).next_to(dB, UP, buff=0.15)
    note = T("右边的数总比左边大：2 > −3", 28, C_HL).move_to([0, -1.8, 0])
    note2 = T("从 A 到 B：向右移动 5 个单位", 24, C_FIX).move_to([0, -2.7, 0])
    return [_g(grp, 1.0), _g(VGroup(dA, dB, lA, lB), 0.8), _g(VGroup(note, note2), 0.8)]


def fig_abs_distance():
    grp, to_x = make_numberline(-5, 5, y=0.3)
    dA = Dot([to_x(-3), 0.3, 0], color=C_MAIN, radius=0.1)
    lA = T("−3", 24, C_MAIN).next_to(dA, DOWN, buff=0.15)
    arc = ArcBetweenPoints([to_x(-3), 0.75, 0], [to_x(0), 0.75, 0], angle=-1.1,
                           color=C_HL, stroke_width=3)
    arc.add_tip(tip_length=0.15)
    dist = T("距离 = 3", 24, C_HL).move_to([to_x(-1.5), 1.6, 0])
    big = T("|−3| = 3", 40, C_MAIN).move_to([3.6, 0.8, 0])
    note = T("绝对值 = 数轴上到原点的距离", 26, C_FIX).move_to([3.6, -0.4, 0])
    note2 = T("距离永远非负", 26, C_AUX).move_to([3.6, -1.4, 0])
    return [_g(VGroup(grp, dA, lA), 1.0), _g(VGroup(arc, dist), 0.8),
            _g(VGroup(big, note, note2), 0.9)]


def fig_add_move():
    grp, to_x = make_numberline(-6, 4, y=0.3)
    d0 = Dot([to_x(-1), 0.3, 0], color=C_MAIN, radius=0.1)
    start = T("从 −1 出发", 24, C_MAIN).next_to(d0, DOWN, buff=0.15)
    arr = Arrow([to_x(-1), 1.0, 0], [to_x(-4), 1.0, 0], color=C_AUX,
                stroke_width=5)
    mov = T("再向左移 3（加 −3）", 24, C_AUX).move_to([to_x(-2.5), 1.5, 0])
    d1 = Dot([to_x(-4), 0.3, 0], color=C_HL, radius=0.12)
    end = T("到 −4", 24, C_HL).next_to(d1, DOWN, buff=0.15)
    eq = T("(−1) + (−3) = −4", 34, C_MAIN).move_to([0, -2.0, 0])
    return [_g(VGroup(grp, d0, start), 0.9), _g(VGroup(arr, mov), 0.8),
            _g(VGroup(d1, end), 0.5), _g(eq, 0.7)]


def fig_power_expand():
    base = T("(−2)³", 44, C_HL).move_to([-3.6, 0.6, 0])
    eqs = VGroup(
        T("= (−2) × (−2) × (−2)", 30),
        T("= 4 × (−2)", 30),
        T("= −8", 30, C_MAIN),
    ).arrange(DOWN, buff=0.35, aligned_edge=LEFT).move_to([1.6, 0.7, 0])
    note = T("指数 3 = 相同因数 (−2) 的个数", 26, C_FIX).move_to([-3.6, -0.9, 0])
    note2 = T("读作：负二的三次方", 24, C_FIX).move_to([-3.6, -1.8, 0])
    return [_g(base, 0.6), _g(eqs, 1.2), _g(VGroup(note, note2), 0.7)]


def fig_sci_notation():
    big = T("3.5 × 10⁴", 48, C_HL).move_to([0, 0.9, 0])
    a1 = T("a：1 ≤ a < 10（一位整数）", 26, C_MAIN).move_to([-3.2, -0.7, 0])
    a2 = T("n：小数点移动的位数", 26, C_BLUE).move_to([3.2, -0.7, 0])
    demo = VGroup(
        T("35000 = 3.5 × 10⁴（小数点右移 4 位）", 26),
        T("0.00035 = 3.5 × 10⁻⁴（小数点左移 4 位）", 26),
    ).arrange(DOWN, buff=0.3).move_to([0, -2.0, 0])
    return [_g(big, 0.7), _g(VGroup(a1, a2), 0.9), _g(demo, 0.9)]


FIGS = {
    "hexprism": fig_hexprism,
    "pyramid_counts": fig_pyramid_counts,
    "cyl_net": fig_cyl_net,
    "cone_net": fig_cone_net,
    "prism3_net": fig_prism3_net,
    "net_141": fig_net_141,
    "net_faces": fig_net_faces,
    "net_options": fig_net_options,
    "cube_tri": fig_cube_tri,
    "cube_rect": fig_cube_rect,
    "cube_hex": fig_cube_hex,
    "cyl_cuts": fig_cyl_cuts,
    "cyl_views": fig_cyl_views,
    "cone_views": fig_cone_views,
    "blocks3d": fig_blocks3d,
    "blocks_front": fig_blocks_front,
    "blocks_top": fig_blocks_top,
    "blocks_left": fig_blocks_left,
    "views_all": fig_views_all,
    "faces_solids": fig_faces_of_solids,
}


# ================= 分幕呈现器 =================

def _clear_check_width(mobj, max_w=13.4):
    if mobj.width > max_w:
        mobj.scale(max_w / mobj.width)
    return mobj


def present(sc, vis):
    """按 vis 描述播放一幕动画，返回已用时间。"""
    k = vis["kind"]
    used = 0.0

    if k == "title":
        main = _clear_check_width(T(vis["main"], 46))
        sc.play(FadeIn(main, shift=UP * 0.25), run_time=0.8)
        used += 0.8
        if vis.get("sub"):
            sub = _clear_check_width(T(vis["sub"], 28, C_HL))
            sub.next_to(main, DOWN, buff=0.45)
            sc.play(FadeIn(sub), run_time=0.5)
            used += 0.5

    elif k == "bullets":
        return _present_bullets(sc, vis)

    elif k == "shapes":
        head = _clear_check_width(T(vis.get("title", ""), 34, C_HL))
        head.to_edge(UP, buff=0.55)
        sc.play(FadeIn(head), run_time=0.5)
        used += 0.5
        builders = {"cuboid": fig_cuboid, "cylinder": fig_cylinder,
                    "cone": fig_cone, "ball": fig_ball,
                    "prism6": lambda: fig_prism(6), "pyramid": fig_pyramid,
                    "prism3": lambda: fig_prism(3)}
        n = len(vis["items"])
        xs = np.linspace(-5.0, 5.0, n)
        for (label, key), x in zip(vis["items"], xs):
            fig = builders[key]()
            fig.scale(min(1.0, 2.4 / max(fig.width, 0.01)))
            fig.move_to([x, 0.4, 0])
            lb = _clear_check_width(T(label, 26)).move_to([x, -1.9, 0])
            sc.play(FadeIn(fig, scale=0.8), FadeIn(lb), run_time=0.6)
            used += 0.6
        if vis.get("note"):
            note = _clear_check_width(T(vis["note"], 26, C_MAIN))
            note.to_edge(DOWN, buff=0.55)
            sc.play(FadeIn(note, shift=UP * 0.2), run_time=0.5)
            used += 0.5

    elif k == "fig":
        head = _clear_check_width(T(vis.get("title", ""), 32, C_HL))
        head.to_edge(UP, buff=0.45)
        sc.play(FadeIn(head), run_time=0.5)
        used += 0.5
        for mobj, rt in FIGS[vis["fig"]]():
            mobj = _clear_check_width(mobj, 12.6)
            if vis.get("fig") and vis["fig"] in ("cube_tri", "cube_rect",
                                                 "cube_hex") and mobj is not None:
                pass
            sc.play(Create(mobj), run_time=rt)
            used += rt

    elif k == "problem":
        tag = vis.get("tag", "例题")
        chip = T(tag, 26, "#1a1a2e")
        chip_bg = SurroundingRectangle(chip, color=C_HL, buff=0.12,
                                       corner_radius=0.1)
        chip_bg.set_fill(C_HL, 1.0)
        chipg = VGroup(chip_bg, chip).to_edge(UP, buff=0.5).shift(LEFT * 5.2)
        head = _clear_check_width(T(vis.get("title", ""), 30))
        head.next_to(chipg, RIGHT, buff=0.4)
        sc.play(FadeIn(chipg), FadeIn(head), run_time=0.6)
        used += 0.6
        objs = [_clear_check_width(T(t, 27)) for t in vis["lines"]]
        grp = VGroup(*objs)
        grp.arrange(DOWN, buff=0.38, aligned_edge=LEFT)
        grp.move_to([0, -0.7, 0])
        for obj in objs:
            sc.play(FadeIn(obj, shift=LEFT * 0.2), run_time=0.35)
            used += 0.35
        return used

    elif k == "steps":
        return _present_steps(sc, vis)

    elif k == "twocol":
        return _present_twocol(sc, vis)

    elif k == "warn":
        return _present_warn(sc, vis)
        used += 0.6

    elif k == "summary":
        return _present_summary(sc, vis)

    else:
        raise ValueError(f"未知视觉类型: {k}")

    return used


def _card(lines_txt, header, color, x, top=1.0):
    """并排卡片：标题 + 多行实例。"""
    if isinstance(lines_txt, str):
        lines_txt = [lines_txt]
    rows = [T(lines_txt[0], 27, color)]
    for ln in lines_txt[1:]:
        rows.append(T(ln, 24, C_TXT))
    body = VGroup(*rows).arrange(DOWN, buff=0.22, aligned_edge=LEFT)
    head = T(header, 26, color)
    grp = VGroup(head, body).arrange(DOWN, buff=0.3, aligned_edge=LEFT)
    box = SurroundingRectangle(grp, color=color, buff=0.32, corner_radius=0.14)
    card = VGroup(box, grp)
    maxw = 6.1
    if card.width > maxw:
        card.scale(maxw / card.width)
    card.move_to([x, 0.3, 0])
    return card


def _present_warn(sc, vis):
    """易错场景：左右并排「✗ 错误实例 / ✓ 正确实例」，讲完随场景淡出。"""
    used = 0.0
    head = _clear_check_width(T(vis.get("title", "易错提醒"), 34, C_AUX))
    head.to_edge(UP, buff=0.55)
    sc.play(FadeIn(head), run_time=0.5)
    used += 0.5
    badc = _card(vis.get("bad", ""), "✗ 错误示例", C_AUX, -3.1)
    goodc = _card(vis.get("good", ""), "✓ 正确实例", C_MAIN, 3.1)
    sc.play(FadeIn(badc, shift=UP * 0.2), run_time=0.6)
    used += 0.6
    sc.play(FadeIn(goodc, shift=UP * 0.2), run_time=0.6)
    used += 0.6
    if vis.get("note"):
        note = _clear_check_width(T(vis["note"], 26, C_MAIN))
        note.to_edge(DOWN, buff=0.75)
        sc.play(FadeIn(note, shift=UP * 0.2), run_time=0.5)
        used += 0.5
    return used


SUB_FONT = "Microsoft YaHei"


def subtitle_chunks(text, maxlen=18):
    """读白按标点切句、合并到 maxlen 以内，作为字幕条。"""
    import re as _re
    text = _re.sub(r"\s+", "", text)
    parts = [q for q in _re.split(r"(?<=[。！？；!?;，,])", text) if q]
    out, buf = [], ""
    for q in parts:
        if len(buf) + len(q) <= maxlen:
            buf += q
        else:
            if buf:
                out.append(buf)
            buf = q
    if buf:
        out.append(buf)
    return out or ([text] if text else [])


def show_subtitles(sc, narr, used, total):
    """字幕引擎：整幕时长内按字数比例轮播字幕（白字黑边，底部居中）。
    used = 呈现动画已耗时间；字幕与配音按时间轴对齐，早于 used 的片段跳过。
    最后一条保留到 end_scene 统一淡出。"""
    if not narr or total <= 0:
        return
    chunks = subtitle_chunks(narr)
    if not chunks:
        return
    weights = [len(c) + 2 for c in chunks]
    total_w = sum(weights)
    sched = []
    acc = 0.0
    for c, w in zip(chunks, weights):
        d = total * w / total_w
        sched.append((c, acc, acc + d))
        acc += d
    prev = None
    for c, t0, t1 in sched:
        if t1 <= used:
            continue  # 已在动画期间过去
        sub = Text(c, font=SUB_FONT, font_size=26, color="#FFFFFF")
        sub.set_stroke(color="#000000", width=2.0)
        sub.to_edge(DOWN, buff=0.16)
        sub = _clear_check_width(sub, 12.6)
        bg = Rectangle(width=13.6, height=max(0.62, sub.height + 0.26))
        bg.set_fill("#000000", 0.72).set_stroke(width=0)
        bg.move_to(sub)
        subgrp = VGroup(bg, sub)
        sc.add(subgrp)
        if prev is not None:
            sc.remove(prev)
        start = max(t0, used)
        d = min(t1, total) - start
        if d > 0.05:
            sc.wait(d)
        prev = subgrp


def _present_bullets(sc, vis):
    used = 0.0
    head = _clear_check_width(T(vis.get("title", ""), 34, C_HL))
    head.to_edge(UP, buff=0.55)
    sc.play(FadeIn(head), run_time=0.5)
    used += 0.5
    objs = []
    for i, t in enumerate(vis["lines"]):
        objs.append(_clear_check_width(
            T(t, 28, C_HL if i in vis.get("hl", []) else C_TXT)))
    grp = VGroup(*objs)
    if grp.height > 4.6:
        grp.arrange(DOWN, buff=0.3, aligned_edge=LEFT)
    else:
        grp.arrange(DOWN, buff=0.42, aligned_edge=LEFT)
    grp.next_to(head, DOWN, buff=0.65)
    for obj in objs:
        sc.play(FadeIn(obj, shift=LEFT * 0.2), run_time=0.35)
        used += 0.35
    return used


def _present_lines_block(sc, lines, head, size):
    """problem 幕的正文块（已逐条播放过则跳过；此函数做排版占位）。"""
    return 0.0


def _present_steps(sc, vis):
    used = 0.0
    head = _clear_check_width(T(vis.get("title", "解"), 32, C_HL))
    head.to_edge(UP, buff=0.5)
    sc.play(FadeIn(head), run_time=0.5)
    used += 0.5
    objs = [_clear_check_width(T(t, 28)) for t in vis["lines"]]
    grp = VGroup(*objs)
    grp.arrange(DOWN, buff=0.36, aligned_edge=LEFT)
    top_y = 0.6
    grp.move_to([0, 0, 0])
    grp.shift(UP * (top_y - grp.get_top()[1]))
    if vis.get("result"):
        res = _clear_check_width(T(vis["result"], 32, C_MAIN))
        res.next_to(grp, DOWN, buff=0.5)
    else:
        res = None
    for obj in objs:
        sc.play(FadeIn(obj, shift=LEFT * 0.2), run_time=0.35)
        used += 0.35
    if res is not None:
        sc.play(Write(res), run_time=0.7)
        sc.play(Flash(res, color=C_MAIN, line_length=0.2), run_time=0.5)
        used += 1.2
    return used


def _present_twocol(sc, vis):
    used = 0.0
    head = _clear_check_width(T(vis.get("title", ""), 32, C_HL))
    head.to_edge(UP, buff=0.5)
    sc.play(FadeIn(head), run_time=0.5)
    used += 0.5
    for side, col, key in (("L", C_MAIN, "left"), ("R", C_BLUE, "right")):
        block = vis[key]
        headt = _clear_check_width(T(block["head"], 28, col))
        lines = [_clear_check_width(T(t, 25)) for t in block["lines"]]
        grp = VGroup(headt, *lines)
        grp.arrange(DOWN, buff=0.3, aligned_edge=LEFT)
        box = SurroundingRectangle(grp, color=col, buff=0.35, corner_radius=0.15)
        g = VGroup(box, grp)
        g.move_to([side_value(side), 0.1, 0])
        sc.play(FadeIn(g, shift=UP * 0.2), run_time=0.7)
        used += 0.7
    return used


def side_value(side):
    return -3.4 if side == "L" else 3.4


def _present_summary(sc, vis):
    used = 0.0
    head = T("课堂小结", 36, C_HL)
    head.to_edge(UP, buff=0.5)
    sc.play(FadeIn(head), run_time=0.5)
    used += 0.5
    objs = [_clear_check_width(T(t, 28)) for t in vis["lines"]]
    grp = VGroup(*objs)
    grp.arrange(DOWN, buff=0.36, aligned_edge=LEFT)
    grp.move_to([0, 0.7, 0])
    for obj in objs:
        sc.play(FadeIn(obj, shift=LEFT * 0.2), run_time=0.35)
        used += 0.35
    if vis.get("hw"):
        hw = _clear_check_width(T("作业：" + vis["hw"], 26, C_MAIN))
        hwbox = SurroundingRectangle(hw, color=C_MAIN, buff=0.25,
                                     corner_radius=0.12)
        hwg = VGroup(hwbox, hw).to_edge(DOWN, buff=0.6)
        sc.play(FadeIn(hwg, shift=UP * 0.2), run_time=0.6)
        used += 0.6
    return used


FIGS.update({
    "numberline": fig_numberline_basic,
    "numberline_points": fig_numberline_points,
    "abs_distance": fig_abs_distance,
    "add_move": fig_add_move,
    "power_expand": fig_power_expand,
    "sci_notation": fig_sci_notation,
})
