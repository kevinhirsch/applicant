// static/js/ollamaModels.js — In-UI Ollama local-model manager.
// Renders into #adm-ollama-mgr inside the model-endpoints settings panel.
// Talks to the admin-gated /api/ollama/* proxy. Defensive throughout: if
// anything is unavailable (non-admin, Ollama down), it hides quietly rather
// than breaking the surrounding settings UI.

let _busy = false;

function _esc(s) {
  return String(s || '').replace(/[&<>"]/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

export async function initOllamaModels() {
  const host = document.getElementById('adm-ollama-mgr');
  if (!host) return;
  let status;
  try {
    const r = await fetch('/api/ollama/status', { credentials: 'same-origin' });
    if (!r.ok) { host.innerHTML = ''; return; }   // non-admin / not available
    status = await r.json();
  } catch { host.innerHTML = ''; return; }

  if (!status || !status.reachable) {
    host.innerHTML =
      '<div class="adm-ep-inline-msg" style="opacity:0.6;font-size:11px;margin-top:8px;">'
      + 'Local models: Ollama isn\'t reachable. Enable the bundled service — add '
      + '<code>COMPOSE_FILE=docker-compose.yml:docker/ollama.yml</code> to <code>.env</code> '
      + 'and run <code>docker compose up -d</code>.</div>';
    return;
  }

  host.innerHTML = `
    <div style="display:flex;align-items:center;gap:8px;margin-top:10px;">
      <strong style="font-size:12px;">Local models (Ollama)</strong>
      <span style="font-size:10px;opacity:0.5;">${_esc(status.endpoint || '')}</span>
    </div>
    <div style="display:flex;gap:6px;margin:6px 0;">
      <input id="adm-ollama-pull-name" type="text" style="flex:1;"
             placeholder="Model to install, e.g. qwen2.5 or llama3.1:8b">
      <button class="admin-btn-add" id="adm-ollama-pull-btn" style="width:60px;">Install</button>
    </div>
    <div id="adm-ollama-progress" class="adm-ep-inline-msg" style="font-size:11px;"></div>
    <div id="adm-ollama-list" style="margin-top:4px;"></div>`;

  document.getElementById('adm-ollama-pull-btn').addEventListener('click', _pull);
  document.getElementById('adm-ollama-pull-name').addEventListener('keydown',
    e => { if (e.key === 'Enter') _pull(); });
  await _refreshList();
}

async function _refreshList() {
  const list = document.getElementById('adm-ollama-list');
  if (!list) return;
  try {
    const r = await fetch('/api/ollama/models', { credentials: 'same-origin' });
    const d = await r.json();
    const models = (d && d.models) || [];
    if (!models.length) {
      list.innerHTML = '<div class="admin-empty">No models installed yet</div>';
      return;
    }
    list.innerHTML = models.map(m => {
      const gb = m.size ? (m.size / 1e9).toFixed(1) + ' GB' : '';
      return `<div style="display:flex;align-items:center;justify-content:space-between;padding:3px 0;border-top:1px solid var(--border,#2a2d35);">
        <span style="font-size:12px;">${_esc(m.name)} <span style="opacity:0.45;font-size:10px;">${gb}</span></span>
        <button class="admin-btn-sm adm-ollama-rm" data-name="${_esc(m.name)}" title="Remove" style="width:28px;">✕</button>
      </div>`;
    }).join('');
    list.querySelectorAll('.adm-ollama-rm').forEach(b =>
      b.addEventListener('click', () => _remove(b.getAttribute('data-name'))));
  } catch {
    list.innerHTML = '<div class="admin-empty">Could not list models</div>';
  }
}

async function _pull() {
  if (_busy) return;
  const inp = document.getElementById('adm-ollama-pull-name');
  const prog = document.getElementById('adm-ollama-progress');
  const name = (inp.value || '').trim();
  if (!name) return;
  _busy = true;
  if (prog) prog.textContent = 'Starting…';
  try {
    const fd = new FormData();
    fd.append('name', name);
    const resp = await fetch('/api/ollama/pull',
      { method: 'POST', body: fd, credentials: 'same-origin' });
    if (!resp.ok || !resp.body) {
      if (prog) prog.textContent = 'Failed to start install';
      _busy = false; return;
    }
    const reader = resp.body.getReader();
    const dec = new TextDecoder();
    let buf = '';
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let idx;
      while ((idx = buf.indexOf('\n\n')) >= 0) {
        const line = buf.slice(0, idx).replace(/^data: ?/, '').trim();
        buf = buf.slice(idx + 2);
        if (!line) continue;
        let o; try { o = JSON.parse(line); } catch { continue; }
        if (o.error) { if (prog) prog.textContent = 'Error: ' + o.error; }
        else if (o.status === 'done') { if (prog) prog.textContent = 'Installed ' + name; }
        else if (prog) {
          let t = o.status || 'working';
          if (o.total && o.completed) t += ' ' + Math.floor(100 * o.completed / o.total) + '%';
          prog.textContent = t;
        }
      }
    }
    inp.value = '';
    await _refreshList();
    if (window.modelsModule && window.modelsModule.refreshModels)
      window.modelsModule.refreshModels(true);
  } catch (e) {
    if (prog) prog.textContent = 'Error: ' + e;
  }
  _busy = false;
}

async function _remove(name) {
  if (!name || !confirm('Remove ' + name + '?')) return;
  const prog = document.getElementById('adm-ollama-progress');
  try {
    const r = await fetch('/api/ollama/models?name=' + encodeURIComponent(name),
      { method: 'DELETE', credentials: 'same-origin' });
    if (r.ok) {
      if (prog) prog.textContent = 'Removed ' + name;
      await _refreshList();
      if (window.modelsModule && window.modelsModule.refreshModels)
        window.modelsModule.refreshModels(true);
    } else if (prog) { prog.textContent = 'Remove failed'; }
  } catch (e) { if (prog) prog.textContent = 'Error: ' + e; }
}

export default { initOllamaModels };
