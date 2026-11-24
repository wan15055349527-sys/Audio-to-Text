"use strict";

const $ = id => document.getElementById(id);
const audio = $("audio");
const stateNames = {
  ready: "待转写", queued: "排队中", working: "转写中", stopping: "正在停止",
  cancelled: "已停止", done: "已完成", failed: "失败",
};
const busyStates = new Set(["queued", "working", "stopping"]);
const startable = new Set(["ready", "failed", "cancelled"]);
const demo = {id: "sample", name: "雨后的街道", status: "done", revision: 0};

let jobs = [];
let current = null;
let selected = -1;
let editing = null;
let review = null;
let endPlayback = null;
let audioKey = null;
let selection = 0;
let reading = false;
let picking = false;
let toastTimer = 0;

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function button(text, click, className) {
  const node = element("button", text, className);
  node.type = "button";
  node.onclick = click;
  return node;
}

function time(seconds) {
  const total = Math.floor(Number.isFinite(seconds) ? seconds : 0);
  const pad = n => String(n).padStart(2, "0");
  return (total >= 3600 ? pad(Math.floor(total / 3600)) + ":" : "")
    + pad(Math.floor(total / 60) % 60) + ":" + pad(total % 60);
}

function flash(message) {
  clearTimeout(toastTimer);
  $("toast").textContent = message;
  $("toast").hidden = false;
  toastTimer = setTimeout(() => { $("toast").hidden = true; }, 4500);
}

async function request(path, options) {
  const response = await fetch(path, options);
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "操作失败，请重试。");
  return result;
}

function post(path, value = {}) {
  return request(path, {
    method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(value),
  });
}

const detailPath = id => "api/jobs/" + encodeURIComponent(id);
const isDemo = () => current?.id === demo.id;

function hideExport() {
  $("menu").hidden = true;
  $("exportBtn").setAttribute("aria-expanded", "false");
}

function renderQueue() {
  const items = current?.id === demo.id ? [...jobs, demo] : jobs;
  const links = items.map(job => {
    const label = job.id === demo.id ? "示例稿" : stateNames[job.status];
    const detail = job.duration ? time(job.duration) + " · " + label : label;
    const item = button(undefined, () => openJob(job.id), "q" + (current?.id === job.id ? " active" : ""));
    item.append(element("b", job.name), element("small", detail));
    return item;
  });
  if (document.activeElement?.classList.contains("q")) {
    const focused = Array.from($("files").children).indexOf(document.activeElement);
    $("files").replaceChildren(...links);
    links[focused]?.focus();
  } else {
    $("files").replaceChildren(...links);
  }
  const home = new Option("导入页", "home");
  $("mobile").replaceChildren(home, ...items.map(job => new Option(job.name, job.id)));
  $("mobile").value = current?.id || "home";
  $("toolbar").hidden = !jobs.some(job => startable.has(job.status)) || !current;
}

function paintIntro() {
  const wave = $("example-wave");
  demo.peaks.forEach((peak, index) => {
    if (index % 2) return;
    const bar = element("i", undefined, index / demo.peaks.length < 9 / demo.duration ? "played" : "");
    bar.style.setProperty("--peak", (2 + 31 * peak) + "px");
    wave.append(bar);
  });
}

function setAudio() {
  const key = current?.duration ? current.id : null;
  if (key === audioKey) return;
  audioKey = key;
  endPlayback = null;
  audio.pause();
  audio.removeAttribute("src");
  if (key) audio.src = key === demo.id ? "demo.mp3" : "audio/" + encodeURIComponent(key);
  audio.load();
  audio.playbackRate = Number($("speed").value);
  paintWave();
}

function paintWave() {
  const wave = $("wave");
  const peaks = current?.peaks || [];
  wave.replaceChildren();
  for (const [index, peak] of peaks.entries()) {
    const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    const height = 3 + 39 * peak;
    for (const [key, value] of Object.entries({
      x: index * 660 / peaks.length, y: (44 - height) / 2,
      width: Math.min(2.5, 420 / peaks.length), height, rx: 1.25,
    })) rect.setAttribute(key, value);
    wave.append(rect);
  }
}

function setActive(row) {
  selected = row;
  Array.from($("rows").children).forEach((node, i) => node.classList.toggle("active", i === row));
}

function syncAudio() {
  if (!current || !audioKey) return;
  const total = Number.isFinite(audio.duration) ? audio.duration : current.duration;
  const seconds = audio.currentTime || 0;
  const ratio = total ? seconds / total : 0;
  $("seek").max = total || 1;
  $("seek").value = seconds;
  $("clock").textContent = time(seconds) + " / " + time(total);
  $("head").style.left = Math.min(100, ratio * 100) + "%";
  const bars = $("wave").children;
  Array.from(bars).forEach((bar, index) => {
    bar.classList.toggle("played", index / bars.length < ratio);
  });
  if (!audio.paused && !editing && !review) {
    if (endPlayback !== null && seconds >= endPlayback) {
      audio.pause();
      endPlayback = null;
      return;
    }
    const index = current.rows.findIndex(row => row.start <= seconds && seconds < row.end);
    if (index !== -1 && index !== selected) setActive(index);
  }
}

