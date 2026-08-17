from __future__ import annotations
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OCR_DEPS = ROOT / 'work' / 'ocr_deps'
RUNTIME = Path(os.environ.get('PLATFORM_RUNTIME', ROOT / 'runtime' / 'dependencies'))
PYTHON = Path(os.environ.get('PYTHON_BIN', RUNTIME / 'python' / 'bin' / 'python3'))
TMP = ROOT / 'tmp' / 'local_ocr'
FONT_CACHE = ROOT / 'tmp' / 'fontconfig'


def find_poppler_bin() -> Path:
    configured = Path(os.environ.get('POPPLER_BIN', RUNTIME / 'bin'))
    runtime_cache = Path.home() / '.cache' / 'codex-runtimes' / 'codex-primary-runtime' / 'dependencies'
    candidates = [
        configured,
        configured / 'override',
        RUNTIME / 'bin' / 'override',
        RUNTIME / 'native' / 'poppler' / 'bin',
        RUNTIME / 'native' / 'poppler' / 'poppler' / 'bin',
        runtime_cache / 'bin' / 'override',
        runtime_cache / 'native' / 'poppler' / 'bin',
        runtime_cache / 'native' / 'poppler' / 'poppler' / 'bin',
        Path('/opt/homebrew/bin'),
        Path('/usr/local/bin'),
        Path('/usr/bin'),
    ]
    for candidate in candidates:
        if (candidate / 'pdftoppm').exists() and (candidate / 'pdfinfo').exists():
            return candidate
    return configured


POPPLER = find_poppler_bin()

sys.path.insert(0, str(OCR_DEPS))
from PIL import Image, ImageOps, ImageEnhance, ImageChops, ImageFilter
from rapidocr_onnxruntime import RapidOCR
import cv2
import numpy as np


def run(cmd: list[str]) -> None:
    FONT_CACHE.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env['XDG_CACHE_HOME'] = str(ROOT / 'tmp')
    env['FONTCONFIG_PATH'] = str(FONT_CACHE)
    subprocess.run(cmd, check=True, env=env)


def pdf_password_args(password: str | None) -> list[str]:
    return ['-opw', password, '-upw', password] if password else []


def pdf_page_count(pdf_path: Path, password: str | None = None) -> int:
    try:
        result = subprocess.run(
            [str(POPPLER / 'pdfinfo'), *pdf_password_args(password), str(pdf_path)],
            check=True,
            capture_output=True,
            text=True,
            env=os.environ.copy(),
        )
    except Exception:
        return 0
    match = re.search(r'^Pages:\s*(\d+)', result.stdout, re.MULTILINE)
    return int(match.group(1)) if match else 0


def render_pdf(pdf_path: Path, out_dir: Path, progress_cb=None, password: str | None = None) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    page_count = pdf_page_count(pdf_path, password=password)
    if page_count:
        paths = []
        for page_no in range(1, page_count + 1):
            if progress_cb:
                progress_cb(page_no - 1, page_count, f'渲染 PDF 第 {page_no}/{page_count} 页')
            prefix = out_dir / f'page-{page_no:03d}'
            run([
                str(POPPLER / 'pdftoppm'),
                '-png',
                '-r',
                '260',
                '-f',
                str(page_no),
                '-l',
                str(page_no),
                '-singlefile',
                *pdf_password_args(password),
                str(pdf_path),
                str(prefix),
            ])
            out = prefix.with_suffix('.png')
            if out.exists():
                paths.append(out)
            if progress_cb:
                progress_cb(page_no, page_count, f'已渲染 PDF {page_no}/{page_count} 页')
        return paths

    prefix = out_dir / 'page'
    run([str(POPPLER / 'pdftoppm'), '-png', '-r', '260', *pdf_password_args(password), str(pdf_path), str(prefix)])
    return sorted(out_dir.glob('page-*.png'))


