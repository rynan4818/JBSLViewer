'use strict';
window.JBSLHelp = (() => {
  let returnFocus = null;
  const dialog = document.getElementById('help-dialog');
  const content = window.JBSL_HELP;
  function open(key, trigger) {
    const entry = content[key];
    if (!entry) return;
    const [title, topic, ...paragraphs] = entry;
    returnFocus = trigger || document.activeElement;
    document.getElementById('help-title').textContent = title;
    const body = document.getElementById('help-body');
    body.replaceChildren(...paragraphs.map(text => { const p = document.createElement('p'); p.textContent = text; return p; }));
    document.getElementById('help-guide').href = '/admin/guide/#' + topic;
    dialog.showModal();
  }
  function button(key) {
    const entry = content[key];
    if (!entry) throw new Error('Missing help: ' + key);
    const b = document.createElement('button');
    b.type = 'button'; b.className = 'help-button'; b.textContent = '?';
    b.setAttribute('aria-label', entry[0] + 'の説明');
    b.setAttribute('aria-haspopup', 'dialog');
    b.addEventListener('click', event => { event.preventDefault(); event.stopPropagation(); open(key, b); });
    return b;
  }
  function label(node, key) {
    // Keep help buttons outside <label>: opening help must never toggle a checkbox.
    const wrapper = document.createElement('div'); wrapper.className = 'field-help';
    wrapper.append(node, button(key)); return wrapper;
  }
  document.getElementById('close-help').addEventListener('click', () => dialog.close());
  dialog.addEventListener('close', () => { if (returnFocus?.isConnected) returnFocus.focus(); });
  dialog.addEventListener('click', event => {
    if (event.target !== dialog) return;
    const r = dialog.getBoundingClientRect();
    if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) dialog.close();
  });
  document.querySelectorAll('[data-help]').forEach(node => node.append(button(node.dataset.help)));
  return {button, label, open};
})();
