const grid = document.querySelector('#grid');
const message = document.querySelector('#message');
const fallback = ['Top left', 'Top right', 'Bottom left', 'Bottom right'];
function render(tvs) {
  grid.replaceChildren();
  tvs.forEach((tv, index) => {
    const tile = document.createElement('article');
    tile.className = 'tile';
    const heading = document.createElement('h2');
    heading.textContent = tv.name;
    const actions = document.createElement('div');
    actions.className = 'tile-buttons';
    for (const [label, action] of [['On', 'on'], ['Off', 'off']]) {
      const button = document.createElement('button');
      button.textContent = label;
      button.className = action;
      button.dataset.target = index;
      button.dataset.action = action;
      actions.append(button);
    }
    tile.append(heading, actions);
    grid.append(tile);
  });
}
render(fallback.map(name => ({name})));
fetch('/api/tvs', {cache:'no-store'}).then(r => {if(!r.ok) throw Error(); return r.json()}).then(tvs => {
  render(tvs);
  message.textContent = 'Ready. Controls are sent over your local network.';
}).catch(() => {message.textContent = 'Controller unavailable. Reconnect to your local network and reload.'});
document.addEventListener('click', async event => {
  const button = event.target.closest('button[data-action]');
  if (!button) return;
  const target = button.dataset.target, action = button.dataset.action;
  const buttons = [...document.querySelectorAll('button[data-action]')];
  buttons.forEach(b => b.disabled = true);
  message.textContent = `Sending ${action} command…`;
  try {
    const response = await fetch(`/api/${target}/${action}`, {method:'POST'});
    if (!response.ok) throw Error(`HTTP ${response.status}`);
    const results = await response.json();
    const failed = results.filter(r => !r.ok).map(r => r.name);
    message.textContent = failed.length ? `Could not reach: ${failed.join(', ')}. Check TV power and network settings.` : `${results.length === 4 ? 'All TVs' : results[0].name}: ${action} command sent.`;
  } catch (_) {message.textContent = 'Controller unavailable. Check your connection and try again.'}
  finally {buttons.forEach(b => b.disabled = false)}
});
if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js');
