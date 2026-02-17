function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return response.json();
}

function renderDashboardProjects(projects) {
  const container = document.getElementById("project-cards");
  const count = document.getElementById("project-count");
  if (!container || !count) return;
  count.textContent = String(projects.length);
  if (!projects.length) {
    container.innerHTML = "<p>暂无项目，先创建一个。</p>";
    return;
  }
  container.innerHTML = projects
    .map(
      (p) => `<a class="project-card" href="/projects/${encodeURIComponent(p.project_id)}">
        <h3>${escapeHtml(p.project_name)}</h3>
        <p>ID: ${escapeHtml(p.project_id)}</p>
        <p>状态: ${escapeHtml(p.status)}</p>
        <p>模式: ${escapeHtml(p.development_mode)}</p>
        <p>Agent 数: ${escapeHtml(p.agent_count)}</p>
        <p>更新时间: ${escapeHtml(p.updated_at)}</p>
      </a>`
    )
    .join("");
}

async function refreshDashboard() {
  const [projectsData, configData] = await Promise.all([
    fetchJson("/api/projects"),
    fetchJson("/api/config/global/data"),
  ]);
  renderDashboardAgentModels(configData);
  const data = projectsData;
  renderDashboardProjects(data.projects || []);
}

function renderDashboardAgentModels(configData) {
  const grid = document.getElementById("agent-model-grid");
  if (!grid || !configData) return;
  const catalog = Array.isArray(configData.model_catalog) ? configData.model_catalog : [];
  const agents = Array.isArray(configData.available_agents) ? configData.available_agents : [];
  const selection = configData.agent_model_selection || {};

  if (!catalog.length || !agents.length) return;

  grid.innerHTML = agents
    .map((agent) => {
      const selected = selection[agent] || "";
      const options = catalog
        .map((item) => {
          const optionId = String(item.id || "");
          const isDefault = !!item.default;
          const isSelected = selected ? selected === optionId : isDefault;
          return `<option value="${escapeHtml(optionId)}" ${isSelected ? "selected" : ""}>
            ${escapeHtml(optionId)}${isDefault ? " (default)" : ""}
          </option>`;
        })
        .join("");
      return `<label>${escapeHtml(agent)}</label>
        <select name="agent_model_${escapeHtml(agent)}" data-agent-model="${escapeHtml(agent)}">${options}</select>`;
    })
    .join("");
}

function setupDashboard() {
  const page = document.getElementById("dashboard-page");
  if (!page) return;
  const form = document.getElementById("create-project-form");
  if (form) {
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const formData = new FormData(form);
      const payload = {
        project_name: String(formData.get("project_name") || ""),
        development_mode: String(formData.get("development_mode") || "local"),
        initial_requirement: String(formData.get("initial_requirement") || ""),
      };
      const created = await fetchJson("/api/projects", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      window.location.href = `/projects/${encodeURIComponent(created.project_id)}`;
    });
  }
  refreshDashboard().catch(() => {});
  setInterval(() => {
    refreshDashboard().catch(() => {});
  }, 10000);
}

function renderProjectRequirements(requirements) {
  const list = document.getElementById("requirements-list");
  if (!list) return;
  if (!requirements.length) {
    list.innerHTML = "<li>暂无需求历史。</li>";
    return;
  }
  list.innerHTML = requirements
    .map((req) => `<li>${escapeHtml(req.created_at)} - ${escapeHtml(req.text)}</li>`)
    .join("");
}

function renderProjectRuns(projectId, runs) {
  const tbody = document.getElementById("runs-tbody");
  if (!tbody) return;
  if (!runs.length) {
    tbody.innerHTML = '<tr><td colspan="4">暂无执行记录。</td></tr>';
    return;
  }
  tbody.innerHTML = runs
    .map(
      (run) => `<tr>
        <td>${escapeHtml(run.run_id)}</td>
        <td>${escapeHtml(run.started_at)}</td>
        <td>${escapeHtml((run.requirement_text || "").slice(0, 80))}</td>
        <td><a href="/projects/${encodeURIComponent(projectId)}/runs/${encodeURIComponent(run.run_id)}">详情</a></td>
      </tr>`
    )
    .join("");
}

