UIHash
====================================================

グリッドベースの表現によるAndroidアプリの類似ユーザーインターフェース(UI)の検出。

引用
----
> Jiawei Li, Jian Mao, Jun Zeng, Qixiao Lin, Shaowen Feng, and Zhenkai Liang. UIHash: Detecting Similar Android UIs through Grid-Based Visual Appearance Representation. In USENIX Security Symposium, 2024.

新着: 代替バージョン
-------------------
ヘッドレスサーバーでより良く動作する別のUIHashバージョンである [UIHash-Serve](https://github.com/DaweiX/UIHash-Serve) も提案しています。
動的アプリテストにQEMUを使用し、類似性検索に [Faiss](https://github.com/facebookresearch/faiss) を使用しています。ぜひお試しください！

必要要件
------------

UIHashはPython3.7で開発され、Python3.7.4およびPython3.7.9でテストされています。

実装に必要な重要なパッケージは以下の通りです：

* numpy~=1.19.3
* matplotlib~=3.5.1
* pandas~=1.3.5
* torch>=1.2.0
* bokeh~=2.3.3
* umap~=0.1.1
* opencv-python~=4.5.5.64
* torchvision~=0.4.0
* progressbar~=2.5
* Pillow~=7.1.2
* seaborn~=0.11.2
* scipy~=1.7.3
* sklearn~=0.0
* scikit-learn~=1.0.2

CUDAが利用可能な場合は、GPUサポート付きのPyTorch (torch) をインストールすることをお勧めします。CPUでも動作します。Intel CPUの場合、MKL (Math Kernel Library) がPyTorchと連携していれば、検出フレームワークははるかに高速に動作します。

UIやその他のアプリ機能を収集するために、以下のパッケージが使用されます：

* androguard~=3.4.0a1
* airtest~=1.2.4

Androidデバイスとの通信にはADB (1.0.41, Version 31.0.3-7562133) を使用します。

データセット
--------

論文で使用されている公開データセットは以下の通りです：

- RePackデータセット: RePack (https://github.com/serval-snt-uni-lu/RePack) は、AndroZoo (https://androzoo.uni.lu/) から収集されたAndroidのリパッケージアプリデータセットです。そのグランドトゥルースには15,000以上のアプリペアがリストされています。このデータセットはUIHashの有効性を評価するために使用されます。

- マルウェアデータセット: RmvDroid (https://ieeexplore.ieee.org/document/8816783) はAndroidマルウェアデータセットで、高い信頼度で56のマルウェアファミリーに属する9,133のサンプルを含んでいます。アプリは異なる年のGoogle Playスナップショットを分析して収集されました。このデータセットにはUIのグランドトゥルースがないため、UIHashが類似したUIクラスターを発見する能力を評価するために使用します。

- Ricoデータセット: Rico (http://interactionmining.org/rico) は、72,000以上のユニークなUIを持つAndroid UIデータセットです。実装では、ビュー画像の再識別を行うCNNモデルの有効性を向上させるためにこのデータセットを使用します。

プロジェクト構成
--------------------
```
[uihash]
│    README.md                     このファイル
│
├----collect                       * 動的にUIを収集
│       device.py                       Androidデバイスオブジェクト
│       manual_capture.py               UIキャプチャ用のテストスクリプト
│       ui_crawler.py                   UIを走査
│
├----hasher                        * UI#を生成
│       extract_view_images.py          UIからビュー画像を抽出
│       reclass.py                      CNNモデルを使用してビューを再識別
│       xml2nodes.py                    階層XMLから可視コントロールを抽出
│       nodes2hash.py                   可視コントロールからUI#を生成
│       uihash.py                       アプリデータセットのUI#を生成
│
├----mlalgos                       * 学習ベースの類似性分析
│       dataset.py                      機械学習用の入力データセットを生成
│       network.py                      ニューラルネットワークの実装
│       siamese.py                      シャムネットワークによる類似度スコアの計算
│       hca.py                          クラスタリング分析
│
├----platform                      *  様々なアプリ機能を抽出
│       apkparser.py                    メインプログラム
│       decompile.py                    コードレベルの検査のためにアプリをデコンパイル
│       extract_apk.py                  アプリを分析して機能を抽出
│
└----util                          * ヘルパー関数
        util_draw.py                    プロットの描画
        util_file.py                    ファイルやフォルダの処理
        util_log.py                     ロガー
        util_math.py                    各種計算
        util_platform.py                プラットフォームで使用されるヘルパー関数
        util_xml.py                     XMLドキュメントの読み込み、解析、処理
```

使用方法
--------

論文で報告された最高性能の再現性を実証し、研究者がモデルの状態が我々のものと一致しているか追跡しやすくするために、コード内で最適なパラメータ設定を提供し、このドキュメントの最後にトレーニングのログを提供しています。以下に、詳細なエンドツーエンド（つまり、Android apkファイルから結果まで）のガイダンスを示します。

### (0) UIの収集

以下のコマンドを実行して、apkファイルから動的にUIを収集します：

``python ./collect/ui_crawler.py path/to/apks device_ip``

スクリプトの詳細な使用方法は以下の通りです：

```text
    usage: ui_crawler.py [-h] [--start START] [--end END] [--resume] [--overwrite]
                        [--package_name] [--logging {debug,info,warn,error}]
                        apk_folder ip

    Launch dynamic testing and collect UIs

    positional arguments:
      apk_folder            the path where you put apks
      ip                    ip address of the android device

    optional arguments:
      -h, --help            show this help message and exit
      --start START, -s START
                            start index of apk testing
      --end END, -e END     last index of apk testing
      --resume, -r          if assigned, start from the recorded last position
                            instead of value start
      --overwrite, -o       if assigned, overwrite the existing output
      --package_name, -p    if assigned, the output folder for an app will be
                            named by the apk's package name instead of its file
                            name
      --logging {debug,info,warn,error}, -l {debug,info,warn,error}
                            logging level, default: info
```

### (1) UIからビューを抽出

UI#を生成する最初のステップは、階層やレイアウトファイル内の宣言された名前ではなく、外観に基づいて再識別するために、UIからビュー画像を抽出することです。ビューを抽出するコマンド例は以下の通りです：


```bash
    python ./hasher/extract_view_images.py path/to/ui/collecting/output
```

``python extract_view_images.py -h`` を実行してヘルプを表示します：

```text

    usage: extract_view_images.py [-h] [--rico] [--naivexml] [--skip] input_path

    Extract view images from UIs, support UI hierarchy printed by naive adb,
    uiautomator2 and RICO

    positional arguments:
      input_path      the path where UI hierarchy exists

    optional arguments:
    -h, --help      show this help message and exit
    --rico, -r      extract view images from rico UIs
    --naivexml, -n  assign it when using naive adb, and ignore it when using
                    uiautomator2 xml
    --skip, -s      skip the existing items
```

### (2) コントロールタイプの認識

ビュー画像を再分類します。モデルは ``models`` という名前のフォルダに保存またはロードされます。存在しない場合、または存在しても更新が必要な場合は、モジュールは新しいモデルをトレーニングします。コマンド例は以下の通りです：

```bash
    python ./hasher/reclass.py path/to/view/image/dataset path/to/ui/collecting/output --notskip
```
``python reclass.py -h`` を実行してヘルプを表示します：

```text
    usage: reclass.py [-h] [--lr LR] [--decay DECAY] [--batch_size BATCH_SIZE]
                      [--epoch EPOCH] [--threshold THRESHOLD] [--retrain]
                      [--notskip]
                      dataset_path input_path

    Reidentify UI controls based on their image features

    positional arguments:
      dataset_path          the path for view image dataset. I get the view type
                            names according to it
      input_path            input path

    optional arguments:
    -h, --help            show this help message and exit
    --lr LR, -l LR        training learning rate of the model
    --decay DECAY, -d DECAY
                          training learning rate decay of the model, format:
                          decay_epoch,decay_rate
    --batch_size BATCH_SIZE, -b BATCH_SIZE
                          training batch size of the model
    --epoch EPOCH, -e EPOCH
                          training epoch of the model
    --threshold THRESHOLD, -t THRESHOLD
                          prediction confidence of the model
    --retrain, -r         retrain and overwrite the existing model
    --notskip, -s         do not skip the reidentified items
```

入力引数のデフォルト値は以下の通りです：

**name**    | **value** | **name** | **value**
------------| -----------| ---------| -----------
lr          | 0.003      | decay    |  4,0.1
batch_size  | 128        | epoch    |  12
threshold   | 0.95       | retrain  |  False
------------ ------------ ---------- -----------

### (3) UI#の生成

UI階層と再識別されたビュータイプを指定して、以下のようなコマンドを実行します：

```bash
    # オリジナルアプリの場合
    python ./hasher/uihash.py path/to/opt_original_apk/ path/to/view/image/dataset -d ori
    # リパッケージアプリの場合
    python ./hasher/uihash.py path/to/opt_repackage_apk/ path/to/view/image/dataset -d re
    # ラベルなしアプリの場合
    python ./hasher/uihash.py path/to/opt_xxx_apk/
```

これにより、ラベル付きまたはラベルなしのアプリデータセットのUI#を生成します。プロセス終了後、``output/hash`` フォルダの下に ``name_[dataset]_5x5x10.npy`` と ``hash_[dataset]_5x5x10.npy`` が生成されます。[dataset] フィールドは、"ori"（RePackのようなラベル付きデータセットのオリジナルアプリの場合）、"re"（ラベル付きデータセットのリパッケージアプリの場合）、またはラベルなしデータセットの名前のいずれかになります。前者のファイルはアプリ名やアクティビティ名などのメタデータを記録します。後者のファイルはUI#マトリックスを保持します。

``python uihash.py -h`` を実行してヘルプを表示します：

```text
    usage: uihash.py [-h] [--output_path OUTPUT_PATH] [--naivexml]
                     [--dataset_name DATASET_NAME] [--grid_size GRID_SIZE]
                     [--filter FILTER]
                     input_path [input_path ...] view_image_path

    Turns UI into UI#

    positional arguments:
      input_path            input paths
      view_image_path       path for the view image dataset

    optional arguments:
      -h, --help            show this help message and exit
      --output_path OUTPUT_PATH, -o OUTPUT_PATH
                            output path
      --naivexml, -n        assign it when using naive adb, and ignore it
                            when use uiautomator2 xml
      --dataset_name DATASET_NAME, -d DATASET_NAME
                            make it 'ori' when the only ipt_path is the original
                            apps in a labeled dataset like RePack, and 're' for
                            the repackaged apps. Just keep it unset when working
                            on an unlabeled dataset
      --grid_size GRID_SIZE, -g GRID_SIZE
                            expected grid size for UI#. format:
                            tick_horizontal,tick_vertical
      --filter FILTER, -f FILTER
                            0 to remove the filter, otherwise the threshold of the
                            minimal accepted visible nodes in a UI
```

``grid_size`` のデフォルト値は ``5,5`` で、``filter`` のデフォルト値は 5 です。``output_path`` を指定しない場合、``<uihash_homepath>/output/hash`` になります。

### (4) データセットの生成

``python ./mlalgos/dataset.py -h`` を実行して以下のようにヘルプを表示します：

```text
    usage: dataset.py [-h] [--hash_size HASH_SIZE]
                      input_path [input_path ...] app_pair_list

    Generate dataset for training and detection

    positional arguments:
      input_path            input paths of repack app
      app_pair_list         a txt file indicating app pairs in a similar app
                            dataset

    optional arguments:
      -h, --help            show this help message and exit
      --hash_size HASH_SIZE, -hs HASH_SIZE
                            shape of the input UI#
```

このモジュールは ``output/dataset`` に ``Re_5x5x10.npz``、``ReDP_5x5x10.npy``、``ReSP_5x5x10.npy`` を出力します。ここで ``SP`` は類似ペア（Similar Pairs）を表し、``DP`` はその中のUI#ペアが非類似（Dissimilar）であることを示します。

ラベルなしデータセットの生成については、代わりに `WildDataSet` クラスを使用してください。

### (5) 結果の取得

シャムネットワーク（Siamese Network）に基づいて検出を実行します。ビュー再識別モデルと同様に、シャムモデルも ``models`` という名前のフォルダに保存またはロードされます。存在しない場合、または存在しても更新が必要な場合は、``siamese.py`` が新しいモデルをトレーニングします。

```bash
    python ./mlalgos/siamese.py -R -f
```

```text
    usage: siamese.py [-h] [--Repack] [--dataset_name DATASET_NAME] [--lr LR]
                      [--decay DECAY] [--batch_size BATCH_SIZE] [--epoch EPOCH]
                      [--threshold THRESHOLD] [--retrain] [--notskip] [--figure]
                      [--hash_size HASH_SIZE]

    Run the siamese network on a dataset

    optional arguments:
    -h, --help              show this help message and exit
    --Repack, -R            use repack dataset
    --dataset_name DATASET_NAME, -dn DATASET_NAME
                            if not use repack dataset, then assign another dataset
                            name. make sure the hash files exist in output/hash
    --lr LR, -l LR          training learning rate of the model
    --decay DECAY, -d DECAY
                            training learning rate decay of the model, format:
                            decay_epoch,decay_rate
    --batch_size BATCH_SIZE, -b BATCH_SIZE
                            batch size for the model
    --epoch EPOCH, -e EPOCH
                            training epoch of the model
    --threshold THRESHOLD, -t THRESHOLD
                            the threshold to determine whether a pair is similar.
                            note that if apply detection on a wild dataset, then the
                            threshold also serves for filtering similar UIs in
                            each app
    --retrain, -r           retrain and overwrite the existing model
    --notskip, -s           do not skip the reidentified items
    --figure, -f            draw and show roc figure
    --hash_size HASH_SIZE, -hs HASH_SIZE
                            shape of UI#. format:
                            channel,tick_horizontal,tick_vertical
```

入力引数のデフォルト値は以下の通りです：

**name**    | **value** | **name** | **value**
------------| -----------| ---------| -----------
lr          | 0.001      | decay    | 10,0.1
batch_size  | 32         | epoch    | 36
threshold   | 0.6        | retrain  | False
hash_size   | 10,5,5     | figure   | False

最終的な出力は、テストデータセットに対する適合率（Precision）、再現率（Recall）、F1スコアです。ROC曲線を確認するには ``--figure`` を使用してください。

大規模なペアワイズ検出をブルートフォースで実装する場合、2GBのグラフィックメモリを持つGPUに対してバッチサイズとして20,000を選択します。この値はハードウェアに応じてより高い値に増やすことができます。

1回の実行の出力例：
```python
DEVICE: cpu
Training (1/36) 100% |========================================================|
Validating (1/36) 100% |======================================================|
Train Loss 0.195 Valid Loss 0.127 lr 0.001
...
(省略)
...
training time cost: 32.7671793
model saved
prediction time cost: 0.025467499999999976
p: 0.9786324786324786
r: 0.9870689655172413
f1: 0.9828326180257511
auc: 0.9966211279953244
```

学習と検証の損失曲線：

<img src="fig/history.png" width=80%>