async function play() {
  try { await audio.play(); }
  catch { flash("无法播放这段音频，请重试。"); }
}

async function listen(index) {
  if (!(await commitEdit())) return;
  review = null;
  setActive(index);
  const row = current.rows[index];
  audio.currentTime = row.start;
  endPlayback = row.end;
  drawRows();
  play();
}

function drawComparison(container, row, index) {
  const panel = element("div", undefined, "compare");
  const original = element("div");
  original.append(element("small", "当前稿件", "label"), element("p", row.text));
  const candidate = element("div");
  const result = review.pending ? "正在复核…" : review.error || review.text || "这一段未识别出文字。";
  candidate.append(element("small", "Paraformer 复核", "label"), element("p", result));
  const controls = element("div", undefined, "compare-actions");
  if (review.text) {
    controls.append(button("采用复核文字", async () => {
      const value = review.text;
      try {
        await saveText(index, value);
        review = null;
        renderCurrent();
        flash("已采用复核文字");
      } catch (error) { flash(error.message); }
    }, "outline"));
  }
  controls.append(button("关闭", () => { review = null; drawRows(); }, "link"));
  panel.append(original, candidate, controls);
  container.append(panel);
}

async function compare(index) {
  if (!(await commitEdit())) return;
  audio.pause();
  const pending = {index, pending: true};
  review = pending;
  selected = index;
  drawRows();
  try {
    const result = await post(detailPath(current.id) + "/review", {row: index});
    pending.text = result.text;
  } catch (error) { pending.error = error.message; }
  finally {
    pending.pending = false;
    if (review === pending) drawRows();
  }
}

async function saveText(index, value) {
  const job = current;
  if (isDemo()) {
    demo.rows[index] = {...demo.rows[index], text: value};
  } else {
    const result = await post(detailPath(job.id) + "/edit", {row: index, text: value});
    if (current?.id === job.id) current = result;
  }
}

async function commitEdit() {
  const action = editing;
  if (!action) return true;
  if (action.saving) return false;
  const value = action.input.value.trim();
  if (!value) {
    flash("请输入这段文字，或点取消。");
    action.input.focus();
    return false;
  }
  action.saving = true;
  try {
    await saveText(action.index, value);
    if (editing === action) editing = null;
    flash("修改已保存");
    return true;
  } catch (error) {
    flash(error.message);
    action.saving = false;
    return false;
  }
}

async function edit(index) {
  if (editing?.index === index) return;
  if (!(await commitEdit())) return;
  audio.pause();
  review = null;
  selected = index;
  editing = {index, input: null, saving: false};
  drawRows();
  editing.input.focus();
}

function rowEditor(row, content, actions) {
  const text = element("textarea", undefined, "editor");
  text.rows = 3;
  text.value = row.text;
  text.setAttribute("aria-label", "片段文字");
  editing.input = text;
  const save = async () => { if (await commitEdit()) drawRows(); };
  const cancel = () => { if (!editing?.saving) { editing = null; drawRows(); } };
  text.onkeydown = event => {
    if (event.key === "Escape") { event.preventDefault(); cancel(); }
    if (event.ctrlKey && event.key.toLowerCase() === "s") { event.preventDefault(); save(); }
  };
  content.append(text);
  actions.append(button("保存", save), button("取消", cancel));
}

function drawRows() {
  const nodes = current.rows.map((row, index) => {
    const line = element("div", undefined, "row" + (index === selected ? " active" : ""));
    const when = button(time(row.start), () => listen(index), "time");
    when.title = "回听本段";
    const content = element("div");
    const actions = element("div", undefined, "ops");
    if (editing?.index === index) {
      rowEditor(row, content, actions);
    } else {
      const text = element("p", row.text, "words");
      text.onclick = async () => {
        if (editing && !(await commitEdit())) return;
        if (review && review.index !== index) review = null;
        setActive(index);
        if (!$("rows").contains(text) || $("rows").querySelector(".editor") || $("rows").querySelector(".compare")) drawRows();
      };
      text.ondblclick = () => edit(index);
      content.append(text);
      actions.append(button("回听本段", () => listen(index)), button("修改文字", () => edit(index)));
      if (!isDemo()) actions.append(button("中文复核", () => compare(index)));
    }
    content.append(actions);
    if (review?.index === index) drawComparison(content, row, index);
    line.append(when, content);
    return line;
  });
  $("rows").replaceChildren(...nodes);
}

