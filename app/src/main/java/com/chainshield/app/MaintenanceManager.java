package com.chainshield.app;

import android.content.Context;
import android.content.SharedPreferences;
import android.util.Base64;
import com.chaquo.python.Python;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import javax.net.ssl.HttpsURLConnection;

/** Signed declarative updates only. Core executable code always ships inside the APK. */
final class MaintenanceManager {
    private final Context context;
    private final SharedPreferences prefs;
    private final File activeFile;
    private final byte[] publicKey;
    private final AtomicBoolean checking = new AtomicBoolean(false);
    private final AtomicInteger reportFailures = new AtomicInteger(0);
    private volatile JSONObject active;
    private volatile String lastMessage = "尚未检查更新";

    MaintenanceManager(Context context) throws Exception {
        this.context = context;
        prefs = context.getSharedPreferences("maintenance", Context.MODE_PRIVATE);
        activeFile = new File(context.getFilesDir(), "maintenance-channel.json");
        try (InputStream stream = context.getAssets().open("maintenance-public.der")) {
            publicKey = read(stream, 4096);
        }
        if (!prefs.contains("channel")) {
            try (InputStream stream = context.getAssets().open("channel-bootstrap.json")) {
                String initial = new JSONObject(new String(read(stream, 4096), StandardCharsets.UTF_8)).optString("url", "");
                if (!initial.isEmpty() && validUrl(initial)) prefs.edit().putString("channel", initial).apply();
            }
        }
        if (activeFile.isFile()) {
            try (InputStream stream = new FileInputStream(activeFile)) {
                active = validate(read(stream, 100000));
                lastMessage = "已加载经过签名校验的维护配置";
            } catch (Exception ignored) { lastMessage = "上次维护配置不可用，已恢复内置配置"; }
        }
    }

    static boolean validUrl(String value) {
        try {
            URL url = new URL(value);
            String host = url.getHost();
            return value.length() <= 2048 && "https".equals(url.getProtocol()) && url.getUserInfo() == null
                && url.getPort() == -1 && url.getRef() == null
                && (host.matches("[a-zA-Z0-9-]+\\.github\\.io") || host.equals("raw.githubusercontent.com"))
                && url.getPath().endsWith(".json");
        } catch (Exception ignored) { return false; }
    }

    private JSONObject validate(byte[] envelopeBytes) throws Exception {
        JSONObject envelope = new JSONObject(new String(envelopeBytes, StandardCharsets.UTF_8));
        if (!"RSA-SHA256".equals(envelope.getString("algorithm"))) throw new Exception("签名算法无效");
        byte[] payload = Base64.decode(envelope.getString("payload"), Base64.NO_WRAP);
        byte[] signature = Base64.decode(envelope.getString("signature"), Base64.NO_WRAP);
        if (!ChannelSignature.verify(publicKey, payload, signature)) throw new Exception("维护配置签名校验失败");
        String validated = Python.getInstance().getModule("runtime_policy").callAttr("validate_channel",
            new String(payload, StandardCharsets.UTF_8), BuildConfig.VERSION_CODE, prefs.getLong("floor", 0)).toString();
        JSONObject result = new JSONObject(validated);
        if (result.getLong("sequence") == prefs.getLong("quarantined", -1)) throw new Exception("已隔离本次故障配置");
        return result;
    }

    private JSONObject current() {
        JSONObject result = active;
        if (result != null && result.optLong("expires_at") <= System.currentTimeMillis() / 1000) {
            active = null;
            lastMessage = "在线配置已过期，已恢复内置配置，等待重新连接更新服务";
            return null;
        }
        return result;
    }

    String config() {
        JSONObject data = current();
        return data == null ? "{}" : data.optJSONObject("config").toString();
    }

    String revision() {
        JSONObject data = current();
        return data == null ? "内置配置" : "在线配置 " + data.optLong("sequence");
    }

