#!/usr/bin/env python3
"""EP thumbnails: sizes reverse-engineered from EP5/EP1/EP6 pixels.
Display: Anton. Header small: Barlow Condensed SemiBold. Tagline: Space Mono.
Pillow + local TTFs only. A venv é automática (sem activate).

Usage 1 — interativo (pergunta ep, título, subtítulo e foto-base na mão):
    $ . ~/.venv/bin/activat && python3 thumb_generator.py
    Número do episódio: 8
    Título linha 1 (ex: QUANTO CUSTA MONTAR): QUANTO CUSTA MONTAR
    Título linha 2 (enter p/ pular): UMA ACADEMIA EM CASA?
    Tagline [natural · sem pressa]:
    Foto base (arraste o jpg/png aqui): /home/eu/fotos/ep8.jpeg

Usage 2 — linha de comando, sem subtítulo (usa o default "natural · sem pressa"):
    $ . ~/.venv/bin/activat && python3 thumb_generator.py --episode-number 8 --title "QUANTO CUSTA MONTAR | UMA ACADEMIA EM CASA?"

Usage 3 — linha de comando, com subtítulo:
    $ . ~/.venv/bin/activat && python3 thumb_generator.py --episode-number 8 --title "QUANTO CUSTA MONTAR | UMA ACADEMIA EM CASA?" --subtitle "treino · sem pressa"

Usage 4 — foto em qualquer lugar (output cai ao lado dela, sem copiar):
    $ . ~/.venv/bin/activate && python3 thumb_generator.py --base-dir ~/Videos/projeto --episode-number 7 --title "QUANTO CUSTA | MONTAR UMA ACADEMIA?" --base-image /home/fabio.venturelli/consultoria/ep7/base.jpeg
    # gera /home/fabio.venturelli/consultoria/ep7/ep7-tiktok-1080x1350.png e ep7-reels-1080x1920.png
"""
import os
import sys
import subprocess

if os.environ.get("THUMBS_BOOT") != "1":
    try:
        import PIL  # noqa: F401
    except ImportError:
        here = os.path.dirname(os.path.abspath(__file__))
        venv = os.path.join(here, ".venv")
        vpy = os.path.join(venv, "bin", "python")
        if not os.path.exists(vpy):
            print("criando venv local + instalando pillow...")
            subprocess.check_call([sys.executable, "-m", "venv", venv])
            subprocess.check_call([vpy, "-m", "pip", "install", "--upgrade", "pip"])
            subprocess.check_call([vpy, "-m", "pip", "install", "pillow"])
        os.environ["THUMBS_BOOT"] = "1"
        os.execv(vpy, [vpy, os.path.abspath(__file__)] + sys.argv[1:])

from PIL import Image, ImageDraw, ImageFont

import argparse

ap = argparse.ArgumentParser(description="Gera thumbs do episódio.")
ap.add_argument("--episode-number", default=None, help="número do episódio (ex: 8)")
ap.add_argument("subtitulo", nargs="?", default=None, help="subtítulo/tagline do rodapé (padrão: natural · sem pressa)")
ap.add_argument("--title", default=None, help='título em até 2 linhas, ex: --title "QUANTO CUSTA MONTAR | UMA ACADEMIA EM CASA?"')
ap.add_argument("--subtitle", default=None, help="subtítulo/tagline do rodapé (padrão: natural · sem pressa)")
ap.add_argument("--base-dir", default=None, help="pasta do projeto (onde ficam epN/ e fonts/). Padrão: pasta do script")
ap.add_argument("--base-image", default=None, help="foto base (jpg/png/webp). O output cai na mesma pasta dela. Se omitido, usa a de thumbs/epN/ ou pergunta")
args = ap.parse_args()

def perguntar(prompt, padrao=None):
    if not sys.stdin.isatty():
        if padrao is not None:
            return padrao
        raise SystemExit(f"sem terminal interativo; passe o valor por argumento ({prompt.strip()})")
    try:
        v = input(prompt).strip()
    except EOFError:
        v = ""
    return v or (padrao or "")

