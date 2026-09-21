# Sa_crosschroma

ゆっくりMovieMaker4（YMM4）用の映像エフェクトプラグインです。

RGBチャンネルを別々にずらす一般的な色収差とは異なり、各チャンネルの輪郭や明るさを使って他のチャンネルを変形します。色が輪郭に沿って流れるような表現や、にじみ・変形した色収差を作れます。

## 主な機能

- R・G・Bを互いの輪郭に沿って変位
- 輪郭を横切る方向と、輪郭に沿う方向を切り替え
- ぼかし・膨張・収縮をチャンネルごとに適用
- RGBの組み合わせ、輝度、カスタム指定に対応
- ステップ数と反復回数で、滑らかさや変形の重なりを調整
- 強度、検出半径、感度、ガンマ、適用量を調整
- 各パラメータをアニメーション可能


## ギャラリー

代表的な設定例です。

| 輪郭に沿って流す | ぼかし・膨張 | 強い変形 |
|---|---|---|
| [![](docs/samples/01-flow.jpg)](docs/samples/01-flow.jpg) | [![](docs/samples/03-morphology.jpg)](docs/samples/03-morphology.jpg) | [![](docs/samples/07-full.jpg)](docs/samples/07-full.jpg) |

## インストール

[Releaseページ](https://github.com/sabiasagimp4-ai/Sa_crosschroma/releases/latest)から `Sa_crosschroma.ymme` をダウンロードし、YMM4で開いてください。

映像アイテムの

`エフェクトを追加` → `加工` → `Sa_crosschroma`

から使用できます。

## もっと詳しく

- [設定ごとの比較と実験結果](docs/parameters.md) — [プリセット例](docs/parameters.md#プリセット例)と、各パラメーターを1項目ずつ振って測った結果
- [実装の話](docs/internals.md) — 処理の流れ、リポジトリ構成、動作確認について
