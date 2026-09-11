"use strict";
const $ = id => document.getElementById(id);
const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const stamp = value => value ? new Date(value).toLocaleString("ja-JP", {hour12: false, timeZoneName: "short"}) : "未取得";
const help = (key, label) => `<button type="button" class="help" data-help="${key}" aria-label="${esc(label)}の説明">?</button>`;
const option = (value, label) => `<option value="${value}">${label}</option>`;
let overview, leagueList, editorState, currentPage = "leagues", currentLogs = [], logBusy = false;
let authenticated = false, csrfToken = "", authGeneration = 0, sessionTimer, loginPending = false;
const pendingRequests = new Set();
class SessionEnded extends Error {}
function notice(message, error=false) { if (authenticated) { $("notice").textContent = message; $("notice").className = error ? "error" : ""; } }
async function api(path, method="GET", body) {
  if (!authenticated && !["login","me"].includes(path)) throw new SessionEnded();
  const generation = authGeneration, controller = new AbortController();
  pendingRequests.add(controller);
  try {
    const response = await fetch("/admin/api/" + path, {method, credentials:"same-origin", signal:controller.signal,
      headers:{"Content-Type":"application/json","X-JBSL-Admin":"1","X-CSRF-Token":csrfToken},
      ...(method === "GET" ? {} : {body:JSON.stringify(body ?? {})})});
    const data = response.status === 204 ? null : await response.json();
    if (generation !== authGeneration) throw new SessionEnded();
    if (response.status === 401 && path !== "login") {
      showLogin(authenticated ? "ログインの有効期限が切れました。再度ログインしてください。" : "");
      throw new SessionEnded();
    }
    if (!response.ok) throw new Error(data?.error?.message || "HTTP " + response.status);
    return data;
  } catch (error) {
    if (generation !== authGeneration || error.name === "AbortError") throw new SessionEnded();
    throw error;
  } finally { pendingRequests.delete(controller); }
}
async function busy(button, fn) {
  button.disabled = true;
  try { await fn(); } catch (error) { if (!(error instanceof SessionEnded)) notice(error.message, true); }
  finally { button.disabled = false; }
}
function showLogin(message="") {
  authenticated = false; csrfToken = ""; authGeneration++;
  clearTimeout(sessionTimer);
  for (const controller of pendingRequests) controller.abort();
  pendingRequests.clear();
  for (const dialog of document.querySelectorAll("dialog[open]")) dialog.close();
  overview = leagueList = editorState = null; currentLogs = []; currentPage = "leagues"; logBusy = false;
  for (const id of ["active-leagues","saved-leagues","behavior-fields","api-links","state-counts","log-rows","map-fields"]) $(id).replaceChildren();
  for (const id of ["operator","notice","connection","viewer-config","request-counts","data-path","active-count","enabled-count",
    "upstream-mode","fault-badge","fetched-at","active-error","log-count","editor-title","editor-revision","editor-notes",
    "ranking-sids","effective-end","preview-json","editor-error","help-title","help-text"]) $(id).textContent = "";
  $("league-form").reset(); $("league-search").value = ""; $("q-participants").value = "";
  for (const id of ["q-end","q-start","q-until"]) { $(id).value = ""; delete $(id).dataset.originalLocal; delete $(id).dataset.originalUtc; }
  $("proxy-docs").href = "#"; $("data-path").hidden = true;
  document.querySelectorAll(".page").forEach(p=>p.hidden=p.id!=="page-leagues");
  document.querySelectorAll(".nav").forEach(n=>n.classList.toggle("active",n.dataset.page==="leagues"));
  $("app-view").hidden = true; $("login-view").hidden = false;
  $("password").value = ""; $("login-error").textContent = message;
  $("username").focus();
}
async function showApp(info) {
  authGeneration++; authenticated = true; csrfToken = info.csrfToken;
  $("operator").textContent = info.username;
  $("password").value = ""; $("login-error").textContent = "";
  $("login-view").hidden = true; $("app-view").hidden = false;
  clearTimeout(sessionTimer);
  sessionTimer = setTimeout(()=>showLogin("ログインの有効期限が切れました。再度ログインしてください。"), Math.max(0, Date.parse(info.expiresAt)-Date.now()));
  try {
    await Promise.all([loadOverview(),loadLeagues()]);
    if (!leagueList.active.fetchedAt && overview.behavior.upstream_mode === "live") await busy($("refresh-live"),refreshLive);
  } catch (error) {
    if (!(error instanceof SessionEnded)) { notice(error.message,true); $("connection").textContent = "接続エラー"; }
  }
}
$("login-form").addEventListener("submit",async event=>{
  event.preventDefault();
  if (loginPending) return;
  loginPending = true; $("login-submit").disabled = true; $("login-error").textContent = "";
  try { await showApp(await api("login","POST",{username:$("username").value,password:$("password").value})); }
  catch (error) { if (!(error instanceof SessionEnded)) { $("login-error").textContent = error.message; $("password").value = ""; $("password").focus(); } }
  finally { loginPending = false; $("login-submit").disabled = false; }
});
$("logout").addEventListener("click",event=>busy(event.currentTarget,async()=>{
  await api("logout","POST"); showLogin("ログアウトしました。");
}));
async function loadOverview() {
  overview = await api("overview");
  $("connection").textContent = "● " + new URL(overview.urls.admin).host + " · 接続済み";
  $("environment-tag").textContent = overview.publicMode ? "● SHARED TEST ENVIRONMENT" : "● LOCAL DEBUG ENVIRONMENT";
  $("environment-note").textContent = overview.publicMode ? "TEST ONLY · 共有検証" : "TEST ONLY · ローカル検証";
  $("proxy-docs").href = overview.urls.proxy + "/docs";
  $("viewer-config").textContent = JSON.stringify(overview.viewerConfig, null, 2);
  $("api-links").innerHTML = `<a class="button" href="${esc(overview.urls.proxy)}/docs" target="_blank" rel="noopener">中継 API · Swagger ↗</a><a class="button" href="/guide" target="_blank" rel="noopener">図付きガイド ↗</a>`;
  $("data-path").textContent = overview.dataDirectory ?? "";
  $("data-path").hidden = !overview.dataDirectory;
  $("runtime-details-label").textContent = overview.publicMode ? "リクエスト数" : "リクエスト数・保存先";
  $("upstream-mode").textContent = overview.behavior.upstream_mode === "live" ? "実サーバへ中継" : "保存応答で再現";
  $("fault-badge").textContent = overview.behavior.proxy_fault === "none" ? "中継の障害注入なし" : "障害注入: " + overview.behavior.proxy_fault;
}
async function loadLeagues() {
  leagueList = await api("leagues");
  renderLeagues();
}
function leagueRow(row, saved, isActive) {
  const status = saved ? (saved.enabled ? "Qualifier 有効" : "Qualifier 無効") : "未設定";
  return `<div class="league-row"><span class="league-id">${row.id}</span><div class="league-name"><strong>${esc(row.name)}</strong><small>${isActive ? "終了 " + stamp(row.end) : (row.source === "sample" ? "同梱サンプル" : "実リーグから取込") + " · " + row.mapCount + "譜面 · revision " + esc(row.revision)}${saved && !saved.isOpen ? " · 受付停止" : ""}</small></div><span class="badge ${saved?.enabled ? "green" : ""}">${status}</span><button data-league="${row.id}" data-import="${!saved}">${saved ? "設定を編集" : "取込・設定"}</button></div>`;
}
function renderLeagues() {
  const query = $("league-search").value.toLowerCase();
  const registered = new Map(leagueList.registered.map(r=>[r.id,r]));
  $("active-count").textContent = leagueList.active.items.length;
  $("enabled-count").textContent = leagueList.registered.filter(r=>r.enabled).length;
  $("fetched-at").textContent = "取得元: 実 JBSL-WEB · 最終成功 " + stamp(leagueList.active.fetchedAt);
  $("active-error").hidden = !leagueList.active.error;
  $("active-error").textContent = leagueList.active.error ? "更新に失敗しました。表示は前回の取得結果です。 " + leagueList.active.error : "";
  const rows = leagueList.active.items.filter(r=>`${r.name} ${r.id}`.toLowerCase().includes(query));
  $("active-leagues").innerHTML = rows.map(r=>leagueRow(r,registered.get(r.id),true)).join("") || '<div class="empty">表示するリーグがありません。「実リーグ一覧を更新」で取得できます。</div>';
  $("saved-leagues").innerHTML = leagueList.registered.map(r=>leagueRow(r,r,false)).join("");
}
async function refreshLive() {
  try { await api("leagues/refresh", "POST"); notice("実 JBSL-WEB の開催中リーグを更新しました。"); }
  finally { await loadLeagues(); }
}
$("refresh-live").addEventListener("click", event => busy(event.currentTarget, refreshLive));
$("league-search").addEventListener("input", renderLeagues);
document.addEventListener("click", event => {
  const target = event.target.closest("[data-league]");
  if (target) busy(target, () => openLeague(Number(target.dataset.league), target.dataset.import === "true"));
});
function dateInput(value) {
  if (!value) return "";
  const date = new Date(value);
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0,23);
}
function setDateInput(id, value) {
  const input = $(id);
  input.value = dateInput(value);
  input.dataset.originalLocal = input.value;
  input.dataset.originalUtc = value ?? "";
}
function wireDate(id) {
  const input = $(id);
  if (!input.value) return null;
  // Keep the original instant when a DST clock change repeats a local time.
  const value = input.value === input.dataset.originalLocal && input.dataset.originalUtc || input.value;
  return new Date(value).toISOString();
}
async function openLeague(id, importing) {
  const data = await api("leagues/" + id + (importing ? "/import" : ""), importing ? "POST" : "GET");
  editorState = {id, ...data};
  const entry = data.entry, fixture = entry.fixture, q = fixture.qualifier;
  $("editor-title").textContent = id + " · " + entry.upstream.league_title;
  $("editor-revision").textContent = "revision " + (data.expectedRevision ?? "未保存") + " · " + (entry.source === "sample" ? "同梱サンプル" : "実 JBSL-WEB から取込");
  $("editor-notes").textContent = entry.notes.join(" ");
  $("q-enabled").checked = q.enabled;
  $("q-method").value = q.submission_method;
  $("q-live").checked = fixture.isLive;
  $("q-open").checked = fixture.isOpen;
  setDateInput("q-end", fixture.end);
  setDateInput("q-start", q.starts_at);
  setDateInput("q-until", q.ends_at);
  $("editor-timezone").textContent = "日時はブラウザのローカル時刻（" + Intl.DateTimeFormat().resolvedOptions().timeZone + "）で入力・表示します。";
  $("q-participants").value = fixture.participants.map(p=>p.sid).join("\n");
  $("q-auto-sids").checked = fixture.auto_add_ranking_sids ?? true;
  showRankingSids();
  $("map-fields").innerHTML = fixture.maps.map((map, index) => {
    const raw = "lid" in map ? entry.upstream.maps.find(m=>String(m.lid)===String(map.lid)) : entry.upstream.maps[map.index];
    return `<article class="map-card"><h4>${index+1}. ${esc(raw.title)}</h4><p class="map-identity">hash: ${esc(raw.hash)} · ${"lid" in map ? "lid: " + esc(map.lid) : "index: " + map.index}</p><div class="map-grid">
    <div class="field"><label for="map-char-${index}">Characteristic</label>${help("characteristic","Characteristic " + (index+1))}<input id="map-char-${index}" value="${esc(map.characteristic)}" required maxlength="80"></div>
    <div class="field"><label for="map-diff-${index}">Difficulty</label>${help("difficulty","Difficulty " + (index+1))}<select id="map-diff-${index}" required>${option("","選択してください")}${["Easy","Normal","Hard","Expert","ExpertPlus"].map(v=>option(v,v)).join("")}</select></div>
    <div class="field"><label for="map-duration-${index}">曲時間（秒・任意）</label>${help("song_duration_seconds","曲時間 " + (index+1))}<input id="map-duration-${index}" type="number" min="0.001" step="any" value="${map.song_duration_seconds ?? ""}"></div>
    <div class="field"><label for="map-limit-${index}">回数上限</label>${help("qualifier_attempt_limit","回数上限 " + (index+1))}<input id="map-limit-${index}" type="number" min="1" max="100" step="1" value="${map.qualifier_attempt_limit ?? 3}" required></div></div></article>`;
  }).join("");
  fixture.maps.forEach((m,i)=>$("map-diff-"+i).value=m.difficulty);
  $("editor-error").hidden = true;
  $("preview-json").textContent = "「JSON をプレビュー」で検証できます。";
  $("preview-details").open = false;
  $("probe-league").disabled = data.expectedRevision === null;
  syncEnabled(false);
  $("editor").showModal();
}
function syncEnabled(changed) {
  const enabled = $("q-enabled").checked;
  $("q-method").disabled = !enabled;
  $("q-start").disabled = !enabled;
  $("q-until").disabled = !enabled;
  if (changed) {
    $("q-method").value = enabled ? "jbsl_qualifier_v1" : "external_leaderboard";
    if (!enabled) { $("q-start").value = ""; $("q-until").value = ""; }
  }
  editorState.entry.fixture.maps.forEach((_,i)=>$("map-limit-"+i).disabled=!enabled);
  effectiveEnd();
}
function effectiveEnd() {
  const value = $("q-enabled").checked && wireDate("q-until") || wireDate("q-end");
  $("effective-end").textContent = value ? stamp(value) : "未設定";
}
function showRankingSids() {
  const manual = new Set($("q-participants").value.split(/\r?\n/));
  const sids = (editorState.rankingSids ?? []).filter(sid=>!manual.has(sid));
  $("ranking-sids").textContent = $("q-auto-sids").checked
    ? "自動追加対象（取込時のランキング）: " + (sids.length ? sids.join(" / ") : "なし") + "。中継時はその時点のランキングから追加します。"
    : "自動追加はOFFです。下の欄に入力したSIDだけを参加者として返します。";
}
$("q-auto-sids").addEventListener("change", showRankingSids);
$("q-participants").addEventListener("input", showRankingSids);
$("q-enabled").addEventListener("change", ()=>syncEnabled(true));
for (const id of ["q-end","q-until"]) $(id).addEventListener("input",effectiveEnd);
$("close-editor").addEventListener("click",()=>$("editor").close());
$("add-sid").addEventListener("click",()=>{
  const lines = $("q-participants").value.split("\n").filter(Boolean), sid = overview.behavior.participant_helper_sid;
  if (!lines.includes(sid)) lines.push(sid);
  $("q-participants").value = lines.join("\n");
  showRankingSids();
});
function readFixture() {
  const fixture = structuredClone(editorState.entry.fixture), enabled = $("q-enabled").checked;
  fixture.isLive = $("q-live").checked; fixture.isOpen = $("q-open").checked; fixture.end = wireDate("q-end");
  fixture.qualifier = {enabled, submission_method:enabled ? $("q-method").value : "external_leaderboard", revision:fixture.qualifier.revision,
    starts_at:enabled ? wireDate("q-start") : null, ends_at:enabled ? wireDate("q-until") : null};
  fixture.participants = $("q-participants").value.split(/\r?\n/).filter(s=>s!=="").map(sid=>({sid}));
  fixture.auto_add_ranking_sids = $("q-auto-sids").checked;
  fixture.maps.forEach((m,i)=>{
    m.characteristic = $("map-char-"+i).value; m.difficulty = $("map-diff-"+i).value;
    m.song_duration_seconds = $("map-duration-"+i).value === "" ? null : Number($("map-duration-"+i).value);
    m.qualifier_attempt_limit = enabled ? Number($("map-limit-"+i).value) : null;
  });
  return fixture;
}
async function submitLeague(preview) {
  $("editor-error").hidden = true;
  try {
    const result = await api("leagues/"+editorState.id+(preview?"/preview":""),preview?"POST":"PUT",{fixture:readFixture(),expectedRevision:editorState.expectedRevision});
    if (preview) { $("preview-json").textContent=JSON.stringify(result.merged,null,2); $("preview-details").open=true; }
    else { $("editor").close(); await loadLeagues(); notice("リーグ設定を保存しました。revision " + result.entry.fixture.qualifier.revision + "。statusへすぐ反映するには接続したスコアサーバの管理画面でキャッシュを消去してください。"); }
  } catch(error) { if (!(error instanceof SessionEnded) && authenticated) { $("editor-error").textContent=error.message; $("editor-error").hidden=false; $("editor-error").scrollIntoView({block:"nearest"}); } }
}
$("league-form").addEventListener("submit",event=>{event.preventDefault();busy(event.submitter,()=>submitLeague(false));});
$("preview-league").addEventListener("click",event=>{if($("league-form").reportValidity())busy(event.currentTarget,()=>submitLeague(true));});
$("probe-league").addEventListener("click",event=>busy(event.currentTarget,async()=>{
  const data = await api("probe/"+editorState.id);
  $("preview-json").textContent = "HTTP " + data.status + "\n" + JSON.stringify(data.body,null,2);
  $("preview-details").open = true;
}));
const groups = [["中継の設定",[
  ["upstream_mode","実リーグの中継モード","select",[["live","実サーバへ中継"],["snapshot","保存応答で再現"]]],
  ["proxy_fault","中継の障害","select",[["none","なし"],["upstream_unavailable","503 · 上流到達不能"],["upstream_invalid","200 · 壊れた JSON"],["rate_limited","429 · レート制限"],["not_found","404 · リーグ不存在"]]],
  ["proxy_delay_ms","中継の遅延（ミリ秒）","number",[0,60000]],
  ["participant_helper_sid","参加者追加用 SID","text"]
]]];
function renderSettings() {
  $("behavior-fields").innerHTML = groups.map(([title,fields])=>`<article class="panel"><h2>${title}</h2><div class="field-grid">${fields.map(([key,label,type,args])=>{
    const value=overview.behavior[key]; let input;
    if(type==="select")input=`<select id="b-${key}">${args.map(([v,l])=>option(v,l)).join("")}</select>`;
    else if(type==="checkbox")input=`<input id="b-${key}" type="checkbox" ${value?"checked":""}>`;
    else input=`<input id="b-${key}" type="${type==="text"?"text":"number"}" ${args?`min="${args[0]}" max="${args[1]}" step="1"`:"maxlength=128"} ${type==="optional"?"":"required"} value="${esc(value ?? "")}">`;
    return `<div class="field">${type==="checkbox"?`<label class="check" for="b-${key}">${input}${label}</label>${help(key,label)}`:`<label for="b-${key}">${label}</label>${help(key,label)}${input}`}<small>${esc(HELP[key][1].split("\n")[0])}</small></div>`;
  }).join("")}</div></article>`).join("");
  groups.flatMap(g=>g[1]).filter(f=>f[2]==="select").forEach(([key])=>$("b-"+key).value=overview.behavior[key]);
}
$("settings-form").addEventListener("submit",event=>{
  event.preventDefault(); busy(event.submitter,async()=>{
    notice("");
    const behavior={};
    groups.flatMap(g=>g[1]).forEach(([key,,type])=>{
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
    $("log-rows").innerHTML=data.items.slice().reverse().map(r=>`<tr><td>${stamp(r.time)}</td><td>${esc(r.role)}<small>${esc(r.source)}</small></td><td class="mono">${esc(r.method)} ${esc(r.path)}</td><td><span class="badge ${r.status>=400||r.errorCode?"red":"green"}">${r.status}</span></td><td>${r.elapsedMs ?? "—"} ms</td><td><code>${esc(r.requestId)}</code><small>${esc(r.errorCode)}</small></td></tr>`).join("")||'<tr><td colspan="6" class="empty">まだ通信ログがありません。リーグ設定の「保存済み API を確認」またはSwagger UIから実行できます。</td></tr>';
  } finally {logBusy=false;}
}
for(const id of ["log-role","log-errors"])$(id).addEventListener("change",()=>loadLogs().catch(e=>notice(e.message,true)));
$("reload-logs").addEventListener("click",event=>busy(event.currentTarget,loadLogs));
$("clear-logs").addEventListener("click",event=>busy(event.currentTarget,async()=>{await api("logs/clear","POST");await loadLogs();notice("表示ログを消去しました。");}));
$("export-logs").addEventListener("click",()=>{
  const url=URL.createObjectURL(new Blob([JSON.stringify(currentLogs,null,2)],{type:"application/json"}));
  const link=document.createElement("a"); link.href=url;link.download="jbsl-mock-traffic.json";link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
});
async function loadState() {
  const data=await api("state");
  $("state-counts").innerHTML=`<article><span>保存済みリーグ</span><strong>${data.registeredLeagues}</strong><small>この中継サーバの設定</small></article>`;
  $("request-counts").textContent=JSON.stringify(data.requests,null,2);
}
$("reload-state").addEventListener("click",event=>busy(event.currentTarget,loadState));
document.querySelectorAll("[data-action]").forEach(button=>button.addEventListener("click",()=>busy(button,async()=>{
  await api("actions/"+button.dataset.action,"POST");await loadState();notice(button.textContent+"を実行しました。");
})));
document.querySelectorAll("[data-page]").forEach(button=>button.addEventListener("click",()=>busy(button,async()=>{
  currentPage=button.dataset.page;
  notice("");
  document.querySelectorAll(".page").forEach(p=>p.hidden=p.id!=="page-"+currentPage);
  document.querySelectorAll(".nav").forEach(n=>n.classList.toggle("active",n===button));
  if(currentPage==="settings"){$("behavior-fields").replaceChildren();await loadOverview();renderSettings();}
  if(currentPage==="traffic")await loadLogs();
  if(currentPage==="state")await loadState();
})));
setInterval(()=>{if(authenticated&&currentPage==="traffic"&&$("log-auto").checked&&!document.hidden)loadLogs().catch(e=>notice(e.message,true));},3000);
window.addEventListener("pageshow",event=>{if(event.persisted)location.reload();});
api("me").then(showApp).catch(error=>{if (!(error instanceof SessionEnded)) showLogin("接続できませんでした。ログインを再試行してください。");});
