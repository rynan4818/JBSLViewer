'use strict';
const $ = id => document.getElementById(id);
const help = window.JBSLHelp;
const helpLabels = {
  '予約日時 / Challenge':'challenge_id', 'ユーザー / League':'sid', 'ユーザー':'sid', 'ユーザー SID':'sid', 'SID':'sid', 'League':'league', 'League ID':'league',
  '譜面':'map', '状態':'status', '回数':'attempts', '提出結果':'result', '使用済み':'used', '返却':'refunded', '残回数 / 上限':'remaining', '残回数':'remaining',
  '時刻':'timestamp', 'イベント':'event', '実行者':'actor', '所要時間':'elapsed_ms', '詳細':'log_detail', '取得日時':'cache', '取得エラー':'cache',
  'Challenge数':'total_challenges', '提出数':'submitted', '操作':'result', 'チャレンジ操作':'challenge_operations', 'SID または表示名':'search',
  'サーバの状態':'overview', '運営操作':'operations', '最近のChallenge':'challenges', '最近の操作・受信ログ':'audit',
  'ユーザーのChallenge・提出':'challenges', '操作・提出・拒否の監査記録':'audit', '受付と期限':'deadlines', 'スコア対象外の回数返却':'refunds'
};
const state = {page:'overview', csrf:'', policy:null, selected:null, challengeAction:null, user:null, userReturn:null, rankingLeague:null, rankingMap:'', generation:0};
const titles = {overview:'概要', rankings:'ランキング', challenges:'Challenge・提出', users:'ユーザー', audit:'操作・受信ログ', settings:'サーバ設定'};
const statuses = {reserved:'予約済み', started:'プレイ中', submitted:'提出済み', abandoned:'終了（未提出）'};
const endings = {clear:'クリア', fail:'失敗', quit:'中断', restart:'Restart', unknown:'不明', preflight_rejected:'開始前・開始時失敗'};
const conditions = {
  preflight_unstarted:['開始前の失敗','プレイ回数0、かつ開始通知なし'],
  preflight_started:['開始時の失敗','Gameplayを観測、または開始通知あり'],
  quit:['中断 / Quit','途中終了のスコア対象外提出'],
  restart:['Restart','元Challengeの終了結果'],
  unknown:['終了理由不明','unknown のスコア対象外提出'],
  submission_disabled:['スコア提出無効','clear / fail でも標準提出が無効'],
  replay_unavailable:['Replay生成失敗','clear / fail でReplayを用意できない'],
  abandoned:['結果未着・タイムアウト','受付期限または運用タイムアウトで未提出確定']
};
function el(tag, text, className) { const n=document.createElement(tag); if(text!==undefined)n.textContent=text; if(className)n.className=className; return n; }
function button(text, action, className) {const n=el('button',text,className);n.type='button';n.addEventListener('click',action);return n;}
function fmt(v){return v===null||v===undefined?'—':String(v);}
function date(v){return v?new Date(v).toLocaleString('ja-JP',{hour12:false}):'—';}
function badge(text, color=''){return el('span',text,'badge '+color);}
function notice(text, error=false){$('notice').textContent=text;$('notice').className=error?'error':'';$('notice').hidden=false;}
async function api(path, options={}){
  const response=await fetch('/admin/api'+path,{credentials:'same-origin',...options,headers:{'Content-Type':'application/json','X-JBSL-Admin':'1','X-CSRF-Token':state.csrf,...options.headers}});
  if(response.status===204)return null;
  const body=await response.json();
  if(!response.ok){if(response.status===401&&path!='/login')showLogin();const e=body.error||{};throw new Error((e.message||'通信に失敗しました。')+' ['+(e.code||response.status)+']'+(e.requestId?' / '+e.requestId:''));}
  return body;
}
function report(error){notice(error.message,true);}
function showLogin(){document.querySelectorAll('dialog[open]').forEach(d=>d.close());$('app-view').hidden=true;$('login-view').hidden=false;state.csrf='';state.generation++;}
function showApp(user){state.csrf=user.csrfToken;$('operator').textContent=user.username;$('login-view').hidden=true;$('app-view').hidden=false;loadPage().catch(report);}
function explained(text,key){const n=el('span',text,'inline-help');if(key)n.append(help.button(key));return n;}
function panel(title){const n=el('section',undefined,'panel');if(title){const h=el('h2',title);const key=helpLabels[title];if(key)h.append(help.button(key));n.append(h);}return n;}
function table(headers,rows){
  const wrap=el('div',undefined,'table-wrap');if(!rows.length){wrap.append(el('div','該当する記録はありません。','empty'));return wrap;}
  const t=el('table'),head=el('thead'),tr=el('tr');headers.forEach(h=>{const th=el('th');th.scope='col';th.append(explained(h,helpLabels[h]));tr.append(th);});head.append(tr);t.append(head);
  const body=el('tbody');rows.forEach(row=>{const tr=el('tr');row.forEach(value=>{const td=el('td');td.append(value instanceof Node?value:document.createTextNode(fmt(value)));tr.append(td);});body.append(tr);});t.append(body);wrap.append(t);return wrap;
}
function inputLabel(text,id,type='text',value=''){const l=el('label',text);const i=el('input');i.id=id;i.type=type;i.value=value;l.append(i);return helpLabels[text]?help.label(l,helpLabels[text]):l;}
function mapText(m){return m.hash.slice(0,10)+'… / '+m.characteristic+' / '+m.difficulty;}
function resultCell(r){const n=el('div');if(r.submissionId){n.append(badge(r.canceled?'取消済み':r.validForRanking?'ランキング対象':'対象外',r.canceled?'red':r.validForRanking?'green':''),el('div',endings[r.endType]||r.endType),button('詳細・取消・復元',()=>openSubmission(r.submissionId).catch(report),'small-button'));}else n.append(el('span','結果未着','muted'));return n;}
function challengeStatus(r){return r.abandonedReason==='admin_force_ended'?'強制終了':statuses[r.status];}
function challengeActions(r){
  const n=el('div',undefined,'challenge-actions');
  if(['reserved','started'].includes(r.status))n.append(button('強制終了',()=>openChallengeAction(r,'force-end'),'small-button danger'));
  else if(!r.attemptRefunded)n.append(button('1回返却',()=>openChallengeAction(r,'refund'),'small-button'));
  if(r.attemptRefunded)n.append(badge('返却済み','green'));
  return n;
}
function challengeTable(items){return table(['予約日時 / Challenge','ユーザー / League','譜面','状態','回数','提出結果','チャレンジ操作'],items.map(r=>{
  const id=el('div');id.append(el('div',date(r.reservedAt)),el('div',r.challengeId,'muted'));
  const user=el('div');user.append(button(r.sid,()=>{state.user=r.sid;state.userReturn=null;navigate('users');},'small-button challenge-user'),el('div','League '+r.leagueId,'muted'));
  const st=el('div');st.append(badge(challengeStatus(r),r.abandonedReason==='admin_force_ended'?'red':r.status==='started'?'blue':''),el('div','受付: '+date(r.resultAcceptUntil),'muted'));
  const attempt=el('div');attempt.append(el('div','#'+r.attemptNumber));if(r.attemptRefunded)attempt.append(el('span','返却済み','challenge-refunded'));
  return [id,user,mapText(r.map),st,attempt,resultCell(r),challengeActions(r)];
}));}
function auditTable(items){
  const wrap=table(['時刻','イベント','実行者','所要時間','詳細'],items.map(r=>[date(r.occurredAt),r.event,r.actor,typeof r.elapsedMs==='number'&&Number.isFinite(r.elapsedMs)?r.elapsedMs.toFixed(1)+' ms':'—',JSON.stringify(r.details)+(r.requestId?' / '+r.requestId:'')]));
  wrap.classList.add('audit-table');return wrap;
}
async function overview(target){
  const [s,ch,logs]=await Promise.all([api('/state'),api('/challenges?limit=8'),api('/audit?limit=6')]);
  const cards=el('div',undefined,'cards');[['進行中',s.counts.reserved+s.counts.started,'active'],['提出済み',s.counts.submitted,'submitted'],['ランキング対象',s.counts.ranked,'ranked'],['登録ユーザー',s.counts.users,'registered']].forEach(([label,v,key])=>{const n=el('section',undefined,'stat'),caption=el('div',undefined,'caption');caption.append(explained(label,key));n.append(caption,el('div',v.toLocaleString(),'value'));cards.append(n);});target.append(cards);
  const columns=el('div',undefined,'two-col'),health=panel('サーバの状態'),links=panel('運営操作');
  [['ディスク空き',s.diskFreeMb.toLocaleString()+' MB','disk'],['データベース',s.databaseMb+' MB','database'],['最終バックアップ',date(s.maintenance.last_backup),'backup'],['Steam認証',s.authentication.steamConfigured?'設定済み':'APIキー未設定','steam'],['Oculus認証',s.authentication.oculusEnabled?'有効':'無効','oculus']].forEach(([k,v,key])=>{const n=el('div',undefined,'health-line');n.append(explained(k,key),el('strong',v));health.append(n);});
  if(s.maintenance.last_backup_error)health.append(el('p','バックアップ失敗: '+s.maintenance.last_backup_error,'error'));
  links.append(el('p','予約・提出の受付状態、期限、返却条件はサーバ設定で変更できます。','section-note'),button('サーバ設定を開く',()=>navigate('settings')));
  const back=button('バックアップを作成',async()=>{back.disabled=true;try{const r=await api('/backups',{method:'POST',body:'{}'});notice('バックアップを検証して保存しました: '+r.file);}catch(e){report(e);}finally{back.disabled=false;}});links.append(el('p','Replay・監査履歴も含めて保存します。','muted'),back,help.button('backup'));
  const cacheHeading=el('h3');cacheHeading.append(explained('JBSL-WEBキャッシュ','cache'));links.append(cacheHeading);links.append(table(['League','取得日時','取得エラー'],s.cache.map(c=>[c.leagueId,date(c.fetchedAt),c.lastError])));columns.append(health,links);target.append(columns);
  const recent=panel('最近のChallenge');recent.append(challengeTable(ch.items));target.append(recent);
  const log=panel('最近の操作・受信ログ');log.append(auditTable(logs.items));target.append(log);
}
function mapKey(m){return JSON.stringify([m.hash,m.characteristic,m.difficulty]);}
async function rankingsPage(target){
  const generation=state.generation;
  const data=await api('/rankings'+(state.rankingLeague===null?'':'?leagueId='+state.rankingLeague));
  if(generation!==state.generation)return;
  state.rankingLeague=data.leagueId;
  if(!data.maps.some(m=>mapKey(m)===state.rankingMap))state.rankingMap='';
  const filters=panel(),toolbar=el('div',undefined,'toolbar ranking-filters');
  const leagueLabel=el('label','リーグ'),league=el('select');league.id='ranking-league';league.setAttribute('aria-label','リーグ');leagueLabel.append(league);
  for(const entry of data.leagues){const o=el('option',entry.title+' / League '+entry.leagueId);o.value=entry.leagueId;league.append(o);}
  league.disabled=!data.leagues.length;
  if(data.leagueId!==null)league.value=String(data.leagueId);
  const mapLabel=el('label','譜面'),map=el('select');map.id='ranking-map';map.setAttribute('aria-label','譜面');mapLabel.append(map);
  const all=el('option','すべての譜面');all.value='';map.append(all);
  for(const m of data.maps){const o=el('option',m.title+' / '+m.characteristic+' / '+m.difficulty+' / '+m.hash.slice(0,10));o.value=mapKey(m);map.append(o);}
  map.value=state.rankingMap;map.disabled=!data.maps.length;
  toolbar.append(leagueLabel,mapLabel);filters.append(toolbar,el('p','各ユーザーの有効な最高スコアを、譜面ごとに高い順で表示します。同点は同順位（1位・1位・3位）です。','section-note'),el('p','取消済み・ランキング対象外の提出は集計から除外します。最新の提出・操作結果は「更新」で取得できます。','muted'));
  target.append(filters);
  const list=el('div');list.id='ranking-list';target.append(list);
  const grouped=new Map(data.maps.map(m=>[mapKey(m),[]]));
  for(const r of data.items)grouped.get(mapKey(r.map)).push(r);
  function render(){
    list.replaceChildren();
    const maps=data.maps.filter(m=>!state.rankingMap||mapKey(m)===state.rankingMap);
    if(!maps.length){const empty=panel();empty.append(el('p',data.leagues.length?'このリーグには譜面の記録がありません。':'リーグの記録はまだありません。Viewerの状態取得・予約などでリーグ情報を取得すると表示されます。','empty'));list.append(empty);return;}
    for(const m of maps){
      const items=grouped.get(mapKey(m)),box=panel();box.classList.add('ranking-panel');
      const heading=el('div',undefined,'ranking-heading'),title=el('div',undefined,'ranking-title');
      const metadata=el('p',undefined,'ranking-metadata');
      metadata.append(el('span','回数上限: '+(m.attemptLimit===null?'—':m.attemptLimit.toLocaleString()+'回')),el('span','曲時間: '+(m.songDurationSeconds===null?'—':m.songDurationSeconds.toLocaleString('ja-JP',{maximumFractionDigits:3})+'秒')));
      title.append(el('h2',m.title),metadata);heading.append(title,badge(items.length.toLocaleString()+'名','blue'));
      box.append(heading,el('p',m.characteristic+' / '+m.difficulty+' / '+m.hash,'muted ranking-map-key'));
      if(!items.length)box.append(el('p','この譜面にはランキング対象のスコアがまだありません。','empty'));
      else box.append(table(['順位','ユーザー','最高スコア','残回数','提出日時 / 結果','操作'],items.map(r=>{
        const rank=el('strong',r.rank.toLocaleString(),'ranking-rank'+(r.rank<=3?' highlight':''));
        const user=el('div');user.append(el('strong',r.displayName||r.sid,'ranking-user-name'),el('div',r.sid,'muted'));
        const score=el('div',undefined,'ranking-score');score.append(el('strong',r.modifiedScore.toLocaleString()),el('div',r.accuracyPercent===null?'精度 —':r.accuracyPercent.toFixed(2)+'%','muted'));
        const received=el('div');received.append(el('div',date(r.receivedAt)),badge(endings[r.endType]||r.endType));
        const actions=el('div',undefined,'ranking-actions');
        actions.append(button('ユーザー・提出履歴',()=>{state.user=r.sid;state.userReturn='rankings';navigate('users');},'small-button'),button('詳細・取消・復元',()=>openSubmission(r.submissionId).catch(report),'small-button'),challengeActions({...r,status:'submitted'}));
        const remaining=el('span',r.remainingAttempts===null?'—':r.remainingAttempts.toLocaleString()+'回','ranking-attempts');
        return [rank,user,score,remaining,received,actions];
      })));
      list.append(box);
    }
  }
  league.addEventListener('change',()=>{state.rankingLeague=Number(league.value);state.rankingMap='';loadPage().catch(report);});
  map.addEventListener('change',()=>{state.rankingMap=map.value;render();});
  render();
}
async function challengePage(target, sid=null){
  const box=panel(sid?'ユーザーのChallenge・提出':null),toolbar=el('form',undefined,'toolbar');
  toolbar.append(inputLabel('ユーザー SID','filter-sid','text',sid||''),inputLabel('League ID','filter-league','number'));
  const l=el('label','状態'),select=el('select');select.id='filter-status';[['','すべて'],...Object.entries(statuses)].forEach(([v,t])=>{const o=el('option',t);o.value=v;select.append(o);});l.append(select);toolbar.append(help.label(l,'status'));const search=el('button','絞り込み','primary');search.type='submit';toolbar.append(search);box.append(toolbar);
  const list=el('div');box.append(list);target.append(box);
  let cursor=null;
  async function fetchList(append=false){const query=new URLSearchParams({limit:'50'});if($('filter-sid').value.trim())query.set('sid',$('filter-sid').value.trim());if($('filter-league').value)query.set('leagueId',$('filter-league').value);if(select.value)query.set('status',select.value);if(append&&cursor)query.set('before',cursor);const r=await api('/challenges?'+query);if(!append)list.replaceChildren();list.querySelector('.pagination')?.remove();list.append(challengeTable(r.items));cursor=r.nextCursor;if(cursor){const pg=el('div',undefined,'pagination');pg.append(button('次の50件を表示',()=>fetchList(true).catch(report)));list.append(pg);}}
  toolbar.addEventListener('submit',e=>{e.preventDefault();fetchList().catch(report);});await fetchList();
}
async function usersPage(target){
  if(state.user&&state.userReturn==='rankings')target.append(button('ランキングへ戻る',()=>navigate('rankings'),'ranking-back'));
  if(state.user){const sid=state.user;target.append(button('ユーザー一覧へ戻る',()=>{state.user=null;loadPage().catch(report);}));const b=panel('SID '+sid);b.append(el('p','上限と残回数は最後に検証したJBSL-WEBキャッシュを基準に表示します。','muted'));const r=await api('/users/'+encodeURIComponent(sid)+'/attempts');b.append(table(['League','譜面','使用済み','返却','残回数 / 上限'],r.items.map(x=>[x.leagueId,mapText(x.map),x.usedAttempts,x.refundedAttempts,fmt(x.remainingAttempts)+' / '+fmt(x.attemptLimit)])));target.append(b);await challengePage(target,sid);return;}
  const box=panel(),form=el('form',undefined,'toolbar');form.append(inputLabel('SID または表示名','user-search'));const b=el('button','検索','primary');b.type='submit';form.append(b);box.append(form);const list=el('div');box.append(list);target.append(box);let after='';
  async function get(append=false){const q=new URLSearchParams({q:$('user-search').value,limit:'50'});if(append)q.set('after',after);const r=await api('/users?'+q);if(!append)list.replaceChildren();list.querySelector('.pagination')?.remove();list.append(table(['ユーザー','SID','Challenge数','提出数','操作'],r.items.map(x=>[x.displayName,x.sid,x.challenges,x.submissions,button('提出状況を確認',()=>{state.user=x.sid;loadPage().catch(report);},'small-button')])));after=r.nextCursor;if(after){const p=el('div',undefined,'pagination');p.append(button('次の50件を表示',()=>get(true).catch(report)));list.append(p);}}
  form.addEventListener('submit',e=>{e.preventDefault();get().catch(report);});await get();
}
async function auditPage(target){const box=panel('操作・提出・拒否の監査記録');box.append(el('p','強制終了、回数返却、設定変更、スコア取消・復元、提出エラーを記録します。時刻はこのブラウザのタイムゾーンで表示します。','section-note'));const list=el('div');box.append(list);target.append(box);let before=null;async function get(){const r=await api('/audit?limit=50'+(before?'&before='+before:''));list.querySelector('.pagination')?.remove();list.append(auditTable(r.items));before=r.nextCursor;if(before){const p=el('div',undefined,'pagination');p.append(button('次の50件を表示',()=>get().catch(report)));list.append(p);}}await get();}
const fields={
  result_grace_seconds:['終了後の提出猶予（秒）',0,604800,'実効終了日時に加算。期限ちょうどは受理します。'],
  challenge_timeout_seconds:['予約からのタイムアウト（秒）',0,604800,'0で無効。曲時間より十分長く設定してください。'],
  max_active_per_user:['ユーザーごとの同時Challenge上限',0,100,'0で制限なし。未提出の予約とプレイ中を数えます。'],
  cache_fresh_seconds:['通常キャッシュ（秒）',0,60,'statusで再利用する期間。新規予約は毎回最新情報を取得。'],
  cache_stale_seconds:['障害時の参考表示（秒）',0,300,'通常キャッシュ以上。古い情報で新規予約は許可しません。'],
  session_seconds:['Viewerセッション有効期間（秒）',300,86400,'新しく発行するセッションに適用。'],
  max_sessions_per_user:['同時セッション数',1,20,'再認証時に古いセッションから失効。'],
  auth_per_minute:['認証要求 / IP / 分',1,600,'Steam・Oculus ticketの検証回数上限。'],
  status_per_minute:['状態取得 / ユーザー / 分',1,600,'statusとセッション確認に適用。'],
  reserve_per_minute:['予約要求 / ユーザー / 分',1,600,'再送も含む要求数。残Challenge回数とは別です。'],
  result_per_minute:['提出要求 / ユーザー / 分',1,600,'結果と開始通知の各要求に適用。'],
  min_free_disk_mb:['ディスク空き下限（MB）',64,1048576,'下回ると予約・新規結果保存を一時停止。'],
  backup_interval_hours:['自動バックアップ間隔（時間）',0,168,'0で自動作成停止。手動作成は可能。'],
  backup_keep_count:['バックアップ保持数',1,100,'検証済みバックアップ作成後に古い世代を削除。']
};
async function settingsPage(target){
  const data=await api('/settings');state.policy=data;
  const form=el('form');form.append(el('p','スコア管理サーバが適用する運用設定を、対象別にまとめています。変更後は、画面下部の「設定を保存」でまとめて保存します。','section-note'));
  function category(title,note){const section=panel(title);section.classList.add('settings-category');section.append(el('p',note,'section-note'));form.append(section);return section;}
  function group(parent,title){const section=el('fieldset',undefined,'settings-group'),legend=el('legend',title);if(helpLabels[title])legend.append(help.button(helpLabels[title]));section.append(legend);parent.append(section);return section;}
  function numberField(key){const [label,min,max,note]=fields[key],l=inputLabel(label,'policy-'+key,'number',data.policy[key]),i=l.querySelector('input');i.required=true;i.min=min;i.max=max;i.step=1;l.append(el('small',note));return help.label(l,key);}
  function numberGrid(parent,keys){const grid=el('div',undefined,'settings-grid');keys.forEach(key=>grid.append(numberField(key)));parent.append(grid);return grid;}

  const viewer=category('JBSLViewer（mod）向け','JBSLViewer（mod）からスコア管理サーバへの接続に適用します。プレイヤーの認証セッションとAPI要求数の上限です。');
  numberGrid(group(viewer,'認証・セッション'),['session_seconds','max_sessions_per_user']);
  numberGrid(group(viewer,'API要求数の制限'),['auth_per_minute','status_per_minute','reserve_per_minute','result_per_minute']);

  const web=category('jbsl-web 連携','スコア管理サーバが jbsl-web から取得する大会・参加資格・譜面情報のキャッシュです。Viewerの状態表示にも影響します。');
  numberGrid(group(web,'上流情報のキャッシュ'),['cache_fresh_seconds','cache_stale_seconds']);

  const common=category('共通（大会運用）','Viewerの予約・提出受付と、jbsl-web に渡す回数情報に関わる共通の大会運用ルールです。判定・管理はスコア管理サーバで行います。');
  common.append(el('p','猶予時間・タイムアウト・返却条件は、新しい予約から適用されます。予約済みChallengeには予約時の設定を維持します。','section-note'));
  const top=group(common,'受付と期限');
  const enable=el('label',undefined,'check-label'),check=el('input');check.id='policy-reservations_enabled';check.type='checkbox';check.checked=data.policy.reservations_enabled;enable.append(check,el('span','新しいChallengeの予約を受け付ける'));top.append(help.label(enable,'reservations_enabled'));
  const grid=el('div',undefined,'settings-grid');
  const l=el('label','新規Challengeの開始締切'),select=el('select');select.id='policy-start_deadline_policy';[['effective_end','実効終了日時まで（標準）'],['end_minus_duration','実効終了日時 − 上流の曲時間']].forEach(([v,t])=>{const o=el('option',t);o.value=v;o.selected=data.policy.start_deadline_policy===v;select.append(o);});l.append(select,el('small','曲時間方式では、上流の曲時間が不明な譜面の新規予約を拒否します。Viewer自身の曲時間判定も維持されます。'));grid.append(help.label(l,'start_deadline_policy'));
  ['result_grace_seconds','challenge_timeout_seconds','max_active_per_user'].forEach(key=>grid.append(numberField(key)));top.append(grid);
  const refunds=group(common,'スコア対象外の回数返却');refunds.append(el('p','チェックした条件に一致する受理済み結果だけ、1回を返却します。既定はすべて返却なし。申告された終了理由に基づくため、参加者による繰り返し利用も考慮して設定してください。','section-note'));
  const rg=el('div',undefined,'refund-grid');Object.entries(conditions).forEach(([key,[label,note]])=>{const l=el('label',undefined,'check-label'),i=el('input');i.type='checkbox';i.id='refund-'+key;i.checked=data.policy.refund_conditions.includes(key);const text=el('span',label);text.append(el('br'),el('small',note));l.append(i,text);rg.append(help.label(l,key));});refunds.append(rg);

  const server=category('スコア管理サーバ固有','スコア管理サーバの保存容量とバックアップを管理します。');
  numberGrid(group(server,'ディスク容量'),['min_free_disk_mb']);
  numberGrid(group(server,'バックアップ'),['backup_interval_hours','backup_keep_count']);
  const actions=el('div',undefined,'form-actions'),save=el('button','設定を保存','primary');save.type='submit';actions.append(save,el('span','設定リビジョン '+data.revision,'muted'),help.button('revision'));form.append(actions);
  form.addEventListener('submit',async e=>{e.preventDefault();save.disabled=true;try{const policy={...data.policy};Object.keys(fields).forEach(k=>policy[k]=Number($('policy-'+k).value));policy.reservations_enabled=check.checked;policy.start_deadline_policy=select.value;policy.refund_conditions=Object.keys(conditions).filter(k=>$('refund-'+k).checked);const r=await api('/settings',{method:'PUT',body:JSON.stringify({revision:data.revision,policy})});notice('設定を保存しました。リビジョン '+r.revision);await loadPage();}catch(error){report(error);}finally{save.disabled=false;}});target.append(form);
}
function openChallengeAction(record,action){
  state.challengeAction={record,action};
  const ending=action==='force-end';
  $('challenge-action-title').textContent=ending?'チャレンジを強制終了':'チャレンジの1回を返却';
  const dl=el('dl',undefined,'details-grid');
  [['ユーザー SID',record.sid],['League',record.leagueId],['譜面',record.map.hash+' / '+record.map.characteristic+' / '+record.map.difficulty],['Challenge ID',record.challengeId],['状態',challengeStatus(record)]].forEach(([k,v])=>dl.append(el('dt',k),el('dd',fmt(v))));
  $('challenge-action-detail').replaceChildren(dl);
  $('challenge-action-note').textContent=ending?'このチャレンジの開始通知・結果提出の受付を終了します。返却を選ばない場合、消費した回数は維持します。':'このチャレンジで消費した1回を返却します。提出済みのスコアとランキングの採否は維持します。';
  $('challenge-refund-option').hidden=!ending;
  $('challenge-refund').checked=false;
  $('challenge-action-reason').value='';
  $('challenge-action-reason').setCustomValidity('');
  $('challenge-action-error').textContent='';
  $('challenge-action-submit').textContent=ending?'強制終了する':'1回返却する';
  $('challenge-action-submit').className=ending?'danger':'primary';
  $('challenge-action-dialog').showModal();
}
$('challenge-refund').addEventListener('change',()=>{$('challenge-action-submit').textContent=$('challenge-refund').checked?'強制終了して1回返却する':'強制終了する';});
$('challenge-action-reason').addEventListener('input',e=>e.target.setCustomValidity(''));
$('close-challenge-action').addEventListener('click',()=>$('challenge-action-dialog').close());
$('challenge-action-dialog').addEventListener('cancel',e=>{if($('challenge-action-submit').disabled)e.preventDefault();});
$('challenge-action-form').addEventListener('submit',async e=>{
  e.preventDefault();
  const reason=$('challenge-action-reason'),b=$('challenge-action-submit'),close=$('close-challenge-action');
  if(!reason.value.trim()){reason.setCustomValidity('操作理由を入力してください。');reason.reportValidity();return;}
  const {record,action}=state.challengeAction,body={reason:reason.value.trim()};
  if(action==='force-end')body.refundAttempt=$('challenge-refund').checked;
  b.disabled=close.disabled=true;$('challenge-action-error').textContent='';
  try{
    const r=await api('/challenges/'+encodeURIComponent(record.challengeId)+'/'+action,{method:'POST',body:JSON.stringify(body)});
    $('challenge-action-dialog').close();
    let message=action==='refund'?'このチャレンジの1回は返却済みです。':'チャレンジは強制終了済みです。'+(r.attemptRefunded?'回数は返却済みです。':'消費回数は維持しています。');
    if(action==='force-end'&&body.refundAttempt&&!r.attemptRefunded)message+='先に強制終了されていたため、返却する場合は「1回返却」を実行してください。';
    notice(message);
    await loadPage().catch(error=>notice(message+' 表示の更新に失敗しました。「更新」で再取得してください。 '+error.message,true));
  }catch(error){if($('challenge-action-dialog').open)$('challenge-action-error').textContent=error.message;else report(error);}
  finally{b.disabled=close.disabled=false;}
});
async function openReplay(id,viewer,trigger,feedback){
  trigger.disabled=true;feedback.replaceChildren();
  let tab=null;
  try{
    tab=window.open('about:blank','_blank');
    if(tab){
      tab.opener=null;
      const policy=tab.document.createElement('meta');policy.name='referrer';policy.content='no-referrer';tab.document.head.append(policy);
      tab.document.title='リプレイを開いています';tab.document.body.textContent='リプレイの再生ページを開いています…';
    }
    const result=await api('/submissions/'+encodeURIComponent(id)+'/replay-viewer',{method:'POST',body:JSON.stringify({viewer})});
    const link=el('a','再生ページを開く');link.href=result.viewerUrl;link.target='_blank';link.rel='noopener noreferrer';link.referrerPolicy='no-referrer';
    if(tab&&!tab.closed){
      const navigation=link.cloneNode(true);navigation.target='_self';tab.document.body.replaceChildren(navigation);navigation.click();
      feedback.textContent='別タブで開きました。再読み込み用URLの有効期限: '+date(result.expiresAt);
    }else{
      feedback.append('別タブを開けませんでした。',link,'（有効期限: '+date(result.expiresAt)+'）');
    }
  }catch(error){
    if(tab&&!tab.closed)tab.close();
    feedback.textContent=error.message;
  }finally{trigger.disabled=false;}
}
function replayActions(r){
  const section=el('section',undefined,'replay-section'),actions=el('div',undefined,'replay-actions');
  const download=el('a','Replayをダウンロード');download.href='/admin/api/submissions/'+encodeURIComponent(r.submissionId)+'/replay';
  actions.append(download,help.button('replay'));
  const feedback=el('p',undefined,'muted replay-feedback');feedback.setAttribute('role','status');
  for(const [viewer,label] of [['beatleader','BeatLeaderで再生'],['arcviewer','ArcViewerで再生']]){
    const b=button(label,()=>openReplay(r.submissionId,viewer,b,feedback));b.disabled=!r.replayViewerAvailable;
    if(b.disabled)b.title='外部再生にはAPI公開URLのHTTPS設定が必要です。';
    actions.append(b);
  }
  actions.append(help.button('replay_viewer'));section.append(actions);
  if(!r.replayViewerAvailable)section.append(el('p','外部再生にはAPI公開URLのHTTPS設定が必要です。','muted'));
  section.append(feedback);return section;
}
async function openSubmission(id){
  const r=await api('/submissions/'+encodeURIComponent(id));state.selected=r;const target=$('submission-detail');target.replaceChildren();
  const dl=el('dl',undefined,'details-grid');[['提出ID',r.submissionId,'submission_id'],['ユーザー',r.sid,'sid'],['League',r.leagueId,'league'],['終了理由',endings[r.endType],'end_type'],['スコア',r.modifiedScore,'score'],['ランキング',r.effectiveForRanking?'対象':r.canceled?'取消済み':'対象外: '+r.invalidReason,'moderation'],['回数返却',r.attemptRefunded?'返却済み: '+r.refundReason:'なし','refunded'],['受信日時',date(r.receivedAt),'timestamp'],['操作バージョン',r.moderationVersion,'moderation_version'],['前回操作理由',r.moderationReason,'moderation_reason']].forEach(([k,v,key])=>{const term=el('dt');term.append(explained(k,key));dl.append(term,el('dd',fmt(v)));});target.append(dl);
  if(r.replaySha256)target.append(replayActions(r));
  const details=el('details');details.append(el('summary','提出metadata・予約時設定'),el('pre',JSON.stringify({metadata:r.metadata,reservationPolicy:r.reservationPolicy,policyRevision:r.policyRevision},null,2)));target.append(details,help.button('metadata'));
  $('moderation-submit').textContent=r.canceled?'このスコアを復元する':'このスコアを取り消す';$('moderation-submit').className=r.canceled?'primary':'danger';$('moderation-reason').value='';if(!$('submission-dialog').open)$('submission-dialog').showModal();
}
$('moderation-form').addEventListener('submit',async e=>{e.preventDefault();const b=$('moderation-submit');b.disabled=true;try{const r=state.selected;await api('/submissions/'+encodeURIComponent(r.submissionId)+'/moderate',{method:'POST',body:JSON.stringify({action:r.canceled?'restore':'cancel',version:r.moderationVersion,reason:$('moderation-reason').value})});$('submission-dialog').close();notice(r.canceled?'スコアを復元しました。':'スコアを取り消しました。');await loadPage();}catch(error){$('submission-dialog').close();report(error);}finally{b.disabled=false;}});
$('close-dialog').addEventListener('click',()=>$('submission-dialog').close());
function navigate(page){state.page=page;$('notice').hidden=true;loadPage().catch(report);}
async function loadPage(){
  const generation=++state.generation,page=state.page;$('page-title').textContent=titles[page];$('page-help').replaceChildren(help.button(page));document.querySelectorAll('nav button[data-page]').forEach(n=>n.classList.toggle('active',n.dataset.page===page));
  // Render in the live content so form controls are discoverable while page loaders run.
  const target=el('div');$('content').replaceChildren(target);
  await ({overview,rankings:rankingsPage,challenges:challengePage,users:usersPage,audit:auditPage,settings:settingsPage}[page])(target);
  if(generation===state.generation)$('updated').textContent='更新 '+new Date().toLocaleTimeString('ja-JP');
}
document.querySelectorAll('nav button[data-page]').forEach(n=>n.addEventListener('click',()=>{if(n.dataset.page==='users'){state.user=null;state.userReturn=null;}navigate(n.dataset.page);}));
$('refresh').addEventListener('click',()=>loadPage().catch(report));
$('logout').addEventListener('click',async()=>{try{await api('/logout',{method:'POST',body:'{}'});showLogin();}catch(e){report(e);}});
$('login-form').addEventListener('submit',async e=>{e.preventDefault();const b=e.target.querySelector('button');b.disabled=true;$('login-error').textContent='';try{const user=await api('/login',{method:'POST',body:JSON.stringify({username:$('username').value,password:$('password').value})});$('password').value='';showApp(user);}catch(error){$('login-error').textContent=error.message;}finally{b.disabled=false;}});
setInterval(()=>{if(!$('app-view').hidden&&state.page==='overview'&&!document.querySelector('dialog[open]'))loadPage().catch(report);},15000);
api('/me').then(showApp).catch(()=>showLogin());
