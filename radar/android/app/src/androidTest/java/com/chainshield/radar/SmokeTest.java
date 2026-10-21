package com.chainshield.radar;
import android.app.*;import android.content.Intent;import android.os.Bundle;import android.view.*;import android.webkit.WebView;import org.json.JSONObject;import java.util.concurrent.*;
public class SmokeTest extends Instrumentation {
 private boolean finalOnly;
 private WebView find(View v){if(v instanceof WebView)return(WebView)v;if(v instanceof ViewGroup){ViewGroup g=(ViewGroup)v;for(int i=0;i<g.getChildCount();i++){WebView w=find(g.getChildAt(i));if(w!=null)return w;}}return null;}
 private String js(WebView w,String code)throws Exception{CountDownLatch l=new CountDownLatch(1);String[] r={""};runOnMainSync(()->w.evaluateJavascript(code,v->{r[0]=v;l.countDown();}));if(!l.await(55,TimeUnit.SECONDS))throw new Exception("JS超时");return r[0];}
 private void require(boolean ok,String s)throws Exception{if(!ok)throw new Exception(s);Bundle b=new Bundle();b.putString("检查",s);sendStatus(0,b);}
 @Override public void onCreate(Bundle args){super.onCreate(args);finalOnly="true".equals(args.getString("finalOnly"));start();}
 @Override public void onStart(){Bundle result=new Bundle();try{
  MainActivity a=(MainActivity)startActivitySync(new Intent(getTargetContext(),MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));WebView w=find(a.getWindow().getDecorView());require(w!=null,"APK安装启动");
  for(int i=0;i<40;i++){if("true".equals(js(w,"typeof window.show==='function'&&document.querySelectorAll('nav button').length===4")))break;Thread.sleep(250);}
  require("4".equals(js(w,"document.querySelectorAll('nav button').length")),"四个中文页面加载");
  for(String p:new String[]{"overview","hotspots","candidates","settings"})require("true".equals(js(w,"show('"+p+"');!document.getElementById('"+p+"').hidden")),"页面切换："+p);
  require("true".equals(js(w,"(()=>{let r=document.querySelector('nav').getBoundingClientRect();return r.bottom<=innerHeight+1&&[...document.querySelectorAll('nav button')].every(b=>b.getBoundingClientRect().height>=48)})()")),"导航位于视口且触摸高度足够");
  MainActivity.Bridge bridge=a.new Bridge();require(new JSONObject(bridge.request("/api/entry","{\"enabled\":true}")).has("error"),"APK拒绝模拟入场操作");require(new JSONObject(bridge.request("/api/social/import","{}")).has("error"),"APK拒绝写入操作");require(new JSONObject(bridge.configure("http://example.com","test-token-00000000000000000000000000")).has("error"),"拒绝明文HTTP");
  if(finalOnly){
   require(new JSONObject(bridge.configure("https://47-74-37-164.sslip.io","invalid-readonly-probe-token-000000000000")).optBoolean("ok"),"真实HTTPS目标配置（无生产密钥）");
   JSONObject r=new JSONObject(bridge.request("/api/state",""));require(r.optInt("_http_status")==401,"交付APK连接阿里云真实HTTPS并收到401，证书校验有效");
   require(new JSONObject(bridge.configure("https://10.0.2.2:9443","radar-ci-readonly-test-token-0000000000")).optBoolean("ok"),"无测试CA版本配置");
   require(new JSONObject(bridge.request("/api/radar/state","")).has("error"),"交付APK拒绝CI自签证书");
  }else{
   require(new JSONObject(bridge.configure("https://10.0.2.2:9443","radar-ci-readonly-test-token-0000000000")).optBoolean("ok"),"CI受控HTTPS配置");
   JSONObject r=new JSONObject(bridge.request("/api/radar/state",""));require(r.optInt("schema_version")==1,"受控HTTPS读取快照（测试夹具，不是生产端到端）");
   js(w,"show('settings');document.getElementById('server').value='https://10.0.2.2:9443';document.getElementById('save').click();true");
   boolean loaded=false;for(int i=0;i<60;i++){Thread.sleep(250);if("true".equals(js(w,"document.getElementById('mints').textContent.includes('CI测试币')&&document.getElementById('connection').textContent.includes('已连接')"))){loaded=true;break;}}
   require(loaded,"异步刷新展示新Mint夹具");
   require("true".equals(js(w,"document.getElementById('posts').textContent.includes('CI测试热点')")),"热点原文与时间展示");
   require("true".equals(js(w,"document.getElementById('candidate-list').textContent.includes('未人工确认')&&document.getElementById('candidate-list').textContent.includes('0.800秒')")),"候选文字证据、未知创建时间及接收延迟展示");
   require("true".equals(js(w,"document.getElementById('grade').value='audit';document.getElementById('grade').dispatchEvent(new Event('change'));document.getElementById('candidate-list').textContent.includes('证据不足')")),"弱关联审计与候选分开");
   js(w,"document.getElementById('grade').value='all';document.getElementById('grade').dispatchEvent(new Event('change'));show('overview');true");
  }
  CountDownLatch painted=new CountDownLatch(1);runOnMainSync(()->w.postVisualStateCallback(android.os.SystemClock.uptimeMillis(),new WebView.VisualStateCallback(){@Override public void onComplete(long id){painted.countDown();}}));require(painted.await(10,TimeUnit.SECONDS),"等待页面实际绘制");
  android.graphics.Bitmap shot=getUiAutomation().takeScreenshot();try(java.io.FileOutputStream out=getTargetContext().openFileOutput(finalOnly?"final-apk.png":"observe-overview.png",0)){shot.compress(android.graphics.Bitmap.CompressFormat.PNG,100,out);}shot.recycle();
  result.putString("结果",finalOnly?"交付APK安装启动及真实HTTPS鉴权边界通过；未使用生产密钥":"受控快照展示验证通过；不代表生产完整接入");finish(Activity.RESULT_OK,result);
 }catch(Exception e){result.putString("错误",e.toString());finish(Activity.RESULT_CANCELED,result);}}
}
