// Node-local forms share the existing CLI API configuration endpoint.
const endpoint = '/api/api-settings';
const pendingProviders = new Set();
let saveQueue = Promise.resolve();

async function request(path = endpoint, options) {
  const response = await fetch(path, { cache: 'no-store', ...options });
  const data = await response.json();
  if (!response.ok) throw new Error(data.message || 'API 配置请求失败。');
  return data;
}

export function createApiSettings(provider, { locked = false, onPending, onSaved }) {
  const key = 'DASHSCOPE_API_KEY';
  const fields = [['DASHSCOPE_REGION', '配音地域', 'text'],
      ['DASHSCOPE_WORKSPACE', '业务空间 ID（可留空）', 'text'],
      ['tts_model', '配音模型', 'text']];
  const form = document.createElement('form');
  form.className = 'node-api-settings';
  const group = document.createElement('fieldset');
  group.disabled = true;
  group.setAttribute('aria-label', '配音 API');
  const controls = new Map();
  function addInput(name, label, type) {
    const row = document.createElement('label');
    row.textContent = label;
    const input = document.createElement('input');
    input.name = name;
    input.type = type;
    input.autocomplete = type === 'password' ? 'new-password' : 'off';
    input.spellcheck = false;
    input.setAttribute('aria-label', label);
    input.required = name !== 'DASHSCOPE_WORKSPACE' && type !== 'password';
    row.append(input);
    group.append(row);
    controls.set(name, input);
    return input;
  }
  for (const field of fields) addInput(...field);
  controls.get('DASHSCOPE_REGION').placeholder = 'ap-southeast-1（新加坡）';
  const secret = addInput(key, 'API Key', 'password');
  const status = document.createElement('p');
  status.setAttribute('role', 'status');
  form.append(group, status);

  let configured = false;
  let revealed = null;
  let revealing;
  let testing;
  let version = 0;
  function conceal() {
    revealing?.abort();
    revealing = null;
    secret.type = 'password';
    secret.value = '';
    revealed = null;
    secret.placeholder = configured ? '••••••••••••' : '输入 API Key';
  }
  function fill(data) {
    for (const [name] of fields) {
      controls.get(name).value = name === 'tts_model' ? data.tts_model : data.values[name];
    }
    configured = data.configured[key];
    conceal();
  }
  function editedKey() {
    return secret.value === revealed ? '' : secret.value.trim();
  }
  async function load() {
    const current = ++version;
    try {
      const data = await request();
      if (current !== version) return;
      fill(data);
      status.textContent = '';
      group.disabled = locked || pendingProviders.has(provider);
    } catch (error) {
      status.textContent = error.message || '无法读取 API 配置，请刷新页面。';
    }
  }

  async function reveal() {
    if (group.disabled || revealing) return;
    secret.type = 'text';
    if (!configured || secret.value) return;
    const controller = new AbortController();
    revealing = controller;
    try {
      const data = await request(endpoint + '/reveal/' + key, {
        method: 'POST', signal: controller.signal,
      });
      if (!controller.signal.aborted && form.isConnected && !secret.value) {
        revealed = data.value;
        secret.value = data.value;
      }
    } catch (error) {
      if (error.name !== 'AbortError') status.textContent = error.message;
    } finally {
      if (revealing === controller) revealing = null;
    }
  }
  secret.addEventListener('focus', reveal);
  secret.addEventListener('click', reveal);
  secret.addEventListener('blur', () => {
    revealing?.abort();
    revealing = null;
    secret.type = 'password';
  });

  form.onsubmit = event => {
    event.preventDefault();
    if (group.disabled || !form.reportValidity()) return;
    // Capture only this provider's edits. Merge with fresh settings in the shared queue.
    const values = Object.fromEntries(fields.map(([name]) => [name, controls.get(name).value.trim()]));
    const secrets = { [key]: editedKey() };
    pendingProviders.add(provider);
    group.disabled = true;
    onPending?.(true);
    status.textContent = '';
    const saving = saveQueue.then(async () => {
      const current = await request();
      const apiValues = { ...current.values };
      for (const [name, value] of Object.entries(values)) {
        if (name !== 'tts_model') apiValues[name] = value;
      }
      apiValues.DEEPSEEK_TRANSPORT = 'api';
      return request(endpoint, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          revision: current.revision, values: apiValues,
          tts_model: values.tts_model ?? current.tts_model, secrets, clear: [],
        }),
      });
    });
    saveQueue = saving.catch(() => {});
    saving.then(data => {
      fill(data);
      onSaved?.();
    }).catch(error => {
      status.textContent = error.message || '无法保存 API 配置。';
    }).finally(() => {
      secrets[key] = '';
      pendingProviders.delete(provider);
      group.disabled = locked;
      onPending?.(false);
      document.dispatchEvent(new CustomEvent('node-api-updated', { detail: { provider, source: form } }));
    });
  };
  const save = document.createElement('button');
  save.type = 'submit';
  save.textContent = '保存';
  const actions = document.createElement('div');
  actions.className = 'model-actions';
  const test = document.createElement('button');
  test.type = 'button';
  test.className = 'speech-test';
  test.textContent = '测试连通性';
  function resetTest() {
    testing?.abort();
    testing = null;
    test.disabled = false;
    test.textContent = '测试连通性';
    delete test.dataset.state;
    status.textContent = '';
  }
  form.addEventListener('input', resetTest);
  test.onclick = async () => {
    if (!controls.get('DASHSCOPE_REGION').reportValidity()) return;
    const controller = new AbortController();
    testing = controller;
    test.disabled = true;
    test.textContent = '正在测试…';
    delete test.dataset.state;
    status.textContent = '';
    try {
      const data = await request(endpoint + '/test-speech', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: controller.signal,
        body: JSON.stringify({
          region: controls.get('DASHSCOPE_REGION').value.trim(),
          workspace: controls.get('DASHSCOPE_WORKSPACE').value.trim(),
          api_key: editedKey(),
        }),
      });
      if (controller.signal.aborted) return;
      test.dataset.state = 'success';
      test.textContent = '✓ 已连通';
      status.textContent = data.message;
    } catch (error) {
      if (controller.signal.aborted) return;
      test.dataset.state = 'error';
      test.textContent = '重试连通性';
      status.textContent = error.message;
    } finally {
      if (testing === controller) {
        testing = null;
        test.disabled = false;
      }
    }
  };
  actions.append(save, test);
  group.append(actions);

  // Clear detached forms and cancel an in-flight reveal when a card is rebuilt.
  const cleanup = new MutationObserver(() => {
    if (!form.isConnected) {
      version += 1;
      testing?.abort();
      conceal();
      document.removeEventListener('node-api-updated', refreshAfterSave);
      cleanup.disconnect();
    }
  });
  function refreshAfterSave(event) {
    if (event.detail.provider === provider && event.detail.source !== form && form.isConnected) {
      void load();
    }
  }
  document.addEventListener('node-api-updated', refreshAfterSave);
  queueMicrotask(() => cleanup.observe(document.getElementById('nodes'), { childList: true }));
  void load();
  return form;
}