function showTask() {
  const box = $("task");
  box.replaceChildren();
  if (isDemo()) return;
  const job = current;
  const state = job.status;
  const messages = {ready: "文件已加入队列。", queued: "等待转写。"};
  const message = job.message || messages[state];
  if (!message && state !== "working") return;
  const row = element("div", undefined, "task-message");
  if (message) row.append(element("span", message));
  if (busyStates.has(state)) {
    const progress = element("progress", undefined, "progress");
    progress.max = 1;
    progress.value = job.progress;
    progress.setAttribute("aria-label", "当前转写进度");
    row.append(progress);
    if (state !== "stopping") row.append(button("停止", () => runAction("cancel"), "link"));
  } else if (state === "failed" || state === "cancelled") {
    row.append(button("重试此文件", () => startJobs([job.id]), "link"));
  }
  box.append(row);
}

function renderCurrent() {
  if (!current) return;
  const job = current;
  $("welcome").hidden = true;
  $("desk").hidden = false;
  $("name").textContent = job.name;
  $("crumb").textContent = "工作台 / 录音校对";
  $("meta").textContent = isDemo() ? "示例稿 · 合成朗读" :
    [stateNames[job.status], job.duration ? time(job.duration) : "", job.language ? "识别语言 " + job.language : ""].filter(Boolean).join(" · ");
  $("player").hidden = !job.duration;
  $("exportBox").hidden = !job.rows.length || job.status !== "done";
  $("state").textContent = job.rows.length ? job.rows.length + " 个片段" : "";
  $("note").textContent = isDemo() ? "点时间回听，双击文字修改。" : job.rows.length ? "点时间回听。可用中文复核对照当前文字。" : "";
  setAudio();
  syncAudio();
  showTask();
  if (!editing) drawRows();
  renderQueue();
}

async function openJob(id) {
  if (!(await commitEdit())) return;
  if (id === demo.id && !demo.rows) { flash("示例稿正在载入，请稍候。"); return; }
  const change = ++selection;
  try {
    const next = id === demo.id ? demo : await request(detailPath(id));
    if (change !== selection) return;
    current = next;
    review = null;
    selected = next.rows.length ? 0 : -1;
    hideExport();
    $("scroller").scrollTop = 0;
    $("player").classList.remove("compact");
    renderCurrent();
  } catch (error) { flash(error.message); }
}

async function showHome() {
  if (!(await commitEdit())) return;
  ++selection;
  current = null;
  review = null;
  setAudio();
  hideExport();
  $("exportBox").hidden = true;
  $("desk").hidden = true;
  $("welcome").hidden = false;
  $("crumb").textContent = "本地工作台";
  $("scroller").scrollTop = 0;
  renderQueue();
}

async function refresh(restore = false) {
  if (reading) return;
  reading = true;
  try {
    const next = await request("api/jobs");
    const changed = JSON.stringify(next) !== JSON.stringify(jobs);
    jobs = next;
    const summary = jobs.find(job => job.id === current?.id);
    if (restore && jobs.length && !current) await openJob(jobs.at(-1).id);
    else if (summary && summary.revision !== current.revision && !editing && !review) {
      const id = summary.id;
      const updated = await request(detailPath(id));
      if (current?.id === id && !editing && !review && updated.revision > current.revision) {
        current = updated;
        if (selected < 0 && current.rows.length) selected = 0;
        renderCurrent();
      }
    } else if (changed) renderQueue();
  } finally { reading = false; }
}

const refreshAfter = () => refresh().catch(error => flash(error.message));

async function runAction(action) {
  if (!current || isDemo()) return;
  try { await post(detailPath(current.id) + "/" + action); refreshAfter(); }
  catch (error) { flash(error.message); }
}

async function startJobs(ids) {
  if (!ids.length) return;
  try { await post("api/start", {ids, language: $("language").value}); refreshAfter(); }
  catch (error) { flash(error.message); }
}

async function onImported(added) {
  if (added.length) {
    await refreshAfter();
    await openJob(added[0].id);
  }
}

async function nativePick() {
  if (picking || !(await commitEdit())) return;
  if (!window.pywebview?.api?.choose_files) { $("picker").click(); return; }
  picking = true;
  try { await onImported(await window.pywebview.api.choose_files()); }
  catch (error) { flash(error.message || "无法导入文件。"); }
  finally { picking = false; }
}