    String status() throws Exception {
        JSONObject data = current();
        JSONObject result = new JSONObject();
        result.put("connected", !prefs.getString("channel", "").isEmpty());
        result.put("channel", prefs.getString("channel", ""));
        result.put("revision", revision());
        result.put("message", prefs.getString("channel", "").isEmpty() ? "更新服务尚未连接，当前使用内置配置" : lastMessage);
        result.put("checked_at", prefs.getLong("lastCheck", 0));
        result.put("checking", checking.get());
        result.put("version", BuildConfig.VERSION_NAME);
        result.put("new_version", data != null && data.optJSONObject("app") != null
            && data.getJSONObject("app").optInt("version_code") > BuildConfig.VERSION_CODE ? data.getJSONObject("app") : JSONObject.NULL);
        result.put("health", new JSONObject(Python.getInstance().getModule("runtime_policy").callAttr("health_json").toString()));
        return result.toString();
    }

    String connect(String url) throws Exception {
        if (!validUrl(url)) throw new IllegalArgumentException("请输入受支持的安全更新地址");
        prefs.edit().putString("channel", url).putLong("lastAttempt", 0).apply();
        return refresh(true);
    }

    String refresh(boolean force) throws Exception {
        String channel = prefs.getString("channel", "");
        if (channel.isEmpty() || !checking.compareAndSet(false, true)) return status();
        long now = System.currentTimeMillis();
        HttpsURLConnection connection = null;
        try {
            long retryAfter = prefs.getLong("nextCheck", 0);
            if (!force && now < retryAfter) return status();
            prefs.edit().putLong("lastAttempt", now).putLong("nextCheck", now + 15 * 60 * 1000).apply();
            connection = (HttpsURLConnection) new URL(channel).openConnection();
            connection.setInstanceFollowRedirects(false);
            connection.setConnectTimeout(6000);
            connection.setReadTimeout(6000);
            connection.setUseCaches(false);
            connection.setRequestProperty("Accept", "application/json");
            connection.setRequestProperty("Cache-Control", "no-cache");
            if (connection.getResponseCode() != 200) throw new Exception("更新服务未返回有效数据");
            byte[] envelope;
            try (InputStream stream = connection.getInputStream()) { envelope = read(stream, 100000); }
            JSONObject next = validate(envelope);
            JSONObject previous = current();
            if (previous != null && next.getLong("sequence") == previous.getLong("sequence") && !next.toString().equals(previous.toString()))
                throw new Exception("相同版本的维护配置发生变化，已拒绝替换");
            File temp = new File(context.getFilesDir(), "maintenance-channel.pending");
            try (FileOutputStream output = new FileOutputStream(temp)) {
                output.write(envelope); output.getFD().sync();
            }
            if (!temp.renameTo(activeFile)) throw new Exception("维护配置保存失败");
            prefs.edit().putLong("floor", next.getLong("sequence")).putLong("lastCheck", now)
                .putLong("nextCheck", now + 6 * 60 * 60 * 1000).commit();
            active = next;
            reportFailures.set(0);
            lastMessage = "维护配置已通过签名校验并更新；查询异常时会自动重试";
        } catch (Exception ignored) {
            lastMessage = "更新检查失败，已保留仍有效的上次配置或内置配置；稍后自动重试";
        } finally {
            if (connection != null) connection.disconnect();
            checking.set(false);
        }
        return status();
    }

    void observeReport(JSONObject report) {
        JSONObject policy = current();
        if (policy == null) return;
        // Never undo an explicit operator security shutdown of a data source.
        if (policy.optJSONObject("config").optJSONArray("disabled").length() > 0) return;
        JSONObject sources = report.optJSONObject("sources");
        if (sources == null) return;
        java.util.Iterator<String> names = sources.keys();
        while (names.hasNext()) {
            JSONObject source = sources.optJSONObject(names.next());
            if (source != null && "ok".equals(source.optString("status"))) {
                reportFailures.set(0);
                return;
            }
        }
        if (reportFailures.incrementAndGet() >= 3) {
            prefs.edit().putLong("quarantined", policy.optLong("sequence")).commit();
            active = null;
            activeFile.delete();
            lastMessage = "连续查询失败，已隔离本次在线配置并恢复内置配置，等待维护服务发布修复";
        }
    }

    private static byte[] read(InputStream stream, int limit) throws Exception {
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        byte[] bytes = new byte[4096];
        int count;
        while ((count = stream.read(bytes)) != -1) {
            if (output.size() + count > limit) throw new Exception("维护数据超过大小限制");
            output.write(bytes, 0, count);
        }
        return output.toByteArray();
    }
}
