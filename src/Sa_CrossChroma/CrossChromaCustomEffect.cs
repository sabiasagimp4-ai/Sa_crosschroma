using System.Diagnostics;
using System.Runtime.InteropServices;
using Vortice;
using Vortice.Direct2D1;
using YukkuriMovieMaker.Commons;
using YukkuriMovieMaker.Player.Video;

namespace Sa_CrossChroma;

/// <summary>
/// CrossChroma.hlsl を ID2D1Effect として動かすためのラッパー。
/// </summary>
internal class CrossChromaCustomEffect : D2D1CustomShaderEffectBase
{
    public const string ShaderResourceName = "Sa_CrossChroma.Shaders.CrossChroma.cso";

    public CrossChromaCustomEffect(IGraphicsDevicesAndContext devices) : base(Create<EffectImpl>(devices))
    {
    }

    /// <summary>
    /// シェーダーに渡す値をまとめて更新する。
    /// </summary>
    public void SetParameters(in CrossChromaShaderParameters p)
    {
        SetValue((int)EffectImpl.Properties.Intensity, p.Intensity);
        SetValue((int)EffectImpl.Properties.AngleRad, p.AngleRad);
        SetValue((int)EffectImpl.Properties.EdgeRadius, p.EdgeRadius);
        SetValue((int)EffectImpl.Properties.EdgeGain, p.EdgeGain);
        SetValue((int)EffectImpl.Properties.EdgeGamma, p.EdgeGamma);
        SetValue((int)EffectImpl.Properties.BlurStrength, p.BlurStrength);
        SetValue((int)EffectImpl.Properties.MorphStrength, p.MorphStrength);
        SetValue((int)EffectImpl.Properties.FilterRadius, p.FilterRadius);
        SetValue((int)EffectImpl.Properties.BlendAmount, p.BlendAmount);
        SetValue((int)EffectImpl.Properties.ModInvert, p.ModInvert);
        SetValue((int)EffectImpl.Properties.FilterEnabled, p.FilterEnabled);
        SetValue((int)EffectImpl.Properties.DriverR, p.DriverR);
        SetValue((int)EffectImpl.Properties.DriverG, p.DriverG);
        SetValue((int)EffectImpl.Properties.DriverB, p.DriverB);
        SetValue((int)EffectImpl.Properties.ModR, p.ModR);
        SetValue((int)EffectImpl.Properties.ModG, p.ModG);
        SetValue((int)EffectImpl.Properties.ModB, p.ModB);
    }

    /// <summary>
    /// エフェクトの実装。inputCountは入力画像の数。
    /// </summary>
    [CustomEffect(1)]
    class EffectImpl : D2D1CustomShaderEffectImplBase<EffectImpl>
    {
        ConstantBuffer constantBuffer;

        public EffectImpl() : base(ShaderResourceLoader.GetShaderResource(ShaderResourceName))
        {
            // シェーダー側の既定値と合わせておく(プロパティは必ず上書きされる)
            constantBuffer.EdgeRadius = 1;
            constantBuffer.EdgeGain = 1;
            constantBuffer.EdgeGamma = 1;
            constantBuffer.FilterRadius = 2;
            constantBuffer.BlendAmount = 1;
        }

        [CustomEffectProperty(PropertyType.Float, (int)Properties.Intensity)]
        public float Intensity
        {
            get => constantBuffer.Intensity;
            set { constantBuffer.Intensity = value; UpdateConstants(); }
        }

        [CustomEffectProperty(PropertyType.Float, (int)Properties.AngleRad)]
        public float AngleRad
        {
            get => constantBuffer.AngleRad;
            set { constantBuffer.AngleRad = value; UpdateConstants(); }
        }

        [CustomEffectProperty(PropertyType.Float, (int)Properties.EdgeRadius)]
        public float EdgeRadius
        {
            get => constantBuffer.EdgeRadius;
            set { constantBuffer.EdgeRadius = value; UpdateConstants(); }
        }

        [CustomEffectProperty(PropertyType.Float, (int)Properties.EdgeGain)]
        public float EdgeGain
        {
            get => constantBuffer.EdgeGain;
            set { constantBuffer.EdgeGain = value; UpdateConstants(); }
        }

        [CustomEffectProperty(PropertyType.Float, (int)Properties.EdgeGamma)]
        public float EdgeGamma
        {
            get => constantBuffer.EdgeGamma;
            set { constantBuffer.EdgeGamma = value; UpdateConstants(); }
        }

        [CustomEffectProperty(PropertyType.Float, (int)Properties.BlurStrength)]
        public float BlurStrength
        {
            get => constantBuffer.BlurStrength;
            set { constantBuffer.BlurStrength = value; UpdateConstants(); }
        }

        [CustomEffectProperty(PropertyType.Float, (int)Properties.MorphStrength)]
        public float MorphStrength
        {
            get => constantBuffer.MorphStrength;
            set { constantBuffer.MorphStrength = value; UpdateConstants(); }
        }

        [CustomEffectProperty(PropertyType.Float, (int)Properties.FilterRadius)]
        public float FilterRadius
        {
            get => constantBuffer.FilterRadius;
            set { constantBuffer.FilterRadius = value; UpdateConstants(); }
        }

        [CustomEffectProperty(PropertyType.Float, (int)Properties.BlendAmount)]
        public float BlendAmount
        {
            get => constantBuffer.BlendAmount;
            set { constantBuffer.BlendAmount = value; UpdateConstants(); }
        }

        [CustomEffectProperty(PropertyType.Float, (int)Properties.ModInvert)]
        public float ModInvert
        {
            get => constantBuffer.ModInvert;
            set { constantBuffer.ModInvert = value; UpdateConstants(); }
        }

