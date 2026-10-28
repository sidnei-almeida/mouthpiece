"""Builds the Mouthpiece brand kit from code: logos (SVG, text converted to outlines), app icons
(PNG at every size, Windows .ico, favicon) and a one-page brand sheet.

    python3 brand/build.py        (needs fonttools, rsvg-convert and ImageMagick's magick)

Everything lands in brand/: logo/, icon/, brand-sheet.png. Edit the constants here, not the outputs.
"""
import subprocess
from pathlib import Path

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

HERE = Path(__file__).parent
FONTS = HERE / 'fonts'

# Palette. Mostly neutral; Signal is the only color, used sparingly (the cursor, primary actions).
INK = '#111214'
PAPER = '#F5F3EE'
SIGNAL = '#FF4F2E'  # an "on air" light
GRAPHITE = '#2A2C31'
ASH = '#8A8D93'
LINE = '#E3E0D8'

# The mark, on a 1024 grid: a voice waveform that trails off into a text cursor ("your voice, typed").
BAR_W, GAP, CURSOR_W = 84, 56, 40
BARS = [260, 520, 380, 200]  # heights, left to right
CURSOR_H = 560
CENTER = 512


def mark_shapes(bar: str, cursor: str) -> tuple[str, tuple[float, float, float, float]]:
    """SVG rects for the mark and their bounding box on the 1024 grid."""
    total = len(BARS) * BAR_W + len(BARS) * GAP + CURSOR_W
    x = CENTER - total / 2
    out = []
    for h in BARS:
        out.append(f'<rect x="{x:g}" y="{CENTER - h / 2:g}" width="{BAR_W}" height="{h}" rx="{BAR_W / 2:g}" fill="{bar}"/>')
        x += BAR_W + GAP
    out.append(
        f'<rect x="{x:g}" y="{CENTER - CURSOR_H / 2:g}" width="{CURSOR_W}" height="{CURSOR_H}" rx="{CURSOR_W / 2:g}" fill="{cursor}"/>'
    )
    left = CENTER - total / 2
    return '\n  '.join(out), (left, CENTER - CURSOR_H / 2, total, CURSOR_H)


def static_font(name: str, weight: int) -> TTFont:
    font = TTFont(FONTS / name)
    if 'fvar' in font:
        axes = {a.axisTag: a.defaultValue for a in font['fvar'].axes}
        axes['wght'] = weight
        font = instantiateVariableFont(font, axes)
    return font


def text_path(text: str, font: TTFont, size: float, tracking: float = 0.0) -> tuple[str, float, dict]:
    """The text as one SVG path (outlines, so no font is needed to display it), its width, and metrics."""
    glyphs = font.getGlyphSet()
    cmap = font.getBestCmap()
    upm = font['head'].unitsPerEm
    scale = size / upm
    pen = SVGPathPen(glyphs)
    x = 0.0
    for i, ch in enumerate(text):
        name = cmap[ord(ch)]
        glyphs[name].draw(TransformPen(pen, (scale, 0, 0, -scale, x, 0)))
        x += glyphs[name].width * scale + (tracking * size if i < len(text) - 1 else 0)
    os2 = font['OS/2']
    metrics = {'xheight': os2.sxHeight * scale, 'cap': os2.sCapHeight * scale, 'desc': -font['hhea'].descent * scale}
    return pen.getCommands(), x, metrics


def svg(width: float, height: float, body: str, bg: str | None = None) -> str:
    fill = f'<rect width="100%" height="100%" fill="{bg}"/>\n  ' if bg else ''
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:g} {height:g}" '
            f'width="{width:g}" height="{height:g}">\n  {fill}{body}\n</svg>\n')


def png(src: Path, out: Path, width: int):
    subprocess.run(['rsvg-convert', '-w', str(width), '-o', str(out), str(src)], check=True)