async function refreshProject(projectId) {
  const [requirementsData, runsData] = await Promise.all([
    fetchJson(`/api/projects/${encodeURIComponent(projectId)}/requirements`),
    fetchJson(`/api/projects/${encodeURIComponent(projectId)}/runs`),
  ]);
  renderProjectRequirements(requirementsData.requirements || []);
  renderProjectRuns(projectId, runsData.runs || []);
}

function setupProjectPage() {
  const page = document.getElementById("project-page");
  if (!page) return;
  const projectId = page.getAttribute("data-project-id");
  if (!projectId) return;

  const form = document.getElementById("requirement-form");
  if (form) {
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const formData = new FormData(form);
      const payload = {
        requirement_text: String(formData.get("requirement_text") || ""),
      };
      const created = await fetchJson(`/api/projects/${encodeURIComponent(projectId)}/requirements`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      window.location.href = `/projects/${encodeURIComponent(projectId)}/runs/${encodeURIComponent(created.run_id)}`;
    });
  }

  refreshProject(projectId).catch(() => {});
  setInterval(() => {
    refreshProject(projectId).catch(() => {});
  }, 10000);
}

function setupGlobalConfigPage() {
  const editor = document.getElementById("model-list-editor");
  if (!editor) return;

  const addBtn = document.getElementById("add-model-btn");
  const agentGrid = document.getElementById("global-agent-model-grid");

  function collectModelRows() {
    return Array.from(editor.querySelectorAll(".model-row"));
  }

  function rebuildAgentOptions() {
    if (!agentGrid) return;
    const rows = collectModelRows();
    const modelIds = rows
      .map((row) => row.querySelector('input[name="model_id"]'))
      .filter((input) => input)
      .map((input) => String(input.value || "").trim())
      .filter((id) => id);
    if (!modelIds.length) return;

    const selects = Array.from(agentGrid.querySelectorAll("select"));
    selects.forEach((select) => {
      const current = String(select.value || "");
      const defaultIdInput = editor.querySelector('input[name="default_model_id"]:checked');
      const defaultId = defaultIdInput ? String(defaultIdInput.value || "").trim() : modelIds[0];
      select.innerHTML = modelIds
        .map((id) => `<option value="${escapeHtml(id)}">${escapeHtml(id)}${id === defaultId ? " (default)" : ""}</option>`)
        .join("");
      if (modelIds.includes(current)) {
        select.value = current;
      } else {
        select.value = defaultId;
      }
    });
  }

  function bindRow(row) {
    const removeBtn = row.querySelector(".model-remove");
    const idInput = row.querySelector('input[name="model_id"]');
    const radio = row.querySelector('input[name="default_model_id"]');

    if (removeBtn) {
      removeBtn.addEventListener("click", () => {
        row.remove();
        const rows = collectModelRows();
        if (rows.length && !editor.querySelector('input[name="default_model_id"]:checked')) {
          const firstRadio = rows[0].querySelector('input[name="default_model_id"]');
          if (firstRadio) firstRadio.checked = true;
        }
        rebuildAgentOptions();
      });
    }

    if (idInput) {
      idInput.addEventListener("input", () => {
        if (radio) {
          radio.value = idInput.value;
        }
        rebuildAgentOptions();
      });
    }
    if (radio) {
      radio.addEventListener("change", () => {
        rebuildAgentOptions();
      });
    }
  }

  collectModelRows().forEach(bindRow);
  rebuildAgentOptions();

  if (addBtn) {
    addBtn.addEventListener("click", () => {
      const row = document.createElement("div");
      row.className = "model-row";
      row.innerHTML = `
        <input name="model_id" value="" placeholder="provider:model">
        <label class="inline-radio">
          <input type="radio" name="default_model_id" value="">
          默认
        </label>
        <button type="button" class="btn secondary model-remove">删除</button>
      `;
      editor.appendChild(row);
      bindRow(row);
    });
  }
}

