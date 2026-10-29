"use strict";

const API = "/api";
const state = { learners: [], current: null };

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

async function req(method, path, body) {
  const opts = { method, headers: { "Content-Type": "application/json" } };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const res = await fetch(API + path, opts);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail ?? data);
    } catch (_) {}
    throw new Error(detail);
  }
  return res.status === 204 ? null : res.json();
}

function toast(msg, kind = "info") {
  const el = $("#toast");
  el.textContent = msg;
  el.className = "toast show " + kind;
  setTimeout(() => (el.className = "toast"), 2600);
}

function notice(msg) {
  const el = $("#notice");
  el.hidden = !msg;
  el.textContent = msg || "";
}

// ----------------------------------------------------------------- tabs
$$(".tab").forEach((btn) =>
  btn.addEventListener("click", () => {
    $$(".tab").forEach((b) => b.classList.remove("active"));
    $$(".panel").forEach((p) => p.classList.remove("active"));
    btn.classList.add("active");
    $("#" + btn.dataset.tab).classList.add("active");
    renderTab(btn.dataset.tab);
  })
);

// ----------------------------------------------------------------- learners
async function loadLearners() {
  state.learners = await req("GET", "/learners");
  const sel = $("#learnerSelect");
  sel.innerHTML = "";
  if (state.learners.length === 0) {
    const opt = document.createElement("option");
    opt.value = "";
    opt.textContent = "(暂无学习者,请先添加)";
    sel.appendChild(opt);
    state.current = null;
    notice("还没有学习者。请在上方填写学习者ID与名称,点击“添加学习者”。");
  } else {
    for (const l of state.learners) {
      const opt = document.createElement("option");
      opt.value = l.learner_id;
      opt.textContent = `${l.name} (${l.learner_id})`;
      sel.appendChild(opt);
    }
    if (!state.current || !state.learners.some((l) => l.learner_id === state.current)) {
      state.current = state.learners[0].learner_id;
    }
    sel.value = state.current;
    notice("");
  }
}

$("#learnerSelect").addEventListener("change", (e) => {
  state.current = e.target.value;
  renderActiveTab();
});

$("#addLearnerBtn").addEventListener("click", async () => {
  const learner_id = $("#newLearnerId").value.trim();
  const name = $("#newLearnerName").value.trim();
  if (!learner_id || !name) return toast("学习者ID和名称都不能为空", "error");
  try {
    await req("POST", "/learners", { learner_id, name });
    $("#newLearnerId").value = "";
    $("#newLearnerName").value = "";
    state.current = learner_id;
    await loadLearners();
    renderActiveTab();
    toast("已添加学习者:" + name, "ok");
  } catch (err) {
    toast("添加失败:" + err.message, "error");
  }
});

function activeTab() {
  return $(".tab.active").dataset.tab;
}
function renderActiveTab() {
  renderTab(activeTab());
}

// ----------------------------------------------------------------- renderers
async function renderTab(tab) {
  if (tab === "overview") return renderOverview();
  if (tab === "profile") return renderProfile();
  if (tab === "records") return renderRecords();
  if (tab === "plan") return renderPlan();
  if (tab === "memory") return renderMemory();
}

async function renderOverview() {
  if (!state.current) return ($("#overviewCards").innerHTML = empty("请先添加并选择学习者。"));
  try {
    const o = await req("GET", `/learners/${state.current}/overview`);
    $("#overviewCards").innerHTML = `
      <div class="card"><div class="k">记录总数</div><div class="v">${o.record_count}</div></div>
      <div class="card"><div class="k">掌握良好(≥4)</div><div class="v good">${o.mastered_count}</div></div>
      <div class="card"><div class="k">薄弱(≤2)</div><div class="v weak">${o.weak_count}</div></div>
      <div class="card"><div class="k">今日到期</div><div class="v">${o.due_count}</div></div>
      <div class="card"><div class="k">每日时间预算</div><div class="v">${o.daily_minutes} <span class="u">分钟</span></div></div>
      <div class="card"><div class="k">学习偏好</div><div class="v">${o.has_preference ? "已设置" : "未设置"}</div></div>
    `;
  } catch (err) {
    $("#overviewCards").innerHTML = empty("读取失败:" + err.message);
  }
}

