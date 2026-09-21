"""テスト画像にプリセットを適用して docs/samples/ に書き出す。

  python3 tools/reference/render_samples.py <入力画像> [出力先] [--full]

--full を付けると、スイープの各設定を切り抜きも拡大もせずそのまま
<出力先>/full/ にも書き出す(10分ほどかかる)。

CPUリファレンス実装(crosschroma.py)を使うので、YMM4上のシェーダーと
同じ結果になる。README用のサンプル画像はこれで作っている。
"""

from __future__ import annotations

import math
import pathlib
import sys
import time
from dataclasses import replace

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
        "強度24px / 角度90° / ステップ数8 / 順回転 / 感度150%",
        cc.CrossChromaParams(
            intensity=24, angle_deg=90, edge_gain=1.5, steps=8,
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
    preset(
        "08-iterate",
        "エフェクト全体を繰り返して、変形の上にさらに変形を重ねる",
        "強度10px / 角度90° / ステップ数4 / 反復回数3 / 感度150%",
        cc.CrossChromaParams(
            intensity=10, angle_deg=90, edge_gain=1.5, steps=4, iterations=3,
            driver=FORWARD, modulation=cc.remaining_channels(FORWARD)),
    ),
]

# ステップ数だけを変えた比較。01-flow と同じ設定から歩数だけ動かす。
STEP_COUNTS = [1, 2, 4, 16]

# ---------------------------------------------------------------------------
# パラメーター実験（1項目ずつ振って並べる）
# ---------------------------------------------------------------------------

# スイープの基準。01-flow と同じ、素直に流れる設定。
SWEEP_BASE = cc.CrossChromaParams(
    intensity=24, angle_deg=90, edge_gain=1.5, steps=8,
    driver=FORWARD, modulation=cc.remaining_channels(FORWARD))


def sweep(name, title, note, variants):
    return dict(name=name, title=title, note=note, variants=variants)


SWEEPS = [
    sweep(
        "sweep-intensity", "強度",
        "1歩あたりを3pxに固定したまま強度だけ伸ばす（ステップ数も一緒に上げている）",
        [("intensity 8px  /  steps 4", "8px", dict(intensity=8, steps=4)),
         ("intensity 24px  /  steps 8", "24px", dict(intensity=24, steps=8)),
         ("intensity 60px  /  steps 20", "60px", dict(intensity=60, steps=20)),
         ("intensity 120px  /  steps 40", "120px", dict(intensity=120, steps=40))],
    ),
    sweep(
        "sweep-stepsize", "1歩あたりの移動量",
        "強度120pxのままステップ数だけを変える（1歩あたり30/15/7.5/3px）",
        [("steps 4  ->  30px per step", "30px-step", dict(intensity=120, steps=4)),
         ("steps 8  ->  15px per step", "15px-step", dict(intensity=120, steps=8)),
         ("steps 16  ->  7.5px per step", "7.5px-step", dict(intensity=120, steps=16)),
         ("steps 40  ->  3px per step", "3px-step", dict(intensity=120, steps=40))],
    ),
    sweep(
        "sweep-angle", "角度",
        "勾配をどれだけ回して進むか。0°で輪郭を横切り、90°で輪郭に沿う",
        [("angle 0 deg  (across the edge)", "0deg", dict(angle_deg=0)),
         ("angle 45 deg", "45deg", dict(angle_deg=45)),
         ("angle 90 deg  (along the edge)", "90deg", dict(angle_deg=90)),
         ("angle 135 deg", "135deg", dict(angle_deg=135))],
    ),
    sweep(
        "sweep-radius", "検出半径",
        "輪郭をどれだけ広く見るか。広げるほど線画ではなく面の陰影を拾う",
        [("edge radius 1px", "1px", dict(edge_radius=1.0)),
         ("edge radius 2px", "2px", dict(edge_radius=2.0)),
         ("edge radius 4px", "4px", dict(edge_radius=4.0)),
         ("edge radius 8px", "8px", dict(edge_radius=8.0))],
    ),
    sweep(
        "sweep-gain", "感度",
        "どれだけ弱い輪郭まで拾うか。上げるほど平坦な部分まで動きだす",
        [("gain 50%", "50", dict(edge_gain=0.5)),
         ("gain 150%", "150", dict(edge_gain=1.5)),
         ("gain 300%", "300", dict(edge_gain=3.0)),
         ("gain 600%", "600", dict(edge_gain=6.0))],
    ),
    sweep(
        "sweep-gamma", "ガンマ",
        "感度600%のまま、弱い輪郭の扱いだけをガンマで変える",
        [("gamma 0.4  (gain 600%)", "0.4", dict(edge_gain=6.0, edge_gamma=0.4)),
         ("gamma 1.0", "1.0", dict(edge_gain=6.0, edge_gamma=1.0)),
         ("gamma 2.5", "2.5", dict(edge_gain=6.0, edge_gamma=2.5)),
         ("gamma 6.0", "6.0", dict(edge_gain=6.0, edge_gamma=6.0))],
    ),
    sweep(
        "sweep-iterations", "反復回数",
        "1回あたり強度12pxに抑えて、エフェクト全体を繰り返す",
        [("1 iteration  (12px total)", "1", dict(intensity=12, iterations=1)),
         ("2 iterations  (24px total)", "2", dict(intensity=12, iterations=2)),
         ("4 iterations  (48px total)", "4", dict(intensity=12, iterations=4)),
         ("8 iterations  (96px total)", "8", dict(intensity=12, iterations=8))],
    ),
    sweep(
        "sweep-modulation", "変調",
        "他チャンネルの明るさでぼかし / 膨張 / 収縮をかける（半径4px）",
        [("no modulation", "none", dict()),
         ("blur 100%", "blur", dict(blur_strength=1.0, filter_radius=4.0)),
         ("dilate 100%", "dilate", dict(morph_strength=1.0, filter_radius=4.0)),
         ("erode -100%", "erode", dict(morph_strength=-1.0, filter_radius=4.0))],
    ),
]

