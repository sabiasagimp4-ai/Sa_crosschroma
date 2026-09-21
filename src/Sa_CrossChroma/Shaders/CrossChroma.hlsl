// Sa_CrossChroma
// RGBを分離し、各チャンネルを「別チャンネルの輪郭」で変形して再合成するピクセルシェーダー。
//
// 1. 1組の3x3タップからR/G/B/輝度すべてのSobel勾配を求める
// 2. チャンネルごとに、割り当てられたドライバーチャンネルの勾配を回転させた方向へ変位させる。
//    このとき stepCount 回に分けて少しずつ進み、1歩ごとに進んだ先で勾配を取り直す。
//    移動の合計量は変えずに経路だけが直線から曲線になるので、輪郭に沿った流れが滑らかになる。
// 3. 変位先で、別チャンネルの明るさに応じてぼかし / 膨張 / 収縮をかける
// 4. 元画像とブレンドして出力する
//
// 定数バッファの並びは CrossChromaCustomEffect.ConstantBuffer と
// tools/reference/crosschroma.py に一致させること。

Texture2D InputTexture : register(t0);
SamplerState InputSampler : register(s0);

cbuffer constants : register(b0)
{
    float intensity     : packoffset(c0.x); // 変位量(px)
    float angleRad      : packoffset(c0.y); // 勾配の回転角(ラジアン)
    float edgeRadius    : packoffset(c0.z); // 輪郭検出半径(px)
    float edgeGain      : packoffset(c0.w); // 輪郭の感度

    float edgeGamma     : packoffset(c1.x); // 輪郭のガンマ
    float blurStrength  : packoffset(c1.y); // ぼかし量
    float morphStrength : packoffset(c1.z); // 正:膨張 負:収縮
    float filterRadius  : packoffset(c1.w); // ぼかし・膨張・収縮の半径(px)

    float blendAmount   : packoffset(c2.x); // 元画像とのブレンド
    float modInvert     : packoffset(c2.y); // 変調チャンネルの反転
    float filterEnabled : packoffset(c2.z); // ぼかし・膨張・収縮を使うか
    float stepCount     : packoffset(c2.w); // 変位を何回に分けて進めるか

    float driverR       : packoffset(c3.x); // Rを変形させるチャンネル
    float driverG       : packoffset(c3.y);
    float driverB       : packoffset(c3.z);
    float reserved1     : packoffset(c3.w);

    float modR          : packoffset(c4.x); // Rの変調に使うチャンネル
    float modG          : packoffset(c4.y);
    float modB          : packoffset(c4.z);
    float reserved2     : packoffset(c4.w);
};

static const float3 LumaWeights = float3(0.2126f, 0.7152f, 0.0722f);

static const float2 Offsets[9] =
{
    float2(-1, -1), float2(0, -1), float2(1, -1),
    float2(-1,  0), float2(0,  0), float2(1,  0),
    float2(-1,  1), float2(0,  1), float2(1,  1)
};
static const float SobelX[9] = { -1, 0, 1, -2, 0, 2, -1, 0, 1 };
static const float SobelY[9] = { -1, -2, -1, 0, 0, 0, 1, 2, 1 };

// 3x3 Sobelは、バイリニア補間を使うと4タップで計算できる。
// (±0.5, ±0.5)のタップは2x2の平均になるので、展開すると
//   gx = (右上 + 右下) - (左上 + 左下)
//   gy = (左下 + 右下) - (左上 + 右上)
// がちょうど Sobel/4 のカーネルと一致する。
static const float2 Diagonals[4] =
{
    float2(-0.5f, -0.5f), float2(0.5f, -0.5f),
    float2(-0.5f,  0.5f), float2(0.5f,  0.5f)
};

// 4タップ版が使える検出半径の上限。
// 2x2の平均は1テクセル分の幅しか無いので、タップを広げると平滑化が足りずにざらつく。
// 半径1pxなら、画素の中心で見るかぎり8タップ版と一致する(切り替えても絵は飛ばない)。
// 歩いている途中の半端な位置では、タップの広がりが±0.5テクセルぶん狭いので
// 輪郭の効く範囲がわずかに狭くなるが、実写でもイラストでも見た目の差は出ない。
static const float FastGradientMaxRadius = 1.0f;

// 勾配がこれ以下だと向きが決まらないので、その画素は1歩も動かない。
// 動かなければ位置も変わらず、次に取り直す勾配も同じ値になる。
// つまり残りのステップは何も起こさないので、丸ごと省ける。平坦な塗りが多い絵ほど効く。
static const float GradientEpsilon = 1e-5f;