def crop_photo_border(im: Image.Image) -> Image.Image:
    """Remove the white canvas commonly added around phone photos in office PDFs."""
    preview_width = min(900, im.width)
    preview_height = max(1, round(im.height * preview_width / im.width))
    preview = ImageOps.grayscale(im.resize((preview_width, preview_height), Image.Resampling.BILINEAR))
    foreground = preview.point(lambda p: 255 if p < 247 else 0)
    bbox = foreground.getbbox()
    if not bbox:
        return im
    left, top, right, bottom = bbox
    # A text-only white page can also produce a bounding box. Only trim when a
    # meaningful outer canvas exists and keep a little breathing room.
    margins = (left, top, preview_width - right, preview_height - bottom)
    if max(margins) < min(preview_width, preview_height) * 0.025:
        return im
    if (right - left) * (bottom - top) < preview_width * preview_height * 0.28:
        return im
    pad = max(4, round(min(preview_width, preview_height) * 0.008))
    left = max(0, left - pad)
    top = max(0, top - pad)
    right = min(preview_width, right + pad)
    bottom = min(preview_height, bottom + pad)
    sx = im.width / preview_width
    sy = im.height / preview_height
    return im.crop((round(left * sx), round(top * sy), round(right * sx), round(bottom * sy)))


def photo_spread_split_x(im: Image.Image) -> int:
    """Find the page join near the middle of a photographed two-page spread."""
    preview_width = min(900, im.width)
    preview_height = max(1, round(im.height * preview_width / im.width))
    gray = ImageOps.grayscale(im.resize((preview_width, preview_height), Image.Resampling.BILINEAR))
    center = preview_width / 2
    start = round(preview_width * 0.44)
    end = round(preview_width * 0.56)
    top = round(preview_height * 0.04)
    bottom = round(preview_height * 0.96)
    best_x = round(center)
    best_score = float('-inf')
    for x in range(max(1, start), min(preview_width - 1, end)):
        edge = sum(abs(gray.getpixel((x, y)) - gray.getpixel((x - 1, y))) for y in range(top, bottom))
        edge /= max(1, bottom - top)
        score = edge - abs(x - center) * 0.15
        if score > best_score:
            best_score = score
            best_x = x
    return max(1, min(im.width - 1, round(best_x * im.width / preview_width)))


def save_photo_ocr_image(crop: Image.Image, out: Path) -> None:
    """Create one shadow-normalized OCR image for a photographed report page."""
    longest = max(crop.size)
    target = 2100
    if longest < target:
        scale = target / longest
        crop = crop.resize((round(crop.width * scale), round(crop.height * scale)), Image.Resampling.LANCZOS)
    rgb = np.asarray(crop)
    # Credit reports contain pale red/blue watermarks. The lightest channel
    # suppresses those marks while retaining black text.
    gray = np.max(rgb, axis=2).astype(np.uint8)
    # Divide by a blurred background to remove desk shadows and the brightness
    # gradient caused by photographing a sheet at an angle.
    small = cv2.resize(gray, None, fx=0.25, fy=0.25, interpolation=cv2.INTER_AREA)
    small_background = cv2.GaussianBlur(small, (0, 0), sigmaX=8, sigmaY=8)
    background = cv2.resize(small_background, (gray.shape[1], gray.shape[0]), interpolation=cv2.INTER_LINEAR)
    normalized = cv2.divide(gray, np.maximum(background, 1), scale=245)
    normalized = cv2.createCLAHE(clipLimit=1.45, tileGridSize=(8, 8)).apply(normalized)
    blurred = cv2.GaussianBlur(normalized, (0, 0), sigmaX=1.0)
    sharpened = cv2.addWeighted(normalized, 1.35, blurred, -0.35, 0)
    Image.fromarray(sharpened).save(out)


def prepare_and_split(image_path: Path, out_dir: Path, page_no: int, include_wide_splits: bool = True) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    im = Image.open(image_path).convert('RGB')
    w, h = im.size
    if include_wide_splits and w > h * 1.2:
        spread = crop_photo_border(im)
        sw, sh = spread.size
        if sw > sh * 1.2:
            split_x = photo_spread_split_x(spread)
            overlap = max(8, round(sw * 0.006))
            crops = [
                spread.crop((0, 0, min(sw, split_x + overlap), sh)),
                spread.crop((max(0, split_x - overlap), 0, sw, sh)),
            ]
            paths = []
            for idx, crop in enumerate(crops, start=1):
                out = out_dir / f'p{page_no:03d}_photo_{idx:02d}.png'
                save_photo_ocr_image(crop, out)
                paths.append(out)
            return paths

    boxes = [(0, 0, w, h)]
    if h > w * 1.35:
        small_w = 220
        small_h = max(1, int(h * small_w / w))
        small = ImageOps.grayscale(im.resize((small_w, small_h), Image.Resampling.BILINEAR))
        bright_rows = []
        pix = small.load()
        for y in range(int(small_h * 0.08), small_h):
            bright = sum(1 for x in range(small_w) if pix[x, y] >= 232)
            bright_rows.append((y, bright / small_w))
        crop_top = None
        run = 0
        for y, ratio in bright_rows:
            run = run + 1 if ratio >= 0.58 else 0
            if run >= 5:
                crop_top = max(0, y - 4)
                break
        if crop_top is not None and crop_top > small_h * 0.12:
            crop_y = max(0, int(crop_top * h / small_h) - 18)
            if h - crop_y > h * 0.45:
                boxes.append((0, crop_y, w, h))
    paths = []
    for idx, box in enumerate(boxes, start=1):
        crop = im.crop(box)
        out = out_dir / f'p{page_no:02d}_{idx}.png'
        save_photo_ocr_image(crop, out)
        paths.append(out)
    return paths


