using System.Diagnostics;
using Vortice.Direct2D1;
using YukkuriMovieMaker.Commons;
using YukkuriMovieMaker.Player.Video;

namespace Sa_CrossChroma;

internal class CrossChromaProcessor : IVideoEffectProcessor
{
    readonly CrossChromaEffect item;
    readonly CrossChromaCustomEffect? effect;
    readonly ID2D1Image? output;

    ID2D1Image? input;
    CrossChromaShaderParameters previous;
    bool isFirst = true;

    /// <summary>エフェクトの出力画像。シェーダーを使えない場合は入力をそのまま返す。</summary>
    public ID2D1Image Output => output ?? input ?? throw new NullReferenceException();

    public CrossChromaProcessor(IGraphicsDevicesAndContext devices, CrossChromaEffect item)
    {
        this.item = item;

        try
        {
            effect = new CrossChromaCustomEffect(devices);
        }
        catch (Exception e)
        {
            // シェーダーを読み込めない場合は素通しにする
            Debug.WriteLine($"[Sa_CrossChroma] シェーダーの読み込みに失敗しました: {e}");
            effect = null;
        }

        if (effect is null)
            return;

        if (!effect.IsEnabled)
        {
            // GPUの性能によってエフェクトの読み込みに失敗することがある
            effect.Dispose();
            effect = null;
            return;
        }

        // EffectからgetしたOutputは必ずDisposeする必要がある。Effect内部では開放されない。
        output = effect.Output;
    }

    public void SetInput(ID2D1Image? input)
    {
        this.input = input;
        effect?.SetInput(0, input, true);
    }

    public void ClearInput()
    {
        effect?.SetInput(0, null, true);
    }

    public DrawDescription Update(EffectDescription effectDescription)
    {
        if (effect is null)
            return effectDescription.DrawDescription;

        var frame = effectDescription.ItemPosition.Frame;
        var length = effectDescription.ItemDuration.Frame;
        var fps = effectDescription.FPS;

        var parameters = CreateParameters(frame, length, fps);
        if (isFirst || parameters != previous)
        {
            effect.SetParameters(parameters);
            previous = parameters;
            isFirst = false;
        }

        return effectDescription.DrawDescription;
    }

    CrossChromaShaderParameters CreateParameters(int frame, int length, int fps)
    {
        var drivers = item.GetDrivers();
        var modulation = item.GetModulationChannels();

        var blur = (float)(item.Blur.GetValue(frame, length, fps) / 100d);
        var morphology = (float)(item.Morphology.GetValue(frame, length, fps) / 100d);
        var filterRadius = (float)item.FilterRadius.GetValue(frame, length, fps);

        // ぼかしも膨張・収縮も使わないなら、9タップ分のサンプリングを丸ごと省く
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
        output?.Dispose();
        // Inputは必ずnullに戻す。
        effect?.SetInput(0, null, true);
        effect?.Dispose();
    }
}