async function importFiles(files) {
  if (picking || !(await commitEdit())) return;
  picking = true;
  const added = [];
  const errors = [];
  try {
    for (const file of files) {
      if (!/\.(mp3|wav|m4a|flac|aac|ogg|opus|mp4|mov|mkv|webm|avi|m4b|wma|aiff?)$/i.test(file.name)
          && !/^(audio|video)\//.test(file.type)) {
        errors.push(file.name + " 不属于支持的音视频格式");
        continue;
      }
      flash("正在导入 " + file.name);
      try {
        const job = await request("api/import", {
          method: "POST", body: file, headers: {"X-TingGao-Filename": encodeURIComponent(file.name)},
        });
        added.push(job);
      } catch (error) { errors.push(file.name + " · " + error.message); }
    }
    await onImported(added);
    if (errors.length) flash(errors.join("。"));
    else if (added.length) flash("已导入 " + added.length + " 个文件");
  } finally { picking = false; }
}

function srtTimestamp(seconds) {
  const total = Math.round(seconds * 1000);
  const pad = (number, width = 2) => String(number).padStart(width, "0");
  return pad(Math.floor(total / 3600000)) + ":" + pad(Math.floor(total / 60000) % 60)
    + ":" + pad(Math.floor(total / 1000) % 60) + "," + pad(total % 1000, 3);
}

async function saveFile(format) {
  if (!(await commitEdit()) || !current?.rows.length) return;
  hideExport();
  try {
    if (window.pywebview?.api?.save_as) {
      const saved = await window.pywebview.api.save_as(current.id, format, isDemo() ? current.rows : null);
      if (saved) flash("已导出 " + format.toUpperCase());
      return;
    }
    const content = current.rows.map((row, index) => format === "txt" ? row.text : [
      index + 1, srtTimestamp(row.start) + " --> " + srtTimestamp(row.end), row.text,
    ].join("\r\n")).join("\r\n\r\n");
    const file = new Blob([format === "txt" ? "\ufeff" : "", content], {type: "text/plain;charset=utf-8"});
    const link = element("a");
    link.href = URL.createObjectURL(file);
    link.download = current.name.replace(/\.[^.]+$/, "") + "." + format;
    link.click();
    setTimeout(() => URL.revokeObjectURL(link.href), 3000);
  } catch (error) { flash(error.message || "导出失败。"); }
}

audio.addEventListener("timeupdate", syncAudio);
audio.addEventListener("loadedmetadata", syncAudio);
audio.addEventListener("play", () => {
  $("play").classList.add("pause");
  $("play").setAttribute("aria-label", "暂停");
});
audio.addEventListener("pause", () => {
  $("play").classList.remove("pause");
  $("play").setAttribute("aria-label", "播放");
});
audio.addEventListener("playing", () => $("player").classList.add("is-playing"));
for (const event of ["pause", "waiting", "ended", "emptied", "error"]) {
  audio.addEventListener(event, () => $("player").classList.remove("is-playing"));
}

$("play").onclick = () => { endPlayback = null; audio.paused ? play() : audio.pause(); };
$("speed").onchange = () => { audio.playbackRate = Number($("speed").value); };
$("seek").oninput = () => {
  endPlayback = null;
  audio.currentTime = Number($("seek").value);
  syncAudio();
};
$("scroller").onscroll = () => $("player").classList.toggle("compact", $("scroller").scrollTop > 155);
$("home").onclick = showHome;
$("sample").onclick = () => openJob(demo.id);
$("addMain").onclick = nativePick;
$("addSide").onclick = nativePick;
$("picker").onchange = event => {
  importFiles(Array.from(event.target.files));
  event.target.value = "";
};
$("mobile").onchange = event => event.target.value === "home" ? showHome() : openJob(event.target.value);
$("begin").onclick = () => {
  const ready = jobs.filter(job => job.status === "ready");
  startJobs((ready.length ? ready : jobs.filter(job => startable.has(job.status))).map(job => job.id));
};
$("exportBtn").onclick = () => {
  $("menu").hidden = !$("menu").hidden;
  $("exportBtn").setAttribute("aria-expanded", String(!$("menu").hidden));
};
$("menu").onclick = event => { if (event.target.dataset.f) saveFile(event.target.dataset.f); };
document.addEventListener("click", event => { if (!event.target.closest(".exportBox")) hideExport(); });

window.addEventListener("dragover", event => {
  event.preventDefault();
  $("app").classList.add("drag");
});
window.addEventListener("dragleave", event => {
  if (!event.relatedTarget) $("app").classList.remove("drag");
});
window.addEventListener("drop", event => {
  event.preventDefault();
  $("app").classList.remove("drag");
  importFiles(Array.from(event.dataTransfer.files));
});

request("demo.json").then(data => { Object.assign(demo, data); paintIntro(); }).catch(error => flash(error.message));
refresh(true).catch(error => flash(error.message));
setInterval(() => { if (jobs.length) refreshAfter(); }, 850);

