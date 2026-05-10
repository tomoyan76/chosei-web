# 調整カレンダー — 調整さん × Google Calendar 自動登録 PWA

調整さん（chouseisan.com）のURLを管理し、自分の回答（○△）を自動でGoogleカレンダーに反映するPWAアプリです。  
`credentials.json` は不要。**環境変数だけで動きます。**

---

## 機能概要

| 機能 | 説明 |
|------|------|
| 📅 自動カレンダー登録 | 調整さんURLを貼るだけ。自分の○△を自動でカレンダーへ |
| 🔄 1時間ごと自動更新 | バックグラウンドで全URLをチェック・カレンダー同期 |
| ✅ 確定検知 | 確定日を検知したら確定イベントだけ残して候補日を削除 |
| 📱 PWA対応 | ホーム画面に追加してネイティブアプリ感覚で使用 |
| 🔗 シェアシート連携 | LINEやSlackのURLを長押し→共有→即登録 |

---

## 環境変数一覧

| 変数名 | 必須 | 説明 |
|--------|------|------|
| `GOOGLE_CLIENT_ID` | ✅ | Google Cloud Console のOAuth2クライアントID |
| `GOOGLE_CLIENT_SECRET` | ✅ | OAuth2クライアントシークレット |
| `SECRET_KEY` | ✅ | セッション署名用ランダム文字列 |
| `BASE_URL` | ✅ | アプリのURL（例: `http://localhost:8000`） |

```bash
# SECRET_KEY の生成コマンド
python -c "import secrets; print(secrets.token_hex(32))"
```

---

## Google Cloud Console — OAuth設定手順

### 1. プロジェクト作成

1. https://console.cloud.google.com/ を開く
2. 上部「プロジェクトを選択」→「新しいプロジェクト」
3. プロジェクト名（例: `chosei-cal`）→「作成」

### 2. Google Calendar API を有効化

```
APIとサービス > ライブラリ > "Google Calendar API" 検索 > 有効にする
```

### 3. OAuth 同意画面の設定

```
APIとサービス > OAuth 同意画面
```

- User Type: **外部** → 「作成」
- アプリ名: `調整カレンダー`、サポートメール: 自分のGmail
- スコープ: `../auth/userinfo.email`、`../auth/calendar` を追加
- テストユーザー: 自分のGmailを追加（公開前必須）
- 「保存して次へ」を3回

### 4. OAuth2 クライアントID を作成

```
APIとサービス > 認証情報 > 認証情報を作成 > OAuth クライアント ID
```

- アプリケーションの種類: **ウェブアプリケーション**
- 承認済みの JavaScript 生成元:
  - `http://localhost:8000`
  - `https://your-app.railway.app`（本番）
- 承認済みのリダイレクト URI:
  - `http://localhost:8000/api/auth/callback`
  - `https://your-app.railway.app/api/auth/callback`（本番）

→「作成」後、**クライアントID** と **クライアントシークレット** をコピー

---

## ローカル開発

```bash
cd chosei-web

# 仮想環境作成（任意）
python3 -m venv venv && source venv/bin/activate

# 依存パッケージインストール
pip install -r requirements.txt

# アイコン生成
python generate_icons.py

# .env ファイルを作成
cp .env.example .env
# .env を編集して GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / SECRET_KEY を設定

# サーバー起動
uvicorn main:app --reload --port 8000
```

→ http://localhost:8000 を開く

---

## Railway へのデプロイ（推奨）

```bash
# Railway CLI インストール
brew install railway   # macOS

# ログイン
railway login

# プロジェクト初期化（chosei-webディレクトリで実行）
railway init

# 環境変数設定
railway variables set GOOGLE_CLIENT_ID=your-client-id
railway variables set GOOGLE_CLIENT_SECRET=your-client-secret
railway variables set SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")

# 一旦デプロイしてURLを取得してからBASE_URLを設定
railway up
railway variables set BASE_URL=https://$(railway domain)

# 最終デプロイ
railway up
```

### デプロイ後にすること

Google Cloud Console のリダイレクトURIに本番URLを追加:
```
https://your-app.railway.app/api/auth/callback
```

---

## Vercel へのデプロイ

```bash
npm i -g vercel
cd chosei-web
vercel

vercel env add GOOGLE_CLIENT_ID
vercel env add GOOGLE_CLIENT_SECRET
vercel env add SECRET_KEY
vercel env add BASE_URL   # https://your-app.vercel.app

vercel --prod
```

---

## iOS ホーム画面追加（PWAインストール）

1. **Safari** でアプリURLを開く（Chrome等では追加不可）
2. 下部ツールバーの **共有ボタン**（□↑）をタップ
3. 「**ホーム画面に追加**」をタップ
4. 「**追加**」をタップ

### シェアシートから調整さんURLを送る方法

1. LINEやSlackで調整さんURLを **長押し**
2. 「**共有**」をタップ
3. **調整カレンダー** のアイコンをタップ
4. 自動でURLが登録されます

> シェアシートに表示されるには、先にPWAをインストールしておく必要があります。

---

## カレンダー登録ルール

| 回答 | カレンダーイベント |
|------|-----------------|
| ○（参加可） | `status: confirmed` で作成 |
| △（仮参加） | `status: tentative` で作成（薄表示） |
| ×（不参加） | 登録しない |
| 確定検知時 | 確定日のみ残し、他の候補日イベントを削除 |

---

## 名前マッチングロジック

本名「山田　太郎」・ニックネーム「たろう」で登録すると以下のトークンが生成されます:

```
山田 / 太郎 / 山田太郎 / たろう
```

- 全角スペース（　）と半角スペース（ ）は同一視
- 回答者名にいずれかのトークンが**部分一致**すれば自分の回答として認識
- 複数マッチ時は画面上でラジオボタン選択（選択結果はDB保存・次回から自動選択）

---

## ファイル構成

```
chosei-web/
├── main.py              # FastAPI アプリ本体
├── scraper.py           # 調整さんスクレイパー
├── calendar_client.py   # Google Calendar API クライアント（環境変数ベース）
├── db.py                # SQLite データベース
├── generate_icons.py    # PWAアイコン生成スクリプト
├── static/
│   ├── index.html       # フロントエンド SPA（Vanilla JS）
│   ├── manifest.json    # PWAマニフェスト（share_target含む）
│   ├── sw.js            # Service Worker
│   ├── icon-192.png     # PWAアイコン（generate_icons.pyで生成）
│   └── icon-512.png
├── .env.example         # 環境変数テンプレート
├── Procfile             # Railway / Heroku 用
├── requirements.txt
├── chosei.db            # SQLite DB（自動生成）
└── README.md
```

---

## トラブルシューティング

### `GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET が設定されていません` エラー

`.env` ファイルを確認してください。値が正しく設定されているか、サーバーを再起動したか確認してください。

### OAuth エラー `redirect_uri_mismatch`

Google Cloud Console のリダイレクトURIに `BASE_URL/api/auth/callback` が登録されているか確認してください。

### スクレイピングが失敗する

- URLが `https://chouseisan.com/s?h=XXXX` 形式か確認
- 調整さんのページがブラウザで正常に開けるか確認
- アクセス数制限に引っかかっている場合は数分待ってリトライ

### カレンダーに登録されない

- 設定タブでGoogleカレンダーが「連携済み ✓」になっているか確認
- Google Cloud ConsoleでCalendar APIが有効になっているか確認
- テストユーザーに自分のGmailが追加されているか確認（OAuth同意画面が「テスト」状態の場合）
