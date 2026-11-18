const endpoint = '/api/translation-models';
const stageKeys = { translate_blocks: 'primary', review_blocks: 'review', repair_blocks: 'repair' };
let queue = Promise.resolve();
const pending = new Set();

async function request(url = endpoint, options) {
  const response = await fetch(url, { cache: 'no-store', ...options });
  const data = await response.json();
  if (!response.ok) throw new Error(data.message || '模型配置请求失败。');
  return data;
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text) node.textContent = text;
  return node;
}

function button(text, className) {
  const control = element('button', className, text);
  control.type = 'button';
  return control;
}

export function createTranslationModels(node, { locked = false, onPending, onResize }) {
  const stage = stageKeys[node];
  const manager = stage === 'primary';
  const root = element('section', 'node-model-settings');
  const group = element('fieldset');
  group.disabled = true;
  const label = element('label', 'model-picker', manager ? '翻译模型' : '选择翻译模型');
  const select = element('select');
  select.name = 'translation_model';
  select.add(new Option('正在读取模型…', ''));
  label.append(select);
  group.append(label);
  const status = element('p');
  status.setAttribute('role', 'status');
  root.append(group, status);

  let data;
  let selectedId;
  let version = 0;
  const list = element('ul', 'model-list');
  const empty = element('p', 'model-empty', '暂无已配置模型。');
  const add = button('添加', 'model-add');
  const edit = button('编辑');
  const remove = button('删除', 'model-delete');
  const form = element('form', 'model-editor');
  form.hidden = true;
  const inputs = new Map();
  const test = button('', 'model-test');
  // Fixed icons for the idle and successful states.
  test.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path class="model-test-plug" d="M12 22v-5m-4-7V3m8 7V3m-10 7h12v1a6 6 0 0 1-12 0z"/><path class="model-test-check" d="m5 12 4 4L19 6"/></svg>';
  const testStatus = element('p', 'model-test-status');
  testStatus.setAttribute('role', 'status');
  let editingId = null;
  let revealed = null;
  let revealRequest;
  let testRequest;

  function clearSecret() {
    revealRequest?.abort();
    revealRequest = null;
    revealed = null;
    const input = inputs.get('api_key');
    if (input) {
      input.type = 'password';
      input.value = '';
    }
  }

  function setTestState(state, message = '') {
    const labels = { idle: '测试连通性', running: '正在测试连通性', success: '连通性测试成功', error: '连通性测试失败，点击重试' };
    test.dataset.state = state;
    test.disabled = state === 'running';
    test.title = labels[state];
    test.setAttribute('aria-label', labels[state]);
    testStatus.textContent = message;
  }

  function resetTest() {
    testRequest?.abort();
    testRequest = null;
    setTestState('idle');
  }

  function editedKey() {
    const value = inputs.get('api_key').value;
    return value === revealed ? '' : value.trim();
  }

  function openEditor(profile) {
    clearSecret();
    resetTest();
    form.reset();
    editingId = profile?.id ?? null;
    form.setAttribute('aria-label', profile ? '编辑模型' : '新增模型');
    for (const key of ['name', 'model', 'base_url']) inputs.get(key).value = profile?.[key] ?? '';
    const secret = inputs.get('api_key');
    secret.required = !profile?.configured;
    secret.placeholder = profile?.configured ? '留空保留原密钥' : '输入 API Key';
    status.textContent = '';
    form.hidden = false;
    inputs.get('name').focus();
  }

  function closeEditor() {
    clearSecret();
    resetTest();
    form.reset();
    form.hidden = true;
    editingId = null;
  }

  function paintList() {
    empty.hidden = data.models.length > 0;
    list.hidden = !empty.hidden;
    list.replaceChildren();
    for (const model of data.models) {
      const row = button('', 'model-row');
      row.append(element('span', 'model-row-name', model.name), element('span', 'model-row-id', model.model));
      row.dataset.modelId = model.id;
      row.setAttribute('aria-pressed', String(model.id === selectedId));
      row.onclick = () => {
        selectedId = model.id;
        for (const choice of list.querySelectorAll('button')) {
          choice.setAttribute('aria-pressed', String(choice === row));
        }
      };
      const item = element('li');
      item.append(row);
      list.append(item);
    }
    edit.disabled = remove.disabled = !selectedId;
    add.textContent = data.models.length ? '添加' : '新增模型';
  }

  if (manager) {
    const heading = element('h4', 'model-list-heading', '模型列表');
    const actions = element('div', 'model-actions');
    actions.append(add, edit, remove);
    group.append(heading, list, empty, actions, form);
    for (const [key, name, type] of [
      ['name', '模型名称', 'text'], ['model', '模型 ID', 'text'],
      ['base_url', 'API 地址', 'url'], ['api_key', 'API Key', 'password'],
    ]) {
      const row = element('label', '', name);
      const input = element('input');
      input.name = key;
      input.type = type;
      input.required = key !== 'api_key';
      input.autocomplete = key === 'api_key' ? 'new-password' : 'off';
      input.spellcheck = false;
      inputs.set(key, input);
      row.append(input);
      form.append(row);
    }

    const submit = button('保存', 'model-save');
    submit.type = 'submit';
    const cancel = button('取消');
    const formActions = element('div', 'model-actions');
    formActions.append(submit, test, cancel);
    form.append(formActions, testStatus);
    add.onclick = () => openEditor();
    edit.onclick = () => openEditor(data.models.find(model => model.id === selectedId));
    remove.onclick = () => {
      const profile = data.models.find(model => model.id === selectedId);
      if (profile && window.confirm(`删除模型「${profile.name}」？`)) {
        void save({ action: 'delete', id: profile.id });
      }
    };
    cancel.onclick = () => {
      const trigger = editingId ? edit : add;
      closeEditor();
      status.textContent = '';
      trigger.focus();
    };
    form.oninput = resetTest;
    test.onclick = async () => {
      if (!form.reportValidity()) return;
      const controller = new AbortController();
      testRequest = controller;
      setTestState('running');
      try {
        const result = await request(endpoint + '/test', {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: controller.signal,
          body: JSON.stringify({
            id: editingId, base_url: inputs.get('base_url').value.trim(),
            model: inputs.get('model').value.trim(), api_key: editedKey(),
          }),
        });
        if (!controller.signal.aborted) setTestState('success', result.message);
      } catch (error) {
        if (!controller.signal.aborted) setTestState('error', error.message);
      } finally {
        if (testRequest === controller) testRequest = null;
      }
    };

    const secret = inputs.get('api_key');
    async function reveal() {
      secret.type = 'text';
      if (!editingId || secret.value || revealRequest || group.disabled) return;
      const controller = new AbortController();
      revealRequest = controller;
      try {
        const result = await request(endpoint + '/' + editingId + '/key', {
          method: 'POST', signal: controller.signal,
        });
        if (!controller.signal.aborted && root.isConnected && !secret.value) {
          revealed = result.value;
          secret.value = result.value;
        }
      } catch (error) {
        if (!controller.signal.aborted) status.textContent = error.message;
      } finally {
        if (revealRequest === controller) revealRequest = null;
      }
    }
    secret.addEventListener('focus', reveal);
    secret.addEventListener('click', reveal);
    secret.addEventListener('blur', () => {
      revealRequest?.abort();
      revealRequest = null;
      secret.type = 'password';
    });
    form.onsubmit = event => {
      event.preventDefault();
      if (group.disabled || !form.reportValidity()) return;
      const profile = Object.fromEntries([...inputs].map(([key, input]) => [key, input.value.trim()]));
      profile.id = editingId;
      profile.api_key = editedKey();
      void save({ action: 'upsert', profile });
    };
  }

  function paint(snapshot) {
    data = snapshot;
    select.replaceChildren();
    const primary = data.models.find(model => model.id === data.primary);
    if (!manager) select.add(new Option('跟随主模型', 'follow'));
    if (manager && !primary) select.add(new Option('暂无已配置模型', ''));
    for (const model of data.models) select.add(new Option(model.name, model.id));
    select.value = data[stage];
    select.disabled = data.models.length === 0;
    if (manager) {
      if (!data.models.some(model => model.id === selectedId)) selectedId = data.primary;
      if (editingId && !data.models.some(model => model.id === editingId)) closeEditor();
      paintList();
    }
  }

  async function load() {
    const current = ++version;
    try {
      const snapshot = await request();
      if (current !== version) return;
      paint(snapshot);
      group.disabled = locked || pending.has(stage);
    } catch (error) {
      if (current === version) status.textContent = error.message;
    }
  }

  async function save(payload) {
    if (group.disabled) return;
    version++;
    group.disabled = true;
    pending.add(stage);
    onPending?.(true);
    status.textContent = '';
    const saving = queue.then(async () => {
      const current = await request();
      return request(endpoint, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...payload, revision: current.revision }),
      });
    });
    queue = saving.catch(() => {});
    let focus;
    try {
      const snapshot = await saving;
      if (payload.action === 'upsert') {
        selectedId = payload.profile.id || snapshot.primary;
        closeEditor();
        focus = select;
      }
      paint(snapshot);
      if (payload.action === 'delete') focus = selectedId ? edit : add;
    } catch (error) {
      select.value = data[stage];
      status.textContent = error.message;
    } finally {
      if (payload.profile) payload.profile.api_key = '';
      pending.delete(stage);
      group.disabled = locked;
      focus?.focus();
      onPending?.(false);
      document.dispatchEvent(new CustomEvent('translation-models-updated', { detail: root }));
    }
  }
  select.onchange = () => { void save({ action: 'select', stage, selected: select.value }); };
  function refresh(event) {
    if (event.detail !== root && root.isConnected) void load();
  }
  document.addEventListener('translation-models-updated', refresh);
  const sizeObserver = new ResizeObserver(() => onResize?.());
  sizeObserver.observe(root);
  const observer = new MutationObserver(() => {
    if (!root.isConnected) {
      version++;
      clearSecret();
      resetTest();
      document.removeEventListener('translation-models-updated', refresh);
      sizeObserver.disconnect();
      observer.disconnect();
    }
  });
  queueMicrotask(() => observer.observe(document.getElementById('nodes'), { childList: true }));
  void load();
  return root;
}
