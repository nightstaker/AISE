function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

async function fetchJson(url, options) {
  const response = await fetch(url, options || {});
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return response.json();
}

function readScriptJson(id, fallback) {
  const node = document.getElementById(id);
  if (!node) return fallback;
  try {
    return JSON.parse(node.textContent || "null") || fallback;
  } catch {
    return fallback;
  }
}

function mountReact(rootId, componentFactory) {
  const rootNode = document.getElementById(rootId);
  if (!rootNode || !window.React || !window.ReactDOM) return;
  const root = window.ReactDOM.createRoot(rootNode);
  root.render(componentFactory(window.React));
}

// ---------------------------------------------------------------------------
// i18n (i18next)
// ---------------------------------------------------------------------------
//
// Translations are standard i18next JSON resource files served by
// FastAPI's StaticFiles mount under ``/static/locales/<lng>/<ns>.json``.
// Adding a new language = drop a new ``<code>/translation.json`` folder;
// no code change required.
//
// The initial language is authoritative from the server (user's Settings)
// and comes through the ``window.__AISE_LANG`` global seeded by layout.html.
// i18next is loaded from CDN in layout.html alongside its http-backend
// plugin, so by the time this file runs ``window.i18next`` exists.
//
// Rendering is async: the bootstrap waits on ``i18next.init()`` before
// mounting React. This avoids a flash-of-raw-key on first paint.
//
// ``t(key, params)`` below is a thin wrapper that delegates to
// ``i18next.t``. Keep it around so existing callers don't care whether
// i18next is loaded yet.

const I18N_SUPPORTED_LANGS = ["zh", "en"];
const I18N_DEFAULT_LANG = "zh";

function resolveInitialLang() {
  const raw = (window.__AISE_LANG || "").toString().toLowerCase();
  return I18N_SUPPORTED_LANGS.indexOf(raw) >= 0 ? raw : I18N_DEFAULT_LANG;
}

// Bootstraps i18next once per page load. Subsequent calls return the
// same promise so multiple page-specific setup functions (dashboard,
// run, task, etc.) can all ``await`` the shared init.
let _i18nReady = null;
function initI18n() {
  if (_i18nReady) return _i18nReady;
  if (!window.i18next || !window.i18nextHttpBackend) {
    // Vendor scripts didn't load (offline / CDN blocked). Resolve the
    // promise so pages still mount; ``t()`` will fall through to the
    // raw key and at least be legible in English-ish form.
    _i18nReady = Promise.resolve(null);
    return _i18nReady;
  }
  _i18nReady = window.i18next.use(window.i18nextHttpBackend).init({
    lng: resolveInitialLang(),
    fallbackLng: "en",
    supportedLngs: I18N_SUPPORTED_LANGS,
    defaultNS: "translation",
    ns: ["translation"],
    backend: {
      loadPath: "/static/locales/{{lng}}/{{ns}}.json",
    },
    interpolation: {
      // React escapes children already — don't double-escape.
      escapeValue: false,
    },
    returnEmptyString: false,
  });
  return _i18nReady;
}

function t(key, params) {
  if (window.i18next && window.i18next.isInitialized) {
    return window.i18next.t(key, params);
  }
  // Pre-init fallback: return the key itself. Any code that renders
  // before ``await initI18n()`` will show raw keys — which is louder
  // than silent undefined and easy to spot in dev.
  return key;
}

function currentLang() {
  if (window.i18next && window.i18next.language) {
    return String(window.i18next.language).toLowerCase();
  }
  return resolveInitialLang();
}

function formatLocalTime(ts) {
  if (!ts) return "";
  try {
    const d = new Date(ts);
    if (isNaN(d.getTime())) return String(ts);
    const locale = currentLang() === "en" ? "en-US" : "zh-CN";
    return d.toLocaleString(locale, {
      year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", second: "2-digit",
      hour12: false
    });
  } catch { return String(ts); }
}

