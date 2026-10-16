package com.chainshield.radar;
import android.app.*;
import android.content.Intent;
import android.os.Bundle;
import android.webkit.WebView;
import android.view.*;
import org.json.JSONObject;
import java.util.concurrent.*;

public class SmokeTest extends Instrumentation {
    private WebView find(View v) { if(v instanceof WebView)return (WebView)v;if(v instanceof ViewGroup){ViewGroup g=(ViewGroup)v;for(int i=0;i<g.getChildCount();i++){WebView w=find(g.getChildAt(i));if(w!=null)return w;}}return null; }
    private String js(WebView web,String code) throws Exception {
        CountDownLatch latch=new CountDownLatch(1);String[] result={""};
        runOnMainSync(()->web.evaluateJavascript(code,v->{result[0]=v;latch.countDown();}));
        if(!latch.await(65,TimeUnit.SECONDS))throw new Exception("页面执行超时");return result[0];
    }
    private void require(boolean ok,String text)throws Exception{if(!ok)throw new Exception(text);Bundle b=new Bundle();b.putString("检查",text);sendStatus(0,b);}
    @Override public void onCreate(Bundle args){super.onCreate(args);start();}
    @Override public void onStart(){Bundle result=new Bundle();try{
        MainActivity a=(MainActivity)startActivitySync(new Intent(getTargetContext(),MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
        WebView web=find(a.getWindow().getDecorView());require(web!=null,"安卓应用启动");
        for(int i=0;i<30;i++){if("4".equals(js(web,"document.querySelectorAll('nav button').length")))break;Thread.sleep(300);}
        require("4".equals(js(web,"document.querySelectorAll('nav button').length")),"四个中文页面加载");
        for(String page:new String[]{"radar","shield","trade","settings"})require("true".equals(js(web,"show('"+page+"');!document.getElementById('"+page+"').hidden")),"页面切换："+page);
        MainActivity.Bridge bridge=a.new Bridge();
        require(new JSONObject(bridge.configure("https://10.0.2.2:9443","radar-ci-readonly-test-token-0000000000")).optBoolean("ok"),"服务器配置");
        JSONObject state=new JSONObject(bridge.request("/api/state",""));
        require("模拟交易".equals(state.optString("mode"))&&state.getInt("budget_cny")==100&&!state.optBoolean("live_available"),"真实服务器连接与模拟模式");
        require(new JSONObject(bridge.request("/api/entry","{\"enabled\":false}")).getBoolean("enabled")==false,"暂停模拟入场接口");
        require(new JSONObject(bridge.request("/api/live","{}")).has("error"),"实盘入口关闭");
        js(web,"show('shield');document.getElementById('address').value='So11111111111111111111111111111111111111112';document.getElementById('check').click();true");
        boolean queried=false;
        for(int i=0;i<90;i++){Thread.sleep(1000);if("true".equals(js(web,"document.getElementById('report').children.length>5"))){queried=true;break;}}
        require(queried,"一键索拉纳查询并展示检测项（允许明确未知）");
        result.putString("结果","全部设备检查通过；真实接口细节见独立探针报告");finish(Activity.RESULT_OK,result);
    }catch(Exception e){result.putString("错误",e.toString());finish(Activity.RESULT_CANCELED,result);}}
}
