const API = ""; // same origin
const $ = id => document.getElementById(id);

// [element id, settings key, type]. Same keys the server's RenderSettings uses.
const CONTROLS = [
  ["styleSelect", "style", "str"], ["paperSelect", "paper", "str"],
  ["paperColor", "paper_color", "str"], ["inkColor", "ink_color", "str"],
  ["imageMode", "image_mode", "str"],
  ["fontSize", "font_size", "num"], ["lineSpacing", "line_spacing", "num"],
  ["wordSpacing", "word_spacing", "num"], ["letterSpacing", "letter_spacing", "num"],
  ["paragraphGap", "paragraph_gap", "num"], ["indent", "first_line_indent_mm", "num"],
  ["alignSelect", "align", "str"], ["headingScale", "heading_scale", "num"],
  ["jitter", "jitter", "num"], ["pageSize", "page_size", "str"],
  ["marginTop", "margin_top_mm", "num"], ["marginBottom", "margin_bottom_mm", "num"],
  ["marginLeft", "margin_left_mm", "num"], ["marginRight", "margin_right_mm", "num"],
  ["imageWidth", "image_width_pct", "num"], ["pageNumbers", "page_numbers", "bool"],
];
const NOT_RESET = new Set(["styleSelect", "paperSelect", "paperColor", "inkColor"]);

let selectedFiles = [];          // ordered entries: { file, settings }
let currentJob = null;
let currentFileSettings = {};
let lastRenderedKey = null;      // text+settings that the preview currently shows
let seed = Math.floor(Math.random() * 1e6);
let toastTimer = null;

// ------------------------------------------------------- first-run setup
async function checkPrerequisites() {
  const status = $("setupStatus");
  const instructions = $("setupInstructions");
  const download = $("setupDownload");
  const checkButton = $("checkSetupBtn");
  const continueButton = $("continueSetupBtn");
  checkButton.disabled = true;
  continueButton.classList.add("hidden");
  status.textContent = "Checking this computer…";
  instructions.textContent = "";
  download.classList.add("hidden");

  try {
    const response = await fetch(`${API}/api/setup/status`);
    if (!response.ok) throw new Error("Could not check this computer.");
    const setup = await response.json();
    if (setup.ready) {
      status.textContent = `Tesseract OCR is ready on ${setup.platform}.`;
      continueButton.classList.remove("hidden");
    } else {
      status.textContent = `Tesseract OCR is not installed on ${setup.platform}.`;
      instructions.textContent = setup.install_instructions;
      download.href = setup.download_url;
      download.classList.remove("hidden");
    }
  } catch (error) {
    status.textContent = error.message || "Could not check this computer.";
    instructions.textContent = "Keep Handwritify open, then try the check again.";
  } finally {
    checkButton.disabled = false;
  }
}

$("checkSetupBtn").addEventListener("click", checkPrerequisites);
$("continueSetupBtn").addEventListener("click", () => {
  $("setupScreen").classList.add("hidden");
  $("authScreen").classList.remove("hidden");
});

// ------------------------------------------------------------ authentication
function showMainApp() {
  $("authScreen").classList.add("hidden");
  $("appHeader").classList.remove("hidden");
  $("mainApp").classList.remove("hidden");
  document.body.classList.add("authenticated");
}