# 適用量は最後のブレンドなので、1枚のレンダーから作れる（反復1回のとき）。
MIX_AMOUNTS = [0.25, 0.5, 0.75, 1.0]


def load(path: pathlib.Path) -> np.ndarray:
    image = Image.open(path).convert("RGBA")
    return np.asarray(image, dtype=np.float32) / 255.0


# 色のにじみを見せる画像なので、クロマサブサンプリングは切っておく。
JPEG_OPTIONS = dict(quality=92, subsampling=0)


def save(array: np.ndarray, path: pathlib.Path) -> None:
    rgb = np.clip(array[..., :3], 0.0, 1.0) * 255.0
    image = Image.fromarray(rgb.round().astype(np.uint8), mode="RGB")
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, **JPEG_OPTIONS)


# 細い金属フレームが多く、チャンネルごとの違いが見やすい場所
CROP_BOX = (380, 280, 680, 480)

# 書き出し済みJPEGと描き直した結果を突き合わせるための範囲。
# JPEGは8x8ブロック単位で圧縮するので、境界を8の倍数に揃えておくと
# 「全体を書き出してから切る」と「切ってから書き出す」が一致する。
VERIFY_BOX = (384, 280, 680, 480)
COMPARISON = ["00-source", "02-displace", "01-flow", "05-soft"]


# ラベルはどの環境でも同じ絵になるよう英数字だけで書く。
# フォントが見つからなければPILの内蔵ビットマップフォントで出る(小さいが読める)。
LABEL_FONTS = ["DejaVuSans.ttf", "LiberationSans-Regular.ttf", "Arial.ttf", "Helvetica.ttc"]


