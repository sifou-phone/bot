#!/usr/bin/env python3
"""Generate placeholder product illustrations (SVG) for the Victoria store.

Replace the files in assets/img/products/ with real photos whenever you have them
(and update the "image" field in assets/js/products.js accordingly).

Usage:  python3 tools/generate_product_images.py
"""
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "assets" / "img" / "products"

# id, garment type, base colour, piping colour
ITEMS = [
    ("pink-classic", "pyjama", "#f2a7c3", "#2b1d22"),
    ("black-royal", "pyjama", "#2b2326", "#d4af37"),
    ("champagne", "pyjama", "#e8cfa6", "#7a5a2b"),
    ("navy-night", "pyjama", "#2f3a63", "#e9c46a"),
    ("sky-dream", "pyjama", "#b9d4ee", "#ffffff"),
    ("lilac-short", "shorts", "#c9b2e6", "#5b3f86"),
    ("mint-short", "shorts", "#a8dcc8", "#2f6b55"),
    ("burgundy-robe", "robe", "#8e2c48", "#d4af37"),
    ("blush-robe", "robe", "#f6c6d4", "#b0476b"),
    ("ivory-gown", "gown", "#f5ece0", "#c9a46a"),
    ("black-lace-gown", "gown", "#262022", "#e8b4c8"),
    ("rosegold-gown", "gown", "#d9a08b", "#7c3f2f"),
]


def hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def mix(h, other, t):
    a, b = hex_to_rgb(h), hex_to_rgb(other)
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def shapes(kind, pip):
    if kind in ("pyjama", "shorts"):
        if kind == "pyjama":
            bottom = "M205,392 L395,392 L422,702 L330,702 L300,488 L270,702 L178,702 Z"
            hems = '<path d="M180,690 L268,690 M332,690 L420,690" stroke="{p}" stroke-width="6" fill="none"/>'
        else:
            bottom = "M205,392 L395,392 L428,566 L322,566 L300,474 L278,566 L172,566 Z"
            hems = '<path d="M174,554 L280,554 M320,554 L426,554" stroke="{p}" stroke-width="6" fill="none"/>'
        return f"""
  <path d="{bottom}" fill="url(#satin)" stroke="{pip}" stroke-width="3"/>
  {hems.format(p=pip)}
  <path d="M300,410 L300,480" stroke="url(#shade)" stroke-width="4" opacity=".5"/>
  <path d="M250,110 L170,135 Q140,145 130,180 L100,320 L150,336 L185,222 L190,402 L410,402 L415,222 L450,336 L500,320 L470,180 Q460,145 430,135 L350,110 Q300,150 250,110 Z"
        fill="url(#satin)" stroke="{pip}" stroke-width="3"/>
  <path d="M100,320 L150,336 M450,336 L500,320" stroke="{pip}" stroke-width="7"/>
  <path d="M190,394 L410,394" stroke="{pip}" stroke-width="5"/>
  <path d="M250,110 L226,150 L268,162 L300,210 Z" fill="url(#satin2)" stroke="{pip}" stroke-width="4" stroke-linejoin="round"/>
  <path d="M350,110 L374,150 L332,162 L300,210 Z" fill="url(#satin2)" stroke="{pip}" stroke-width="4" stroke-linejoin="round"/>
  <path d="M300,210 L300,400" stroke="{pip}" stroke-width="2" opacity=".55"/>
  <g fill="{pip}"><circle cx="300" cy="245" r="6"/><circle cx="300" cy="295" r="6"/><circle cx="300" cy="345" r="6"/></g>
  <path d="M338,226 L384,226 L382,268 L340,268 Z" fill="none" stroke="{pip}" stroke-width="3"/>
  <path d="M338,226 L384,226" stroke="{pip}" stroke-width="6"/>
  <path d="M205,160 Q215,260 208,380" stroke="#fff" stroke-width="10" opacity=".22" fill="none" stroke-linecap="round"/>
  <path d="M232,420 Q238,560 224,680" stroke="#fff" stroke-width="9" opacity=".18" fill="none" stroke-linecap="round"/>
"""
    if kind == "robe":
        return f"""
  <path d="M255,95 L165,125 Q135,135 125,170 L78,388 L152,408 L190,252 L176,696 L424,696 L410,252 L448,408 L522,388 L475,170 Q465,135 435,125 L345,95 Q300,120 255,95 Z"
        fill="url(#satin)" stroke="{pip}" stroke-width="3"/>
  <path d="M78,388 L152,408 M448,408 L522,388" stroke="{pip}" stroke-width="9"/>
  <path d="M255,95 L325,400 L300,696" fill="none" stroke="url(#shade)" stroke-width="3" opacity=".5"/>
  <path d="M255,95 Q262,250 318,392 L338,392 Q282,250 282,100 Z" fill="{pip}" opacity=".95"/>
  <path d="M345,95 Q340,240 300,330 L286,316 Q318,230 318,100 Z" fill="{pip}" opacity=".85"/>
  <path d="M184,382 L416,382 L416,408 L184,408 Z" fill="url(#satin2)" stroke="{pip}" stroke-width="2"/>
  <path d="M322,404 Q312,470 296,540 L318,544 Q330,474 340,406 Z" fill="url(#satin2)" stroke="{pip}" stroke-width="2"/>
  <path d="M336,404 Q352,462 372,520 L392,512 Q368,456 350,404 Z" fill="url(#satin2)" stroke="{pip}" stroke-width="2"/>
  <ellipse cx="330" cy="395" rx="16" ry="14" fill="url(#satin2)" stroke="{pip}" stroke-width="2"/>
  <path d="M182,682 L418,682" stroke="{pip}" stroke-width="7"/>
  <path d="M212,170 Q224,420 206,660" stroke="#fff" stroke-width="12" opacity=".2" fill="none" stroke-linecap="round"/>
  <path d="M380,440 Q392,560 384,670" stroke="#fff" stroke-width="8" opacity=".15" fill="none" stroke-linecap="round"/>
"""
    # gown
    scallops = "".join(
        f'<circle cx="{x}" cy="702" r="10" fill="{pip}" opacity=".9"/>' for x in range(158, 446, 18)
    )
    return f"""
  <path d="M246,92 L252,172 M354,92 L348,172" stroke="{pip}" stroke-width="4" stroke-linecap="round"/>
  <path d="M238,170 Q270,150 300,196 Q330,150 362,170 L376,300 Q420,500 452,700 L148,700 Q180,500 224,300 Z"
        fill="url(#satin)" stroke="{pip}" stroke-width="3"/>
  <path d="M238,170 Q270,150 300,196 Q330,150 362,170 L366,214 Q332,196 300,236 Q268,196 234,214 Z" fill="{pip}" opacity=".55"/>
  <path d="M226,300 Q300,318 376,300" stroke="{pip}" stroke-width="5" fill="none"/>
  <g fill="{pip}"><path d="M300,306 L272,290 L274,322 Z"/><path d="M300,306 L328,290 L326,322 Z"/><circle cx="300" cy="306" r="7"/></g>
  {scallops}
  <path d="M248,330 Q226,500 196,680" stroke="#fff" stroke-width="12" opacity=".22" fill="none" stroke-linecap="round"/>
  <path d="M330,340 Q350,500 372,680" stroke="#fff" stroke-width="7" opacity=".15" fill="none" stroke-linecap="round"/>
"""


