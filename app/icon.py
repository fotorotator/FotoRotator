"""Ikona programu - kreslena cez Pillow (ziadny externy graficky subor).

Motiv: naklonena fotka (vseobecny "obrazok" glyf) + oranzova znacka s
sipkou otacania - vizualne pomenuje, co program robi.
"""

from __future__ import annotations

import math

from PIL import Image, ImageDraw


def draw_icon(size: int = 256) -> Image.Image:
    bg = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(bg)
    pad = size * 0.03
    d.rounded_rectangle([pad, pad, size - pad, size - pad], radius=size * 0.2, fill=(24, 98, 208, 255))

    # Naklonena "fotka" - kreslena na samostatnej vrstve a otocena, aby okraje
    # ostali ostre (rotacia cez Pillow, nie kreslenie sikmych ciar rucne).
    tile = size
    photo_layer = Image.new("RGBA", (tile, tile), (0, 0, 0, 0))
    pd = ImageDraw.Draw(photo_layer)
    pw, ph = size * 0.52, size * 0.40
    px0 = (tile - pw) / 2
    py0 = (tile - ph) / 2
    px1, py1 = px0 + pw, py0 + ph
    pd.rounded_rectangle(
        [px0, py0, px1, py1], radius=size * 0.035,
        fill=(255, 255, 255, 255), outline=(18, 66, 132, 255), width=max(2, int(size * 0.012)),
    )
    sun_r = size * 0.038
    sx, sy = px0 + pw * 0.22, py0 + ph * 0.30
    pd.ellipse([sx - sun_r, sy - sun_r, sx + sun_r, sy + sun_r], fill=(255, 199, 64, 255))
    pd.polygon(
        [
            (px0 + pw * 0.06, py1 - ph * 0.10),
            (px0 + pw * 0.32, py0 + ph * 0.40),
            (px0 + pw * 0.50, py1 - ph * 0.18),
            (px0 + pw * 0.68, py0 + ph * 0.50),
            (px1 - pw * 0.05, py1 - ph * 0.10),
            (px1 - pw * 0.05, py1 - ph * 0.04),
            (px0 + pw * 0.06, py1 - ph * 0.04),
        ],
        fill=(52, 145, 98, 255),
    )
    photo_layer = photo_layer.rotate(-13, resample=Image.BICUBIC, center=(tile / 2, tile / 2))
    bg.alpha_composite(photo_layer)

    # Znacka otacania - oranzovy kruh s bielou sipkou, vpravo dole (prekryva
    # roh fotky, aby bolo jasne ze ide o AKCIU nad fotkou).
    r = size * 0.27
    cx, cy = size * 0.735, size * 0.735
    d.ellipse(
        [cx - r, cy - r, cx + r, cy + r],
        fill=(255, 140, 35, 255), outline=(255, 255, 255, 255), width=max(2, int(size * 0.014)),
    )
    arc_r = r * 0.56
    arc_box = [cx - arc_r, cy - arc_r, cx + arc_r, cy + arc_r]
    d.arc(arc_box, start=25, end=305, fill=(255, 255, 255, 255), width=max(2, int(size * 0.045)))
    ah = size * 0.045
    ang = math.radians(25)
    tip_x = cx + arc_r * math.cos(ang)
    tip_y = cy - arc_r * math.sin(ang)
    d.polygon(
        [
            (tip_x - ah * 0.9, tip_y - ah * 0.25),
            (tip_x + ah * 0.5, tip_y + ah * 0.55),
            (tip_x - ah * 0.75, tip_y + ah * 0.95),
        ],
        fill=(255, 255, 255, 255),
    )

    return bg


def save_ico(path, sizes=(16, 24, 32, 48, 64, 128, 256)):
    draw_icon(256).save(path, format="ICO", sizes=[(s, s) for s in sizes])


if __name__ == "__main__":
    import sys

    save_ico(sys.argv[1] if len(sys.argv) > 1 else "icon.ico")
