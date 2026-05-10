# 調整カレンダー（chosei-web）

調整さん（chouseisan.com）のURLを登録するだけで、自分の回答（○△）をGoogleカレンダーに自動登録するPWAアプリです。

---

## 機能

| 機能 | 説明 |
|------|------|
| 📅 自動カレンダー登録 | 調整さんURLを登録するだけ。○→確定登録、△→仮登録 |
| ✅ 確定検知 | 日程確定を検知したら仮登録を本登録に自動切り替え |
| 🔄 起動時自動更新 | アプリを開くたびに未確定アイテムを自動チェック |
| 📋 一覧管理 | 複数の調整さんをまとめて確認・管理 |
| 📱 PWA対応 | ホーム画面に追加してネイティブアプリ感覚で使用 |
| 🔐 招待コード認証 | 限定公開用の招待コードでアクセス制限 |

---

## クローンして動かす

### 1. リポジトリをクローン

```bash
git clone https://github.com/tomoyan76/chosei-web.git
cd chosei-web
```

### 2. 依存パッケージをインストール

```bash
pip3 install -r requirements.txt
```

### 3. Google Cloud Console でOAuth設定

#### プロジェクト作成
1. https://console.cloud.google.com/ を開く
2. 「プロジェクトを選択」→「新しいプロジェクト」→ 任意の名前で作成

#### Google Calendar API を有効化
```
APIとサービス > ライブラリ > "Google Calendar API" > 有効にする
```

#### OAuth 同意画面の設定
```
APIとサービス > OAuth 同意画面
```
- User Type: **外部** → 作成
- アプリ名・サポートメール: 任意
- スコープ: `../auth/userinfo.email`、`../auth/calendar` を追加
- テストユーザー: 自分のGmailを追加

#### OAuth2 クライアントID を作成
```
APIとサービス > 認証情報 > 認証情報を作成 > OAuth クライアント ID
```
- アプリケーションの種類: **ウェブアプリケーション**
- 承認済みのリダイレクト URI:
  - `http://localhost:8000/api/auth/callback`（ローカル用）
  - `https://your-app.fly.dev/api/auth/callback`（本番用）

作成後、**クライアントID** と **クライアントシークレット** をコピー。

### 4. .env ファイルを作成

```bash
cp .env.example .env
```

`.env` を編集して以下を設定：

```
GOOGLE_CLIENT_ID=（取得したクライアントID）
GOOGLE_CLIENT_SECRET=（取得したクライアントシークレット）
SECRET_KEY=（下記コマンドで生成）
BASE_URL=http://localhost:8000
INVITE_CODE=（任意の招待コード。空欄なら制限なし）
```

```bash
# SECRET_KEY の生成
python3 -c "import secrets; print(secrets.token_hex(32))"
```

### 5. 起動

```bash
python3 main.py
```

→ http://localhost:8000 を開く

---

## Fly.io へのデプロイ

```bash
# flyctl インストール（未インストールの場合）
curl -L https://fly.io/install.sh | sh

# ログイン
fly auth login

# アプリ作成（初回のみ）
fly launch

# 環境変数を設定
fly secrets set GOOGLE_CLIENT_ID=your-client-id
fly secrets set GOOGLE_CLIENT_SECRET=your-client-secret
fly secrets set SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
fly secrets set BASE_URL=https://your-app.fly.dev
fly secrets set INVITE_CODE=your-invite-code

# デプロイ
fly deploy
```

### GitHub Actions で自動デプロイ（推奨）

1. `fly tokens create deploy` でトークンを発行
2. GitHubリポジトリの Settings → Secrets → `FLY_API_TOKEN` として登録
3. 以降は `git push origin main` するだけで自動デプロイ

---

## 環境変数一覧

| 変数名 | 必須 | 説明 |
|--------|------|------|
| `GOOGLE_CLIENT_ID` | ✅ | Google OAuth2 クライアントID |
| `GOOGLE_CLIENT_SECRET` | ✅ | Google OAuth2 クライアントシークレット |
| `SECRET_KEY` | ✅ | Cookie署名用ランダム文字列（`secrets.token_hex(32)` で生成） |
| `BASE_URL` | ✅ | アプリのURL（例: `https://your-app.fly.dev`） |
| `INVITE_CODE` | ☑️ | 招待コード。設定しない場合はアクセス制限なし |

---

## iOS ホーム画面への追加（PWAインストール）

1. **Safari** でアプリURLを開く（Chrome等では追加不可）
2. 下部ツールバーの **共有ボタン**（□↑）をタップ
3. 「**ホーム画面に追加**」をタップ → 「追加」

### LINEから調整さんURLを共有する方法

LINEのURL長押しでは iOS の共有シートが開きません。以下の手順で操作してください：

1. LINEでURLをタップして開く
2. LINE内ブラウザの **共有ボタン**（↑）をタップ
3. **調整カレンダー** のアイコンをタップ

> PWAをインストール済みの場合のみ共有先に表示されます。

---

## カレンダー登録ルール

| 回答 | カレンダーイベント |
|------|-----------------|
| ○（参加可） | 通常イベントとして登録 |
| △（仮参加） | 仮イベント（タイトルに【仮】）として登録 |
| ×（不参加） | 登録しない |
| 確定検知時 | 確定日のみ残し、他の候補日イベントを削除 |

---

## ファイル構成

```
chosei-web/
├── main.py              # FastAPI アプリ本体
├── scraper.py           # 調整さんスクレイパー
├── calendar_client.py   # Google Calendar API クライアント
├── db.py                # SQLite データベース
├── Dockerfile           # コンテナ設定
├── fly.toml             # Fly.io 設定
├── .env.example         # 環境変数テンプレート
├── requirements.txt
├── static/
│   ├── index.html       # フロントエンド（Vanilla JS PWA）
│   ├── manifest.json    # PWAマニフェスト
│   ├── sw.js            # Service Worker
│   ├── icon-192.png
│   └── icon-512.png
└── .github/
    └── workflows/
        └── deploy.yml   # GitHub Actions 自動デプロイ
```

---

## トラブルシューティング

**`GOOGLE_CLIENT_ID が設定されていません` エラー**
→ `.env` ファイルの値を確認し、サーバーを再起動してください。

**OAuth エラー `redirect_uri_mismatch`**
→ Google Cloud Console のリダイレクトURIに `{BASE_URL}/api/auth/callback` が登録されているか確認してください。

**招待コード画面が出ない（古い画面が表示される）**
→ Safariのキャッシュをクリアするか、アドレスバーからURLを直接入力して再アクセスしてください。

**カレンダーに登録されない**
→ 設定タブでGoogleカレンダーが「連携済み ✓」になっているか確認してください。Google Cloud ConsoleでCalendar APIが有効か、テストユーザーに自分のGmailが追加されているかも確認してください。