def build():
    logo, icon = HERE / 'logo', HERE / 'icon'
    logo.mkdir(exist_ok=True)
    icon.mkdir(exist_ok=True)
    font = static_font('SpaceGrotesk-VF.ttf', 500)

    # Mark alone, tight box, padded by a bar width.
    for suffix, bar in (('', INK), ('-light', PAPER)):
        shapes, (x, y, w, h) = mark_shapes(bar, SIGNAL)
        pad = BAR_W
        body = f'<g transform="translate({pad - x:g} {pad - y:g})">\n  {shapes}\n  </g>'
        (logo / f'mark{suffix}.svg').write_text(svg(w + 2 * pad, h + 2 * pad, body))
    shapes, (x, y, w, h) = mark_shapes(INK, INK)
    (logo / 'mark-mono.svg').write_text(svg(w + 2 * BAR_W, h + 2 * BAR_W, f'<g transform="translate({BAR_W - x:g} {BAR_W - y:g})">\n  {shapes}\n  </g>'))

    # Wordmark: lowercase, Space Grotesk Medium, tightened a touch.
    size = 200
    d, tw, m = text_path('mouthpiece', font, size, tracking=-0.025)
    asc = m['cap'] * 1.08  # room for the ascenders of h and t
    pad = 24
    wm_h = asc + m['desc'] + 2 * pad
    for suffix, color in (('', INK), ('-light', PAPER)):
        body = f'<path transform="translate({pad} {pad + asc:g})" d="{d}" fill="{color}"/>'
        (logo / f'wordmark{suffix}.svg').write_text(svg(tw + 2 * pad, wm_h, body))

    # Horizontal lockup: the mark as tall as the wordmark's cap height x 1.5, centred on the x-height.
    mark_h = m['cap'] * 1.5
    s = mark_h / CURSOR_H
    shapes, (mx, my, mw, mh) = mark_shapes('BAR', SIGNAL)
    gap = mark_h * 0.42
    baseline = pad + mark_h / 2 + m['xheight'] / 2
    lock_w = pad + mw * s + gap + tw + pad
    lock_h = max(pad * 2 + mark_h, baseline + m['desc'] + pad)
    for suffix, color in (('', INK), ('-light', PAPER)):
        body = (f'<g transform="translate({pad - mx * s:g} {pad - my * s:g}) scale({s:g})">\n  '
                f'{shapes.replace("BAR", color)}\n  </g>\n  '
                f'<path transform="translate({pad + mw * s + gap:g} {baseline:g})" d="{d}" fill="{color}"/>')
        (logo / f'lockup{suffix}.svg').write_text(svg(lock_w, lock_h, body))

    # App icon: the mark in Paper on an Ink squircle-ish tile.
    shapes, _ = mark_shapes(PAPER, SIGNAL)
    tile = f'<rect width="1024" height="1024" rx="232" fill="{INK}"/>\n  {shapes}'
    (icon / 'icon.svg').write_text(svg(1024, 1024, tile))
    (icon / 'favicon.svg').write_text(svg(1024, 1024, tile))
    for px in (48, 64, 128, 256, 512, 1024):
        png(icon / 'icon.svg', icon / f'icon-{px}.png', px)
    # 16-32 px: scaling the big mark down blurs the bars into grey. These are drawn on the pixel grid
    # instead (whole-pixel bars and gaps; three bars at 16 px), rendered at their native size.
    for grid, bars, bar_w, gap, cur_w, cur_h, rx in ((16, [4, 8, 6], 2, 1, 1, 10, 3),
                                                     (32, [8, 16, 12, 6], 3, 2, 2, 20, 7)):
        x = (grid - (len(bars) * bar_w + len(bars) * gap + cur_w)) // 2
        rects = []
        for h in bars:
            rects.append(f'<rect x="{x}" y="{(grid - h) // 2}" width="{bar_w}" height="{h}" fill="{PAPER}"/>')
            x += bar_w + gap
        rects.append(f'<rect x="{x}" y="{(grid - cur_h) // 2}" width="{cur_w}" height="{cur_h}" fill="{SIGNAL}"/>')
        small = (f'<rect width="{grid}" height="{grid}" rx="{rx}" fill="{INK}"/>\n  <g shape-rendering="crispEdges">'
                 + ''.join(rects) + '</g>')
        (icon / f'icon-{grid}.svg').write_text(svg(grid, grid, small))
        png(icon / f'icon-{grid}.svg', icon / f'icon-{grid}.png', grid)
    png(icon / 'icon-32.svg', icon / 'icon-24.png', 24)
    subprocess.run(['magick', *[str(icon / f'icon-{px}.png') for px in (16, 24, 32, 48, 64, 128, 256)],
                    str(icon / 'mouthpiece.ico')], check=True)

    sheet(logo, icon, font)


