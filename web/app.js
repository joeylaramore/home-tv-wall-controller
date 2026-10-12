const grid = document.querySelector('#grid');
const setup = document.querySelector('#setup');
const discovered = document.querySelector('#discovered');
const message = document.querySelector('#message');
let tvs = [];
let found = [];
let scenes = [];
let editing = false;
let draggedIndex = null;
let remoteIndex = null;

function openRemote(index) {
  remoteIndex = index; document.querySelector('#remote-title').textContent = `${tvs[index].name} remote`; document.querySelector('#remote-panel').hidden = false;
}

function render() {
  grid.replaceChildren();
  tvs.forEach((tv, index) => {
    const tile = document.createElement('article'); tile.className = 'tile'; tile.draggable = editing; tile.dataset.index = index;
    const heading = editing ? document.createElement('input') : document.createElement('h2');
    if (editing) { heading.className = 'tile-name'; heading.value = tv.name; heading.setAttribute('aria-label', `Name for TV ${index + 1}`); heading.addEventListener('input', () => { tv.name = heading.value; }); }
    else heading.textContent = tv.name;
    const actions = document.createElement('div'); actions.className = 'tile-buttons';
    for (const [label, action] of [['On', 'on'], ['Off', 'off']]) {
      const button = document.createElement('button'); button.textContent = label; button.className = action;
      button.dataset.target = index; button.dataset.action = action; button.disabled = editing; actions.append(button);
    }
    const inputs = document.createElement('div'); inputs.className = 'input-buttons';
    for (let input = 1; input <= 4; input++) { const button = document.createElement('button'); button.textContent = `HDMI ${input}`; button.dataset.target = index; button.dataset.input = `InputHDMI${input}`; button.disabled = editing; inputs.append(button); }
    const apps = document.createElement('div'); apps.className = 'app-controls';
    const select = document.createElement('select'); select.className = 'app-select'; select.setAttribute('aria-label', `App for ${tv.name}`); select.disabled = editing;
    const placeholder = document.createElement('option'); placeholder.textContent = 'Loading apps…'; placeholder.value = ''; select.append(placeholder);
    const launch = document.createElement('button'); launch.textContent = 'Open app'; launch.className = 'launch-app'; launch.dataset.target = index; launch.disabled = editing;
    apps.append(select, launch); tile.append(heading, actions, inputs, apps); grid.append(tile); loadApps(index, select);
    if (editing) {
      tile.addEventListener('dragstart', () => { draggedIndex = index; tile.classList.add('dragging'); });
      tile.addEventListener('dragend', () => tile.classList.remove('dragging'));
      tile.addEventListener('dragover', event => event.preventDefault());
      tile.addEventListener('drop', event => { event.preventDefault(); if (draggedIndex === null || draggedIndex === index) return; const [moved] = tvs.splice(draggedIndex, 1); tvs.splice(index, 0, moved); draggedIndex = null; render(); });
    }
  });
  setup.hidden = tvs.length > 0;
  document.querySelector('#edit-layout').hidden = tvs.length === 0 || editing;
  document.querySelector('#save-layout').hidden = !editing;
  document.querySelectorAll('.group button').forEach(button => { button.disabled = editing; });
  document.querySelectorAll('#scenes button').forEach(button => { button.disabled = editing; });
}

async function loadApps(index, select) {
  try {
    const response = await fetch(`/api/apps/${index}`, {cache:'no-store'}); if (!response.ok) throw Error();
    const apps = await response.json(); select.replaceChildren(); apps.sort((a, b) => a.name.localeCompare(b.name)).forEach(app => { const option = document.createElement('option'); option.value = app.id; option.textContent = app.name; select.append(option); });
    if (!apps.length) { const option = document.createElement('option'); option.textContent = 'No apps found'; select.append(option); }
  } catch (_) { select.replaceChildren(); const option = document.createElement('option'); option.textContent = 'Apps unavailable'; select.append(option); }
}

async function loadScenes() {
  const container = document.querySelector('#scenes');
  try {
    const response = await fetch('/api/scenes', {cache:'no-store'}); if (!response.ok) throw Error(); scenes = await response.json(); container.replaceChildren();
    scenes.forEach((scene, index) => { const button = document.createElement('button'); button.textContent = scene.name; button.dataset.scene = index; container.append(button); }); container.hidden = !scenes.length;
  } catch (_) { container.hidden = true; }
}