EP = (args.episode_number or perguntar("Número do episódio: ")).strip()
if not EP:
    raise SystemExit("episódio vazio, abortando.")

if args.title:
    TOP_SMALL = [l.strip().upper() for l in args.title.split("|") if l.strip()][:2]
else:
    l1 = perguntar("Título linha 1 (ex: QUANTO CUSTA MONTAR): ").upper()
    l2 = perguntar("Título linha 2 (enter p/ pular): ").upper()
    TOP_SMALL = [l1] + ([l2] if l2 else [])
if not TOP_SMALL or not TOP_SMALL[0]:
    raise SystemExit("título vazio, abortando.")

TAGLINE = args.subtitle or args.subtitulo or perguntar(
    "Tagline [natural · sem pressa]: ", padrao="natural \u00b7 sem pressa"
)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.abspath(os.path.expanduser(args.base_dir)) if args.base_dir else SCRIPT_DIR
EP_DIR = f"{BASE_DIR}/thumbs/ep{EP}"  # usado só p/ procurar foto do projeto

EXTS = (".jpeg", ".jpg", ".png", ".webp")
BASE = None  # foto-base (manda no output: ele cai ao lado dela, sem copiar nada)
if args.base_image:
    p = os.path.abspath(os.path.expanduser(args.base_image))
    if not os.path.isfile(p) or not p.lower().endswith(EXTS):
        raise SystemExit(f"base-image inválida: {args.base_image} (use jpg/png/webp)")
    BASE = p
if BASE is None and os.path.isdir(EP_DIR):
    for cand in ("base.jpeg", "base.jpg", "base.png", "base.webp"):
        if os.path.isfile(f"{EP_DIR}/{cand}"):
            BASE = f"{EP_DIR}/{cand}"
            break
    if BASE is None:
        cands = sorted(f for f in os.listdir(EP_DIR) if f.lower().endswith(EXTS))
        if cands:
            BASE = f"{EP_DIR}/{cands[0]}"
            print("usando base:", BASE)
while BASE is None:
    p = os.path.abspath(os.path.expanduser(
        perguntar("Foto base (caminho do jpg/png): ").strip().strip("'\"")))
    if os.path.isfile(p) and p.lower().endswith(EXTS):
        BASE = p
    else:
        print("arquivo não encontrado, tente de novo.")
OUT_DIR = os.path.dirname(BASE)
OUT_REELS = f"{OUT_DIR}/ep{EP}-reels-1080x1920.png"
OUT_TT = f"{OUT_DIR}/ep{EP}-tiktok-1080x1350.png"

BG = (10, 10, 10)          
LIME = (232, 255, 89)      
WHITE = (242, 242, 238)    
GREY = (201, 201, 194)     

def font_path(name):
    p = f"{BASE_DIR}/fonts/{name}"
    if os.path.isfile(p):
        return p
    return f"{SCRIPT_DIR}/fonts/{name}"

DISPLAY = font_path("Anton.ttf")
HEAD_SMALL = font_path("JetBrainsMono.ttf")
MONO = font_path("SpaceMono.ttf")
for f in (DISPLAY, HEAD_SMALL, MONO):
    if not os.path.isfile(f):
        raise SystemExit(f"fonte não encontrada: {f}")

EPISODE_NUMBER = f"EP.{EP}"
EP_SHIFT = 12  


def draw_tracked(draw, xy, text, font, fill, tracking=0):
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=font, fill=fill)
        x += draw.textlength(ch, font=font) + tracking
    return x - tracking - xy[0]


def cover(img, w, h, focal=0.5):
    sw, sh = img.size
    scale = max(w / sw, h / sh)
    img = img.resize((int(sw * scale + 0.5), int(sh * scale + 0.5)), Image.LANCZOS)
    nw, nh = img.size
    x = (nw - w) // 2
    y = max(0, min(nh - h, int((nh - h) * focal)))
    return img.crop((x, y, x + w, y + h))


def gradient_band(w, h, top=True):
    m = Image.new("L", (1, h))
    px = m.load()
    for y in range(h):
        t = y / max(1, h - 1)
        px[0, y] = int(255 * (1 - t)) if top else int(255 * t)
    return Image.new("RGB", (w, h), BG), m.resize((w, h))


