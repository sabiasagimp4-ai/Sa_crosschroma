namespace Sa_CrossChroma;

/// <summary>
/// シェーダーに渡す値一式。
/// 並び順は CrossChroma.hlsl の定数バッファと
/// CrossChromaCustomEffect.EffectImpl.Properties に一致させること。
/// </summary>
internal record struct CrossChromaShaderParameters
{
    /// <summary>変位量(px)</summary>
    public float Intensity { get; init; }

    /// <summary>勾配ベクトルの回転角(ラジアン)</summary>
    public float AngleRad { get; init; }

    /// <summary>輪郭検出の半径(px)</summary>
    public float EdgeRadius { get; init; }

    /// <summary>輪郭の感度(1.0で等倍)</summary>
    public float EdgeGain { get; init; }

    /// <summary>輪郭のガンマ</summary>
    public float EdgeGamma { get; init; }

    /// <summary>ぼかし量(0で無効)</summary>
    public float BlurStrength { get; init; }

    /// <summary>正で膨張、負で収縮</summary>
    public float MorphStrength { get; init; }

    /// <summary>ぼかし・膨張・収縮の半径(px)</summary>
    public float FilterRadius { get; init; }

    /// <summary>元画像とのブレンド量(0-1)</summary>
    public float BlendAmount { get; init; }

    /// <summary>変調チャンネルを反転するなら1</summary>
    public float ModInvert { get; init; }

    /// <summary>ぼかし・膨張・収縮を行うなら1</summary>
    public float FilterEnabled { get; init; }

    /// <summary>変位を何歩に分けて進めるか(1以上)</summary>
    public float StepCount { get; init; }

    /// <summary>Rを変形させるチャンネル</summary>
    public float DriverR { get; init; }

    /// <summary>Gを変形させるチャンネル</summary>
    public float DriverG { get; init; }

    /// <summary>Bを変形させるチャンネル</summary>
    public float DriverB { get; init; }

    /// <summary>Rの変調に使うチャンネル</summary>
    public float ModR { get; init; }

    /// <summary>Gの変調に使うチャンネル</summary>
    public float ModG { get; init; }

    /// <summary>Bの変調に使うチャンネル</summary>
    public float ModB { get; init; }
}
