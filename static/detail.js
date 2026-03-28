// detail.js — logika pro stránku detailu zápisu
// Proměnné ZAPIS_ID, KLIENT_TASKLIST_ID, KLIENT_ID jsou definovány inline v šabloně

document.addEventListener("DOMContentLoaded", function() {
  applyScoreBadges();
  if (KLIENT_TASKLIST_ID) {
    loadMembersForFixed();
  } else {
    loadProjects();
  }
  updateCount();
  document.querySelectorAll(".task-checkbox").forEach(function(cb) {
    cb.addEventListener("change", updateCount);
  });
  document.querySelectorAll(".task-row").forEach(function(r) {
    populateAD(r.querySelector(".task-assignee"));
  });
  document.addEventListener("click", function(e) {
    if (!e.target.closest(".asgn-wrap")) {
      document.querySelectorAll(".asgn-dd.open").forEach(function(d) {
        d.classList.remove("open");
      });
    }
    ["modal-new-list", "modal-task-detail"].forEach(function(id) {
      if (e.target === document.getElementById(id)) closeModal(id);
    });
  });
});

async function loadMembersForFixed() {
  try {
    if (KLIENT_ID) {
      const dm = await fetch("/api/klient/" + KLIENT_ID + "/freelo-members").then(function(r) { return r.json(); });
      freeloMembers = dm.members || [];
      document.querySelectorAll(".task-assignee,#detail-assignee").forEach(populateAD);
    }
    const dp = await fetch("/api/freelo/projects").then(function(r) { return r.json(); });
    freeloProjects = dp.projects || [];
    if (!KLIENT_ID) {
      let pid = null;
      for (const p of freeloProjects) {
        for (const tl of (p.tasklists || [])) {
          if (String(tl.id) === String(KLIENT_TASKLIST_ID)) { pid = p.id; break; }
        }
        if (pid) break;
      }
      if (pid) await loadMembers(pid);
    }
  } catch(e) {}
  updateCount();
}

function applyScoreBadges() {
  document.querySelectorAll(".section-content td").forEach(function(td) {
    const txt = td.textContent.trim();
    const m = txt.match(/^(\d+)\s*%?$/);
    if (m && parseInt(m[1]) <= 100 && txt.length <= 5) {
      const p = parseInt(m[1]);
      let bg = "#FF383C";
      if (p >= 70) bg = "#34C759";
      else if (p >= 55) bg = "#00AFF0";
      else if (p >= 40) bg = "#FF8D00";
      td.innerHTML = '<span class="score-badge" style="background:' + bg + '">' + p + '%</span>';
    }
  });
}

function toast(msg, ok) {
  if (ok === undefined) ok = true;
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.style.background = ok ? "#173767" : "#C0392B";
  t.classList.add("show");
  setTimeout(function() { t.classList.remove("show"); }, 2500);
}

function downloadPDF() {
  document.querySelectorAll(".print-header,.print-footer").forEach(function(el) {
    el.style.display = "flex";
  });
  window.print();
  setTimeout(function() {
    document.querySelectorAll(".print-header,.print-footer").forEach(function(el) {
      el.style.display = "none";
    });
  }, 1000);
}

function fmt(key, cmd) { document.execCommand(cmd, false, null); }

function insertTable(key) {
  const ed = document.getElementById("editor-" + key);
  ed.focus();
  document.execCommand("insertHTML", false,
    "<table><tr><th>Oblast</th><th>%</th><th>Komentář</th></tr>" +
    "<tr><td>Název</td><td>50</td><td>Popis</td></tr>" +
    "<tr><td>Další oblast</td><td>70</td><td>Popis</td></tr></table>"
  );
}