function setupDashboardReact() {
  const initial = readScriptJson("dashboard-initial-data", { projects: [], global_config_data: {} });

  function formatTime(ts) {
    if (!ts) return "";
    const d = new Date(ts);
    if (isNaN(d.getTime())) return String(ts);
    const now = Date.now();
    const diff = now - d.getTime();
    if (diff < 60000) return "刚刚";
    if (diff < 3600000) return `${Math.floor(diff / 60000)} 分钟前`;
    if (diff < 86400000) return `${Math.floor(diff / 3600000)} 小时前`;
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  }

  function DashboardApp() {
    const h = window.React.createElement;
    const config = initial.global_config_data || {};
    const availableAgents = Array.isArray(config.available_agents) ? config.available_agents : [];
    const [projects, setProjects] = window.React.useState(Array.isArray(initial.projects) ? initial.projects : []);
    const [catalog, setCatalog] = window.React.useState(Array.isArray(config.model_catalog) ? config.model_catalog : []);
    const [agentModels, setAgentModels] = window.React.useState(config.agent_model_selection || {});
    const [formData, setFormData] = window.React.useState({
      project_name: "",
      development_mode: config.development_mode || "local",
      process_type: "waterfall",
      initial_requirement: "",
    });
    const [submitting, setSubmitting] = window.React.useState(false);
    const [deletingProjectId, setDeletingProjectId] = window.React.useState("");
    const [error, setError] = window.React.useState("");
    const [showModal, setShowModal] = window.React.useState(false);

    window.React.useEffect(() => {
      let active = true;
      async function refresh() {
        try {
          const [projectsData, cfgData] = await Promise.all([
            fetchJson("/api/projects"),
            fetchJson("/api/config/global/data"),
          ]);
          if (!active) return;
          setProjects(Array.isArray(projectsData.projects) ? projectsData.projects : []);
          const nextCatalog = Array.isArray(cfgData.model_catalog) ? cfgData.model_catalog : [];
          setCatalog(nextCatalog);
          setAgentModels(cfgData.agent_model_selection || {});
          setFormData((prev) => ({
            project_name: prev.project_name,
            initial_requirement: prev.initial_requirement,
            development_mode: prev.development_mode || cfgData.development_mode || "local",
            process_type: prev.process_type || "waterfall",
            _showAgentModels: prev._showAgentModels,
          }));
        } catch {
          // keep current state
        }
      }

      refresh();
      const timer = window.setInterval(refresh, 3000);
      return () => {
        active = false;
        window.clearInterval(timer);
      };
    }, []);

    async function submitProject(event) {
      event.preventDefault();
      setSubmitting(true);
      setError("");
      try {
        const payload = {
          project_name: String(formData.project_name || ""),
          development_mode: String(formData.development_mode || "local"),
          process_type: String(formData.process_type || "waterfall"),
          initial_requirement: String(formData.initial_requirement || ""),
          agent_models: agentModels,
        };
        const created = await fetchJson("/api/projects", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        setShowModal(false);
        if (created.run_id) {
          window.location.href = `/projects/${encodeURIComponent(created.project_id)}/runs/${encodeURIComponent(created.run_id)}`;
          return;
        }
        window.location.href = `/projects/${encodeURIComponent(created.project_id)}`;
      } catch (err) {
        setError(err instanceof Error ? err.message : "创建失败");
        setSubmitting(false);
      }
    }

    async function deleteProject(project, e) {
      e.preventDefault();
      e.stopPropagation();
      const projectId = String(project.project_id || "");
      if (!projectId) return;
      const first = window.confirm(`确认删除项目「${project.project_name || projectId}」？`);
      if (!first) return;
      const second = window.confirm(`再次确认：删除后将同步清理目录，且不可恢复。\n项目ID: ${projectId}`);
      if (!second) return;
      setDeletingProjectId(projectId);
      setError("");
      try {
        await fetchJson(`/api/projects/${encodeURIComponent(projectId)}`, { method: "DELETE" });
        setProjects((prev) => prev.filter((p) => String(p.project_id) !== projectId));
      } catch (err) {
        setError(err instanceof Error ? err.message : "删除失败");
      } finally {
        setDeletingProjectId("");
      }
    }

    async function restartProject(project, e) {
      e.preventDefault();
      e.stopPropagation();
      const projectId = String(project.project_id || "");
      if (!projectId) return;
      if (!window.confirm(`确认重新开始项目「${project.project_name || projectId}」？\n将清除所有执行记录，重新提交原始需求。`)) return;
      setError("");
      try {
        const result = await fetchJson(`/api/projects/${encodeURIComponent(projectId)}/restart`, { method: "POST" });
        if (result.run_id) {
          window.location.href = `/projects/${encodeURIComponent(projectId)}/runs/${encodeURIComponent(result.run_id)}`;
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "重启失败");
      }
    }

    function defaultModelId() {
      const byFlag = catalog.find((item) => !!item.default && item.id);
      if (byFlag) return String(byFlag.id);
      if (catalog.length && catalog[0].id) return String(catalog[0].id);
      return "";
    }

    function selectOptionsFor(agent) {
      return catalog.map((item) => {
        const optionId = String(item.id || "");
        const isDefault = !!item.default;
        const optionText = `${optionId}${isDefault ? " (default)" : ""}`;
        return h("option", { key: optionId, value: optionId }, optionText);
      });
    }

    // Project card badge: prefer workflow-run state (has_active_run +
    // latest_run_status) over the project-lifecycle status. The lifecycle
    // ``active`` just means "not paused/archived", which is the default for
    // every project — rendering that as "in progress" made every card look busy.
    function projectBadge(project) {
      if (project && project.has_active_run) {
        return h("span", { className: "status-badge status-running" }, "◉ 运行中");
      }
      const latest = project ? project.latest_run_status : null;
      if (latest === "completed" || latest === "success") return h("span", { className: "status-badge status-success" }, "✓ 成功");
      if (latest === "failed" || latest === "error") return h("span", { className: "status-badge status-failed" }, "✕ 失败");
      const lifecycle = project ? project.status : null;
      if (lifecycle === "paused") return h("span", { className: "status-badge status-pending" }, "⏸ 暂停");
      if (lifecycle === "archived") return h("span", { className: "status-badge status-pending" }, "▣ 归档");
      if (lifecycle === "completed") return h("span", { className: "status-badge status-success" }, "✓ 已完成");
      return h("span", { className: "status-badge status-pending" }, "○ 就绪");
    }

    const runningCount = projects.filter((p) => p.has_active_run).length;
    const successCount = projects.filter((p) => (p.latest_run_status === "completed" || p.latest_run_status === "success") && !p.has_active_run).length;
    const failedCount = projects.filter((p) => (p.latest_run_status === "failed" || p.latest_run_status === "error") && !p.has_active_run).length;

    const modal = showModal
      ? h(
          "div",
          {
            className: "modal-overlay",
            onClick: (e) => { if (e.target === e.currentTarget) setShowModal(false); },
          },
          h(
            "div",
            { className: "modal-content" },
            h(
              "div",
              { className: "modal-header" },
              h("h2", null, "新建项目"),
              h("button", { className: "modal-close", onClick: () => setShowModal(false) }, "×")
            ),
            h(
              "form",
              { className: "modal-form", onSubmit: submitProject },
              h("label", null, "项目名称"),
              h("input", {
                required: true,
                value: formData.project_name,
                placeholder: "例如: UserAPI",
                onChange: (e) => setFormData((prev) => ({ ...prev, project_name: e.target.value })),
              }),
              h("label", null, "开发模式"),
              h(
                "select",
                {
                  value: formData.development_mode,
                  onChange: (e) => setFormData((prev) => ({ ...prev, development_mode: e.target.value })),
                },
                h("option", { value: "local" }, "Local"),
                h("option", { value: "github" }, "GitHub")
              ),
              h("label", null, "研发流程"),
              h(
                "select",
                {
                  value: formData.process_type || "waterfall",
                  onChange: (e) => setFormData((prev) => ({ ...prev, process_type: e.target.value })),
                },
                h("option", { value: "waterfall" }, "Waterfall — 线性全生命周期"),
                h("option", { value: "agile" }, "Agile Sprint — 迭代交付 MVP")
              ),
              h("p", { style: { margin: "4px 0 12px", color: "#888", fontSize: "12px" } },
                formData.process_type === "agile"
                  ? "迭代模式：sprint planning / sprint execution / sprint review / retrospective / delivery"
                  : "瀑布模式：需求 / 架构 / 开发 / 入口验证 / 集成测试 / 交付报告"),
              h("label", null, "初始需求（可选）"),
              h("textarea", {
                rows: 4,
                placeholder: "例如：构建一个用户管理 API",
                value: formData.initial_requirement,
                onChange: (e) => setFormData((prev) => ({ ...prev, initial_requirement: e.target.value })),
              }),
              h("div", { className: "agent-model-toggle-row" },
                h("button", {
                  type: "button",
                  className: "btn secondary btn-sm",
                  onClick: () => setFormData((prev) => ({ ...prev, _showAgentModels: !prev._showAgentModels })),
                }, formData._showAgentModels ? "\u25BC \u6536\u8D77 Agent \u6A21\u578B\u914D\u7F6E" : "\u25B6 \u81EA\u5B9A\u4E49 Agent \u6A21\u578B"),
              ),
              formData._showAgentModels ? h(
                "div",
                { className: "agent-grid" },
                ...availableAgents.flatMap((agent) => [
                  h("label", { key: `${agent}-label` }, agent),
                  h(
                    "select",
                    {
                      key: `${agent}-select`,
                      value: String(agentModels[agent] || defaultModelId()),
                      onChange: (e) =>
                        setAgentModels((prev) => ({
                          ...prev,
                          [agent]: e.target.value,
                        })),
                    },
                    ...selectOptionsFor(agent)
                  ),
                ])
              ) : null,
              error ? h("p", { className: "warning" }, error) : null,
              h(
                "div",
                { className: "modal-actions" },
                h("button", { type: "button", className: "btn secondary", onClick: () => setShowModal(false) }, "取消"),
                h("button", { className: "btn", type: "submit", disabled: submitting }, submitting ? "创建中..." : "创建项目")
              )
            )
          )
        )
      : null;

    return h(
      "div",
      { className: "dashboard-shell" },
      h(
        "div",
        { className: "dashboard-topbar" },
        h(
          "div",
          { className: "dashboard-topbar-left" },
          h("h1", { className: "dashboard-title" }, "项目"),
          h(
            "div",
            { className: "dashboard-stats" },
            h("span", { className: "stat-chip" }, `共 ${projects.length} 个`),
            runningCount > 0 ? h("span", { className: "stat-chip stat-running" }, `${runningCount} 运行中`) : null,
            successCount > 0 ? h("span", { className: "stat-chip stat-success" }, `${successCount} 成功`) : null,
            failedCount > 0 ? h("span", { className: "stat-chip stat-failed" }, `${failedCount} 失败`) : null
          )
        ),
        h("button", { className: "btn create-project-btn", onClick: () => setShowModal(true) }, "＋ 新建项目")
      ),
      error ? h("div", { className: "dashboard-error" }, error) : null,
      h(
        "div",
        { className: "project-cards-grid" },
        projects.length
          ? projects.map((project) =>
              h(
                "a",
                {
                  key: project.project_id,
                  className: "project-card",
                  href: `/projects/${encodeURIComponent(project.project_id)}`,
                },
                h(
                  "div",
                  { className: "project-card-header" },
                  h("h3", null, project.project_name),
                  projectBadge(project)
                ),
                h(
                  "div",
                  { className: "project-card-meta" },
                  h("span", null, `模式: ${project.development_mode}`),
                  h("span", null, `流程: ${project.process_type || "waterfall"}`),
                  h("span", null, `Agent: ${project.agent_count}`)
                ),
                h(
                  "div",
                  { className: "project-card-footer" },
                  h("span", { className: "project-card-time" }, formatTime(project.updated_at)),
                  h(
                    "button",
                    {
                      className: "project-card-action project-card-restart",
                      onClick: (e) => restartProject(project, e),
                    },
                    "\u21BB"
                  ),
                  h(
                    "button",
                    {
                      className: "project-card-action project-card-delete",
                      disabled: deletingProjectId === String(project.project_id),
                      onClick: (e) => deleteProject(project, e),
                    },
                    deletingProjectId === String(project.project_id) ? "..." : "\u2715"
                  )
                )
              )
            )
          : h(
              "div",
              { className: "empty-state" },
              h("div", { className: "empty-icon" }, "📂"),
              h("p", null, "暂无项目"),
              h("p", null, "点击上方按钮创建你的第一个项目")
            )
      ),
      modal
    );
  }

  mountReact("dashboard-react-root", () => window.React.createElement(DashboardApp));
}

function setupProjectReact() {
  const initial = readScriptJson("project-initial-data", { project: null });
  if (!initial.project) return;

  function ProjectApp() {
    const h = window.React.createElement;
    const project = initial.project;
    const projectId = String((project.info || {}).project_id || "");
    const [requirements, setRequirements] = window.React.useState(Array.isArray(project.requirements) ? project.requirements : []);
    const [runs, setRuns] = window.React.useState(Array.isArray(project.runs) ? project.runs : []);
    const [text, setText] = window.React.useState("");
    const [submitting, setSubmitting] = window.React.useState(false);
    const [deleting, setDeleting] = window.React.useState(false);
    const [error, setError] = window.React.useState("");
    const [projectMissing, setProjectMissing] = window.React.useState(false);

    window.React.useEffect(() => {
      let active = true;
      let timer = 0;
      async function refresh() {
        try {
          const [requirementsData, runsData] = await Promise.all([
            fetchJson(`/api/projects/${encodeURIComponent(projectId)}/requirements`),
            fetchJson(`/api/projects/${encodeURIComponent(projectId)}/runs`),
          ]);
          if (!active) return;
          setRequirements(Array.isArray(requirementsData.requirements) ? requirementsData.requirements : []);
          setRuns(Array.isArray(runsData.runs) ? runsData.runs : []);
          setProjectMissing(false);
        } catch (err) {
          if (!active) return;
          const message = err instanceof Error ? err.message : "";
          if (String(message).includes("404")) {
            setProjectMissing(true);
            setError("项目不存在或已被删除。");
            if (timer) window.clearInterval(timer);
          }
        }
      }
      if (projectMissing) return () => {};
      refresh();
      timer = window.setInterval(refresh, 3000);
      return () => {
        active = false;
        if (timer) window.clearInterval(timer);
      };
    }, [projectId, projectMissing]);

    async function submitRequirement(event) {
      event.preventDefault();
      if (!text.trim()) return;
      setSubmitting(true);
      setError("");
      try {
        const created = await fetchJson(`/api/projects/${encodeURIComponent(projectId)}/requirements`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ requirement_text: text }),
        });
        window.location.href = `/projects/${encodeURIComponent(projectId)}/runs/${encodeURIComponent(created.run_id)}`;
      } catch (err) {
        setError(err instanceof Error ? err.message : "提交失败");
        setSubmitting(false);
      }
    }

    async function deleteCurrentProject() {
      const first = window.confirm(`确认删除项目「${project.info.project_name || projectId}」？`);
      if (!first) return;
      const second = window.confirm(`再次确认：删除后将同步清理目录，且不可恢复。\n项目ID: ${projectId}`);
      if (!second) return;
      setDeleting(true);
      setError("");
      try {
        await fetchJson(`/api/projects/${encodeURIComponent(projectId)}`, { method: "DELETE" });
        window.location.href = "/";
      } catch (err) {
        setError(err instanceof Error ? err.message : "删除失败");
        setDeleting(false);
      }
    }

    async function restartCurrentProject() {
      if (!window.confirm(`确认重新开始项目「${project.info.project_name || projectId}」？\n将清除所有执行记录，重新提交原始需求。`)) return;
      setError("");
      try {
        const result = await fetchJson(`/api/projects/${encodeURIComponent(projectId)}/restart`, { method: "POST" });
        if (result.run_id) {
          window.location.href = `/projects/${encodeURIComponent(projectId)}/runs/${encodeURIComponent(result.run_id)}`;
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "重启失败");
      }
    }

    const [view, setView] = window.React.useState("default");

    // Backend returns runs in insertion (chronological) order, so ``runs[0]``
    // is the OLDEST run. Sort by started_at descending and pick the newest
    // as the "latest run" target for the auto-redirect. Without this,
    // clicking a project card could bounce the user to a run from days ago
    // (e.g. an old failed dispatch) instead of whatever was just started.
    function pickLatestRun(list) {
      if (!list || list.length === 0) return null;
      return [...list].sort((a, b) => {
        const ta = Date.parse(a && a.started_at) || 0;
        const tb = Date.parse(b && b.started_at) || 0;
        return tb - ta;
      })[0];
    }

    // Auto-redirect to latest run if available
    window.React.useEffect(() => {
      const latestRun = pickLatestRun(runs);
      if (latestRun && latestRun.run_id) {
        window.location.href = `/projects/${encodeURIComponent(projectId)}/runs/${encodeURIComponent(latestRun.run_id)}`;
      }
    }, []); // only on initial load

    // If redirecting, show loading
    if (runs.length > 0 && view === "default") {
      return h(
        "div",
        { className: "project-layout" },
        h(
          "section",
          { className: "card card-glow project-header-card" },
          h("h1", null, project.info.project_name),
          h("p", { className: "muted" }, "正在跳转到最新执行记录...")
        )
      );
    }

    return h(
      "div",
      { className: "project-layout" },
      h(
        "section",
        { className: "card card-glow project-header-card" },
        h("h1", null, project.info.project_name),
        h("p", { className: "muted" }, `ID: ${project.info.project_id} | 状态: ${project.info.status} | 模式: ${project.info.development_mode}`),
        h("div", { style: { display: "flex", gap: "8px", marginTop: "8px" } },
          h(
            "button",
            {
              type: "button",
              className: "btn secondary",
              disabled: projectMissing,
              onClick: restartCurrentProject,
            },
            "\u21BB \u91CD\u65B0\u5F00\u59CB"
          ),
          h(
            "button",
            {
              type: "button",
              className: "btn danger",
              disabled: deleting || projectMissing,
              onClick: deleteCurrentProject,
            },
            deleting ? "\u5220\u9664\u4E2D..." : "\u5220\u9664\u9879\u76EE"
          ),
        )
      ),
      projectMissing
        ? h(
            "section",
            { className: "card" },
            h("p", { className: "warning" }, "当前项目已不存在，已停止轮询。"),
            h("a", { className: "btn secondary", href: "/" }, "返回项目列表")
          )
        : null,
      view === "default" ? h(
        "section",
        { className: "card", style: { display: "flex", gap: "16px", justifyContent: "center", padding: "32px" } },
        h(
          "button",
          {
            type: "button",
            className: "btn",
            style: { fontSize: "1.1rem", padding: "12px 32px" },
            disabled: projectMissing,
            onClick: () => setView("new-requirement"),
          },
          "＋ 新增需求"
        ),
        h(
          "button",
          {
            type: "button",
            className: "btn secondary",
            style: { fontSize: "1.1rem", padding: "12px 32px" },
            onClick: () => setView("history"),
          },
          "📋 查看历史需求"
        )
      ) : null,
      view === "new-requirement" ? h(
        "section",
        { className: "card" },
        h("div", { style: { display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" } },
          h("h2", null, "下发新需求"),
          h("button", { type: "button", className: "btn secondary", onClick: () => setView("default") }, "← 返回")
        ),
        h(
          "form",
          { className: "stack", onSubmit: submitRequirement },
          h("label", null, "需求内容"),
          h("textarea", {
            required: true,
            rows: 6,
            placeholder: "输入新需求",
            value: text,
            disabled: projectMissing,
            onChange: (e) => setText(e.target.value),
          }),
          error ? h("p", { className: "warning" }, error) : null,
          h(
            "button",
            { className: "btn", type: "submit", disabled: submitting || projectMissing },
            submitting ? "提交中..." : "提交并运行工作流"
          )
        )
      ) : null,
      view === "history" ? h(
        "div",
        null,
        h(
          "section",
          { className: "card" },
          h("div", { style: { display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" } },
            h("h2", null, "历史需求与执行记录"),
            h("button", { type: "button", className: "btn secondary", onClick: () => setView("default") }, "← 返回")
          ),
          h("h3", null, "需求列表"),
          h(
            "ul",
            { className: "history-list" },
            ...(requirements.length
              ? requirements.map((req, idx) => h("li", { key: `${req.created_at}-${idx}` }, `${formatLocalTime(req.created_at)} - ${req.text}`))
              : [h("li", { key: "empty", className: "muted" }, "暂无需求历史。")])
          ),
          h("h3", { style: { marginTop: "24px" } }, "工作流执行记录"),
          h(
            "div",
            { className: "table-scroll" },
            h(
              "table",
              null,
              h(
                "thead",
                null,
                h(
                  "tr",
                  null,
                  h("th", null, "执行ID"),
                  h("th", null, "时间"),
                  h("th", null, "状态"),
                  h("th", null, "需求摘要"),
                  h("th", null, "查看")
                )
              ),
              h(
                "tbody",
                null,
                ...(runs.length
                  ? runs.map((run) =>
                      h(
                        "tr",
                        { key: run.run_id },
                        h("td", null, run.run_id),
                        h("td", null, formatLocalTime(run.started_at)),
                        h("td", null, run.status || "pending"),
                        h("td", null, String(run.requirement_text || "").slice(0, 80)),
                        h(
                          "td",
                          null,
                          h(
                            "a",
                            {
                              href: `/projects/${encodeURIComponent(projectId)}/runs/${encodeURIComponent(run.run_id)}`,
                            },
                            "详情"
                          )
                        )
                      )
                    )
                  : [h("tr", { key: "empty" }, h("td", { colSpan: 5, className: "muted" }, "暂无执行记录。"))])
              )
            )
          )
        )
      ) : null
    );
  }

  mountReact("project-react-root", () => window.React.createElement(ProjectApp));
}

function setupRunReact() {
  const initial = readScriptJson("run-initial-data", { project: null, run: null });
  if (!initial.project || !initial.run) return;

  // Stage names live in the ``stage.<id>`` namespace of the i18next
  // resource files under ``static/locales/<lng>/translation.json``.
  // Phase names are free-form strings the PM picks at dispatch
  // time, so this resolver has to handle three cases:
  //
  //   1. Exact match on the full stage id  (``architecture`` → 架构设计)
  //   2. Known suffix patterns that carry a numeric counter —
  //      ``implementation_layer1`` / ``implementation_cycle_3`` /
  //      ``design_part_2`` etc. Strip the suffix, translate the base,
  //      append ``#N``.
  //   3. Unknown stage id: humanize it (``impl_config_loader`` →
  //      ``Impl Config Loader``) so the user never sees a raw
  //      snake_case identifier among Chinese labels.
  //
  // Missing-key detection uses i18next's built-in ``exists`` so we
  // don't depend on any string-equality trick between the probe key
  // and the return value.
  function humanizeStageId(stage) {
    return String(stage)
      .split(/[_-]+/)
      .filter(function (w) { return w.length > 0; })
      .map(function (w) {
        return w.charAt(0).toUpperCase() + w.slice(1);
      })
      .join(" ");
  }

  // Trailing counter suffix: ``_layer1`` / ``_layer_1`` / ``_cycle2`` /
  // ``_part_3`` / ``_iter4`` / ``_round_5`` / ``_v2``. Captures base +
  // numeric N.
  var STAGE_SUFFIX_RE = /^(.+?)_(?:layer|cycle|part|iter|iteration|round|stage|v|step)_?(\d+)$/;

  function stageKeyExists(stageId) {
    var key = "stage." + stageId;
    if (window.i18next && window.i18next.isInitialized) {
      return window.i18next.exists(key);
    }
    return false;
  }

  // Normalize a raw stage id down to its canonical "phase" id by
  // stripping the counter suffix. ``implementation_layer1`` and
  // ``implementation_layer2`` both normalize to ``implementation`` so
  // the chip strip shows a single "开发实现 / Implementation" chip
  // instead of one chip per layer. The expanded log entries still
  // show the raw ``ev.stage`` value (``implementation_layer1``) so
  // per-layer progress is not lost.
  function normalizeStageId(stage) {
    if (!stage) return stage;
    var m = String(stage).match(STAGE_SUFFIX_RE);
    return m ? m[1] : stage;
  }

  function resolveStageLabel(stage) {
    if (!stage) return stage;

    if (stageKeyExists(stage)) return t("stage." + stage);

    var suffix = stage.match(STAGE_SUFFIX_RE);
    if (suffix) {
      var base = stageKeyExists(suffix[1])
        ? t("stage." + suffix[1])
        : humanizeStageId(suffix[1]);
      return base + " #" + suffix[2];
    }

    return humanizeStageId(stage);
  }

  // Chip-strip label: always uses the NORMALIZED stage id so
  // ``implementation_layer2`` renders as just "Implementation" without
  // a "#2" suffix. This keeps the phase progression readable when a
  // phase has many sub-layers.
  function resolveChipLabel(stage) {
    if (!stage) return stage;
    var normalized = normalizeStageId(stage);
    if (stageKeyExists(normalized)) return t("stage." + normalized);
    return humanizeStageId(normalized);
  }

  const EVENT_ICONS = {
    stage_update: "▶",
    tool_call: "⚙",
    task_request: "→",
    task_response: "←",
    parallel_start: "≡",
  };

  // Todo status labels resolve via ``t()`` — see ``todo.status.*`` keys
  // in the i18next locale resource files.
  function todoStatusLabel(status) {
    var key = "todo.status." + status;
    var translated = t(key);
    return translated === key ? status : translated;
  }

  function TaskTodoProgress({ todos }) {
    const h = window.React.createElement;
    if (!Array.isArray(todos) || todos.length === 0) return null;
    var total = todos.length;
    var done = todos.filter((t) => t && t.status === "completed").length;
    return h("div", { className: "run-log-todos" },
      h("div", { className: "run-log-todos-header" },
        h("span", { className: "run-log-todos-title" }, t("todo.title")),
        h("span", { className: "run-log-todos-progress" }, done + " / " + total),
      ),
      h("ol", { className: "run-log-todos-list" },
        todos.map((t, i) => {
          var status = (t && t.status) || "pending";
          var label = (t && (t.activeForm && status === "in_progress" ? t.activeForm : t.content)) || "";
          var marker = status === "completed" ? "✓" : status === "in_progress" ? "●" : "○";
          return h("li", { key: i, className: "run-log-todo-item run-log-todo-" + status },
            h("span", { className: "run-log-todo-marker" }, marker),
            h("span", { className: "run-log-todo-text" }, label),
            h("span", { className: "run-log-todo-status" }, todoStatusLabel(status)),
          );
        }),
      ),
    );
  }

  function RunApp() {
    const h = window.React.createElement;
    const project = initial.project;
    const [run, setRun] = window.React.useState(initial.run);
    const [stageFilter, setStageFilter] = window.React.useState(null);
    const [runView, setRunView] = window.React.useState("timeline");
    const runStatus = String(run.status || "pending");
    const isRunning = runStatus === "pending" || runStatus === "running";
    const taskLog = Array.isArray(run.task_log) ? run.task_log : [];

    window.React.useEffect(() => {
      if (!isRunning) return;
      let active = true;
      const poll = () => {
        fetchJson("/api/projects/" + encodeURIComponent(project.info.project_id) + "/runs/" + encodeURIComponent(run.run_id))
          .then((d) => { if (active) setRun(d); })
          .catch(() => {});
      };
      const tid = setInterval(poll, 2000);
      return () => { active = false; clearInterval(tid); };
    }, [project.info.project_id, run.run_id, isRunning]);

    // Derive stages and tag each event with its stage.
    //
    // We track TWO things per event: the raw ``ev.stage`` (used in the
    // expanded log entry so the per-layer detail stays visible) and
    // the NORMALIZED stage id (e.g. ``implementation`` for
    // ``implementation_layer1``). The chip strip only shows normalized
    // ids, deduped, so multi-layer phases render as one chip.
    const stages = [];
    const normalizedSeen = new Set();
    let curRawStage = null;
    let curNormalizedStage = null;
    const evStagesRaw = [];
    const evStagesNormalized = [];
    for (let i = 0; i < taskLog.length; i++) {
      const ev = taskLog[i];
      if (ev.type === "stage_update" && ev.stage) {
        curRawStage = ev.stage;
        curNormalizedStage = normalizeStageId(ev.stage);
        if (!normalizedSeen.has(curNormalizedStage)) {
          normalizedSeen.add(curNormalizedStage);
          stages.push(curNormalizedStage);
        }
      }
      evStagesRaw.push(curRawStage);
      evStagesNormalized.push(curNormalizedStage);
    }
    const requests = taskLog.filter((e) => e.type === "task_request");
    const responses = taskLog.filter((e) => e.type === "task_response");
    const completed = responses.filter((e) => e.status === "completed").length;
    const failed = responses.filter((e) => e.status === "failed").length;

    // Build taskId → latest todos list. Each todos_update event carries
    // the full todo list at the time the agent invoked write_todos, so
    // the newest entry wins.
    // Agents often call write_todos once at the start to plan and then
    // never revisit it, so a task_response(completed) retroactively marks
    // every remaining todo as done. Failed tasks keep their last snapshot
    // so the user can see where the agent was when it died.
    // Tasks that never called write_todos at all (common for small
    // TDD modules) get a synthetic single-item list derived from the
    // task's terminal status so the card still shows a progress cue.
    const taskTodos = {};
    const taskTerminalStatus = {};
    const seenTaskIds = new Set();
    const taskRequestPayload = {};
    for (let i = 0; i < taskLog.length; i++) {
      const ev = taskLog[i];
      if (!ev || !ev.taskId) continue;
      if (ev.type === "task_request") {
        seenTaskIds.add(ev.taskId);
        taskRequestPayload[ev.taskId] = ev.payload || {};
      } else if (ev.type === "todos_update" && Array.isArray(ev.todos)) {
        taskTodos[ev.taskId] = ev.todos;
      } else if (ev.type === "task_response") {
        seenTaskIds.add(ev.taskId);
        taskTerminalStatus[ev.taskId] = ev.status;
      }
    }
    for (const tid of Object.keys(taskTerminalStatus)) {
      if (taskTerminalStatus[tid] !== "completed") continue;
      const list = taskTodos[tid];
      if (!Array.isArray(list)) continue;
      taskTodos[tid] = list.map((t) => (t && t.status !== "completed")
        ? Object.assign({}, t, { status: "completed" })
        : t);
    }
    // Synthetic fallback: if a task has no todos_update at all, build a
    // single-row list from its current state (in-progress / completed /
    // failed). Keeps every task card visually uniform instead of some
    // showing todos and some showing nothing.
    for (const tid of seenTaskIds) {
      if (Array.isArray(taskTodos[tid])) continue;
      const term = taskTerminalStatus[tid];
      const payload = taskRequestPayload[tid] || {};
      const label = payload.step || (payload.task ? String(payload.task).split("\n")[0].slice(0, 60) : "任务");
      let status = "in_progress";
      if (term === "completed") status = "completed";
      else if (term === "failed") status = "pending";
      taskTodos[tid] = [{
        content: label,
        activeForm: label,
        status: status,
        synthetic: true,
      }];
    }
    // Each completed task used to produce TWO rows in the log (a
    // task_request and a task_response). Merge them: render only the
    // task_request; its card shows the response's status/output in the
    // expanded details. Map taskId → response event here.
    const taskResponseByTaskId = {};
    for (let i = 0; i < taskLog.length; i++) {
      const ev = taskLog[i];
      if (ev && ev.type === "task_response" && ev.taskId) {
        taskResponseByTaskId[ev.taskId] = ev;
      }
    }
    // Hide raw todos_update rows (render inline under their task_request)
    // and task_response rows (merged into their request).
    const visibleLog = taskLog.filter(
      (e) => e.type !== "todos_update" && e.type !== "task_response",
    );
    // Filter predicate uses the NORMALIZED stage so a single
    // ``implementation`` chip matches every ``implementation_layer*``
    // event, not just the one raw id the user clicked.
    const visibleStages = taskLog
      .map((_, i) => evStagesNormalized[i])
      .filter(
        (_, i) =>
          taskLog[i].type !== "todos_update" &&
          taskLog[i].type !== "task_response",
      );
    const filteredLog = stageFilter
      ? visibleLog.filter((_, i) => visibleStages[i] === stageFilter)
      : visibleLog;

    const statusCls = runStatus === "completed" ? "run-status-completed"
      : runStatus === "failed" ? "run-status-failed"
      : runStatus === "running" ? "run-status-running" : "run-status-pending";
    const toggleStage = (s) => setStageFilter((prev) => prev === s ? null : s);

    return h("div", { className: "run-container" },
      h("div", { className: "run-header" },
        h("div", { className: "run-header-left" },
          h("a", { className: "run-back-link", href: "/projects/" + project.info.project_id }, "\u2190 " + (project.info.name || t("run.back.project_fallback"))),
          h("h1", { className: "run-title" }, t("run.title")),
          h("span", { className: "run-id-label" }, run.run_id),
        ),
        h("span", { className: "run-status-badge " + statusCls },
          isRunning ? h("span", { className: "monitor-task-pulse" }) : null,
          runStatus === "completed" ? t("run.status.completed")
            : runStatus === "failed" ? t("run.status.failed")
            : runStatus === "running" ? t("run.status.running")
            : t("run.status.pending"),
        ),
        run.mode === "incremental" ? h("span", {
          className: "run-mode-badge run-mode-badge-incremental",
          title: t("run.mode.incremental_hint"),
        }, t("run.mode.incremental")) : null,
        (run.process_type === "agile") ? h("span", {
          className: "run-mode-badge run-mode-badge-agile",
          title: currentLang() === "en"
            ? "Agile Sprint process: Planning → Execution → Review → Retrospective → Delivery"
            : "Agile Sprint 流程：规划 → 执行 → 评审 → 复盘 → 交付",
        }, currentLang() === "en" ? "Agile Sprint" : "Agile 迭代") :
        h("span", {
          className: "run-mode-badge run-mode-badge-waterfall",
          title: currentLang() === "en"
            ? "Waterfall process: Requirements → Architecture → Implementation → Entry → QA → Delivery"
            : "Waterfall 流程：需求 → 架构 → 实现 → 入口 → 测试 → 交付",
        }, currentLang() === "en" ? "Waterfall" : "Waterfall 瀑布"),
      ),
      h("div", { className: "run-section" },
        h("div", { className: "run-section-title" }, t("run.section.requirement")),
        h("div", { className: "run-requirement-text" }, run.requirement_text || ""),
      ),
      h("div", { className: "run-stats" },
        h("div", { className: "run-stat" }, h("span", { className: "run-stat-value" }, stages.length), h("span", { className: "run-stat-label" }, t("run.stat.stages"))),
        h("div", { className: "run-stat" }, h("span", { className: "run-stat-value" }, requests.length), h("span", { className: "run-stat-label" }, t("run.stat.dispatches"))),
        h("div", { className: "run-stat" }, h("span", { className: "run-stat-value" }, completed), h("span", { className: "run-stat-label" }, t("run.stat.completed"))),
        failed > 0 ? h("div", { className: "run-stat run-stat-error" }, h("span", { className: "run-stat-value" }, failed), h("span", { className: "run-stat-label" }, t("run.stat.failed"))) : null,
      ),
      // View switcher: "timeline" = current stage-progress + A2A log;
      // "agents" = the agent-interaction graph. Persists only for the
      // life of the component (simple UI preference, not a deep link).
      h("div", { className: "run-view-tabs", role: "tablist" },
        ["timeline", "agents"].map((key) => h(
          "button",
          {
            key: key,
            type: "button",
            role: "tab",
            "aria-selected": runView === key ? "true" : "false",
            className: "run-view-tab" + (runView === key ? " run-view-tab-active" : ""),
            onClick: function () { setRunView(key); },
          },
          t("run.view." + key),
        )),
      ),
      runView === "agents" ? h(AgentInteractionView, {
        taskLog: taskLog,
        orchestratorName: (project.info || {}).orchestrator_name || null,
        taskResponseByTaskId: taskResponseByTaskId,
        isRunning: isRunning,
      }) : null,
      runView === "timeline" && stages.length > 0 ? h("div", { className: "run-section" },
        h("div", { className: "run-section-title" }, t("run.section.stage_progress") + (stageFilter ? t("run.section.stage_progress_filter_hint") : "")),
        h("div", { className: "run-stages-flow" },
          stages.map((s, i) => {
            var lastStageIdx = stages.length - 1;
            var isDone = isRunning ? i < lastStageIdx : true;
            var isCurrent = isRunning && i === lastStageIdx;
            var cls = "run-stage-chip run-stage-clickable"
              + (stageFilter === s ? " run-stage-selected" : "")
              + (isDone && !isCurrent ? " run-stage-done" : "")
              + (isCurrent ? " run-stage-active" : "");
            return h(window.React.Fragment, { key: s },
              i > 0 ? h("span", { className: "run-stage-arrow" + (isDone ? " run-stage-arrow-done" : "") }, "\u2192") : null,
              h("span", { className: cls, onClick: function() { toggleStage(s); } }, resolveChipLabel(s) || s),
            );
          }),
        ),
      ) : null,
      runView === "timeline" ? h("div", { className: "run-section" },
        h("div", { className: "run-section-title" }, t("run.section.log_title") + " (" + filteredLog.length + (stageFilter ? " / " + taskLog.length : "") + ")"),
        filteredLog.length === 0
          ? h("div", { className: "run-log-empty" }, isRunning ? t("run.log.waiting") : t("run.log.empty"))
          : h("div", { className: "run-task-log" }, filteredLog.map((ev, idx) => h(RunLogEntry, {
              key: idx,
              event: ev,
              taskTodos: taskTodos,
              taskResponse: ev.taskId ? taskResponseByTaskId[ev.taskId] : null,
            }))),
      ) : null,
      // The delivery report (``run.result``) is produced by Phase 6 /
      // the ``delivery`` stage. It's noisy to show on every view of the
      // run detail page, so scope it: only render when the user has
      // actively filtered the log to the delivery stage (by clicking
      // the delivery chip). When no filter is applied or a different
      // stage is selected, the report is hidden and the rest of the
      // A2A log takes the space.
      run.result && stageFilter && /deliver/i.test(stageFilter)
        ? h("div", { className: "run-section" },
            h("div", { className: "run-section-title" }, t("run.section.delivery_report")),
            h("pre", { className: "run-result-text" }, run.result),
          )
        : null,
      run.error ? h("div", { className: "run-section run-error-section" },
        h("div", { className: "run-section-title" }, t("run.section.error")),
        h("pre", { className: "run-error-text" }, run.error),
      ) : null,
    );
  }

  // ------------------------------------------------------------------
  // Agent interaction view
  // ------------------------------------------------------------------
  //
  // Parses the run's ``task_log`` into three structures:
  //
  //   agents     — one card per participating agent (orchestrator on
  //                the top row, workers in a grid below). Each agent
  //                carries its running-task count, completed / failed
  //                totals, and its recent task list.
  //   edges      — ``(from → to)`` pairs with a count of dispatches.
  //                Rendered as SVG arrows laid over the grid with a
  //                small count badge.
  //   taskById   — ``taskId`` → {agent, label, status, goal, startedAt}
  //                used to populate the task list under each worker.
  //
  // All computation is derived from ``task_request`` / ``task_response``
  // events that the runtime already emits — no new backend data needed.
  function computeAgentGraph(taskLog, orchestratorName, taskResponseByTaskId) {
    var orchestrator = orchestratorName || "orchestrator";
    var workerSet = new Set();
    var edges = new Map(); // key "fromto" -> count
    var tasksByAgent = new Map();
    var allTasks = [];

    function bumpEdge(from, to) {
      var k = from + "" + to;
      edges.set(k, (edges.get(k) || 0) + 1);
    }

    for (var i = 0; i < taskLog.length; i++) {
      var ev = taskLog[i];
      if (!ev) continue;
      if (ev.type === "task_request" && ev.to) {
        workerSet.add(ev.to);
        bumpEdge(orchestrator, ev.to);
        var payload = ev.payload || {};
        var response = ev.taskId ? taskResponseByTaskId[ev.taskId] : null;
        var respPayload = (response && response.payload) || {};
        var goal = payload.step
          || (payload.task ? String(payload.task).split("\n")[0].slice(0, 80) : "")
          || t("entry.fallback_task_name");
        var status = response ? (response.status || "completed") : "running";
        var outputLen = response ? (respPayload.output_length || 0) : 0;
        var task = {
          taskId: ev.taskId || null,
          agent: ev.to,
          goal: goal,
          phase: payload.phase || "",
          status: status,
          startedAt: ev.timestamp || "",
          completedAt: response ? (response.timestamp || "") : "",
          outputLen: outputLen,
        };
        if (!tasksByAgent.has(ev.to)) tasksByAgent.set(ev.to, []);
        tasksByAgent.get(ev.to).push(task);
        allTasks.push(task);
      }
    }

    // Agents array: orchestrator first, then workers in declaration
    // order (which matches dispatch order — a readable flow).
    var workers = Array.from(workerSet);
    var agents = [{ name: orchestrator, role: "orchestrator" }];
    workers.forEach(function (n) { agents.push({ name: n, role: "worker" }); });

    // Edges as a simple array.
    var edgeArr = [];
    edges.forEach(function (count, key) {
      var parts = key.split("");
      edgeArr.push({ from: parts[0], to: parts[1], count: count });
    });

    // Per-agent status summary.
    agents.forEach(function (a) {
      var tasks = tasksByAgent.get(a.name) || [];
      a.tasks = tasks;
      a.runningCount = tasks.filter(function (t) { return t.status === "running"; }).length;
      a.completedCount = tasks.filter(function (t) { return t.status === "completed"; }).length;
      a.failedCount = tasks.filter(function (t) { return t.status === "failed"; }).length;
    });

    return { agents: agents, edges: edgeArr, tasks: allTasks };
  }

  function AgentStatusBadge({ agent }) {
    const h = window.React.createElement;
    if (agent.runningCount > 0) {
      return h("span", { className: "agent-card-status agent-card-status-working" },
        h("span", { className: "monitor-task-pulse" }),
        t("agents.status.working", { n: agent.runningCount }),
      );
    }
    if (agent.completedCount + agent.failedCount === 0) {
      return h("span", { className: "agent-card-status agent-card-status-idle" }, t("agents.status.idle"));
    }
    return h("span", { className: "agent-card-status agent-card-status-done" }, t("agents.status.done"));
  }

  function AgentCard({ agent }) {
    const h = window.React.createElement;
    // Cap the per-agent task list to the most recent 12 entries so a
    // long-running project with dozens of dispatches per agent stays
    // scannable. Older tasks can still be found via the timeline view.
    var visibleTasks = agent.tasks.slice(-12).reverse();
    return h("div", {
      className: "agent-card agent-card-role-" + agent.role,
      "data-agent-name": agent.name,
    },
      h("div", { className: "agent-card-header" },
        h("span", { className: "agent-card-icon" }, agent.role === "orchestrator" ? "🎯" : "🤖"),
        h("span", { className: "agent-card-name" }, agent.name),
        h("span", { className: "agent-card-role-tag" }, t("agents.role." + agent.role)),
      ),
      h(AgentStatusBadge, { agent: agent }),
      h("div", { className: "agent-card-stats" },
        h("span", { title: t("agents.stat.running") }, "● " + agent.runningCount),
        h("span", { title: t("agents.stat.completed") }, "✓ " + agent.completedCount),
        agent.failedCount > 0
          ? h("span", { className: "agent-card-stat-failed", title: t("agents.stat.failed") }, "✕ " + agent.failedCount)
          : null,
      ),
      h("div", { className: "agent-card-tasks" },
        h("div", { className: "agent-card-tasks-title" }, t("agents.tasks_heading")),
        visibleTasks.length === 0
          ? h("div", { className: "agent-card-tasks-empty" }, t("agents.no_tasks"))
          : h("ul", { className: "agent-card-tasks-list" }, visibleTasks.map(function (task, idx) {
              var statusClass = "agent-task-" + task.status;
              return h("li", { className: "agent-card-task " + statusClass, key: task.taskId || idx },
                h("span", { className: "agent-card-task-icon" },
                  task.status === "running" ? "●" : task.status === "failed" ? "✕" : "✓",
                ),
                h("span", { className: "agent-card-task-goal", title: task.goal }, task.goal),
              );
            })),
      ),
    );
  }

  function AgentInteractionView({ taskLog, orchestratorName, taskResponseByTaskId, isRunning }) {
    const h = window.React.createElement;
    const React = window.React;
    var graph = computeAgentGraph(taskLog, orchestratorName, taskResponseByTaskId);
    var orchestrators = graph.agents.filter(function (a) { return a.role === "orchestrator"; });
    var workers = graph.agents.filter(function (a) { return a.role === "worker"; });

    // Per-worker interaction summary: dispatches + completed + failed
    // counts, keyed by agent name. These numbers land verbatim on the
    // connector label so the orchestrator → worker edge carries the
    // per-pair interaction info, not a single aggregate.
    var interactionByWorker = {};
    workers.forEach(function (w) {
      var tasks = w.tasks || [];
      interactionByWorker[w.name] = {
        dispatches: tasks.length,
        completed: w.completedCount || 0,
        failed: w.failedCount || 0,
      };
    });

    // SVG connector geometry is measured from the DOM after render —
    // one line per worker, anchored at the orchestrator card's
    // bottom-center and terminating at the worker card's top-center.
    // Re-measures when the task log grows, when a new worker joins,
    // and on viewport resize.
    const containerRef = React.useRef(null);
    const [edges, setEdges] = React.useState([]);
    React.useLayoutEffect(function () {
      function measure() {
        var container = containerRef.current;
        if (!container) return;
        var orchEl = container.querySelector(".agent-card-role-orchestrator");
        var workerEls = Array.prototype.slice.call(
          container.querySelectorAll(".agent-card-role-worker")
        );
        if (!orchEl || workerEls.length === 0) {
          setEdges([]);
          return;
        }
        var cRect = container.getBoundingClientRect();
        var oRect = orchEl.getBoundingClientRect();
        var fromX = oRect.left + oRect.width / 2 - cRect.left;
        var fromY = oRect.bottom - cRect.top;
        var next = workerEls.map(function (el) {
          var r = el.getBoundingClientRect();
          var name = el.getAttribute("data-agent-name") || "";
          var info = interactionByWorker[name] || { dispatches: 0, completed: 0, failed: 0 };
          return {
            name: name,
            fromX: fromX,
            fromY: fromY,
            toX: r.left + r.width / 2 - cRect.left,
            toY: r.top - cRect.top,
            dispatches: info.dispatches,
            completed: info.completed,
            failed: info.failed,
          };
        });
        setEdges(next);
      }
      measure();
      window.addEventListener("resize", measure);
      return function () { window.removeEventListener("resize", measure); };
      // Depend on both length fields so new dispatches + new workers
      // trigger a re-measure.
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [taskLog.length, workers.length]);

    if (workers.length === 0) {
      return h("div", { className: "run-section agent-graph-empty" },
        h("div", { className: "run-log-empty" }, isRunning ? t("agents.waiting") : t("agents.no_participants")),
      );
    }

    return h("div", { className: "run-section agent-graph-section" },
      h("div", { className: "run-section-title" }, t("agents.section_title")),
      h("div", { className: "agent-graph-container", ref: containerRef },
        // SVG connector overlay: one ``<line>`` per worker + an
        // HTML label block carried in a ``foreignObject`` at the
        // midpoint. Sits behind the cards (z-index 0) and has
        // pointer-events: none so the cards stay clickable. The
        // ``aria-hidden`` reminds screen readers that the same
        // numbers are already present on each agent card.
        h("svg", {
          className: "agent-graph-connectors",
          "aria-hidden": "true",
          xmlns: "http://www.w3.org/2000/svg",
          preserveAspectRatio: "none",
        },
          h("defs", null,
            h("marker", {
              id: "agent-graph-arrow",
              viewBox: "0 0 10 10",
              refX: "9",
              refY: "5",
              markerWidth: "8",
              markerHeight: "8",
              orient: "auto-start-reverse",
            },
              h("path", { d: "M 0 0 L 10 5 L 0 10 Z", className: "agent-graph-arrow-head" }),
            ),
          ),
          edges.map(function (e) {
            var midX = (e.fromX + e.toX) / 2;
            var midY = (e.fromY + e.toY) / 2;
            return h("g", { key: e.name, className: "agent-graph-connector-group" },
              h("line", {
                x1: e.fromX,
                y1: e.fromY,
                x2: e.toX,
                y2: e.toY,
                className: "agent-graph-connector-line",
                "marker-end": "url(#agent-graph-arrow)",
                "data-from": "orchestrator",
                "data-to": e.name,
              }),
              h("foreignObject", {
                x: midX - 80,
                y: midY - 14,
                width: 160,
                height: 30,
                className: "agent-graph-connector-fo",
              },
                h("div", { className: "agent-graph-connector-label", "data-to": e.name },
                  h("span", { className: "agent-graph-connector-dispatches" }, t("agents.dispatches", { n: e.dispatches })),
                  e.completed > 0 ? h("span", {
                    className: "agent-graph-connector-chip agent-graph-connector-chip-completed",
                    title: t("agents.stat.completed"),
                  }, "✓ " + e.completed) : null,
                  e.failed > 0 ? h("span", {
                    className: "agent-graph-connector-chip agent-graph-connector-chip-failed",
                    title: t("agents.stat.failed"),
                  }, "✕ " + e.failed) : null,
                ),
              ),
            );
          }),
        ),
        h("div", { className: "agent-graph-row agent-graph-row-top" },
          orchestrators.map(function (a) { return h(AgentCard, { key: a.name, agent: a }); }),
        ),
        h("div", {
          className: "agent-graph-row agent-graph-row-workers",
          style: { gridTemplateColumns: "repeat(" + workers.length + ", minmax(0, 1fr))" },
        },
          workers.map(function (a) { return h(AgentCard, { key: a.name, agent: a }); }),
        ),
      ),
    );
  }

  function RunLogEntry({ event, taskTodos, taskResponse }) {
    const h = window.React.createElement;
    const ev = event;
    const ts = ev.timestamp ? formatLocalTime(ev.timestamp) : "";
    const todosForTask = ev && ev.taskId && taskTodos ? taskTodos[ev.taskId] : null;

    // Default-expand running tasks (no response yet); default-collapse
    // completed/failed tasks. A completed task card is a compact summary
    // until the user clicks to open it.
    const taskIsRunning = ev.type === "task_request" && !taskResponse;
    const [expanded, setExpanded] = window.React.useState(taskIsRunning);

    if (ev.type === "stage_update") {
      return h("div", { className: "run-log-entry run-log-stage", onClick: function() { setExpanded(!expanded); } },
        h("div", { className: "run-log-row" },
          h("span", { className: "run-log-toggle" }, expanded ? "▼" : "▶"),
          h("span", { className: "run-log-stage-label" }, resolveStageLabel(ev.stage) || ev.stage),
          h("span", { className: "run-log-ts" }, ts),
        ),
        expanded ? h("div", { className: "run-log-body run-log-stage-detail" },
          h("div", { className: "run-log-meta" }, t("entry.meta.stage") + ev.stage),
          ev.status ? h("div", { className: "run-log-meta" }, t("entry.meta.status") + ev.status) : null,
        ) : null,
      );
    }

    if (ev.type === "tool_call") {
      // Collapse tool_call details by default — the summary is only
      // shown when the user expands. Keeps the main log uncluttered.
      return h("div", { className: "run-log-entry run-log-tool" + (expanded ? " run-log-expanded" : ""), onClick: function() { setExpanded(!expanded); } },
        h("div", { className: "run-log-row" },
          h("span", { className: "run-log-toggle" }, expanded ? "\u25bc" : "\u25b6"),
          h("span", { className: "run-log-icon" }, EVENT_ICONS.tool_call),
          h("span", { className: "run-log-tool-name" }, ev.tool || t("entry.tool_fallback_name")),
          h("span", { className: "run-log-ts" }, ts),
        ),
        expanded ? h("div", { className: "run-log-body" },
          ev.summary ? h("pre", { className: "run-log-full-text" }, ev.summary) : h("div", { className: "run-log-meta" }, t("entry.summary_no_summary")),
        ) : null,
      );
    }

    if (ev.type === "task_request") {
      var payload = ev.payload || {};
      var fullTask = payload.task || "";
      // The task row shows the task's GOAL (what it is, not the full
      // description text sent to the worker). Prefer ``payload.step``
      // (e.g. "impl_config_loader", "phase_2_design") — it is the
      // orchestrator's short identifier for what the task accomplishes.
      // Fall back to the first line of the task description, which is
      // typically a goal-like sentence.
      var goalText =
        payload.step ||
        (fullTask ? fullTask.split("\n")[0].slice(0, 100) : "") ||
        t("entry.fallback_task_name");
      var response = taskResponse || null;
      var responsePayload = (response && response.payload) || {};
      var responseStatus = response ? response.status : null;
      var outputText = response
        ? String(responsePayload.output_preview || responsePayload.output || responsePayload.error || "")
        : "";
      var outputLen = response ? (responsePayload.output_length || outputText.length) : 0;
      var savedTo = response ? (responsePayload.saved_to || "") : "";
      var displayStatus = responseStatus || "running";
      var statusTagCls = responseStatus === "completed" ? "log-completed"
        : responseStatus === "failed" ? "log-failed"
        : "log-running";
      // Todos are always visible for running tasks (live progress cue),
      // and only shown for completed tasks when the card is expanded.
      var showTodos = todosForTask && (!response || expanded);
      return h("div", { className: "run-log-entry run-log-request " + statusTagCls + (expanded ? " run-log-expanded" : "") },
        h("div", { className: "run-log-row", onClick: function() { setExpanded(!expanded); } },
          h("span", { className: "run-log-toggle" }, expanded ? "\u25bc" : "\u25b6"),
          h("span", { className: "run-log-icon" }, EVENT_ICONS.task_request),
          h("span", { className: "run-log-agent" }, ev.to),
          payload.phase ? h("span", { className: "run-log-phase-tag" }, payload.phase) : null,
          h("span", { className: "run-log-status-tag " + statusTagCls },
            response
              ? (responseStatus === "completed" ? t("entry.status.completed")
                 : responseStatus === "failed" ? t("entry.status.failed")
                 : responseStatus)
              : t("entry.status.running"),
          ),
          h("span", { className: "run-log-detail" }, goalText),
          h("span", { className: "run-log-ts" }, ts),
        ),
        showTodos ? h(TaskTodoProgress, { todos: todosForTask }) : null,
        expanded ? h("div", { className: "run-log-body" },
          h("div", { className: "run-log-response-meta" },
            ev.taskId ? h("span", null, t("entry.meta.task_id") + ev.taskId) : null,
            payload.step ? h("span", null, t("entry.meta.step") + payload.step) : null,
            payload.phase ? h("span", null, t("entry.meta.phase") + payload.phase) : null,
            outputLen > 0 ? h("span", null, t("entry.meta.output", { n: outputLen })) : null,
            savedTo ? h("span", null, "\u2713 " + savedTo) : null,
          ),
          fullTask ? h("div", { className: "run-log-subsection" },
            h("div", { className: "run-log-subsection-title" }, t("entry.task_description_title")),
            h("pre", { className: "run-log-full-text" }, fullTask),
          ) : null,
          response ? h("div", { className: "run-log-subsection" },
            h("div", { className: "run-log-subsection-title" }, t("entry.execution_result_title")),
            outputText
              ? h("pre", { className: "run-log-full-text" }, outputText)
              : h("div", { className: "run-log-meta" }, t("entry.no_text_output")),
          ) : null,
        ) : null,
      );
    }

    return h("div", { className: "run-log-entry" },
      h("span", { className: "run-log-icon" }, "\u00b7"),
      h("span", null, ev.type || "event"),
      h("span", { className: "run-log-ts" }, ts),
    );
  }

  mountReact("run-react-root", () => window.React.createElement(RunApp));
}

function setupTaskReact() {
  const initial = readScriptJson("task-initial-data", null);
  if (!initial) return;

  function TaskApp() {
    const h = window.React.createElement;
    const task = initial.task || {};
    return h(
      "section",
      { className: "card card-glow" },
      h("h1", null, t("task.title")),
      h("p", null, `${t("task.field.phase")}: ${initial.phase_name}`),
      h("p", null, `${t("task.field.task_key")}: ${initial.task_key}`),
      h("p", null, `${t("task.field.status")}: ${task.status || ""}`),
      task.artifact_id ? h("p", null, `${t("task.field.artifact_id")}: ${task.artifact_id}`) : null,
      task.error ? h("pre", { className: "error" }, task.error) : null,
      h(
        "a",
        {
          className: "btn secondary",
          href: `/projects/${encodeURIComponent(initial.project_id)}/runs/${encodeURIComponent(initial.run_id)}`,
        },
        t("task.back_to_run"),
      )
    );
  }

  mountReact("task-react-root", () => window.React.createElement(TaskApp));
}

function setupLoginReact() {
  const initial = readScriptJson("login-initial-data", {
    local_admin_username: "admin",
    error: null,
    configured: {},
  });

  function LoginApp() {
    const h = window.React.createElement;
    const configured = initial.configured || {};
    return h(
      "section",
      { className: "card narrow card-glow login-card" },
      h("h1", null, "⚡ 登录 AISE Web"),
      h("p", { className: "muted" }, "支持内置管理员账号、Google 或 Microsoft 登录。"),
      h(
        "form",
        { method: "post", action: "/auth/local-login", className: "stack" },
        h("label", null, "用户名"),
        h("input", { name: "username", required: true, defaultValue: initial.local_admin_username || "admin" }),
        h("label", null, "密码"),
        h("input", { name: "password", type: "password", required: true, placeholder: "请输入密码" }),
        h("button", { className: "btn", type: "submit" }, "管理员登录")
      ),
      initial.error ? h("p", { className: "warning" }, initial.error) : null,
      h("p", { className: "muted" }, ["默认内置账号: ", h("code", { key: "u" }, "admin"), " / ", h("code", { key: "p" }, "123456")]),
      h(
        "div",
        { className: "auth-grid" },
        h("a", { className: "btn", href: "/auth/google" }, "使用 Google 登录"),
        h("a", { className: "btn", href: "/auth/microsoft" }, "使用 Microsoft 登录"),
        configured.dev_login_enabled ? h("a", { className: "btn secondary", href: "/auth/dev-login" }, "开发环境快速登录") : null
      ),
      !configured.oauth_enabled ? h("p", { className: "warning" }, "未安装 OAuth 依赖，请安装 web 依赖后重试。") : null,
      !configured.google ? h("p", { className: "warning" }, "GOOGLE_CLIENT_ID 未配置。") : null,
      !configured.microsoft ? h("p", { className: "warning" }, "MICROSOFT_CLIENT_ID 未配置。") : null
    );
  }

  mountReact("login-react-root", () => window.React.createElement(LoginApp));
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

  function createProviderRow(provider) {
    const row = document.createElement("div");
    row.className = "provider-row";
    row.innerHTML = `
      <input class="provider-name" placeholder="provider" value="${escapeHtml((provider && provider.provider) || "")}">
      <input class="provider-key" placeholder="api key" value="${escapeHtml((provider && provider.api_key) || "")}">
      <input class="provider-uri" placeholder="base url" value="${escapeHtml((provider && provider.base_url) || "")}">
      <label><input type="checkbox" class="provider-enabled" ${(provider && provider.enabled) !== false ? "checked" : ""}>启用</label>
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

  function createModelCard(model) {
    const card = document.createElement("div");
    card.className = "model-card";
    const modelValue = model || {};
    const isLocal = !!modelValue.is_local;
    card.innerHTML = `
      <div class="stack">
        <label>模型ID</label>
        <input class="model-id" placeholder="例如 gpt-4o" value="${escapeHtml(modelValue.id || "")}">
        <label>API 模型名（OpenAI model 字段）</label>
        <input class="model-api-model" placeholder="例如 gpt-4o" value="${escapeHtml(modelValue.api_model || modelValue.id || "")}">
        <label class="inline-radio"><input type="radio" name="model-default-flag" class="model-default" ${modelValue.default ? "checked" : ""}> 设为默认模型</label>
        <label><input type="checkbox" class="model-is-local" ${isLocal ? "checked" : ""}> 本地模型（无需 providers）</label>
        <label>默认 Provider</label>
        <select class="model-default-provider"></select>
        <label>扩展参数（JSON）</label>
        <textarea class="model-extra" rows="3" placeholder='{"supports_tools": true}'>${escapeHtml(JSON.stringify(modelValue.extra || {}, null, 2))}</textarea>
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
    const presetProviders = Array.isArray(modelValue.providers) ? modelValue.providers.map((p) => String(p)) : [];

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
        defaultSelect.innerHTML = '<option value="local">local</option>';
        defaultSelect.value = "local";
        return;
      }
      const options = selectedNow.length ? selectedNow : available;
      defaultSelect.innerHTML = options.map((name) => `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`).join("");
      defaultSelect.value = options.includes(String(modelValue.default_provider || "")) ? String(modelValue.default_provider || "") : (options[0] || "");
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

/* ═══════════════════════════════════════════════════════════════
   Monitor Page — Real-time agent status dashboard
   ═══════════════════════════════════════════════════════════════ */

function setupMonitorReact() {
  const initial = readScriptJson("monitor-initial-data", { agents: [], active_runs: 0, active_retries: 0 });

  const ROLE_LABELS = {
    product_manager: "Product Manager",
    architect: "Architect",
    developer: "Developer",
    qa_engineer: "QA Engineer",
    project_manager: "Project Manager",
    rd_director: "R&D Director",
    reviewer: "Reviewer",
  };

  const ROLE_ICONS = {
    product_manager: "\uD83D\uDCCB",
    architect: "\uD83C\uDFD7\uFE0F",
    developer: "\uD83D\uDCBB",
    qa_engineer: "\uD83D\uDD0D",
    project_manager: "\uD83D\uDCC8",
    rd_director: "\uD83C\uDFAF",
    reviewer: "\uD83D\uDCDD",
  };

  const STATUS_META = {
    working: { label: "\u6267\u884C\u4E2D", cls: "monitor-status-working" },
    idle:    { label: "\u7A7A\u95F2",       cls: "monitor-status-idle" },
    standby: { label: "\u5F85\u547D",       cls: "monitor-status-standby" },
  };

  function MonitorApp() {
    const h = window.React.createElement;
    const [data, setData] = window.React.useState(initial);
    const [selected, setSelected] = window.React.useState(null);
    const [filter, setFilter] = window.React.useState(null); // null = all, "working" / "idle" / "standby"

    window.React.useEffect(() => {
      let active = true;
      const poll = () => {
        fetchJson("/api/monitor")
          .then((d) => { if (active) setData(d); })
          .catch(() => {});
      };
      const tid = setInterval(poll, 3000);
      return () => { active = false; clearInterval(tid); };
    }, []);

    const agents = Array.isArray(data.agents) ? data.agents : [];
    const workingCount = agents.filter((a) => a.status === "working").length;
    const idleCount = agents.filter((a) => a.status === "idle").length;
    const standbyCount = agents.filter((a) => a.status === "standby").length;
    const filtered = filter ? agents.filter((a) => a.status === filter) : agents;

    const toggle = (status) => setFilter((prev) => prev === status ? null : status);

    return h("div", { className: "monitor-container" },
      // Header
      h("div", { className: "monitor-header" },
        h("h1", { className: "monitor-title" }, "Agent Monitor"),
        h("p", { className: "monitor-subtitle" }, "\u5B9E\u65F6\u67E5\u770B Agent \u72B6\u6001\u4E0E\u4EFB\u52A1"),
      ),

      // Summary cards (clickable filter)
      h("div", { className: "monitor-summary" },
        h(SummaryCard, { label: "Agent \u603B\u6570", value: agents.length, cls: "summary-total", active: filter === null, onClick: () => setFilter(null) }),
        h(SummaryCard, { label: "\u6267\u884C\u4E2D", value: workingCount, cls: "summary-working", active: filter === "working", onClick: () => toggle("working") }),
        h(SummaryCard, { label: "\u7A7A\u95F2", value: idleCount, cls: "summary-idle", active: filter === "idle", onClick: () => toggle("idle") }),
        h(SummaryCard, { label: "\u5F85\u547D", value: standbyCount, cls: "summary-standby", active: filter === "standby", onClick: () => toggle("standby") }),
        h(SummaryCard, { label: "\u6D3B\u8DC3\u8FD0\u884C", value: data.active_runs || 0, cls: "summary-runs summary-info" }),
      ),

      // Agent grid (filtered)
      filtered.length === 0
        ? h("div", { className: "monitor-empty" },
            filter
              ? "\u6CA1\u6709\u5904\u4E8E\u201C" + (STATUS_META[filter] || {}).label + "\u201D\u72B6\u6001\u7684 Agent"
              : "\u6682\u65E0\u6D3B\u8DC3 Agent\u3002\u8BF7\u5148\u521B\u5EFA\u9879\u76EE\u5E76\u63D0\u4EA4\u9700\u6C42\u3002",
          )
        : h("div", { className: "monitor-grid" },
            filtered.map((agent) => h(AgentCard, { key: agent.agent_id, agent: agent, onSelect: setSelected })),
          ),

      // Detail modal
      selected ? h(AgentDetailModal, { agent: selected, onClose: () => setSelected(null) }) : null,
    );
  }

  function SummaryCard({ label, value, cls, active, onClick }) {
    const h = window.React.createElement;
    const classes = "monitor-summary-card " + (cls || "") + (active ? " monitor-summary-active" : "") + (onClick ? " monitor-summary-clickable" : "");
    return h("div", { className: classes, onClick: onClick || null },
      h("div", { className: "monitor-summary-value" }, value),
      h("div", { className: "monitor-summary-label" }, label),
    );
  }

  function AgentCard({ agent, onSelect }) {
    const h = window.React.createElement;
    const statusMeta = STATUS_META[agent.status] || STATUS_META.standby;
    const roleLabel = agent.role_display || ROLE_LABELS[agent.role] || agent.role;
    const roleIcon = ROLE_ICONS[agent.role] || "\uD83E\uDD16";
    const modelStr = agent.model && agent.model.model ? agent.model.model : "\u672A\u914D\u7F6E";
    const task = agent.current_task;
    const isRuntime = agent.source === "runtime";

    return h("div", {
      className: "monitor-agent-card monitor-agent-card-clickable " + statusMeta.cls,
      onClick: () => onSelect && onSelect(agent),
    },
      // Card header
      h("div", { className: "monitor-agent-header" },
        h("span", { className: "monitor-agent-icon" }, roleIcon),
        h("div", { className: "monitor-agent-identity" },
          h("div", { className: "monitor-agent-name" },
            agent.name,
            isRuntime ? h("span", { className: "monitor-source-tag" }, "Runtime") : null,
          ),
          h("div", { className: "monitor-agent-role" }, roleLabel),
        ),
        h("span", { className: "monitor-agent-status-badge" }, statusMeta.label),
      ),

      // Card body
      h("div", { className: "monitor-agent-body" },
        // Project (only for project-bound agents)
        agent.project_id
          ? h("div", { className: "monitor-agent-field" },
              h("span", { className: "monitor-field-label" }, "\u9879\u76EE"),
              h("span", { className: "monitor-field-value" },
                h("a", { href: "/projects/" + agent.project_id }, agent.project_name),
              ),
            )
          : null,
        // Model
        h("div", { className: "monitor-agent-field" },
          h("span", { className: "monitor-field-label" }, "\u6A21\u578B"),
          h("span", { className: "monitor-field-value monitor-model-tag" }, modelStr),
        ),
        // Skills
        h("div", { className: "monitor-agent-field" },
          h("span", { className: "monitor-field-label" }, "\u6280\u80FD"),
          h("div", { className: "monitor-skills-list" },
            (agent.skills || []).length > 0
              ? agent.skills.map((s) => h("span", { key: s, className: "monitor-skill-tag" }, s))
              : h("span", { className: "monitor-field-muted" }, "\u65E0"),
          ),
        ),
      ),

      // Current task
      task
        ? h("div", { className: "monitor-agent-task" },
            h("div", { className: "monitor-task-header" },
              h("span", { className: "monitor-task-pulse" }),
              h("span", null, "\u5F53\u524D\u4EFB\u52A1"),
            ),
            h("div", { className: "monitor-task-name" }, task.display_name || task.task_key),
            task.phase
              ? h("div", { className: "monitor-task-phase" }, "\u9636\u6BB5: " + task.phase)
              : null,
          )
        : null,
    );
  }

  function AgentDetailModal({ agent, onClose }) {
    const h = window.React.createElement;
    const card = agent.agent_card || {};
    const roleLabel = agent.role_display || ROLE_LABELS[agent.role] || agent.role;
    const roleIcon = ROLE_ICONS[agent.role] || "\uD83E\uDD16";
    const skills = card.skills || [];
    const caps = card.capabilities || {};
    const modelInfo = card.model || agent.model || {};
    const provider = card.provider || {};

    return h("div", { className: "monitor-modal-overlay", onClick: (e) => { if (e.target === e.currentTarget) onClose(); } },
      h("div", { className: "monitor-modal" },
        // Modal header
        h("div", { className: "monitor-modal-header" },
          h("div", { className: "monitor-modal-title-row" },
            h("span", { className: "monitor-agent-icon" }, roleIcon),
            h("div", null,
              h("h2", { className: "monitor-modal-title" }, card.name || agent.name),
              h("div", { className: "monitor-modal-role" }, roleLabel),
            ),
          ),
          h("button", { className: "monitor-modal-close", onClick: onClose }, "\u00D7"),
        ),

        // Modal body
        h("div", { className: "monitor-modal-body" },

          // Description
          card.description
            ? h("div", { className: "monitor-modal-section" },
                h("div", { className: "monitor-modal-section-title" }, "Description"),
                h("p", { className: "monitor-modal-text" }, card.description),
              )
            : null,

          // Model info
          h("div", { className: "monitor-modal-section" },
            h("div", { className: "monitor-modal-section-title" }, "Model"),
            h("div", { className: "monitor-modal-kv-grid" },
              h("span", { className: "monitor-modal-kv-label" }, "Provider"),
              h("span", { className: "monitor-modal-kv-value" }, modelInfo.provider || "-"),
              h("span", { className: "monitor-modal-kv-label" }, "Model"),
              h("code", { className: "monitor-modal-kv-value monitor-model-tag" }, modelInfo.model || "-"),
              modelInfo.temperature != null
                ? [
                    h("span", { key: "t-l", className: "monitor-modal-kv-label" }, "Temperature"),
                    h("span", { key: "t-v", className: "monitor-modal-kv-value" }, modelInfo.temperature),
                  ]
                : null,
              modelInfo.maxTokens != null
                ? [
                    h("span", { key: "m-l", className: "monitor-modal-kv-label" }, "Max Tokens"),
                    h("span", { key: "m-v", className: "monitor-modal-kv-value" }, modelInfo.maxTokens),
                  ]
                : null,
            ),
          ),

          // Capabilities
          h("div", { className: "monitor-modal-section" },
            h("div", { className: "monitor-modal-section-title" }, "Capabilities"),
            h("div", { className: "monitor-modal-caps" },
              Object.entries(caps).map(([k, v]) =>
                h("span", { key: k, className: "monitor-modal-cap-tag " + (v ? "cap-on" : "cap-off") },
                  (v ? "\u2713 " : "\u2717 ") + k,
                ),
              ),
            ),
          ),

          // Provider
          provider.organization
            ? h("div", { className: "monitor-modal-section" },
                h("div", { className: "monitor-modal-section-title" }, "Provider"),
                h("div", { className: "monitor-modal-text" }, provider.organization + (provider.url ? " \u00B7 " + provider.url : "")),
              )
            : null,

          // Protocol info
          h("div", { className: "monitor-modal-section" },
            h("div", { className: "monitor-modal-section-title" }, "Protocol"),
            h("div", { className: "monitor-modal-kv-grid" },
              h("span", { className: "monitor-modal-kv-label" }, "Version"),
              h("span", { className: "monitor-modal-kv-value" }, card.version || "1.0.0"),
              h("span", { className: "monitor-modal-kv-label" }, "Input Modes"),
              h("span", { className: "monitor-modal-kv-value" }, (card.defaultInputModes || ["text"]).join(", ")),
              h("span", { className: "monitor-modal-kv-label" }, "Output Modes"),
              h("span", { className: "monitor-modal-kv-value" }, (card.defaultOutputModes || ["text"]).join(", ")),
            ),
          ),

          // Skills detail table
          h("div", { className: "monitor-modal-section" },
            h("div", { className: "monitor-modal-section-title" }, "Skills (" + skills.length + ")"),
            skills.length > 0
              ? h("table", { className: "monitor-modal-skills-table" },
                  h("thead", null,
                    h("tr", null,
                      h("th", null, "ID"),
                      h("th", null, "Name"),
                      h("th", null, "Description"),
                    ),
                  ),
                  h("tbody", null,
                    skills.map((s) =>
                      h("tr", { key: s.id },
                        h("td", null, h("code", null, s.id)),
                        h("td", null, s.name),
                        h("td", null, s.description || "-"),
                      ),
                    ),
                  ),
                )
              : h("div", { className: "monitor-field-muted" }, "\u65E0\u6280\u80FD"),
          ),
        ),
      ),
    );
  }

  mountReact("monitor-react-root", () => window.React.createElement(MonitorApp));
}

document.addEventListener("DOMContentLoaded", () => {
  // Wait for i18next to finish loading its resource files before
  // mounting any React tree. First paint therefore has the correct
  // translations — no flash of raw ``stage.xxx`` keys.
  initI18n().finally(() => {
    setupDashboardReact();
    setupProjectReact();
    setupRunReact();
    setupTaskReact();
    setupLoginReact();
    setupModelsConfigPage();
    setupMonitorReact();
  });
});