def label_font(size: int = 17):
    from PIL import ImageFont

    for name in LABEL_FONTS:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def make_sheet(tiles, path: pathlib.Path, scale: int = 2, label_height: int = 26,
               crop=CROP_BOX, columns: int = 2) -> None:
    """(ラベル, PIL画像) を2列に並べたシートを書き出す。

    crop に矩形を渡すとその範囲を切り出す。None なら渡された画像をそのまま使う
    (すでに切り出し済みの場合)。
    """
    from PIL import ImageDraw

    if crop is None:
        tile_w = tiles[0][1].width * scale
        tile_h = tiles[0][1].height * scale + label_height
    else:
        left, top, right, bottom = crop
        tile_w = (right - left) * scale
        tile_h = (bottom - top) * scale + label_height
    rows = (len(tiles) + columns - 1) // columns
    sheet = Image.new("RGB", (tile_w * columns, tile_h * rows), (24, 24, 24))
    draw = ImageDraw.Draw(sheet)
    font = label_font()

    for index, (label, image) in enumerate(tiles):
        tile = image.convert("RGB")
        if crop is not None:
            tile = tile.crop(crop)
        tile = tile.resize((tile_w, tile_h - label_height), Image.NEAREST)
        x = (index % columns) * tile_w
        y = (index // columns) * tile_h
        sheet.paste(tile, (x, y + label_height))
        draw.text((x + 8, y + 5), label, fill=(235, 235, 235), font=font)

    sheet.save(path, **JPEG_OPTIONS)


def dependency_margin(p: cc.CrossChromaParams) -> int:
    """出力1画素が入力を参照しうる最大距離 (px)。

    1パスで参照が届くのは「歩いた先 + 輪郭検出の半径 + フィルタの半径」まで。
    バイリニア補間のぶん1px、切り上げのぶん1pxを足して余裕を持たせる。
    反復するとこれがパスごとに積み上がる。
    """
    reach = p.intensity + p.edge_radius
    if p.filter_enabled:
        reach += p.filter_radius
    return int(math.ceil((reach + 2.0) * max(1, p.iterations)))


def render_crop(source: np.ndarray, p: cc.CrossChromaParams, box) -> Image.Image:
    """box の範囲だけをレンダリングする。

    参照が届く距離ぶん余白を付けて計算してから切り出すので、
    全画面をレンダリングして切り出したものと同じ絵になる。
    スイープは同じ場所しか見ないので、こちらのほうがずっと速い。

    厳密にビット単位で同じにはならない。座標の絶対値が変わるぶん
    float32の丸めがずれ、歩いた経路は初期値に敏感なので、
    数画素だけ数/255の差が出ることがある。
    """
    left, top, right, bottom = box
    height, width = source.shape[:2]
    margin = dependency_margin(p)
    x0, y0 = max(0, left - margin), max(0, top - margin)
    x1, y1 = min(width, right + margin), min(height, bottom + margin)

    result = cc.apply(source[y0:y1, x0:x1], p)
    patch = result[top - y0:bottom - y0, left - x0:right - x0]
    rgb = np.clip(patch[..., :3], 0.0, 1.0) * 255.0
    return Image.fromarray(rgb.round().astype(np.uint8))


def crop_source(source: np.ndarray, box) -> np.ndarray:
    left, top, right, bottom = box
    return source[top:bottom, left:right, :3] * 255.0


def make_sweeps(source: np.ndarray, out_dir: pathlib.Path) -> None:
    """パラメーターを1項目ずつ振った比較シートを書き出す。"""
    original = crop_source(source, CROP_BOX)
    for item in SWEEPS:
        started = time.perf_counter()
        tiles, changes = [], []
        for label, _slug, overrides in item["variants"]:
            params = replace(SWEEP_BASE, **overrides)
            tile = render_crop(source, params, CROP_BOX)
            tiles.append((label, tile))
            changes.append(float(np.abs(
                np.asarray(tile, dtype=np.float32) - original).mean()))
        make_sheet(tiles, out_dir / f"{item['name']}.jpg", crop=None)
        elapsed = time.perf_counter() - started
        amounts = " / ".join(f"{value:.1f}" for value in changes)
        print(f"  {item['name']:<18} {item['title']}  "
              f"(比較領域の平均変化 {amounts} /255, {elapsed:.1f}s)")


def make_full_frames(source: np.ndarray, out_dir: pathlib.Path) -> None:
    """スイープの各設定を、切り抜きも拡大もせずそのまま書き出す。

    比較シートは細部を見るために2倍に拡大しているので、
    「実際に使うとどう見えるか」は等倍のこちらで見る。
    全画面を人数分レンダリングするので時間がかかる(10分ほど)。
    """
    full_dir = out_dir / "full"
    for item in SWEEPS:
        started = time.perf_counter()
        for _label, slug, overrides in item["variants"]:
            params = replace(SWEEP_BASE, **overrides)
            save(cc.apply(source, params), full_dir / f"{item['name']}-{slug}.jpg")
        elapsed = time.perf_counter() - started
        names = " / ".join(slug for _l, slug, _o in item["variants"])
        print(f"  full/{item['name']:<22} {names}  ({elapsed:.0f}s)")

    # 適用量は最後のブレンドなので、1枚から作れる
    started = time.perf_counter()
    full = cc.apply(source, replace(SWEEP_BASE, mix=1.0))
    for amount in MIX_AMOUNTS:
        blended = source.copy()
        blended[..., :3] = source[..., :3] * (1 - amount) + full[..., :3] * amount
        save(blended, full_dir / f"sweep-mix-{int(amount * 100)}.jpg")
    print(f"  full/{'sweep-mix':<22} "
          f"{' / '.join(str(int(a * 100)) for a in MIX_AMOUNTS)}  "
          f"({time.perf_counter() - started:.0f}s)")


def make_mix_sweep(source: np.ndarray, out_dir: pathlib.Path) -> None:
    """適用量だけを振った比較シート。最後のブレンドなので1枚から作れる。"""
    started = time.perf_counter()
    params = replace(SWEEP_BASE, mix=1.0)
    full = render_crop(source, params, CROP_BOX)
    left, top, right, bottom = CROP_BOX
    original = Image.fromarray(
        (np.clip(source[top:bottom, left:right, :3], 0.0, 1.0) * 255.0)
        .round().astype(np.uint8))

    tiles = [(f"mix {int(amount * 100)}%",
              Image.blend(original, full, amount)) for amount in MIX_AMOUNTS]
    make_sheet(tiles, out_dir / "sweep-mix.jpg", crop=None)
    elapsed = time.perf_counter() - started
    print(f"  {'sweep-mix':<18} 適用量  "
          f"({'/'.join(f'{int(a * 100)}%' for a in MIX_AMOUNTS)}, {elapsed:.1f}s)")


def make_comparison(out_dir: pathlib.Path) -> None:
    """プリセット同士を並べた比較画像を作る。"""
    tiles = [(name, Image.open(out_dir / f"{name}.jpg")) for name in COMPARISON]
    make_sheet(tiles, out_dir / "comparison.jpg")
    print(f"  comparison     {'/'.join(COMPARISON)} を並べた比較画像")


def make_full_comparison(out_dir: pathlib.Path) -> None:
    """元画像と適用後を、切り抜きも拡大もせず縦に並べる。

    READMEの先頭に置く1枚。実際に使ったときの見え方をそのまま見せたいので、
    こちらは等倍にしておく(拡大した比較は comparison.jpg のほうにある)。
    """
    tiles = [
        ("before", "00-source"),
        ("after  01-flow   (intensity 24px)", "01-flow"),
        ("after  05-soft   (intensity 40px / edge radius 6px)", "05-soft"),
    ]
    make_sheet([(label, Image.open(out_dir / f"{name}.jpg")) for label, name in tiles],
               out_dir / "comparison-full.jpg", scale=1, crop=None, columns=1)
    print("  comparison-full  元画像と01-flow/05-softを等倍で縦に並べた1枚")


def make_step_comparison(source: np.ndarray, out_dir: pathlib.Path) -> None:
    """ステップ数だけを変えた比較画像を作る。"""
    base = PRESETS[0]["params"]
    tiles = []
    for steps in STEP_COUNTS:
        params = replace(base, steps=steps)
        result = cc.apply(source, params)
        rgb = np.clip(result[..., :3], 0.0, 1.0) * 255.0
        tiles.append((f"steps = {steps}", Image.fromarray(rgb.round().astype(np.uint8))))

    make_sheet(tiles, out_dir / "steps.jpg")
    print(f"  steps          ステップ数 {'/'.join(map(str, STEP_COUNTS))} を並べた比較画像")


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    want_full = "--full" in sys.argv
    if not args:
        print(__doc__)
        return 1

    source_path = pathlib.Path(args[0])
    out_dir = pathlib.Path(args[1]) if len(args) > 1 else pathlib.Path("docs/samples")

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
    make_full_comparison(out_dir)
    make_step_comparison(source, out_dir)
    make_sweeps(source, out_dir)
    make_mix_sweep(source, out_dir)
    if want_full:
        make_full_frames(source, out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