async function load() {
  try {
    const response = await fetch('/api/tvs', {cache:'no-store'}); if (!response.ok) throw Error(); tvs = await response.json(); render(); loadScenes();
    message.textContent = tvs.length ? 'Ready. Controls are sent over your local network.' : 'Discover your Roku TVs to get started.';
    return true;
  } catch (_) { message.textContent = 'Controller unavailable. Reconnect to your local network and reload.'; return false; }
}

document.querySelector('#discover').addEventListener('click', async () => {
  message.textContent = 'Looking for Roku TVs on this network…';
  try {
    const response = await fetch('/api/discover', {cache:'no-store'}); if (!response.ok) throw Error();
    found = await response.json(); discovered.replaceChildren();
    if (!found.length) { message.textContent = 'No Roku TVs found. Check that the controller is on the same network.'; return; }
    found.forEach((device, index) => {
      const row = document.createElement('label'); row.className = 'found';
      const checkbox = document.createElement('input'); checkbox.type = 'checkbox'; checkbox.checked = true; checkbox.dataset.index = index;
      const text = document.createElement('span'); text.textContent = `${device['user-device-name'] || device['model-name'] || 'Roku TV'} · ${device['wifi-mac'] || device['ethernet-mac'] || device['device-id']}`;
      row.append(checkbox, text); discovered.append(row);
    });
    document.querySelector('#save').hidden = false; message.textContent = `${found.length} Roku TV${found.length === 1 ? '' : 's'} found.`;
  } catch (_) { message.textContent = 'Discovery failed. Check the controller network and Roku mobile-app setting.'; }
});

document.querySelector('#save').addEventListener('click', async () => {
  const selected = [...discovered.querySelectorAll('input:checked')].map((box, position) => { const device = found[Number(box.dataset.index)]; return {name: device['user-device-name'] || `TV ${position + 1}`, device_id: device['device-id'], ip: device.ip || ''}; });
  if (!selected.length) return;
  const response = await fetch('/api/configure', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({tvs:selected})});
  if (!response.ok) { message.textContent = 'Could not save the TV wall.'; return; }
  tvs = selected; render(); message.textContent = `${tvs.length} TVs saved.`;
});

document.querySelector('#edit-layout').addEventListener('click', () => { editing = true; render(); message.textContent = 'Drag TVs to reorder them and edit names, then save layout.'; });

document.querySelector('#save-layout').addEventListener('click', async () => {
  const response = await fetch('/api/configure', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({tvs: tvs.map(tv => ({name: tv.name.trim() || 'Roku TV', device_id: tv.device_id, mac: tv.mac || '', ip: tv.ip || ''}))})});
  if (!response.ok) { message.textContent = 'Could not save the layout.'; return; }
  editing = false; render(); message.textContent = 'Layout saved.';
});

document.querySelector('#backup-config').addEventListener('click', async () => {
  try {
    const response = await fetch('/api/backup', {cache:'no-store'});
    if (!response.ok) throw Error('Could not back up the configuration.');
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement('a');
    link.href = url; link.download = 'roku-wall-config.json';
    document.body.append(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    message.textContent = 'Saved configuration downloaded. Save layout first to include unsaved edits.';
  } catch (error) { message.textContent = error.message || 'Backup failed.'; }
});

const restoreFile = document.querySelector('#restore-file');
document.querySelector('#restore-config').addEventListener('click', () => restoreFile.click());
restoreFile.addEventListener('change', async () => {
  const file = restoreFile.files[0];
  if (!file) return;
  const button = document.querySelector('#restore-config');
  button.disabled = true;
  try {
    if (file.size > 262144) throw Error('Backup must be no larger than 256 KB.');
    const config = JSON.parse(await file.text());
    if (!window.confirm('Restore this backup and replace the current TV names and layout? The previous configuration will be saved on the controller.')) return;
    const response = await fetch('/api/restore', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(config)});
    const result = await response.json();
    if (!response.ok) throw Error(result.error || 'Restore failed.');
    editing = false;
    const loaded = await load();
    message.textContent = loaded ? 'Configuration restored. The previous configuration was saved on the controller.' : 'Configuration restored, but the TV list could not be refreshed. Reload to reconnect.';
  } catch (error) { message.textContent = `Restore failed: ${error.message}`; }
  finally { button.disabled = false; restoreFile.value = ''; }
});

