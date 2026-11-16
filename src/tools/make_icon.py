"""生成程序图标：从设计稿 assets/icon-raw.png 做出 icon-1024.png 与多尺寸 app.ico。

两步：
  1. --prepare 处理设计稿：去掉右下角水印、把圆角外的白底裁成透明；
  2. 不带参数：由处理好的图生成 assets/app.ico（16~256，小尺寸单独锐化）。

设计稿缺失时回退到旧的内置矢量图标（蓝色圆角块 + N），保证任何环境都能打包。
"""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
RAW = ASSETS / "icon-raw.png"          # 模型出的设计稿（含白底与水印）
SOURCE = ASSETS / "icon-1024.png"      # 处理后的源图（透明圆角）
OUT = ASSETS / "app.ico"

SIZES = (16, 24, 32, 48, 64, 128, 256)
# 水印所在的矩形（由设计稿目测再留了余量）；上/左两条边取纯背景做插值基准
MARK_BOX = (886, 946, 994, 1022)
MARK_REF_TOP = 949
MARK_REF_LEFT = 889
WHITE_CUTOFF = 235                     # 亮度高于此为白底


def _luma(im: Image.Image) -> Image.Image:
    return im.convert("L")


def fit_radius(im: Image.Image) -> int:
    """用缩略图试出一圈圆角半径，使「圆角矩形」最贴合设计稿的非白区域。"""
    small = im.convert("RGB").resize((128, 128), Image.LANCZOS)
    solid = _luma(small).point(lambda v: 255 if v < WHITE_CUTOFF else 0)
    best_r, best_diff = 0, None
    for r in range(4, 46):
        mask = Image.new("L", (128, 128), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, 127, 127), radius=r, fill=255)
        # 只比较像素归类不一致的数量
        diff = 0
        sm, mm = solid.load(), mask.load()
        for y in range(0, 128, 2):
            for x in range(0, 128, 2):
                if (sm[x, y] > 127) != (mm[x, y] > 127):
                    diff += 1
        if best_diff is None or diff < best_diff:
            best_r, best_diff = r, diff
    return round(best_r * (im.width / 128))


def remove_watermark(im: Image.Image) -> Image.Image:
    """把右下角的水印用「上方一行 + 左侧一列」的背景渐变插值抹掉。"""
    px = im.load()
    x0, y0, x1, y1 = MARK_BOX
    base = [tuple(px[x, MARK_REF_TOP][i] for i in range(3)) for x in range(x0, x1)]
    top_left = [px[MARK_REF_LEFT, MARK_REF_TOP][i] for i in range(3)]
    col = []
    for y in range(y0, y1):
        cur = px[MARK_REF_LEFT, y]
        col.append([cur[i] - top_left[i] for i in range(3)])
    for xi, x in enumerate(range(x0, x1)):
        b = base[xi]
        for yi, y in enumerate(range(y0, y1)):
            d = col[yi]
            px[x, y] = (max(0, min(255, b[0] + d[0])),
                        max(0, min(255, b[1] + d[1])),
                        max(0, min(255, b[2] + d[2])), 255)
    # 插值区域轻微模糊，抹掉可能的竖条
    patch = im.crop((x0, y0, x1, y1)).filter(ImageFilter.GaussianBlur(3))
    im.paste(patch, (x0, y0))
    return im


