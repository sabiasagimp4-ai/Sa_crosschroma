"""Sa_CrossChroma のテスト。

  python3 tools/reference/test_crosschroma.py

前半はアルゴリズムの振る舞い、後半は HLSL / C# / Python の3実装が
同じ並び・同じ定数を使っているかの突き合わせ。
"""

from __future__ import annotations

import pathlib
import re
import sys
import traceback

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import crosschroma as cc  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]
HLSL = (ROOT / "src/Sa_CrossChroma/Shaders/CrossChroma.hlsl").read_text(encoding="utf-8")
CUSTOM_EFFECT_CS = (ROOT / "src/Sa_CrossChroma/CrossChromaCustomEffect.cs").read_text(encoding="utf-8")
PARAMETERS_CS = (ROOT / "src/Sa_CrossChroma/CrossChromaShaderParameters.cs").read_text(encoding="utf-8")
ROUTING_CS = (ROOT / "src/Sa_CrossChroma/ChannelRouting.cs").read_text(encoding="utf-8")
EFFECT_CS = (ROOT / "src/Sa_CrossChroma/CrossChromaEffect.cs").read_text(encoding="utf-8")
PROCESSOR_CS = (ROOT / "src/Sa_CrossChroma/CrossChromaProcessor.cs").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# テスト用の画像
# ---------------------------------------------------------------------------

def solid(w=16, h=16, rgb=(0.5, 0.5, 0.5), alpha=1.0):
    img = np.zeros((h, w, 4), dtype=np.float32)
    img[..., 0], img[..., 1], img[..., 2] = rgb
    img[..., 3] = alpha
    return img


