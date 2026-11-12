# Avatar Chat

OpenAI互換エンドポイントにつなぐ、アバターの表情が変わるチャット。キャラごとの記憶が時間とともに薄れます。

## 使い方
1. `start.bat` をダブルクリック(初回のみ Python・ライブラリを自動でダウンロードします。インターネット接続が必要)
2. ブラウザが開いたら「設定」で接続先URL・モデル名を入力(一覧取得ボタンあり)
3. 話しかける。右側に記憶とその「薄れ具合」が出ます

詳しい操作方法・アバターの作り方は `manual.html`(ブラウザで開く)を見てください。English / 简体中文 / Español / Português 版も同じファイル内にあり、上のタブで切り替えます(機械翻訳)。

## ローカルLLMのセットアップ(任意)
**初回の `start.bat` で自動的にメニューが出ます**(ダブルクリックだけでOK。キーボードの数字キーを押して選ぶだけで、文字入力は要りません)。やり直したいときは `misc\setup-llm.bat` をダブルクリックします。
- 「1 Radeon(Vulkan版。IntelのGPUや内蔵GPUでも動くかもしれませんが未確認)」「2 GeForce RTX 20系以降(VRAM 8GB以上、CUDA 12.4版)」「3 すでにあるLLMサーバーを使う(LM Studio / Ollama / llama.cpp)」「4 あとで設定する」から選びます。
- Stheno / Lumimaid は少し古いモデルで、日本語は弱めです(VRAM 8GB で動かせる範囲での割り切り)。
- すでに `user-data/config.json` がある場合(更新時など)は、メニューは出ません。
- 1・2では `llama.cpp/`、`llama-swap/`、`models/` を作ってインストールし、Stheno v3.4 8B Q4_K_M(約4.9GB)をダウンロードします。Lumimaid v0.2 8B(任意)も選べます。500MB以上のファイルは `--limit-rate 5m` で取得するので、モデルの取得には約17分かかります(中断しても再実行で続きから)。
- 1・2では `llama-swap/config.yaml` と `user-data/config.json`(接続先 `http://127.0.0.1:8080/v1`、モデル名 `stheno-8b`)が自動で作られます。以後は `start.bat` が llama-swap も自動で起動します。
- コンテキスト長やGPUレイヤー数は `llama-swap/config.yaml` で変更できます(雛形は `misc/llama-swap.config.template.yaml`)。
- バージョンは `misc/setup-llm.bat` の冒頭で固定しています(llama.cpp v0.9.0 = ビルド b12110、llama-swap v270)。更新するときは `LLAMA_TAG` / `SWAP_VER` を書き換えます。

## フォルダ
- `app/` アプリ本体(更新時はここを差し替え)
- `characters/` 組み込みキャラ(1フォルダ = 1キャラ。`character.json` + 表情画像)
- `user-data/` 設定・会話・記憶(`app.db`)・追加したキャラ。**更新しても消えません**
- `system/` 自動で作られる Python 一式(消すと次回起動時に再作成)
- `llama.cpp/` `llama-swap/` `models/` `misc/setup-llm.bat` で作られるローカルLLM一式

## キャラの追加
- 画面左の「＋キャラ追加」から、表情画像を選んで登録(neutral 必須、足りない表情は neutral で代用)
- 動き方は `character.json` の `"motion"` で選べます。`squash`(つぶれ・伸び・跳ねあり。生き物向け、既定)/ `soft`(体を歪めない。人間型向け)
- 手動で足すなら `characters/<名前>/character.json` と画像(svg/png/webp)を置く

## ネット検索(Brave Search API)
- 設定に Brave Search API のキーを入れると、入力欄の横の「🔍」で切り替えられます。
  - **自動**: LLM が「検索が必要か」を判断し、必要なときだけ検索します(判断のためLLMを1回余分に呼びます)
  - **毎回**: 毎回検索します / **なし**: 検索しません
- 検索結果はキャラの口調で答えに使われ、画面に出典リンクが出ます。
- 検索キーワードは Brave に送られます。キーは `user-data/config.json` に平文で保存されます。

## 記憶の仕組み
強さ = 重要度/5 × exp(-最後に思い出してからの日数 / (基準日数 × (1+ln(1+想起回数))))
話題に出るたびに強くなり、強さが閾値を下回ると思い出せなくなります(設定で基準日数を調整)。
- 記憶の抽出は**ユーザーの発言だけ**を根拠にします(キャラの創作や、現在時刻のような変わる情報は覚えません)。
- 名前の言い直しなど、古い記憶と食い違う情報が出たら、古い記憶は新しい内容に置き換わります。
- 間違った記憶は、右パネルの「×」で個別に消せます。

## テスト(開発用)
`python3 misc/smoke_test.py` — モックLLMでAPI一式を確認します。