def prepare() -> Path:
    if not RAW.exists():
        raise SystemExit(f"缺少设计稿：{RAW}")
    im = Image.open(RAW).convert("RGB")
    if im.width != im.height:
        side = min(im.size)
        im = im.crop(((im.width - side) // 2, (im.height - side) // 2,
                      (im.width + side) // 2, (im.height + side) // 2))

    radius = fit_radius(im)
    im = remove_watermark(im)

    # 4 倍超采样画圆角遮罩，缩回来就是抗锯齿的边缘；向内缩 2px 去掉边缘白点
    scale = 4
    inset = 2 * scale
    big = Image.new("L", (im.width * scale, im.height * scale), 0)
    ImageDraw.Draw(big).rounded_rectangle(
        (inset, inset, big.width - 1 - inset, big.height - 1 - inset),
        radius=radius * scale, fill=255)
    mask = big.resize(im.size, Image.LANCZOS)
    # 设计稿的圆角边上有一圈「深色→白」的抗锯齿过渡，单靠遮罩会留下白色描边；
    # 这里把接近白的像素也压成透明，两者相乘得到干净的边缘。
    luma = im.convert("L")
    whiteness = luma.point(
        lambda v: 255 if v <= 215 else (0 if v >= 250 else int((250 - v) / 35 * 255)))
    alpha = ImageChops.multiply(mask, whiteness).filter(ImageFilter.MinFilter(3))

    out = im.convert("RGBA")
    out.putalpha(alpha)
    out.save(SOURCE)
    print(f"圆角半径 {radius}px → {SOURCE.name} {out.size} "
          f"({SOURCE.stat().st_size / 1024:.0f} KB)")
    return SOURCE


def _legacy_png(size: int) -> bytes:
    """设计稿缺失时的兜底图标：蓝色圆角块 + 白 N。"""
    from PySide6.QtCore import QBuffer, QByteArray, QRect, Qt
    from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPixmap
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv[:1])
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    m = max(1, size // 32)
    p.setBrush(QColor("#3B6BF5"))
    p.drawRoundedRect(QRect(m, m, size - 2 * m, size - 2 * m),
                      size * 0.25, size * 0.25)
    p.setPen(QColor("#FFFFFF"))
    f = QFont(p.font())
    f.setPixelSize(int(size * 0.58))
    f.setBold(True)
    p.setFont(f)
    p.drawText(QRect(0, 0, size, size), Qt.AlignCenter, "N")
    p.end()
    img = pix.toImage().convertToFormat(QImage.Format_ARGB32)
    buf = QByteArray()
    qb = QBuffer(buf)
    qb.open(QBuffer.WriteOnly)
    img.save(qb, "PNG")
    qb.close()
    del app
    return bytes(buf)


def _sharp(im: Image.Image, amount: float) -> Image.Image:
    """小尺寸缩放后会发糊，补一点锐化（仅在无 alpha 溢出的范围内安全）。"""
    return im.filter(ImageFilter.UnsharpMask(radius=0.8, percent=int(amount), threshold=0))


def _mini_icon(size: int) -> Image.Image:
    """小尺寸（16~32px）专用：同一套「环 + 三柱」图形，去掉柔光并加粗线条。

    设计稿缩到 16px 时柔光会把环糊成一团，这里按 256 画布重画一遍再缩，
    托盘和任务栏上才能看清。
    """
    S = 256
    canvas = Image.new("RGBA", (S, S), (0, 0, 0, 0))

    # 圆角底 + 竖向深色渐变
    base = Image.new("RGBA", (S, S))
    bd = ImageDraw.Draw(base)
    for y in range(S):
        t = y / (S - 1)
        bd.line([(0, y), (S, y)],
                fill=(int(18 + 12 * t), int(26 + 17 * t), int(38 + 20 * t), 255))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle((2, 2, S - 3, S - 3), radius=62, fill=255)
    canvas.paste(base, (0, 0), mask)

    # 环形 + 三根柱子
    shape = Image.new("L", (S, S), 0)
    sd = ImageDraw.Draw(shape)
    cx, cy = S // 2, 124
    outer, ring = 75, 22
    sd.ellipse((cx - outer, cy - outer, cx + outer, cy + outer), outline=255, width=ring)
    bar_w, gap = 21, 7
    total = bar_w * 3 + gap * 2
    left, bottom = cx - total // 2, 174
    for i, h in enumerate((44, 66, 88)):
        x0 = left + i * (bar_w + gap)
        sd.rounded_rectangle((x0, bottom - h, x0 + bar_w, bottom),
                             radius=bar_w // 2, fill=255)

    # 青→蓝斜向渐变，只填在形状里
    grad = Image.new("RGBA", (S, S))
    gd = ImageDraw.Draw(grad)
    for i in range(S * 2):
        t = i / (2 * S)
        gd.line([(i, 0), (0, i)],
                fill=(int(34 + 25 * t), int(211 - 104 * t), int(197 + 48 * t), 255))
    canvas.paste(grad, (0, 0), shape)
    return canvas.resize((size, size), Image.LANCZOS)


def build_ico() -> int:
    if SOURCE.exists():
        src = Image.open(SOURCE).convert("RGBA")
        pngs = []
        for size in SIZES:
            if size <= 32:
                small = _mini_icon(size)
            else:
                small = src.resize((size, size), Image.LANCZOS)
                if size <= 48:
                    small = _sharp(small, 55)
            pngs.append((size, small))
    else:
        pngs = [(s, None) for s in SIZES]

    count = len(SIZES)
    header = struct.pack("<HHH", 0, 1, count)
    offset = len(header) + 16 * count
    entries, blobs = b"", b""
    for size, img in pngs:
        if img is None:
            data = _legacy_png(size)
        else:
            import io
            buf = io.BytesIO()
            img.save(buf, "PNG")
            data = buf.getvalue()
        w = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", w, w, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
        blobs += data
    OUT.write_bytes(header + entries + blobs)
    return len(header + entries + blobs)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="生成程序图标")
    ap.add_argument("--prepare", action="store_true", help="先处理设计稿（去水印、圆角透明）")
    args = ap.parse_args()
    if args.prepare:
        prepare()
    n = build_ico()
    print(f"wrote {OUT.name} ({n / 1024:.1f} KB, {len(SIZES)} sizes)")
