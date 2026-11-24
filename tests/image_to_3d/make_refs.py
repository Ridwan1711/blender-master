#!/usr/bin/env python3
"""Generate the five reference-image sets used by the image-to-3D tests (system Python + Pillow).

    python tests/image_to_3d/make_refs.py      ->  tests/image_to_3d/refs/<case>/<view>.png

Drawn as 2D artwork, independently of any Blender code, in the styles people actually hand
over: pixel-art sprites, flat low-poly concept art, architectural elevations, a technical
blueprint, and a soft-shaded single-view illustration. Side views are seen from +X with the
object's front on the image's LEFT (see bkit/recon.py world convention).
"""
import math
import os

from PIL import Image, ImageDraw, ImageFilter

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "refs")
BG = (233, 233, 236)


def canvas(w=512, h=512, bg=BG):
    im = Image.new("RGB", (w, h), bg)
    return im, ImageDraw.Draw(im)


def save(im, case, view):
    d = os.path.join(OUT, case)
    os.makedirs(d, exist_ok=True)
    im.save(os.path.join(d, view + ".png"))


# 1 ----------------------------------------------------------------- voxel knight (pixel art)
KNIGHT_PAL = {"P": (192, 57, 43), "H": (138, 143, 153), "h": (90, 95, 105), "V": (30, 30, 36),
              "A": (184, 190, 200), "T": (46, 92, 154), "Y": (224, 184, 58), "B": (107, 68, 35),
              "G": (107, 68, 35), "L": (74, 78, 87), "S": (90, 58, 30)}
KNIGHT_FRONT = [".....PP.....", ".....PP.....", "...HHHHHH...", "..HHHHHHHH..", "..HVVVVVVH..",
                "..HhhhhhhH..", "...HHHHHH...", ".AAATTTTAAA.", "AAATTYYTTAAA", "AA.TTTTTT.AA",
                "AA.TTYYTT.AA", "GG.BBBBBB.GG", "...TTTTTT...", "...TTTTTT...", "...LL..LL...",
                "...LL..LL...", "...LL..LL...", "...LL..LL...", "..SSS..SSS..", "..SSS..SSS.."]
KNIGHT_SIDE = ["...PP...", "...PPP..", "..HHHH..", ".HHHHHH.", ".VHHHHH.", ".hHHHHH.", "..HHHH..",
               ".TAAAAA.", ".TAAAAA.", ".TAAAAA.", ".TAAAAA.", ".BGGGBB.", ".TTTTTT.", "..TTTT..",
               "..LLLL..", "..LLLL..", "..LLLL..", "..LLLL..", ".SSSSS..", ".SSSSS.."]


def sprite(rows, cell=20):
    w, h = len(rows[0]) * cell, len(rows) * cell
    im, d = canvas(max(512, w + 80), max(512, h + 80))
    ox, oy = (im.width - w) // 2, (im.height - h) // 2
    for r, line in enumerate(rows):
        assert len(line) == len(rows[0]), line
        for c, ch in enumerate(line):
            if ch != ".":
                d.rectangle([ox + c * cell, oy + r * cell, ox + (c + 1) * cell - 1, oy + (r + 1) * cell - 1],
                            fill=KNIGHT_PAL[ch])
    return im


# 2 ----------------------------------------------------------------- low-poly robot (flat concept art)
ORANGE, ORANGE_D, GREY, CYAN, RED = (224, 123, 57), (184, 94, 37), (59, 63, 70), (79, 209, 232), (210, 60, 50)


