package com.chainshield.app;

import android.app.Activity;
import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.graphics.Insets;
import android.view.WindowInsets;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;
import org.json.JSONObject;
import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.Map;

public final class MainActivity extends Activity {
    private static final String SITE = "appassets.androidplatform.net";
    private WebView webView;
    private MaintenanceManager maintenance;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        if (!Python.isStarted()) Python.start(new AndroidPlatform(getApplicationContext()));
        try { maintenance = new MaintenanceManager(getApplicationContext()); } catch (Exception ignored) { maintenance = null; }
        webView = new WebView(this);
        webView.setBackgroundColor(0xff0b1020);
        getWindow().setStatusBarColor(0xff0b1020);
        getWindow().setNavigationBarColor(0xff0b1020);
        if (Build.VERSION.SDK_INT >= 35) {
            webView.setOnApplyWindowInsetsListener((view, insets) -> {
                Insets bars = insets.getInsets(WindowInsets.Type.systemBars() | WindowInsets.Type.displayCutout());
                view.setPadding(bars.left, bars.top, bars.right, bars.bottom);
                return insets;
            });
        }
        webView.getSettings().setJavaScriptEnabled(true);
        webView.getSettings().setDomStorageEnabled(true);
        webView.getSettings().setAllowFileAccess(false);
        webView.getSettings().setAllowContentAccess(false);
        webView.getSettings().setJavaScriptCanOpenWindowsAutomatically(false);
        webView.getSettings().setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        if (Build.VERSION.SDK_INT >= 26) webView.getSettings().setSafeBrowsingEnabled(true);
        // The app never exposes a JavaScript bridge to remote web pages.
        webView.setWebViewClient(new LocalClient());
        setContentView(webView);
        webView.loadUrl("https://" + SITE + "/index.html");
    }

    @Override public void onBackPressed() {
        if (webView != null && webView.canGoBack()) webView.goBack();
        else super.onBackPressed();
    }

    @Override protected void onDestroy() {
        if (webView != null) { webView.destroy(); webView = null; }
        super.onDestroy();
    }

    private final class LocalClient extends WebViewClient {
        @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest req) {
            Uri uri = req.getUrl();
            if ("https".equals(uri.getScheme()) && SITE.equals(uri.getHost())) return false;
            if ("https".equals(uri.getScheme()) && req.isForMainFrame()) {
                try { startActivity(new Intent(Intent.ACTION_VIEW, uri)); } catch (Exception ignored) { }
            }
            return true;
        }

        @Override public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest req) {
            Uri uri = req.getUrl();
            if (!"https".equals(uri.getScheme()) || !SITE.equals(uri.getHost()))
                return response(403, "text/plain", "应用内禁止加载外部资源");
            if (uri.toString().length() > 4096) return response(400, "application/json", "{\"error\":\"请求过长\"}");
            if (!"GET".equals(req.getMethod())) return response(405, "application/json", "{\"error\":\"只读应用\"}");
            String path = uri.getPath();
            if (path == null) return response(404, "text/plain", "未找到请求的内容");
            if (path.startsWith("/api/maintenance/")) {
                try {
                    if (maintenance == null) return response(503, "application/json", "{\"error\":\"更新模块暂不可用，合约查询仍可使用\"}");
                    if ("/api/maintenance/status".equals(path)) return response(200, "application/json", maintenance.status());
                    if ("/api/maintenance/refresh".equals(path)) return response(200, "application/json", maintenance.refresh("1".equals(uri.getQueryParameter("force"))));
                    if ("/api/maintenance/connect".equals(path)) {
                        String channel = uri.getQueryParameter("url");
                        return response(200, "application/json", maintenance.connect(channel == null ? "" : channel));
                    }
                    return response(404, "application/json", "{\"error\":\"未找到更新功能\"}");
                } catch (Exception ignored) { return response(400, "application/json", "{\"error\":\"更新地址无效或更新检查未完成\"}"); }
            }
            if ("/api/check".equals(path)) {
                String chain = uri.getQueryParameter("chain");
                String address = uri.getQueryParameter("address");
                if (chain == null || address == null || uri.toString().length() > 512)
                    return response(400, "application/json", "{\"error\":\"参数不完整\"}");
                try {
                    if (maintenance != null) Python.getInstance().getModule("android_bridge")
                        .callAttr("configure", maintenance.config(), maintenance.revision());
                    String raw = Python.getInstance().getModule("android_bridge")
                        .callAttr("check_json", chain, address).toString();
                    JSONObject parsed = new JSONObject(raw);
                    if (maintenance != null && !parsed.has("_httpStatus")) maintenance.observeReport(parsed);
                    int code = parsed.optInt("_httpStatus", 200);
                    parsed.remove("_httpStatus");
                    return response(code, "application/json", parsed.toString());
                } catch (Exception ex) {
                    return response(502, "application/json", "{\"error\":\"本机检测服务异常，未生成结论\"}");
                }
            }
            final String file;
            if ("/".equals(path)) file = "index.html";
            else if (path.equals("/index.html") || path.equals("/app.css") || path.equals("/app.js") ||
                     path.equals("/maintenance.js") || path.equals("/manifest.webmanifest") || path.equals("/sw.js") ||
                     path.equals("/icons/icon-192.png") || path.equals("/icons/icon-512.png")) {
                file = path.substring(1);
            } else return response(404, "text/plain", "未找到请求的内容");
            String mime = file.endsWith(".js") ? "text/javascript" : file.endsWith(".css") ? "text/css" :
                file.endsWith(".png") ? "image/png" : file.endsWith(".webmanifest") ? "application/manifest+json" : "text/html";
            try {
                InputStream stream = getAssets().open(file);
                return resource(200, mime, stream);
            } catch (IOException ex) {
                return response(404, "text/plain", "未找到请求的内容");
            }
        }
    }

    private static WebResourceResponse response(int status, String mime, String content) {
        return resource(status, mime, new ByteArrayInputStream(content.getBytes(StandardCharsets.UTF_8)));
    }
    private static WebResourceResponse resource(int status, String mime, InputStream body) {
        Map<String, String> headers = new HashMap<>();
        headers.put("Cache-Control", "no-store");
        headers.put("X-Content-Type-Options", "nosniff");
        headers.put("Referrer-Policy", "no-referrer");
        if (mime.equals("text/html")) headers.put("Content-Security-Policy", "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; manifest-src 'self'; worker-src 'self'; base-uri 'none'; form-action 'self'");
        return new WebResourceResponse(mime, mime.equals("image/png") ? null : "UTF-8",
            status, status == 200 ? "OK" : "Error", headers, body);
    }
}
