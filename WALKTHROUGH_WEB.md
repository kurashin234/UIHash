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
**出力:** `output_web/web_xxx/` フォルダ（切り出された画像と `classify.txt` が含まれます）

## 3. ハッシュ生成 (Hash)
最終的なUIHashベクトルを生成します。
**注意:** Web版ではクラス数が固定（0〜7の8クラス）のため、`--num_classes 8` を指定し、第2引数にはダミーのパス（`dummy`など）を指定します。

```bash
# ハッシュの生成
python hasher/uihash.py output_web dummy --output_path output_web/hash --num_classes 8
```
**出力:** `output_web/hash/hash_5x5x30.npy` (ベクトルデータ), `output_web/hash/name_5x5x30.npy` (ファイル名リスト)

## コードベースの主な変更点
- **`collect/web_crawler.py`**: Seleniumベースのクローラー（新規作成）。
- **`hasher/extract_view_images.py`**: `--web` フラグを追加し、JSON入力と画面ごとの出力構造に対応。
- **`hasher/reclass_web.py`**: タグベースの分類ツール（新規作成）。
- **`hasher/uihash.py`**: `.json` ファイルのサポート、ディレクトリ以外のアイテムを無視、`--num_classes` オプションの追加。
- **`hasher/xml2nodes.py`**: `XMLReader` を更新し、Rico形式のJSONをパースできるように変更。
- **`hasher/nodes2hash.py`**: `.png` 画像のサポートと、`classify.txt` の柔軟な配置に対応。