## 天気について
天気の質問で地域名(都道府県・市区町村・九州などの広い地域)が分かるときは、Braveではなく気象庁の予報データ(jma.go.jp)を直接取得して答えます。APIキーは不要で、出典は気象庁です。地域が分からない質問は、従来どおりBrave検索になります。

---

# English

# Avatar Chat

A chat app that connects to any OpenAI-compatible endpoint, where the avatar's facial expression changes as you talk. Each character's memories fade over time.

## Usage
1. Double-click `start.bat` (on the first run it automatically downloads Python and the libraries; an internet connection is required)
2. When the browser opens, enter the endpoint URL and model name in "Settings" (there is a button to fetch the model list)
3. Start talking. The memories and how much they have "faded" appear on the right

For detailed instructions and how to make avatars, see `manual.html` (open it in a browser). English / 简体中文 / Español / Português versions are in the same file, switched with the tabs at the top (machine-translated).

## Local LLM setup (optional)
**A menu appears automatically on the first run of `start.bat`** (just double-click; choose by pressing a number key, no typing needed). To redo it, double-click `misc\setup-llm.bat`.
- Choose from: "1 Radeon (Vulkan build; it may also work on Intel GPUs and integrated GPUs, but this is unconfirmed)", "2 GeForce RTX 20 series or later (VRAM 8GB or more, CUDA 12.4 build)", "3 Use an existing LLM server (LM Studio / Ollama / llama.cpp)", "4 Set up later".
- Stheno / Lumimaid are somewhat older models and are weak in Japanese (a compromise for what runs on 8GB of VRAM).
- If `user-data/config.json` already exists (e.g. when updating), the menu does not appear.
- Options 1 and 2 create and install `llama.cpp/`, `llama-swap/` and `models/`, and download Stheno v3.4 8B Q4_K_M (about 4.9GB). Lumimaid v0.2 8B can also be selected (optional). Files over 500MB are fetched with `--limit-rate 5m`, so fetching the model takes about 17 minutes (if interrupted, re-running resumes where it left off).
- Options 1 and 2 also create `llama-swap/config.yaml` and `user-data/config.json` (endpoint `http://127.0.0.1:8080/v1`, model name `stheno-8b`) automatically. From then on, `start.bat` also starts llama-swap automatically.
- Context length and the number of GPU layers can be changed in `llama-swap/config.yaml` (the template is `misc/llama-swap.config.template.yaml`).
- Versions are pinned at the top of `misc/setup-llm.bat` (llama.cpp v0.9.0 = build b12110, llama-swap v270). To update, edit `LLAMA_TAG` / `SWAP_VER`.

## Folders
- `app/` The application itself (replace this when updating)
- `characters/` Built-in characters (one folder = one character: `character.json` + expression images)
- `user-data/` Settings, conversations, memories (`app.db`) and characters you added. **Not erased by updates**
- `system/` The Python environment created automatically (delete it and it is recreated on the next run)
- `llama.cpp/` `llama-swap/` `models/` The local LLM set created by `misc/setup-llm.bat`

## Adding characters
- Use "+ Add character" on the left of the screen and choose expression images to register (neutral is required; missing expressions fall back to neutral)
- The movement style can be chosen with `"motion"` in `character.json`: `squash` (squash, stretch and bounce; for living creatures; the default) / `soft` (does not distort the body; for human-like characters)
- To add one manually, place `characters/<name>/character.json` and the images (svg/png/webp)

## Web search (Brave Search API)
- If you enter a Brave Search API key in Settings, you can switch search modes with the "🔍" next to the input box.
  - **Auto**: the LLM decides whether a search is needed and searches only when it is (this costs one extra LLM call for the decision)
  - **Always**: searches every time / **Off**: never searches
- Search results are used in the character's tone of voice, and source links are shown on screen.
- Search keywords are sent to Brave. The key is stored in plain text in `user-data/config.json`.

## How memory works
strength = importance/5 × exp(−days since last recalled / (base days × (1 + ln(1 + recall count))))
A memory gets stronger every time it comes up, and once its strength falls below a threshold it can no longer be recalled (the base days can be adjusted in Settings).
- Memories are extracted **only from the user's own statements** (things the character makes up, or information that changes such as the current time, are not remembered).
- If information that contradicts an old memory appears (e.g. a corrected name), the old memory is replaced with the new content.
- Wrong memories can be deleted one by one with the "×" in the right panel.

## Tests (for development)
`python3 misc/smoke_test.py` — checks the whole API against a mock LLM.

## About weather
When a weather question names a region (a prefecture, a city, or a broad area such as Kyushu), the app fetches the Japan Meteorological Agency's forecast data (jma.go.jp) directly instead of using Brave. No API key is needed, and the source is the JMA. For questions where the region is unclear, it falls back to Brave search as before.