async function renderProfile() {
  if (!state.current) return;
  try {
    const { preference } = await req("GET", `/learners/${state.current}/preference`);
    if (preference) {
      $("#dailyMinutes").value = preference.daily_minutes;
      $("#goal").value = preference.goal || "";
      $("#preferences").value = preference.preferences || "";
    }
  } catch (err) {
    toast("读取偏好失败:" + err.message, "error");
  }
}

$("#prefForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!state.current) return toast("请先选择学习者", "error");
  const body = {
    daily_minutes: Number($("#dailyMinutes").value),
    goal: $("#goal").value,
    preferences: $("#preferences").value,
  };
  try {
    await req("PUT", `/learners/${state.current}/preference`, body);
    $("#prefMsg").textContent = "偏好已保存到 PowerContext,复习清单将立即采用。";
    $("#prefMsg").className = "msg ok";
    toast("偏好已保存", "ok");
  } catch (err) {
    $("#prefMsg").textContent = "保存失败:" + err.message;
    $("#prefMsg").className = "msg error";
  }
});

async function renderRecords() {
  if (!state.current) return ($("#recordsTable").innerHTML = empty("请先选择学习者。"));
  try {
    const { records } = await req("GET", `/learners/${state.current}/records`);
    if (records.length === 0) return ($("#recordsTable").innerHTML = empty("还没有学习记录。"));
    $("#recordsTable").innerHTML =
      head(["课程", "知识点", "笔记", "掌握度", "学习日期", "上次复习", "复习次数", "操作"]) +
      records
        .map(
          (r) => `<tr>
        <td>${esc(r.course)}</td><td>${esc(r.topic)}</td><td>${esc(r.note || "")}</td>
        <td>${r.mastery}/5</td><td>${r.studied_on || "-"}</td><td>${r.last_review || "未复习"}</td>
        <td>${r.review_count}</td>
        <td><button class="ghost sm" data-topic="${esc(r.topic)}" data-q="5">记住了</button>
            <button class="ghost sm" data-topic="${esc(r.topic)}" data-q="3">模糊</button>
            <button class="ghost sm danger" data-topic="${esc(r.topic)}" data-q="1">忘了</button></td>
      </tr>`
        )
        .join("");
    $$("#recordsTable button[data-topic]").forEach((b) =>
      b.addEventListener("click", async () => {
        const today = new Date().toISOString().slice(0, 10);
        try {
          await req("POST", `/learners/${state.current}/review-result`, {
            topic: b.dataset.topic,
            quality: Number(b.dataset.q),
            review_date: today,
          });
          toast(`已回写「${b.dataset.topic}」复习结果`, "ok");
          renderRecords();
        } catch (err) {
          toast("回写失败:" + err.message, "error");
        }
      })
    );
  } catch (err) {
    $("#recordsTable").innerHTML = empty("读取失败:" + err.message);
  }
}

$("#recordForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!state.current) return toast("请先选择学习者", "error");
  const body = {
    course: $("#course").value.trim(),
    topic: $("#topic").value.trim(),
    note: $("#note").value,
    mastery: Number($("#mastery").value),
    studied_on: $("#studiedOn").value || null,
  };
  try {
    await req("POST", `/learners/${state.current}/records`, body);
    $("#recordMsg").textContent = "记录已保存到 PowerContext(相同内容重复提交不会产生重复记录)。";
    $("#recordMsg").className = "msg ok";
    $("#recordForm").reset();
    $("#mastery").value = 2;
    renderRecords();
  } catch (err) {
    $("#recordMsg").textContent = "保存失败:" + err.message;
    $("#recordMsg").className = "msg error";
  }
});

