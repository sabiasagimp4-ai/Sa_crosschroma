"""テスト画像にプリセットを適用して docs/samples/ に書き出す。

  python3 tools/reference/render_samples.py <入力画像> [出力先]

CPUリファレンス実装(crosschroma.py)を使うので、YMM4上のシェーダーと
同じ結果になる。README用のサンプル画像はこれで作っている。
"""

from __future__ import annotations

import pathlib
import sys
import time

import numpy as np
from PIL import Image

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import crosschroma as cc  # noqa: E402

FORWARD = cc.ROUTING["forward"]
BACKWARD = cc.ROUTING["backward"]


def preset(name, description, ui, params):
    return dict(name=name, description=description, ui=ui, params=params)


PRESETS = [
    preset(
        "01-flow",
        "勾配を90°回転させ、輪郭に沿って色を流す",
        "強度24px / 角度90° / 順回転 / 感度150%",
        cc.CrossChromaParams(
            intensity=24, angle_deg=90, edge_gain=1.5,
            driver=FORWARD, modulation=cc.remaining_channels(FORWARD)),
    ),
    preset(
        "02-displace",
        "輪郭を横切る向きに変位させる（角度0°）",
        "強度16px / 角度0° / 順回転 / 感度150%",
        cc.CrossChromaParams(
            intensity=16, angle_deg=0, edge_gain=1.5,
            driver=FORWARD, modulation=cc.remaining_channels(FORWARD)),
    ),
    preset(
        "03-morphology",
        "他チャンネルの明るさで膨張させる",
        "強度10px / 角度90° / 膨張100% / 半径4px / 制御=残りのチャンネル",
        cc.CrossChromaParams(
            intensity=10, angle_deg=90, edge_gain=1.5,
            morph_strength=1.0, filter_radius=4.0,
            driver=FORWARD, modulation=cc.remaining_channels(FORWARD)),
    ),
    preset(
        "04-blur",
        "他チャンネルの明るさでぼかす",
        "強度12px / 角度90° / ぼかし100% / 半径3px / 制御=残りのチャンネル",
        cc.CrossChromaParams(
            intensity=12, angle_deg=90, edge_gain=1.5,
            blur_strength=1.0, filter_radius=3.0,
            driver=FORWARD, modulation=cc.remaining_channels(FORWARD)),
    ),
    preset(
        "05-soft",
        "広い範囲の濃淡に反応させる（検出半径を広げる）",
        "強度40px / 角度90° / 検出半径6px / 感度250% / ガンマ0.6",
        cc.CrossChromaParams(
            intensity=40, angle_deg=90, edge_radius=6.0,
            edge_gain=2.5, edge_gamma=0.6,
            driver=FORWARD, modulation=cc.remaining_channels(FORWARD)),
    ),
    preset(
        "06-subtle",
        "実用的な控えめの設定",
        "強度6px / 角度90° / 感度200% / 適用量60%",
        cc.CrossChromaParams(
            intensity=6, angle_deg=90, edge_gain=2.0, mix=0.6,
            driver=FORWARD, modulation=cc.remaining_channels(FORWARD)),
    ),
    preset(
        "07-full",
        "変位・ぼかし・収縮を全部使い、逆回転で組み合わせる",
        "強度28px / 角度120° / 逆回転 / ぼかし60% / 収縮-60% / 半径4px",
        cc.CrossChromaParams(
            intensity=28, angle_deg=120, edge_gain=2.0,
            blur_strength=0.6, morph_strength=-0.6, filter_radius=4.0,
            driver=BACKWARD, modulation=cc.remaining_channels(BACKWARD)),
    ),
]


def load(path: pathlib.Path) -> np.ndarray:
    image = Image.open(path).convert("RGBA")
    return np.asarray(image, dtype=np.float32) / 255.0


def save(array: np.ndarray, path: pathlib.Path) -> None:
    rgb = np.clip(array[..., :3], 0.0, 1.0) * 255.0
    image = Image.fromarray(rgb.round().astype(np.uint8), mode="RGB")
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, quality=92, subsampling=0)


# 細い金属フレームが多く、チャンネルごとの違いが見やすい場所
CROP_BOX = (380, 280, 680, 480)
COMPARISON = ["00-source", "02-displace", "01-flow", "05-soft"]


def make_comparison(out_dir: pathlib.Path, scale: int = 2, label_height: int = 22) -> None:
    """サンプルの一部を拡大して並べた比較画像を作る。"""
    from PIL import ImageDraw

    left, top, right, bottom = CROP_BOX
    tile_w = (right - left) * scale
    tile_h = (bottom - top) * scale + label_height
    sheet = Image.new("RGB", (tile_w * 2, tile_h * 2), (24, 24, 24))
    draw = ImageDraw.Draw(sheet)

    for index, name in enumerate(COMPARISON):
        tile = Image.open(out_dir / f"{name}.jpg").convert("RGB")
        tile = tile.crop(CROP_BOX).resize((tile_w, tile_h - label_height), Image.NEAREST)
        x = (index % 2) * tile_w
        y = (index // 2) * tile_h
        sheet.paste(tile, (x, y + label_height))
        draw.text((x + 6, y + 6), name, fill=(235, 235, 235))

    sheet.save(out_dir / "comparison.jpg", quality=92, subsampling=0)
    print(f"  comparison     {'/'.join(COMPARISON)} を {scale}倍で並べた比較画像")


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1

    source_path = pathlib.Path(sys.argv[1])
    out_dir = pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 else pathlib.Path("docs/samples")

    source = load(source_path)
    print(f"入力: {source_path} {source.shape[1]}x{source.shape[0]}")

    # 入力がそのままサンプルの元画像になっている場合は、再圧縮しない
    copied = out_dir / "00-source.jpg"
    if source_path.resolve() != copied.resolve():
        save(source, copied)

    for item in PRESETS:
        started = time.perf_counter()
        result = cc.apply(source, item["params"])
        save(result, out_dir / f"{item['name']}.jpg")
        elapsed = time.perf_counter() - started
        diff = float(np.abs(result[..., :3] - source[..., :3]).mean())
        print(f"  {item['name']:<14} {item['description']}  "
              f"(平均変化 {diff * 255:.1f}/255, {elapsed:.1f}s)")

    make_comparison(out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