async function submitLogin(event) {
  event.preventDefault();
  const username = $("username").value.trim();
  const password = $("password").value;
  const error = $("loginError");
  const button = $("loginButton");

  error.textContent = "";
  button.disabled = true;
  button.textContent = "Checking…";
  $("authScreen").classList.remove("login-failed");

  try {
    const response = await fetch(`${API}/api/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Unable to sign in.");
    showMainApp();
    loadStyles();
  } catch (e) {
    error.textContent = e.message || "The login service is unavailable.";
    $("authScreen").classList.add("login-failed");
    $("password").value = "";
    $("password").focus();
  } finally {
    button.disabled = false;
    button.textContent = "Open Handwritify";
  }
}

$("loginForm").addEventListener("submit", submitLogin);
$("togglePassword").addEventListener("click", () => {
  const input = $("password");
  const visible = input.type === "text";
  input.type = visible ? "password" : "text";
  $("togglePassword").textContent = visible ? "Show" : "Hide";
  $("togglePassword").setAttribute("aria-label", visible ? "Show password" : "Hide password");
});

// ------------------------------------------------------------ small helpers
function notify(msg) {
  const t = $("toast");
  t.textContent = msg;
  t.classList.remove("hidden");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.add("hidden"), 4000);
}

function setStatus(msg, isError = false) {
  const el = $("statusMsg");
  el.textContent = msg || "";
  el.classList.toggle("error", isError);
}

function readSettings() {
  const s = { seed };
  for (const [id, key, type] of CONTROLS) {
    const el = $(id);
    if (type === "bool") s[key] = el.checked;
    else if (type === "num") {
      const v = parseFloat(el.value);
      s[key] = Number.isNaN(v) ? parseFloat(el.defaultValue) : v;
    } else s[key] = el.value;
  }
  return s;
}

const currentKey = () => JSON.stringify([$("editor").value, readSettings()]);

async function errorText(res) {
  try {
    const body = await res.json();
    if (typeof body.detail === "string") return body.detail;
    return JSON.stringify(body.detail || body);
  } catch { return `Something went wrong (${res.status}).`; }
}

// Same rules as the server's strip_markup().
function stripMarkup(t) {
  return t.replace(/\r\n/g, "\n").split("\n")
    .filter(l => !/^\s*\[\[(IMG:[^\]]*|PAGEBREAK|STYLE:[^\]]*)\]\]\s*$/i.test(l))
    .map(l => l.replace(/^\s*#\s+/, ""))
    .join("\n").replace(/\n{3,}/g, "\n\n").trim();
}

// ---------------------------------------------------------------- settings UI
function syncLabels() {
  document.querySelectorAll('input[type="range"]').forEach(el => {
    const out = $(el.id + "Val");
    if (out) out.textContent = el.value + (el.dataset.unit || "");
  });
}
document.querySelectorAll('input[type="range"]').forEach(el => el.addEventListener("input", syncLabels));
syncLabels();
for (const id of ["styleSelect", "paperSelect", "imageMode", "paperColor"]) {
  $(id).addEventListener("change", renderFileList);
}
$("paperColor").addEventListener("input", renderFileList);
$("inkColor").addEventListener("input", renderFileList);

$("resetBtn").addEventListener("click", () => {
  for (const [id, , type] of CONTROLS) {
    if (NOT_RESET.has(id)) continue;
    const el = $(id);
    if (type === "bool") el.checked = el.defaultChecked;
    else if (el.tagName === "SELECT") el.selectedIndex = [...el.options].findIndex(o => o.defaultSelected);
    else el.value = el.defaultValue;
  }
  syncLabels();
  notify("Spacing and layout reset. Press Apply (or Convert) to use them.");
});

async function loadStyles() {
  try {
    const data = await (await fetch(`${API}/api/styles`)).json();
    $("styleSelect").innerHTML = data.fonts.length
      ? data.fonts.map(f => `<option value="${f}">${f}</option>`).join("")
      : `<option value="">(no fonts installed yet)</option>`;
    $("paperSelect").innerHTML = data.paper_styles
      .map(p => `<option value="${p.key}">${p.name}</option>`).join("");
    renderFileList();
    if (data.note) setStatus(data.note, true);
  } catch {
    setStatus("Can't reach the Handwritify server. Is it still running?", true);
  }
}
checkPrerequisites();

// ------------------------------------------------------ files (order matters)
const dropzone = $("dropzone");
dropzone.addEventListener("click", () => $("fileInput").click());
dropzone.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); $("fileInput").click(); } });
dropzone.addEventListener("dragover", e => { e.preventDefault(); dropzone.classList.add("dragover"); });
dropzone.addEventListener("dragleave", () => dropzone.classList.remove("dragover"));
dropzone.addEventListener("drop", e => { e.preventDefault(); dropzone.classList.remove("dragover"); addFiles(e.dataTransfer.files); });
$("fileInput").addEventListener("change", e => { addFiles(e.target.files); e.target.value = ""; });

function addFiles(list) {
  const ok = /\.(pdf|pptx|jpe?g|png)$/i;
  const rejected = [];
  for (const file of list) {
    if (ok.test(file.name)) selectedFiles.push({ file, overrides: {} });
    else rejected.push(file.name);
  }
  if (rejected.length) notify(`Skipped (unsupported type): ${rejected.join(", ")}`);
  renderFileList();
}

function moveFile(i, delta) {
  const j = i + delta;
  if (j < 0 || j >= selectedFiles.length) return;
  [selectedFiles[i], selectedFiles[j]] = [selectedFiles[j], selectedFiles[i]];
  renderFileList();
}

function renderFileList() {
  const ul = $("fileList");
  ul.innerHTML = "";
  selectedFiles.forEach((f, i) => {
    const li = document.createElement("li");
    const entry = selectedFiles[i];
    const name = document.createElement("span");
    name.className = "name";
    name.textContent = `${i + 1}. ${entry.file.name}`;
    li.appendChild(name);
    const addSelect = (key, options, title) => {
      const select = document.createElement("select");
      select.title = title;
      for (const [value, label] of options) {
        const option = document.createElement("option");
        option.value = value; option.textContent = label;
        select.appendChild(option);
      }
      select.value = entry.overrides[key] ?? readSettings()[key];
      select.addEventListener("change", () => { entry.overrides[key] = select.value; });
      li.appendChild(select);
    };
    addSelect("style", [...$("styleSelect").options].map(o => [o.value, o.textContent]), "Handwriting style for this file");
    addSelect("paper", [["ruled", "Ruled"], ["grid", "Grid"], ["blank", "Blank"]], "Paper for this file");
    const paperColor = document.createElement("input");
    paperColor.type = "color"; paperColor.value = entry.overrides.paper_color ?? readSettings().paper_color;
    paperColor.title = "Paper background color for this file";
    paperColor.setAttribute("aria-label", `Paper color for ${entry.file.name}`);
    paperColor.addEventListener("input", () => { entry.overrides.paper_color = paperColor.value; });
    li.appendChild(paperColor);
    const color = document.createElement("input");
    color.type = "color"; color.value = entry.overrides.ink_color ?? readSettings().ink_color;
    color.title = "Ink color for this file";
    color.addEventListener("input", () => { entry.overrides.ink_color = color.value; });
    li.appendChild(color);
    const fontSize = document.createElement("input");
    fontSize.type = "number"; fontSize.min = "20"; fontSize.max = "90"; fontSize.step = "1";
    fontSize.value = entry.overrides.font_size ?? readSettings().font_size;
    fontSize.title = "Text size for this file (px)";
    fontSize.setAttribute("aria-label", `Text size for ${entry.file.name}`);
    fontSize.addEventListener("change", () => {
      entry.overrides.font_size = Math.min(90, Math.max(20, Number(fontSize.value) || readSettings().font_size));
      fontSize.value = entry.overrides.font_size;
    });
    li.appendChild(fontSize);
    addSelect("image_mode", [["sketch", "Sketch"], ["ink", "Ink drawing"], ["grayscale", "B&W"], ["original", "Original"], ["skip", "No pictures"]], "Picture style for this file");
    const mk = (label, title, fn, disabled = false, cls = "") => {
      const b = document.createElement("button");
      b.type = "button"; b.textContent = label; b.title = title; b.disabled = disabled;
      if (cls) b.className = cls;
      b.addEventListener("click", fn);
      li.appendChild(b);
    };
    mk("↑", "Move up", () => moveFile(i, -1), i === 0);
    mk("↓", "Move down", () => moveFile(i, 1), i === selectedFiles.length - 1);
    mk("✕", "Remove", () => { selectedFiles.splice(i, 1); renderFileList(); }, false, "remove");
    ul.appendChild(li);
  });
}

// ------------------------------------------------------------------ convert
$("convertBtn").addEventListener("click", async () => {
  if (selectedFiles.length === 0) return setStatus("Add at least one file first.", true);
  if (!$("styleSelect").value) return setStatus("No handwriting font yet. Add a .ttf file to the fonts folder (see README) and refresh.", true);

  $("convertBtn").disabled = true;
  setStatus("Converting… photos and scans take a little longer.");
  const form = new FormData();
  selectedFiles.forEach(entry => form.append("files", entry.file));
  form.append("settings", JSON.stringify(readSettings()));
  const initialFileSettings = Object.fromEntries(selectedFiles.map((entry, i) => [
    `file_${i + 1}`, { ...readSettings(), ...entry.overrides },
  ]));
  currentFileSettings = Object.fromEntries(selectedFiles.map((entry, i) => [
    `file_${i + 1}`, { ...entry.overrides },
  ]));
  form.append("file_settings", JSON.stringify(initialFileSettings));

  try {
    const res = await fetch(`${API}/api/convert`, { method: "POST", body: form });
    if (!res.ok) throw new Error(await errorText(res));
    currentJob = await res.json();
    $("editor").value = currentJob.text;
    showJob(currentJob);
    lastRenderedKey = currentKey();
    $("resultSection").classList.remove("hidden");
    $("resultSection").scrollIntoView({ behavior: "smooth", block: "start" });
    setStatus(`Done: ${currentJob.page_count} page${currentJob.page_count === 1 ? "" : "s"}.`);
  } catch (e) {
    setStatus(e.message, true);
  } finally {
    $("convertBtn").disabled = false;
  }
});

function showJob(job) {
  const car = $("previewCarousel");
  car.innerHTML = "";
  job.previews.forEach((url, i) => {
    const img = document.createElement("img");
    img.src = url; img.alt = `Page ${i + 1}`; img.loading = "lazy";
    img.title = "Click to open full size";
    img.addEventListener("click", () => window.open(url, "_blank"));
    car.appendChild(img);
  });
  $("pageInfo").textContent = `${job.page_count} page${job.page_count === 1 ? "" : "s"}. Click a page to see it full size.`;

  const thumbs = $("imageThumbs");
  thumbs.innerHTML = "";
  job.images.forEach(im => {
    const b = document.createElement("button");
    b.type = "button"; b.title = `Insert ${im.id} at the cursor`;
    b.innerHTML = `<img src="${im.url}" alt="${im.id}" /><span>${im.id}</span>`;
    b.addEventListener("click", () => insertAtCursor(`\n\n[[IMG:${im.id}]]\n\n`));
    thumbs.appendChild(b);
  });
  $("imagePanel").classList.toggle("hidden", job.images.length === 0);
}

// ------------------------------------------------------------------- editing
function insertAtCursor(text) {
  const ed = $("editor");
  const s = ed.selectionStart, e = ed.selectionEnd;
  ed.value = ed.value.slice(0, s) + text + ed.value.slice(e);
  const pos = s + text.length;
  ed.setSelectionRange(pos, pos);
  ed.focus();
}

$("editor").addEventListener("paste", async event => {
  const imageItem = [...(event.clipboardData?.items || [])].find(item => item.type.startsWith("image/"));
  if (!imageItem) return;
  event.preventDefault();
  if (!currentJob) return notify("Convert a document before pasting an image.");
  const image = imageItem.getAsFile();
  if (!image) return notify("The clipboard image could not be read.");
  const form = new FormData();
  form.append("file", image, "pasted-image");
  try {
    const res = await fetch(`${API}/api/image/${currentJob.job_id}`, { method: "POST", body: form });
    if (!res.ok) throw new Error(await errorText(res));
    const added = await res.json();
    currentJob.images.push(added);
    showJob(currentJob);
    insertAtCursor(`\n\n[[IMG:${added.id}|${readSettings().image_width_pct}]]\n\n`);
    notify("Image added. Apply changes to see it on the page.");
  } catch (error) {
    notify(`Could not add image: ${error.message}`);
  }
});

$("pageBreakBtn").addEventListener("click", () => insertAtCursor("\n\n[[PAGEBREAK]]\n\n"));

$("headingBtn").addEventListener("click", () => {
  const ed = $("editor");
  const pos = ed.selectionStart;
  const start = pos === 0 ? 0 : ed.value.lastIndexOf("\n", pos - 1) + 1;
  if (ed.value.startsWith("# ", start)) {
    ed.value = ed.value.slice(0, start) + ed.value.slice(start + 2);
    ed.setSelectionRange(Math.max(start, pos - 2), Math.max(start, pos - 2));
  } else {
    ed.value = ed.value.slice(0, start) + "# " + ed.value.slice(start);
    ed.setSelectionRange(pos + 2, pos + 2);
  }
  ed.focus();
});

async function rerender(newSeed = false) {
  if (!currentJob) return false;
  if (newSeed) seed = Math.floor(Math.random() * 1e6);
  $("applyBtn").disabled = true; $("shuffleBtn").disabled = true;
  notify("Redrawing pages…");
  try {
    const res = await fetch(`${API}/api/rerender/${currentJob.job_id}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        text: $("editor").value,
        settings: readSettings(),
        file_settings: Object.fromEntries(Object.entries(currentFileSettings).map(([id, overrides]) => [
          id, { ...readSettings(), ...overrides },
        ])),
      }),
    });
    if (!res.ok) throw new Error(await errorText(res));
    currentJob = await res.json();     // note: the editor keeps what you typed
    showJob(currentJob);
    lastRenderedKey = currentKey();
    notify(`Updated: ${currentJob.page_count} page${currentJob.page_count === 1 ? "" : "s"}.`);
    return true;
  } catch (e) {
    notify(`Could not apply changes: ${e.message}`);
    return false;
  } finally {
    $("applyBtn").disabled = false; $("shuffleBtn").disabled = false;
  }
}
$("applyBtn").addEventListener("click", () => rerender(false));
$("shuffleBtn").addEventListener("click", () => rerender(true));

