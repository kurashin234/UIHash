# Web UIHash 実行ガイド

このドキュメントでは、新しく実装されたツールを使用してWebサイトからUIHashを生成する手順を説明します。

## 1. データ収集 (Collect)
Webページを巡回し、スクリーンショットとDOM構造（JSON）を保存します。

```bash
# 例: Wikipediaを巡回（最大10ページ）
python collect/web_crawler.py --output output_web --pages 10
```
**出力:** `output_web/*.png`, `output_web/*.json`

## 2. 抽出と分類 (Extract & Classify)
スクリーンショットからUI要素を切り出し、HTMLタグを使用して分類します。
**注意:** このステップで、ファイルは自動的に画面ごとのフォルダに整理され、`classify.txt` が生成されます。

```bash
# ステップ 2a: 画像の切り出しとフォルダ整理
python hasher/extract_view_images.py output_web --web

# ステップ 2b: 分類ラベルの生成（タグベース）
python hasher/reclass_web.py output_web
```
**出力:** `output_web/<domain>_<timestamp>/` フォルダ（切り出された画像と `classify.txt` が含まれます）
*注意: クローラーはURLごとに `output_web/www_google_com_12345/` のようなサブフォルダを作成します。以降の手順は `output_web` を指定すれば全サブフォルダを一括処理します。*

> [!NOTE]
> 自動抽出された要素画像の一部（特に文字）が見切れることがありますが、これはDOMの矩形計算（`getBoundingClientRect`）と実際のフォント描画領域の微細なズレによるもので、仕様上の動作です。
> ハッシュ生成（UIHash）は画像の色分布や大まかな形状に基づいているため、数ピクセルの文字欠けは類似度判定に大きな影響を与えません。

## 3. ハッシュ生成 (Hash)
最終的なUIHashベクトルを生成します。
**注意:** Web版ではクラス数が固定（0〜7の8クラス）のため、`--num_classes 8` を指定し、第2引数にはダミーのパス（`dummy`など）を指定します。

```bash
# ハッシュの生成
python hasher/uihash.py output_web dummy --output_path output_web/hash --num_classes 8
```
**出力:** `output_web/hash/hash_5x5x30.npy` (ベクトルデータ), `output_web/hash/name_5x5x30.npy` (ファイル名リスト)

## 4. 類似度比較 (Compare)
生成されたハッシュベクトルを使用して、Webページ間の類似度を計算します。

### シナリオ: 2つのURLを比較する
特定の2つのサイト（例: GoogleとBing）を比較したい場合の全手順です。

1. **データ収集**: 2つのURLを指定してクローラーを実行します。
```bash
python collect/web_crawler.py https://www.google.com https://www.bing.com --output output_web --pages 1
```

2. **抽出と分類**:
```bash
python hasher/extract_view_images.py output_web --web
python hasher/reclass_web.py output_web
```

3. **ハッシュ生成**:
```bash
python hasher/uihash.py output_web dummy --output_path output_web/hash --num_classes 8 --filter 0 --grid_size 5,10
```
*注意: `--filter 0` はノード数が少ないページも強制的に処理するために重要です。*
*ヒント: Webページは縦長のため、`--grid_size 5,10` (横5x縦10) のように縦の分割数を増やすと、より正確な特徴を捉えられる場合があります。*

4. **比較実行**:
```bash
python hasher/compare_hashes.py output_web/hash/hash_5x10x8.npy output_web/hash/name_5x10x8.npy --top 10 --threshold 0.1 --cross
```
*   `--cross`: 同一サイト内の比較を除外し、異なるサイト間の類似度のみを表示します。
*   これにより、類似度の高いペアがリストアップされます。特定のURLペアのスコアを確認したい場合は、出力リストを確認してください（現在は全ペアの総当たりからトップKを表示する仕様です）。

## コードベースの主な変更点
- **`collect/web_crawler.py`**: 複数のURL入力をサポートするように更新。
- **`hasher/compare_hashes.py`**: ハッシュベクトル間のコサイン類似度を計算するスクリプト（新規作成）。
- **`hasher/extract_view_images.py`**: `--web` フラグを追加し、JSON入力と画面ごとの出力構造に対応。
- **`hasher/reclass_web.py`**: タグベースの分類ツール（新規作成）。
- **`hasher/uihash.py`**: `.json` ファイルのサポート、ディレクトリ以外のアイテムを無視、`--num_classes` オプションの追加。
- **`hasher/xml2nodes.py`**: `XMLReader` を更新し、Rico形式のJSONをパースできるように変更。
- **`hasher/nodes2hash.py`**: `.png` 画像のサポートと、`classify.txt` の柔軟な配置に対応。
