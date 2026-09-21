"""Sa_CrossChroma のCPUリファレンス実装。

`src/Sa_CrossChroma/Shaders/CrossChroma.hlsl` と同じ計算を numpy で再現したもの。
シェーダーを書き換えたらこちらも合わせて更新し、`test_crosschroma.py` で検証する。

画素の扱いはシェーダーに合わせてある:
  * D2Dから渡ってくる画像は乗算済みアルファなので、サンプリングは乗算済みで行い、
    タップごとに非乗算へ戻してから色として扱う。
  * 完全に透明なタップには色の情報が無いため、中心画素の値で代用する。
  * 出力アルファは入力の中心画素のアルファをそのまま使う。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

# チャンネル指定子。シェーダー側の driver / modulation の値と一致させること。
CH_R = 0
CH_G = 1
CH_B = 2
CH_LUMA = 3
CH_ONE = 4

LUMA_WEIGHTS = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)

# 3x3 のタップ位置 (dx, dy)。テクスチャ座標系なので +y は下方向。
OFFSETS = [(-1, -1), (0, -1), (1, -1), (-1, 0), (0, 0), (1, 0), (-1, 1), (0, 1), (1, 1)]

# Sobel。0.25倍して正規化するので、0→1のステップエッジで長さ1.0になる。
SOBEL_X = [-1.0, 0.0, 1.0, -2.0, 0.0, 2.0, -1.0, 0.0, 1.0]
SOBEL_Y = [-1.0, -2.0, -1.0, 0.0, 0.0, 0.0, 1.0, 2.0, 1.0]

BORDER_CLAMP = "clamp"
BORDER_TRANSPARENT = "transparent"

EPS = 1e-6


@dataclass
class CrossChromaParams:
    """エフェクトのパラメーター。単位はYMM4のUIと同じ。"""

    intensity: float = 20.0          # 変位量 (px)
    angle_deg: float = 90.0          # 勾配ベクトルの回転角 (度)。90で輪郭に沿う
    steps: int = 4                   # 変位を何歩に分けて進めるか (多いほど滑らか)
    iterations: int = 1              # エフェクト全体を繰り返す回数
    edge_radius: float = 1.0         # 輪郭検出の半径 (px)
    edge_gain: float = 1.0           # 輪郭の感度
    edge_gamma: float = 1.0          # 輪郭のガンマ
    blur_strength: float = 0.0       # ぼかし量 (0-1+)
    morph_strength: float = 0.0      # 正:膨張 / 負:収縮 (-1-1)
    filter_radius: float = 2.0       # ぼかし・膨張・収縮の半径 (px)
    mix: float = 1.0                 # 元画像とのブレンド (0-1)
    driver: tuple = (CH_G, CH_B, CH_R)       # R,G,B を変形させるチャンネル
    modulation: tuple = (CH_B, CH_R, CH_G)   # R,G,B の変調に使うチャンネル
    mod_invert: bool = False         # 変調チャンネルの明暗を反転
    border: str = BORDER_CLAMP       # 画像外の扱い

    @property
    def filter_enabled(self) -> bool:
        return self.blur_strength > 0.0 or self.morph_strength != 0.0


# ---------------------------------------------------------------------------
# サンプリング (GPUのバイリニアサンプラー相当)
# ---------------------------------------------------------------------------

def _fetch(premul: np.ndarray, xi: np.ndarray, yi: np.ndarray, border: str) -> np.ndarray:
    h, w = premul.shape[:2]
    texel = premul[np.clip(yi, 0, h - 1), np.clip(xi, 0, w - 1)]
    if border == BORDER_TRANSPARENT:
        inside = (xi >= 0) & (xi < w) & (yi >= 0) & (yi < h)
        texel = texel * inside[..., None]
    return texel


def sample_premultiplied(premul: np.ndarray, x: np.ndarray, y: np.ndarray, border: str) -> np.ndarray:
    """乗算済みRGBAをバイリニア補間で取得する。整数座標がテクセル中心。"""
    x0 = np.floor(x)
    y0 = np.floor(y)
    fx = (x - x0)[..., None].astype(np.float32)
    fy = (y - y0)[..., None].astype(np.float32)
    x0i = x0.astype(np.int64)
    y0i = y0.astype(np.int64)

    c00 = _fetch(premul, x0i, y0i, border)
    c10 = _fetch(premul, x0i + 1, y0i, border)
    c01 = _fetch(premul, x0i, y0i + 1, border)
    c11 = _fetch(premul, x0i + 1, y0i + 1, border)

    top = c00 * (1.0 - fx) + c10 * fx
    bottom = c01 * (1.0 - fx) + c11 * fx
    return top * (1.0 - fy) + bottom * fy


def premultiply(straight: np.ndarray) -> np.ndarray:
    out = straight.astype(np.float32).copy()
    out[..., :3] *= out[..., 3:4]
    return out


def unpremultiply(premul: np.ndarray) -> np.ndarray:
    """HLSLのSampleStraight相当。透明画素のRGBは0になる。"""
    alpha = premul[..., 3:4]
    rgb = np.where(alpha > EPS, premul[..., :3] / np.maximum(alpha, EPS), 0.0)
    return np.concatenate([rgb, alpha], axis=-1).astype(np.float32)


def select_channel(straight: np.ndarray, index: int) -> np.ndarray:
    """HLSLのSelectChannel相当。0:R 1:G 2:B 3:輝度 4:定数1.0"""
    if index >= CH_ONE:
        return np.ones(straight.shape[:-1], dtype=np.float32)
    if index == CH_LUMA:
        return straight[..., :3] @ LUMA_WEIGHTS
    return straight[..., index]


def signals(straight: np.ndarray) -> np.ndarray:
    """HLSLのSignals相当。RGBと輝度をまとめた4成分。"""
    luma = (straight[..., :3] @ LUMA_WEIGHTS)[..., None]
    return np.concatenate([straight[..., :3], luma], axis=-1).astype(np.float32)


def select_gradient(gradient: np.ndarray, index: int) -> np.ndarray:
    """HLSLのSelectGradient相当。定数チャンネルには勾配が無いので0。"""
    if index >= CH_ONE:
        return np.zeros(gradient.shape[:-1], dtype=np.float32)
    return gradient[..., index]


def sample_signals(premul, x, y, border, fallback: np.ndarray) -> np.ndarray:
    """HLSLのSampleSignals相当。透明なタップは中心画素の値で代用する。"""
    c = sample_premultiplied(premul, x, y, border)
    valid = (c[..., 3:4] > EPS)
    return np.where(valid, signals(unpremultiply(c)), fallback)


def sample_channel(premul, x, y, border, channel: int, fallback: np.ndarray) -> np.ndarray:
    """HLSLのSampleChannel相当。透明なタップは中心画素の値で代用する。"""
    c = sample_premultiplied(premul, x, y, border)
    valid = c[..., 3] > EPS
    return np.where(valid, select_channel(unpremultiply(c), channel), fallback)


def channel_gradient(premul, x, y, border, channel: int, fallback, edge_radius: float):
    """HLSLのChannelGradient相当。任意の位置で1チャンネル分のSobel勾配を求める。

    mainの勾配計算は1組のタップからR/G/B/輝度をまとめて出すが、
    歩きながら勾配を取り直すときは必要な1チャンネルだけで足りる。
    """
    gx = np.zeros(np.shape(x), dtype=np.float32)
    gy = np.zeros(np.shape(x), dtype=np.float32)
    for i, (ox, oy) in enumerate(OFFSETS):
        if SOBEL_X[i] == 0.0 and SOBEL_Y[i] == 0.0:
            continue
        tap = sample_channel(
            premul, x + ox * edge_radius, y + oy * edge_radius, border, channel, fallback)
        if SOBEL_X[i] != 0.0:
            gx += SOBEL_X[i] * tap
        if SOBEL_Y[i] != 0.0:
            gy += SOBEL_Y[i] * tap
    return gx * 0.25, gy * 0.25


# ---------------------------------------------------------------------------
# 本体 (CrossChroma.hlsl の main / ProcessChannel と対応)
# ---------------------------------------------------------------------------

def apply(src_straight: np.ndarray, p: CrossChromaParams) -> np.ndarray:
    """非乗算RGBA float32 (H,W,4) を受け取り、同じ形式で返す。

    iterations を増やすと、変形した結果をもう一度入力に戻して繰り返す。
    C#側では同じエフェクトを数珠つなぎにすることで同じことをしている。
    """
    out = np.ascontiguousarray(src_straight, dtype=np.float32)
    for _ in range(max(int(p.iterations), 1)):
        out = apply_once(out, p)
    return out


def apply_once(src_straight: np.ndarray, p: CrossChromaParams) -> np.ndarray:
    """1パスぶん。CrossChroma.hlsl の main 1回に対応する。"""
    src_straight = np.ascontiguousarray(src_straight, dtype=np.float32)
    h, w = src_straight.shape[:2]
    premul = premultiply(src_straight)

    xs, ys = np.meshgrid(
        np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32)
    )

    center = unpremultiply(sample_premultiplied(premul, xs, ys, p.border))
    center_signals = signals(center)

    # --- 1. 1組のタップからR/G/B/輝度すべての勾配を求める --------------------
    grad_x = np.zeros((h, w, 4), dtype=np.float32)
    grad_y = np.zeros((h, w, 4), dtype=np.float32)
    for i, (ox, oy) in enumerate(OFFSETS):
        if SOBEL_X[i] == 0.0 and SOBEL_Y[i] == 0.0:
            continue
        tap = sample_signals(
            premul,
            xs + ox * p.edge_radius,
            ys + oy * p.edge_radius,
            p.border,
            center_signals,
        )
        if SOBEL_X[i] != 0.0:
            grad_x += SOBEL_X[i] * tap
        if SOBEL_Y[i] != 0.0:
            grad_y += SOBEL_Y[i] * tap
    grad_x *= 0.25
    grad_y *= 0.25

    theta = math.radians(p.angle_deg)
    sin_t = math.sin(theta)
    cos_t = math.cos(theta)

    processed = np.zeros((h, w, 3), dtype=np.float32)

    steps = int(np.clip(int(p.steps), 1, 64))
    # 合計の移動量は変えず、steps回に分けて進む
    step_scale = p.intensity / steps

    # --- 2. チャンネルごとに、別チャンネルの輪郭で変位させる -------------------
    for c in (0, 1, 2):
        center_value = select_channel(center, c)
        driver_value = select_channel(center, p.driver[c])

        dx = xs.copy()
        dy = ys.copy()
        # 1歩目の勾配は上で計算済みのものを使い回す
        gx = select_gradient(grad_x, p.driver[c])
        gy = select_gradient(grad_y, p.driver[c])

        for s in range(steps):
            # 2歩目以降は、進んだ先の勾配を取り直す。
            # 勾配が消えた場所では amount が0になるので、流れは自然に止まる。
            if s > 0:
                gx, gy = channel_gradient(
                    premul, dx, dy, p.border, p.driver[c], driver_value, p.edge_radius)

            length = np.sqrt(gx * gx + gy * gy)
            inv_len = np.where(length > 1e-5, 1.0 / np.maximum(length, 1e-5), 0.0)
            dir_x = gx * inv_len
            dir_y = gy * inv_len

            amount = np.clip(length * p.edge_gain, 0.0, 1.0) ** p.edge_gamma

            # 勾配ベクトルを回転する。90度で輪郭に沿う方向になる。
            rot_x = dir_x * cos_t - dir_y * sin_t
            rot_y = dir_x * sin_t + dir_y * cos_t

            dx = dx + rot_x * (amount * step_scale)
            dy = dy + rot_y * (amount * step_scale)

        value = sample_channel(premul, dx, dy, p.border, c, center_value)

        # --- 3. 他チャンネルの明るさでぼかし・膨張・収縮を制御 -----------------
        if p.filter_enabled:
            taps = np.stack([
                sample_channel(
                    premul,
                    dx + ox * p.filter_radius,
                    dy + oy * p.filter_radius,
                    p.border,
                    c,
                    center_value,
                )
                for ox, oy in OFFSETS
            ])
            blurred = taps.mean(axis=0)
            dilated = taps.max(axis=0)
            eroded = taps.min(axis=0)

            m = select_channel(center, p.modulation[c])
            if p.mod_invert:
                m = 1.0 - m

            value = value + (blurred - value) * np.clip(p.blur_strength * m, 0.0, 1.0)
            value = value + (dilated - value) * np.clip(p.morph_strength * m, 0.0, 1.0)
            value = value + (eroded - value) * np.clip(-p.morph_strength * m, 0.0, 1.0)

        processed[..., c] = value

    rgb = np.clip(center[..., :3] + (processed - center[..., :3]) * p.mix, 0.0, 1.0)

    alpha = center[..., 3:4]
    out = np.concatenate([rgb, alpha], axis=-1).astype(np.float32)
    out[..., :3] = np.where(alpha > 0.0, out[..., :3], 0.0)
    return out


# ---------------------------------------------------------------------------
# ルーティング (C#側の ChannelRouting / ModulationSource と対応)
# ---------------------------------------------------------------------------

ROUTING = {
    "forward": (CH_G, CH_B, CH_R),   # R←G, G←B, B←R
    "backward": (CH_B, CH_R, CH_G),  # R←B, G←R, B←G
    "swap_rg": (CH_G, CH_R, CH_B),
    "swap_gb": (CH_R, CH_B, CH_G),
    "swap_br": (CH_B, CH_G, CH_R),
    "luma": (CH_LUMA, CH_LUMA, CH_LUMA),
}


def remaining_channels(driver: tuple) -> tuple:
    """自分でもドライバーでもない、残りのチャンネルを返す。"""
    out = []
    for c in (0, 1, 2):
        rest = [x for x in (0, 1, 2) if x != c and x != driver[c]]
        out.append(rest[0] if len(rest) == 1 else CH_LUMA)
    return tuple(out)