def svg(kind, base, pip):
    light = mix(base, "#ffffff", 0.45)
    dark = mix(base, "#000000", 0.28)
    bg1 = mix(base, "#ffffff", 0.82)
    bg2 = mix(base, "#ffffff", 0.6)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 750" width="600" height="750">
  <defs>
    <radialGradient id="bg" cx="50%" cy="38%" r="75%">
      <stop offset="0" stop-color="{bg1}"/><stop offset="1" stop-color="{bg2}"/>
    </radialGradient>
    <linearGradient id="satin" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="{light}"/><stop offset=".45" stop-color="{base}"/>
      <stop offset=".7" stop-color="{light}"/><stop offset="1" stop-color="{dark}"/>
    </linearGradient>
    <linearGradient id="satin2" x1="1" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="{light}"/><stop offset="1" stop-color="{base}"/>
    </linearGradient>
    <linearGradient id="shade" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="{dark}"/><stop offset="1" stop-color="{dark}" stop-opacity="0"/>
    </linearGradient>
  </defs>
  <rect width="600" height="750" fill="url(#bg)"/>
  <ellipse cx="300" cy="722" rx="200" ry="14" fill="#000" opacity=".08"/>
  <g fill="#d4af37" opacity=".55">
    <path d="M520,80 l5,14 14,5 -14,5 -5,14 -5,-14 -14,-5 14,-5z"/>
    <path d="M80,600 l4,10 10,4 -10,4 -4,10 -4,-10 -10,-4 10,-4z"/>
  </g>
{shapes(kind, pip)}
</svg>
"""


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for pid, kind, base, pip in ITEMS:
        (OUT / f"{pid}.svg").write_text(svg(kind, base, pip), encoding="utf-8")
    print(f"wrote {len(ITEMS)} images to {OUT}")


if __name__ == "__main__":
    main()
