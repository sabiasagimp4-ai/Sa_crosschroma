# Sa_CrossChroma

RGBを分離し、各チャンネルを **別チャンネルの輪郭** で変形してから再合成する、
ゆっくりMovieMaker4（YMM4）用の映像エフェクトプラグイン。

普通の色収差が「RGBを別々にずらす」だけなのに対して、これは **色同士が互いを変形させる色収差**。
Rの動き方はGの輪郭が決め、Gの動き方はBが決め、Bの動き方はRが決める、という循環になっている。

![before / after](docs/samples/comparison.jpg)

## できること

- **RをGの輪郭で変位**、**GをBの輪郭で変位**、**BをRの輪郭で変位**（循環的な相互作用）
- **勾配を90°回転**させて、輪郭を横切るのではなく **輪郭に沿って色を流す**
- **他チャンネルの明るさでBlur / 膨張 / 収縮を制御**する
- 変形元・制御元のチャンネルは、プリセットからもチャンネル単位のカスタムからも指定できる
- 変位量・角度・輪郭の検出半径などはすべてアニメーション可能

## サンプル

添付のテスト画像（`docs/samples/00-source.jpg`）に適用した結果。
すべて `tools/reference/render_samples.py` で生成している。

| | |
|---|---|
| **元画像**<br>![](docs/samples/00-source.jpg) | **01-flow** — 輪郭に沿って色を流す<br>`強度24px / 角度90° / 順回転 / 感度150%`<br>![](docs/samples/01-flow.jpg) |
| **02-displace** — 輪郭を横切る向きに変位<br>`強度16px / 角度0° / 順回転 / 感度150%`<br>![](docs/samples/02-displace.jpg) | **03-morphology** — 他チャンネルの明るさで膨張<br>`強度10px / 角度90° / 膨張100% / 半径4px`<br>![](docs/samples/03-morphology.jpg) |
| **04-blur** — 他チャンネルの明るさでぼかす<br>`強度12px / 角度90° / ぼかし100% / 半径3px`<br>![](docs/samples/04-blur.jpg) | **05-soft** — 広い濃淡に反応させる<br>`強度40px / 検出半径6px / 感度250% / ガンマ0.6`<br>![](docs/samples/05-soft.jpg) |
| **06-subtle** — 実用的な控えめの設定<br>`強度6px / 角度90° / 感度200% / 適用量60%`<br>![](docs/samples/06-subtle.jpg) | **07-full** — 変位・ぼかし・収縮を全部使う<br>`強度28px / 角度120° / 逆回転 / ぼかし60% / 収縮-60%`<br>![](docs/samples/07-full.jpg) |

## 仕組み

1ピクセルにつき、次の順で計算する（すべて1パスのピクセルシェーダー内）。

1. **勾配を求める**
   3x3のSobelフィルタを1組だけ回して、R / G / B / 輝度の4つの勾配 `(gx, gy)` を同時に得る。
   タップ位置は「検出半径」でスケールするので、半径を広げるとゆるやかな濃淡にも反応する。
   Sobelは1/4に正規化してあり、0→1のステップエッジで長さがちょうど1.0になる。

2. **変位ベクトルを作る**（チャンネルごと）
   自分に割り当てられたドライバーチャンネルの勾配を使う。

   ```
   dir    = normalize(gx, gy)                    // 輪郭に垂直な向き
   amount = pow(saturate(|g| * 感度), ガンマ)     // 輪郭の強さ 0-1
   変位   = rotate(dir, 角度) * amount * 強度     // 角度90°で輪郭に沿う向きになる
   ```

3. **変位先でサンプリングする**
   `自分のチャンネル` の値だけを変位先から拾う。アルファは動かさないので、
   絵のシルエットは元のまま保たれる。

4. **他チャンネルの明るさでフィルタする**
   変位先の周囲3x3（半径は可変）から平均・最大・最小を取り、
   制御チャンネルの明るさ `m` を重みにして混ぜる。

   ```
   value = lerp(value, 平均, ぼかし量 * m)    // Blur
   value = lerp(value, 最大, 膨張量 * m)      // Dilate
   value = lerp(value, 最小, 収縮量 * m)      // Erode
   ```

5. **元画像とブレンドして出力する**

透明な部分には色の情報が無いため、完全に透明なタップは中心画素の値で代用している。
黒として扱うとシルエットの外側に偽の輪郭が出てしまうため。

## パラメーター

### 変位

| 項目 | 既定値 | 説明 |
|---|---|---|
| 強度 | 20px | 輪郭に沿って色をずらす量 |
| 角度 | 90° | 0°で輪郭を横切る向き、90°で輪郭に沿う向き |
| 組み合わせ | 順回転 | `順回転 R←G←B←R` / `逆回転` / `R⇔G交換` / `G⇔B交換` / `B⇔R交換` / `輝度` / `カスタム` |
| R ← / G ← / B ← | G / B / R | 「カスタム」のとき、各チャンネルを変形させるチャンネル |

### 輪郭

| 項目 | 既定値 | 説明 |
|---|---|---|
| 検出半径 | 1px | 輪郭を調べる幅。広げるとゆるやかな濃淡にも反応する |
| 感度 | 100% | 弱い輪郭をどれだけ拾うか。上げるほど平坦な部分も動く |
| ガンマ | 1.00 | 小さくすると弱い輪郭も強く、大きくすると強い輪郭だけが動く |

### 変調（他チャンネルの明るさでBlur / 膨張 / 収縮を制御）

