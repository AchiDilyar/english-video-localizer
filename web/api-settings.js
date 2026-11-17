const dialog = document.getElementById('api-settings-dialog');
const form = document.getElementById('api-settings-form');
const status = document.getElementById('api-settings-status');
const save = document.getElementById('api-settings-save');
const keys = ['DEEPSEEK_API_KEY', 'DASHSCOPE_API_KEY'];
let revision = null;
let pending = false;

function clearSecrets() {
  for (const name of keys) {
    form.elements[name].value = '';
    form.elements[`clear_${name}`].checked = false;
  }
}
function fill(data) {
  revision = data.revision;
  for (const [name, value] of Object.entries(data.values)) {
    if (form.elements[name]) form.elements[name].value = value;
  }
  form.elements.tts_model.value = data.tts_model;
  for (const name of keys) {
    form.querySelector(`[data-key-status="${name}"]`).textContent = data.configured[name] ? '（已配置，原值隐藏）' : '（未配置）';
  }
  clearSecrets();
}
document.getElementById('api-settings-open').onclick = async () => {
  form.reset();
  revision = null;
  status.textContent = '正在读取本机配置…';
  save.disabled = true;
  dialog.showModal();
  try {
    const response = await fetch('/api/api-settings', { cache: 'no-store' });
    const data = await response.json();
    if (!response.ok) throw new Error(data.message);
    if (!dialog.open) return;
    fill(data);
    status.textContent = '';
    save.disabled = false;
  } catch {
    status.textContent = '无法读取配置，请关闭后重试。';
  }
};
document.getElementById('api-settings-close').onclick = () => dialog.close();
dialog.addEventListener('close', clearSecrets);
form.onsubmit = async event => {
  event.preventDefault();
  if (!revision || pending) return;
  pending = true;
  save.disabled = true;
  const values = Object.fromEntries(['DEEPSEEK_BASE_URL', 'DEEPSEEK_MODEL', 'DASHSCOPE_REGION', 'DASHSCOPE_WORKSPACE'].map(name => [name, form.elements[name].value.trim()]));
  values.DEEPSEEK_TRANSPORT = 'api';
  const payload = {
    revision, values, tts_model: form.elements.tts_model.value.trim(),
    secrets: Object.fromEntries(keys.map(name => [name, form.elements[name].value])),
    clear: keys.filter(name => form.elements[`clear_${name}`].checked),
  };
  status.textContent = '正在保存…';
  try {
    const response = await fetch('/api/api-settings', {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.message || '保存失败。');
    fill(data);
    status.textContent = '已保存，下次任务生效；未发起任何模型调用。';
  } catch (error) {
    status.textContent = error.message || '保存失败，请重试。';
  } finally {
    clearSecrets();
    payload.secrets = {};
    pending = false;
    save.disabled = false;
  }
};