def sheet(logo: Path, icon: Path, font: TTFont):
    """One-page overview of the kit, for a quick look or to share."""
    W, H = 1600, 1000
    lock = (logo / 'lockup.svg').read_text()
    lock_light = (logo / 'lockup-light.svg').read_text()

    def embed(src: str, x: float, y: float, w: float) -> str:
        vb = src.split('viewBox="')[1].split('"')[0].split()
        sw, sh = float(vb[2]), float(vb[3])
        inner = src.split('>', 1)[1].rsplit('</svg>', 1)[0]
        return f'<svg x="{x}" y="{y}" width="{w}" height="{w * sh / sw:g}" viewBox="0 0 {sw:g} {sh:g}">{inner}</svg>'

    def label(text: str, x: float, y: float, color=ASH, size=18, weight=400):
        d, _, _ = text_path(text, static_font('Inter-VF.ttf', weight), size)
        return f'<path transform="translate({x} {y})" d="{d}" fill="{color}"/>'

    icon_svg = (icon / 'icon.svg').read_text()
    swatches = [('Ink', INK, PAPER), ('Paper', PAPER, INK), ('Signal', SIGNAL, PAPER), ('Graphite', GRAPHITE, PAPER),
                ('Ash', ASH, PAPER), ('Line', LINE, INK)]
    parts = [f'<rect width="{W}" height="{H}" fill="{PAPER}"/>',
             f'<rect x="{W / 2}" y="0" width="{W / 2}" height="560" fill="{INK}"/>',
             embed(lock, 80, 210, 640), embed(lock_light, W / 2 + 80, 210, 640),
             label('MOUTHPIECE  BRAND KIT', 80, 80, INK, 20, 600),
             label('your voice, typed.', 80, 120, ASH, 20),
             label('Primary lockup', 80, 500), label('On dark', W / 2 + 80, 500, ASH)]
    for i, px in enumerate((256, 128, 64, 32)):
        x = 80 + sum((256, 128, 64, 32)[:i]) + i * 48
        parts.append(embed(icon_svg, x, 620, px))
        parts.append(label(f'{px}', x, 920))
    for i, (name, hexv, fg) in enumerate(swatches):
        x, y = 820 + (i % 3) * 240, 620 + (i // 3) * 170
        parts.append(f'<rect x="{x}" y="{y}" width="220" height="140" rx="14" fill="{hexv}" stroke="{LINE}"/>')
        parts.append(label(name, x + 18, y + 40, fg, 20, 600))
        parts.append(label(hexv, x + 18, y + 120, fg, 16))
    out = HERE / 'brand-sheet.svg'
    out.write_text(svg(W, H, '\n  '.join(parts)))
    png(out, HERE / 'brand-sheet.png', W)
    out.unlink()


def diagram():
    """docs/como-funciona(-dark).svg: how a line of text becomes a WAV, in the brand's style. Drawn
    here instead of Mermaid so it renders the same everywhere; the README picks the version that
    matches the reader's theme."""
    inter = static_font('Inter-VF.ttf', 600)
    inter_r = static_font('Inter-VF.ttf', 400)
    W, H = 1200, 330
    boxes = [  # x, y, w, h, title, subtitle, accent
        (20, 40, 230, 96, 'Navegador', 'o app em 127.0.0.1', False),
        (20, 194, 230, 96, 'Terminal', 'mouthpiece say, Claude Code', False),
        (330, 40, 230, 250, 'Servidor local', 'só aceita este computador', False),
        (640, 40, 230, 120, 'Qwen3-TTS', 'na placa de vídeo', False),
        (640, 210, 230, 80, 'Sua voz', 'até 30 s de referência', False),
        (950, 40, 230, 120, 'Acabamento', '-16 LUFS · 48 kHz · 24 bits', False),
        (950, 210, 230, 80, 'WAV pronto', 'para a edição', True),
    ]
    arrows = [  # x1, y1, x2, y2
        (250, 88, 330, 88), (250, 242, 330, 242), (560, 100, 640, 100), (755, 210, 755, 160),
        (870, 100, 950, 100), (1065, 160, 1065, 210),
    ]
    # Small labels on the server box: what it does with the text.
    notes = ['divide em frases', 'aplica a pronúncia', 'uma geração por vez', 'vigia a placa']
    for suffix, fg, sub, box, stroke, arrow in (('', INK, ASH, '#FFFFFF', LINE, ASH),
                                               ('-dark', PAPER, ASH, '#1A1C20', GRAPHITE, ASH)):
        parts = ['<defs><marker id="a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
                 f'orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="{arrow}"/></marker></defs>']
        for x1, y1, x2, y2 in arrows:
            parts.append(f'<line x1="{x1}" y1="{y1}" x2="{x2 - 2 if x2 > x1 else x2}" y2="{y2 + 2 if y2 < y1 else y2}" '
                         f'stroke="{arrow}" stroke-width="2" marker-end="url(#a)"/>')
        for x, y, w, h, title, subtitle, accent in boxes:
            parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14" fill="{box}" '
                         f'stroke="{SIGNAL if accent else stroke}" stroke-width="{2 if accent else 1.5}"/>')
            d, _, _ = text_path(title, inter, 22)
            parts.append(f'<path transform="translate({x + 22} {y + 42})" d="{d}" fill="{fg}"/>')
            d, _, _ = text_path(subtitle, inter_r, 15)
            parts.append(f'<path transform="translate({x + 22} {y + 68})" d="{d}" fill="{sub}"/>')
        for i, note in enumerate(notes):
            d, _, _ = text_path(note, inter_r, 15)
            parts.append(f'<circle cx="{358}" cy="{148 + i * 34 - 5}" r="3" fill="{SIGNAL}"/>')
            parts.append(f'<path transform="translate(370 {148 + i * 34})" d="{d}" fill="{fg}"/>')
        (HERE.parent / 'docs' / f'como-funciona{suffix}.svg').write_text(svg(W, H, '\n  '.join(parts)))


if __name__ == '__main__':
    build()
    diagram()
    print('brand kit built in', HERE)
