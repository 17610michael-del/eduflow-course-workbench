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

  $$('[data-toggle-checks]').forEach((button) => {
    const picker = button.closest('.assignee-picker');
    const checkboxes = $$('input[type="checkbox"]', picker);
    const count = $('[data-selection-count]', picker);
    const updatePickerSelection = () => {
      const selected = checkboxes.filter((checkbox) => checkbox.checked).length;
      const allSelected = checkboxes.length > 0 && selected === checkboxes.length;
      if (count) count.textContent = `已选 ${selected}/${checkboxes.length}`;
      button.textContent = allSelected ? '取消全选' : button.dataset.selectLabel;
      button.classList.toggle('is-clear', allSelected);
      button.disabled = checkboxes.length === 0;
    };
    button.addEventListener('click', () => {
      const shouldCheck = checkboxes.some((checkbox) => !checkbox.checked);
      checkboxes.forEach((checkbox) => {
        if (checkbox.checked === shouldCheck) return;
        checkbox.checked = shouldCheck;
        checkbox.dispatchEvent(new Event('change', { bubbles: true }));
      });
      updatePickerSelection();
    });
    checkboxes.forEach((checkbox) => checkbox.addEventListener('change', updatePickerSelection));
    updatePickerSelection();
  });

  const assignmentModePicker = $('[data-assignment-mode-picker]');
  if (assignmentModePicker) {
    const individualPanel = $('[data-individual-assignees]');
    const groupPanel = $('[data-group-assignees]');
    const syncAssignmentMode = () => {
      const mode = $('input[name="assignment_mode"]:checked', assignmentModePicker)?.value || 'individual';
      const grouped = mode === 'group';
      individualPanel.hidden = grouped;
      groupPanel.hidden = !grouped;
      $$('input[type="checkbox"]', individualPanel).forEach((input) => { input.disabled = grouped; });
      $$('input[type="checkbox"]', groupPanel).forEach((input) => { input.disabled = !grouped; });
      $$('label', assignmentModePicker).forEach((label) => label.classList.toggle('active', label.querySelector('input')?.checked));
    };
    $$('input[name="assignment_mode"]', assignmentModePicker).forEach((input) => input.addEventListener('change', syncAssignmentMode));
    syncAssignmentMode();
  }

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

  const userSearch = $('[data-user-search]');
  const userFilterButtons = $$('[data-user-filter]');
  const userRoleCards = $$('[data-user-role-filter]');
  if (userSearch) {
    let activeUserRole = 'all';
    const refreshUserDirectory = () => {
      const keyword = userSearch.value.trim().toLowerCase();
      let visibleCount = 0;
      $$('[data-user-role-section]').forEach((section) => {
        const roleMatches = activeUserRole === 'all' || section.dataset.userRoleSection === activeUserRole;
        let sectionVisibleCount = 0;
        $$('[data-user-row]', section).forEach((row) => {
          const visible = roleMatches && row.dataset.userRow.toLowerCase().includes(keyword);
          row.hidden = !visible;
          if (visible) sectionVisibleCount += 1;
        });
        section.hidden = !roleMatches || sectionVisibleCount === 0;
        visibleCount += sectionVisibleCount;
      });
      $('[data-user-empty]')?.toggleAttribute('hidden', visibleCount !== 0);
    };
    const selectUserRole = (role) => {
      activeUserRole = role;
      userFilterButtons.forEach((button) => button.classList.toggle('active', button.dataset.userFilter === role));
      userRoleCards.forEach((card) => card.classList.toggle('active', role === 'all' || card.dataset.userRoleFilter === role));
      refreshUserDirectory();
    };
    userSearch.addEventListener('input', refreshUserDirectory);
    userFilterButtons.forEach((button) => button.addEventListener('click', () => selectUserRole(button.dataset.userFilter)));
    userRoleCards.forEach((card) => card.addEventListener('click', () => selectUserRole(card.dataset.userRoleFilter)));
  }

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

  const aiChat = $('[data-ai-chat]');
  if (aiChat) {
    const form = $('[data-ai-chat-form]', aiChat);
    const textarea = $('textarea', form);
    const sendButton = $('button[type=submit]', form);
    const thread = $('[data-ai-chat-thread]', aiChat);
    const welcome = $('[data-ai-chat-welcome]', aiChat);
    const clearButton = $('[data-clear-ai-chat]', aiChat);
    const scrollToLatest = () => { thread.scrollTop = thread.scrollHeight; };
    const appendMessage = (role, content, options = {}) => {
      const article = document.createElement('article');
      article.className = `ai-message ${role}${options.error ? ' error' : ''}${options.loading ? ' loading' : ''}`;
      if (options.loading) article.dataset.aiLoading = '';
      if (role === 'assistant') {
        const avatar = document.createElement('span');
        avatar.className = 'ai-message-avatar';
        avatar.textContent = options.error ? '!' : 'DS';
        article.appendChild(avatar);
      }
      const bubble = document.createElement('div');
      const author = document.createElement('strong');
      const message = document.createElement('p');
      author.textContent = role === 'user' ? '你' : options.error ? '暂时无法回复' : 'DeepSeek';
      message.textContent = content;
      bubble.append(author, message);
      article.appendChild(bubble);
      thread.appendChild(article);
      if (welcome) welcome.hidden = true;
      scrollToLatest();
      return article;
    };

    form?.addEventListener('submit', async (event) => {
      event.preventDefault();
      const message = textarea.value.trim();
      if (!message || sendButton.disabled) return;
      appendMessage('user', message);
      textarea.value = '';
      sendButton.disabled = true;
      sendButton.textContent = '思考中…';
      const loading = appendMessage('assistant', '正在整理回答…', { loading: true });
      try {
        const response = await fetch('/api/ai-chat', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message }),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'DeepSeek API 暂时不可用');
        loading.remove();
        appendMessage('assistant', data.reply);
        clearButton.disabled = false;
      } catch (error) {
        loading.remove();
        appendMessage('assistant', error.message, { error: true });
      } finally {
        sendButton.disabled = false;
        sendButton.innerHTML = '发送 <span>↗</span>';
        textarea.focus();
      }
    });
    textarea?.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
        event.preventDefault();
        form.requestSubmit();
      }
    });
    $$('[data-ai-prompt]', aiChat).forEach((button) => button.addEventListener('click', () => {
      textarea.value = button.dataset.aiPrompt;
      textarea.focus();
    }));
    clearButton?.addEventListener('click', async () => {
      if (!window.confirm('确定清空你的全部 AI 对话记录吗？')) return;
      clearButton.disabled = true;
      try {
        const response = await fetch('/api/ai-chat/clear', { method: 'POST' });
        if (!response.ok) throw new Error('清空失败，请稍后重试');
        $$('.ai-message', thread).forEach((item) => item.remove());
        if (welcome) welcome.hidden = false;
      } catch (error) {
        appendMessage('assistant', error.message, { error: true });
        clearButton.disabled = false;
      }
    });
    scrollToLatest();
  }

  const knowledgeBase = $('[data-knowledge-base]');
  if (knowledgeBase) {
    const fileInput = $('[data-knowledge-file]', knowledgeBase);
    const fileName = $('[data-knowledge-file-name]', knowledgeBase);
    fileInput?.addEventListener('change', () => {
      if (fileInput.files?.[0] && fileName) fileName.textContent = fileInput.files[0].name;
    });

    const form = $('[data-knowledge-form]', knowledgeBase);
    const textarea = form ? $('textarea', form) : null;
    const sendButton = form ? $('button[type=submit]', form) : null;
    const thread = $('[data-knowledge-thread]', knowledgeBase);
    const welcome = $('[data-knowledge-welcome]', knowledgeBase);
    const clearButton = $('[data-clear-knowledge-chat]', knowledgeBase);
    const username = knowledgeBase.dataset.knowledgeUsername;
    const scrollToLatest = () => { if (thread) thread.scrollTop = thread.scrollHeight; };
    const appendKnowledgeMessage = (role, content, sources = [], options = {}) => {
      const article = document.createElement('article');
      article.className = `knowledge-message ${role}${options.error ? ' error' : ''}${options.loading ? ' loading' : ''}`;
      if (role === 'assistant') {
        const avatar = document.createElement('span');
        avatar.textContent = options.error ? '!' : 'AI';
        article.appendChild(avatar);
      }
      const bubble = document.createElement('div');
      const author = document.createElement('strong');
      author.textContent = role === 'user' ? '你' : options.error ? '暂时无法回答' : '知识库助手';
      const paragraph = document.createElement('p');
      paragraph.textContent = content;
      bubble.append(author, paragraph);
      if (sources.length) {
        const sourceBox = document.createElement('div');
        sourceBox.className = 'knowledge-sources';
        sources.forEach((source, index) => {
          const link = document.createElement('a');
          link.href = source.url;
          const mark = document.createElement('b');
          mark.textContent = `[${index + 1}] `;
          link.append(mark, document.createTextNode(`${source.name} · 片段 ${source.chunk}`));
          sourceBox.appendChild(link);
        });
        bubble.appendChild(sourceBox);
      }
      article.appendChild(bubble);
      thread?.appendChild(article);
      if (welcome) welcome.hidden = true;
      scrollToLatest();
      return article;
    };

    form?.addEventListener('submit', async (event) => {
      event.preventDefault();
      const message = textarea.value.trim();
      if (!message || sendButton.disabled) return;
      appendKnowledgeMessage('user', message);
      textarea.value = '';
      sendButton.disabled = true;
      sendButton.textContent = '检索中…';
      const loading = appendKnowledgeMessage('assistant', '正在检索私有资料并组织回答…', [], { loading: true });
      try {
        const response = await fetch('/api/knowledge/chat', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message, username }),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || '知识库问答暂时不可用');
        loading.remove();
        appendKnowledgeMessage('assistant', data.reply, data.sources || []);
        if (clearButton) clearButton.disabled = false;
      } catch (error) {
        loading.remove();
        appendKnowledgeMessage('assistant', error.message, [], { error: true });
      } finally {
        sendButton.disabled = false;
        sendButton.innerHTML = '检索并提问 <span>↗</span>';
        textarea.focus();
      }
    });
    textarea?.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
        event.preventDefault();
        form.requestSubmit();
      }
    });
    $$('[data-knowledge-prompt]', knowledgeBase).forEach((button) => button.addEventListener('click', () => {
      textarea.value = button.dataset.knowledgePrompt;
      textarea.focus();
    }));
    clearButton?.addEventListener('click', async () => {
      if (!window.confirm('确定清空你在当前学生知识库中的问答记录吗？')) return;
      clearButton.disabled = true;
      try {
        const response = await fetch('/api/knowledge/chat/clear', {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username }),
        });
        if (!response.ok) throw new Error('清空失败，请稍后重试');
        $$('.knowledge-message', thread).forEach((item) => item.remove());
        if (welcome) welcome.hidden = false;
      } catch (error) {
        appendKnowledgeMessage('assistant', error.message, [], { error: true });
        clearButton.disabled = false;
      }
    });
    scrollToLatest();
  }

  const projectMonitor = $('[data-project-monitor]');
  if (projectMonitor) {
    const dialog = $('[data-agent-token-dialog]', projectMonitor);
    const usernameField = $('[data-agent-username]', dialog);
    const workspaceField = $('[data-agent-workspace]', dialog);
    const tokenField = $('[data-agent-token]', dialog);
    $$('[data-create-agent-token]', projectMonitor).forEach((button) => button.addEventListener('click', async () => {
      const original = button.textContent;
      button.disabled = true;
      button.textContent = '正在生成…';
      try {
        const username = button.dataset.createAgentToken;
        const response = await fetch(`/api/project-agents/${encodeURIComponent(username)}/token`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ workspace_root: button.dataset.workspace }),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Token 生成失败');
        usernameField.value = data.username;
        workspaceField.value = data.workspace_root;
        tokenField.value = data.token;
        if (typeof dialog.showModal === 'function') dialog.showModal();
        else dialog.setAttribute('open', '');
        button.textContent = '查看 Token';
      } catch (error) {
        window.alert(error.message);
        button.textContent = original;
      } finally {
        button.disabled = false;
      }
    }));
    $$('[data-close-agent-dialog]', dialog).forEach((button) => button.addEventListener('click', () => {
      tokenField.value = '';
      if (typeof dialog.close === 'function') dialog.close();
      else dialog.removeAttribute('open');
    }));
    $('[data-copy-agent-token]', dialog)?.addEventListener('click', async (event) => {
      try {
        await navigator.clipboard.writeText(tokenField.value);
        event.currentTarget.textContent = '已复制';
        setTimeout(() => { event.currentTarget.textContent = '复制'; }, 1500);
      } catch (_) {
        tokenField.select();
      }
    });
  }

  const deepseekWorkbench = $('[data-deepseek-workbench]');
  if (deepseekWorkbench) {
    const sessionId = deepseekWorkbench.dataset.sessionId;
    const thread = $('[data-ds-chat-thread]', deepseekWorkbench);
    const form = $('[data-ds-message-form]', deepseekWorkbench);
    const textarea = form?.querySelector('textarea');
    const sendButton = form?.querySelector('button[type=submit]');
    const fileList = $('[data-ds-file-list]', deepseekWorkbench);
    const pathLabel = $('[data-ds-current-path]', deepseekWorkbench);
    const backButton = $('[data-ds-files-back]', deepseekWorkbench);
    const preview = $('[data-ds-file-preview]', deepseekWorkbench);
    let currentPath = '.';

    const errorMessage = async (response, fallback) => {
      try {
        const data = await response.json();
        return data.error || fallback;
      } catch (_) {
        return fallback;
      }
    };

    $$('[data-new-ds-session]', deepseekWorkbench).forEach((button) => button.addEventListener('click', async () => {
      button.disabled = true;
      try {
        const response = await fetch('/api/deepseek-workbench/sessions', { method: 'POST' });
        if (!response.ok) throw new Error(await errorMessage(response, '新建对话失败'));
        const data = await response.json();
        window.location.href = data.url;
      } catch (error) {
        window.alert(error.message);
        button.disabled = false;
      }
    }));

    $$('[data-delete-ds-session]', deepseekWorkbench).forEach((button) => button.addEventListener('click', async (event) => {
      event.preventDefault();
      event.stopPropagation();
      if (!window.confirm('确定删除这条项目对话吗？项目文件不会被删除。')) return;
      button.disabled = true;
      const response = await fetch(`/api/deepseek-workbench/sessions/${button.dataset.deleteDsSession}`, { method: 'DELETE' });
      if (!response.ok) {
        window.alert(await errorMessage(response, '删除对话失败'));
        button.disabled = false;
        return;
      }
      window.location.href = '/deepseek-workbench';
    }));

    $$('[data-ds-prompt]', deepseekWorkbench).forEach((button) => button.addEventListener('click', () => {
      if (!textarea) return;
      textarea.value = button.dataset.dsPrompt;
      textarea.focus();
    }));

    const appendMessage = (role, content, toolEvents = []) => {
      $('[data-ds-welcome]', thread)?.remove();
      const article = document.createElement('article');
      article.className = `ds-message ${role}`;
      const events = toolEvents.length ? `<div class="ds-tool-events">${toolEvents.map((item) => `<span class="${item.ok ? 'ok' : 'error'}">${item.ok ? '✓' : '!'} ${escapeHtml({ list_directory: '浏览目录', read_file: '读取文件', search_text: '搜索代码' }[item.name] || item.name || '工具')}</span>`).join('')}</div>` : '';
      article.innerHTML = `${role === 'assistant' ? '<span class="ds-message-avatar">DS</span>' : ''}<div><strong>${role === 'assistant' ? 'DeepSeek' : '你'}</strong><div class="ds-message-content"><p>${escapeHtml(content).replace(/\n/g, '<br>')}</p></div>${events}</div>`;
      thread?.appendChild(article);
      thread?.scrollTo({ top: thread.scrollHeight, behavior: 'smooth' });
      return article;
    };

    form?.addEventListener('submit', async (event) => {
      event.preventDefault();
      const message = textarea.value.trim();
      if (!message || !sessionId) return;
      textarea.value = '';
      textarea.disabled = true;
      sendButton.disabled = true;
      appendMessage('user', message);
      const loading = appendMessage('assistant', '正在查看项目并思考…');
      loading.classList.add('loading');
      try {
        const response = await fetch(`/api/deepseek-workbench/sessions/${sessionId}/messages`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message }),
        });
        if (!response.ok) throw new Error(await errorMessage(response, 'DeepSeek 请求失败'));
        const data = await response.json();
        loading.remove();
        appendMessage('assistant', data.reply, data.tool_events || []);
        const title = $('.ds-chat-topbar strong', deepseekWorkbench);
        if (title) title.textContent = data.title;
        const selectedTitle = $('.ds-session-item.active strong', deepseekWorkbench);
        if (selectedTitle) selectedTitle.textContent = data.title;
      } catch (error) {
        loading.remove();
        appendMessage('assistant', `请求失败：${error.message}`);
      } finally {
        textarea.disabled = false;
        sendButton.disabled = false;
        textarea.focus();
      }
    });
    textarea?.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        form?.requestSubmit();
      }
    });

    const fileItemMarkup = (entry) => `<button type="button" class="ds-file-item" data-ds-file-type="${entry.type}" data-ds-file-path="${escapeHtml(entry.path)}"><span>${entry.type === 'directory' ? '▸' : '◇'}</span><span><strong>${escapeHtml(entry.name)}</strong><small>${entry.type === 'directory' ? '目录' : `${Math.max(1, Math.ceil((entry.size || 0) / 1024))} KB`}</small></span></button>`;
    const bindFileItems = () => {
      $$('[data-ds-file-path]', fileList).forEach((button) => button.addEventListener('click', async () => {
        if (button.dataset.dsFileType === 'directory') {
          await loadFiles(button.dataset.dsFilePath);
          return;
        }
        const response = await fetch(`/api/deepseek-workbench/file?path=${encodeURIComponent(button.dataset.dsFilePath)}`);
        if (!response.ok) {
          window.alert(await errorMessage(response, '文件无法预览'));
          return;
        }
        const data = await response.json();
        $('[data-ds-preview-name]', preview).textContent = data.path;
        $('[data-ds-preview-content]', preview).textContent = data.content;
        preview.hidden = false;
      }));
    };
    const loadFiles = async (path = '.') => {
      if (!fileList) return;
      const response = await fetch(`/api/deepseek-workbench/files?path=${encodeURIComponent(path)}`);
      if (!response.ok) {
        window.alert(await errorMessage(response, '目录读取失败'));
        return;
      }
      const data = await response.json();
      currentPath = path || '.';
      pathLabel.textContent = currentPath;
      backButton.disabled = currentPath === '.';
      fileList.innerHTML = data.entries.length ? data.entries.map(fileItemMarkup).join('') : '<div class="ds-files-empty">这个目录是空的</div>';
      bindFileItems();
    };
    bindFileItems();
    backButton?.addEventListener('click', () => {
      const parts = currentPath.split('/').filter((part) => part && part !== '.');
      parts.pop();
      loadFiles(parts.length ? parts.join('/') : '.');
    });
    $('[data-refresh-ds-files]', deepseekWorkbench)?.addEventListener('click', () => loadFiles(currentPath));
    $('[data-close-ds-preview]', deepseekWorkbench)?.addEventListener('click', () => { preview.hidden = true; });
    thread?.scrollTo({ top: thread.scrollHeight });
  }

  function escapeHtml(value) {
    const element = document.createElement('span');
    element.textContent = value;
    return element.innerHTML;
  }
})();