function startEdit(key) {
  const content = document.getElementById("content-" + key);
  const ed = document.getElementById("editor-" + key);
  if (!content || !ed) return;
  ed.innerHTML = content.innerHTML;
  content.style.display = "none";
  document.getElementById("edit-wrap-" + key).classList.add("active");
  const aiBar = document.getElementById("ai-bar-" + key);
  if (aiBar) aiBar.classList.remove("active");
  ed.focus();
  const range = document.createRange();
  const sel = window.getSelection();
  range.selectNodeContents(ed);
  range.collapse(false);
  sel.removeAllRanges();
  sel.addRange(range);
}

function cancelEdit(key) {
  const content = document.getElementById("content-" + key);
  const wrap = document.getElementById("edit-wrap-" + key);
  if (content) content.style.display = "";
  if (wrap) wrap.classList.remove("active");
}

async function saveSection(key) {
  const html = document.getElementById("editor-" + key).innerHTML.trim();
  try {
    const r = await fetch("/api/zapis/" + ZAPIS_ID + "/sekce", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ key: key, html: html })
    });
    const d = await r.json();
    if (d.ok) {
      document.getElementById("content-" + key).innerHTML = html;
      cancelEdit(key);
      applyScoreBadges();
      toast("Uloženo");
    } else {
      toast("Chyba: " + (d.error || "?"), false);
    }
  } catch(e) {
    toast("Chyba: " + e.message, false);
  }
}

function toggleAiBar(key) {
  const bar = document.getElementById("ai-bar-" + key);
  if (!bar) return;
  const isOpen = bar.classList.contains("active");
  document.querySelectorAll(".ai-bar.active").forEach(function(b) { b.classList.remove("active"); });
  if (!isOpen) {
    bar.classList.add("active");
    const input = document.getElementById("ai-input-" + key);
    if (input) input.focus();
  }
}

async function runAi(key) {
  const input = document.getElementById("ai-input-" + key);
  const prompt = input.value.trim();
  if (!prompt) { input.focus(); return; }
  const content = document.getElementById("content-" + key);
  input.disabled = true;
  const origPlaceholder = input.placeholder;
  input.placeholder = "Pracuji...";
  try {
    const r = await fetch("/api/zapis/" + ZAPIS_ID + "/ai-sekce", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ key: key, prompt: prompt, html: content.innerHTML })
    });
    const d = await r.json();
    if (d.ok && d.html) {
      content.innerHTML = d.html;
      applyScoreBadges();
      await fetch("/api/zapis/" + ZAPIS_ID + "/sekce", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key: key, html: d.html })
      });
      input.value = "";
      toggleAiBar(key);
      toast("AI úprava uložena");
    } else {
      toast("Chyba: " + (d.error || "?"), false);
    }
  } catch(e) {
    toast("Chyba: " + e.message, false);
  } finally {
    input.disabled = false;
    input.placeholder = origPlaceholder;
  }
}

async function togglePublish() {
  const btn = document.getElementById("pub-btn");
  const isPublic = btn.classList.contains("btn-success");
  try {
    const d = await fetch("/api/zapis/" + ZAPIS_ID + "/publikovat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ publish: !isPublic })
    }).then(function(r) { return r.json(); });
    if (d.ok) {
      if (d.is_public) {
        btn.className = "btn btn-success btn-sm";
        btn.innerHTML = "&#x1F30D; Zveřejněno";
        let bar = document.getElementById("pub-bar-wrap");
        if (!bar) {
          bar = document.createElement("div");
          bar.id = "pub-bar-wrap";
          bar.style.cssText = "background:#E2F5EE;border:1px solid #0A7A5A;border-radius:5px;padding:9px 14px;margin-bottom:1rem;font-size:12px;display:flex;align-items:center;gap:10px;flex-wrap:wrap;";
          bar.innerHTML = '<span style="color:#0A7A5A;font-weight:700;">&#x1F30D; Veřejný odkaz:</span>' +
            '<a id="pub-link" href="' + d.url + '" target="_blank" style="color:#0A7A5A;word-break:break-all;flex:1;">' + d.url + '</a>' +
            '<button onclick="copyPubLink()" class="btn btn-secondary btn-sm">Kopírovat</button>';
          document.querySelector(".card-actions").insertAdjacentElement("afterend", bar);
        }
        toast("Zápis je nyní veřejný");
      } else {
        btn.className = "btn btn-secondary btn-sm";
        btn.innerHTML = "Zveřejnit";
        const bar = document.getElementById("pub-bar-wrap");
        if (bar) bar.remove();
        toast("Zápis je nyní soukromý");
      }
    }
  } catch(e) {
    toast("Chyba: " + e.message, false);
  }
}

