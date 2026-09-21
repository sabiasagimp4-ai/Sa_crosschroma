using System.IO;
using System.Reflection;

namespace Sa_CrossChroma;

internal static class ShaderResourceLoader
{
    /// <summary>
    /// ビルド時にfxcでコンパイルし、埋め込んだシェーダーを読み込む。
    /// リソース名はSa_CrossChroma.csprojのLogicalNameで指定している。
    /// </summary>
    public static byte[] GetShaderResource(string name)
    {
        var assembly = Assembly.GetExecutingAssembly();
        using var stream = assembly.GetManifestResourceStream(name)
            ?? throw new FileNotFoundException($"シェーダー {name} が埋め込まれていません。");

        var bytes = new byte[stream.Length];
        stream.ReadExactly(bytes);
        return bytes;
    }
}
