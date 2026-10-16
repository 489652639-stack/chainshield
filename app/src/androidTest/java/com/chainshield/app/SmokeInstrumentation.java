package com.chainshield.app;

import android.app.Activity;
import android.app.Instrumentation;
import android.content.Intent;
import android.os.Bundle;
import android.util.Base64;
import android.view.View;
import android.view.ViewGroup;
import android.webkit.WebView;
import com.chaquo.python.Python;
import org.json.JSONArray;
import org.json.JSONObject;
import org.json.JSONTokener;
import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

/** Runs in an installed APK on Android. No fixtures are used in the three live scans.
 * Optional proxy/CA arguments configure only the test process, never the shipped APK.
 */
public final class SmokeInstrumentation extends Instrumentation {
    private Bundle arguments;
    private WebView web;
    private final JSONArray results = new JSONArray();
    private File testCa;

    @Override public void onCreate(Bundle args) {
        arguments = args == null ? new Bundle() : args;
        start();
    }

    @Override public void onStart() {
        Bundle output = new Bundle();
        try {
            Intent intent = new Intent(Intent.ACTION_MAIN);
            intent.setClassName(getTargetContext(), "com.chainshield.app.MainActivity");
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            Activity activity = startActivitySync(intent);
            runOnMainSync(() -> web = findWeb(activity.getWindow().getDecorView()));
            if (web == null) throw new AssertionError("No WebView after launch");
            waitJs("document.readyState === 'complete' && !!document.querySelector('#scan')", 60000);
            if (!Boolean.TRUE.equals(eval("document.documentElement.lang === 'zh-CN'")))
                throw new AssertionError("Chinese UI missing");
            record("install_launch_chinese_ui", "passed", null);

            configureTestNetwork();
            eval("document.querySelector('#checkUpdates').click();true");
            waitJs("/维护配置已通过签名校验|已加载经过签名校验/.test(document.querySelector('#maintenanceMessage').textContent)", 30000);
            record("live_signed_maintenance_channel", "passed", null);
            scan("bnb", "0x55d398326f99059ff775485246999027b3197955");
            scan("eth", "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48");
            scan("sol", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v");

            eval("document.querySelector('#address').value='invalid';document.querySelector('#scan').click();true");
            waitJs("!document.querySelector('#inputError').hidden", 5000);
            record("invalid_address_validation", "passed", null);

            // Deliberate offline regression, distinct from the live checks above.
            Python.getInstance().getModule("builtins").callAttr("exec",
                "import engine, android_bridge\n"
                + "_qa_original_get_json = engine.get_json\n"
                + "def _qa_offline(*args, **kwargs):\n    raise engine.DataError('测试断网')\n"
                + "engine.get_json = _qa_offline\nandroid_bridge._CACHE.clear()\n",
                Python.getInstance().getModule("__main__").get("__dict__"));
            try {
                eval("document.querySelector('[data-chain=bnb]').click();document.querySelector('#address').value='0x55d398326f99059ff775485246999027b3197955';document.querySelector('#scan').click();true");
                waitJs("!document.querySelector('#results').hidden && !!document.querySelector('.result-head')", 10000);
                if (!Boolean.TRUE.equals(eval("document.querySelector('#results').textContent.includes('检测服务暂不可用') && !document.querySelector('.finding-status.ok')")))
                    throw new AssertionError("Offline response was marked clean");
                record("offline_never_safe_mock", "passed", null);
            } finally {
                Python.getInstance().getModule("builtins").callAttr("exec", "engine.get_json = _qa_original_get_json\nandroid_bridge._CACHE.clear()\n",
                    Python.getInstance().getModule("__main__").get("__dict__"));
            }
            eval("document.querySelector('#clear').click();true");
            if (!Boolean.TRUE.equals(eval("document.querySelector('#address').value === '' && document.querySelector('#results').hidden")))
                throw new AssertionError("Clear failed");
            record("clear_input_and_results", "passed", null);
            output.putString("stream", "\nCHAINSHIELD_TESTS=" + results.toString() + "\n");
            finish(Activity.RESULT_OK, output);
        } catch (Throwable error) {
            output.putString("stream", "\nCHAINSHIELD_TESTS=" + results.toString() + "\nFAIL=" + error.toString() + "\n");
            finish(Activity.RESULT_CANCELED, output);
        } finally {
            if (testCa != null) testCa.delete();
        }
    }

    private void configureTestNetwork() throws Exception {
        String proxy = arguments.getString("networkProxy", "");
        String ca = arguments.getString("caCertificateBase64", "");
        if (!proxy.isEmpty()) {
            Python.getInstance().getModule("os").get("environ").callAttr("__setitem__", "https_proxy", proxy);
            Python.getInstance().getModule("os").get("environ").callAttr("__setitem__", "http_proxy", proxy);
        }
        if (!ca.isEmpty()) {
            testCa = new File(getTargetContext().getFilesDir(), "qa-network-ca.pem");
            try (FileOutputStream stream = new FileOutputStream(testCa)) { stream.write(Base64.decode(ca, Base64.DEFAULT)); }
            Python.getInstance().getModule("os").get("environ").callAttr("__setitem__", "SSL_CERT_FILE", testCa.getAbsolutePath());
        }
    }

    private void scan(String chain, String address) throws Exception {
        long started = System.currentTimeMillis();
        eval("document.querySelector('[data-chain=" + chain + "]').click();document.querySelector('#address').value=" + JSONObject.quote(address) + ";document.querySelector('#scan').click();true");
        waitJs("!document.querySelector('#results').hidden && !document.querySelector('#scan').disabled", 40000);
        Object state = eval("JSON.stringify({title:document.querySelector('#results h2')?.textContent||'',address:document.querySelector('.address-box')?.textContent||'',rows:document.querySelectorAll('.finding').length,okSources:document.querySelectorAll('.provider-state.good').length,providers:Array.from(document.querySelectorAll('.provider-line')).map(x=>x.innerText),horizontalOverflow:document.documentElement.scrollWidth>innerWidth+1})");
        JSONObject snapshot = new JSONObject(String.valueOf(state));
        snapshot.put("elapsedMs", System.currentTimeMillis()-started);
        boolean sameAddress = "sol".equals(chain) ? address.equals(snapshot.optString("address")) : address.equalsIgnoreCase(snapshot.optString("address"));
        if (!sameAddress || snapshot.optInt("rows") < 10 || snapshot.optBoolean("horizontalOverflow"))
            throw new AssertionError("Query UI failed: " + snapshot);
        record("live_"+chain+"_one_click", snapshot.optInt("okSources")==2 ? "passed" : "partial", snapshot);
    }

    private Object eval(String script) throws Exception {
        CountDownLatch latch = new CountDownLatch(1);
        AtomicReference<String> value = new AtomicReference<>();
        runOnMainSync(() -> web.evaluateJavascript(script, result -> { value.set(result); latch.countDown(); }));
        if (!latch.await(15, TimeUnit.SECONDS)) throw new AssertionError("WebView JavaScript timeout");
        return new JSONTokener(value.get() == null ? "null" : value.get()).nextValue();
    }

    private void waitJs(String expression, long timeoutMs) throws Exception {
        long deadline = System.currentTimeMillis()+timeoutMs;
        while (System.currentTimeMillis()<deadline) {
            if (Boolean.TRUE.equals(eval(expression))) return;
            Thread.sleep(200);
        }
        throw new AssertionError("Condition timeout: " + expression);
    }

    private void record(String name, String status, JSONObject details) throws Exception {
        JSONObject result = new JSONObject().put("test",name).put("status",status);
        if (details != null) result.put("details", details);
        results.put(result);
        Bundle event = new Bundle(); event.putString("stream", result.toString()+"\n"); sendStatus(0,event);
    }

    private WebView findWeb(View view) {
        if (view instanceof WebView) return (WebView)view;
        if (view instanceof ViewGroup) {
            ViewGroup group = (ViewGroup)view;
            for (int i=0;i<group.getChildCount();i++) { WebView found=findWeb(group.getChildAt(i)); if(found!=null)return found; }
        }
        return null;
    }
}