def robot(view):
    im, d = canvas()
    S, gy, cx = 250.0, 470, 256          # px per metre, ground y, centre x

    def box(x0, z0, x1, z1, col, facet=None):
        X0, X1 = cx + x0 * S, cx + x1 * S
        Y0, Y1 = gy - z1 * S, gy - z0 * S
        d.rectangle([X0, Y0, X1, Y1], fill=col)
        if facet:  # low-poly two-tone facet: darker lower-right triangle
            d.polygon([(X1, Y0), (X1, Y1), (X0, Y1)], fill=facet)
    if view == "front":
        for sx in (-1, 1):
            box(sx * 0.14 - 0.11, 0.0, sx * 0.14 + 0.11, 0.08, GREY)               # feet
            box(sx * 0.14 - 0.06, 0.08, sx * 0.14 + 0.06, 0.53, ORANGE, ORANGE_D)   # legs
            box(sx * 0.38 - 0.05, 0.62, sx * 0.38 + 0.05, 1.07, ORANGE, ORANGE_D)   # arms
            box(sx * 0.38 - 0.06, 0.52, sx * 0.38 + 0.06, 0.62, GREY)              # hands
            d.ellipse([cx + (sx * 0.36 - 0.09) * S, gy - 1.15 * S, cx + (sx * 0.36 + 0.09) * S, gy - 0.97 * S], fill=GREY)
        box(-0.21, 0.53, 0.21, 0.63, GREY)                                         # pelvis
        d.polygon([(cx - 0.30 * S, gy - 1.13 * S), (cx + 0.30 * S, gy - 1.13 * S), (cx + 0.24 * S, gy - 0.63 * S),
                   (cx - 0.24 * S, gy - 0.63 * S)], fill=ORANGE)                    # torso (tapered)
        d.polygon([(cx + 0.30 * S, gy - 1.13 * S), (cx + 0.24 * S, gy - 0.63 * S), (cx, gy - 0.63 * S)], fill=ORANGE_D)
        box(-0.10, 0.90, 0.10, 1.00, CYAN)                                         # chest light
        box(-0.05, 1.13, 0.05, 1.18, GREY)                                         # neck
        box(-0.17, 1.18, 0.17, 1.44, ORANGE, ORANGE_D)                             # head
        box(-0.13, 1.27, 0.13, 1.34, CYAN)                                         # visor
        box(-0.01, 1.44, 0.01, 1.56, GREY)                                         # antenna
        d.ellipse([cx - 0.03 * S, gy - 1.62 * S, cx + 0.03 * S, gy - 1.56 * S], fill=RED)
    else:  # side: depth along x (front = LEFT, i.e. negative)
        box(-0.19, 0.0, 0.11, 0.08, GREY)                                          # feet stick forward
        box(-0.07, 0.08, 0.07, 0.53, ORANGE, ORANGE_D)
        box(-0.15, 0.53, 0.15, 0.63, GREY)
        d.polygon([(cx - 0.18 * S, gy - 1.13 * S), (cx + 0.18 * S, gy - 1.13 * S), (cx + 0.16 * S, gy - 0.63 * S),
                   (cx - 0.14 * S, gy - 0.63 * S)], fill=ORANGE)
        d.polygon([(cx + 0.18 * S, gy - 1.13 * S), (cx + 0.16 * S, gy - 0.63 * S), (cx, gy - 0.63 * S)], fill=ORANGE_D)
        box(-0.05, 0.62, 0.05, 1.07, ORANGE_D)                                     # arm (side)
        box(-0.06, 0.52, 0.06, 0.62, GREY)
        d.ellipse([cx - 0.09 * S, gy - 1.15 * S, cx + 0.09 * S, gy - 0.97 * S], fill=GREY)
        box(-0.05, 1.13, 0.05, 1.18, GREY)
        box(-0.15, 1.18, 0.15, 1.44, ORANGE, ORANGE_D)
        box(-0.155, 1.27, -0.12, 1.34, CYAN)                                       # visor at the front edge
        box(-0.01, 1.44, 0.01, 1.56, GREY)
        d.ellipse([cx - 0.03 * S, gy - 1.62 * S, cx + 0.03 * S, gy - 1.56 * S], fill=RED)
    return im


# 3 ----------------------------------------------------------------- medieval house (elevations)
STONE, STONE_L, PLASTER, BEAM, ROOF, ROOF_L, DOOR, WIN = (128, 126, 120), (95, 93, 88), (236, 224, 196), \
    (92, 60, 38), (139, 46, 30), (110, 34, 22), (90, 58, 34), (40, 44, 52)