| 項目 | 既定値 | 説明 |
|---|---|---|
| 制御チャンネル | 残りのチャンネル | `残りのチャンネル`（自分でも変形元でもない3つ目） / `変形元と同じ` / `自分自身` / `輝度` / `制御しない` / `カスタム` |
| R ← / G ← / B ← | B / R / G | 「カスタム」のとき、各チャンネルの強さを決めるチャンネル |
| 明暗反転 | オフ | 制御チャンネルの明るい所と暗い所を入れ替える |
| ぼかし | 0% | 制御チャンネルが明るいほど強くぼかす |
| 膨張 / 収縮 | 0% | プラスで明るい部分が広がり、マイナスで痩せる |
| 半径 | 2px | ぼかし・膨張・収縮の半径 |

### 仕上げ

| 項目 | 既定値 | 説明 |
|---|---|---|
| 適用量 | 100% | 元の映像とのブレンド量 |

> ぼかしも膨張・収縮も0%のときは、シェーダー内でフィルタ処理ごとスキップされる（1画素あたり36タップ→12タップ）。
> 軽くしたい場合は変調を使わない設定にするとよい。

## インストール

1. [Releases](../../releases) から `.ymme` ファイルをダウンロードする（または自分でビルドする）
2. `.ymme` ファイルをダブルクリックする
3. YMM4を起動し、`設定` → `プラグイン` → `プラグイン一覧` に `Sa_CrossChroma` が出ていれば成功

手動で入れる場合は、`Sa_CrossChroma.dll` を `YMM4フォルダ\user\plugin\Sa_CrossChroma\` に置く。

使うときは、映像アイテムの `エフェクトを追加` → `加工` → `クロスクロマ`。

## ビルド

### 必要なもの

- YMM4 本体（v4.47.0.0以降 = .NET10版）
- Visual Studio 2022 以降、または .NET SDK
- Windows SDK（HLSLのコンパイルに `fxc.exe` を使う。Visual Studioの「C++によるデスクトップ開発」を入れると付いてくる）

### 手順

1. `Directory.Build.props.sample` をコピーして `Directory.Build.props` を作り、
   `YMM4DirPath` にYMM4のインストールフォルダを設定する（末尾の `\` を忘れずに）

   ```xml
   <YMM4DirPath>C:\Program Files\YMM4\</YMM4DirPath>
   ```

2. `Sa_CrossChroma.sln` を開いてビルドする（または `dotnet build -c Release`）

ビルド時に `Shaders\CrossChroma.hlsl` が `fxc.exe` で `ps_4_0` にコンパイルされ、
dllに埋め込まれる。ビルド後、dllは自動で `YMM4フォルダ\user\plugin\Sa_CrossChroma\` にコピーされる。

`fxc.exe` が自動で見つからない場合は、`Directory.Build.props` に `FxcPath` を直接書く。

> **v4.46.x.x以前のYMM4向けにビルドする場合**は、`src/Sa_CrossChroma/Sa_CrossChroma.csproj` の
> `<TargetFramework>` を `net8.0-windows` に変更する。

## リポジトリ構成

```
src/Sa_CrossChroma/
  CrossChromaEffect.cs            エフェクトの設定項目（YMM4のUIに出る部分）
  CrossChromaProcessor.cs         フレームごとの更新処理
  CrossChromaCustomEffect.cs      ID2D1Effectとしての実装・定数バッファ
  CrossChromaShaderParameters.cs  シェーダーに渡す値一式
  ChannelRouting.cs               チャンネルの組み合わせ
  ShaderResourceLoader.cs         埋め込みシェーダーの読み込み
  Shaders/CrossChroma.hlsl        本体（ピクセルシェーダー）

tools/reference/
  crosschroma.py                  HLSLと同じ計算のCPUリファレンス実装
  test_crosschroma.py             テスト
  render_samples.py               サンプル画像の生成

docs/samples/                     READMEに貼っているサンプル
```

## 開発

GPUを使うシェーダーはそのままではテストしづらいので、
`tools/reference/crosschroma.py` にHLSLと同じ計算のCPU実装を置いている。
アルゴリズムを変えるときは、シェーダーとこちらを両方更新する。

```bash
pip install numpy pillow

# テスト（アルゴリズムの振る舞い + 3実装の整合性チェック）
python3 tools/reference/test_crosschroma.py

# サンプル画像の生成
python3 tools/reference/render_samples.py docs/samples/00-source.jpg docs/samples
```

テストは振る舞いだけでなく、**HLSLの定数バッファ / C#の構造体 / プロパティID / Pythonの定数**が
同じ並び・同じ値になっているかも突き合わせる。
定数バッファは並び順がずれても無言で壊れるだけなので、ここで機械的に止めている。

## 動作確認について

- アルゴリズム（変位・回転・変調・アルファの扱い）は、CPUリファレンス実装に対する
  21件のテストと、上のサンプル画像のレンダリングで確認している
- HLSL / C# / Python の3実装が食い違っていないことは、テストで機械的に検証している
- **C#とHLSLの実ビルド、およびYMM4上での動作確認は、Windows + YMM4本体が必要なため未実施**。
  最初のビルド時はYMM4のバージョンとの整合（`TargetFramework`、参照DLL）を確認してほしい

## ライセンス

未設定。公開する場合は、リポジトリにライセンスファイルを追加すること。

`docs/samples/` の画像は、動作確認用に提供されたテスト画像とその加工結果。
リポジトリを公開する場合は、元画像の権利を確認して差し替えること。
