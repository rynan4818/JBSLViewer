"use strict";
const labels={reserved:"予約済み",started:"開始済み",submitted:"提出済み",abandoned:"受付期限切れ"};
const shown=value=>value===null||value===undefined?"—（未送信）":typeof value==="boolean"?(value?"true":"false"):String(value);
const mapCell=r=>`${esc(r.characteristic)} / ${esc(r.difficulty)}<small><code>${esc(r.map_hash)}</code></small>`;
const statusBadge=value=>`<span class="badge ${value==="submitted"?"green":value==="abandoned"?"red":""}">${esc(labels[value]||value)}</span>`;
const rankingBadge=value=>`<span class="badge ${value?"green":""}">${value?"採用対象":"対象外"}</span>`;
const recordButton=(kind,id,label="詳細")=>`<button data-record-kind="${kind}" data-record-id="${esc(id)}">${label}</button>`;
const pageState=Object.fromEntries(["results","challenges","budgets","audit"].map(key=>[key,{page:1,total:0,sequence:0}]));

async function loadState(){
  const data=await api("state");
  $("state-counts").innerHTML=[["challenges","Challenge"],["results","提出済み結果"],["users","テストユーザー"]].map(([key,label])=>`<article><span>${label}</span><strong>${data.counts[key]}</strong><small>${key==="results"?`採用対象 ${data.rankedResults} · 対象外 ${data.unrankedResults}`:"この仮サーバの SQLite"}</small></article>`).join("");
  $("status-counts").innerHTML=Object.entries(data.challengeCounts).map(([name,count])=>`<span class="badge">${labels[name]} <b>${count}</b></span>`).join("");
  $("server-clock").textContent="判定用サーバ時刻: "+stamp(data.serverTime)+" · 時計差 "+overview.behavior.clock_offset_seconds+" 秒";
  $("request-counts").textContent=JSON.stringify(data.requests,null,2);
}
function listParams(key){
  const params=new URLSearchParams({page:pageState[key].page,page_size:25});
  for(const field of ["league","sid","q","ranking","end_type","status"]){
    const input=$(key+"-"+field);
    if(input?.value)params.set(field==="league"?"league_id":field,input.value);
  }
  return params;
}
async function loadList(key){
  const state=pageState[key], sequence=++state.sequence;
  const data=await api(key+"?"+listParams(key));
  if(sequence!==state.sequence)return;
  state.total=data.total;
  $(key+"-page").textContent=`${data.total} 件 · ${data.page} / ${Math.max(1,Math.ceil(data.total/data.pageSize))} ページ`;
  $(key+"-prev").disabled=data.page<=1;
  $(key+"-next").disabled=data.page*data.pageSize>=data.total;
  $(key+"-rows").innerHTML=data.items.map(r=>{
    if(key==="results")return `<tr><td>${stamp(r.received_at)}<small><code>${esc(r.id)}</code></small></td><td>${esc(r.display_name)}<small>${esc(r.sid)} · リーグ ${r.league_id}</small></td><td>${mapCell(r)}</td><td class="score-value">${esc(shown(r.modified_score))}<small>最大 ${esc(shown(r.max_possible_modified_score))}</small></td><td>${esc(r.end_type)}<small>${rankingBadge(r.valid_for_ranking)}</small><small>${esc(r.invalid_reason)}</small></td><td>${recordButton("results",r.id)}</td></tr>`;
    if(key==="challenges")return `<tr><td>${stamp(r.reserved_at)}<small><code>${esc(r.id)}</code></small></td><td>${esc(r.display_name)}<small>${esc(r.sid)} · リーグ ${r.league_id}</small></td><td>${mapCell(r)}</td><td>${statusBadge(r.effective_status)}</td><td>${r.attempt_number} / ${r.attempt_limit_at_reserve}<small>${stamp(r.result_accept_until)}</small></td><td>${recordButton("challenges",r.id)}</td></tr>`;
    if(key==="budgets")return `<tr><td class="mono">${esc(r.sid)}</td><td>${r.league_id}</td><td>${mapCell(r)}</td><td>${r.used_attempts} / ${r.attempt_limit}</td></tr>`;
    return `<tr><td>${stamp(r.occurred_at)}</td><td>${esc(r.event_type)}</td><td class="mono">${esc(r.sid||"—")}</td><td>${r.challenge_id?recordButton("challenges",r.challenge_id,r.challenge_id):"未作成"}</td><td><code>${esc(JSON.stringify(r.details))}</code></td></tr>`;
  }).join("")||`<tr><td colspan="6" class="empty">該当する記録はありません。フィルター条件と送信先スコアAPIを確認してください。</td></tr>`;
}
function facts(values){return '<div class="detail-grid">'+values.map(([label,value])=>`<dl><dt>${esc(label)}</dt><dd>${esc(shown(value))}</dd></dl>`).join("")+'</div>';}
function jsonBlock(label,value){return `<details class="record-section"><summary>${label}</summary><pre>${esc(JSON.stringify(value,null,2))}</pre></details>`;}
async function openRecord(kind,id){
  const data=await api(kind+"/"+encodeURIComponent(id)), c=data.challenge, r=data.result;
  $("record-title").textContent=kind==="results"?"提出スコアの詳細":"Challenge の詳細";
  let html=`<p><code>${esc(c.id)}</code> ${statusBadge(c.effective_status)} ${help("challenge_status","Challenge の状態")}</p>`;
  html+=facts([["SID / 表示名",c.sid+" / "+c.display_name],["リーグ / revision",c.league_id+" / "+c.qualifier_revision],["譜面",c.map_hash+" / "+c.characteristic+" / "+c.difficulty],["予約回数 / 予約時上限",c.attempt_number+" / "+c.attempt_limit_at_reserve],["DBに保存された状態",c.status],["現在の判定用サーバ時刻",stamp(data.serverTime)]]);
  html+='<div class="timeline" role="img" aria-label="予約、開始、結果受理、受付期限の時系列">'+[["予約",c.reserved_at],["開始",c.started_at],["結果受理",c.submitted_at],["受付期限",c.result_accept_until]].map(([label,time])=>`<div class="${time?"done":""}"><b>${label}</b><small>${time?stamp(time):"通知なし"}</small></div>`).join("")+'</div>';
  if(c.operationalTimeoutAt)html+=`<p class="callout">現在の運用タイムアウト: ${stamp(c.operationalTimeoutAt)} ${help("challenge_timeout_seconds","運用タイムアウト")}</p>`;
  if(r){
    html+=`<section class="record-section"><h3>受理したスコア ${help("ranking","ランキング採用可否")}</h3><p>${rankingBadge(r.valid_for_ranking)} ${esc(r.invalid_reason||"")} · 結果ID <code>${esc(r.id)}</code></p>`;
    html+=facts([["終了種別",r.end_type],["Modified Score",r.modified_score],["Multiplied Score",r.multiplied_score],["最大スコア",r.max_possible_modified_score],["ミス / Bad Cut",shown(r.missed_count)+" / "+shown(r.bad_cuts_count)],["Good Cut / 最大コンボ",shown(r.good_cuts_count)+" / "+shown(r.max_combo)],["Full Combo",r.full_combo===null?null:Boolean(r.full_combo)],["Energy",r.energy],["Restart検出",Boolean(r.restart_detected)],["Play Instance数",r.play_instance_count]]);
    html+=`<h3>リプレイ ${help("replay","リプレイ保存状態")}</h3>`;
    html+=data.replay?facts([["ファイル",data.replay.fileExists?"保存済み":"保存記録あり・ファイルなし"],["展開後バイト数",data.replay.byteCount],["SHA-256",data.replay.sha256]]):'<p class="muted">リプレイの提出はありません。</p>';
    html+=`<h3>提出データ ${help("metadata","提出メタデータ")}</h3>`+jsonBlock("受信メタデータ JSON",r.metadata)+jsonBlock("受理時の API 応答 JSON",r.response)+'</section>';
  }else html+='<div class="callout">受理済みの結果はまだありません。提出の拒否や期限切れは以下の受付履歴で確認できます。</div>';
  html+=jsonBlock("Challenge と開始通知の詳細 JSON",c);
  html+='<section class="record-section"><h3>この Challenge の受付履歴</h3><div class="table-scroll"><table><thead><tr><th>時刻</th><th>種類</th><th>詳細</th></tr></thead><tbody>'+data.events.map(e=>`<tr><td>${stamp(e.occurred_at)}</td><td>${esc(e.event_type)}</td><td><code>${esc(JSON.stringify(e.details))}</code></td></tr>`).join("")+'</tbody></table></div></section>';
  $("record-body").innerHTML=html;
  if(!$("record-dialog").open)$("record-dialog").showModal();
  $("record-body").scrollTop=0;
}
$("close-record").addEventListener("click",()=>$("record-dialog").close());
document.addEventListener("click",event=>{const button=event.target.closest("[data-record-id]");if(button)busy(button,()=>openRecord(button.dataset.recordKind,button.dataset.recordId));});
for(const key of Object.keys(pageState)){
  $(key+"-filters").addEventListener("submit",event=>{event.preventDefault();pageState[key].page=1;busy(event.submitter,()=>loadList(key));});
  for(const [suffix,delta] of [["prev",-1],["next",1]])$(key+"-"+suffix).addEventListener("click",async event=>{
    await busy(event.currentTarget,async()=>{pageState[key].page+=delta;await loadList(key);});
    $(key+"-prev").disabled=pageState[key].page<=1;
    $(key+"-next").disabled=pageState[key].page*25>=pageState[key].total;
  });
}
$("reload-state").addEventListener("click",event=>busy(event.currentTarget,async()=>{await loadOverview();await loadState();}));
$("probe-upstream").addEventListener("click",event=>busy(event.currentTarget,async()=>{
  if(!$("probe-id").reportValidity())return;
  const result=await api("probe/"+encodeURIComponent($("probe-id").value));
  $("probe-output").hidden=false;$("probe-output").textContent=JSON.stringify(result,null,2);
  notice("リーグ取得先への接続と Qualifier 応答を確認しました。");
}));
document.querySelectorAll("[data-action]").forEach(button=>button.addEventListener("click",()=>busy(button,async()=>{await api("actions/"+button.dataset.action,"POST");await loadState();notice(button.textContent+"を実行しました。");})));
document.querySelectorAll("[data-page]").forEach(button=>button.addEventListener("click",()=>busy(button,async()=>{
  currentPage=button.dataset.page;
  notice("");
  document.querySelectorAll(".page").forEach(p=>p.hidden=p.id!=="page-"+currentPage);
  document.querySelectorAll(".nav").forEach(n=>n.classList.toggle("active",n===button));
  if(currentPage==="settings"){$("behavior-fields").replaceChildren();await loadOverview();renderSettings();}
  else if(currentPage==="traffic")await loadLogs();
  else if(currentPage==="state"){await loadOverview();await loadState();}
  else await loadList(currentPage);
})));
setInterval(()=>{if(document.hidden)return;if(currentPage==="traffic"&&$("log-auto").checked)loadLogs().catch(e=>notice(e.message,true));},3000);
setInterval(()=>{if(!document.hidden&&pageState[currentPage]&&$(currentPage+"-auto").checked)loadList(currentPage).catch(e=>notice(e.message,true));},5000);
(async()=>{await loadOverview();await loadState();})().catch(error=>{notice(error.message,true);$("connection").textContent="接続エラー";});
