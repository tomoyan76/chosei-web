#!/bin/bash
# =================================================================
# chosei-web GitHub push スクリプト（PAT認証版）
# このファイルをダブルクリックするとターミナルが開いて自動実行します
# =================================================================

cd "$(dirname "$0")"

echo "================================================"
echo "  調整カレンダー → GitHub push（PAT認証）"
echo "================================================"
echo ""
echo "GitHub Personal Access Token（PAT）が必要です。"
echo ""
echo "まだトークンがない場合は、以下のURLで発行してください："
echo "  https://github.com/settings/tokens/new"
echo "  → Expiration: 7 days"
echo "  → Scopes: ✅ repo （チェックを入れる）"
echo "  → 「Generate token」をクリック → 表示されたトークンをコピー"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
read -sp "GitHubトークンを貼り付けて Enter: " GH_TOKEN
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [ -z "$GH_TOKEN" ]; then
  echo "❌ トークンが入力されませんでした。終了します。"
  read -p "Enterキーを押して終了..."
  exit 1
fi

# リモートURLにトークンを埋め込む
REMOTE="https://tomoyan76:${GH_TOKEN}@github.com/tomoyan76/chosei-web.git"

# すでに origin があれば削除して再設定
git remote remove origin 2>/dev/null || true
git remote add origin "$REMOTE"

echo "📤 GitHub にプッシュ中..."
if git push -u origin main; then
  # セキュリティのためトークン入りURLを削除し、通常のURLに戻す
  git remote set-url origin "https://github.com/tomoyan76/chosei-web.git"
  echo ""
  echo "================================================"
  echo "  ✅ GitHub プッシュ完了！"
  echo "  🔗 https://github.com/tomoyan76/chosei-web"
  echo "================================================"
  echo ""
  echo "次のステップ: Railway でデプロイ"
  echo "  1. https://railway.app にアクセス"
  echo "  2. 「Start a New Project」→「Deploy from GitHub repo」"
  echo "  3. tomoyan76/chosei-web を選択"
else
  git remote set-url origin "https://github.com/tomoyan76/chosei-web.git"
  echo ""
  echo "❌ プッシュに失敗しました。"
  echo "   トークンのスコープに「repo」が含まれているか確認してください。"
fi

echo ""
read -p "Enterキーを押して終了..."