// 0:R 1:G 2:B 3:輝度 4:定数1.0
float SelectChannel(float4 straight, int index)
{
    if (index >= 4)
        return 1.0f;
    if (index == 0)
        return straight.r;
    if (index == 1)
        return straight.g;
    if (index == 2)
        return straight.b;
    return dot(straight.rgb, LumaWeights);
}

// 勾配の4成分(R,G,B,輝度)から1つ選ぶ。定数チャンネルには勾配が無いので0を返す。
float SelectGradient(float4 gradient, int index)
{
    if (index >= 4)
        return 0.0f;
    if (index == 0)
        return gradient.r;
    if (index == 1)
        return gradient.g;
    if (index == 2)
        return gradient.b;
    return gradient.a;
}

// RGBと輝度をまとめた4成分を作る
float4 Signals(float4 straight)
{
    return float4(straight.rgb, dot(straight.rgb, LumaWeights));
}

// D2Dの入力は乗算済みアルファなので、非乗算に戻してから色として扱う。
float4 SampleStraight(float2 uv)
{
    float4 c = InputTexture.SampleLevel(InputSampler, uv, 0);
    float3 rgb = c.a > 1e-6f ? c.rgb / c.a : float3(0, 0, 0);
    return float4(rgb, c.a);
}

// 完全に透明な場所には色の情報が無い。
// 黒として扱うと輪郭の外側に偽の輪郭が出てしまうので、中心画素の値で代用する。
float4 SampleSignals(float2 uv, float4 fallback)
{
    float4 c = InputTexture.SampleLevel(InputSampler, uv, 0);
    if (c.a <= 1e-6f)
        return fallback;
    return Signals(float4(c.rgb / c.a, c.a));
}

float SampleChannel(float2 uv, int channel, float fallback)
{
    float4 c = InputTexture.SampleLevel(InputSampler, uv, 0);
    if (c.a <= 1e-6f)
        return fallback;
    return SelectChannel(float4(c.rgb / c.a, c.a), channel);
}

// R/G/B/輝度の勾配を1組のタップからまとめて求める。
void SignalGradient(float2 pos, float2 texel, float4 fallback, out float4 gradX, out float4 gradY)
{
    // edgeRadiusは画面全体で同じ値なので、この分岐は画素ごとにばらけない
    if (edgeRadius <= FastGradientMaxRadius)
    {
        float4 a = SampleSignals(pos + Diagonals[0] * edgeRadius * texel, fallback);
        float4 b = SampleSignals(pos + Diagonals[1] * edgeRadius * texel, fallback);
        float4 c = SampleSignals(pos + Diagonals[2] * edgeRadius * texel, fallback);
        float4 d = SampleSignals(pos + Diagonals[3] * edgeRadius * texel, fallback);
        gradX = (b + d) - (a + c);
        gradY = (c + d) - (a + b);
        return;
    }

    gradX = 0;
    gradY = 0;

    [unroll]
    for (int i = 0; i < 9; i++)
    {
        if (SobelX[i] == 0.0f && SobelY[i] == 0.0f)
            continue;

        float4 tap = SampleSignals(pos + Offsets[i] * edgeRadius * texel, fallback);
        gradX += SobelX[i] * tap;
        gradY += SobelY[i] * tap;
    }

    gradX *= 0.25f;
    gradY *= 0.25f;
}

// 任意の位置で、1チャンネル分の勾配を求める。
// 1歩進むごとにその場所の勾配を取り直すために使う。
// SignalGradientとは違い、必要な1チャンネルだけを見る。
float2 ChannelGradient(float2 pos, float2 texel, int channel, float fallback)
{
    if (edgeRadius <= FastGradientMaxRadius)
    {
        float a = SampleChannel(pos + Diagonals[0] * edgeRadius * texel, channel, fallback);
        float b = SampleChannel(pos + Diagonals[1] * edgeRadius * texel, channel, fallback);
        float c = SampleChannel(pos + Diagonals[2] * edgeRadius * texel, channel, fallback);
        float d = SampleChannel(pos + Diagonals[3] * edgeRadius * texel, channel, fallback);
        return float2((b + d) - (a + c), (c + d) - (a + b));
    }

    float2 gradient = float2(0, 0);

    [unroll]
    for (int i = 0; i < 9; i++)
    {
        if (SobelX[i] == 0.0f && SobelY[i] == 0.0f)
            continue;

        float tap = SampleChannel(pos + Offsets[i] * edgeRadius * texel, channel, fallback);
        gradient += float2(SobelX[i], SobelY[i]) * tap;
    }

    return gradient * 0.25f;
}

