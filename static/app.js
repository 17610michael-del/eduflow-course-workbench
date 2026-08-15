(() => {
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

  // A page restored from the browser's back/forward memory may contain a stale
  // signed-in screen. Reloading forces Flask to re-check the current session.
  window.addEventListener('pageshow', (event) => {
    if (event.persisted) window.location.reload();
  });

  const sidebar = $("#sidebar");
  $("[data-toggle-sidebar]")?.addEventListener("click", () => sidebar?.classList.toggle("open"));
  document.addEventListener("click", (event) => {
    if (window.innerWidth <= 820 && sidebar?.classList.contains("open") && !sidebar.contains(event.target) && !event.target.closest("[data-toggle-sidebar]")) {
      sidebar.classList.remove("open");
    }
  });

  const usernameInput = $('[data-username-input]');
  const usernameHistory = $('[data-username-history]');
  $('[data-toggle-usernames]')?.addEventListener('click', (event) => {
    event.preventDefault();
    if (usernameHistory) usernameHistory.hidden = !usernameHistory.hidden;
    usernameInput?.focus();
  });
  $$('[data-known-username]').forEach((button) => button.addEventListener('click', () => {
    usernameInput.value = button.dataset.knownUsername;
    usernameHistory.hidden = true;
    document.querySelector('input[name=password]')?.focus();
  }));
  document.addEventListener('click', (event) => {
    if (usernameHistory && !event.target.closest('.username-field')) usernameHistory.hidden = true;
  });

  $$(".flash button").forEach((button) => button.addEventListener("click", () => button.parentElement.remove()));
  setTimeout(() => $$(".flash").forEach((item) => item.remove()), 4500);

  document.addEventListener("keydown", (event) => {
    if (event.key === "/" && !event.ctrlKey && !event.metaKey && !["INPUT", "TEXTAREA"].includes(document.activeElement.tagName)) {
      event.preventDefault();
      $(".global-search input")?.focus();
    }
  });

  $("[data-copy-link]")?.addEventListener("click", async (event) => {
    try {
      await navigator.clipboard.writeText(location.href);
      const button = event.currentTarget;
      const oldText = button.textContent;
      button.textContent = "已复制";
      setTimeout(() => (button.textContent = oldText), 1400);
    } catch (_) {
      window.prompt("复制此链接：", location.href);
    }
  });

  const fileLabels = $$(".file-drop input[type=file]");
  fileLabels.forEach((input) => input.addEventListener("change", () => {
    const drop = input.closest(".file-drop");
    const strong = drop?.querySelector("strong");
    const icon = drop?.querySelector(".upload-icon");
    const action = drop?.querySelector(".file-drop-action");
    const selected = Boolean(input.files[0]);
    drop?.classList.toggle("file-selected", selected);
    if (strong && selected) strong.textContent = input.files[0].name;
    if (icon && selected) icon.textContent = "✓";
    if (action) action.textContent = selected ? " 已选择，可确认提交" : " 或拖到这里";
  }));

  const draftForms = $$('[data-draft-form]');
  draftForms.forEach((form) => {
    const status = $('[data-draft-status]', form);
    let timer;
    let saving = false;
    const collectDraft = () => {
      const data = {};
      new FormData(form).forEach((value, key) => {
        if (value instanceof File) return;
        if (Object.prototype.hasOwnProperty.call(data, key)) data[key] = [].concat(data[key], value);
        else data[key] = value;
      });
      return data;
    };
    const saveDraft = async (includeFile = false) => {
      if (saving) return;
      saving = true;
      if (status) status.textContent = '正在保存草稿…';
      try {
        const file = $('[data-draft-file]', form)?.files[0];
        const endpoint = `/api/drafts/${form.dataset.draftType}/${form.dataset.draftKey}`;
        let options;
        if (includeFile && file) {
          const payload = new FormData(); payload.set('data', JSON.stringify(collectDraft())); payload.set('file', file);
          options = { method: 'POST', body: payload };
        } else {
          options = { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(collectDraft()) };
        }
        const response = await fetch(endpoint, options);
        const result = await response.json();
        if (!response.ok) throw new Error(result.error || '草稿保存失败');
        if (status) status.textContent = `草稿已保存 · ${new Date().toLocaleTimeString('zh-CN', {hour:'2-digit',minute:'2-digit'})}`;
      } catch (error) {
        if (status) status.textContent = error.message;
      } finally { saving = false; }
    };
    const schedule = () => {
      clearTimeout(timer);
      if (status) status.textContent = '有未保存的更改…';
      timer = setTimeout(() => saveDraft(false), 700);
    };
    form.addEventListener('input', (event) => { if (event.target.type !== 'file') schedule(); });
    form.addEventListener('change', (event) => { if (event.target.type !== 'file') schedule(); });
    $('[data-save-draft]', form)?.addEventListener('click', () => saveDraft(true));
  });

  const examBuilder = $('[data-exam-builder]');
  if (examBuilder) {
    const mode = $('[data-exam-mode]', examBuilder);
    const paperSettings = $('[data-paper-settings]', examBuilder);
    const builder = $('[data-question-builder]', examBuilder);
    const list = $('[data-question-list]', examBuilder);
    const payload = $('[data-question-data]', examBuilder);
    let questions;
    try { questions = JSON.parse(payload.value || '[]'); } catch (_) { questions = []; }
    const typeNames = { single:'单选题', multiple:'多选题', true_false:'判断题', fill:'填空题', essay:'简答题' };
    const syncQuestions = () => {
      questions = $$('.question-editor', list).map((card) => ({
        type: $('[data-question-type]', card).value,
        prompt: $('[data-question-prompt]', card).value,
        options: $('[data-question-options]', card).value.split('\n').map((x) => x.trim()).filter(Boolean),
        points: Number($('[data-question-points]', card).value || 0),
      }));
      payload.value = JSON.stringify(questions);
      payload.dispatchEvent(new Event('input', { bubbles: true }));
    };
    const renderQuestions = () => {
      list.innerHTML = questions.map((q, index) => `<article class="question-editor">
        <header><strong>第 ${index + 1} 题</strong><button type="button" data-remove-question="${index}">删除</button></header>
        <div class="question-editor-grid"><label>题型<select data-question-type>${Object.entries(typeNames).map(([value,name]) => `<option value="${value}" ${q.type === value ? 'selected' : ''}>${name}</option>`).join('')}</select></label><label>分值<input type="number" min="0" max="100" data-question-points value="${Number(q.points || 0)}"></label><label class="full">题干<textarea rows="2" data-question-prompt placeholder="输入题目内容">${escapeHtml(q.prompt || '')}</textarea></label><label class="full question-options-field">选项（每行一个，选择题使用）<textarea rows="4" data-question-options placeholder="选项 A&#10;选项 B">${escapeHtml((q.options || []).join('\n'))}</textarea></label></div></article>`).join('');
      $$('input,textarea,select', list).forEach((field) => field.addEventListener('input', syncQuestions));
      $$('[data-remove-question]', list).forEach((button) => button.addEventListener('click', () => { questions.splice(Number(button.dataset.removeQuestion), 1); renderQuestions(); syncQuestions(); }));
    };
    const toggleExamMode = () => { const computer = mode.value === 'computer'; builder.hidden = !computer; paperSettings.hidden = computer; };
    mode.addEventListener('change', toggleExamMode);
    $('[data-add-question]', examBuilder)?.addEventListener('click', () => { questions.push({ type:'single', prompt:'', options:['',''], points:0 }); renderQuestions(); syncQuestions(); });
    renderQuestions(); toggleExamMode();
  }

  const examTake = $('[data-exam-take]');
  if (examTake) {
    const form = $('[data-exam-answer-form]', examTake);
    const countdown = $('[data-countdown]', examTake);
    const status = $('[data-answer-status]', examTake);
    const deadline = Number(examTake.dataset.deadline);
    let saveTimer;
    let submitted = false;
    let automaticSubmit = false;
    const collectAnswers = () => {
      const answers = {};
      new FormData(form).forEach((value, key) => {
        if (!key.startsWith('answer_')) return;
        const id = key.slice(7);
        answers[id] = Object.prototype.hasOwnProperty.call(answers, id) ? [].concat(answers[id], value) : value;
      });
      return answers;
    };
    const saveAnswers = async () => {
      if (submitted) return;
      status.textContent = '正在保存…';
      try {
        const response = await fetch(`/api/exams/${examTake.dataset.examId}/answers`, { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ answers:collectAnswers() }) });
        if (!response.ok) throw new Error();
        status.textContent = '答案已自动保存';
      } catch (_) { status.textContent = '保存失败，正在重试'; }
    };
    form.addEventListener('input', () => { clearTimeout(saveTimer); status.textContent = '有未保存答案…'; saveTimer = setTimeout(saveAnswers, 500); });
    form.addEventListener('submit', (event) => {
      if (!automaticSubmit && !window.confirm('交卷后不能继续修改，确定现在提交吗？')) {
        event.preventDefault();
        return;
      }
      submitted = true;
    });
    const tick = () => {
      const remaining = Math.max(0, deadline - Date.now());
      const seconds = Math.ceil(remaining / 1000); const hours = Math.floor(seconds / 3600); const minutes = Math.floor(seconds % 3600 / 60); const secs = seconds % 60;
      countdown.textContent = `${hours ? `${hours}:` : ''}${String(minutes).padStart(2,'0')}:${String(secs).padStart(2,'0')}`;
      countdown.classList.toggle('urgent', remaining <= 5 * 60 * 1000);
      if (remaining <= 0 && !submitted) { automaticSubmit = true; form.requestSubmit(); return; }
      requestAnimationFrame(() => setTimeout(tick, 250));
    };
    tick();
  }

  $$('form[data-confirm-submit]').forEach((form) => form.addEventListener('submit', (event) => {
    if (!window.confirm('交卷后将不能继续修改，确定提交这份答卷吗？')) event.preventDefault();
  }));

  const generateForm = $('[data-question-generate]');
  generateForm?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const status = $('[data-generate-status]', generateForm);
    const data = Object.fromEntries(new FormData(generateForm));
    status.textContent = '正在生成题目草案…';
    try {
      const response = await fetch('/api/question-bank/generate', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data) });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || '生成失败');
      status.textContent = `已生成 ${result.created} 道题，正在刷新题库…`;
      window.setTimeout(() => window.location.reload(), 500);
    } catch (error) { status.textContent = `生成失败：${error.message}`; }
  });

  const studentSearch = $('[data-student-search]');
  studentSearch?.addEventListener('input', () => {
    const keyword = studentSearch.value.trim().toLowerCase();
    $$('[data-student-row]').forEach((row) => {
      row.hidden = !row.dataset.studentRow.toLowerCase().includes(keyword);
    });
  });

  const submitModal = $('#submit-modal');
  $$('[data-open-submit]').forEach((button) => button.addEventListener('click', () => submitModal?.showModal()));
  $$('[data-close-submit]').forEach((button) => button.addEventListener('click', () => submitModal?.close()));
  submitModal?.addEventListener('click', (event) => {
    const rect = submitModal.getBoundingClientRect();
    if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) submitModal.close();
  });
  $$('.source-tabs input[name=source]').forEach((radio) => radio.addEventListener('change', () => {
    $$('.source-tabs label').forEach((label) => label.classList.toggle('active', label.contains(radio)));
    $$('[data-source-panel]').forEach((panel) => { panel.hidden = panel.dataset.sourcePanel !== radio.value; });
  }));

  const commentContent = $("#comment-content");
  const parentId = $("#parent-id");
  const replyIndicator = $("#reply-indicator");
  $$('[data-reply-to]').forEach((button) => button.addEventListener('click', () => {
    parentId.value = button.dataset.replyTo;
    replyIndicator.hidden = false;
    $('strong', replyIndicator).textContent = `@${button.dataset.replyName}`;
    commentContent.focus();
    commentContent.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }));
  $('[data-cancel-reply]')?.addEventListener('click', () => {
    parentId.value = '';
    replyIndicator.hidden = true;
  });

  const formatText = (prefix, suffix = prefix, placeholder = "文本") => {
    if (!commentContent) return;
    const start = commentContent.selectionStart;
    const end = commentContent.selectionEnd;
    const selected = commentContent.value.slice(start, end) || placeholder;
    commentContent.setRangeText(`${prefix}${selected}${suffix}`, start, end, 'select');
    commentContent.focus();
  };
  $$('[data-format]').forEach((button) => button.addEventListener('click', () => {
    const formats = {
      bold: ['**', '**', '粗体文本'], italic: ['*', '*', '斜体文本'], link: ['[', '](https://)', '链接文字'],
      code: ['`', '`', 'code'], list: ['\n- ', '', '列表项'],
    };
    formatText(...formats[button.dataset.format]);
  }));

  const dropZone = $('[data-file-drop]');
  const commentFile = $('#comment-file');
  const filePreview = $('#file-preview');
  const showPreview = () => {
    if (!commentFile?.files[0] || !filePreview) return;
    $('strong', filePreview).textContent = commentFile.files[0].name;
    filePreview.hidden = false;
  };
  commentFile?.addEventListener('change', showPreview);
  if (dropZone && commentFile) {
    ['dragenter', 'dragover'].forEach((name) => dropZone.addEventListener(name, (event) => { event.preventDefault(); dropZone.classList.add('dragging'); }));
    ['dragleave', 'drop'].forEach((name) => dropZone.addEventListener(name, (event) => { event.preventDefault(); dropZone.classList.remove('dragging'); }));
    dropZone.addEventListener('drop', (event) => {
      if (!event.dataTransfer.files.length) return;
      const transfer = new DataTransfer();
      transfer.items.add(event.dataTransfer.files[0]);
      commentFile.files = transfer.files;
      showPreview();
    });
    $('button', filePreview)?.addEventListener('click', () => {
      commentFile.value = '';
      filePreview.hidden = true;
    });
  }

  const studentSelect = $('#analytics-student');
  const profile = $('#selected-profile');
  const updateProfile = () => {
    if (!studentSelect || !profile) return;
    const option = studentSelect.selectedOptions[0];
    $('.avatar', profile).textContent = option.dataset.name?.[0] || '?';
    $('strong', profile).textContent = option.dataset.name;
    $('div > span', profile).textContent = `${option.dataset.major || '未填写专业'} · ${option.dataset.grade || '未填写年级'}`;
  };
  studentSelect?.addEventListener('change', updateProfile);

  const analyzeButton = $('#analyze-button');
  analyzeButton?.addEventListener('click', async () => {
    const result = $('#analytics-result');
    const placeholder = $('.analysis-placeholder', result);
    const loading = $('.analysis-loading', result);
    const report = $('.analysis-report', result);
    placeholder.hidden = true;
    report.hidden = true;
    loading.hidden = false;
    analyzeButton.disabled = true;
    try {
      const response = await fetch('/api/analyze', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: studentSelect.value }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.message || '分析失败');
      await new Promise((resolve) => setTimeout(resolve, 650));
      const score = Math.round(data.mastery.overall_score * 100);
      $('#report-avatar').textContent = data.name[0];
      $('#report-name').textContent = data.name;
      $('#report-id').textContent = `@${data.username} · Linux 账号`;
      $('#generated-time').textContent = `生成于 ${new Date(data.generated_at).toLocaleString('zh-CN')}`;
      $('#score-value').textContent = `${score}%`;
      $('#score-ring').style.setProperty('--score', `${score * 3.6}deg`);
      $('#score-heading').textContent = score >= 80 ? '整体掌握情况良好' : score >= 65 ? '整体掌握情况中等' : '需要加强基础巩固';
      $('#engagement').textContent = data.mastery.engagement === 'active' ? '积极' : '一般';
      $('#question-count').textContent = `累计 ${data.activity.question_count} 次互动提问`;
      $('#submission-ratio').textContent = `${data.activity.submitted_tasks} / ${data.activity.total_tasks}`;
      $('#weak-topics').innerHTML = data.mastery.weak_topics.map((topic) => `<span>${escapeHtml(topic)}</span>`).join('');
      $('#suggestion').textContent = data.mastery.suggestion;
      $('#json-output').textContent = JSON.stringify(data, null, 2);
      loading.hidden = true;
      report.hidden = false;
    } catch (error) {
      loading.hidden = true;
      placeholder.hidden = false;
      $('h2', placeholder).textContent = '暂时无法生成分析';
      $('p', placeholder).textContent = error.message;
    } finally {
      analyzeButton.disabled = false;
    }
  });

  const tabButtons = $$('[data-tab-target]');
  tabButtons.forEach((button) => button.addEventListener('click', () => {
    tabButtons.forEach((item) => item.classList.toggle('active', item === button));
    $$('[data-tab-panel]').forEach((panel) => {
      const active = panel.id === button.dataset.tabTarget;
      panel.hidden = !active;
      panel.classList.toggle('active', active);
    });
    if (button.dataset.tabTarget === 'assistant-panel') {
      const chatWindow = $('#chat-window');
      if (chatWindow) chatWindow.scrollTop = chatWindow.scrollHeight;
    }
  }));

  const chatForm = $('#chat-form');
  chatForm?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const textarea = $('textarea', chatForm);
    const button = $('button[type=submit]', chatForm);
    const message = textarea.value.trim();
    if (!message) return;
    const chatWindow = $('#chat-window');
    const userBubble = document.createElement('div');
    userBubble.className = 'chat-message user';
    userBubble.innerHTML = `<div><strong>你</strong><p>${escapeHtml(message)}</p></div>`;
    chatWindow.appendChild(userBubble);
    textarea.value = '';
    button.disabled = true;
    button.textContent = '回复中...';
    chatWindow.scrollTop = chatWindow.scrollHeight;
    try {
      const history = $$('.chat-message', chatWindow).slice(-10).map((item) => ({
        role: item.classList.contains('user') ? 'user' : 'assistant',
        content: $('p', item)?.textContent || '',
      }));
      const response = await fetch(`/api/assignments/${chatForm.dataset.assignmentId}/chat`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message, history }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || '请求失败');
      const bubble = document.createElement('div');
      bubble.className = 'chat-message assistant';
      bubble.innerHTML = `<span class="chat-avatar">AI</span><div><strong>任务助教</strong><p>${escapeHtml(data.reply)}</p></div>`;
      chatWindow.appendChild(bubble);
    } catch (error) {
      const bubble = document.createElement('div');
      bubble.className = 'chat-message assistant error';
      bubble.innerHTML = `<span class="chat-avatar">!</span><div><strong>暂时无法回复</strong><p>${escapeHtml(error.message)}</p></div>`;
      chatWindow.appendChild(bubble);
    } finally {
      button.disabled = false;
      button.textContent = '发送 ↗';
      chatWindow.scrollTop = chatWindow.scrollHeight;
      textarea.focus();
    }
  });

  function escapeHtml(value) {
    const element = document.createElement('span');
    element.textContent = value;
    return element.innerHTML;
  }
})();
