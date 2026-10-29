#!/usr/bin/env python3
"""
LanDrop — 局域网文件/消息互传（单文件，零依赖，Python 3.8+）

用法：
    python landrop.py            # 启动服务，自动打开浏览器
    python landrop.py 8080      # 指定端口
    python landrop.py --no-browser

朋友访问：http://<你的IP>:8000（控制台会打印地址）

特性：
    - 纯 HTTP 轮询 + 分块上传，文件大小不限（流式落盘）
    - 电脑课/宿舍同一 WiFi 下互传，无需任何服务器
    - 收到的文件存在 ./landrop_files/
    - 中英文一键切换
"""
import http.server
import json
import os
import re
import socket
import socketserver
import sys
import threading
import time
import urllib.parse

PORT = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 8000
NO_BROWSER = '--no-browser' in sys.argv
RECV_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'landrop_files')
os.makedirs(RECV_DIR, exist_ok=True)

_lock = threading.Lock()
messages = []
uploads = {}
NEXT_ID = [1]


def add_message(type_, nick, text=None, name=None, size=None, done=None, key=None, params=None):
    with _lock:
        mid = NEXT_ID[0]; NEXT_ID[0] += 1
        m = {'id': mid, 'ts': int(time.time()), 'type': type_, 'nick': nick,
             'text': text, 'name': name, 'size': size, 'done': done, 'key': key, 'params': params}
        messages.append(m)
        if len(messages) > 2000:
            del messages[:500]
        return mid