document.addEventListener('click', async event => {
  if (!editing && event.target.closest('.tile') && !event.target.closest('button, select, input')) { openRemote(Number(event.target.closest('.tile').dataset.index)); return; }
  const remote = event.target.closest('button[data-remote]');
  if (remote && remoteIndex !== null) {
    const buttons = [...document.querySelectorAll('#remote-panel button')]; buttons.forEach(item => item.disabled = true); message.textContent = `Sending ${remote.textContent}…`;
    try { const response = await fetch(`/api/${remoteIndex}/keypress/${remote.dataset.remote}`, {method:'POST'}); if (!response.ok) throw Error(); const result = await response.json(); message.textContent = result[0].ok ? `${result[0].name}: command sent.` : `Could not reach ${result[0].name}.`; }
    catch (_) { message.textContent = 'Could not send the remote command.'; } finally { buttons.forEach(item => item.disabled = false); }
    return;
  }
  const scene = event.target.closest('button[data-scene]');
  if (scene) {
    const index = Number(scene.dataset.scene); document.querySelectorAll('button').forEach(item => { item.disabled = true; }); message.textContent = `Running ${scenes[index].name}…`;
    try { const response = await fetch(`/api/scenes/${index}/run`, {method:'POST'}); if (!response.ok) throw Error(); const result = await response.json(); const failed = result.results.filter(item => !item.ok).map(item => item.name); message.textContent = failed.length ? `Scene completed with failures: ${failed.join(', ')}.` : `${result.name} completed.`; }
    catch (_) { message.textContent = 'Could not run scene.'; } finally { render(); } return;
  }
  const input = event.target.closest('button[data-input]');
  if (input) {
    document.querySelectorAll('button').forEach(item => { item.disabled = true; }); message.textContent = `Selecting ${input.dataset.input.replace('Input', '')}…`;
    try { const response = await fetch(`/api/${input.dataset.target}/input/${input.dataset.input}`, {method:'POST'}); if (!response.ok) throw Error(); const results = await response.json(); const failed = results.filter(result => !result.ok).map(result => result.name); message.textContent = failed.length ? `Could not reach: ${failed.join(', ')}.` : `${results[0].name}: input selected.`; }
    catch (_) { message.textContent = 'Could not select the input.'; } finally { render(); } return;
  }
  const launch = event.target.closest('button.launch-app');
  if (launch) {
    const appId = launch.parentElement.querySelector('select').value; if (!appId) return; launch.disabled = true; message.textContent = 'Opening app…';
    try { const response = await fetch(`/api/${launch.dataset.target}/launch`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({app_id: appId})}); if (!response.ok) throw Error(); const result = await response.json(); message.textContent = result[0].ok ? `${result[0].name}: app opened.` : `Could not reach ${result[0].name}.`; }
    catch (_) { message.textContent = 'Could not open the app.'; } finally { launch.disabled = false; } return;
  }
  const button = event.target.closest('button[data-action]'); if (!button) return;
  const buttons = [...document.querySelectorAll('button[data-action]')]; buttons.forEach(item => item.disabled = true);
  const action = button.dataset.action; message.textContent = `Sending ${action} command…`;
  try {
    const response = await fetch(`/api/${button.dataset.target}/${action}`, {method:'POST'}); if (!response.ok) throw Error();
    const results = await response.json(); const failed = results.filter(result => !result.ok).map(result => result.name);
    message.textContent = failed.length ? `Could not reach: ${failed.join(', ')}.` : `${results.length === 1 ? results[0].name : 'All TVs'}: ${action} command sent.`;
  } catch (_) { message.textContent = 'Controller unavailable. Check your connection and try again.'; }
  finally { buttons.forEach(item => item.disabled = false); }
});

load();
document.querySelector('#close-remote').addEventListener('click', () => { document.querySelector('#remote-panel').hidden = true; remoteIndex = null; });
if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js');