        [CustomEffectProperty(PropertyType.Float, (int)Properties.FilterEnabled)]
        public float FilterEnabled
        {
            get => constantBuffer.FilterEnabled;
            set { constantBuffer.FilterEnabled = value; UpdateConstants(); }
        }

        [CustomEffectProperty(PropertyType.Float, (int)Properties.DriverR)]
        public float DriverR
        {
            get => constantBuffer.DriverR;
            set { constantBuffer.DriverR = value; UpdateConstants(); }
        }

        [CustomEffectProperty(PropertyType.Float, (int)Properties.DriverG)]
        public float DriverG
        {
            get => constantBuffer.DriverG;
            set { constantBuffer.DriverG = value; UpdateConstants(); }
        }

        [CustomEffectProperty(PropertyType.Float, (int)Properties.DriverB)]
        public float DriverB
        {
            get => constantBuffer.DriverB;
            set { constantBuffer.DriverB = value; UpdateConstants(); }
        }

        [CustomEffectProperty(PropertyType.Float, (int)Properties.ModR)]
        public float ModR
        {
            get => constantBuffer.ModR;
            set { constantBuffer.ModR = value; UpdateConstants(); }
        }

        [CustomEffectProperty(PropertyType.Float, (int)Properties.ModG)]
        public float ModG
        {
            get => constantBuffer.ModG;
            set { constantBuffer.ModG = value; UpdateConstants(); }
        }

        [CustomEffectProperty(PropertyType.Float, (int)Properties.ModB)]
        public float ModB
        {
            get => constantBuffer.ModB;
            set { constantBuffer.ModB = value; UpdateConstants(); }
        }

        protected override void UpdateConstants()
        {
            if (drawInformation is null)
                return;

            SetLinearFiltering();
            drawInformation.SetPixelShaderConstantBuffer(constantBuffer);
        }

        /// <summary>
        /// 変位量は整数pxとは限らないので、入力を線形補間でサンプリングする。
        /// D2Dの既定はポイントサンプリングで、そのままだと変位がガタつく。
        /// </summary>
        void SetLinearFiltering()
        {
            if (drawInformation is null || linearFilteringFailed)
                return;

            try
            {
                drawInformation.SetInputDescription(0, new InputDescription(Filter.MinMagMipLinear, 0));
            }
            catch (Exception e)
            {
                // 失敗してもポイントサンプリングで描画は続けられる
                linearFilteringFailed = true;
                Debug.WriteLine($"[Sa_CrossChroma] 線形補間の設定に失敗しました: {e}");
            }
        }
        bool linearFilteringFailed;

        /// <summary>
        /// 出力範囲は入力範囲と同じ。
        /// アルファは入力画素のものをそのまま使うので、絵が元の範囲からはみ出すことはない。
        /// </summary>
        public override void MapInputRectsToOutputRect(RawRect[] inputRects, RawRect[] inputOpaqueSubRects, out RawRect outputRect, out RawRect outputOpaqueSubRect)
        {
            outputRect = inputRects[0];
            outputOpaqueSubRect = inputOpaqueSubRects[0];
        }

        /// <summary>
        /// 1画素の計算には、変位先とその周囲のぼかし半径、さらに輪郭検出の半径が必要になる。
        /// </summary>
        public override void MapOutputRectToInputRects(RawRect outputRect, RawRect[] inputRects)
        {
            inputRects[0] = Expand(outputRect, GetMargin());
        }

        int GetMargin()
        {
            var reach = Math.Abs(constantBuffer.Intensity) + Math.Abs(constantBuffer.EdgeRadius);
            if (constantBuffer.FilterEnabled > 0.5f)
                reach += Math.Abs(constantBuffer.FilterRadius);

            if (float.IsNaN(reach) || float.IsInfinity(reach))
                return 1;

            return (int)Math.Ceiling(Math.Min(reach, 4096f)) + 1;
        }

        /// <summary>矩形を広げる。無限大の矩形が渡されることがあるので桁あふれに注意する。</summary>
        static RawRect Expand(RawRect rect, int margin)
        {
            static int Offset(int value, long delta)
                => (int)Math.Clamp(value + delta, int.MinValue, int.MaxValue);

            return new RawRect(
                Offset(rect.Left, -margin),
                Offset(rect.Top, -margin),
                Offset(rect.Right, margin),
                Offset(rect.Bottom, margin));
        }

        /// <summary>
        /// シェーダーに渡すバッファ。CrossChroma.hlsl の cbuffer と並びを一致させること。
        /// </summary>
        [StructLayout(LayoutKind.Sequential)]
        struct ConstantBuffer
        {
            public float Intensity;
            public float AngleRad;
            public float EdgeRadius;
            public float EdgeGain;

            public float EdgeGamma;
            public float BlurStrength;
            public float MorphStrength;
            public float FilterRadius;

            public float BlendAmount;
            public float ModInvert;
            public float FilterEnabled;
            public float Reserved0;

            public float DriverR;
            public float DriverG;
            public float DriverB;
            public float Reserved1;

            public float ModR;
            public float ModG;
            public float ModB;
            public float Reserved2;
        }

        public enum Properties
        {
            Intensity = 0,
            AngleRad,
            EdgeRadius,
            EdgeGain,
            EdgeGamma,
            BlurStrength,
            MorphStrength,
            FilterRadius,
            BlendAmount,
            ModInvert,
            FilterEnabled,
            DriverR,
            DriverG,
            DriverB,
            ModR,
            ModG,
            ModB,
        }
    }
}