async function renderPlan() {
  if (!state.current) {
    $("#planSummary").innerHTML = "";
    return ($("#planTable").innerHTML = empty("请先选择学习者。"));
  }
  try {
    const p = await req("GET", `/learners/${state.current}/review-plan`);
    $("#planSummary").innerHTML = `生成日期 ${p.generated_on} · 预算 ${p.daily_minutes} 分钟 · 已用 ${p.total_est_minutes} 分钟 · ${p.items.length} 条<br><span class="muted">${esc(p.note)}</span>`;
    if (p.items.length === 0) return ($("#planTable").innerHTML = empty("当前没有到期的复习项。"));
    $("#planTable").innerHTML =
      head(["优先级", "知识点", "课程", "掌握度", "推荐理由", "预计分钟", "复习"]) +
      p.items
        .map(
          (it, i) => `<tr>
        <td>${i + 1}</td><td>${esc(it.topic)}</td><td>${esc(it.course)}</td>
        <td>${it.mastery}/5</td><td>${esc(it.reason)}</td><td>${it.est_minutes}</td>
        <td><button class="ghost sm" data-topic="${esc(it.topic)}" data-q="5">记住了</button>
            <button class="ghost sm" data-topic="${esc(it.topic)}" data-q="3">模糊</button>
            <button class="ghost sm danger" data-topic="${esc(it.topic)}" data-q="1">忘了</button></td>
      </tr>`
        )
        .join("");
    $$("#planTable button[data-topic]").forEach((b) =>
      b.addEventListener("click", async () => {
        const today = new Date().toISOString().slice(0, 10);
        try {
          await req("POST", `/learners/${state.current}/review-result`, {
            topic: b.dataset.topic,
            quality: Number(b.dataset.q),
            review_date: today,
          });
          toast(`已回写「${b.dataset.topic}」`, "ok");
          renderPlan();
        } catch (err) {
          toast("回写失败:" + err.message, "error");
        }
      })
    );
  } catch (err) {
    $("#planTable").innerHTML = empty("读取失败:" + err.message);
  }
}
$("#refreshPlanBtn").addEventListener("click", renderPlan);

async function renderMemory() {
  if (!state.current) return ($("#memoryView").innerHTML = empty("请先选择学习者。"));
  try {
    const m = await req("GET", `/learners/${state.current}/memory`);
    const rows = m.entries
      .map(
        (e) => `<tr>
      <td class="mono">${esc(e.kind)}</td>
      <td class="mono small">${esc(e.entry_id)}</td>
      <td class="mono small">${esc(e.entry_version_id)}</td>
      <td>${e.version}</td><td>${esc(e.state)}</td>
      <td class="mono small wrap">${esc(e.text)}</td>
    </tr>`
      )
      .join("");
    $("#memoryView").innerHTML = `
      <div class="meta">
        <div><b>scope</b><span class="mono">${esc(m.scope_id)}</span></div>
        <div><b>memory_artifact_id</b><span class="mono">${esc(m.memory_artifact_id)}</span></div>
        <div><b>当前 revision</b><span class="mono">${m.revision}</span></div>
        <div><b>活动条目数</b><span class="mono">${m.entry_count}</span></div>
      </div>
      <div class="table-wrap"><table>
        ${head(["kind", "entry_id", "entry_version_id", "version", "state", "正文(回查)"]) + rows}
      </table></div>`;
  } catch (err) {
    $("#memoryView").innerHTML = empty("读取失败:" + err.message);
  }
}
$("#refreshMemoryBtn").addEventListener("click", renderMemory);

$("#refreshHistoryBtn").addEventListener("click", async () => {
  if (!state.current) return toast("请先选择学习者", "error");
  try {
    const h = await req("GET", `/learners/${state.current}/memory/history`);
    const blocks = h.revisions
      .map((rev) => {
        const chg = rev.changes.length
          ? rev.changes.map((c) => `${c.op}:${short(c.entry_id)}`).join(" ")
          : "(初始)";
        const es = rev.entries.map((e) => `${e.kind}=${e.text}`).join(" | ");
        return `<div class="rev"><span class="mono">revision ${rev.revision}</span> 变更:${esc(chg)}<br><span class="small">${esc(es)}</span></div>`;
      })
      .join("");
    $("#memoryView").innerHTML =
      `<div class="meta"><div><b>scope</b><span class="mono">${esc(h.scope_id)}</span></div></div>` +
      `<h4>SDK 逐修订回查历史(共 ${h.revisions.length} 个 revision)</h4>` +
      (blocks || "(无)");
  } catch (err) {
    toast("读取历史失败:" + err.message, "error");
  }
});

// ----------------------------------------------------------------- helpers
function head(cols) {
  return "<thead><tr>" + cols.map((c) => `<th>${c}</th>`).join("") + "</tr></thead>";
}
function empty(msg) {
  return `<tbody><tr><td class="empty">${esc(msg)}</td></tr></tbody>`;
}
function short(id) {
  return (id || "").slice(0, 14) + "…";
}
function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

// ----------------------------------------------------------------- boot
async function boot() {
  try {
    await loadLearners();
    renderOverview();
  } catch (err) {
    notice("后端连接失败:" + err.message);
  }
}
boot();
