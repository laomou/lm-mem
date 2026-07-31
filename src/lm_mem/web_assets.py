"""lm-mem Web 台的静态资源:CSS 与前端 JS。

纯字符串常量,零依赖(与 memory_utils 同风格)。从 web.py 抽出,
让样式/脚本可独立编辑,不必在 Python 代码里翻找长字符串。
"""

PAGE_CSS = """
:root{
  --bg:#fafafa;--surface:#fff;--border:#ebecf0;--text:#1a1a2e;--muted:#8b8fa3;
  --accent:#6366f1;--accent-hover:#4f46e5;--accent-soft:#f0f0ff;
  --green:#059669;--amber:#d97706;--red:#ef4444;
  --radius:12px;--radius-sm:8px;--shadow:0 1px 3px rgba(0,0,0,.04),0 1px 2px rgba(0,0,0,.03);
}
@media (prefers-color-scheme:dark){
  :root{
    --bg:#09090b;--surface:#121217;--border:#1f1f2a;--text:#e4e4ed;--muted:#727282;
    --accent:#818cf8;--accent-hover:#a5b4fc;--accent-soft:#1c1c2a;
    --shadow:0 1px 2px rgba(0,0,0,.22);
  }
}
*{box-sizing:border-box}
body{font:14px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
     margin:0;color:var(--text);background:var(--bg);-webkit-font-smoothing:antialiased}
.wrap{max-width:1600px;margin:0 auto;padding:0 24px 80px}
header.topbar{position:sticky;top:0;z-index:50;background:rgba(250,250,250,.82);
     border-bottom:1px solid var(--border);backdrop-filter:saturate(180%) blur(12px);
     -webkit-backdrop-filter:saturate(180%) blur(12px)}
@media(prefers-color-scheme:dark){header.topbar{background:rgba(9,9,11,.82)}}
.topbar-inner{max-width:1600px;margin:0 auto;padding:14px 24px;display:flex;
     align-items:center}
.topbar h1{font-size:16px;margin:0;font-weight:640;letter-spacing:-.01em}
.topbar h1 .ver{font-size:11px;color:var(--muted);font-weight:400;margin-left:8px}
form.filters{display:flex;flex-wrap:wrap;gap:8px;margin:24px 0 16px;align-items:end}
form.filters .field{display:flex;flex-direction:column;gap:4px}
form.filters .field label{font-size:11px;color:var(--muted);padding-left:2px}
input,button,select{font:inherit;padding:8px 12px;border:1px solid var(--border);
     border-radius:var(--radius-sm);background:var(--surface);color:var(--text);
     transition:border .18s,box-shadow .18s,background .18s}
input:focus{outline:none;border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-soft)}
input[type=text]{min-width:160px}
input[type=text].grow{flex:1;min-width:220px}
button{background:var(--accent);color:#fff;border-color:var(--accent);
       cursor:pointer;font-weight:500;padding:8px 18px;border-radius:var(--radius-sm)}
button:hover{background:var(--accent-hover);border-color:var(--accent-hover)}
button.ghost{background:transparent;color:var(--text);border-color:var(--border)}
button.ghost:hover{background:var(--accent-soft);color:var(--accent);border-color:transparent}
button.ghost.icon{padding:6px 12px;font-size:13px}
.toolbar{display:flex;align-items:center;justify-content:space-between;gap:12px;
         margin-bottom:16px;flex-wrap:wrap}
.toolbar .count{color:var(--muted);font-size:13px}
.pager{display:flex;gap:4px;align-items:center;flex-wrap:wrap}
.pager a,.pager span{padding:6px 12px;border:1px solid var(--border);border-radius:var(--radius-sm);
       text-decoration:none;color:var(--text);font-size:13px;background:var(--surface);
       transition:all .15s}
.pager a:hover{background:var(--accent-soft);color:var(--accent);border-color:transparent}
.pager .cur{background:var(--accent);color:#fff;border-color:var(--accent)}
.pager .gap{border:none;background:transparent;color:var(--muted)}
.table-wrap{overflow-x:auto;border-radius:var(--radius);overflow:hidden;
    background:var(--surface);box-shadow:var(--shadow);border:1px solid var(--border)}
.mem-table{border-collapse:collapse;width:100%;min-width:640px}
.mem-table td,.mem-table th{padding:5px 12px;text-align:left;font-size:12px;
    vertical-align:middle;border-bottom:1px solid var(--border)}
.mem-table tr:last-child td{border-bottom:0}
.mem-table th{background:var(--bg);color:var(--muted);font-weight:600;font-size:11px;
    text-transform:uppercase;letter-spacing:.05em;position:sticky;top:0;z-index:1;padding:6px 12px}
.mem-table tbody tr{transition:background .12s}
.mem-table tbody tr:hover td{background:var(--accent-soft)}
.mem-table td.time{color:var(--muted);font-family:"SF Mono",ui-monospace,monospace;
    white-space:nowrap;font-size:11px;width:85px}
.mem-table td.entities{width:200px}
.mem-table td.entities .scope{display:inline-block;font-family:"SF Mono",ui-monospace,monospace;
    font-size:11px;color:var(--muted);background:var(--bg);border:1px solid var(--border);
    padding:2px 9px;border-radius:20px;margin:1px 4px 2px 0}
.mem-table td.content{max-width:600px}
.mem-table td.content a{color:var(--text);text-decoration:none;display:block;
    display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;
    font-size:12px;line-height:1.35;height:calc(1.35em*2);text-overflow:ellipsis}
.mem-table td.content a:hover{color:var(--accent)}
.mem-table td.categories{width:180px}
.mem-table td.categories .tag{display:inline-block;background:var(--accent-soft);
    color:var(--accent);padding:2px 9px;border-radius:20px;font-size:11px;margin:1px 3px 1px 0}
.mem-table td.categories .tag.cat{background:rgba(217,119,6,.1);color:var(--amber)}
@media(max-width:640px){.mem-table td.content{max-width:55vw}}
.empty{text-align:center;padding:64px 20px;color:var(--muted)}
.empty .big{font-size:44px;margin-bottom:12px;opacity:.45}
.muted{color:var(--muted)}
h2{font-size:15px;margin:28px 0 12px;font-weight:600}
pre{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);
    padding:16px;white-space:pre-wrap;word-break:break-word;overflow:auto;
    font-size:12.5px;font-family:"SF Mono",ui-monospace,monospace}
.kv{display:grid;grid-template-columns:auto 1fr;gap:8px 18px;font-size:13px;margin:4px 0}
.kv dt{color:var(--muted);font-weight:500}
.kv dd{margin:0;word-break:break-word}
.error-box{background:rgba(239,68,68,.06);border:1px solid rgba(239,68,68,.25);color:var(--red);
    padding:14px 16px;border-radius:var(--radius)}
.card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);
      padding:14px 16px;margin-bottom:10px;box-shadow:var(--shadow);transition:border .15s}
.card:hover{border-color:var(--accent)}
.card .top{display:flex;align-items:center;gap:8px;margin-bottom:6px}
.card .id{color:var(--muted);font-size:12px;font-family:"SF Mono",ui-monospace,monospace}
.card .id a{color:inherit;text-decoration:none}
.card .id a:hover{color:var(--accent)}
.card .sim{color:var(--green);font-size:12px;font-weight:600;
     background:rgba(5,150,105,.1);padding:1px 8px;border-radius:20px}
.card .content{margin:4px 0;white-space:pre-wrap;word-break:break-word;color:var(--text)}
.card a.content{display:block;text-decoration:none;color:var(--text);border-radius:6px;
     margin:4px -4px;padding:4px;transition:background .12s}
.card a.content:hover{background:var(--accent-soft)}
.card .content.clamp{display:-webkit-box;-webkit-line-clamp:4;-webkit-box-orient:vertical;
     overflow:hidden;cursor:pointer}
.card .meta{color:var(--muted);font-size:12px;margin-top:8px;display:flex;
     flex-wrap:wrap;gap:4px 10px}
.card .meta .tag{background:var(--accent-soft);color:var(--accent);padding:1px 8px;
     border-radius:20px;font-size:11px}
.card .meta .scope{font-family:"SF Mono",ui-monospace,monospace;font-size:11px}
.card .meta .expire{color:var(--amber)}
.card .actions{margin-top:10px;display:flex;gap:8px}
.card .del-inline{background:transparent;border:1px solid var(--border);color:var(--muted);
    padding:3px 10px;font-size:12px;border-radius:6px;cursor:pointer}
.card .del-inline:hover{background:rgba(239,68,68,.06);color:var(--red);border-color:var(--red)}
.danger{background:var(--red);color:#fff;border-color:var(--red);font-weight:500;
    border-radius:var(--radius-sm)}
.danger:hover{background:#dc2626;border-color:#dc2626}
.confirm-bar{display:flex;align-items:center;gap:12px;flex-wrap:wrap;
    background:rgba(239,68,68,.06);border:1px solid rgba(239,68,68,.25);border-radius:var(--radius);
    padding:12px 16px;margin-bottom:16px}
.confirm-bar .msg{color:var(--red);font-size:13px;font-weight:500}
.overlay{position:fixed;inset:0;background:rgba(0,0,0,.3);opacity:0;visibility:hidden;
    transition:opacity .22s;z-index:60;backdrop-filter:blur(2px)}
.overlay.show{opacity:1;visibility:visible}
.drawer{position:fixed;top:0;right:0;bottom:0;width:500px;max-width:100vw;
    background:var(--bg);border-left:1px solid var(--border);
    box-shadow:-4px 0 40px rgba(0,0,0,.08);transform:translateX(104%);
    transition:transform .28s cubic-bezier(.32,.72,0,1);z-index:70;
    display:flex;flex-direction:column}
.drawer.show{transform:translateX(0)}
.drawer header{display:flex;align-items:center;gap:10px;padding:16px 20px;
    background:var(--surface);border-bottom:1px solid var(--border)}
.drawer header .title{font-weight:640;font-size:15px;flex:1;color:var(--text)}
.drawer header .close{background:transparent;border:none;color:var(--muted);
    font-size:22px;cursor:pointer;padding:2px 6px;line-height:1;border-radius:8px;
    transition:all .15s}
.drawer header .close:hover{background:var(--accent-soft);color:var(--accent)}
.drawer .body{flex:1;overflow-y:auto;padding:18px 20px}
.drawer .d-content{background:var(--surface);border:1px solid var(--border);
    border-radius:var(--radius-sm);padding:14px 16px;white-space:pre-wrap;
    word-break:break-word;margin-bottom:16px;font-size:13px;line-height:1.6}
.drawer .d-id{font-family:"SF Mono",ui-monospace,monospace;font-size:12px;color:var(--muted);
    background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-sm);
    padding:8px 12px;word-break:break-all;margin-bottom:16px}
.drawer .d-section{font-size:11px;color:var(--muted);text-transform:uppercase;
    letter-spacing:.06em;margin:18px 0 8px;font-weight:600}
.drawer .d-meta{display:flex;flex-wrap:wrap;gap:6px 8px;font-size:13px}
.drawer .d-meta .tag{background:var(--accent-soft);color:var(--accent);
    padding:3px 10px;border-radius:20px;font-size:11px}
.drawer .d-meta .scope{font-family:"SF Mono",ui-monospace,monospace;font-size:11px;
    color:var(--muted);background:var(--surface);border:1px solid var(--border);
    padding:3px 10px;border-radius:20px}
.drawer .d-kv{font-size:13px;color:var(--text)}
.drawer .d-kv div{padding:6px 0;border-bottom:1px solid var(--border);display:flex;gap:10px}
.drawer .d-kv div:last-child{border-bottom:0}
.drawer .d-kv .k{color:var(--muted);min-width:65px;font-weight:500}
.drawer .d-loading{text-align:center;padding:40px 0;color:var(--muted)}
.drawer .d-error{color:var(--red);text-align:center;padding:40px 0}
.drawer footer{padding:16px 20px;border-top:1px solid var(--border);background:var(--surface)}
.tools-right{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.filters.collapsed{display:none}
.filter-active{display:inline-block;width:7px;height:7px;border-radius:50%;
    background:var(--accent);margin-left:3px}
@media(max-width:640px){
  .drawer{width:100vw}
  .mem-table td.content{max-width:55vw}
  form.filters .field{flex:1 1 45%}
  input[type=text]{min-width:0;width:100%}
  .topbar-inner{padding:12px 16px}
}
"""


