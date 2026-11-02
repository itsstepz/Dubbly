"""Рисует картинки для интерфейса (переключатели и стрелки списков) для обеих тем.

Нужен только при изменении цветов темы: python tools/make_ui_assets.py (нужен пакет Pillow).
Готовые файлы лежат в assets/ui и в программу попадают вместе с ней.
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

OUT = Path(__file__).resolve().parent.parent / "assets" / "ui"

THEMES = {
    "dark":  dict(inp="#23282d", bd="#3e454d", c1="#373d45", c2="#2d3238", mu="#98a2ad"),
    "light": dict(inp="#dde2e8", bd="#cfd6de", c1="#f7f9fb", c2="#e9edf2", mu="#66727e"),
}
ACC2, ACC3 = "#f58a4d", "#df5f29"
SS = 8  # во сколько раз рисуем крупнее для сглаживания


def hx(c):
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def vgrad(size, top, bottom):
    w, h = size
    img = Image.new("RGBA", size)
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = y / max(h - 1, 1)
        d.line([(0, y), (w, y)], fill=tuple(round(a + (b - a) * t) for a, b in zip(hx(top), hx(bottom))) + (255,))
    return img


def switch(theme, on):
    t = THEMES[theme]
    W, H = 44 * SS, 24 * SS
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, W - 1, H - 1], radius=H // 2, fill=255)
    track = vgrad((W, H), ACC2, ACC3) if on else Image.new("RGBA", (W, H), hx(t["inp"]) + (255,))
    img.paste(track, (0, 0), mask)
    d = ImageDraw.Draw(img)
    if not on:  # тонкая рамка и «вдавленность»
        d.rounded_rectangle([0, 0, W - 1, H - 1], radius=H // 2, outline=hx(t["bd"]) + (255,), width=SS)
        d.arc([SS, SS, W - SS, H - SS], 200, 340, fill=(0, 0, 0, 60 if theme == "dark" else 0), width=SS)
    r = 9 * SS
    cx = (33 if on else 11) * SS
    cy = H // 2
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).ellipse([cx - r, cy - r + 2 * SS, cx + r, cy + r + 2 * SS], fill=(0, 0, 0, 90))
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(2 * SS)))
    knob = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    kmask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(kmask).ellipse([cx - r, cy - r, cx + r, cy + r], fill=255)
    fill = Image.new("RGBA", (W, H), (255, 255, 255, 255)) if on else vgrad((W, H), t["c1"], t["c2"])
    knob.paste(fill, (0, 0), kmask)
    img.alpha_composite(knob)
    return img


def chevron(theme):
    S = 16 * SS
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c = hx(THEMES[theme]["mu"]) + (255,)
    w = 2 * SS
    pts = [(3.5 * SS, 5.5 * SS), (8 * SS, 10.5 * SS), (12.5 * SS, 5.5 * SS)]
    d.line(pts, fill=c, width=w, joint="curve")
    for x, y in (pts[0], pts[2]):
        d.ellipse([x - w / 2, y - w / 2, x + w / 2, y + w / 2], fill=c)
    return img


def reset_icon(theme):
    """Круговая стрелка «сбросить»."""
    import math
    S = 16 * SS
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c = hx(THEMES[theme]["mu"]) + (255,)
    cx = cy = S / 2
    r = 4.6 * SS
    d.arc([cx - r, cy - r, cx + r, cy + r], start=-40, end=250, fill=c, width=round(1.7 * SS))
    # наконечник стрелки на конце дуги (угол 250° от оси X, против часовой стрелки на экране)
    a = math.radians(250)
    tx, ty = cx + r * math.cos(a), cy + r * math.sin(a)
    # направление движения по касательной (в сторону увеличения угла)
    dx, dy = -math.sin(a), math.cos(a)
    nx, ny = -dy, dx
    size = 3.4 * SS
    p1 = (tx + dx * size * 0.9, ty + dy * size * 0.9)
    p2 = (tx - nx * size * 0.75, ty - ny * size * 0.75)
    p3 = (tx + nx * size * 0.75, ty + ny * size * 0.75)
    d.polygon([p1, p2, p3], fill=c)
    return img


def save(img, name, size):
    OUT.mkdir(parents=True, exist_ok=True)
    img.resize(size, Image.LANCZOS).save(OUT / f"{name}.png")
    img.resize((size[0] * 2, size[1] * 2), Image.LANCZOS).save(OUT / f"{name}@2x.png")


for theme in THEMES:
    save(switch(theme, False), f"switch-off-{theme}", (44, 24))
    save(switch(theme, True), f"switch-on-{theme}", (44, 24))
    save(chevron(theme), f"chevron-down-{theme}", (16, 16))
    save(reset_icon(theme), f"reset-{theme}", (16, 16))
print("готово:", ", ".join(sorted(p.name for p in OUT.glob("*.png") if "@2x" not in p.name)))
