/**
 * Service Worker — 調整カレンダー PWA
 * - アプリシェルをキャッシュしてオフラインでも一覧を表示
 * - APIリクエストはネットワーク優先、失敗時はキャッシュにフォールバック
 */

const CACHE_NAME = "chosei-cal-__VERSION__";

// キャッシュするアプリシェル
const APP_SHELL = [
  "/",
  "/manifest.json",
  "/static/icon-192.png",
  "/static/icon-512.png",
];

// ────────────────────────────────────────────────
// インストール: アプリシェルをキャッシュ
// ────────────────────────────────────────────────
self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE_NAME)
      .then((cache) => cache.addAll(APP_SHELL))
      .then(() => self.skipWaiting())
  );
});

// ────────────────────────────────────────────────
// アクティベート: 古いキャッシュを削除
// ────────────────────────────────────────────────
self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((k) => k !== CACHE_NAME)
            .map((k) => caches.delete(k))
        )
      )
      .then(() => self.clients.claim())
  );
});

// ────────────────────────────────────────────────
// フェッチ: ルートごとに戦略を分ける
// ────────────────────────────────────────────────
self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);

  // share_target: /share?url=... → メインページへリダイレクト
  if (url.pathname === "/share" && url.searchParams.has("url")) {
    const sharedUrl = url.searchParams.get("url") || "";
    if (sharedUrl.includes("chouseisan.com")) {
      event.respondWith(
        clients
          .openWindow(`/?shared=${encodeURIComponent(sharedUrl)}`)
          .then(() => new Response("", { status: 200 }))
          .catch(() =>
            Response.redirect(`/?shared=${encodeURIComponent(sharedUrl)}`, 302)
          )
      );
      return;
    }
  }

  // API リクエスト: ネットワーク優先（オフライン時は503）
  if (url.pathname.startsWith("/api/")) {
    event.respondWith(
      fetch(event.request).catch(
        () =>
          new Response(
            JSON.stringify({ detail: "オフラインです。ネットワーク接続を確認してください。" }),
            {
              status: 503,
              headers: { "Content-Type": "application/json" },
            }
          )
      )
    );
    return;
  }

  // ナビゲーション (HTMLページ): キャッシュ優先 → ネットワーク
  if (event.request.mode === "navigate") {
    event.respondWith(
      caches.match("/").then(
        (cached) => cached || fetch(event.request)
      )
    );
    return;
  }

  // 静的アセット: キャッシュ優先 → ネットワーク → キャッシュに保存
  event.respondWith(
    caches.match(event.request).then((cached) => {
      if (cached) return cached;
      return fetch(event.request).then((response) => {
        if (!response || response.status !== 200 || response.type !== "basic") {
          return response;
        }
        const toCache = response.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(event.request, toCache));
        return response;
      });
    })
  );
});

// ────────────────────────────────────────────────
// プッシュ通知（将来拡張用）
// ────────────────────────────────────────────────
self.addEventListener("push", (event) => {
  if (!event.data) return;
  const data = event.data.json();
  self.registration.showNotification(data.title || "調整カレンダー", {
    body: data.body || "",
    icon: "/static/icon-192.png",
    badge: "/static/icon-192.png",
  });
});
