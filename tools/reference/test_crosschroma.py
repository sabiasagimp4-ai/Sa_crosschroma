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
    assert diff.max() > 0.05, "Gの輪郭でRが動いていない"
    # エッジから十分離れた場所は動かない
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
        intensity=8, angle_deg=0, driver=(cc.CH_R,) * 3, edge_radius=1.0))

    row = out[h // 2, :, cc.CH_R]
    src = img[h // 2, :, cc.CH_R]
    # 検出半径1pxなので、エッジの1px手前だけが明るい側から色を拾う
    assert src[w // 2 - 1] == 0.0 and row[w // 2 - 1] == 1.0
    assert row[w // 2 - 2] == 0.0


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