def house(view):
    im, d = canvas(560, 512)
    S, gy = 52.0, 478
    W = 6.0 if view == "front" else 9.0
    cx = im.width / 2
    eave, ridge, stone_h = 4.2, 7.6, 2.4

    def X(x):
        return cx + x * S

    def Y(z):
        return gy - z * S
    # walls
    d.rectangle([X(-W / 2), Y(stone_h), X(W / 2), Y(0)], fill=STONE)
    for z in [0.6, 1.2, 1.8]:
        d.line([X(-W / 2), Y(z), X(W / 2), Y(z)], fill=STONE_L, width=2)
    d.rectangle([X(-W / 2), Y(eave), X(W / 2), Y(stone_h)], fill=PLASTER)
    if view == "front":
        # gable end: triangle wall + timber frame + roof edges with overhang
        d.polygon([(X(-W / 2), Y(eave)), (X(W / 2), Y(eave)), (X(0), Y(ridge))], fill=PLASTER)
        for x in (-W / 2, -1.0, 1.0, W / 2):
            d.line([X(x), Y(stone_h), X(x), Y(eave)], fill=BEAM, width=6)
        d.line([X(-W / 2), Y(stone_h), X(W / 2), Y(stone_h)], fill=BEAM, width=8)
        d.line([X(-W / 2), Y(eave), X(W / 2), Y(eave)], fill=BEAM, width=6)
        d.line([X(-W / 2), Y(eave), X(-1.0), Y(stone_h)], fill=BEAM, width=5)
        d.line([X(W / 2), Y(eave), X(1.0), Y(stone_h)], fill=BEAM, width=5)
        d.line([X(0), Y(eave), X(0), Y(ridge)], fill=BEAM, width=6)
        # roof slab: underside parallel to the gable line, 0.05 above it, 0.30 thick (vertical),
        # overhanging the wall by o. (Fixture fix: the first version drew a self-crossing
        # "bow-tie" polygon that pinched the roof to zero thickness - caught by inspection in T3.)
        o, k = 0.35, (ridge - eave) / (W / 2)
        for sgn in (-1, 1):
            ze = eave - o * k + 0.05
            d.polygon([(X(0), Y(ridge + 0.05)), (X(sgn * (W / 2 + o)), Y(ze)),
                       (X(sgn * (W / 2 + o)), Y(ze + 0.30)), (X(0), Y(ridge + 0.35))], fill=ROOF)
        d.rectangle([X(-0.55), Y(2.0), X(0.55), Y(0)], fill=DOOR)                 # door
        d.pieslice([X(-0.55), Y(2.55), X(0.55), Y(1.45)], 180, 360, fill=DOOR)
        for x in (-1.9, 1.9):
            d.rectangle([X(x - 0.35), Y(3.7), X(x + 0.35), Y(2.9)], fill=WIN)
        d.rectangle([X(-0.3), Y(5.7), X(0.3), Y(5.0)], fill=WIN)
    else:
        # long side: roof slope seen face-on as a band from eave to ridge, chimney near the back
        # same roof as the gable view: eave edge at eave - o*k + 0.05, top at ridge + 0.35
        o, k = 0.35, (ridge - eave) / 3.0
        ze = eave - o * k + 0.05
        d.rectangle([X(-W / 2 - o), Y(ridge + 0.35), X(W / 2 + o), Y(ze)], fill=ROOF)
        for i in range(1, 9):
            z = ze + i * (ridge + 0.35 - ze) / 9
            d.line([X(-W / 2 - o), Y(z), X(W / 2 + o), Y(z)], fill=ROOF_L, width=2)
        d.rectangle([X(W / 2 - 2.4), Y(8.6), X(W / 2 - 1.6), Y(ridge - 0.6)], fill=STONE)   # chimney (back = right)
        for x in (-W / 2, -1.5, 1.5, W / 2):
            d.line([X(x), Y(stone_h), X(x), Y(eave)], fill=BEAM, width=6)
        d.line([X(-W / 2), Y(stone_h), X(W / 2), Y(stone_h)], fill=BEAM, width=8)
        for x in (-3.0, 0.0, 3.0):
            d.rectangle([X(x - 0.4), Y(3.8), X(x + 0.4), Y(2.85)], fill=WIN)
        for x in (-2.5, 2.5):
            d.rectangle([X(x - 0.35), Y(1.6), X(x + 0.35), Y(0.8)], fill=WIN)
    return im