PAGE = r'''<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>LanDrop · 局域网传输</title>
<style>
:root{--bg:#0f1420;--card:#1a2130;--line:#2a3448;--fg:#e8ecf4;--dim:#8b95a8;--acc:#4f8cff;--ok:#3ecf8e}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,"Microsoft YaHei",sans-serif;height:100vh;display:flex;flex-direction:column}
header{padding:10px 16px;border-bottom:1px solid var(--line);display:flex;gap:10px;align-items:center;background:var(--card)}
header .logo{font-weight:700;font-size:16px}
header .dot{width:8px;height:8px;border-radius:50%;background:var(--ok);box-shadow:0 0 6px var(--ok)}
header .addr{color:var(--dim);font-size:12px;margin-left:auto}
#nick{background:var(--bg);border:1px solid var(--line);color:var(--fg);border-radius:6px;padding:4px 8px;width:100px;font-size:12px}
#lang{background:#2a3448;color:var(--fg);border:1px solid var(--line);border-radius:6px;padding:4px 10px;font-size:12px;cursor:pointer}
#main{flex:1;display:flex;flex-direction:column;min-height:0}
#chat{flex:1;overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:10px}
.msg{max-width:78%;padding:8px 12px;border-radius:10px;background:var(--card);border:1px solid var(--line);word-break:break-all;white-space:pre-wrap}
.msg .meta{color:var(--dim);font-size:11px;margin-bottom:4px}
.msg.me{align-self:flex-end;background:#1c2a45;border-color:#2e4a75}
.msg.file .fname{color:var(--acc);text-decoration:none;font-weight:600}
.msg.file .fsize{color:var(--dim);font-size:11px;margin-top:2px}
.sys{align-self:center;color:var(--dim);font-size:12px;background:none;border:none}
#bar{padding:10px 16px;border-top:1px solid var(--line);background:var(--card);display:flex;gap:8px}
#text{flex:1;background:var(--bg);border:1px solid var(--line);color:var(--fg);border-radius:8px;padding:8px 12px;font-size:14px;resize:none;height:40px}
button{background:var(--acc);color:#fff;border:none;border-radius:8px;padding:8px 14px;font-size:14px;cursor:pointer;white-space:nowrap}
button:hover{filter:brightness(1.1)}
#file-btn{background:#2a3448}
#prog{padding:0 16px 8px;background:var(--card);display:none}
#prog .pinfo{font-size:12px;color:var(--dim);margin-bottom:4px;display:flex;justify-content:space-between}
#pbar{height:6px;background:var(--bg);border-radius:3px;overflow:hidden}
#pfill{height:100%;background:var(--acc);width:0%;transition:width .2s}
</style>
</head>
<body>
<header>
  <div class="dot"></div>
  <div class="logo">LanDrop</div>
  <div class="addr" id="addr"></div>
  <button id="lang">EN</button>
  <input id="nick" maxlength="12" placeholder="昵称">
</header>
<div id="main">
  <div id="chat"></div>
  <div id="prog">
    <div class="pinfo"><span id="pfname"></span><span id="pstat"></span></div>
    <div id="pbar"><div id="pfill"></div></div>
  </div>
  <div id="bar">
    <button id="file-btn">📁 发文件</button>
    <textarea id="text" placeholder="发消息… (Enter 发送)"></textarea>
    <button id="send">发送</button>
  </div>
</div>
<input type="file" id="picker" style="display:none">
<script>
const $=s=>document.querySelector(s);
const chat=$('#chat'),picker=$('#picker');

const I18N={
 zh:{nickPh:'昵称',send:'发送',fileBtn:'📁 发文件',textPh:'发消息… (Enter 发送)',langBtn:'EN',uploading:'上传中…',done:'完成 ✓',fail:'失败：',startUpload:'「%s」开始上传',interrupted:'「%s」上传中断，已删除',sizeMismatch:'大小不匹配',unknown:'未知'},
 en:{nickPh:'Nickname',send:'Send',fileBtn:'📁 Send File',textPh:'Type a message… (Enter to send)',langBtn:'中文',uploading:'Uploading…',done:'Done ✓',fail:'Failed: ',startUpload:'"%s" upload started',interrupted:'"%s" upload interrupted, deleted',sizeMismatch:'size mismatch',unknown:'unknown'}
};
let lang=localStorage.getItem('ld_lang')||'zh';
function t(k){return I18N[lang][k]}
function applyLang(){
  $('#nick').placeholder=t('nickPh');
  $('#send').textContent=t('send');
  $('#file-btn').textContent=t('fileBtn');
  $('#text').placeholder=t('textPh');
  $('#lang').textContent=t('langBtn');
  document.documentElement.lang=lang;
}
$('#lang').onclick=()=>{lang=lang==='zh'?'en':'zh';localStorage.setItem('ld_lang',lang);applyLang()};

let nick=localStorage.getItem('ld_nick')||'';
let lastId=0;
$('#nick').value=nick;
$('#nick').onchange=e=>{nick=e.target.value.trim();localStorage.setItem('ld_nick',nick)};

function fmtSize(n){if(n==null)return'';if(n<1024)return n+' B';if(n<1048576)return(n/1024).toFixed(1)+' KB';if(n<1073741824)return(n/1048576).toFixed(1)+' MB';return(n/1073741824).toFixed(2)+' GB'}

function sysText(m){
  if(m.key==='start')return t('startUpload').replace('%s',m.params&&m.params.name||'');
  if(m.key==='interrupted')return t('interrupted').replace('%s',m.params&&m.params.name||'');
  return m.text||'';
}

function add(m){
  if(m.id<=lastId)return;
  const el=document.createElement('div');
  if(m.type==='sys'){el.className='msg sys';el.textContent=sysText(m)}
  else{
    el.className='msg '+(m.nick===nick?'me':'')+(m.type==='file'?' file':'');
    const meta=document.createElement('div');meta.className='meta';
    meta.textContent=(m.nick||'?')+' · '+new Date(m.ts*1000).toLocaleTimeString();
    el.appendChild(meta);
    if(m.type==='text'){const b=document.createElement('div');b.textContent=m.text;el.appendChild(b)}
    else if(m.type==='file'){
      const a=document.createElement('a');a.className='fname';a.href='/f/'+m.id;a.textContent='📄 '+m.name;a.download=m.name;
      const s=document.createElement('div');s.className='fsize';s.textContent=fmtSize(m.size);
      el.appendChild(a);el.appendChild(s);
    }
  }
  chat.appendChild(el);chat.scrollTop=chat.scrollHeight;
  lastId=m.id;
}

async function poll(){
  try{
    const r=await fetch('/poll?after='+lastId);
    const ms=await r.json();
    ms.forEach(add);
  }catch(e){}
  setTimeout(poll,800);
}
poll();
fetch('/whoami').then(r=>r.text()).then(t=>{$('#addr').textContent=t});
applyLang();

function ensureNick(){
  if(!nick){nick='匿名'+Math.floor(Math.random()*900+100);$('#nick').value=nick;localStorage.setItem('ld_nick',nick)}
}

$('#send').onclick=sendText;
$('#text').addEventListener('keydown',e=>{
  if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();sendText()}
});
function sendText(){
  const t=$('#text').value.trim();
  if(!t)return;
  ensureNick();
  const fd=new FormData();fd.append('nick',nick);fd.append('text',t);
  fetch('/send',{method:'POST',body:fd});
  $('#text').value='';
}

$('#file-btn').onclick=()=>picker.click();
picker.onchange=()=>{
  const f=picker.files[0];
  if(!f)return;
  ensureNick();
  uploadFile(f);
  picker.value='';
};
async function uploadFile(f){
  const CHUNK=4*1024*1024;
  const uid=uuid4();
  const prog=$('#prog'),fill=$('#pfill'),stat=$('#pstat'),fn=$('#pfname');
  prog.style.display='block';fn.textContent=f.name;
  stat.textContent=t('uploading');
  let sent=0;
  while(sent<f.size){
    const blob=f.slice(sent,sent+CHUNK);
    const fd=new FormData();
    fd.append('uid',uid);fd.append('name',f.name);fd.append('index',sent);fd.append('total',f.size);
    fd.append('data',blob);
    const r=await fetch('/upload',{method:'POST',body:fd});
    if(!r.ok){stat.textContent=t('fail')+r.status;return}
    sent+=blob.size;
    const pct=f.size?Math.round(sent/f.size*100):100;
    fill.style.width=pct+'%';stat.textContent=pct+'% · '+fmtSize(sent)+' / '+fmtSize(f.size);
  }
  const fd2=new FormData();
  fd2.append('uid',uid);fd2.append('nick',nick);fd2.append('name',f.name);fd2.append('total',f.size);
  await fetch('/done',{method:'POST',body:fd2});
  stat.textContent=t('done');fill.style.width='100%';
  setTimeout(()=>{prog.style.display='none';fill.style.width='0%'},1500);
}
function uuid4(){
  return 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'.replace(/x/g,()=>Math.floor(Math.random()*16).toString(16));
}
</script>
</body>
</html>'''


