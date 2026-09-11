"use strict";
const $ = id => document.getElementById(id);
const endpoint = "/public/api/qualifier-leagues";
const stamp = value => value ? new Date(value).toLocaleString("ja-JP", {hour12:false,timeZoneName:"short"}) : "未取得";
let catalog, loading = false, pending = 0;
const forms = new Map();

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}
async function api(path=endpoint, body) {
  let response, data;
  try {
    response = await fetch(path, {method:body ? "POST" : "GET", credentials:"omit",
      headers:{"Content-Type":"application/json","X-JBSL-Public":"1"}, ...(body ? {body:JSON.stringify(body)} : {})});
    data = await response.json();
  } catch (_) { throw new Error("サーバに接続できませんでした。時間を置いて再試行してください。"); }
  if (!response.ok) throw Object.assign(new Error(data.error?.message || "処理できませんでした。時間を置いて再試行してください。"),
                                        {status:response.status, code:data.error?.code});
  return data;
}
function syncButtons() {
  $("reload-leagues").disabled = loading || pending > 0;
  for (const form of forms.values()) {
    form.input.disabled = loading || form.busy || form.unavailable || !catalog?.canAddSid;
    form.button.disabled = form.input.disabled;
    form.button.textContent = form.busy ? "追加中…" : "SIDを追加";
  }
}
function catalogNotice(message, info=false) {
  $("catalog-notice").textContent = message;
  $("catalog-notice").hidden = !message;
  $("catalog-notice").className = "catalog-notice" + (info ? " info" : "");
}
function card(league, savedInput) {
  const article = element("article", "qualifier-card");
  article.dataset.league = league.id;
  const details = element("div", "league-details"), meta = element("div", "league-meta");
  meta.append(element("span", "league-id", "LEAGUE " + league.id), element("span", "qualifier-badge", "Qualifier 有効"));
  const title = element("h2", "", league.name);
  title.id = "league-title-" + league.id;
  article.setAttribute("aria-labelledby", title.id);
  const dates = element("dl", "league-dates");
  dates.append(element("dt", "", "Qualifier開始"), element("dd", "", league.startsAt ? stamp(league.startsAt) : "開始日時の指定なし"),
               element("dt", "", "Qualifier終了"), element("dd", "", stamp(league.endsAt)));
  details.append(meta, title, dates);
  const node = element("form", "sid-form"), label = element("label", "", "追加するSID");
  const input = element("input");
  input.id = "sid-" + league.id; input.name = "sid"; input.type = "text"; input.required = true; input.maxLength = 128;
  input.autocomplete = "off"; input.spellcheck = false; input.value = savedInput || "";
  input.placeholder = "例: 76561198000000000";
  label.htmlFor = input.id;
  const hint = element("small", "", "空白を含まない1〜128文字で入力してください。");
  hint.id = "sid-hint-" + league.id;
  const button = element("button", "", "SIDを追加"), result = element("p", "sid-result");
  button.type = "submit"; result.id = "sid-result-" + league.id; result.setAttribute("role", "status");
  result.setAttribute("aria-live", "polite"); input.setAttribute("aria-describedby", hint.id + " " + result.id);
  node.append(label, input, hint, button, result);
  const form = {input, button, result, busy:false, unavailable:false};
  forms.set(league.id, form);
  node.addEventListener("submit", event=>{event.preventDefault();addSid(league.id, form);});
  article.append(details, node);
  return article;
}
async function loadCatalog() {
  if (loading || pending) return;
  loading = true; syncButtons(); $("league-list").setAttribute("aria-busy", "true");
  try {
    const data = await api();
    const saved = new Map([...forms].map(([id, form])=>[id, form.input.value]));
    catalog = data; forms.clear();
    $("league-list").replaceChildren(...data.items.map(league=>card(league, saved.get(league.id))));
    $("league-count").textContent = data.items.length + "リーグ";
    $("catalog-time").textContent = "開催中一覧の最終取得: " + stamp(data.fetchedAt);
    if (data.stale) catalogNotice("現在の開催状況を確認できません。前回取得時の情報を表示しています。SID追加は一時停止しています。");
    else if (data.source === "snapshot") catalogNotice("保存済み情報による検証です。取得日時時点の開催中一覧を使用しています。", true);
    else catalogNotice("");
    if (!data.items.length) {
      const empty = element("div", "empty-list");
      empty.append(element("p", "", data.stale ? "前回取得時の情報に、表示対象のリーグはありません。" : "現在、公開対象のQualifierリーグはありません。"));
      $("league-list").append(empty);
    }
  } catch (error) {
    if (catalog) catalog.canAddSid = false;
    else $("league-count").textContent = "一覧を取得できませんでした";
    catalogNotice(error.message + " 開催状況を確認できるまでSID追加を停止します。");
  } finally { loading = false; $("league-list").setAttribute("aria-busy", "false"); syncButtons(); }
}
async function addSid(id, form) {
  if (loading || form.busy || form.unavailable || !catalog?.canAddSid) return;
  const sid = form.input.value.trim();
  form.result.className = "sid-result";
  if (!sid || [...sid].length > 128 || /\s|[\u0000-\u001f\u007f-\u009f]/u.test(sid)) {
    form.result.textContent = "SIDは空白・改行を含まない1〜128文字で入力してください。";
    form.result.classList.add("error"); form.input.focus(); return;
  }
  form.busy = true; pending++; syncButtons(); form.result.textContent = "SIDを追加しています…";
  try {
    const result = await api(endpoint + "/" + id + "/participants", {sid});
    form.result.textContent = result.added ? "SIDを追加しました。" : "このSIDは登録済みです。";
    form.input.value = "";
  } catch (error) {
    form.result.textContent = error.message; form.result.classList.add("error");
    if (error.status === 404) form.unavailable = true;
    if (error.code === "active_leagues_unavailable") {
      catalog.canAddSid = false;
      catalogNotice("開催状況を確認できないため、SID追加を一時停止しています。時間を置いて一覧を更新してください。");
    }
  } finally { form.busy = false; pending--; syncButtons(); }
}
$("reload-leagues").addEventListener("click", loadCatalog);
loadCatalog();
