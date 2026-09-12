(() => {
  const root = document.querySelector('[data-workbench]');
  if (!root) return;
  const sessionId = root.dataset.sessionId;
  const dialog = document.querySelector('[data-new-dialog]');
  const messages = document.querySelector('[data-messages]');
  const composer = document.querySelector('[data-message-form]');
  const textarea = composer?.querySelector('textarea');
  const sendButton = composer?.querySelector('button');
  const fileList = document.querySelector('[data-file-list]');
  const pathLabel = document.querySelector('[data-current-path]');
  const backButton = document.querySelector('[data-file-back]');
  const preview = document.querySelector('[data-preview]');
  let currentPath = '.';

  const escapeHtml = (value) => {
    const span = document.createElement('span');
    span.textContent = String(value ?? '');
    return span.innerHTML;
  };
  const apiError = async (response, fallback) => {
    try { return (await response.json()).error || fallback; } catch (_) { return fallback; }
  };

  document.querySelectorAll('[data-open-new]').forEach((button) => button.addEventListener('click', () => dialog?.showModal()));
  document.querySelector('[data-new-session-form]')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const submit = form.querySelector('button[type=submit]');
    submit.disabled = true;
    try {
      const response = await fetch('/api/sessions', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ project: form.elements.project.value, model: form.elements.model.value }),
      });
      if (!response.ok) throw new Error(await apiError(response, '新建对话失败'));
      location.href = (await response.json()).url;
    } catch (error) { alert(error.message); submit.disabled = false; }
  });

  document.querySelectorAll('[data-delete-session]').forEach((button) => button.addEventListener('click', async (event) => {
    event.preventDefault(); event.stopPropagation();
    if (!confirm('删除这条对话？项目文件不会被删除。')) return;
    const response = await fetch(`/api/sessions/${button.dataset.deleteSession}`, {method:'DELETE'});
    if (!response.ok) return alert(await apiError(response, '删除失败'));
    location.href = '/';
  }));

  document.querySelector('[data-model-select]')?.addEventListener('change', async (event) => {
    const select = event.currentTarget;
    select.disabled = true;
    const response = await fetch(`/api/sessions/${sessionId}`, {
      method:'PATCH', headers:{'Content-Type':'application/json'}, body:JSON.stringify({model:select.value}),
    });
    if (!response.ok) alert(await apiError(response, '模型切换失败'));
    select.disabled = false;
  });
  document.querySelectorAll('[data-prompt]').forEach((button) => button.addEventListener('click', () => {
    textarea.value = button.dataset.prompt; textarea.focus();
  }));

  const appendMessage = (role, text, events=[]) => {
    document.querySelector('[data-welcome]')?.remove();
    const article = document.createElement('article');
    article.className = `message ${role}`;
    const tools = events.length ? `<div class="tool-events">${events.map((item) => `<span class="${item.ok?'ok':'error'}">${item.ok?'✓':'!'} ${escapeHtml({list_directory:'浏览目录',read_file:'读取文件',search_text:'搜索代码'}[item.name] || item.name)}</span>`).join('')}</div>` : '';
    article.innerHTML = `<span class="avatar">${role==='assistant'?'DS':'我'}</span><div><strong>${role==='assistant'?'DeepSeek':'你'}</strong><p>${escapeHtml(text)}</p>${tools}</div>`;
    messages.appendChild(article); messages.scrollTo({top:messages.scrollHeight,behavior:'smooth'});
    return article;
  };
  composer?.addEventListener('submit', async (event) => {
    event.preventDefault(); const prompt = textarea.value.trim();
    if (!prompt || !sessionId) return;
    textarea.value=''; textarea.disabled=true; sendButton.disabled=true;
    appendMessage('user',prompt); const loading=appendMessage('assistant','正在查看项目并思考…');
    try {
      const response=await fetch(`/api/sessions/${sessionId}/messages`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:prompt})});
      if(!response.ok) throw new Error(await apiError(response,'DeepSeek 请求失败'));
      const data=await response.json(); loading.remove(); appendMessage('assistant',data.reply,data.tool_events||[]);
      const title=document.querySelector('.topbar>div:first-child strong'); if(title) title.textContent=data.title;
      const sideTitle=document.querySelector('.session-item.active strong'); if(sideTitle) sideTitle.textContent=data.title;
    } catch(error) { loading.remove(); appendMessage('assistant',`请求失败：${error.message}`); }
    finally {textarea.disabled=false;sendButton.disabled=false;textarea.focus();}
  });
  textarea?.addEventListener('keydown',(event)=>{if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();composer.requestSubmit();}});

  const fileMarkup=(item)=>`<button type="button" data-file-path="${escapeHtml(item.path)}" data-file-type="${item.type}"><span>${item.type==='directory'?'▸':'◇'}</span><span><strong>${escapeHtml(item.name)}</strong><small>${item.type==='directory'?'目录':`${Math.max(1,Math.ceil((item.size||0)/1024))} KB`}</small></span></button>`;
  const bindFiles=()=>document.querySelectorAll('[data-file-path]').forEach((button)=>button.addEventListener('click',async()=>{
    if(button.dataset.fileType==='directory') return loadFiles(button.dataset.filePath);
    const response=await fetch(`/api/file?session=${sessionId}&path=${encodeURIComponent(button.dataset.filePath)}`);
    if(!response.ok) return alert(await apiError(response,'文件无法预览'));
    const data=await response.json(); preview.querySelector('[data-preview-name]').textContent=data.path; preview.querySelector('[data-preview-content]').textContent=data.content; preview.hidden=false;
  }));
  const loadFiles=async(path='.')=>{
    if(!fileList)return; const response=await fetch(`/api/files?session=${sessionId}&path=${encodeURIComponent(path)}`);
    if(!response.ok)return alert(await apiError(response,'目录读取失败'));
    const data=await response.json();currentPath=path||'.';pathLabel.textContent=currentPath;backButton.disabled=currentPath==='.';
    fileList.innerHTML=data.entries.length?data.entries.map(fileMarkup).join(''):'<p>目录为空</p>';bindFiles();
  };
  bindFiles();
  backButton?.addEventListener('click',()=>{const parts=currentPath.split('/').filter((part)=>part&&part!=='.');parts.pop();loadFiles(parts.length?parts.join('/'):'.');});
  document.querySelector('[data-refresh-files]')?.addEventListener('click',()=>loadFiles(currentPath));
  document.querySelector('[data-close-preview]')?.addEventListener('click',()=>preview.hidden=true);
  messages?.scrollTo({top:messages.scrollHeight});
})();
