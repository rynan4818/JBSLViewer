"use strict";
const $ = id => document.getElementById(id);
const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const stamp = value => value ? new Date(value).toLocaleString("ja-JP", {timeZone: "Asia/Tokyo", hour12: false}) + " JST" : "未取得";
const help = (key, label) => `<button type="button" class="help" data-help="${key}" aria-label="${esc(label)}の説明">?</button>`;
const option = (value, label) => `<option value="${value}">${label}</option>`;
let overview, currentPage = "state", currentLogs = [], logBusy = false;
function notice(message, error=false) { $("notice").textContent = message; $("notice").className = error ? "error" : ""; }
async function api(path, method="GET", body) {
  const response = await fetch("/admin/api/" + path, {method, headers: {"Content-Type":"application/json","X-JBSL-Admin":"1"},
    ...(method === "GET" ? {} : {body:JSON.stringify(body ?? {})})});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error?.message || "HTTP " + response.status);
  return data;
}
async function busy(button, fn) {
  button.disabled = true;
  try { await fn(); } catch (error) { notice(error.message, true); }
  finally { button.disabled = false; }
}
async function loadOverview() {
  overview=await api("overview");
  $("connection").textContent="● 127.0.0.1 · 仮スコア管理 " + new URL(overview.urls.admin).port;
  $("score-docs").href=overview.urls.score+"/docs";
  $("viewer-config").textContent=JSON.stringify(overview.viewerConfig,null,2);
  $("upstream-url").textContent=overview.behavior.upstream_base_url;
  $("data-path").textContent=overview.dataDirectory;
  $("api-links").innerHTML=`<a class="button" href="${esc(overview.urls.score)}/docs" target="_blank" rel="noopener">スコア API · Swagger ↗</a><a class="button" href="/guide" target="_blank" rel="noopener">図付きガイド ↗</a>`;
}
const settingsCategories = [
  {
    id: "viewer", title: "JBSLViewer(mod) 向け",
    description: "JBSLViewer(mod) からの認証・スコアAPI通信・結果提出に対する、このサーバの応答や受信条件を設定します。",
    groups: [
      ["テストユーザーと認証",[
        ["stub_sid","テスト SID","text"],["stub_display_name","テスト表示名","text"],
        ["session_seconds","Viewer セッションの寿命（秒）","number",[1,86400]]]],
      ["API の障害・遅延とレート制限",[
        ["score_fault","スコア API の障害","select",[["none","なし"],["unavailable","503 · 一時障害"],["authentication_required","401 · 認証要求"],["rate_limited","429 · レート制限"]]],
        ["score_fault_route","スコア障害・遅延の対象","select",[["all","すべて"],["auth","認証"],["status","status · 資格確認"],["reserve","reserve · 予約"],["started","started · 開始"],["result","result · 結果提出"]]],
        ["score_delay_ms","スコア API の遅延（ミリ秒）","number",[0,60000]],
        ["rate_limit_enabled","通常のレート制限","checkbox"]]],
      ["提出サイズの上限",[
        ["compressed_replay_limit","圧縮リプレイ上限（バイト）","number",[1024,67108864]],
        ["expanded_replay_limit","展開後リプレイ上限（バイト）","number",[1024,536870912]],
        ["metadata_limit","メタデータ上限（バイト）","number",[1024,4194304]]]]
    ]
  },
  {
    id: "jbsl-web", title: "jbsl-web 連携",
    description: "このスコア管理サーバから jbsl-web（中継APIを含む）へリーグ情報を取得するときの接続と、取得した情報のキャッシュを設定します。",
    groups: [
      ["リーグ取得先",[
        ["upstream_base_url","リーグ取得先 URL","text"],
        ["upstream_timeout_seconds","リーグ取得のタイムアウト（秒）","number",[1,120]]]],
      ["リーグ情報のキャッシュ",[
        ["cache_fresh_seconds","通常キャッシュ期限（秒）","number",[0,3600]],
        ["cache_stale_seconds","参考キャッシュ期限（秒）","number",[0,86400]]]]
    ]
  },
  {
    id: "shared", title: "共通",
    description: "このサーバ内で、Viewer の認証・受付判定と、jbsl-web から取得したリーグ情報のキャッシュに共通して使う設定です。",
    groups: [
      ["サーバ時刻",[
        ["clock_offset_seconds","スコアサーバの時計差（秒）","number",[-31536000,31536000]]]]
    ]
  },
  {
    id: "score-manager", title: "スコア管理サーバ固有",
    description: "チャレンジ予約と結果提出を受け付ける期限を、このスコア管理サーバで判定するための設定です。",
    groups: [
      ["期間と受付ポリシー",[
        ["result_grace_seconds","結果提出の猶予 α（秒）","number",[0,604800]],
        ["result_deadline_equal_is_accepted","受付期限ちょうどを受理","checkbox"],
        ["challenge_timeout_seconds","予約からの運用タイムアウト（秒・任意）","optional",[1,604800]],
        ["server_start_deadline_policy","サーバの開始締切ポリシー","select",[["effective_end_only","実効終了のみ"],["effective_end_minus_song_duration","実効終了 − 曲時間"]]]]]
    ]
  }
];
const behaviorFields = settingsCategories.flatMap(category=>category.groups.flatMap(([,fields])=>fields));
function renderSettings() {
  $("behavior-fields").innerHTML = `<p class="callout">この画面では、スコア管理サーバの設定を通信相手・適用範囲ごとにまとめています。</p>` + settingsCategories.map(category=>`<section class="settings-category" aria-labelledby="settings-${category.id}-title" aria-describedby="settings-${category.id}-description"><header class="settings-category-header"><h2 id="settings-${category.id}-title">${esc(category.title)}</h2><p id="settings-${category.id}-description">${esc(category.description)}</p></header>${category.groups.map(([title,fields])=>`<article class="panel"><h3>${esc(title)}</h3><div class="field-grid">${fields.map(([key,label,type,args])=>{
    const value=overview.behavior[key]; let input;
    if(type==="select")input=`<select id="b-${key}">${args.map(([v,l])=>option(v,l)).join("")}</select>`;
    else if(type==="checkbox")input=`<input id="b-${key}" type="checkbox" ${value?"checked":""}>`;
    else input=`<input id="b-${key}" type="${type==="text"?"text":"number"}" ${args?`min="${args[0]}" max="${args[1]}" step="1"`:"maxlength=512"} ${type==="optional"?"":"required"} value="${esc(value ?? "")}">`;
    return `<div class="field">${type==="checkbox"?`<label class="check" for="b-${key}">${input}${label}</label>${help(key,label)}`:`<label for="b-${key}">${label}</label>${help(key,label)}${input}`}<small>${esc(HELP[key][1].split("\n")[0])}</small></div>`;
  }).join("")}</div></article>`).join("")}</section>`).join("");
  behaviorFields.filter(f=>f[2]==="select").forEach(([key])=>$("b-"+key).value=overview.behavior[key]);
}
$("settings-form").addEventListener("submit",event=>{
  event.preventDefault(); busy(event.submitter,async()=>{
    notice("");
    const behavior={};
    behaviorFields.forEach(([key,,type])=>{
      const el=$("b-"+key); behavior[key]=type==="checkbox"?el.checked:type==="number"?Number(el.value):type==="optional"?(el.value===""?null:Number(el.value)):el.value;
    });
    await api("settings","PUT",{behavior,generation:overview.generation});
    await loadOverview(); notice("サーバ設定を保存しました。次のリクエストから反映されます。");
  });
});
$("reload-settings").addEventListener("click",event=>busy(event.currentTarget,async()=>{await loadOverview();renderSettings();notice("サーバ設定を再読込しました。");}));
async function loadLogs() {
  if(logBusy)return; logBusy=true;
  try {
    const data=await api(`logs?role=${encodeURIComponent($("log-role").value)}&errors=${$("log-errors").checked}`);
    currentLogs=data.items;
    $("log-count").textContent=`${data.items.length}件表示 · 最大${data.capacity}件を保持 · 本文・認証情報は記録しません`;
    $("log-rows").innerHTML=data.items.slice().reverse().map(r=>`<tr><td>${stamp(r.time)}</td><td>${esc(r.role)}<small>${esc(r.source)}</small></td><td class="mono">${esc(r.method)} ${esc(r.path)}</td><td><span class="badge ${r.status>=400||r.errorCode?"red":"green"}">${r.status}</span></td><td>${r.elapsedMs ?? "—"} ms</td><td><code>${esc(r.requestId)}</code><small>${esc(r.errorCode)}</small></td></tr>`).join("")||'<tr><td colspan="6" class="empty">まだ通信ログがありません。Swagger UIまたはViewerから実行すると記録されます。</td></tr>';
  } finally {logBusy=false;}
}
for(const id of ["log-role","log-errors"])$(id).addEventListener("change",()=>loadLogs().catch(e=>notice(e.message,true)));
$("reload-logs").addEventListener("click",event=>busy(event.currentTarget,loadLogs));
$("clear-logs").addEventListener("click",event=>busy(event.currentTarget,async()=>{await api("logs/clear","POST");await loadLogs();notice("表示ログを消去しました。");}));
$("export-logs").addEventListener("click",()=>{
  const url=URL.createObjectURL(new Blob([JSON.stringify(currentLogs,null,2)],{type:"application/json"}));
  const link=document.createElement("a"); link.href=url;link.download="jbsl-mock-traffic.json";link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
});