def cap_draw_tracked(draw, x, text, font, fill, cap_top, tracking=0):
    """Tracked draw anchored so caps start exactly at cap_top. Returns ink height."""
    bb = draw.textbbox((0, 0), text, font=font)
    y = cap_top - bb[1]
    cx = x
    for ch in text:
        draw.text((cx, y), ch, font=font, fill=fill)
        cx += draw.textlength(ch, font=font) + tracking
    return bb[3] - bb[1]


def build(W, H, hdr_h, ftr_h, focal, head_px, ep_px, small_px, tag_px, ep_cap_top):
    photo_h = H - hdr_h - ftr_h
    photo = cover(Image.open(BASE).convert("RGB"), W, photo_h, focal)
    fade = 130
    tb, tm = gradient_band(W, fade, top=True)
    photo.paste(tb, (0, 0), tm)
    bb, bm = gradient_band(W, fade, top=False)
    photo.paste(bb, (0, photo_h - fade), bm)

    canvas = Image.new("RGB", (W, H), BG)
    canvas.paste(photo, (0, hdr_h))
    d = ImageDraw.Draw(canvas)
    pad = 60

    # --- header: EP.7 (Anton ep_px) + 2 small lines (JB Mono, ls 0.08em, lh 1.15) ---
    epf = ImageFont.truetype(DISPLAY, ep_px)
    ep_h = cap_draw_tracked(d, pad, EPISODE_NUMBER, epf, LIME, ep_cap_top + EP_SHIFT)
    ep_w = d.textlength(EPISODE_NUMBER, font=epf)
    mf = ImageFont.truetype(HEAD_SMALL, small_px)
    tx = pad + ep_w + 18
    # flex row, align-items:center: bloco de 2 linhas centralizado na faixa do EP
    lh = round(small_px * 1.15)
    ty = ep_cap_top + (ep_h - 2 * lh) // 2 + round(small_px * 0.3)
    for line in TOP_SMALL:
        draw_tracked(d, (tx, ty), line, mf, WHITE, tracking=round(small_px * 0.08, 1))
        ty += lh

    # --- footer: CRESCER / SECO (Anton head_px, ls -0.01em, rhythm 160) ---
    fx = pad
    l1_top = H - ftr_h + 20
    ls_head = round(head_px * -0.01, 1)
    real1 = cap_draw_tracked(d, fx, "CRESCER", ImageFont.truetype(DISPLAY, head_px), WHITE, l1_top, ls_head)
    l2_top = l1_top + 160
    f2 = ImageFont.truetype(DISPLAY, head_px)
    real2 = cap_draw_tracked(d, fx, "SECO", f2, LIME, l2_top, ls_head)
    seco_w = d.textlength("SECO", font=f2) + ls_head * 3
    tf = ImageFont.truetype(HEAD_SMALL, tag_px)
    # tagline vertically centered on the SECO cap band
    tag_bb = d.textbbox((0, 0), TAGLINE, font=tf)
    tag_h = tag_bb[3] - tag_bb[1]
    tag_y = l2_top + (real2 - tag_h) // 2 - tag_bb[1]
    draw_tracked(d, (fx + seco_w + 32, tag_y), TAGLINE, tf, GREY, tracking=round(tag_px * 0.06, 1))
    return canvas


# TT: spec EP5 — EP Anton 104, small JB Mono 40/lh1.15/ls.08, headline 172px-eq, tag 40/ls.06
tt = build(1080, 1350, hdr_h=160, ftr_h=370, focal=0.62,
           head_px=172, ep_px=104, small_px=40, tag_px=40, ep_cap_top=15)
tt.save(OUT_TT)
print("saved", OUT_TT, tt.size)

# Reels (ep1 model): same sizes (absolute, per refs), EP bottom-anchored
reels = build(1080, 1920, hdr_h=480, ftr_h=620, focal=0.65,
              head_px=161, ep_px=104, small_px=52, tag_px=40, ep_cap_top=289)
reels.save(OUT_REELS)
print("saved", OUT_REELS, reels.size)

