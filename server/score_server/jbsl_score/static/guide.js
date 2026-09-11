'use strict';
const example = document.getElementById('example-grace');
const deadline = document.getElementById('example-deadline');
document.getElementById('deadline-example-form').addEventListener('submit', event => event.preventDefault());
example.addEventListener('input', () => {
  if (!example.value || !example.checkValidity()) { deadline.textContent = '0～604800の整数を入力してください'; return; }
  const total = 21 * 3600 + Number(example.value);
  const days = Math.floor(total / 86400);
  const parts = [Math.floor(total % 86400 / 3600), Math.floor(total % 3600 / 60), total % 60];
  deadline.textContent = '受付期限 ' + (days ? days + '日後 ' : '') + parts.map(v => String(v).padStart(2, '0')).join(':');
});