def parse_multipart(rfile, boundary, remaining):
    fields = {}
    files = {}
    bnd = b'--' + boundary
    body = rfile.read(remaining)
    for part in body.split(bnd)[1:]:
        if part.startswith(b'--'):
            break
        if part.startswith(b'\r\n'):
            part = part[2:]
        idx = part.find(b'\r\n\r\n')
        if idx == -1:
            idx = part.find(b'\n\n')
            if idx == -1:
                continue
            sep = 2
        else:
            sep = 4
        headers_raw = part[:idx]
        data = part[idx + sep:]
        if data.endswith(b'\r\n'):
            data = data[:-2]
        elif data.endswith(b'\n'):
            data = data[:-1]
        headers = {}
        for hl in headers_raw.split(b'\n'):
            hl = hl.rstrip(b'\r')
            if not hl or b':' not in hl:
                continue
            k, v = hl.decode('utf-8', 'ignore').split(':', 1)
            headers[k.strip().lower()] = v.strip()
        disp = headers.get('content-disposition', '')
        name_m = re.search(r'name="([^"]*)"', disp)
        fname_m = re.search(r'filename="([^"]*)"', disp)
        part_name = name_m.group(1) if name_m else ''
        if fname_m:
            files[part_name] = data
        elif part_name:
            fields[part_name] = data.decode('utf-8', 'replace')
    return fields, files


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    def log_message(self, *a):
        pass
    def _json(self, obj, code=200):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)
    def _text(self, s):
        data = s.encode()
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path in ('/', '/index.html'):
            data = PAGE.encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if path == '/whoami':
            ip = get_lan_ip()
            self._text('%s:%d' % (ip, PORT))
            return
        if path == '/poll':
            qs = urllib.parse.parse_qs(parsed.query)
            after = int(qs.get('after', ['0'])[0])
            with _lock:
                pending = [m for m in messages if m['id'] > after]
            self._json(pending)
            return
        m = re.match(r'^/f/(\d+)$', path)
        if m:
            mid = int(m.group(1))
            with _lock:
                msg = next((x for x in messages if x['id'] == mid and x['type'] == 'file'), None)
            if not msg or not msg.get('done'):
                self.send_response(404)
                self.send_header('Content-Length', '0')
                self.end_headers()
                return
            fpath = msg['done']
            try:
                fsize = os.path.getsize(fpath)
            except OSError:
                self.send_response(404)
                self.send_header('Content-Length', '0')
                self.end_headers()
                return
            quoted = urllib.parse.quote(msg['name'])
            self.send_response(200)
            self.send_header('Content-Type', 'application/octet-stream')
            self.send_header('Content-Disposition', "attachment; filename*=UTF-8''" + quoted)
            self.send_header('Content-Length', str(fsize))
            self.end_headers()
            with open(fpath, 'rb') as f:
                while True:
                    chunk = f.read(1024 * 1024)
                    if not chunk:
                        break
                    try:
                        self.wfile.write(chunk)
                    except (BrokenPipeError, ConnectionResetError):
                        return
            return
        self.send_response(404)
        self.send_header('Content-Length', '0')
        self.end_headers()
    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        ctype = self.headers.get('Content-Type', '')
        if 'multipart/form-data' not in ctype:
            self._json({'err': 'need multipart'}, 400)
            return
        boundary = ctype.split('boundary=')[-1].encode()
        remaining = int(self.headers.get('Content-Length', 0))
        fields, files = parse_multipart(self.rfile, boundary, remaining)
        if path == '/send':
            nick = fields.get('nick', '?')
            text = fields.get('text', '')
            if text:
                add_message('text', nick, text=text)
            self._json({'ok': True})
            return
        if path == '/upload':
            uid = fields.get('uid', '')
            name = fields.get('name', 'file')
            index = int(fields.get('index', '0'))
            total = int(fields.get('total', '0'))
            data = files.get('data', b'')
            with _lock:
                up = uploads.get(uid)
                if up is None:
                    safe = re.sub(r'[\\/:*?"<>|]', '_', name)
                    fpath = os.path.join(RECV_DIR, safe)
                    base, ext = os.path.splitext(fpath)
                    n = 1
                    while os.path.exists(fpath):
                        fpath = '%s_%d%s' % (base, n, ext); n += 1
                    up = {'path': fpath, 'fh': open(fpath, 'wb'), 'got': 0}
                    uploads[uid] = up
                    add_message('sys', '', key='start', params={'name': name})
                if index == up['got']:
                    up['fh'].write(data)
                    up['got'] += len(data)
                else:
                    self._json({'err': 'chunk out of order'}, 400)
                    return
            self._json({'ok': True, 'got': up['got']})
            return
        if path == '/done':
            uid = fields.get('uid', '')
            nick = fields.get('nick', '?')
            name = fields.get('name', '')
            total = int(fields.get('total', '0'))
            with _lock:
                up = uploads.pop(uid, None)
            if up:
                up['fh'].close()
                if up['got'] != total:
                    try:
                        os.remove(up['path'])
                    except OSError:
                        pass
                    add_message('sys', '', key='interrupted', params={'name': name})
                    self._json({'err': 'size mismatch'}, 400)
                    return
                add_message('file', nick, name=name, size=total, done=up['path'])
            self._json({'ok': True})
            return
        self._json({'err': 'unknown'}, 404)


def get_lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return '127.0.0.1'


class ThreadedServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


if __name__ == '__main__':
    ip = get_lan_ip()
    print()
    print('  LanDrop 已启动')
    print('  本机:     http://127.0.0.1:%d' % PORT)
    print('  局域网:   http://%s:%d   <- 给朋友这个地址' % (ip, PORT))
    print('  收件目录: %s' % RECV_DIR)
    print()
    if not NO_BROWSER:
        try:
            import webbrowser
            webbrowser.open('http://127.0.0.1:%d' % PORT)
        except Exception:
            pass
    try:
        ThreadedServer(('0.0.0.0', PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        print('\n  再见')