DRAWER_JS = r"""
(function(){
  var ov=document.getElementById('ov'),dr=document.getElementById('dr'),
      bt=document.getElementById('dr-body'),ti=document.getElementById('dr-title'),
      ft=document.getElementById('dr-foot'),cl=document.getElementById('dr-close');
  if(!dr) return;
  function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){
    return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}
  function ts(v){if(!v)return '—';var d=new Date(v*1000);
    if(isNaN(d))return String(v);
    var p=function(n){return n<10?'0'+n:n;};
    return d.getFullYear()+'-'+p(d.getMonth()+1)+'-'+p(d.getDate())+
      ' '+p(d.getHours())+':'+p(d.getMinutes())+':'+p(d.getSeconds());}
  function close(){ov.classList.remove('show');dr.classList.remove('show');
    dr.setAttribute('aria-hidden','true');bt.innerHTML='';ft.hidden=true;ft.innerHTML='';}
  function open(mid){
    ti.textContent='记忆详情';
    bt.innerHTML='<div class="d-loading">加载中…</div>';
    ft.hidden=true;
    ov.classList.add('show');dr.classList.add('show');
    dr.setAttribute('aria-hidden','false');
    fetch('/api/mem/'+encodeURIComponent(mid)).then(function(r){return r.json();})
      .then(function(r){render(r,mid);})
      .catch(function(){bt.innerHTML='<div class="d-error">加载失败</div>';});
  }
  function render(r,mid){
    if(!r||!r.id){bt.innerHTML='<div class="d-error">未找到该记忆</div>';ft.hidden=true;return;}
    ti.textContent='记忆详情';
    var md=r.metadata||{}; var mdKeys=Object.keys(md);
    var mdJson=JSON.stringify(md,null,2);
    var scopeJson=JSON.stringify(r.scope||{},null,2);
    var scopeKeys=Object.keys(r.scope||{});
    bt.innerHTML=
      '<div class="d-section">ID</div>'
      +'<div class="d-id">'+esc(r.id)+'</div>'
      +'<div class="d-section">内容</div>'
      +'<div class="d-content">'+esc(r.content)+'</div>'
      +'<div class="d-kv">'
        +'<div><span class="k">创建时间</span><span>'+esc(ts(r.created_at))+'</span></div>'
        +'<div><span class="k">更新时间</span><span>'+esc(ts(r.updated_at))+'</span></div>'
        +(r.expires_at?'<div><span class="k">过期时间</span><span>'+esc(ts(r.expires_at))+'</span></div>':'')
      +'</div>'
      +'<div class="d-section">作用域</div>'
      +(scopeKeys.length?'<div class="d-content">'+esc(scopeJson)+'</div>':'<span class="muted">—</span>')
      +(mdKeys.length?('<div class="d-section">元数据</div><div class="d-content">'+esc(mdJson)+'</div>'):'<div class="d-section">元数据</div><span class="muted">—</span>')
    // 底部删除按钮
    ft.hidden=false;
    // action 是 URL 路径:必须 encodeURIComponent(它的输出天然是属性安全的),
    // 用 esc() 只做 HTML 转义会让含 & / 的 id 指向错误路径。
    ft.innerHTML='<form method="post" action="/mem/'+encodeURIComponent(mid)+'/delete" '
      +'onsubmit="return confirm(\'确认删除?不可撤销。\')">'
      +'<button type="submit" class="danger" style="width:100%">🗑 删除这条记忆</button>'
      +'</form>';
  }
  // 点表格行 → 开抽屉;ctrl/shift/中键放行(新标签打开链接)
  document.addEventListener('click',function(e){
    if(e.metaKey||e.ctrlKey||e.shiftKey||e.button!==0)return;
    var a=e.target.closest('a.mem-link');
    var tr=e.target.closest('tr[data-mid]');
    // 一律读 data-mid(原始 id),不从 href 里切——href 是百分号编码过的,
    // 切出来还要再解码一次,容易和 encodeURIComponent 叠成双重编码。
    if(a){e.preventDefault();open(a.getAttribute('data-mid'));return;}
    if(tr){e.preventDefault();open(tr.getAttribute('data-mid'));return;}
  });
  ov.addEventListener('click',close);
  cl.addEventListener('click',close);
  document.addEventListener('keydown',function(e){if(e.key==='Escape')close();});
  // 从详情页返回时若带 ?deleted=,列表已自行处理;抽屉不主动开
})();
"""
