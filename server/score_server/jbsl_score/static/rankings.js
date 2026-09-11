'use strict';
(() => {
  const league = document.getElementById('ranking-league');
  const map = document.getElementById('ranking-map');
  const list = document.getElementById('ranking-list');
  const status = document.getElementById('ranking-status');
  const error = document.getElementById('ranking-error');
  const replayNote = document.getElementById('ranking-replay-note');
  const endings = {clear:'クリア', fail:'失敗', quit:'中断', restart:'Restart', unknown:'不明', preflight_rejected:'開始前・開始時失敗'};
  let data = null;
  let generation = 0;

  function el(tag, text, className) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (className) node.className = className;
    return node;
  }
  function mapKey(chart) { return JSON.stringify([chart.hash, chart.characteristic, chart.difficulty]); }
  function count(value) { return value === null ? '—' : value.toLocaleString('ja-JP') + '回'; }
  function option(value, text) {
    const node = el('option', text);
    node.value = value;
    return node;
  }
  function replayActions(replay) {
    if (!replay.downloadUrl) return el('span', 'リプレイなし', 'muted');
    const actions = el('div', undefined, 'ranking-replay-actions');
    for (const [key, label, shortLabel] of [['downloadUrl', 'Replayをダウンロード', 'DL'], ['beatleaderUrl', 'BeatLeaderで再生', 'BeatLeader'], ['arcviewerUrl', 'ArcViewerで再生', 'ArcViewer']]) {
      const url = replay[key];
      const action = el(url ? 'a' : 'button', shortLabel, 'ranking-replay-action');
      action.setAttribute('aria-label', label);
      action.title = label;
      if (url) {
        action.href = url;
        if (key === 'downloadUrl') action.setAttribute('download', '');
        else { action.target = '_blank'; action.rel = 'noopener noreferrer'; }
      } else {
        action.type = 'button';
        action.disabled = true;
        action.title = label + '（HTTPS配信の設定が必要です）';
        action.setAttribute('aria-describedby', 'ranking-replay-note');
      }
      actions.append(action);
    }
    return actions;
  }
  function rankingTable(items, title) {
    const wrap = el('div', undefined, 'table-wrap');
    const table = el('table');
    table.append(el('caption', title + 'のランキング', 'sr-only'));
    const head = el('thead'), headings = el('tr');
    for (const text of ['順位', 'ユーザー', '最高スコア', '残回数', '提出日時 / 結果', 'リプレイ']) {
      const th = el('th', text);
      th.scope = 'col';
      headings.append(th);
    }
    head.append(headings);
    const body = el('tbody');
    for (const item of items) {
      const rank = el('strong', item.rank.toLocaleString('ja-JP'), 'ranking-rank' + (item.rank <= 3 ? ' highlight' : ''));
      const user = el('div');
      user.append(el('strong', item.displayName || item.sid, 'ranking-user-name'), el('div', item.sid, 'muted'));
      const score = el('div', undefined, 'ranking-score');
      score.append(el('strong', item.modifiedScore === null ? '—' : item.modifiedScore.toLocaleString('ja-JP')),
        el('div', item.accuracyPercent === null ? '精度 —' : item.accuracyPercent.toFixed(2) + '%', 'muted'));
      const received = el('div');
      received.append(el('div', new Date(item.receivedAt).toLocaleString('ja-JP')),
        el('span', endings[item.endType] || item.endType, 'badge'));
      const row = el('tr');
      for (const value of [rank, user, score, el('span', count(item.remainingAttempts), 'ranking-attempts'), received, replayActions(item.replay)]) {
        const cell = el('td');
        cell.append(value);
        row.append(cell);
      }
      body.append(row);
    }
    table.append(head, body);
    wrap.append(table);
    return wrap;
  }
  function render() {
    list.replaceChildren();
    replayNote.hidden = !data.items.some(item => item.replay.downloadUrl && !item.replay.beatleaderUrl);
    const charts = data.maps.filter(chart => !map.value || mapKey(chart) === map.value);
    if (!charts.length) {
      const box = el('section', undefined, 'panel');
      box.append(el('p', data.leagues.length ? 'このリーグには譜面の記録がありません。' : 'リーグの記録はまだありません。', 'empty'));
      list.append(box);
      return;
    }
    const grouped = new Map(data.maps.map(chart => [mapKey(chart), []]));
    for (const item of data.items) grouped.get(mapKey(item.map)).push(item);
    for (const chart of charts) {
      const items = grouped.get(mapKey(chart));
      const box = el('section', undefined, 'panel ranking-panel');
      const heading = el('div', undefined, 'ranking-heading'), title = el('div', undefined, 'ranking-title');
      const metadata = el('p', undefined, 'ranking-metadata');
      metadata.append(el('span', '回数上限: ' + count(chart.attemptLimit)),
        el('span', '曲時間: ' + (chart.songDurationSeconds === null ? '—' : chart.songDurationSeconds.toLocaleString('ja-JP', {maximumFractionDigits:3}) + '秒')));
      title.append(el('h2', chart.title), metadata);
      heading.append(title, el('span', items.length.toLocaleString('ja-JP') + '名', 'badge blue'));
      box.append(heading, el('p', chart.characteristic + ' / ' + chart.difficulty + ' / ' + chart.hash, 'muted ranking-map-key'));
      box.append(items.length ? rankingTable(items, chart.title) : el('p', 'この譜面にはランキング対象のスコアがまだありません。', 'empty'));
      list.append(box);
    }
  }
  async function load(leagueId = null) {
    const current = ++generation;
    const selectedMap = data && data.leagueId === leagueId ? map.value : '';
    map.disabled = true;
    list.replaceChildren();
    list.setAttribute('aria-busy', 'true');
    error.hidden = true;
    error.textContent = '';
    replayNote.hidden = true;
    status.textContent = 'ランキングを読み込んでいます…';
    try {
      const query = leagueId === null ? '' : '?' + new URLSearchParams({leagueId});
      const response = await fetch('/admin/api/public/rankings' + query, {credentials:'omit', cache:'no-store'});
      if (!response.ok) throw new Error('HTTP ' + response.status);
      const result = await response.json();
      if (current !== generation) return;
      data = result;
      league.replaceChildren(...data.leagues.map(entry => option(entry.leagueId, entry.title + ' / League ' + entry.leagueId)));
      league.disabled = !data.leagues.length;
      if (data.leagueId !== null) league.value = String(data.leagueId);
      map.replaceChildren(option('', 'すべての譜面'), ...data.maps.map(chart => option(mapKey(chart), chart.title + ' / ' + chart.characteristic + ' / ' + chart.difficulty + ' / ' + chart.hash.slice(0, 10))));
      if (data.maps.some(chart => mapKey(chart) === selectedMap)) map.value = selectedMap;
      map.disabled = !data.maps.length;
      render();
      status.textContent = '更新 ' + new Date().toLocaleString('ja-JP');
    } catch (_) {
      if (current !== generation) return;
      list.replaceChildren();
      status.textContent = '';
      error.textContent = 'ランキングを取得できませんでした。時間をおいてページを再読み込みしてください。';
      error.hidden = false;
    } finally {
      if (current === generation) list.setAttribute('aria-busy', 'false');
    }
  }
  league.addEventListener('change', () => load(Number(league.value)));
  map.addEventListener('change', render);
  load();
})();
