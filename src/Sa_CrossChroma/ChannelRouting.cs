using System.ComponentModel.DataAnnotations;

namespace Sa_CrossChroma;

/// <summary>
/// 変形や変調に使うチャンネル。
/// 値はシェーダーの SelectChannel / SelectGradient と一致させること。
/// </summary>
public enum CrossChromaChannel
{
    [Display(Name = "R", Description = "赤")]
    Red = 0,

    [Display(Name = "G", Description = "緑")]
    Green = 1,

    [Display(Name = "B", Description = "青")]
    Blue = 2,

    [Display(Name = "輝度", Description = "RGB全体の明るさ")]
    Luminance = 3,

    [Display(Name = "なし", Description = "常に最大値として扱う")]
    None = 4,
}

/// <summary>
/// どのチャンネルをどのチャンネルの輪郭で変形させるか。
/// </summary>
public enum ChannelRouting
{
    [Display(Name = "順回転 R←G←B←R", Description = "RをGの輪郭で、GをBの輪郭で、BをRの輪郭で変形します")]
    Forward,

    [Display(Name = "逆回転 R←B←G←R", Description = "RをBの輪郭で、GをRの輪郭で、BをGの輪郭で変形します")]
    Backward,

    [Display(Name = "R⇔G 交換", Description = "RとGを互いの輪郭で変形します")]
    SwapRedGreen,

    [Display(Name = "G⇔B 交換", Description = "GとBを互いの輪郭で変形します")]
    SwapGreenBlue,

    [Display(Name = "B⇔R 交換", Description = "BとRを互いの輪郭で変形します")]
    SwapBlueRed,

    [Display(Name = "輝度", Description = "すべてのチャンネルを輝度の輪郭で変形します")]
    Luminance,

    [Display(Name = "カスタム", Description = "チャンネルごとに個別に指定します")]
    Custom,
}

/// <summary>
/// ぼかし / 膨張 / 収縮の強さを制御するチャンネルの決め方。
/// </summary>
public enum ModulationSource
{
    [Display(Name = "残りのチャンネル", Description = "自分でも変形元でもない、3つ目のチャンネルの明るさで制御します")]
    Remaining,

    [Display(Name = "変形元と同じ", Description = "変形に使ったチャンネルの明るさで制御します")]
    Driver,

    [Display(Name = "自分自身", Description = "そのチャンネル自身の明るさで制御します")]
    Self,

    [Display(Name = "輝度", Description = "画像全体の輝度で制御します")]
    Luminance,

    [Display(Name = "制御しない", Description = "常に最大の強さでかけます")]
    None,

    [Display(Name = "カスタム", Description = "チャンネルごとに個別に指定します")]
    Custom,
}

/// <summary>R/G/Bそれぞれに割り当てるチャンネルの組。</summary>
/// <param name="Red">Rに割り当てるチャンネル</param>
/// <param name="Green">Gに割り当てるチャンネル</param>
/// <param name="Blue">Bに割り当てるチャンネル</param>
public readonly record struct ChannelAssignment(
    CrossChromaChannel Red,
    CrossChromaChannel Green,
    CrossChromaChannel Blue);

public static class ChannelRoutingHelper
{
    /// <summary>
    /// ルーティング設定から、R/G/Bをそれぞれ変形させるチャンネルを求める。
    /// </summary>
    public static ChannelAssignment GetDrivers(ChannelRouting routing, ChannelAssignment custom) => routing switch
    {
        // R←G, G←B, B←R
        ChannelRouting.Forward => new(CrossChromaChannel.Green, CrossChromaChannel.Blue, CrossChromaChannel.Red),
        // R←B, G←R, B←G
        ChannelRouting.Backward => new(CrossChromaChannel.Blue, CrossChromaChannel.Red, CrossChromaChannel.Green),
        ChannelRouting.SwapRedGreen => new(CrossChromaChannel.Green, CrossChromaChannel.Red, CrossChromaChannel.Blue),
        ChannelRouting.SwapGreenBlue => new(CrossChromaChannel.Red, CrossChromaChannel.Blue, CrossChromaChannel.Green),
        ChannelRouting.SwapBlueRed => new(CrossChromaChannel.Blue, CrossChromaChannel.Green, CrossChromaChannel.Red),
        ChannelRouting.Luminance => new(CrossChromaChannel.Luminance, CrossChromaChannel.Luminance, CrossChromaChannel.Luminance),
        _ => custom,
    };

    /// <summary>
    /// 変調設定から、R/G/Bそれぞれの強さを制御するチャンネルを求める。
    /// </summary>
    public static ChannelAssignment GetModulation(
        ModulationSource source,
        ChannelAssignment drivers,
        ChannelAssignment custom) => source switch
        {
            ModulationSource.Remaining => new(
                Remaining(0, drivers.Red),
                Remaining(1, drivers.Green),
                Remaining(2, drivers.Blue)),
            ModulationSource.Driver => drivers,
            ModulationSource.Self => new(CrossChromaChannel.Red, CrossChromaChannel.Green, CrossChromaChannel.Blue),
            ModulationSource.Luminance => new(CrossChromaChannel.Luminance, CrossChromaChannel.Luminance, CrossChromaChannel.Luminance),
            ModulationSource.None => new(CrossChromaChannel.None, CrossChromaChannel.None, CrossChromaChannel.None),
            _ => custom,
        };

    /// <summary>
    /// 自分でも変形元でもない、残りのチャンネルを返す。
    /// 決められない場合(変形元が自分自身や輝度の場合)は輝度を使う。
    /// </summary>
    static CrossChromaChannel Remaining(int self, CrossChromaChannel driver)
    {
        var found = CrossChromaChannel.Luminance;
        var count = 0;
        for (var i = 0; i < 3; i++)
        {
            if (i == self || i == (int)driver)
                continue;
            found = (CrossChromaChannel)i;
            count++;
        }
        return count == 1 ? found : CrossChromaChannel.Luminance;
    }
}