def box_center(box) -> tuple[float, float]:
    xs = [float(pt[0]) for pt in box]
    ys = [float(pt[1]) for pt in box]
    return sum(xs) / len(xs), sum(ys) / len(ys)


def box_height(box) -> float:
    ys = [float(pt[1]) for pt in box]
    return max(ys) - min(ys)


def rebuild_table_rows(lines: list[dict]) -> list[str]:
    items = [line for line in lines if line.get('box') and line.get('text')]
    if not items:
        return []
    heights = sorted(max(8.0, box_height(line['box'])) for line in items)
    median_height = heights[len(heights) // 2]
    tolerance = max(10.0, median_height * 0.75)
    rows: list[dict] = []
    for line in sorted(items, key=lambda item: (box_center(item['box'])[1], box_center(item['box'])[0])):
        x, y = box_center(line['box'])
        chosen = None
        for row in rows:
            if abs(row['y'] - y) <= tolerance:
                chosen = row
                break
        if chosen is None:
            chosen = {'y': y, 'cells': []}
            rows.append(chosen)
        chosen['cells'].append((x, line['text']))
        chosen['y'] = (chosen['y'] * (len(chosen['cells']) - 1) + y) / len(chosen['cells'])
    rebuilt = []
    for row in sorted(rows, key=lambda item: item['y']):
        cells = [text for _x, text in sorted(row['cells'], key=lambda item: item[0])]
        if len(cells) >= 2:
            rebuilt.append(' '.join(cells))
    return rebuilt


def ocr_images(images: list[Path], progress_cb=None) -> list[dict]:
    ocr = RapidOCR()
    pages = []
    total = len(images) or 1
    for i, img in enumerate(images, start=1):
        result, elapsed = ocr(str(img))
        lines = []
        for item in result or []:
            box, text, score = item
            if text and score >= 0.40:
                lines.append({'text': text, 'score': float(score), 'box': box})
        row_text = rebuild_table_rows(lines)
        raw_text = '\n'.join(line['text'] for line in lines)
        combined_text = '\n'.join([*row_text, raw_text]) if row_text else raw_text
        pages.append({'page': i, 'image': str(img), 'lines': lines, 'rows': row_text, 'text': combined_text})
        if progress_cb:
            progress_cb(i, total, img)
    return pages


def main() -> None:
    if len(sys.argv) < 3:
        raise SystemExit('usage: ocr_credit_pdf.py input.pdf output_prefix')
    pdf_path = Path(sys.argv[1])
    output_prefix = Path(sys.argv[2])
    work = TMP / pdf_path.stem
    if work.exists():
        shutil.rmtree(work)
    rendered = render_pdf(pdf_path, work / 'rendered')
    split_images = []
    for page_no, image in enumerate(rendered, start=1):
        split_images.extend(prepare_and_split(image, work / 'split', page_no))
    pages = ocr_images(split_images)
    text = '\n\n'.join(f'【第 {page["page"]} 页】\n{page["text"]}' for page in pages)
    output_prefix.parent.mkdir(parents=True, exist_ok=True)
    output_prefix.with_suffix('.txt').write_text(text, encoding='utf-8')
    output_prefix.with_suffix('.json').write_text(json.dumps({'pages': pages}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(output_prefix.with_suffix('.txt'))
    print(output_prefix.with_suffix('.json'))


if __name__ == '__main__':
    main()