def vertical_edge(channel, w=32, h=32, low=0.0, high=1.0):
    """x = w/2 で切り替わる縦のエッジ。勾配は +x 方向を向く。"""
    img = solid(w, h, (0, 0, 0))
    img[..., channel] = low
    img[:, w // 2:, channel] = high
    return img


def radial_ramp(channels, size=64, scale=32.0):
    """中心からの距離をそのまま値にした画像。勾配は放射方向、等値線は同心円になる。"""
    center = (size - 1) / 2.0
    ys, xs = np.mgrid[0:size, 0:size].astype(np.float32)
    radius = np.sqrt((xs - center) ** 2 + (ys - center) ** 2)

    img = solid(size, size, (0.0, 0.0, 0.0))
    for channel in channels:
        img[..., channel] = np.clip(radius / scale, 0.0, 1.0)
    return img, radius


# ---------------------------------------------------------------------------
# アルゴリズム
# ---------------------------------------------------------------------------

def test_identity_when_intensity_is_zero():
    img = vertical_edge(cc.CH_G)
    img[..., cc.CH_R] = np.linspace(0, 1, img.shape[1], dtype=np.float32)
    out = cc.apply(img, cc.CrossChromaParams(intensity=0))
    assert np.allclose(out, img, atol=1e-6), np.abs(out - img).max()


def test_mix_zero_is_identity():
    img = vertical_edge(cc.CH_G)
    img[..., cc.CH_R] = np.linspace(0, 1, img.shape[1], dtype=np.float32)
    out = cc.apply(img, cc.CrossChromaParams(intensity=8, mix=0.0))
    assert np.allclose(out, img, atol=1e-6), np.abs(out - img).max()


def test_flat_image_is_unchanged():
    """輪郭が無ければ動かない。"""
    img = solid(rgb=(0.3, 0.6, 0.9))
    out = cc.apply(img, cc.CrossChromaParams(intensity=20, blur_strength=1.0, morph_strength=1.0))
    assert np.allclose(out, img, atol=1e-5), np.abs(out - img).max()


def test_alpha_is_preserved():
    img = vertical_edge(cc.CH_G)
    img[..., 3] = np.linspace(0.2, 1.0, img.shape[1], dtype=np.float32)
    out = cc.apply(img, cc.CrossChromaParams(intensity=6))
    assert np.allclose(out[..., 3], img[..., 3], atol=1e-6)


def test_displacement_follows_driver_channel():
    """Rが動くのはドライバー(G)の輪郭のある所だけ。"""
    h = w = 32
    img = vertical_edge(cc.CH_G, w, h)
    img[..., cc.CH_R] = np.linspace(0.0, 1.0, w, dtype=np.float32)  # x方向に変化

    moved = cc.apply(img, cc.CrossChromaParams(
        intensity=6, angle_deg=0, driver=(cc.CH_G, cc.CH_G, cc.CH_G)))
    diff = np.abs(moved[..., cc.CH_R] - img[..., cc.CH_R])

    # Rは傾斜なので、値の差をそのまま移動距離(px)に直せる
    slope = 1.0 / (w - 1)
    assert diff.max() / slope > 1.0, f"Gの輪郭でRが動いていない ({diff.max() / slope:.2f}px)"
    # 動くのは輪郭をまたぐ2列だけ。エッジから十分離れた場所は動かない
    assert diff[:, :w // 2 - 4].max() < 1e-5
    assert diff[:, w // 2 + 4:].max() < 1e-5

    # ドライバーを平坦なBにすると、どこも動かない
    still = cc.apply(img, cc.CrossChromaParams(
        intensity=6, angle_deg=0, driver=(cc.CH_B, cc.CH_B, cc.CH_B)))
    assert np.allclose(still[..., cc.CH_R], img[..., cc.CH_R], atol=1e-6)


def test_angle_rotates_displacement():
    """0°は輪郭を横切る向き、90°は輪郭に沿う向き。"""
    h = w = 32
    img = vertical_edge(cc.CH_G, w, h)
    # Rはyにだけ変化させる → y方向に動いた時だけ値が変わる
    img[..., cc.CH_R] = np.linspace(0.0, 1.0, h, dtype=np.float32)[:, None]

    across = cc.apply(img, cc.CrossChromaParams(
        intensity=6, angle_deg=0, driver=(cc.CH_G,) * 3))
    assert np.allclose(across[..., cc.CH_R], img[..., cc.CH_R], atol=1e-6), \
        "0°では輪郭を横切る向き(x)に動くので、y方向にしか変化しないRは変わらないはず"

    along = cc.apply(img, cc.CrossChromaParams(
        intensity=6, angle_deg=90, driver=(cc.CH_G,) * 3))
    center = w // 2
    assert np.abs(along[..., cc.CH_R] - img[..., cc.CH_R]).max() > 0.05, \
        "90°では輪郭に沿う向き(y)に動くはず"
    # +y(下)からサンプリングするので、上から下に明るくなるRは明るい方へ寄る
    row = h // 2
    assert along[row, center, cc.CH_R] > img[row, center, cc.CH_R]


def test_cyclic_routing_moves_every_channel():
    rng = np.random.default_rng(0)
    img = np.zeros((24, 24, 4), dtype=np.float32)
    img[..., :3] = rng.random((24, 24, 3), dtype=np.float32)
    img[..., 3] = 1.0

    out = cc.apply(img, cc.CrossChromaParams(intensity=4, driver=cc.ROUTING["forward"]))
    for c, name in enumerate("RGB"):
        assert np.abs(out[..., c] - img[..., c]).max() > 0.01, f"{name}が動いていない"


def test_dilate_and_erode():
    """膨張で明るい点が広がり、収縮で痩せる。"""
    img = solid(24, 24, (0.0, 0.0, 0.0))
    img[10:14, 10:14, cc.CH_R] = 1.0

    base = dict(intensity=0, filter_radius=1.0,
                modulation=(cc.CH_ONE,) * 3, driver=(cc.CH_ONE,) * 3)
    dilated = cc.apply(img, cc.CrossChromaParams(morph_strength=1.0, **base))
    eroded = cc.apply(img, cc.CrossChromaParams(morph_strength=-1.0, **base))

    lit = lambda a: int((a[..., cc.CH_R] > 0.5).sum())
    assert lit(dilated) > lit(img) > lit(eroded), (lit(dilated), lit(img), lit(eroded))


def test_blur_reduces_contrast():
    rng = np.random.default_rng(1)
    img = np.zeros((24, 24, 4), dtype=np.float32)
    img[..., :3] = rng.random((24, 24, 3), dtype=np.float32)
    img[..., 3] = 1.0

    out = cc.apply(img, cc.CrossChromaParams(
        intensity=0, blur_strength=1.0, filter_radius=1.0,
        modulation=(cc.CH_ONE,) * 3, driver=(cc.CH_ONE,) * 3))
    assert out[..., cc.CH_R].std() < img[..., cc.CH_R].std() * 0.8


def test_modulation_channel_controls_strength():
    """変調チャンネルが暗い所ではフィルタがかからない。"""
    w = h = 32
    img = solid(w, h, (0.0, 0.0, 0.0))
    img[..., cc.CH_B] = 0.0
    img[:, w // 2:, cc.CH_B] = 1.0          # 右半分だけ変調が最大
    img[8:12, 4:8, cc.CH_R] = 1.0           # 左の点
    img[8:12, w - 8:w - 4, cc.CH_R] = 1.0   # 右の点

    out = cc.apply(img, cc.CrossChromaParams(
        intensity=0, morph_strength=1.0, filter_radius=1.0,
        driver=(cc.CH_ONE,) * 3, modulation=(cc.CH_B, cc.CH_B, cc.CH_B)))

    left = out[:, :w // 2, cc.CH_R]
    left_src = img[:, :w // 2, cc.CH_R]
    assert np.allclose(left, left_src, atol=1e-6), "変調が0の側でフィルタがかかっている"
    assert int((out[:, w // 2:, cc.CH_R] > 0.5).sum()) > int((img[:, w // 2:, cc.CH_R] > 0.5).sum())


def test_transparent_area_does_not_bleed_black():
    """完全に透明な部分は色を持たないので、偽の輪郭を作らない。"""
    w = h = 32
    img = solid(w, h, (0.5, 0.5, 0.5))
    img[:, w // 2:, :] = 0.0  # 右半分は透明(乗算済みでもRGB=0)

    out = cc.apply(img, cc.CrossChromaParams(intensity=10, driver=(cc.CH_LUMA,) * 3))

    opaque = out[:, :w // 2, :3]
    assert np.allclose(opaque, 0.5, atol=1e-5), \
        f"不透明部分に透明部分の黒が滲んでいる (min={opaque.min()})"
    assert np.allclose(out[:, w // 2:, 3], 0.0)


def test_intensity_scales_displacement():
    """強度をn倍にすると、サンプリング位置もn倍離れる。

    ステップエッジだと「勾配が0でない画素」しか動かないので、
    傾斜(どこでも勾配が一定)を使って移動量そのものを測る。
    """
    w = h = 32
    slope = 1.0 / (w - 1)
    ramp = np.linspace(0.0, 1.0, w, dtype=np.float32)

    img = solid(w, h, (0.0, 0.0, 0.0))
    img[..., cc.CH_G] = ramp  # 変形の元
    img[..., cc.CH_R] = ramp  # 移動量を読み取る対象

    # 勾配の長さは 2*slope。感度でちょうど1.0に正規化する
    p = dict(angle_deg=0, driver=(cc.CH_G,) * 3,
             edge_gain=1.0 / (2.0 * slope), edge_radius=1.0)
    row, col = h // 2, w // 2

    for intensity in (2.0, 4.0, 6.0):
        out = cc.apply(img, cc.CrossChromaParams(intensity=intensity, **p))
        moved = out[row, col, cc.CH_R] - img[row, col, cc.CH_R]
        assert abs(moved - intensity * slope) < 1e-4, (intensity, moved, intensity * slope)


def test_step_edge_moves_by_edge_width():
    """ステップエッジでは、輪郭が見えている画素だけが動く。"""
    w = h = 32
    img = vertical_edge(cc.CH_R, w, h)
    out = cc.apply(img, cc.CrossChromaParams(
        intensity=8, angle_deg=0, steps=1, driver=(cc.CH_R,) * 3, edge_radius=1.0))

    row = out[h // 2, :, cc.CH_R]
    src = img[h // 2, :, cc.CH_R]
    # 検出半径1pxなので、エッジの1px手前だけが明るい側から色を拾う
    assert src[w // 2 - 1] == 0.0 and row[w // 2 - 1] == 1.0
    assert row[w // 2 - 2] == 0.0


def test_steps_do_not_change_total_displacement():
    """勾配が一定な場所では、歩数を変えても結果は変わらない。

    ステップ数は「どう進むか」を細かくするだけで、移動量そのものは
    強度で決まる、という取り決めを固定しておく。
    """
    size = 64
    slope = 1.0 / (size - 1)
    ramp = np.linspace(0.0, 1.0, size, dtype=np.float32)

    img = solid(size, size, (0.0, 0.0, 0.0))
    img[..., cc.CH_G] = ramp  # 変形の元。傾斜なのでどこでも勾配が同じ
    img[..., cc.CH_R] = ramp  # 移動量を読み取る対象

    p = dict(intensity=6, angle_deg=0, driver=(cc.CH_G,) * 3,
             edge_gain=1.0 / (2.0 * slope), edge_radius=1.0)
    one = cc.apply(img, cc.CrossChromaParams(steps=1, **p))
    many = cc.apply(img, cc.CrossChromaParams(steps=12, **p))

    # 画像の端は外側のクランプで勾配が変わるので内側だけ見る
    inner = (slice(10, size - 12), slice(10, size - 12))
    assert np.allclose(one[inner], many[inner], atol=1e-5), \
        np.abs(one[inner] - many[inner]).max()


def test_steps_follow_the_contour():
    """角度90°では、歩数を増やすほど等値線に沿って進む。

    放射状の傾斜だと等値線は同心円になる。接線方向へ一気に飛ぶと円の外へ
    ふくらんでしまうが、細かく刻んで勾配を取り直せば円に沿って回れる。
    Rにも同じ傾斜を入れてあるので、円からのずれがそのままRの変化になる。
    """
    size, scale = 64, 32.0
    img, radius = radial_ramp((cc.CH_R, cc.CH_G), size, scale)

    # 勾配の長さは 2/scale。感度でちょうど1.0に正規化する
    p = dict(intensity=12, angle_deg=90, driver=(cc.CH_G,) * 3,
             edge_gain=scale / 2.0, edge_radius=1.0)
    ring = (radius > 12) & (radius < 20)

    def drift(steps):
        out = cc.apply(img, cc.CrossChromaParams(steps=steps, **p))
        return float(np.abs(out[..., cc.CH_R] - img[..., cc.CH_R])[ring].mean() * scale)

    coarse = drift(1)
    fine = drift(16)
    assert coarse > 2.0, coarse                     # 1歩だと円からはっきり外れる
    assert fine < coarse * 0.35, (coarse, fine)     # 刻めば円に沿う


def test_channel_gradient_matches_shared_gradient():
    """歩きながら取り直す勾配が、1歩目に使う共有の勾配と一致すること。

    1歩目だけmainで計算済みの勾配を使い回しているので、
    ここがずれると歩数を変えた瞬間に絵が飛ぶ。
    """
    size = 20
    rng = np.random.default_rng(7)
    img = np.zeros((size, size, 4), dtype=np.float32)
    img[..., :3] = rng.random((size, size, 3), dtype=np.float32)
    img[..., 3] = 1.0

    premul = cc.premultiply(img)
    xs, ys = np.meshgrid(np.arange(size, dtype=np.float32), np.arange(size, dtype=np.float32))
    center = cc.unpremultiply(cc.sample_premultiplied(premul, xs, ys, cc.BORDER_CLAMP))
    center_signals = cc.signals(center)

    grad_x = np.zeros((size, size, 4), dtype=np.float32)
    grad_y = np.zeros((size, size, 4), dtype=np.float32)
    for i, (ox, oy) in enumerate(cc.OFFSETS):
        tap = cc.sample_signals(premul, xs + ox, ys + oy, cc.BORDER_CLAMP, center_signals)
        grad_x += cc.SOBEL_X[i] * tap
        grad_y += cc.SOBEL_Y[i] * tap
    grad_x *= 0.25
    grad_y *= 0.25

    for channel in (cc.CH_R, cc.CH_G, cc.CH_B, cc.CH_LUMA, cc.CH_ONE):
        gx, gy = cc.channel_gradient(
            premul, xs, ys, cc.BORDER_CLAMP, channel,
            cc.select_channel(center, channel), 1.0)
        assert np.allclose(gx, cc.select_gradient(grad_x, channel), atol=1e-6), channel
        assert np.allclose(gy, cc.select_gradient(grad_y, channel), atol=1e-6), channel


def test_iterations_accumulate_displacement():
    """反復するとそのぶん変位が積み重なる。

    どこでも勾配が一定な傾斜なら1回につき同じ量だけずれるので、
    n回でちょうどn倍になるはず。ステップ数(合計が変わらない)との違いがここ。
    """
    size = 64
    slope = 1.0 / (size - 1)
    ramp = np.linspace(0.0, 1.0, size, dtype=np.float32)

    img = solid(size, size, (0.0, 0.0, 0.0))
    img[..., cc.CH_G] = ramp  # 変形の元。1回通しても傾斜のままなので勾配が変わらない
    img[..., cc.CH_R] = ramp  # 移動量を読み取る対象

    intensity = 3.0
    p = dict(intensity=intensity, angle_deg=0, steps=1, driver=(cc.CH_G,) * 3,
             edge_gain=1.0 / (2.0 * slope), edge_radius=1.0)
    row, col = size // 2, size // 2

    for iterations in (1, 2, 4):
        out = cc.apply(img, cc.CrossChromaParams(iterations=iterations, **p))
        moved = out[row, col, cc.CH_R] - img[row, col, cc.CH_R]
        expected = iterations * intensity * slope
        assert abs(moved - expected) < 1e-4, (iterations, moved, expected)


def test_iterations_feed_the_result_back():
    """n回の反復は、1回通した結果をさらにn-1回通したものと一致する。"""
    rng = np.random.default_rng(3)
    img = np.zeros((32, 32, 4), dtype=np.float32)
    img[..., :3] = rng.random((32, 32, 3), dtype=np.float32)
    img[..., 3] = 1.0

    p = dict(intensity=4, edge_gain=2.0, driver=cc.ROUTING["forward"])
    once = cc.apply(img, cc.CrossChromaParams(iterations=1, **p))
    thrice = cc.apply(img, cc.CrossChromaParams(iterations=3, **p))
    again = cc.apply(once, cc.CrossChromaParams(iterations=2, **p))

    assert np.allclose(again, thrice, atol=1e-6), np.abs(again - thrice).max()
    # 1回目ですでに絵は動いている(この比較が無意味にならないことの確認)
    assert np.abs(once[..., :3] - img[..., :3]).mean() > 0.01


def test_iterations_do_nothing_when_mix_is_zero():
    """適用量は1回ごとに効くので、0なら何回繰り返しても素通し。"""
    img = vertical_edge(cc.CH_G)
    img[..., cc.CH_R] = np.linspace(0, 1, img.shape[1], dtype=np.float32)
    out = cc.apply(img, cc.CrossChromaParams(intensity=8, iterations=6, mix=0.0))
    assert np.allclose(out, img, atol=1e-6), np.abs(out - img).max()


def test_fast_gradient_matches_sobel_at_texel_centers():
    """4タップ版の勾配が、画素の中心では8タップSobelと一致すること。

    検出半径1pxなら (±0.5, ±0.5) のタップがちょうど2x2の平均になり、
    展開すると Sobel/4 のカーネルそのものになる。
    ここが崩れると、切り替えのしきい値をまたいだ瞬間に絵が飛ぶ。
    """
    size = 40
    rng = np.random.default_rng(11)
    img = np.zeros((size, size, 4), dtype=np.float32)
    img[..., :3] = rng.random((size, size, 3), dtype=np.float32)
    img[..., 3] = 1.0

    premul = cc.premultiply(img)
    xs, ys = np.meshgrid(np.arange(size, dtype=np.float32), np.arange(size, dtype=np.float32))
    center = cc.unpremultiply(cc.sample_premultiplied(premul, xs, ys, cc.BORDER_CLAMP))
    inner = (slice(4, size - 4), slice(4, size - 4))

    assert cc.use_fast_gradient(1.0), "半径1pxは4タップ版のはず"
    original = cc.FAST_GRADIENT_MAX_RADIUS
    try:
        for channel in (cc.CH_R, cc.CH_G, cc.CH_B, cc.CH_LUMA, cc.CH_ONE):
            fallback = cc.select_channel(center, channel)

            cc.FAST_GRADIENT_MAX_RADIUS = 1.0
            fast = cc.channel_gradient(premul, xs, ys, cc.BORDER_CLAMP, channel, fallback, 1.0)
            cc.FAST_GRADIENT_MAX_RADIUS = 0.0  # 8タップ版を強制する
            slow = cc.channel_gradient(premul, xs, ys, cc.BORDER_CLAMP, channel, fallback, 1.0)

            for f, sl, axis in zip(fast, slow, "xy"):
                assert np.allclose(f[inner], sl[inner], atol=1e-5), \
                    (channel, axis, np.abs(f[inner] - sl[inner]).max())
    finally:
        cc.FAST_GRADIENT_MAX_RADIUS = original


def test_wide_radius_keeps_the_eight_tap_gradient():
    """検出半径を広げたら8タップ版に戻ること。

    2x2の平均ではタップを広げたぶんの平滑化が足りず、目に見えてざらつく。
    """
    assert not cc.use_fast_gradient(cc.FAST_GRADIENT_MAX_RADIUS + 0.5)
    assert "FastGradientMaxRadius" in HLSL
    assert HLSL.count("edgeRadius <= FastGradientMaxRadius") == 2, \
        "共有の勾配と歩行中の勾配の両方で切り替える"
    assert "if (len <= GradientEpsilon)" in HLSL, "止まった画素の打ち切りが無い"


def test_flow_stops_where_there_is_no_gradient():
    """勾配が無い場所は1歩も動かないので、残りのステップを打ち切ってよい。

    向きが決まらない画素は移動量が0になり、位置が変わらない以上
    次に取り直す勾配も同じ値になる。HLSL側はここでループを抜けている。
    打ち切りが結果を変えないことは、歩数を変えても絵が変わらないことで確かめられる。
    """
    flat = solid(24, 24, (0.3, 0.6, 0.9))
    for steps in (1, 8, 32):
        out = cc.apply(flat, cc.CrossChromaParams(intensity=40, steps=steps))
        assert np.allclose(out, flat, atol=1e-6), (steps, np.abs(out - flat).max())

    # 平坦な部分を含む絵でも、歩数を増やした結果がそこだけ変わらないこと
    img = solid(32, 32, (0.2, 0.2, 0.2))
    img[:, 16:, cc.CH_G] = 1.0          # 右半分に輪郭
    flat_area = (slice(None), slice(0, 12))
    few = cc.apply(img, cc.CrossChromaParams(intensity=20, steps=2))
    many = cc.apply(img, cc.CrossChromaParams(intensity=20, steps=32))
    assert np.allclose(few[flat_area], many[flat_area], atol=1e-6)


# ---------------------------------------------------------------------------
# 実装間の整合性 (HLSL / C# / Python)
# ---------------------------------------------------------------------------

def _hlsl_constant_buffer_fields():
    body = re.search(r"cbuffer constants[^{]*\{(.*?)\};", HLSL, re.S)
    assert body, "cbuffer constants が見つからない"
    return re.findall(r"float\s+(\w+)\s*:\s*packoffset\(c(\d+)\.([xyzw])\)", body.group(1))


def _cs_constant_buffer_fields():
    body = re.search(r"struct ConstantBuffer\s*\{(.*?)\n\s*\}", CUSTOM_EFFECT_CS, re.S)
    assert body, "struct ConstantBuffer が見つからない"
    return re.findall(r"public float (\w+);", body.group(1))


def test_constant_buffer_layout_matches():
    hlsl_fields = _hlsl_constant_buffer_fields()
    cs_fields = _cs_constant_buffer_fields()

    assert len(hlsl_fields) == len(cs_fields), (len(hlsl_fields), len(cs_fields))
    assert len(hlsl_fields) % 4 == 0, "定数バッファは16バイト境界に揃える"

    components = "xyzw"
    for i, ((name, reg, comp), cs_name) in enumerate(zip(hlsl_fields, cs_fields)):
        assert int(reg) == i // 4 and comp == components[i % 4], \
            f"{name} の packoffset が並び順とずれている"
        assert name.lower() == cs_name.lower(), f"{i}番目: HLSL={name} C#={cs_name}"


def test_property_ids_match_parameter_order():
    body = re.search(r"public enum Properties\s*\{(.*?)\}", CUSTOM_EFFECT_CS, re.S)
    assert body
    enum_names = [
        line.split("=")[0].strip().rstrip(",").strip()
        for line in body.group(1).strip().splitlines()
        if line.strip() and not line.strip().startswith("//")
    ]
    enum_names = [n.rstrip(",") for n in enum_names if n]

    param_names = re.findall(r"public float (\w+) \{ get; init; \}", PARAMETERS_CS)
    assert enum_names == param_names, (enum_names, param_names)

    # SetParameters が全プロパティを同じ順番で書き込んでいるか
    calls = re.findall(
        r"SetValue\(\(int\)EffectImpl\.Properties\.(\w+), p\.(\w+)\);", CUSTOM_EFFECT_CS)
    assert [a for a, _ in calls] == enum_names, [a for a, _ in calls]
    assert all(a == b for a, b in calls), calls

    # 定数バッファの先頭が、そのままプロパティの並びになっている
    cs_fields = _cs_constant_buffer_fields()
    reserved = [f for f in cs_fields if f.startswith("Reserved")]
    assert [f for f in cs_fields if not f.startswith("Reserved")] == enum_names
    assert len(reserved) == len(cs_fields) - len(enum_names)


def test_property_attributes_cover_every_property():
    ids = re.findall(r"\[CustomEffectProperty\(PropertyType\.Float, \(int\)Properties\.(\w+)\)\]",
                     CUSTOM_EFFECT_CS)
    param_names = re.findall(r"public float (\w+) \{ get; init; \}", PARAMETERS_CS)
    assert ids == param_names, (ids, param_names)


def _cs_channel_values():
    body = re.search(r"enum CrossChromaChannel\s*\{(.*?)\n\}", ROUTING_CS, re.S)
    assert body
    return {name: int(value) for name, value in re.findall(r"(\w+) = (\d+),", body.group(1))}


def test_channel_indices_match_python():
    values = _cs_channel_values()
    assert values == {
        "Red": cc.CH_R,
        "Green": cc.CH_G,
        "Blue": cc.CH_B,
        "Luminance": cc.CH_LUMA,
        "None": cc.CH_ONE,
    }, values


def test_sobel_and_offsets_match_python():
    def floats(name):
        body = re.search(rf"static const float {name}\[9\] = \{{([^}}]*)\}};", HLSL)
        assert body, name
        return [float(v) for v in body.group(1).replace("\n", "").split(",") if v.strip()]

    assert floats("SobelX") == cc.SOBEL_X
    assert floats("SobelY") == cc.SOBEL_Y

    body = re.search(r"static const float2 Offsets\[9\] =\s*\{(.*?)\};", HLSL, re.S)
    assert body
    offsets = [(float(x), float(y)) for x, y in
               re.findall(r"float2\(\s*(-?\d+),\s*(-?\d+)\)", body.group(1))]
    assert offsets == [(float(x), float(y)) for x, y in cc.OFFSETS]


def test_gradient_constants_match_python():
    """4タップ版のタップ位置と、切り替え/打ち切りのしきい値が3実装で揃っているか。"""
    body = re.search(r"static const float2 Diagonals\[4\] =\s*\{(.*?)\};", HLSL, re.S)
    assert body, "Diagonals が見つからない"
    diagonals = [(float(x), float(y)) for x, y in
                 re.findall(r"float2\(\s*(-?[\d.]+)f?,\s*(-?[\d.]+)f?\)", body.group(1))]
    assert diagonals == [(float(x), float(y)) for x, y in cc.DIAGONALS], diagonals

    for name, value in (("FastGradientMaxRadius", cc.FAST_GRADIENT_MAX_RADIUS),
                        ("GradientEpsilon", cc.GRADIENT_EPSILON)):
        found = re.search(rf"static const float {name} = ([\d.e-]+)f;", HLSL)
        assert found, name
        assert float(found.group(1)) == value, (name, found.group(1), value)


def test_luma_weights_match_python():
    body = re.search(r"LumaWeights = float3\(([^)]*)\)", HLSL)
    assert body
    weights = [float(v.strip().rstrip("f")) for v in body.group(1).split(",")]
    assert np.allclose(weights, cc.LUMA_WEIGHTS), weights


def test_routing_table_matches_python():
    values = _cs_channel_values()
    names = {
        "Forward": "forward",
        "Backward": "backward",
        "SwapRedGreen": "swap_rg",
        "SwapGreenBlue": "swap_gb",
        "SwapBlueRed": "swap_br",
        "Luminance": "luma",
    }
    found = re.findall(
        r"ChannelRouting\.(\w+) => new\(CrossChromaChannel\.(\w+), "
        r"CrossChromaChannel\.(\w+), CrossChromaChannel\.(\w+)\)", ROUTING_CS)
    assert len(found) == len(names), found

    for routing, r, g, b in found:
        key = names[routing]
        actual = (values[r], values[g], values[b])
        assert actual == cc.ROUTING[key], (routing, actual, cc.ROUTING[key])


def test_remaining_channel_rule():
    # 順回転 R←G なら、残りはB
    assert cc.remaining_channels(cc.ROUTING["forward"]) == (cc.CH_B, cc.CH_R, cc.CH_G)
    assert cc.remaining_channels(cc.ROUTING["backward"]) == (cc.CH_G, cc.CH_B, cc.CH_R)
    # 3つ目が決まらない場合は輝度
    assert cc.remaining_channels((cc.CH_R, cc.CH_G, cc.CH_B)) == (cc.CH_LUMA,) * 3


def test_step_count_is_wired_from_the_ui():
    """UIのステップ数がシェーダーまで届いているか。"""
    assert re.search(r"public Animation Steps \{ get; \} = new Animation\(", EFFECT_CS)

    animatables = re.search(r"GetAnimatables\(\) =>\s*\[([^\]]*)\]", EFFECT_CS)
    assert animatables, "GetAnimatables が見つからない"
    names = [n.strip() for n in animatables.group(1).split(",")]
    assert "Steps" in names, names

    assert re.search(r"StepCount = .*item\.Steps\.GetValue", PROCESSOR_CS), \
        "ステップ数がシェーダーのパラメーターに渡っていない"

    # UIの既定値とPython側の既定値を揃えておく(サンプル画像が実機と食い違わないように)
    default = re.search(r"public Animation Steps \{ get; \} = new Animation\((\d+),", EFFECT_CS)
    assert default, "Steps の既定値が読めない"
    assert int(default.group(1)) == cc.CrossChromaParams().steps, \
        (default.group(1), cc.CrossChromaParams().steps)


def test_iterations_is_handled_outside_the_shader():
    """反復はシェーダーではなく、エフェクトの多段接続で行う。"""
    assert not any("iteration" in name.lower() for name, _, _ in _hlsl_constant_buffer_fields())
    assert "Iterations" not in PARAMETERS_CS

    # 上限はエフェクト側の定数で一元管理する
    assert re.search(r"public const int MaxIterations = \d+;", EFFECT_CS)
    assert "CrossChromaEffect.MaxIterations" in PROCESSOR_CS

    # 前の段の出力を次の段の入力に繋いでいる
    assert "effectOutputs[i + 1]" in PROCESSOR_CS


def test_sweep_crop_matches_a_full_render():
    """スイープ画像の切り出しレンダーが、全画面レンダーと同じ絵になること。

    READMEのパラメーター実験は render_crop() で一部だけを計算している。
    余白の取りかたを間違えると、比較画像だけが実機と食い違うことになる。
    """
    import render_samples as rs
    from dataclasses import replace

    # ランダムノイズは使わない。輪郭が画素ごとにばらばらだと歩く経路が
    # 初期値のわずかな差で大きく散るので、余白の妥当性とは別の話になる。
    # 実際の絵と同じく、なめらかな濃淡と太い輪郭を持つ画像で見る。
    height, width = 90, 120
    ys, xs = np.mgrid[0:height, 0:width].astype(np.float32)
    source = np.zeros((height, width, 4), dtype=np.float32)
    source[..., 0] = 0.5 + 0.4 * np.sin(xs / 9.0) * np.cos(ys / 11.0)
    source[..., 1] = np.clip(np.sqrt((xs - 55) ** 2 + (ys - 45) ** 2) / 40.0, 0.0, 1.0)
    source[..., 2] = 0.25
    source[:, 30:38, 2] = 0.9          # 縦の帯
    source[50:58, :, 2] = 0.9          # 横の帯
    source[..., 3] = 1.0

    box = (40, 30, 80, 60)
    left, top, right, bottom = box

    for overrides in ({}, {"edge_radius": 4.0},
                      {"blur_strength": 1.0, "morph_strength": -0.5, "filter_radius": 3.0},
                      {"intensity": 8, "iterations": 3}):
        params = replace(rs.SWEEP_BASE, **overrides)
        full = cc.apply(source, params)[top:bottom, left:right, :3]
        cropped = np.asarray(rs.render_crop(source, params, box), dtype=np.float32) / 255.0
        # 8bitに落としてから比べる(書き出すのは画像なので、そこで一致していればよい)
        quantized = np.round(np.clip(full, 0.0, 1.0) * 255.0) / 255.0
        assert np.abs(quantized - cropped).max() < 1.5 / 255.0, \
            (overrides, float(np.abs(quantized - cropped).max()))


def test_sweep_labels_are_ascii():
    """比較シートのラベルは、日本語フォントの無い環境でも豆腐にならないこと。"""
    import render_samples as rs

    labels = [label for item in rs.SWEEPS for label, _ in item["variants"]]
    for label in labels:
        assert label.isascii(), label


# ---------------------------------------------------------------------------

def main() -> int:
    tests = [(name, fn) for name, fn in sorted(globals().items())
             if name.startswith("test_") and callable(fn)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  ok   {name}")
        except Exception:
            failed += 1
            print(f"  FAIL {name}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