function copyPubLink() {
  navigator.clipboard.writeText(document.getElementById("pub-link").href);
  toast("Odkaz zkopírován");
}

async function loadProjects() {
  try {
    const d = await fetch("/api/freelo/projects").then(function(r) { return r.json(); });
    freeloProjects = d.projects || [];
    const sel = document.getElementById("project-select");
    const nlp = document.getElementById("new-list-project");
    if (!freeloProjects.length) { sel.innerHTML = '<option value="">Žádné projekty</option>'; return; }
    const opts = freeloProjects.map(function(p) {
      return '<option value="' + p.id + '">' + p.name + '</option>';
    }).join("");
    sel.innerHTML = opts;
    if (nlp) nlp.innerHTML = opts;
    onProjectChange();
    loadMembers(freeloProjects[0] && freeloProjects[0].id);
  } catch(e) {
    const sel = document.getElementById("project-select");
    if (sel) sel.innerHTML = '<option value="">Chyba</option>';
  }
  updateCount();
}

function onProjectChange() {
  const pid = document.getElementById("project-select").value;
  const proj = freeloProjects.find(function(p) { return String(p.id) === String(pid); });
  const sel = document.getElementById("tasklist-select");
  if (!proj) { sel.innerHTML = '<option value="">— vyberte projekt —</option>'; return; }
  sel.innerHTML = (proj.tasklists || []).length
    ? proj.tasklists.map(function(tl) { return '<option value="' + tl.id + '">' + tl.name + '</option>'; }).join("")
    : '<option value="">Žádné listy</option>';
  loadMembers(pid);
}

async function loadMembers(pid) {
  if (!pid) return;
  try {
    const d = await fetch("/api/freelo/members/" + pid).then(function(r) { return r.json(); });
    freeloMembers = d.members || [];
    document.querySelectorAll(".task-assignee,#detail-assignee").forEach(populateAD);
  } catch(e) {}
}

function populateAD(input) {
  if (!input) return;
  const wrap = input.closest(".asgn-wrap");
  if (!wrap) return;
  let dd = wrap.querySelector(".asgn-dd");
  if (!dd) {
    dd = document.createElement("div");
    dd.className = "asgn-dd";
    wrap.appendChild(dd);
  }
  renderAD(dd, input);
}

function renderAD(dd, input) {
  const q = (input.value || "").toLowerCase();
  const members = freeloMembers.filter(function(m) {
    return m.name.toLowerCase().includes(q) || (m.email || "").toLowerCase().includes(q);
  });
  dd.innerHTML = members.length
    ? members.map(function(m) {
        return '<div class="asgn-opt" onclick="pickAsgn(this,' + JSON.stringify(m.name) + ')">' +
               '<strong>' + m.name + '</strong>' +
               '<span style="color:#4A6080;font-size:11px;margin-left:6px;">' + (m.email || "") + '</span>' +
               '</div>';
      }).join("")
    : '<div class="asgn-opt" style="color:#4A6080;font-style:italic;">Žádné výsledky</div>';
}

function openAD(input) {
  populateAD(input);
  const dd = input.closest(".asgn-wrap") && input.closest(".asgn-wrap").querySelector(".asgn-dd");
  if (dd) dd.classList.add("open");
}