# 4 ----------------------------------------------------------------- walkie-talkie (blueprint)
BODY, BODY_D, GRILLE, SCREEN, KNOB, ANT = (52, 56, 62), (36, 39, 44), (20, 22, 25), (122, 150, 120), (28, 30, 33), (30, 32, 35)


def walkie(view):
    im, d = canvas(512, 512, (226, 232, 238))
    S, gy, cx = 1800.0, 470, 256
    W, H, D, R = 0.07, 0.16, 0.04, 0.008

    def rrect(x0, z0, x1, z1, r, col):
        d.rounded_rectangle([cx + x0 * S, gy - z1 * S, cx + x1 * S, gy - z0 * S], radius=r * S, fill=col)
    if view == "front":
        rrect(-W / 2, 0, W / 2, H, R, BODY)
        rrect(-W / 2 + 0.003, 0.003, W / 2 - 0.003, H - 0.003, R - 0.002, BODY_D)
        # antenna (left) rises from its base on top. Fixture fix: v1 drew it from z=4 mm as an opaque
        # strip over the body face in front AND side (a hidden part drawn visible) - caught in T4.
        rrect(-0.026, H - 0.004, -0.014, H + 0.075, 0.004, ANT)
        rrect(-0.029, H - 0.002, -0.011, H + 0.012, 0.003, KNOB)               # antenna base
        rrect(0.011, H - 0.002, 0.025, H + 0.012, 0.003, KNOB)                 # volume knob (right)
        for r_ in range(5):
            for c_ in range(5):
                x, z = -0.022 + c_ * 0.011, 0.142 - r_ * 0.011
                d.ellipse([cx + (x - 0.003) * S, gy - (z + 0.003) * S, cx + (x + 0.003) * S, gy - (z - 0.003) * S], fill=GRILLE)
        rrect(-0.024, 0.055, 0.024, 0.08, 0.002, SCREEN)                       # screen
        for i, x in enumerate((-0.018, 0.0, 0.018)):
            rrect(x - 0.007, 0.022, x + 0.007, 0.036, 0.003, KNOB)             # buttons
    elif view == "side":
        rrect(-D / 2, 0, D / 2, H, R, BODY)
        rrect(-D / 2 + 0.003, 0.003, D / 2 - 0.003, H - 0.003, R - 0.002, BODY_D)
        rrect(-0.006, H - 0.004, 0.006, H + 0.075, 0.004, ANT)
        rrect(-0.009, H - 0.002, 0.009, H + 0.012, 0.003, KNOB)
        rrect(D / 2 - 0.002, 0.07, D / 2 + 0.008, 0.13, 0.003, KNOB)          # belt clip at the back (right)
        rrect(-0.004, 0.09, 0.006, 0.125, 0.002, (70, 75, 82))                 # PTT button on the side face
    else:  # top view: x -> +X, image down -> front (-Y)
        S2, cy = S, 256

        def trect(x0, y0, x1, y1, r, col):
            d.rounded_rectangle([cx + x0 * S2, cy - y1 * S2, cx + x1 * S2, cy - y0 * S2], radius=r * S2, fill=col)
        trect(-W / 2, -D / 2, W / 2, D / 2, R, BODY)
        trect(-W / 2, D / 2 - 0.002, W / 2 - 0.01, D / 2 + 0.008, 0.003, KNOB)  # clip seen from above
        d.ellipse([cx - 0.026 * S2, cy - 0.006 * S2, cx - 0.014 * S2, cy + 0.006 * S2], fill=ANT)
        d.ellipse([cx + 0.011 * S2, cy - 0.007 * S2, cx + 0.025 * S2, cy + 0.007 * S2], fill=KNOB)
    return im


