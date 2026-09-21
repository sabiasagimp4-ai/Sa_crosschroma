using System.ComponentModel;
using System.ComponentModel.DataAnnotations;
using YukkuriMovieMaker.Commons;
using YukkuriMovieMaker.Controls;
using YukkuriMovieMaker.Exo;
using YukkuriMovieMaker.Player.Video;
using YukkuriMovieMaker.Plugin.Effects;

namespace Sa_CrossChroma;

/// <summary>
/// RGBを分離し、各チャンネルを別チャンネルの情報で変形して再合成する映像エフェクト。
/// 普通の色収差が「RGBを別々にずらす」のに対して、こちらは色同士が互いを変形させる。
/// </summary>
[VideoEffect("Sa_crosschroma", ["加工"], ["Sa_crosschroma", "sa_crosschroma", "crosschroma", "クロスクロマ", "色収差", "chromatic", "aberration", "RGB"])]
public class CrossChromaEffect : VideoEffectBase
{
    public override string Label => "Sa_crosschroma";

    /// <summary>反復回数の上限。増やすほどパス数がそのまま増えるので、常識的な範囲で止めておく。</summary>
    public const int MaxIterations = 8;

    // ------------------------------------------------------------------
    // 変位
    // ------------------------------------------------------------------

    [Display(GroupName = "変位", Name = "強度", Description = "他チャンネルの輪郭に沿って色をずらす量")]
    [AnimationSlider("F1", "px", 0, 100)]
    public Animation Intensity { get; } = new Animation(20, 0, 2000);

    [Display(GroupName = "変位", Name = "角度", Description = "0°で輪郭を横切る方向、90°で輪郭に沿う方向に色が流れます")]
    [AnimationSlider("F1", "°", -180, 180)]
    public Animation Angle { get; } = new Animation(90, -36000, 36000);

    [Display(GroupName = "変位", Name = "ステップ数",
        Description = "変位を何回に分けて進めるか。1歩ごとに進んだ先の輪郭を見直すので、増やすほど輪郭に沿った滑らかな曲線を描きます。移動量そのものは変わりません")]
    [AnimationSlider("F0", "", 1, 32)]
    public Animation Steps { get; } = new Animation(8, 1, 64);

    [Display(GroupName = "変位", Name = "組み合わせ", Description = "どのチャンネルをどのチャンネルの輪郭で変形させるか")]
    [EnumComboBox]
    public ChannelRouting Routing { get => routing; set => Set(ref routing, value); }
    ChannelRouting routing = ChannelRouting.Forward;

    [Display(GroupName = "変位", Name = "R ← ", Description = "組み合わせが「カスタム」のとき、Rを変形させるチャンネル")]
    [EnumComboBox]
    public CrossChromaChannel CustomDriverRed { get => customDriverRed; set => Set(ref customDriverRed, value); }
    CrossChromaChannel customDriverRed = CrossChromaChannel.Green;

    [Display(GroupName = "変位", Name = "G ← ", Description = "組み合わせが「カスタム」のとき、Gを変形させるチャンネル")]
    [EnumComboBox]
    public CrossChromaChannel CustomDriverGreen { get => customDriverGreen; set => Set(ref customDriverGreen, value); }
    CrossChromaChannel customDriverGreen = CrossChromaChannel.Blue;

    [Display(GroupName = "変位", Name = "B ← ", Description = "組み合わせが「カスタム」のとき、Bを変形させるチャンネル")]
    [EnumComboBox]
    public CrossChromaChannel CustomDriverBlue { get => customDriverBlue; set => Set(ref customDriverBlue, value); }
    CrossChromaChannel customDriverBlue = CrossChromaChannel.Red;

    // ------------------------------------------------------------------
    // 輪郭
    // ------------------------------------------------------------------

    [Display(GroupName = "輪郭", Name = "検出半径", Description = "輪郭を調べる幅。大きくするとゆるやかな濃淡にも反応します")]
    [AnimationSlider("F1", "px", 0.5, 16)]
    public Animation EdgeRadius { get; } = new Animation(1, 0.1, 64);

    [Display(GroupName = "輪郭", Name = "感度", Description = "弱い輪郭をどれだけ拾うか。大きいほど平坦な部分も動きます")]
    [AnimationSlider("F0", "%", 0, 400)]
    public Animation EdgeGain { get; } = new Animation(100, 0, 2000);

    [Display(GroupName = "輪郭", Name = "ガンマ", Description = "小さくすると弱い輪郭も強く、大きくすると強い輪郭だけが動きます")]
    [TextBoxSlider("F2", "", 0.1, 4)]
    [DefaultValue(1d)]
    [Range(0.05, 10)]
    public double EdgeGamma { get => edgeGamma; set => Set(ref edgeGamma, value); }
    double edgeGamma = 1;