// 1チャンネル分の処理
float ProcessChannel(
    float2 uv,
    float2 texel,
    float4 center,
    float4 gradX,
    float4 gradY,
    float2 sinCos,
    int steps,
    int channel,
    int driverIndex,
    int modIndex)
{
    float centerValue = SelectChannel(center, channel);
    float driverValue = SelectChannel(center, driverIndex);

    // 合計の移動量は変えず、steps回に分けて進む
    float stepScale = intensity / steps;

    float2 displaced = uv;
    // 1歩目の勾配はmainで計算済みのものを使い回す
    float2 gradient = float2(
        SelectGradient(gradX, driverIndex),
        SelectGradient(gradY, driverIndex));

    [loop]
    for (int s = 0; s < steps; s++)
    {
        // 2歩目以降は、進んだ先の勾配を取り直す。
        // 輪郭が消えた場所では勾配が無くなるので、流れは自然に止まる。
        if (s > 0)
            gradient = ChannelGradient(displaced, texel, driverIndex, driverValue);

        float len = sqrt(gradient.x * gradient.x + gradient.y * gradient.y);

        // 向きが決まらない = もう動かない。残りのステップごと省く。
        if (len <= GradientEpsilon)
            break;

        float2 dir = gradient / len;
        float amount = pow(saturate(len * edgeGain), edgeGamma);

        // 勾配ベクトルを回転する。90度で輪郭に沿う方向になる。
        float2 rotated = float2(
            dir.x * sinCos.y - dir.y * sinCos.x,
            dir.x * sinCos.x + dir.y * sinCos.y);

        displaced += rotated * (amount * stepScale) * texel;
    }

    float value = SampleChannel(displaced, channel, centerValue);

    if (filterEnabled > 0.5f)
    {
        // 中心のタップは変位先の値そのものなので、取り直さず value を使う
        float blurred = value;
        float dilated = value;
        float eroded = value;

        [unroll]
        for (int i = 0; i < 9; i++)
        {
            if (i == 4)
                continue;

            float tap = SampleChannel(
                displaced + Offsets[i] * filterRadius * texel, channel, centerValue);
            blurred += tap;
            dilated = max(dilated, tap);
            eroded = min(eroded, tap);
        }
        blurred /= 9.0f;

        float m = SelectChannel(center, modIndex);
        m = modInvert > 0.5f ? 1.0f - m : m;

        value = lerp(value, blurred, saturate(blurStrength * m));
        value = lerp(value, dilated, saturate(morphStrength * m));
        value = lerp(value, eroded, saturate(-morphStrength * m));
    }

    return value;
}

float4 main(
    float4 pos : SV_POSITION,
    float4 posScene : SCENE_POSITION,
    float4 uv0 : TEXCOORD0
) : SV_Target
{
    float2 uv = uv0.xy;

    // 入力テクスチャの1テクセル分のサイズ。
    // 出力画素と入力テクセルは1:1で対応するので、uvの画面空間微分がそのままテクセルサイズになる。
    // uv0.zwにも同じ値が入るが、そちらに依存しなくて済むよう微分を優先して使う。
    float2 derivative = float2(abs(ddx(uv0.x)), abs(ddy(uv0.y)));
    float2 texel = (derivative.x > 0.0f && derivative.y > 0.0f) ? derivative : uv0.zw;

    float4 center = SampleStraight(uv);
    if (center.a <= 0.0f)
        return float4(0, 0, 0, 0);

    // 1組のタップからR/G/B/輝度すべての勾配を求める
    float4 centerSignals = Signals(center);
    float4 gradX;
    float4 gradY;
    SignalGradient(uv, texel, centerSignals, gradX, gradY);

    float2 sinCos = float2(sin(angleRad), cos(angleRad));
    int steps = clamp((int)stepCount, 1, 64);

    float3 processed;
    processed.r = ProcessChannel(uv, texel, center, gradX, gradY, sinCos, steps, 0, (int)driverR, (int)modR);
    processed.g = ProcessChannel(uv, texel, center, gradX, gradY, sinCos, steps, 1, (int)driverG, (int)modG);
    processed.b = ProcessChannel(uv, texel, center, gradX, gradY, sinCos, steps, 2, (int)driverB, (int)modB);

    float3 rgb = saturate(lerp(center.rgb, processed, blendAmount));

    // 乗算済みアルファに戻す
    return float4(rgb * center.a, center.a);
}
