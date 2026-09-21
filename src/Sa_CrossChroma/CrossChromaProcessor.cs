using System.Diagnostics;
using Vortice.Direct2D1;
using YukkuriMovieMaker.Commons;
using YukkuriMovieMaker.Player.Video;

namespace Sa_CrossChroma;

internal class CrossChromaProcessor : IVideoEffectProcessor
{
    readonly IGraphicsDevicesAndContext devices;
    readonly CrossChromaEffect item;

    // 反復回数のぶんだけエフェクトを数珠つなぎにする。
    // effects[0] を常に最終段にしておくと、反復回数が変わっても Output を差し替えずに済む。
    //   入力 → effects[n-1] → … → effects[1] → effects[0] → Output
    readonly List<CrossChromaCustomEffect> effects = [];
    // EffectからgetしたOutputは必ずDisposeする必要がある。Effect内部では開放されない。
    readonly List<ID2D1Image> effectOutputs = [];

    readonly ID2D1Image? output;

    ID2D1Image? input;
    int chainLength;
    bool shaderFailed;
    CrossChromaShaderParameters previous;
    bool isFirst = true;

    /// <summary>エフェクトの出力画像。シェーダーを使えない場合は入力をそのまま返す。</summary>
    public ID2D1Image Output => output ?? input ?? throw new NullReferenceException();

    public CrossChromaProcessor(IGraphicsDevicesAndContext devices, CrossChromaEffect item)
    {
        this.devices = devices;
        this.item = item;

        if (EnsureEffects(1) == 0)
            return;

        chainLength = 1;
        output = effectOutputs[0];
    }

    /// <summary>
    /// エフェクトが count 個になるまで作り足す。実際に用意できた数を返す。
    /// GPUの性能やシェーダーの読み込み失敗で作れないことがあるので、足りない場合はその数で妥協する。
    /// </summary>
    int EnsureEffects(int count)
    {
        while (effects.Count < count && !shaderFailed)
        {
            CrossChromaCustomEffect effect;
            try
            {
                effect = new CrossChromaCustomEffect(devices);
            }
            catch (Exception e)
            {
                Debug.WriteLine($"[Sa_CrossChroma] シェーダーの読み込みに失敗しました: {e}");
                shaderFailed = true;
                break;
            }

            if (!effect.IsEnabled)
            {
                // GPUの性能によってエフェクトの読み込みに失敗することがある
                effect.Dispose();
                shaderFailed = true;
                break;
            }

            effects.Add(effect);
            effectOutputs.Add(effect.Output);
        }

        return effects.Count;
    }

    /// <summary>入力から最終段まで繋ぎ直す。使っていない段の入力は外しておく。</summary>
    void ConnectChain(ID2D1Image? source)
    {
        for (var i = 0; i < effects.Count; i++)
        {
            if (i >= chainLength)
                effects[i].SetInput(0, null, true);
            else if (i + 1 < chainLength)
                effects[i].SetInput(0, effectOutputs[i + 1], true);
            else
                effects[i].SetInput(0, source, true);
        }
    }

    public void SetInput(ID2D1Image? input)
    {
        this.input = input;
        ConnectChain(input);
    }

    public void ClearInput()
    {
        ConnectChain(null);
    }

    public DrawDescription Update(EffectDescription effectDescription)
    {
        if (effects.Count == 0)
            return effectDescription.DrawDescription;

        var frame = effectDescription.ItemPosition.Frame;
        var length = effectDescription.ItemDuration.Frame;
        var fps = effectDescription.FPS;

        UpdateChainLength();

        var parameters = CreateParameters(frame, length, fps);
        if (isFirst || parameters != previous)
        {
            // 全段に同じ設定を渡す。使っていない段に入っていても描画には影響しない。
            foreach (var effect in effects)
                effect.SetParameters(parameters);

            previous = parameters;
            isFirst = false;
        }

        return effectDescription.DrawDescription;
    }

    /// <summary>反復回数に合わせて、繋ぐ段数を変える。</summary>
    void UpdateChainLength()
    {
        var before = effects.Count;
        var wanted = Math.Clamp(item.Iterations, 1, CrossChromaEffect.MaxIterations);
        var length = Math.Min(wanted, EnsureEffects(wanted));

        if (effects.Count != before)
        {
            // 作り足した段にはまだ設定が入っていない
            isFirst = true;
        }

        if (length == chainLength)
            return;

        chainLength = length;
        ConnectChain(input);
    }

    CrossChromaShaderParameters CreateParameters(int frame, int length, int fps)
    {
        var drivers = item.GetDrivers();
        var modulation = item.GetModulationChannels();

        var blur = (float)(item.Blur.GetValue(frame, length, fps) / 100d);
        var morphology = (float)(item.Morphology.GetValue(frame, length, fps) / 100d);
        var filterRadius = (float)item.FilterRadius.GetValue(frame, length, fps);

        // ぼかしも膨張・収縮も使わないなら、フィルタのサンプリング(24タップ)を丸ごと省く
        var useFilter = filterRadius > 0 && (blur > 0 || morphology != 0);

        return new CrossChromaShaderParameters
        {
            Intensity = (float)item.Intensity.GetValue(frame, length, fps),
            AngleRad = (float)(item.Angle.GetValue(frame, length, fps) * Math.PI / 180d),
            EdgeRadius = Math.Max((float)item.EdgeRadius.GetValue(frame, length, fps), 0.01f),
            EdgeGain = (float)(item.EdgeGain.GetValue(frame, length, fps) / 100d),
            EdgeGamma = Math.Max((float)item.EdgeGamma, 0.01f),
            BlurStrength = Math.Max(blur, 0f),
            MorphStrength = Math.Clamp(morphology, -1f, 1f),
            FilterRadius = filterRadius,
            BlendAmount = (float)(item.Mix.GetValue(frame, length, fps) / 100d),
            ModInvert = item.InvertModulation ? 1f : 0f,
            FilterEnabled = useFilter ? 1f : 0f,
            StepCount = Math.Clamp((float)Math.Round(item.Steps.GetValue(frame, length, fps)), 1f, 64f),
            DriverR = (int)drivers.Red,
            DriverG = (int)drivers.Green,
            DriverB = (int)drivers.Blue,
            ModR = (int)modulation.Red,
            ModG = (int)modulation.Green,
            ModB = (int)modulation.Blue,
        };
    }

    public void Dispose()
    {
        // EffectからgetしたOutputは必ずDisposeする必要がある。Effect内部では開放されない。
        foreach (var image in effectOutputs)
            image.Dispose();
        effectOutputs.Clear();

        foreach (var effect in effects)
        {
            // Inputは必ずnullに戻す。
            effect.SetInput(0, null, true);
            effect.Dispose();
        }
        effects.Clear();
    }
}