    // ------------------------------------------------------------------
    // 変調 (他チャンネルの明るさでぼかし・膨張・収縮を制御)
    // ------------------------------------------------------------------

    [Display(GroupName = "変調", Name = "制御チャンネル", Description = "ぼかし・膨張・収縮の強さを決めるチャンネル")]
    [EnumComboBox]
    public ModulationSource Modulation { get => modulation; set => Set(ref modulation, value); }
    ModulationSource modulation = ModulationSource.Remaining;

    [Display(GroupName = "変調", Name = "R ← ", Description = "制御チャンネルが「カスタム」のとき、Rの強さを決めるチャンネル")]
    [EnumComboBox]
    public CrossChromaChannel CustomModulationRed { get => customModulationRed; set => Set(ref customModulationRed, value); }
    CrossChromaChannel customModulationRed = CrossChromaChannel.Blue;

    [Display(GroupName = "変調", Name = "G ← ", Description = "制御チャンネルが「カスタム」のとき、Gの強さを決めるチャンネル")]
    [EnumComboBox]
    public CrossChromaChannel CustomModulationGreen { get => customModulationGreen; set => Set(ref customModulationGreen, value); }
    CrossChromaChannel customModulationGreen = CrossChromaChannel.Red;

    [Display(GroupName = "変調", Name = "B ← ", Description = "制御チャンネルが「カスタム」のとき、Bの強さを決めるチャンネル")]
    [EnumComboBox]
    public CrossChromaChannel CustomModulationBlue { get => customModulationBlue; set => Set(ref customModulationBlue, value); }
    CrossChromaChannel customModulationBlue = CrossChromaChannel.Green;

    [Display(GroupName = "変調", Name = "明暗反転", Description = "制御チャンネルの明るい所と暗い所を入れ替えます")]
    [ToggleSlider]
    public bool InvertModulation { get => invertModulation; set => Set(ref invertModulation, value); }
    bool invertModulation = false;

    [Display(GroupName = "変調", Name = "ぼかし", Description = "制御チャンネルが明るいほど強くぼかします")]
    [AnimationSlider("F0", "%", 0, 100)]
    public Animation Blur { get; } = new Animation(0, 0, 400);

    [Display(GroupName = "変調", Name = "膨張 / 収縮", Description = "プラスで明るい部分が広がり、マイナスで痩せます")]
    [AnimationSlider("F0", "%", -100, 100)]
    public Animation Morphology { get; } = new Animation(0, -100, 100);

    [Display(GroupName = "変調", Name = "半径", Description = "ぼかし・膨張・収縮の半径")]
    [AnimationSlider("F1", "px", 0, 16)]
    public Animation FilterRadius { get; } = new Animation(2, 0, 64);

    // ------------------------------------------------------------------
    // 仕上げ
    // ------------------------------------------------------------------

    [Display(GroupName = "仕上げ", Name = "反復回数",
        Description = "エフェクト全体を繰り返す回数。変形した結果をもう一度変形するので、効果が積み重なって崩れていきます。ステップ数と違って移動量も増えます")]
    [TextBoxSlider("F0", "回", 1, MaxIterations)]
    [DefaultValue(1)]
    [Range(1, MaxIterations)]
    public int Iterations { get => iterations; set => Set(ref iterations, value); }
    int iterations = 1;

    [Display(GroupName = "仕上げ", Name = "適用量", Description = "元の映像とのブレンド量。反復回数が2以上のときは1回ごとに適用されます")]
    [AnimationSlider("F0", "%", 0, 100)]
    public Animation Mix { get; } = new Animation(100, 0, 100);

    /// <summary>R/G/Bをそれぞれ変形させるチャンネル。</summary>
    public ChannelAssignment GetDrivers() =>
        ChannelRoutingHelper.GetDrivers(Routing, new(CustomDriverRed, CustomDriverGreen, CustomDriverBlue));

    /// <summary>R/G/Bそれぞれの変調に使うチャンネル。</summary>
    public ChannelAssignment GetModulationChannels() =>
        ChannelRoutingHelper.GetModulation(
            Modulation,
            GetDrivers(),
            new(CustomModulationRed, CustomModulationGreen, CustomModulationBlue));

    /// <summary>
    /// AviUtlに相当するフィルタが無いため、exo出力はしない。
    /// </summary>
    public override IEnumerable<string> CreateExoVideoFilters(int keyFrameIndex, ExoOutputDescription exoOutputDescription) => [];

    public override IVideoEffectProcessor CreateVideoEffect(IGraphicsDevicesAndContext devices)
        => new CrossChromaProcessor(devices, this);

    protected override IEnumerable<IAnimatable> GetAnimatables() =>
        [Intensity, Angle, Steps, EdgeRadius, EdgeGain, Blur, Morphology, FilterRadius, Mix];
}
