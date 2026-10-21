package com.chainshield.radar;

import android.app.Activity;
import android.os.Bundle;
import android.content.SharedPreferences;
import android.content.Intent;
import android.graphics.Insets;
import android.os.Build;
import android.view.WindowInsets;
import android.view.WindowInsetsController;
import android.view.WindowManager;
import android.widget.FrameLayout;
import android.graphics.drawable.ColorDrawable;
import android.webkit.*;
import java.net.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.*;
import org.json.JSONObject;

public final class MainActivity extends Activity {
    private WebView web;
    private SharedPreferences prefs;
    private final ThreadPoolExecutor requests = new ThreadPoolExecutor(1,1,0L,TimeUnit.SECONDS,new ArrayBlockingQueue<>(4));
    private static final String HOST = "appassets.androidplatform.net";
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        prefs = getSharedPreferences("connection", MODE_PRIVATE);
        web = new WebView(this);
        web.setBackgroundColor(0xff0b1420);
        // Resize the WebView viewport, rather than padding its HTML scroll area.
        // Fixed HTML navigation otherwise remains behind Android's navigation bar.
        FrameLayout frame = new FrameLayout(this);
        frame.setBackgroundColor(0xff0b1420);
        frame.addView(web,new FrameLayout.LayoutParams(-1,-1));
        getWindow().setBackgroundDrawable(new ColorDrawable(0xff0b1420));
        getWindow().setStatusBarColor(0xff0b1420);
        getWindow().setNavigationBarColor(0xff0b1420);
        getWindow().setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE);
        getWindow().getDecorView().setSystemUiVisibility(0);
        if (Build.VERSION.SDK_INT >= 29) getWindow().setNavigationBarContrastEnforced(false);
        if (Build.VERSION.SDK_INT >= 30) {
            getWindow().setDecorFitsSystemWindows(false);
            frame.setOnApplyWindowInsetsListener((view,insets)->{
                Insets bars=insets.getInsets(WindowInsets.Type.systemBars() | WindowInsets.Type.displayCutout() | WindowInsets.Type.ime());
                view.setPadding(bars.left,bars.top,bars.right,bars.bottom);
                return WindowInsets.CONSUMED;
            });
        }
        web.getSettings().setJavaScriptEnabled(true);
        web.getSettings().setDomStorageEnabled(true);
        web.getSettings().setAllowFileAccess(false);
        web.getSettings().setAllowContentAccess(false);
        web.getSettings().setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        web.addJavascriptInterface(new Bridge(), "Native");
        web.setWebViewClient(new WebViewClient() {
            @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest r) {
                if (r.isForMainFrame() && "https".equals(r.getUrl().getScheme()) && !HOST.equals(r.getUrl().getHost())) {
                    try { startActivity(new Intent(Intent.ACTION_VIEW,r.getUrl())); } catch (Exception ignored) { }
                }
                return true;
            }
            @Override public WebResourceResponse shouldInterceptRequest(WebView v, WebResourceRequest r) {
                String path = r.getUrl().getPath();
                if (!"https".equals(r.getUrl().getScheme()) || !HOST.equals(r.getUrl().getHost()) || !Arrays.asList("/index.html","/app.js","/app.css").contains(path))
                    return response(403,"text/plain",new ByteArrayInputStream("禁止外部页面".getBytes(StandardCharsets.UTF_8)));
                try {
                    return response(200,path.endsWith("js")?"text/javascript":path.endsWith("css")?"text/css":"text/html",getAssets().open(path.substring(1)));
                } catch (IOException e) { return response(404,"text/plain",new ByteArrayInputStream(new byte[0])); }
            }
        });
        setContentView(frame);
        if (Build.VERSION.SDK_INT >= 30) {
            WindowInsetsController controller=getWindow().getInsetsController();
            if(controller!=null)controller.setSystemBarsAppearance(0,WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS | WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS);
        }
        web.loadUrl("https://" + HOST + "/index.html");
    }
    private static WebResourceResponse response(int code, String mime, InputStream data) {
        Map<String,String> headers = new HashMap<>();
        headers.put("Content-Security-Policy", "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'none'; base-uri 'none'; form-action 'none'");
        headers.put("Cache-Control", "no-store");
        headers.put("X-Content-Type-Options", "nosniff");
        return new WebResourceResponse(mime,"UTF-8",code,code==200?"OK":"Error",headers,data);
    }
    private static String error(String message) {
        try { return new JSONObject().put("error",message).toString(); } catch (Exception e) { return "{}"; }
    }
    public final class Bridge {
        @JavascriptInterface public String config() {
            try { return new JSONObject().put("url",prefs.getString("url","")).put("hasToken",!prefs.getString("token","").isEmpty()).toString(); }
            catch (Exception e) { return error("读取连接设置失败"); }
        }
        @JavascriptInterface public String configure(String base, String token) {
            try {
                URI uri = new URI(base.trim());
                if (!"https".equals(uri.getScheme()) || uri.getHost()==null || uri.getUserInfo()!=null || uri.getQuery()!=null || uri.getFragment()!=null || !(uri.getPath().isEmpty() || uri.getPath().equals("/")))
                    return error("请输入 HTTPS 服务器根地址");
                String secret = token.isEmpty() ? prefs.getString("token","") : token;
                if (secret.length()<32 || secret.length()>512 || !secret.matches("[\\x21-\\x7E]+")) return error("访问密钥需要32至512位可见ASCII字符");
                prefs.edit().putString("url",base.trim().replaceAll("/+$", "")).putString("token",secret).commit();
                return "{\"ok\":true}";
            } catch (Exception e) { return error("服务器地址格式错误"); }
        }
        @JavascriptInterface public String request(String path, String body) {
            HttpURLConnection conn = null;
            try {
                if (!body.isEmpty() || !(path.equals("/api/state") || path.equals("/api/radar/state") || path.matches("/api/check\\?chain=sol&address=[1-9A-HJ-NP-Za-km-z]{32,44}"))) return error("只允许读取观察数据或手动安全查询");
                if (path.length()>1024 || !path.startsWith("/api/") || path.contains("\r") || path.contains("\n")) return error("请求格式错误");
                String base = prefs.getString("url","");
                if (base.isEmpty()) return error("请先在系统设置连接服务器");
                conn = (HttpURLConnection) new URL(base+path).openConnection();
                conn.setInstanceFollowRedirects(false);
                conn.setConnectTimeout(10000);
                conn.setReadTimeout(25000);
                conn.setRequestProperty("Authorization", "Bearer " + prefs.getString("token",""));
                int status = conn.getResponseCode();
                if (status>=300 && status<400) return error("服务器跳转已拦截，请检查根地址");
                InputStream stream = status<400 ? conn.getInputStream() : conn.getErrorStream();
                if (stream==null) return error("服务器没有返回数据");
                ByteArrayOutputStream bytes=new ByteArrayOutputStream();
                try (InputStream in=stream) {
                    byte[] buf=new byte[8192]; int n;
                    while ((n=in.read(buf))!=-1) { bytes.write(buf,0,n); if (bytes.size()>2_000_000) return error("服务器响应过大"); }
                }
                return new JSONObject(bytes.toString("UTF-8")).put("_http_status",status).toString();
            } catch (Exception e) { return error("连接失败，请检查地址、证书、密钥及网络"); }
            finally { if(conn!=null) conn.disconnect(); }
        }
        @JavascriptInterface public void requestAsync(String path, String id) {
            if (!id.matches("[0-9]{1,12}")) return;
            try { requests.execute(()->{
                String result=request(path,"");
                runOnUiThread(()->{ if(!isDestroyed()) web.evaluateJavascript("window.nativeResult("+JSONObject.quote(id)+","+JSONObject.quote(result)+")",null); });
            }); } catch(RejectedExecutionException ignored) {
                runOnUiThread(()->web.evaluateJavascript("window.nativeResult("+JSONObject.quote(id)+","+JSONObject.quote(error("请求队列繁忙，请稍后刷新"))+")",null));
            }
        }
        @JavascriptInterface public String copyMint(String mint) {
            if (!mint.matches("[1-9A-HJ-NP-Za-km-z]{32,44}")) return error("Mint地址格式错误");
            runOnUiThread(()->((android.content.ClipboardManager)getSystemService(CLIPBOARD_SERVICE)).setPrimaryClip(android.content.ClipData.newPlainText("Mint",mint)));
            return "{\"ok\":true}";
        }
    }
    @Override protected void onDestroy() { requests.shutdownNow(); web.removeJavascriptInterface("Native"); web.destroy(); super.onDestroy(); }
}