# 5 ----------------------------------------------------------------- fantasy creature (single view)
def creature():
    im, d = canvas(512, 512, (236, 236, 240))
    big = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
    g = ImageDraw.Draw(big)

    def shaded_ellipse(box, base, light, steps=14):
        x0, y0, x1, y1 = box
        for i in range(steps):
            t = i / steps
            col = tuple(int(base[k] + (light[k] - base[k]) * t) for k in range(3)) + (255,)
            cxx, cyy = (x0 + x1) / 2 - (x1 - x0) * 0.12 * t, (y0 + y1) / 2 - (y1 - y0) * 0.12 * t
            rx, ry = (x1 - x0) / 2 * (1 - 0.55 * t), (y1 - y0) / 2 * (1 - 0.55 * t)
            g.ellipse([cxx - rx, cyy - ry, cxx + rx, cyy + ry], fill=col)
    GREEN, GREEN_L, BELLY, LEAF, LEAF_D = (64, 140, 72), (140, 205, 120), (226, 220, 160), (110, 170, 60), (70, 120, 40)
    # tail curling out to the right behind the body
    shaded_ellipse([690, 640, 860, 760], GREEN, GREEN_L)
    shaded_ellipse([800, 560, 900, 660], GREEN, GREEN_L)
    # leaf ears
    for sx in (-1, 1):
        cxl = 512 + sx * 170
        g.polygon([(512 + sx * 90, 300), (cxl + sx * 120, 120), (cxl + sx * 40, 330)], fill=LEAF)
        g.line([(512 + sx * 100, 300), (cxl + sx * 110, 135)], fill=LEAF_D, width=8)
    shaded_ellipse([270, 360, 754, 900], GREEN, GREEN_L)          # body
    shaded_ellipse([300, 180, 724, 560], GREEN, GREEN_L)          # head
    shaded_ellipse([400, 560, 624, 840], BELLY, (250, 248, 220))  # belly
    for sx in (-1, 1):                                            # feet + arms
        shaded_ellipse([512 + sx * 150 - 70, 850, 512 + sx * 150 + 70, 930], GREEN, GREEN_L)
        shaded_ellipse([512 + sx * 230 - 45, 560, 512 + sx * 230 + 45, 700], GREEN, GREEN_L)
    for sx in (-1, 1):                                            # eyes
        ex = 512 + sx * 95
        g.ellipse([ex - 62, 290, ex + 62, 430], fill=(255, 255, 255, 255))
        g.ellipse([ex - 34 + sx * 6, 320, ex + 30 + sx * 6, 410], fill=(25, 25, 30, 255))
        g.ellipse([ex - 18 + sx * 6, 330, ex - 2 + sx * 6, 348], fill=(255, 255, 255, 255))
    g.arc([462, 440, 562, 500], 20, 160, fill=(40, 60, 40, 255), width=8)                 # smile
    g.ellipse([380, 440, 420, 465], fill=(235, 140, 130, 200))
    g.ellipse([604, 440, 644, 465], fill=(235, 140, 130, 200))
    small = big.resize((512, 512), Image.LANCZOS)
    im.paste(small, (0, 0), small)
    return im


def main():
    save(sprite(KNIGHT_FRONT), "voxel_knight", "front")
    save(sprite(KNIGHT_SIDE), "voxel_knight", "side")
    save(robot("front"), "lowpoly_robot", "front")
    save(robot("side"), "lowpoly_robot", "side")
    save(house("front"), "medieval_house", "front")
    save(house("side"), "medieval_house", "side")
    for v in ("front", "side", "top"):
        save(walkie(v), "walkie_talkie", v)
    save(creature(), "fantasy_creature", "front")
    print("written to", OUT)


if __name__ == "__main__":
    main()
