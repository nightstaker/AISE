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

function setupDashboardReact() {
  const initial = readScriptJson("dashboard-initial-data", { projects: [], global_config_data: {} });

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

    async function deleteProject(project) {
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

    const projectCards = projects.length
      ? projects.map((project) =>
          h(
            "div",
            {
              key: project.project_id,
              className: "project-card",
            },
            h(
              "a",
              {
                className: "project-card-link",
                href: `/projects/${encodeURIComponent(project.project_id)}`,
              },
              h("h3", null, project.project_name),
              h("p", null, `ID: ${project.project_id}`),
              h("p", null, `状态: ${project.status}`),
              h("p", null, `模式: ${project.development_mode}`),
              h("p", null, `Agent 数: ${project.agent_count}`),
              h("p", null, `更新时间: ${project.updated_at}`)
            ),
            h(
              "button",
              {
                type: "button",
                className: "btn danger",
                disabled: deletingProjectId === String(project.project_id),
                onClick: () => deleteProject(project),
              },
              deletingProjectId === String(project.project_id) ? "删除中..." : "删除项目"
            )
          )
        )
      : [h("p", { key: "empty", className: "muted" }, "暂无项目，先创建一个。")];

    return h(
      "div",
      { className: "dashboard-shell" },
      h(
        "section",
        { className: "split" },
        h(
          "article",
          { className: "card card-glow" },
          h("h2", null, "新建项目"),
          h(
            "form",
            { className: "stack", onSubmit: submitProject },
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
            h("h3", null, "Agent 模型选择"),
            h(
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
            ),
            error ? h("p", { className: "warning" }, error) : null,
            h("button", { className: "btn", type: "submit", disabled: submitting }, submitting ? "创建中..." : "创建项目")
          )
        ),
        h(
          "article",
          { className: "card" },
          h("h2", null, "工作台概览"),
          h("p", { className: "metric-line" }, ["项目数", h("strong", { key: "count" }, String(projects.length))]),
          h(
            "div",
            { className: "auth-grid" },
            h("a", { className: "btn secondary", href: "/config/global/models" }, "模型配置"),
            h("a", { className: "btn secondary", href: "/config/global/agents" }, "Agent 配置")
          )
        )
      ),
      error ? h("section", { className: "error" }, error) : null,
      h("section", { className: "card" }, h("h2", null, "项目概览"), h("div", { className: "project-cards" }, ...projectCards))
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

    window.React.useEffect(() => {
      let active = true;
      async function refresh() {
        try {
          const [requirementsData, runsData] = await Promise.all([
            fetchJson(`/api/projects/${encodeURIComponent(projectId)}/requirements`),
            fetchJson(`/api/projects/${encodeURIComponent(projectId)}/runs`),
          ]);
          if (!active) return;
          setRequirements(Array.isArray(requirementsData.requirements) ? requirementsData.requirements : []);
          setRuns(Array.isArray(runsData.runs) ? runsData.runs : []);
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
    }, [projectId]);

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

    return h(
      "div",
      null,
      h(
        "section",
        { className: "card card-glow" },
        h("h1", null, project.info.project_name),
        h("p", { className: "muted" }, `ID: ${project.info.project_id} | 状态: ${project.info.status} | 模式: ${project.info.development_mode}`),
        h(
          "button",
          {
            type: "button",
            className: "btn danger",
            disabled: deleting,
            onClick: deleteCurrentProject,
          },
          deleting ? "删除中..." : "删除项目"
        )
      ),
      h(
        "section",
        { className: "split" },
        h(
          "article",
          { className: "card" },
          h("h2", null, "下发新需求"),
          h(
            "form",
            { className: "stack", onSubmit: submitRequirement },
            h("label", null, "需求内容"),
            h("textarea", {
              required: true,
              rows: 6,
              placeholder: "输入新需求",
              value: text,
              onChange: (e) => setText(e.target.value),
            }),
            error ? h("p", { className: "warning" }, error) : null,
            h("button", { className: "btn", type: "submit", disabled: submitting }, submitting ? "提交中..." : "提交并运行工作流")
          )
        ),
        h(
          "article",
          { className: "card" },
          h("h2", null, "工作流节点"),
          h(
            "ol",
            { className: "workflow-list" },
            ...(Array.isArray(project.workflow_nodes) ? project.workflow_nodes : []).map((node, index) =>
              h(
                "li",
                { key: `${node.name}-${index}` },
                h("strong", null, node.name),
                h("p", { className: "muted" }, `任务: ${(node.tasks || []).join(", ")}`),
                h("p", { className: "muted" }, `评审: ${node.review_gate || "无"}`)
              )
            )
          )
        )
      ),
      h(
        "section",
        { className: "card" },
        h("h2", null, "历时需求"),
        h(
          "ul",
          { className: "history-list" },
          ...(requirements.length
            ? requirements.map((req, idx) => h("li", { key: `${req.created_at}-${idx}` }, `${req.created_at} - ${req.text}`))
            : [h("li", { key: "empty", className: "muted" }, "暂无需求历史。")])
        )
      ),
      h(
        "section",
        { className: "card" },
        h("h2", null, "工作流执行记录"),
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
                    h("td", null, run.started_at),
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
    );
  }

  mountReact("project-react-root", () => window.React.createElement(ProjectApp));
}

function setupRunReact() {
  const initial = readScriptJson("run-initial-data", { project: null, run: null });
  if (!initial.project || !initial.run) return;

  function RunApp() {
    const h = window.React.createElement;
    const project = initial.project;
    const [run, setRun] = window.React.useState(initial.run);
    const [pollError, setPollError] = window.React.useState("");
    const phases = Array.isArray(run.phase_results) ? run.phase_results : [];
    const runStatus = String(run.status || "pending");
    const isRunning = runStatus === "pending" || runStatus === "running";
    const workflowNodes = Array.isArray(project.workflow_nodes) ? project.workflow_nodes : [];

    const phaseNameMap = {
      requirements: "需求分析",
      design: "架构设计",
      implementation: "开发实现",
      testing: "测试验收",
    };

    window.React.useEffect(() => {
      let active = true;
      async function refreshRun() {
        try {
          const latest = await fetchJson(
            `/api/projects/${encodeURIComponent(project.info.project_id)}/runs/${encodeURIComponent(run.run_id)}`
          );
          if (!active) return;
          setRun(latest);
          setPollError("");
        } catch (err) {
          if (!active) return;
          setPollError(err instanceof Error ? err.message : "刷新失败");
        }
      }

      if (!isRunning) return () => {};
      refreshRun();
      const timer = window.setInterval(refreshRun, 3000);
      return () => {
        active = false;
        window.clearInterval(timer);
      };
    }, [project.info.project_id, run.run_id, isRunning]);

    function normalizePhaseState(status) {
      if (status === "completed") return "completed";
      if (status === "failed") return "failed";
      if (status === "in_progress" || status === "in_review") return "running";
      return "pending";
    }

    function toTaskLabel(taskKey) {
      const parts = String(taskKey || "").split(".");
      return parts.length > 1 ? parts[1] : String(taskKey || "");
    }

    function buildFlowData() {
      const phaseResultMap = {};
      phases.forEach((p) => {
        phaseResultMap[String(p.phase || "")] = p;
      });

      let hasBlockingPending = false;
      return workflowNodes.map((node) => {
        const phaseKey = String(node.name || "");
        const phaseResult = phaseResultMap[phaseKey];
        let phaseState = "pending";
        if (phaseResult) {
          phaseState = normalizePhaseState(String(phaseResult.status || ""));
        } else if (!hasBlockingPending && isRunning) {
          phaseState = "running";
          hasBlockingPending = true;
        }
        if (phaseState === "pending") {
          hasBlockingPending = true;
        }

        const taskStatusMap = phaseResult && phaseResult.tasks && typeof phaseResult.tasks === "object" ? phaseResult.tasks : {};
        const taskItems = Array.isArray(node.tasks) ? node.tasks : [];
        const tasks = taskItems.map((taskKey) => {
          const taskResult = taskStatusMap[taskKey];
          const status = taskResult ? (taskResult.status === "success" ? "completed" : "failed") : (phaseState === "running" ? "running" : "pending");
          return {
            key: taskKey,
            label: toTaskLabel(taskKey),
            status,
          };
        });

        return {
          key: phaseKey,
          title: phaseNameMap[phaseKey] || phaseKey,
          rawTitle: phaseKey,
          status: phaseState,
          tasks,
        };
      });
    }

    const flowData = buildFlowData();

    return h(
      "div",
      null,
      h(
        "section",
        { className: "card card-glow" },
        h("h1", null, "工作流执行详情"),
        h(
          "p",
          null,
          "项目: ",
          h("a", { href: `/projects/${encodeURIComponent(project.info.project_id)}` }, project.info.project_name)
        ),
        h("p", { className: "muted" }, `执行ID: ${run.run_id} | 时间: ${run.started_at}`),
        h("p", null, `状态: ${runStatus}${isRunning ? "（执行中，自动刷新）" : ""}`),
        run.completed_at ? h("p", { className: "muted" }, `完成时间: ${run.completed_at}`) : null,
        run.error ? h("pre", { className: "error" }, run.error) : null,
        pollError ? h("p", { className: "warning" }, `轮询失败: ${pollError}`) : null,
        h("p", null, `需求: ${run.requirement_text}`)
      ),
      h(
        "section",
        { className: "card" },
        h("h2", null, "端到端流程图"),
        h(
          "div",
          { className: "flow-chart-track" },
          ...flowData.map((phase, index) =>
            h(
              "div",
              {
                key: `${phase.key}-${index}`,
                className: `flow-step ${phase.status} ${index < flowData.length - 1 ? "has-next" : ""}`,
              },
              h("div", { className: "flow-step-dot" }, phase.status === "completed" ? "✓" : index + 1),
              h("div", { className: "flow-step-title" }, phase.title),
              h("div", { className: "flow-step-subtitle" }, phase.rawTitle),
              h(
                "div",
                { className: "flow-task-list" },
                ...phase.tasks.map((task) =>
                  h(
                    "span",
                    {
                      key: `${phase.key}-${task.key}`,
                      className: `flow-task-chip ${task.status}`,
                    },
                    task.label
                  )
                )
              )
            )
          )
        )
      ),
      h(
        "section",
        { className: "card" },
        h("h2", null, "节点与任务结果"),
        phases.length
          ? phases.map((phase, phaseIndex) =>
              h(
                "article",
                { className: "phase-card", key: `${phase.phase}-${phaseIndex}` },
                h("h3", null, `${phase.phase} (${phase.status})`),
                phase.tasks && Object.keys(phase.tasks).length
                  ? h(
                      "ul",
                      null,
                      ...Object.entries(phase.tasks).map(([taskKey, task]) =>
                        h(
                          "li",
                          { key: taskKey },
                          `${taskKey} - ${task.status} `,
                          h(
                            "a",
                            {
                              href: `/projects/${encodeURIComponent(project.info.project_id)}/runs/${encodeURIComponent(run.run_id)}/phases/${phaseIndex}/tasks/${encodeURIComponent(taskKey)}`,
                            },
                            "任务详情"
                          )
                        )
                      )
                    )
                  : h("p", { className: "muted" }, "无任务。")
              )
            )
          : h("p", { className: "muted" }, isRunning ? "工作流执行中，等待阶段结果..." : "暂无阶段结果。")
      )
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
      { className: "card narrow card-glow" },
      h("h1", null, "登录 AISE Web"),
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

document.addEventListener("DOMContentLoaded", () => {
  setupDashboardReact();
  setupProjectReact();
  setupRunReact();
  setupTaskReact();
  setupLoginReact();
  setupModelsConfigPage();
});
