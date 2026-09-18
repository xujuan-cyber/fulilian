#!/usr/bin/env node
/**
 * 小红书关键词采集脚本 (CDP + Pinia)
 * 
 * 原理：通过 Chrome DevTools Protocol 连接到浏览器，
 * 利用页面内 Vue 3 Pinia store 的 searchNotes() 方法翻页，
 * 绕过 X-s/X-S-Common 签名限制。
 * 
 * 用法：
 *   node xhs_collect.js --keyword AI生成 --max 50
 * 
 * 依赖：ws (Node.js WebSocket 库)
 * 输出：CSV + JSONL 到 bazhuayu_output/<date>/exports/
 */

const WebSocket = require('ws');
const http = require('http');
const fs = require('fs');

// ============ 配置 ============
const CONFIG = {
  chromePort: 9555,
  userDataDir: '/home/xujuan/bazhuayu_output/xhs_browser_profile',
  sessionFile: '/home/xujuan/.octopus/browser-sessions/xhs-login-ai.json',
  outputBase: '/home/xujuan/bazhuayu_output',
  pageSize: 20,
};

// ============ 工具函数 ============
function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }
function httpGet(url) {
  return new Promise((resolve, reject) => {
    http.get(url, (res) => { let d = ''; res.on('data', c => d += c); res.on('end', () => resolve(d)); }).on('error', reject);
  });
}
function escapeCSV(s) {
  if (!s) return '""';
  return '"' + String(s).replace(/"/g, '""') + '"';
}

// ============ 主流程 ============
async function main() {
  const args = process.argv.slice(2);
  const keyword = parseArg(args, '--keyword') || 'AI生成';
  const maxItems = parseInt(parseArg(args, '--max') || '50');
  const chromePort = parseInt(parseArg(args, '--port') || String(CONFIG.chromePort));

  console.log(`\n🔍 小红书采集启动`);
  console.log(`   关键词: ${keyword}`);
  console.log(`   目标: ${maxItems} 条`);

  // 1. 启动 Chrome
  console.log('1. 启动 Chrome...');
  await killChrome(chromePort);
  await launchChrome(chromePort, keyword);
  await sleep(5000);

  // 2. 连接 CDP + 注入 cookie
  console.log('2. 连接 CDP + 注入 cookie...');
  const { ws, send } = await connectCDP(chromePort, keyword);
  await injectCookies(ws, send);

  // 3. 导航
  console.log('3. 导航到搜索页...');
  await send('Page.navigate', {
    url: `https://www.xiaohongshu.com/search_result?keyword=${encodeURIComponent(keyword)}&type=51`
  });
  await sleep(8000);

  // 4. 翻页采集
  console.log('4. 翻页采集...');
  const allNotes = [];
  let page = 1;
  const apiBodies = {};
  let apiSeq = 0;

  ws.on('message', d => {
    try {
      const msg = JSON.parse(d.toString());
      if (msg.method === 'Network.responseReceived' && msg.params.response.url.includes('search/notes')) {
        const rid = msg.params.requestId;
        apiSeq++;
        setTimeout(() => {
          send('Network.getResponseBody', { requestId: rid }).then(r => {
            if (r.result) apiBodies[apiSeq] = r.result.body;
          }).catch(() => {});
        }, 200);
      }
    } catch (e) {}
  });
  await send('Network.enable', {});

  while (allNotes.length < maxItems) {
    console.log(`   第 ${page} 页...`);
    await send('Runtime.evaluate', {
      expression: `(async () => {
        try {
          const pinia = document.querySelector('#app').__vue_app__.config.globalProperties.$pinia;
          const store = pinia._s.get('search');
          await store.searchNotes({
            keyword: ${JSON.stringify(keyword)},
            page: ${page}, pageSize: ${CONFIG.pageSize},
            sort: 'general', noteType: 0, extFlags: [],
            imageFormats: ['jpg', 'webp', 'avif'],
            search_id: store.searchContext?.searchId || ''
          });
          return 'OK';
        } catch(e) { return 'ERR:' + e.message; }
      })()`,
      returnByValue: true,
      awaitPromise: true
    });
    await sleep(3000);

    const before = allNotes.length;
    for (const body of Object.values(apiBodies)) {
      try {
        const data = JSON.parse(body);
        if (data.success?.data?.items) {
          for (const item of data.data.items) {
            if (allNotes.some(n => n.noteId === item.id)) continue;
            const nc = item.note_card || {};
            allNotes.push({
              noteId: item.id,
              url: 'https://www.xiaohongshu.com/explore/' + item.id,
              title: nc.display_title || '',
              author: nc.user?.nickname || nc.user?.nick_name || '',
              time: nc.corner_tag_info?.[0]?.text || '',
              likes: nc.interact_info?.liked_count || '',
              comments: nc.interact_info?.comment_count || '',
              favorites: nc.interact_info?.collected_count || '',
              shares: nc.interact_info?.shared_count || '',
              keyword, platform: '小红书',
              collected_at: new Date().toISOString()
            });
          }
        }
      } catch(e) {}
    }
    const added = allNotes.length - before;
    console.log(`     → +${added} = ${allNotes.length}`);
    if (added === 0 && page > 3) break;
    page++;
  }

  // 5. 导出
  console.log(`\n5. 导出...`);
  const date = new Date().toISOString().slice(0, 10);
  const ts = Date.now();
  const runDir = `${CONFIG.outputBase}/${date}/runs/xhs_cdp_${ts}`;
  const exportDir = `${CONFIG.outputBase}/${date}/exports`;
  fs.mkdirSync(runDir, { recursive: true });
  fs.mkdirSync(exportDir, { recursive: true });

  const final = allNotes.slice(0, maxItems);
  const rowsPath = `${runDir}/rows.jsonl`;
  for (const n of final) fs.appendFileSync(rowsPath, JSON.stringify(n) + '\n');

  const csvPath = `${exportDir}/小红书_${keyword}_${final.length}条.csv`;
  const h = ['发帖人','发布时间','标题','点赞数','评论数','收藏数','转发数','笔记链接','关键词','平台'];
  let csv = '\uFEFF' + h.join(',') + '\n';
  const m = {发帖人:'author',发布时间:'time',标题:'title',点赞数:'likes',评论数:'comments',收藏数:'favorites',转发数:'shares',笔记链接:'url',关键词:'kw',平台:'plat'};
  for (const n of final) {
    csv += h.map(k => {
      const v = k === '关键词' ? keyword : k === '平台' ? '小红书' : n[m[k]];
      return escapeCSV(v);
    }).join(',') + '\n';
  }
  fs.writeFileSync(csvPath, csv);

  console.log(`\n✅ 完成！${final.length} 条, ${page} 页`);
  console.log(`   CSV: ${csvPath}`);
  console.log(`   JSONL: ${rowsPath}`);
  for (const f of ['author','time','title','likes','comments','favorites','shares']) {
    const filled = final.filter(n => n[f] && n[f] !== '0').length;
    console.log(`   ${f}: ${filled}/${final.length}`);
  }

  await killChrome(chromePort);
  ws.close();
  process.exit(0);
}

// ============ Chrome 管理 ============
async function launchChrome(port, keyword) {
  const { execSync } = require('child_process');
  const cp = '/home/xujuan/.cache/octorunner/chrome/linux-147.0.7727.50/chrome-linux64/chrome';
  const url = `https://www.xiaohongshu.com/search_result?keyword=${encodeURIComponent(keyword)}&type=51`;
  execSync(`DISPLAY=:1.0 nohup "${cp}" --user-data-dir="${CONFIG.userDataDir}" --remote-debugging-port=${port} --no-first-run --no-default-browser-check --new-window "${url}" > /dev/null 2>&1 &`, { shell: '/bin/bash', timeout: 5000 });
  for (let i = 0; i < 30; i++) {
    try { await httpGet(`http://localhost:${port}/json/version`); console.log(`   Chrome ready`); return; } catch(e) { await sleep(1000); }
  }
  throw new Error('Chrome failed to start');
}

async function killChrome(port) {
  try {
    const { execSync } = require('child_process');
    let pids = '';
    try { pids = execSync(`lsof -ti:${port} 2>/dev/null`).toString().trim(); } catch(e) {}
    if (!pids) {
      try { const ss = execSync(`ss -tlnp 2>/dev/null | grep ":${port}"`).toString(); const m = ss.match(/pid=(\d+)/g); if (m) pids = m.map(x => x.replace('pid=','')).join('\n'); } catch(e) {}
    }
    if (pids) { for (const pid of pids.split('\n').filter(Boolean)) { try { process.kill(parseInt(pid), 'SIGTERM'); } catch(e) {} } }
    await sleep(2000);
  } catch(e) {}
}

async function connectCDP(port, keyword) {
  const tabs = JSON.parse(await httpGet(`http://localhost:${port}/json`));
  let tab = tabs.find(t => t.title.includes(keyword)) || tabs[0];
  const ws = new WebSocket(tab.webSocketDebuggerUrl);
  let msgId = 1, pending = {};
  ws.on('message', d => { try { const m = JSON.parse(d.toString()); if (m.id && pending[m.id]) { pending[m.id](m); delete pending[m.id]; } } catch(e) {} });
  await new Promise((r, rej) => { ws.on('open', r); ws.on('error', rej); });
  return { ws, send: (method, params = {}) => new Promise(r => { const id = msgId++; ws.send(JSON.stringify({id, method, params})); pending[id] = r; }) };
}

async function injectCookies(ws, send) {
  let cookies;
  try {
    const s = JSON.parse(fs.readFileSync(CONFIG.sessionFile, 'utf8'));
    cookies = s.cookies;
    console.log(`   读取 ${cookies.length} 个 cookie`);
  } catch(e) {
    const r = await send('Storage.getCookies', {});
    cookies = r.result.cookies.filter(c => c.domain.includes('xiaohongshu'));
    console.log(`   浏览器已有 ${cookies.length} 个 cookie`);
  }
  for (const c of cookies) {
    try {
      await send('Network.setCookie', {
        name: c.name, value: c.value,
        url: (c.secure ? 'https://' : 'http://') + (c.domain.startsWith('.') ? c.domain.substring(1) : c.domain) + (c.path || '/'),
        domain: c.domain, path: c.path || '/', secure: c.secure || false,
        httpOnly: c.httpOnly || false,
        expires: c.expires || (c.expirationDate ? Math.floor(c.expirationDate) : undefined)
      });
    } catch(e) {}
  }
  console.log(`   注入 ${cookies.length} 个 cookie`);
}

function parseArg(args, name) {
  const idx = args.indexOf(name);
  return idx !== -1 && idx + 1 < args.length ? args[idx + 1] : null;
}

main().catch(e => { console.error('\n❌ 错误:', e.message); process.exit(1); });