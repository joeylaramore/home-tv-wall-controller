const grid = document.querySelector('#grid');
const setup = document.querySelector('#setup');
const discovered = document.querySelector('#discovered');
const message = document.querySelector('#message');
let tvs = [];
let found = [];

function render() {
  grid.replaceChildren();
  tvs.forEach((tv, index) => {
    const tile = document.createElement('article'); tile.className = 'tile';
    const heading = document.createElement('h2'); heading.textContent = tv.name;
    const actions = document.createElement('div'); actions.className = 'tile-buttons';
    for (const [label, action] of [['On', 'on'], ['Off', 'off']]) {
      const button = document.createElement('button'); button.textContent = label; button.className = action;
      button.dataset.target = index; button.dataset.action = action; actions.append(button);
    }
    tile.append(heading, actions); grid.append(tile);
  });
  setup.hidden = tvs.length > 0;
}

async function load() {
  try {
    const response = await fetch('/api/tvs', {cache:'no-store'}); tvs = await response.json(); render();
    message.textContent = tvs.length ? 'Ready. Controls are sent over your local network.' : 'Discover your Roku TVs to get started.';
  } catch (_) { message.textContent = 'Controller unavailable. Reconnect to your local network and reload.'; }
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
  const selected = [...discovered.querySelectorAll('input:checked')].map((box, position) => ({name: `TV ${position + 1}`, device_id: found[Number(box.dataset.index)]['device-id'], ip: ''}));
  if (!selected.length) return;
  const response = await fetch('/api/configure', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({tvs:selected})});
  if (!response.ok) { message.textContent = 'Could not save the TV wall.'; return; }
  tvs = selected; render(); message.textContent = `${tvs.length} TVs saved.`;
});

document.addEventListener('click', async event => {
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
if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js');