function filterAD(input) {
  const dd = input.closest(".asgn-wrap") && input.closest(".asgn-wrap").querySelector(".asgn-dd");
  if (dd) { renderAD(dd, input); dd.classList.add("open"); }
}

function pickAsgn(opt, name) {
  const w = opt.closest(".asgn-wrap");
  if (w && w.querySelector("input")) w.querySelector("input").value = name;
  const dd = w && w.querySelector(".asgn-dd");
  if (dd) dd.classList.remove("open");
}

function selectAllTasks(v) {
  document.querySelectorAll(".task-checkbox").forEach(function(cb) { cb.checked = v; });
  updateCount();
}

function updateCount() {
  const t = document.querySelectorAll(".task-checkbox").length;
  const s = document.querySelectorAll(".task-checkbox:checked").length;
  const el = document.getElementById("task-count-label");
  if (el) el.textContent = s + " z " + t + " úkolů vybráno";
}

function addTaskRow() {
  const c = document.getElementById("tasks-list-container");
  const nm = document.getElementById("no-tasks-msg");
  if (nm) nm.remove();
  const idx = nextIdx++;
  const row = document.createElement("div");
  row.className = "task-row freelo-task-row";
  row.dataset.idx = idx;
  row.innerHTML =
    '<div style="padding-top:4px;"><input type="checkbox" class="task-checkbox" checked style="width:16px;height:16px;accent-color:#00AFF0;cursor:pointer;margin:0;"></div>' +
    '<div><input type="text" class="task-name-input fl-in" placeholder="Název úkolu..." style="font-size:13px;font-weight:600;margin-bottom:4px;"></div>' +
    '<div class="asgn-wrap"><input type="text" class="task-assignee fl-in" placeholder="Vybrat..." autocomplete="off" onfocus="openAD(this)" oninput="filterAD(this)" style="cursor:pointer;"><div class="asgn-dd"></div></div>' +
    '<input type="date" class="task-deadline fl-in">' +
    '<button onclick="openDetail(this)" title="Detail" style="background:none;border:1.5px solid var(--border);border-radius:4px;width:32px;height:32px;cursor:pointer;font-size:16px;color:#4A6080;">&#x22EF;</button>';
  c.appendChild(row);
  row.querySelector(".task-checkbox").addEventListener("change", updateCount);
  populateAD(row.querySelector(".task-assignee"));
  row.querySelector(".task-name-input").focus();
  updateCount();
}

function closeModal(id) {
  const el = document.getElementById(id);
  if (el) el.classList.remove("open");
  if (id === "modal-task-detail") activeRow = null;
}

function openNewListModal() {
  document.getElementById("modal-new-list").classList.add("open");
  setTimeout(function() { document.getElementById("new-list-name").focus(); }, 50);
}

async function createNewList() {
  const name = document.getElementById("new-list-name").value.trim();
  const pid = document.getElementById("new-list-project").value;
  if (!name || !pid) { toast("Vyplňte název a vyberte projekt", false); return; }
  const btn = document.getElementById("create-list-btn");
  btn.disabled = true;
  btn.textContent = "Vytvářím...";
  try {
    const d = await fetch("/api/freelo/create-tasklist", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: name, project_id: pid })
    }).then(function(r) { return r.json(); });
    if (d.id) {
      const proj = freeloProjects.find(function(p) { return String(p.id) === String(pid); });
      if (proj) { proj.tasklists = proj.tasklists || []; proj.tasklists.push({ id: d.id, name: d.name }); }
      document.getElementById("project-select").value = pid;
      onProjectChange();
      document.getElementById("tasklist-select").value = d.id;
      closeModal("modal-new-list");
      toast("List vytvořen");
    } else {
      toast("Chyba: " + (d.error || "?"), false);
    }
  } catch(e) {
    toast("Chyba: " + e.message, false);
  } finally {
    btn.disabled = false;
    btn.textContent = "Vytvořit";
  }
}