// If there are edits/setting changes the preview doesn't show yet, apply them first
// so downloads and shares always match what's on screen after the click.
async function ensureRendered() {
  if (!currentJob) return false;
  if (currentKey() !== lastRenderedKey) return rerender(false);
  return true;
}

// ---------------------------------------------------- copy / download / share
async function copyToClipboard(text) {
  if (navigator.clipboard && window.isSecureContext) {
    await navigator.clipboard.writeText(text);
  } else {
    const ta = document.createElement("textarea");
    ta.value = text; document.body.appendChild(ta); ta.select();
    document.execCommand("copy"); ta.remove();
  }
}

$("copyBtn").addEventListener("click", async () => {
  if (!currentJob) return;
  try { await copyToClipboard(stripMarkup($("editor").value)); notify("Text copied."); }
  catch { notify("Couldn't copy. Select the text in the editor and copy it manually."); }
});

async function download(fmt) {
  if (!(await ensureRendered())) return;
  window.location.href = `${API}/api/download/${currentJob.job_id}?fmt=${fmt}`;
}
$("downloadPdfBtn").addEventListener("click", () => download("pdf"));
$("downloadDocxBtn").addEventListener("click", () => download("docx"));

$("shareBtn").addEventListener("click", async () => {
  if (!(await ensureRendered())) return;
  const text = stripMarkup($("editor").value);
  try {
    const blob = await (await fetch(`${API}/api/download/${currentJob.job_id}?fmt=pdf`)).blob();
    const file = new File([blob], "handwritten.pdf", { type: "application/pdf" });
    if (navigator.canShare && navigator.canShare({ files: [file] })) {
      await navigator.share({ files: [file], title: "Handwritten notes" });
    } else if (navigator.share) {
      await navigator.share({ title: "Handwritten notes", text: text.slice(0, 500) });
    } else {
      await copyToClipboard(text);
      notify("This browser can't share directly. The text was copied; use Download PDF for the file.");
    }
  } catch (e) {
    if (e.name !== "AbortError") notify(`Share failed: ${e.message}`);
  }
});
