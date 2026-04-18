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

function formatLocalTime(ts) {
  if (!ts) return "";
  try {
    const d = new Date(ts);
    if (isNaN(d.getTime())) return String(ts);
    return d.toLocaleString("zh-CN", {
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

  const STAGE_LABELS = {
    process_selection: "流程选择",
    team_assembly: "团队组建",
    workflow_planning: "流程规划",
    execution: "任务执行",
    phase_1_requirement: "需求分析",
    phase_2_design: "架构设计",
    phase_3_implementation: "开发实现",
    phase_4_verification: "测试验证",
    requirement: "需求分析",
    design: "架构设计",
    implementation: "开发实现",
    testing: "测试验证",
    sprint_planning: "迭代规划",
    sprint_execution: "快速开发",
    sprint_review: "迭代评审",
  };

  // Dynamic stage label resolver (handles implementation_cycle_1, etc.)
  function resolveStageLabel(stage) {
    if (STAGE_LABELS[stage]) return STAGE_LABELS[stage];
    var cycleMatch = stage.match(/^(.+)_cycle_(\d+)$/);
    if (cycleMatch) {
      var base = STAGE_LABELS[cycleMatch[1]] || cycleMatch[1];
      return base + " #" + cycleMatch[2];
    }
    return stage;
  }

  const EVENT_ICONS = {
    stage_update: "▶",
    tool_call: "⚙",
    task_request: "→",
    task_response: "←",
    parallel_start: "≡",
  };

  const TODO_STATUS_LABEL = {
    pending: "待处理",
    in_progress: "进行中",
    completed: "已完成",
  };

  function TaskTodoProgress({ todos }) {
    const h = window.React.createElement;
    if (!Array.isArray(todos) || todos.length === 0) return null;
    var total = todos.length;
    var done = todos.filter((t) => t && t.status === "completed").length;
    return h("div", { className: "run-log-todos" },
      h("div", { className: "run-log-todos-header" },
        h("span", { className: "run-log-todos-title" }, "任务步骤"),
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
            h("span", { className: "run-log-todo-status" }, TODO_STATUS_LABEL[status] || status),
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

    // Derive stages and tag each event with its stage
    const stages = [];
    const stageSet = new Set();
    let curStage = null;
    const evStages = taskLog.map((ev) => {
      if (ev.type === "stage_update" && ev.stage) {
        curStage = ev.stage;
        if (!stageSet.has(ev.stage)) { stageSet.add(ev.stage); stages.push(ev.stage); }
      }
      return curStage;
    });
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
    const visibleStages = taskLog
      .map((_, i) => evStages[i])
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
          h("a", { className: "run-back-link", href: "/projects/" + project.info.project_id }, "\u2190 " + (project.info.name || "Project")),
          h("h1", { className: "run-title" }, "\u6267\u884c\u8be6\u60c5"),
          h("span", { className: "run-id-label" }, run.run_id),
        ),
        h("span", { className: "run-status-badge " + statusCls },
          isRunning ? h("span", { className: "monitor-task-pulse" }) : null,
          runStatus === "completed" ? "\u5df2\u5b8c\u6210" : runStatus === "failed" ? "\u5931\u8d25" : runStatus === "running" ? "\u8fd0\u884c\u4e2d" : "\u7b49\u5f85",
        ),
      ),
      h("div", { className: "run-section" },
        h("div", { className: "run-section-title" }, "\u9700\u6c42"),
        h("div", { className: "run-requirement-text" }, run.requirement_text || ""),
      ),
      h("div", { className: "run-stats" },
        h("div", { className: "run-stat" }, h("span", { className: "run-stat-value" }, stages.length), h("span", { className: "run-stat-label" }, "\u9636\u6bb5")),
        h("div", { className: "run-stat" }, h("span", { className: "run-stat-value" }, requests.length), h("span", { className: "run-stat-label" }, "\u4efb\u52a1\u6d3e\u53d1")),
        h("div", { className: "run-stat" }, h("span", { className: "run-stat-value" }, completed), h("span", { className: "run-stat-label" }, "\u5df2\u5b8c\u6210")),
        failed > 0 ? h("div", { className: "run-stat run-stat-error" }, h("span", { className: "run-stat-value" }, failed), h("span", { className: "run-stat-label" }, "\u5931\u8d25")) : null,
      ),
      stages.length > 0 ? h("div", { className: "run-section" },
        h("div", { className: "run-section-title" }, "\u9636\u6bb5\u8fdb\u5ea6" + (stageFilter ? " \u2014 \u70b9\u51fb\u53d6\u6d88\u7b5b\u9009" : "")),
        h("div", { className: "run-stages-flow" },
          stages.map((s, i) => {
            var lastStageIdx = stages.length - 1;
            var isDone = isRunning ? i < lastStageIdx : true;
            var isCurrent = isRunning && i === lastStageIdx;
            var isCycle = /_cycle_\d+$/.test(s);
            var cls = "run-stage-chip run-stage-clickable"
              + (isCycle ? " run-stage-cycle" : "")
              + (stageFilter === s ? " run-stage-selected" : "")
              + (isDone && !isCurrent ? " run-stage-done" : "")
              + (isCurrent ? " run-stage-active" : "");
            return h(window.React.Fragment, { key: s },
              i > 0 ? h("span", { className: "run-stage-arrow" + (isDone ? " run-stage-arrow-done" : "") }, "\u2192") : null,
              h("span", { className: cls, onClick: function() { toggleStage(s); } }, resolveStageLabel(s) || s),
            );
          }),
        ),
      ) : null,
      h("div", { className: "run-section" },
        h("div", { className: "run-section-title" }, "A2A \u4efb\u52a1\u65e5\u5fd7 (" + filteredLog.length + (stageFilter ? " / " + taskLog.length : "") + ")"),
        filteredLog.length === 0
          ? h("div", { className: "run-log-empty" }, isRunning ? "\u7b49\u5f85\u4efb\u52a1\u6d3e\u53d1..." : "\u65e0\u4efb\u52a1\u65e5\u5fd7")
          : h("div", { className: "run-task-log" }, filteredLog.map((ev, idx) => h(RunLogEntry, {
              key: idx,
              event: ev,
              taskTodos: taskTodos,
              taskResponse: ev.taskId ? taskResponseByTaskId[ev.taskId] : null,
            }))),
      ),
      run.result ? h("div", { className: "run-section" },
        h("div", { className: "run-section-title" }, "\u4ea4\u4ed8\u62a5\u544a"),
        h("pre", { className: "run-result-text" }, run.result),
      ) : null,
      run.error ? h("div", { className: "run-section run-error-section" },
        h("div", { className: "run-section-title" }, "\u9519\u8bef"),
        h("pre", { className: "run-error-text" }, run.error),
      ) : null,
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
          h("div", { className: "run-log-meta" }, "Stage: " + ev.stage),
          ev.status ? h("div", { className: "run-log-meta" }, "Status: " + ev.status) : null,
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
          h("span", { className: "run-log-tool-name" }, ev.tool || "tool"),
          h("span", { className: "run-log-ts" }, ts),
        ),
        expanded ? h("div", { className: "run-log-body" },
          ev.summary ? h("pre", { className: "run-log-full-text" }, ev.summary) : h("div", { className: "run-log-meta" }, "(no summary)"),
        ) : null,
      );
    }

    if (ev.type === "task_request") {
      var payload = ev.payload || {};
      var fullTask = payload.task || "";
      var preview = fullTask.length > 120 ? fullTask.substring(0, 120) + "..." : fullTask;
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
              ? (responseStatus === "completed" ? "✓ 已完成" : responseStatus === "failed" ? "✕ 失败" : responseStatus)
              : "● 进行中",
          ),
          h("span", { className: "run-log-detail" }, expanded ? "" : preview),
          h("span", { className: "run-log-ts" }, ts),
        ),
        showTodos ? h(TaskTodoProgress, { todos: todosForTask }) : null,
        expanded ? h("div", { className: "run-log-body" },
          h("div", { className: "run-log-response-meta" },
            ev.taskId ? h("span", null, "Task: " + ev.taskId) : null,
            payload.step ? h("span", null, "Step: " + payload.step) : null,
            payload.phase ? h("span", null, "Phase: " + payload.phase) : null,
            outputLen > 0 ? h("span", null, "Output: " + outputLen + " chars") : null,
            savedTo ? h("span", null, "\u2713 " + savedTo) : null,
          ),
          fullTask ? h("div", { className: "run-log-subsection" },
            h("div", { className: "run-log-subsection-title" }, "任务描述"),
            h("pre", { className: "run-log-full-text" }, fullTask),
          ) : null,
          response ? h("div", { className: "run-log-subsection" },
            h("div", { className: "run-log-subsection-title" }, "执行结果"),
            outputText
              ? h("pre", { className: "run-log-full-text" }, outputText)
              : h("div", { className: "run-log-meta" }, "(no text output — agent wrote files directly)"),
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
      h("h1", null, "任务详情"),
      h("p", null, `阶段: ${initial.phase_name}`),
      h("p", null, `任务: ${initial.task_key}`),
      h("p", null, `状态: ${task.status || ""}`),
      task.artifact_id ? h("p", null, `产物ID: ${task.artifact_id}`) : null,
      task.error ? h("pre", { className: "error" }, task.error) : null,
      h(
        "a",
        {
          className: "btn secondary",
          href: `/projects/${encodeURIComponent(initial.project_id)}/runs/${encodeURIComponent(initial.run_id)}`,
        },
        "返回执行详情"
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
  setupDashboardReact();
  setupProjectReact();
  setupRunReact();
  setupTaskReact();
  setupLoginReact();
  setupModelsConfigPage();
  setupMonitorReact();
});
