'use strict';
(() => {
  const $ = id => document.getElementById(id);
  let busy = false;
  function show(state) {
    $('maintenanceMessage').textContent = state.message || '尚未检查维护配置';
    $('maintenanceMeta').textContent = `应用版本：${state.version || '1.6'} · ${state.revision || '内置配置'}` +
      (state.checked_at ? ` · 最近成功检查：${new Date(state.checked_at).toLocaleString('zh-CN')}` : ' · 尚无成功更新记录');
    if (document.activeElement !== $('channelUrl')) $('channelUrl').value = state.channel || '';
    const names = {'api.gopluslabs.io':'GoPlus', 'api.honeypot.is':'Honeypot.is', 'api.rugcheck.xyz':'RugCheck'};
    const sources = (state.health || {}).sources || {};
    $('maintenanceHealth').textContent = Object.keys(sources).filter(key => names[key]).map(key => `${names[key]}：${sources[key].cooling ? '短暂冷却，稍后重试' : sources[key].state === '可用' ? '最近连接成功' : '最近连接失败'}`).join('；');
    const app = state.new_version;
    const valid = app && /^https:\/\/github\.com\/[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+\/releases\/tag\/[A-Za-z0-9_.-]+$/.test(app.release_url || '');
    $('appUpdate').hidden = !valid;
    if (valid) {
      $('newVersion').textContent = `发现新版本：${app.version_name}`;
      $('updateNotes').textContent = /[\u3400-\u9fff]/.test(app.notes_zh || '') ? app.notes_zh : '新版应用已发布，请查看发布说明。';
      $('updateLink').href = app.release_url;
    } else $('updateLink').removeAttribute('href');
  }
  async function request(path) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 16000);
    try {
      const response = await fetch(path, {cache:'no-store', signal:controller.signal});
      const state = await response.json();
      if (!response.ok) throw new Error('维护检查暂未完成，请稍后重试');
      return state;
    } finally { clearTimeout(timer); }
  }
  async function check(force = false, channel = null) {
    if (busy) return;
    busy = true;
    $('checkUpdates').disabled = true;
    $('connectUpdates').disabled = true;
    try {
      const route = channel !== null ? `/api/maintenance/connect?url=${encodeURIComponent(channel)}` : `/api/maintenance/refresh?force=${force ? '1' : '0'}`;
      show(await request(route));
    } catch (ignored) {
      $('maintenanceMessage').textContent = '维护服务暂时无法连接，合约查询仍可使用；稍后会重新检查。';
    } finally {
      busy = false;
      $('checkUpdates').disabled = false;
      $('connectUpdates').disabled = false;
    }
  }
  $('checkUpdates').addEventListener('click', () => check(true));
  $('connectUpdates').addEventListener('click', () => {
    const channel = $('channelUrl').value.trim();
    if (!/^https:\/\//.test(channel)) {
      $('maintenanceMessage').textContent = '请粘贴发布方提供的安全更新地址。';
      return;
    }
    check(true, channel);
  });
  if (location.hostname === 'appassets.androidplatform.net') {
    request('/api/maintenance/status').then(show).catch(() => {});
    check();
    document.addEventListener('visibilitychange', () => { if (!document.hidden) check(); });
    setInterval(() => { if (!document.hidden) check(); }, 6 * 60 * 60 * 1000);
  } else {
    $('maintenanceMessage').textContent = '浏览器预览仅展示界面；自动维护在安卓应用内运行。';
  }
})();
