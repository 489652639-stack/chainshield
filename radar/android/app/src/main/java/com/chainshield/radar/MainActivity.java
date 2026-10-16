package com.chainshield.radar;

import android.app.Activity;
import android.os.Bundle;
import android.content.SharedPreferences;
import android.webkit.*;
import java.net.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import org.json.JSONObject;

public final class MainActivity extends Activity {
    private WebView web;
    private SharedPreferences prefs;
    private static final String HOST = "appassets.androidplatform.net";
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        prefs = getSharedPreferences("connection", MODE_PRIVATE);
        web = new WebView(this);
        web.setBackgroundColor(0xff0b1420);
        web.getSettings().setJavaScriptEnabled(true);
        web.getSettings().setDomStorageEnabled(true);
        web.getSettings().setAllowFileAccess(false);
        web.getSettings().setAllowContentAccess(false);
        web.getSettings().setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        web.addJavascriptInterface(new Bridge(), "Native");
        web.setWebViewClient(new WebViewClient() {
            @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest r) { return true; }
            @Override public WebResourceResponse shouldInterceptRequest(WebView v, WebResourceRequest r) {
                String path = r.getUrl().getPath();
                if (!"https".equals(r.getUrl().getScheme()) || !HOST.equals(r.getUrl().getHost()) || !Arrays.asList("/index.html","/app.js","/app.css").contains(path))
                    return response(403,"text/plain",new ByteArrayInputStream("禁止外部页面".getBytes(StandardCharsets.UTF_8)));
                try {
                    return response(200,path.endsWith("js")?"text/javascript":path.endsWith("css")?"text/css":"text/html",getAssets().open(path.substring(1)));
                } catch (IOException e) { return response(404,"text/plain",new ByteArrayInputStream(new byte[0])); }
            }
        });
        setContentView(web);
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
                if (secret.length()<32) return error("访问密钥至少32位");
                prefs.edit().putString("url",base.trim().replaceAll("/+$", "")).putString("token",secret).commit();
                return "{\"ok\":true}";
            } catch (Exception e) { return error("服务器地址格式错误"); }
        }
        @JavascriptInterface public String request(String path, String body) {
            HttpURLConnection conn = null;
            try {
                if (!(path.equals("/api/state") || path.startsWith("/api/check?") || path.equals("/api/entry"))) return error("不支持该操作");
                if (path.length()>1024 || !path.startsWith("/api/") || path.contains("\r") || path.contains("\n")) return error("请求格式错误");
                String base = prefs.getString("url","");
                if (base.isEmpty()) return error("请先在系统设置连接服务器");
                conn = (HttpURLConnection) new URL(base+path).openConnection();
                conn.setInstanceFollowRedirects(false);
                conn.setConnectTimeout(10000);
                conn.setReadTimeout(40000);
                conn.setRequestProperty("Authorization", "Bearer " + prefs.getString("token",""));
                if (!body.isEmpty()) {
                    if (!path.equals("/api/entry")) return error("不支持该操作");
                    conn.setRequestMethod("POST"); conn.setDoOutput(true);
                    conn.setRequestProperty("Content-Type", "application/json");
                    try (OutputStream out=conn.getOutputStream()) { out.write(body.getBytes(StandardCharsets.UTF_8)); }
                }
                int status = conn.getResponseCode();
                if (status>=300 && status<400) return error("服务器跳转已拦截，请检查根地址");
                InputStream stream = status<400 ? conn.getInputStream() : conn.getErrorStream();
                if (stream==null) return error("服务器没有返回数据");
                ByteArrayOutputStream bytes=new ByteArrayOutputStream();
                try (InputStream in=stream) {
                    byte[] buf=new byte[8192]; int n;
                    while ((n=in.read(buf))!=-1) { bytes.write(buf,0,n); if (bytes.size()>2_000_000) return error("服务器响应过大"); }
                }
                return bytes.toString("UTF-8");
            } catch (Exception e) { return error("连接失败，请检查地址、证书、密钥及网络"); }
            finally { if(conn!=null) conn.disconnect(); }
        }
    }
    @Override protected void onDestroy() { web.removeJavascriptInterface("Native"); web.destroy(); super.onDestroy(); }
}