function openDetail(btn) {
  activeRow = btn.closest(".freelo-task-row");
  document.getElementById("detail-name").value = (activeRow.querySelector(".task-name-input") || {}).value || "";
  document.getElementById("detail-assignee").value = (activeRow.querySelector(".task-assignee") || {}).value || "";
  document.getElementById("detail-deadline").value = (activeRow.querySelector(".task-deadline") || {}).value || "";
  const d = activeRow.querySelector(".task-desc-text");
  document.getElementById("detail-desc").value = d ? (d.innerHTML || d.value || d.textContent || "").trim() : "";
  populateAD(document.getElementById("detail-assignee"));
  document.getElementById("modal-task-detail").classList.add("open");
}

function saveDetail() {
  if (!activeRow) return;
  const ni = activeRow.querySelector(".task-name-input");
  if (ni) ni.value = document.getElementById("detail-name").value;
  const ai2 = activeRow.querySelector(".task-assignee");
  if (ai2) ai2.value = document.getElementById("detail-assignee").value;
  const di = activeRow.querySelector(".task-deadline");
  if (di) di.value = document.getElementById("detail-deadline").value;
  closeModal("modal-task-detail");
}

async function odeslatDoFreela() {
  const btn = document.getElementById("freelo-send-btn");
  const tlEl = document.getElementById("tasklist-select");
  const tlId = KLIENT_TASKLIST_ID || (tlEl && tlEl.value) || null;
  if (!tlId) { toast("Vyberte To-Do list", false); return; }
  const sel = [];
  document.querySelectorAll(".task-checkbox:checked").forEach(function(cb) {
    const row = cb.closest(".freelo-task-row");
    if (!row) return;
    const name = ((row.querySelector(".task-name-input") || {}).value || "").trim();
    if (!name) return;
    const de = row.querySelector(".task-desc-text");
    sel.push({
      name: name,
      desc: (de ? (de.innerHTML || de.value || de.textContent) : "").trim(),
      assignee: ((row.querySelector(".task-assignee") || {}).value || "").trim(),
      deadline: ((row.querySelector(".task-deadline") || {}).value || "").trim()
    });
  });
  if (!sel.length) { toast("Vyberte alespoň jeden úkol", false); return; }
  btn.disabled = true;
  btn.innerHTML = '<span style="display:inline-block;width:12px;height:12px;border:2px solid rgba(255,255,255,0.3);border-top-color:white;border-radius:50%;animation:spin 0.7s linear infinite;margin-right:6px;vertical-align:middle"></span>Odesílám ' + sel.length + ' úkolů...';
  try {
    const d = await fetch("/api/freelo/" + ZAPIS_ID, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tasks: sel, tasklist_id: tlId })
    }).then(function(r) { return r.json(); });
    if (d.created && d.created.length > 0) {
      document.getElementById("freelo-result").innerHTML =
        '<div style="background:#E2F5EE;border:1px solid #0A7A5A;border-radius:5px;padding:10px 14px;font-size:13px;color:#0A7A5A;font-weight:600;">&#x2713; Odesláno ' + d.created.length + ' úkolů do Freela</div>';
      btn.style.background = "#0A7A5A";
      btn.innerHTML = "&#x2713; Odesláno";
    } else {
      document.getElementById("freelo-result").innerHTML =
        '<div style="background:#FCEAEA;border:1px solid #C0392B;border-radius:5px;padding:10px 14px;font-size:13px;color:#C0392B;">Chyba: ' + ((d.errors || []).join(", ") || d.error || "Neznámá chyba") + '</div>';
      btn.disabled = false;
      btn.innerHTML = "Odeslat vybrané do Freela &rarr;";
    }
  } catch(e) {
    toast("Chyba: " + e.message, false);
    btn.disabled = false;
    btn.innerHTML = "Odeslat vybrané do Freela &rarr;";
  }
}
