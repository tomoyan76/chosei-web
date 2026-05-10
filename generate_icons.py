"""
PWAアイコン生成スクリプト
static/icon-192.png と static/icon-512.png を生成する。
Pillow がインストールされている必要がある: pip install Pillow
"""
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("Pillow がインストールされていません。")
    print("  pip install Pillow")
    raise


def make_icon(size: int) -> Image.Image:
    """指定サイズのアイコンを生成する"""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 背景：グラデーション風の角丸矩形
    # まず全体を塗る
    radius = size // 6
    bg_color = (79, 114, 255, 255)   # #4F72FF
    _draw_rounded_rect(draw, (0, 0, size, size), radius, bg_color)

    # カレンダーアイコンを描画
    pad = size // 8
    cal_left   = pad
    cal_top    = pad + size // 10
    cal_right  = size - pad
    cal_bottom = size - pad

    cal_w = cal_right - cal_left
    cal_h = cal_bottom - cal_top

    # カレンダー本体（白い角丸矩形）
    r2 = size // 14
    _draw_rounded_rect(draw, (cal_left, cal_top, cal_right, cal_bottom), r2, (255, 255, 255, 255))

    # ヘッダー部分（青い帯）
    header_h = cal_h // 4
    header_color = (63, 94, 210, 255)  # 少し暗い青
    _draw_rounded_rect(
        draw,
        (cal_left, cal_top, cal_right, cal_top + header_h + r2),
        r2,
        header_color,
    )
    # ヘッダー下部を矩形で覆って角丸を消す
    draw.rectangle(
        (cal_left, cal_top + header_h // 2, cal_right, cal_top + header_h + r2),
        fill=header_color,
    )

    # リングを描画（2本）
    ring_w = max(2, size // 50)
    ring_r = size // 20
    ring_y = cal_top - size // 20
    ring_color = (255, 255, 255, 255)
    ring1_x = cal_left + cal_w // 3
    ring2_x = cal_left + cal_w * 2 // 3
    for rx in (ring1_x, ring2_x):
        draw.ellipse(
            (rx - ring_r, ring_y - ring_r, rx + ring_r, ring_y + ring_r),
            fill=(79, 114, 255, 255),
            outline=ring_color,
            width=ring_w,
        )

    # グリッド線（日付マス）
    grid_top = cal_top + header_h + size // 20
    grid_bottom = cal_bottom - size // 20
    grid_left = cal_left + size // 20
    grid_right = cal_right - size // 20

    cols = 3
    rows = 2
    cell_w = (grid_right - grid_left) / cols
    cell_h = (grid_bottom - grid_top) / rows
    dot_r = max(2, size // 40)
    dot_color = (100, 130, 200, 200)

    for row in range(rows):
        for col in range(cols):
            cx = int(grid_left + cell_w * (col + 0.5))
            cy = int(grid_top + cell_h * (row + 0.5))
            draw.ellipse(
                (cx - dot_r, cy - dot_r, cx + dot_r, cy + dot_r),
                fill=dot_color,
            )

    # ○マーク（自分の回答）を1つハイライト
    highlight_cx = int(grid_left + cell_w * 0.5)
    highlight_cy = int(grid_top + cell_h * 0.5)
    hl_r = dot_r * 2
    draw.ellipse(
        (highlight_cx - hl_r, highlight_cy - hl_r, highlight_cx + hl_r, highlight_cy + hl_r),
        fill=(34, 197, 94, 255),   # #22C55E (green)
    )

    return img


def _draw_rounded_rect(draw: ImageDraw.Draw, bbox, radius: int, fill):
    """角丸矩形を描画するヘルパー"""
    x0, y0, x1, y1 = bbox
    draw.rectangle((x0 + radius, y0, x1 - radius, y1), fill=fill)
    draw.rectangle((x0, y0 + radius, x1, y1 - radius), fill=fill)
    draw.ellipse((x0, y0, x0 + radius * 2, y0 + radius * 2), fill=fill)
    draw.ellipse((x1 - radius * 2, y0, x1, y0 + radius * 2), fill=fill)
    draw.ellipse((x0, y1 - radius * 2, x0 + radius * 2, y1), fill=fill)
    draw.ellipse((x1 - radius * 2, y1 - radius * 2, x1, y1), fill=fill)


def main():
    static_dir = Path(__file__).parent / "static"
    static_dir.mkdir(exist_ok=True)

    for size in (192, 512):
        out_path = static_dir / f"icon-{size}.png"
        img = make_icon(size)
        img.save(str(out_path), "PNG")
        print(f"✅ {out_path} を生成しました ({size}x{size}px)")


if __name__ == "__main__":
    main()