function setupModelsConfigPage() {
  const modelsEditor = document.getElementById("models-editor");
  const providersEditor = document.getElementById("providers-editor");
  const modelsInitialNode = document.getElementById("models-initial-data");
  const providersInitialNode = document.getElementById("providers-initial-data");
  const form = document.getElementById("models-config-form");
  const addModelBtn = document.getElementById("add-model-btn");
  const addProviderBtn = document.getElementById("add-provider-btn");
  const modelsOutput = document.getElementById("models-json-input");
  const providersOutput = document.getElementById("providers-json-input");

  if (!modelsEditor || !providersEditor || !modelsInitialNode || !providersInitialNode || !form || !modelsOutput || !providersOutput) return;

  let models = [];
  let providers = [];
  try {
    models = JSON.parse(modelsInitialNode.textContent || "[]");
  } catch {
    models = [];
  }
  try {
    providers = JSON.parse(providersInitialNode.textContent || "[]");
  } catch {
    providers = [];
  }
  if (!Array.isArray(models)) models = [];
  if (!Array.isArray(providers)) providers = [];

  function createProviderRow(provider = {}) {
    const row = document.createElement("div");
    row.className = "provider-row";
    row.innerHTML = `
      <input class="provider-name" placeholder="provider" value="${escapeHtml(provider.provider || "")}">
      <input class="provider-key" placeholder="api key" value="${escapeHtml(provider.api_key || "")}">
      <input class="provider-uri" placeholder="base url" value="${escapeHtml(provider.base_url || "")}">
      <label><input type="checkbox" class="provider-enabled" ${provider.enabled !== false ? "checked" : ""}>启用</label>
      <button type="button" class="btn secondary provider-remove">删除</button>
    `;
    row.querySelector(".provider-name")?.addEventListener("input", syncModelProviderSelectors);
    row.querySelector(".provider-enabled")?.addEventListener("change", syncModelProviderSelectors);
    row.querySelector(".provider-remove")?.addEventListener("click", () => {
      row.remove();
      syncModelProviderSelectors();
    });
    return row;
  }

  function getEnabledProviderNames() {
    return Array.from(providersEditor.querySelectorAll(".provider-row"))
      .map((row) => ({
        name: String(row.querySelector(".provider-name")?.value || "").trim(),
        enabled: !!row.querySelector(".provider-enabled")?.checked,
      }))
      .filter((item) => item.name && item.enabled)
      .map((item) => item.name);
  }

  function createModelCard(model = {}) {
    const card = document.createElement("div");
    card.className = "model-card";
    const isLocal = !!model.is_local;
    card.innerHTML = `
      <div class="stack">
        <label>模型ID</label>
        <input class="model-id" placeholder="例如 gpt-4o" value="${escapeHtml(model.id || "")}">
        <label>模型名称</label>
        <input class="model-name" placeholder="例如 GPT-4o" value="${escapeHtml(model.name || model.id || "")}">
        <label>API 模型名（OpenAI model 字段）</label>
        <input class="model-api-model" placeholder="例如 gpt-4o" value="${escapeHtml(model.api_model || model.id || "")}">
        <label class="inline-radio"><input type="radio" name="model-default-flag" class="model-default" ${model.default ? "checked" : ""}> 设为默认模型</label>
        <label><input type="checkbox" class="model-is-local" ${isLocal ? "checked" : ""}> 本地模型（无需 providers）</label>
        <label>默认 Provider</label>
        <select class="model-default-provider"></select>
        <label>扩展参数（JSON）</label>
        <textarea class="model-extra" rows="3" placeholder='{"supports_tools": true}'>${escapeHtml(JSON.stringify(model.extra || {}, null, 2))}</textarea>
      </div>
      <h4>绑定 Providers</h4>
      <div class="model-provider-selectors"></div>
      <div class="auth-grid">
        <button type="button" class="btn secondary model-remove">删除模型</button>
      </div>
    `;

    const defaultSelect = card.querySelector(".model-default-provider");
    const selectors = card.querySelector(".model-provider-selectors");
    const localCheckbox = card.querySelector(".model-is-local");
    const presetProviders = Array.isArray(model.providers) ? model.providers.map((p) => String(p)) : [];

    function syncSelectors() {
      const available = getEnabledProviderNames();
      const currentChecked = Array.from(selectors.querySelectorAll('input[type="checkbox"]:checked')).map((el) => el.value);
      const selected = currentChecked.length ? currentChecked : presetProviders;
      selectors.innerHTML = available
        .map((name) => `<label><input type="checkbox" value="${escapeHtml(name)}" ${selected.includes(name) ? "checked" : ""}> ${escapeHtml(name)}</label>`)
        .join(" ");
      const selectedNow = Array.from(selectors.querySelectorAll('input[type="checkbox"]:checked')).map((el) => el.value);
      const localMode = !!localCheckbox?.checked;
      selectors.style.display = localMode ? "none" : "block";
      defaultSelect.disabled = localMode;
      if (localMode) {
        defaultSelect.innerHTML = `<option value="local">local</option>`;
        defaultSelect.value = "local";
        return;
      }
      const options = selectedNow.length ? selectedNow : available;
      defaultSelect.innerHTML = options.map((name) => `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`).join("");
      defaultSelect.value = options.includes(String(model.default_provider || "")) ? String(model.default_provider || "") : (options[0] || "");
    }

    selectors.addEventListener("change", () => syncSelectors());
    localCheckbox?.addEventListener("change", () => syncSelectors());
    card.querySelector(".model-remove")?.addEventListener("click", () => card.remove());
    card.syncSelectors = syncSelectors;
    syncSelectors();
    return card;
  }

  function syncModelProviderSelectors() {
    Array.from(modelsEditor.querySelectorAll(".model-card")).forEach((card) => {
      if (typeof card.syncSelectors === "function") {
        card.syncSelectors();
      }
    });
  }

  providersEditor.innerHTML = "";
  providers.forEach((p) => providersEditor.appendChild(createProviderRow(p)));
  if (!providers.length) {
    providersEditor.appendChild(createProviderRow({ provider: "openai", api_key: "", base_url: "", enabled: true }));
  }

  modelsEditor.innerHTML = "";
  models.forEach((m) => modelsEditor.appendChild(createModelCard(m)));
  if (!models.length) {
    modelsEditor.appendChild(createModelCard({ id: "", default: true, default_provider: "", providers: [], is_local: false }));
  }

  syncModelProviderSelectors();

  addProviderBtn?.addEventListener("click", () => {
    providersEditor.appendChild(createProviderRow({ provider: "", api_key: "", base_url: "", enabled: true }));
  });

  addModelBtn?.addEventListener("click", () => {
    modelsEditor.appendChild(createModelCard({ id: "", default: false, default_provider: "", providers: [], is_local: false }));
    syncModelProviderSelectors();
  });

  form.addEventListener("submit", () => {
    const collectedProviders = Array.from(providersEditor.querySelectorAll(".provider-row"))
      .map((row) => ({
        provider: String(row.querySelector(".provider-name")?.value || "").trim(),
        api_key: String(row.querySelector(".provider-key")?.value || ""),
        base_url: String(row.querySelector(".provider-uri")?.value || ""),
        enabled: !!row.querySelector(".provider-enabled")?.checked,
      }))
      .filter((p) => p.provider);

    const collectedModels = Array.from(modelsEditor.querySelectorAll(".model-card"))
      .map((card) => {
        const isLocal = !!card.querySelector(".model-is-local")?.checked;
        const selectedProviders = Array.from(card.querySelectorAll('.model-provider-selectors input[type="checkbox"]:checked')).map((el) => el.value);
        return {
          id: String(card.querySelector(".model-id")?.value || "").trim(),
          name: String(card.querySelector(".model-name")?.value || "").trim(),
          api_model: String(card.querySelector(".model-api-model")?.value || "").trim(),
          default: !!card.querySelector(".model-default")?.checked,
          default_provider: String(card.querySelector(".model-default-provider")?.value || "").trim(),
          is_local: isLocal,
          providers: isLocal ? [] : selectedProviders,
          extra: (() => {
            const raw = String(card.querySelector(".model-extra")?.value || "").trim();
            if (!raw) return {};
            try {
              const parsed = JSON.parse(raw);
              return typeof parsed === "object" && parsed !== null ? parsed : {};
            } catch {
              return {};
            }
          })(),
        };
      })
      .filter((m) => m.id);

    if (!collectedModels.some((m) => m.default) && collectedModels.length) {
      collectedModels[0].default = true;
    }

    providersOutput.value = JSON.stringify(collectedProviders);
    modelsOutput.value = JSON.stringify(collectedModels);
  });
}

document.addEventListener("DOMContentLoaded", () => {
  setupDashboard();
  setupProjectPage();
  setupGlobalConfigPage();
  setupModelsConfigPage();
});
