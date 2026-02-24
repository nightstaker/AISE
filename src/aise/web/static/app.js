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
      { className: "dashboard-shell dashboard-layout" },
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

    return h(
      "div",
      { className: "project-layout" },
      h(
        "section",
        { className: "card card-glow project-header-card" },
        h("h1", null, project.info.project_name),
        h("p", { className: "muted" }, `ID: ${project.info.project_id} | 状态: ${project.info.status} | 模式: ${project.info.development_mode}`),
        h(
          "button",
          {
            type: "button",
            className: "btn danger",
            disabled: deleting || projectMissing,
            onClick: deleteCurrentProject,
          },
          deleting ? "删除中..." : "删除项目"
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
      h(
        "section",
        { className: "split project-top-grid" },
        h(
          "article",
          { className: "card project-new-req-card" },
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
        ),
        h(
          "article",
          { className: "card project-workflow-card" },
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
        "div",
        { className: "project-bottom-grid" },
        h(
          "section",
          { className: "card project-history-card" },
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
          { className: "card project-runs-card" },
          h("h2", null, "工作流执行记录"),
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
    const [selectedTask, setSelectedTask] = window.React.useState(null);
    const [taskLogsByKey, setTaskLogsByKey] = window.React.useState({});
    const [taskLogError, setTaskLogError] = window.React.useState("");
    const [taskLogLoading, setTaskLogLoading] = window.React.useState(false);
    const [expandedTraceLogIds, setExpandedTraceLogIds] = window.React.useState({});
    const [taskStateDetail, setTaskStateDetail] = window.React.useState(null);
    const [taskStateLoading, setTaskStateLoading] = window.React.useState(false);
    const [taskStateError, setTaskStateError] = window.React.useState("");
    const [taskMemoryExpanded, setTaskMemoryExpanded] = window.React.useState(false);
    const [retryMode, setRetryMode] = window.React.useState("current");
    const [retrySubmitting, setRetrySubmitting] = window.React.useState(false);
    const [retryError, setRetryError] = window.React.useState("");
    const [retryNotice, setRetryNotice] = window.React.useState("");
    const phases = Array.isArray(run.phase_results) ? run.phase_results : [];
    const liveTaskStates = run && run.live_task_states && typeof run.live_task_states === "object" ? run.live_task_states : {};
    const taskStateSummary =
      run && run.task_state_summary && typeof run.task_state_summary === "object" ? run.task_state_summary : {};
    const activeOperation = run && run.active_operation && typeof run.active_operation === "object" ? run.active_operation : null;
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

    function laneKind(agentName) {
      const name = String(agentName || "").toLowerCase();
      if (name.includes("reviewer")) return "review";
      if (name.includes("designer") || name.includes("architect")) return "design";
      if (name.includes("programmer") || name.includes("developer")) return "build";
      if (name.includes("qa")) return "qa";
      return "task";
    }

    function isParallelLane(agentName) {
      return String(agentName || "").includes("[*]");
    }

    function buildPhaseRelations(phaseKey, agentTasks) {
      const lanes = Array.isArray(agentTasks) ? agentTasks : [];
      const badges = [];
      const hints = [];
      const hasManyLanes = lanes.length > 1;
      const hasWildcardLane = lanes.some((lane) => isParallelLane(lane.agent));
      const hasReviewer = lanes.some((lane) => String(lane.agent || "").toLowerCase().includes("reviewer"));
      const hasDesignerOrBuilder = lanes.some((lane) => {
        const n = String(lane.agent || "").toLowerCase();
        return n.includes("designer") || n.includes("architect") || n.includes("programmer");
      });
      const allTasks = lanes.flatMap((lane) => (Array.isArray(lane.tasks) ? lane.tasks : []));
      const hasSrGroupedDev = allTasks.some((task) =>
        String(task && task.name ? task.name : "").includes("sr_group_parallel_development")
      );
      const hasSubsystemBatchReview = allTasks.some((task) =>
        String(task && task.name ? task.name : "").includes("subsystem_batch_code_and_test_review")
      );

      if (hasManyLanes) {
        badges.push({ type: "split", label: `任务拆分 ${lanes.length} 路` });
        hints.push("阶段内任务已按角色/子代理拆分");
      }
      if (hasWildcardLane || lanes.length >= 2) {
        badges.push({ type: "parallel", label: "并发执行" });
        hints.push("不同 lane 可并行推进，等待阶段汇总");
      }
      if (hasReviewer && hasDesignerOrBuilder) {
        badges.push({ type: "collab", label: "设计/开发-评审协同" });
        hints.push("设计/开发与评审形成往返反馈回路");
      }
      if (!badges.length) {
        badges.push({ type: "sequence", label: "串行执行" });
      } else {
        badges.push({ type: "sequence", label: "阶段内有序编排" });
      }
      if (phaseKey === "implementation" && hasSrGroupedDev) {
        badges.push({ type: "split", label: "同 SR 合并任务" });
        hints.push("子系统内同一 SR 的多个 FN 合并为一次开发任务，降低任务切换成本");
        hints.push("同一子系统内多个 SR 按顺序串行开发，便于复用文件与代码上下文");
        hints.push("不同子系统之间并行开发，提升整体吞吐");
      }
      if (phaseKey === "implementation" && hasSubsystemBatchReview) {
        hints.push("代码评审按子系统批量进行，开发完成后统一评审与修订");
      }
      if (phaseKey === "testing") {
        hints.push("QA 阶段先产出测试设计，再执行测试自动化与验收评审");
      }
      return { badges, hints };
    }

    function buildAgentTasksFromTaskItems(taskItems) {
      const grouped = {};
      const order = [];
      taskItems.forEach((taskKey) => {
        const parts = String(taskKey || "").split(".");
        const agent = parts[0] || "unknown";
        if (!grouped[agent]) {
          grouped[agent] = [];
          order.push(agent);
        }
        grouped[agent].push({
          key: taskKey,
          name: parts.length > 1 ? parts.slice(1).join(".") : String(taskKey || ""),
          input_hints: [],
        });
      });
      return order.map((agent) => ({ agent, tasks: grouped[agent] }));
    }

    function normalizeTaskState(taskResult, phaseState) {
      if (taskResult && typeof taskResult === "object") {
        return taskResult.status === "success" ? "completed" : "failed";
      }
      if (phaseState === "completed") return "completed";
      if (phaseState === "failed") return "failed";
      if (phaseState === "running") return "pending";
      return "pending";
    }

    function isTerminalTaskStatus(status) {
      return status === "completed" || status === "failed";
    }

    function rebalanceLaneTaskStatuses(agentTasks, phaseState) {
      if (!Array.isArray(agentTasks) || phaseState !== "running") return agentTasks;
      return agentTasks.map((lane) => {
        const tasks = Array.isArray(lane.tasks) ? lane.tasks.slice() : [];
        if (!tasks.length) return lane;
        if (lane.parallelized) {
          return { ...lane, tasks };
        }

        const explicitRunningIndex = tasks.findIndex(
          (task) => task && task.status === "running" && task.statusSource !== "phase_fallback"
        );

        let activeIndex = explicitRunningIndex;
        if (activeIndex < 0) {
          activeIndex = tasks.findIndex((task) => task && !isTerminalTaskStatus(String(task.status || "")));
        }

        const normalizedTasks = tasks.map((task, index) => {
          if (!task || typeof task !== "object") return task;
          if (isTerminalTaskStatus(String(task.status || ""))) return task;
          if (task.statusSource !== "phase_fallback") {
            if (explicitRunningIndex >= 0 && index > explicitRunningIndex && task.status === "running") {
              return { ...task, status: "pending" };
            }
            return task;
          }
          return { ...task, status: index === activeIndex ? "running" : "pending" };
        });

        return { ...lane, tasks: normalizedTasks };
      });
    }

    function resolveTaskResult(taskStatusMap, agentName, phaseKey, taskKey) {
      if (taskStatusMap[taskKey]) {
        return { result: taskStatusMap[taskKey], resultKey: taskKey };
      }
      const phaseScopedKey = `${agentName}.${phaseKey}`;
      if (taskStatusMap[phaseScopedKey]) {
        return { result: taskStatusMap[phaseScopedKey], resultKey: phaseScopedKey };
      }
      // Deep PM subagent virtual tasks map back to PM phase/skill runtime keys.
      if (String(taskKey).startsWith("product_manager.deep_product_workflow")) {
        const deepSkillKey = "product_manager.deep_product_workflow";
        if (taskStatusMap[deepSkillKey]) {
          return { result: taskStatusMap[deepSkillKey], resultKey: deepSkillKey };
        }
        const phaseKeyAlias = "product_manager.requirements";
        if (taskStatusMap[phaseKeyAlias]) {
          return { result: taskStatusMap[phaseKeyAlias], resultKey: phaseKeyAlias };
        }
      }
      if (String(taskKey).startsWith("architect.deep_architecture_workflow")) {
        const deepSkillKey = "architect.deep_architecture_workflow";
        if (taskStatusMap[deepSkillKey]) {
          return { result: taskStatusMap[deepSkillKey], resultKey: deepSkillKey };
        }
        const phaseKeyAlias = "architect.design";
        if (taskStatusMap[phaseKeyAlias]) {
          return { result: taskStatusMap[phaseKeyAlias], resultKey: phaseKeyAlias };
        }
      }
      if (String(taskKey).startsWith("developer.deep_developer_workflow")) {
        const deepSkillKey = "developer.deep_developer_workflow";
        if (taskStatusMap[deepSkillKey]) {
          return { result: taskStatusMap[deepSkillKey], resultKey: deepSkillKey };
        }
        const phaseKeyAlias = "developer.implementation";
        if (taskStatusMap[phaseKeyAlias]) {
          return { result: taskStatusMap[phaseKeyAlias], resultKey: phaseKeyAlias };
        }
      }
      return { result: null, resultKey: "" };
    }

    function getLiveTaskState(phaseKey, taskKey) {
      const key = `${phaseKey}::${taskKey}`;
      const value = liveTaskStates[key];
      return value && typeof value === "object" ? value : null;
    }

    function getTaskStateSummaryItem(phaseKey, taskKey) {
      const key = `${phaseKey}::${taskKey}`;
      const value = taskStateSummary[key];
      return value && typeof value === "object" ? value : null;
    }

    function summarizeLiveTaskProgress(liveState) {
      if (!liveState || typeof liveState !== "object") return "";
      const evt = liveState.last_event && typeof liveState.last_event === "object" ? liveState.last_event : null;
      if (!evt) return "";
      const meta = evt.purpose_meta && typeof evt.purpose_meta === "object" ? evt.purpose_meta : {};
      const parts = [];
      if (meta.subagent) parts.push(String(meta.subagent));
      if (meta.step) parts.push(String(meta.step));
      if (meta.fn) parts.push(`fn:${String(meta.fn)}`);
      if (meta.subsystem) parts.push(`subsys:${String(meta.subsystem)}`);
      const prefix = parts.length ? `${parts.join(" · ")} · ` : "";
      return `${prefix}${String(evt.message || "")}`.slice(0, 160);
    }

    function taskStatusLabel(status) {
      return status === "completed" ? "完成" : status === "running" ? "执行中" : status === "failed" ? "失败" : "待执行";
    }

    function selectTaskByCardTask(task, event) {
      if (event && typeof event.stopPropagation === "function") event.stopPropagation();
      if (!task) return;
      setSelectedTask({ phaseKey: task.phaseKey, taskKey: task.key });
    }

    function isVisibleTaskLogEvent(evt) {
      const source = String((evt && evt.source) || "");
      return source === "runtime" || source === "trace";
    }

    function getTaskLogDetailsForDisplay(evt) {
      const details = evt && evt.details && typeof evt.details === "object" ? evt.details : null;
      if (!details) return null;
      const source = String((evt && evt.source) || "");
      const out = { ...details };
      if (source === "aise.log") {
        delete out.logger;
        delete out.line;
      }
      return out;
    }

    function traceMarkdownFromEvent(evt) {
      const details = evt && evt.details && typeof evt.details === "object" ? evt.details : null;
      if (!details) return "";
      const providerMeta =
        details.provider_response_meta && typeof details.provider_response_meta === "object"
          ? details.provider_response_meta
          : {};
      const sections = [];
      const title = String(evt.message || "").trim();
      if (title) sections.push(`## LLM Call\n\n${title}`);
      const bullets = [];
      ["agent", "skill", "model", "provider"].forEach((k) => {
        if (details[k]) bullets.push(`- **${k}**: ${details[k]}`);
      });
      if (providerMeta.finish_reason) bullets.push(`- **finish_reason**: ${providerMeta.finish_reason}`);
      if (providerMeta.total_tokens) bullets.push(`- **total_tokens**: ${providerMeta.total_tokens}`);
      if (bullets.length) sections.push(bullets.join("\n"));
      const preview = String(details.output_preview || "").trim();
      if (preview) {
        sections.push("### Output Preview");
        sections.push(formatTraceOutputPreviewMarkdown(preview));
      }
      return sections.join("\n\n").trim();
    }

    function formatTraceOutputPreviewMarkdown(preview) {
      const text = String(preview || "").trim();
      if (!text) return "";
      const candidate = text.startsWith("```")
        ? text
        : text;
      if (!candidate.startsWith("```")) {
        try {
          const parsed = JSON.parse(candidate);
          return `\`\`\`json\n${JSON.stringify(parsed, null, 2)}\n\`\`\``;
        } catch (err) {
          // non-JSON preview, render as markdown text
        }
      }
      return text;
    }

    function simpleMarkdownToHtml(md) {
      const escapeHtml = (s) =>
        String(s)
          .replace(/&/g, "&amp;")
          .replace(/</g, "&lt;")
          .replace(/>/g, "&gt;");
      const inline = (s) =>
        escapeHtml(s)
          .replace(/`([^`]+)`/g, "<code>$1</code>")
          .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
          .replace(/\*([^*]+)\*/g, "<em>$1</em>");
      const lines = String(md || "").replace(/\r\n/g, "\n").split("\n");
      const out = [];
      let inCode = false;
      let codeLines = [];
      let inList = false;
      const closeList = () => {
        if (inList) {
          out.push("</ul>");
          inList = false;
        }
      };
      const closeCode = () => {
        if (inCode) {
          out.push(`<pre><code>${escapeHtml(codeLines.join("\n"))}</code></pre>`);
          inCode = false;
          codeLines = [];
        }
      };
      for (const line of lines) {
        if (String(line).startsWith("```")) {
          if (inCode) closeCode();
          else {
            closeList();
            inCode = true;
          }
          continue;
        }
        if (inCode) {
          codeLines.push(String(line));
          continue;
        }
        if (!String(line).trim()) {
          closeList();
          continue;
        }
        const hm = String(line).match(/^(#{1,3})\s+(.*)$/);
        if (hm) {
          closeList();
          const level = Math.min(3, hm[1].length);
          out.push(`<h${level}>${inline(hm[2])}</h${level}>`);
          continue;
        }
        const lm = String(line).match(/^\s*[-*]\s+(.*)$/);
        if (lm) {
          if (!inList) {
            out.push("<ul>");
            inList = true;
          }
          out.push(`<li>${inline(lm[1])}</li>`);
          continue;
        }
        closeList();
        out.push(`<p>${inline(String(line))}</p>`);
      }
      closeCode();
      closeList();
      return out.join("");
    }

    function flattenPhaseTasks(agentTasks) {
      return (Array.isArray(agentTasks) ? agentTasks : []).flatMap((agentBlock) =>
        Array.isArray(agentBlock && agentBlock.tasks) ? agentBlock.tasks : []
      );
    }

    function pickPhaseTask(agentTasks, taskKey) {
      const key = String(taskKey || "");
      return flattenPhaseTasks(agentTasks).find((t) => String(t && t.key) === key) || null;
    }

    function readWorkflowSummary(task) {
      const item = task && task.taskStateItem && typeof task.taskStateItem === "object" ? task.taskStateItem : null;
      const outputs = item && item.latest_outputs && typeof item.latest_outputs === "object" ? item.latest_outputs : null;
      const summary = outputs && outputs.workflow_summary && typeof outputs.workflow_summary === "object" ? outputs.workflow_summary : null;
      return summary || null;
    }

    function readWorkflowSummaryFromTasks() {
      const tasks = Array.from(arguments);
      let fallbackSummary = null;
      for (const task of tasks) {
        const summary = readWorkflowSummary(task);
        if (!summary) continue;
        const subsystems = Array.isArray(summary.subsystems) ? summary.subsystems : [];
        if (subsystems.length) return summary;
        if (!fallbackSummary) fallbackSummary = summary;
      }
      return fallbackSummary;
    }

    function readRoundCount(task, stepKey) {
      const summary = readWorkflowSummary(task);
      const rounds = summary && summary.rounds && typeof summary.rounds === "object" ? summary.rounds : null;
      const value = rounds ? rounds[stepKey] : null;
      return Number.isFinite(Number(value)) ? Number(value) : 0;
    }

    function mergeTaskStatus(a, b) {
      const sa = a ? String(a.status || "") : "pending";
      const sb = b ? String(b.status || "") : "pending";
      if (sa === "failed" || sb === "failed") return "failed";
      if (sa === "running" || sb === "running") return "running";
      if (sa === "completed" && sb === "completed") return "completed";
      if (sa === "completed" || sb === "completed") return "running";
      return "pending";
    }

    function pairedRoleDisplayStatus(task, counterpartTask, role) {
      if (!task) return "pending";
      const raw = String(task.status || "pending");
      if (raw !== "running") return raw;

      const liveStatus =
        task.liveState && typeof task.liveState.status === "string" ? String(task.liveState.status) : "";
      const hasLiveRunning = liveStatus === "running";
      if (hasLiveRunning) return "running";

      const statusSource = String(task.statusSource || "");
      // If the task is explicitly running (task_state/live_state/runtime), preserve running for design/build roles.
      // Only keep the delayed-review visualization rule for review roles.
      if (role !== "review" && statusSource && statusSource !== "phase_fallback") {
        return "running";
      }

      // Deep loop tasks may be pre-marked running via task_state as soon as the parent loop starts.
      // For paired cards, only show review running after there is actual review live progress.
      if (role === "review") {
        const designDone = counterpartTask && String(counterpartTask.status || "") === "completed";
        return designDone ? "pending" : "pending";
      }
      return "pending";
    }

    function inferLiveRound(task) {
      const meta =
        task &&
        task.liveState &&
        task.liveState.last_event &&
        task.liveState.last_event.purpose_meta &&
        typeof task.liveState.last_event.purpose_meta === "object"
          ? task.liveState.last_event.purpose_meta
          : null;
      const roundText = meta && meta.round ? String(meta.round) : "";
      const roundNum = Number(roundText);
      return Number.isFinite(roundNum) ? roundNum : 0;
    }

    function inferLiveSubsystem(task) {
      const meta =
        task &&
        task.liveState &&
        task.liveState.last_event &&
        task.liveState.last_event.purpose_meta &&
        typeof task.liveState.last_event.purpose_meta === "object"
          ? task.liveState.last_event.purpose_meta
          : null;
      return meta && meta.subsystem ? String(meta.subsystem) : "";
    }

    function normalizeSubsystemMatchKey(value) {
      return String(value || "")
        .trim()
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, "_")
        .replace(/^_+|_+$/g, "");
    }

    function subsystemCardState(baseTask, subsystemRef) {
      if (!baseTask) return "pending";
      const baseStatus = String(baseTask.status || "pending");
      const liveSubsystem = inferLiveSubsystem(baseTask);
      if (baseStatus === "running") {
        const liveKey = normalizeSubsystemMatchKey(liveSubsystem);
        const candidates = [];
        if (subsystemRef && typeof subsystemRef === "object") {
          candidates.push(subsystemRef.subsystemSlug, subsystemRef.subsystemId, subsystemRef.subsystemName);
        } else {
          candidates.push(subsystemRef);
        }
        const matched = liveKey
          ? candidates.some((item) => normalizeSubsystemMatchKey(item) === liveKey)
          : false;
        if (matched) return "running";
        return "pending";
      }
      return baseStatus;
    }

    function buildCompositeTaskCards(phaseKey, agentTasks) {
      const cards = [];
      const get = (key) => pickPhaseTask(agentTasks, key);

      if (phaseKey === "requirements") {
        const step1 = get("product_manager.deep_product_workflow.step1");
        if (step1) {
          cards.push({
            type: "single",
            key: `${phaseKey}::step1`,
            title: "需求澄清扩展",
            primaryTask: step1,
            status: String(step1.status || "pending"),
            meta: [`输入: ${(step1.inputHints || []).slice(0, 2).join(", ") || "-"}`],
          });
        }
        const step2Design = get("product_manager.deep_product_workflow.step2.design");
        const step2Review = get("product_manager.deep_product_workflow.step2.review");
        if (step2Design || step2Review) {
          cards.push({
            type: "paired",
            key: `${phaseKey}::step2`,
            title: "产品设计迭代",
            primaryTask: step2Design || step2Review,
            designTask: step2Design,
            reviewTask: step2Review,
            status: mergeTaskStatus(step2Design, step2Review),
            designRoundTotal: readRoundCount(step2Design || step2Review, "step2"),
            reviewRoundTotal: readRoundCount(step2Design || step2Review, "step2"),
            designRoundCurrent: inferLiveRound(step2Design),
            reviewRoundCurrent: inferLiveRound(step2Review),
          });
        }
        const step3Design = get("product_manager.deep_product_workflow.step3.design");
        const step3Review = get("product_manager.deep_product_workflow.step3.review");
        if (step3Design || step3Review) {
          cards.push({
            type: "paired",
            key: `${phaseKey}::step3`,
            title: "系统需求设计迭代",
            primaryTask: step3Design || step3Review,
            designTask: step3Design,
            reviewTask: step3Review,
            status: mergeTaskStatus(step3Design, step3Review),
            designRoundTotal: readRoundCount(step3Design || step3Review, "step3"),
            reviewRoundTotal: readRoundCount(step3Design || step3Review, "step3"),
            designRoundCurrent: inferLiveRound(step3Design),
            reviewRoundCurrent: inferLiveRound(step3Review),
          });
        }
        return cards;
      }

      if (phaseKey === "design") {
        const archDesign = get("architect.deep_architecture_workflow.step1.design");
        const archReview = get("architect.deep_architecture_workflow.step1.review");
        if (archDesign || archReview) {
          cards.push({
            type: "paired",
            key: `${phaseKey}::step1`,
            title: "系统架构设计迭代",
            primaryTask: archDesign || archReview,
            designTask: archDesign,
            reviewTask: archReview,
            status: mergeTaskStatus(archDesign, archReview),
            designRoundTotal: readRoundCount(archDesign || archReview, "step1"),
            reviewRoundTotal: readRoundCount(archDesign || archReview, "step1"),
            designRoundCurrent: inferLiveRound(archDesign),
            reviewRoundCurrent: inferLiveRound(archReview),
          });
        }
        const splitTask = get("architect.deep_architecture_workflow.step2_3");
        if (splitTask) {
          cards.push({
            type: "single",
            key: `${phaseKey}::step2_3`,
            title: "架构引导代码与子系统拆分",
            primaryTask: splitTask,
            status: String(splitTask.status || "pending"),
          });
        }
        const subDesign = get("architect.deep_architecture_workflow.step4.design");
        const subReview = get("architect.deep_architecture_workflow.step4.review");
        const subInit = get("architect.deep_architecture_workflow.step5");
        const subSummary = readWorkflowSummaryFromTasks(subDesign, subReview, splitTask);
        const subsystems = subSummary && Array.isArray(subSummary.subsystems) ? subSummary.subsystems : [];
        const subRoundsEach =
          subSummary && subSummary.subsystem_rounds_each && typeof subSummary.subsystem_rounds_each === "object"
            ? subSummary.subsystem_rounds_each
            : {};
        if (subDesign || subReview) {
          cards.push({
            type: "subsystem_group",
            key: `${phaseKey}::step4`,
            title: "子系统详细设计与评审",
            primaryTask: subDesign || subReview,
            designTask: subDesign,
            reviewTask: subReview,
            status: mergeTaskStatus(subDesign, subReview),
            cards: subsystems.map((sub) => {
              const subsystemId = String((sub && sub.subsystem_id) || "");
              return {
                subsystemId,
                subsystemName: String((sub && (sub.subsystem_name || sub.subsystem)) || subsystemId),
                subsystemSlug: String((sub && (sub.subsystem_slug || sub.subsystem_english_name || "")) || ""),
                srIds: Array.isArray(sub && sub.assigned_sr_ids) ? sub.assigned_sr_ids.map((x) => String(x)) : [],
                designStatus: subsystemCardState(subDesign, {
                  subsystemId,
                  subsystemName: String((sub && (sub.subsystem_name || sub.subsystem)) || subsystemId),
                  subsystemSlug: String((sub && (sub.subsystem_slug || sub.subsystem_english_name || "")) || ""),
                }),
                reviewStatus: subsystemCardState(subReview, {
                  subsystemId,
                  subsystemName: String((sub && (sub.subsystem_name || sub.subsystem)) || subsystemId),
                  subsystemSlug: String((sub && (sub.subsystem_slug || sub.subsystem_english_name || "")) || ""),
                }),
                designRoundTotal: Number(subRoundsEach[subsystemId] || 0),
                reviewRoundTotal: Number(subRoundsEach[subsystemId] || 0),
                designRoundCurrent:
                  inferLiveSubsystem(subDesign) === subsystemId ? inferLiveRound(subDesign) : 0,
                reviewRoundCurrent:
                  inferLiveSubsystem(subReview) === subsystemId ? inferLiveRound(subReview) : 0,
              };
            }),
            tailTask: subInit || null,
          });
        }
        if (subInit && !(subDesign || subReview)) {
          cards.push({
            type: "single",
            key: `${phaseKey}::step5`,
            title: "子系统源码初始化",
            primaryTask: subInit,
            status: String(subInit.status || "pending"),
          });
        }
        return cards;
      }

      if (phaseKey === "implementation") {
        const assignment = get("developer.deep_developer_workflow.step1");
        if (assignment) {
          cards.push({
            type: "single",
            key: `${phaseKey}::step1`,
            title: "子系统任务分配",
            primaryTask: assignment,
            status: String(assignment.status || "pending"),
          });
        }
        const devTask = get("developer.deep_developer_workflow.step2.develop");
        const reviewTask = get("developer.deep_developer_workflow.step2.review");
        const revisionTask = get("developer.deep_developer_workflow.step2.revision");
        const mergeTask = get("developer.deep_developer_workflow.step2.merge");
        const devSummary = readWorkflowSummaryFromTasks(devTask, reviewTask, revisionTask, mergeTask, assignment);
        const subsystems = devSummary && Array.isArray(devSummary.subsystems) ? devSummary.subsystems : [];
        if (devTask || reviewTask) {
          cards.push({
            type: "subsystem_group",
            key: `${phaseKey}::step2`,
            title: "子系统开发与评审轮次",
            primaryTask: devTask || reviewTask,
            designTask: devTask,
            reviewTask,
            status: mergeTaskStatus(devTask, reviewTask),
            cards: subsystems.map((sub) => {
              const subsystemId = String((sub && sub.subsystem_id) || "");
              return {
                subsystemId,
                subsystemName: String((sub && (sub.subsystem_name || sub.subsystem)) || subsystemId),
                subsystemSlug: String((sub && (sub.subsystem_slug || sub.subsystem_english_name || "")) || ""),
                srIds: Array.isArray(sub && sub.assigned_sr_ids) ? sub.assigned_sr_ids.map((x) => String(x)) : [],
                designStatus: subsystemCardState(devTask, {
                  subsystemId,
                  subsystemName: String((sub && (sub.subsystem_name || sub.subsystem)) || subsystemId),
                  subsystemSlug: String((sub && (sub.subsystem_slug || sub.subsystem_english_name || "")) || ""),
                }),
                reviewStatus: subsystemCardState(reviewTask, {
                  subsystemId,
                  subsystemName: String((sub && (sub.subsystem_name || sub.subsystem)) || subsystemId),
                  subsystemSlug: String((sub && (sub.subsystem_slug || sub.subsystem_english_name || "")) || ""),
                }),
                designRoundTotal: readRoundCount(devTask || reviewTask, "step2"),
                reviewRoundTotal: readRoundCount(devTask || reviewTask, "step2"),
                designRoundCurrent:
                  inferLiveSubsystem(devTask) === subsystemId ? inferLiveRound(devTask) : 0,
                reviewRoundCurrent:
                  inferLiveSubsystem(reviewTask) === subsystemId ? inferLiveRound(reviewTask) : 0,
                extraStatus: revisionTask ? taskStatusLabel(revisionTask.status) : "",
              };
            }),
            tailTask: mergeTask || revisionTask || null,
          });
        }
        if (mergeTask && !(devTask || reviewTask)) {
          cards.push({
            type: "single",
            key: `${phaseKey}::step2.merge`,
            title: "批量合并",
            primaryTask: mergeTask,
            status: String(mergeTask.status || "pending"),
          });
        }
        return cards;
      }

      return [];
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
          const { result: taskResult } = resolveTaskResult(taskStatusMap, String(taskKey || "").split(".")[0] || "", phaseKey, taskKey);
          const status = normalizeTaskState(taskResult, phaseState);
          return {
            key: taskKey,
            label: toTaskLabel(taskKey),
            status,
          };
        });

        const rawAgentTasks = Array.isArray(node.agent_tasks) ? node.agent_tasks : buildAgentTasksFromTaskItems(taskItems);
        const agentTasks = rawAgentTasks.map((entry) => {
          const agent = String(entry.agent || "");
          const entryTasks = Array.isArray(entry.tasks) ? entry.tasks : [];
          const laneType = laneKind(agent);
          return {
            agent,
            laneType,
            parallelized: isParallelLane(agent),
            tasks: entryTasks.map((task) => {
              const taskKey = String(task.key || "");
              const taskName = String(task.name || toTaskLabel(taskKey));
              const inputHints = Array.isArray(task.input_hints) ? task.input_hints : [];
              const { result: taskResult, resultKey } = resolveTaskResult(taskStatusMap, agent, phaseKey, taskKey);
              const liveState = getLiveTaskState(phaseKey, taskKey);
              const taskStateItem = getTaskStateSummaryItem(phaseKey, taskKey);
              const resolvedStatus =
                taskStateItem && typeof taskStateItem.latest_status === "string" && taskStateItem.latest_status
                  ? String(taskStateItem.latest_status)
                  : liveState && typeof liveState.status === "string" && liveState.status
                  ? String(liveState.status)
                  : normalizeTaskState(taskResult, phaseState);
              const statusSource =
                taskStateItem && typeof taskStateItem.latest_status === "string" && taskStateItem.latest_status
                  ? "task_state"
                  : liveState && typeof liveState.status === "string" && liveState.status
                  ? "live_state"
                  : taskResult && typeof taskResult === "object"
                  ? "runtime_result"
                  : "phase_fallback";
              return {
                phaseKey,
                phaseTitle: phaseNameMap[phaseKey] || phaseKey,
                agent,
                key: taskKey,
                name: taskName,
                inputHints,
                status: resolvedStatus,
                runtimeResult: taskResult,
                runtimeTaskKey: resultKey,
                liveState,
                taskStateItem,
                progressText: summarizeLiveTaskProgress(liveState),
                statusSource,
                parallelized: isParallelLane(agent),
                laneType,
              };
            }),
          };
        });
        const normalizedAgentTasks = rebalanceLaneTaskStatuses(agentTasks, phaseState);
        const relations = buildPhaseRelations(phaseKey, agentTasks);
        const compositeTaskCards = buildCompositeTaskCards(phaseKey, normalizedAgentTasks);

        return {
          key: phaseKey,
          title: phaseNameMap[phaseKey] || phaseKey,
          rawTitle: phaseKey,
          status: phaseState,
          tasks,
          agentTasks: normalizedAgentTasks,
          compositeTaskCards,
          relations,
        };
      });
    }

    const flowData = buildFlowData();
    const selectedTaskDetail = selectedTask
      ? flowData
          .flatMap((phase) => phase.agentTasks || [])
          .flatMap((agentBlock) => agentBlock.tasks || [])
          .find((item) => item.phaseKey === selectedTask.phaseKey && item.key === selectedTask.taskKey) || null
      : null;
    const selectedTaskStoreKey = selectedTaskDetail
      ? `${selectedTaskDetail.phaseKey}::${selectedTaskDetail.key}`
      : "";
    const selectedTaskLogs = selectedTaskStoreKey ? taskLogsByKey[selectedTaskStoreKey] || [] : [];
    const visibleTaskLogs = selectedTaskLogs.filter(isVisibleTaskLogEvent);

    window.React.useEffect(() => {
      if (selectedTask) return;
      const candidates = flowData
        .flatMap((phase) => phase.agentTasks || [])
        .flatMap((agentBlock) => agentBlock.tasks || []);
      const preferred =
        candidates.find((item) => item.status === "running" && item.liveState && item.liveState.last_event) ||
        candidates.find((item) => item.status === "running") ||
        candidates.find((item) => item.liveState && item.liveState.last_event) ||
        null;
      if (preferred) {
        setSelectedTask({ phaseKey: preferred.phaseKey, taskKey: preferred.key });
      }
    }, [selectedTask, flowData]);

    window.React.useEffect(() => {
      let active = true;
      if (!selectedTaskDetail) {
        setTaskLogError("");
        setTaskLogLoading(false);
        return () => {
          active = false;
        };
      }

      async function refreshTaskLogs() {
        setTaskLogLoading(true);
        try {
          const payload = await fetchJson(
            `/api/projects/${encodeURIComponent(project.info.project_id)}/runs/${encodeURIComponent(
              run.run_id
            )}/task-logs?phase_key=${encodeURIComponent(selectedTaskDetail.phaseKey)}&task_key=${encodeURIComponent(
              selectedTaskDetail.key
            )}&limit=250`
          );
          if (!active) return;
          const incoming = Array.isArray(payload.events) ? payload.events : [];
          setTaskLogsByKey((prev) => {
            const existing = Array.isArray(prev[selectedTaskStoreKey]) ? prev[selectedTaskStoreKey] : [];
            const merged = [...existing];
            const seen = new Set(existing.map((item) => String(item.id || "")));
            incoming.forEach((item) => {
              const id = String(item && item.id ? item.id : "");
              if (!id || seen.has(id)) return;
              seen.add(id);
              merged.push(item);
            });
            merged.sort((a, b) => String(a.ts || "").localeCompare(String(b.ts || "")));
            return { ...prev, [selectedTaskStoreKey]: merged };
          });
          setTaskLogError("");
        } catch (err) {
          if (!active) return;
          setTaskLogError(err instanceof Error ? err.message : "任务日志加载失败");
        } finally {
          if (active) setTaskLogLoading(false);
        }
      }

      refreshTaskLogs();
      const timer = window.setInterval(refreshTaskLogs, isRunning ? 2500 : 6000);
      return () => {
        active = false;
        window.clearInterval(timer);
      };
    }, [
      project.info.project_id,
      run.run_id,
      isRunning,
      selectedTaskStoreKey,
      selectedTaskDetail && selectedTaskDetail.phaseKey,
      selectedTaskDetail && selectedTaskDetail.key,
    ]);

    window.React.useEffect(() => {
      let active = true;
      if (!selectedTaskDetail) {
        setTaskStateDetail(null);
        setTaskStateError("");
        setTaskStateLoading(false);
        setTaskMemoryExpanded(false);
        return () => {
          active = false;
        };
      }
      setTaskMemoryExpanded(false);
      async function refreshTaskState() {
        setTaskStateLoading(true);
        try {
          const payload = await fetchJson(
            `/api/projects/${encodeURIComponent(project.info.project_id)}/runs/${encodeURIComponent(
              run.run_id
            )}/task-state?phase_key=${encodeURIComponent(selectedTaskDetail.phaseKey)}&task_key=${encodeURIComponent(
              selectedTaskDetail.key
            )}`
          );
          if (!active) return;
          setTaskStateDetail(payload);
          setTaskStateError("");
        } catch (err) {
          if (!active) return;
          setTaskStateDetail(null);
          setTaskStateError(err instanceof Error ? err.message : "任务记忆体加载失败");
        } finally {
          if (active) setTaskStateLoading(false);
        }
      }
      refreshTaskState();
      const timer = window.setInterval(refreshTaskState, isRunning ? 3000 : 6000);
      return () => {
        active = false;
        window.clearInterval(timer);
      };
    }, [
      project.info.project_id,
      run.run_id,
      isRunning,
      selectedTaskDetail && selectedTaskDetail.phaseKey,
      selectedTaskDetail && selectedTaskDetail.key,
    ]);

    async function submitRetry() {
      if (!selectedTaskDetail || retrySubmitting) return;
      setRetrySubmitting(true);
      setRetryError("");
      setRetryNotice("");
      try {
        const payload = await fetchJson(
          `/api/projects/${encodeURIComponent(project.info.project_id)}/runs/${encodeURIComponent(run.run_id)}/task-retries`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              phase_key: selectedTaskDetail.phaseKey,
              task_key: selectedTaskDetail.key,
              mode: retryMode === "downstream" ? "downstream" : "current",
            }),
          }
        );
        setRetryNotice(`已提交重试: ${payload.op_id || ""}`);
      } catch (err) {
        setRetryError(err instanceof Error ? err.message : "任务重试提交失败");
      } finally {
        setRetrySubmitting(false);
      }
    }

    return h(
      "div",
      { className: "run-layout" },
      h(
        "section",
        { className: "card card-glow run-summary-card" },
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
        "div",
        { className: "run-main-grid" },
        h(
          "section",
          { className: "card run-flow-card" },
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
                h(
                  "div",
                  { className: "flow-step-head" },
                  h("div", { className: "flow-step-title" }, phase.title),
                  h("div", { className: "flow-step-subtitle" }, phase.rawTitle),
                  h(
                    "div",
                    { className: "flow-phase-badges" },
                    ...((phase.relations && phase.relations.badges) || []).map((badge) =>
                      h(
                        "span",
                        {
                          key: `${phase.key}-${badge.type}-${badge.label}`,
                          className: `flow-badge ${badge.type}`,
                        },
                        badge.label
                      )
                    )
                  )
                ),
                phase.relations && Array.isArray(phase.relations.hints) && phase.relations.hints.length
                  ? h(
                      "ul",
                      { className: "flow-relation-hints" },
                      ...phase.relations.hints.map((hint, hintIdx) =>
                        h("li", { key: `${phase.key}-hint-${hintIdx}` }, hint)
                      )
                    )
                  : null,
                phase.compositeTaskCards && phase.compositeTaskCards.length
                  ? h(
                      "div",
                      { className: "flow-composite-list" },
                      ...phase.compositeTaskCards.map((card) => {
                        const primary = card.primaryTask || null;
                        const selected =
                          primary &&
                          selectedTask &&
                          selectedTask.phaseKey === primary.phaseKey &&
                          selectedTask.taskKey === primary.key;
                        const onSelect = () =>
                          primary ? setSelectedTask({ phaseKey: primary.phaseKey, taskKey: primary.key }) : null;

                        const renderDualStatus = (designTask, reviewTask, row) =>
                          h(
                            "div",
                            { className: "flow-dual-status" },
                            h(
                              "span",
                              {
                                className: `flow-dual-pill design clickable ${String(
                                  (row && row.designStatus) ||
                                    (row ? "pending" : pairedRoleDisplayStatus(designTask, reviewTask, "design"))
                                )}${
                                  designTask ? " is-action" : ""
                                }`,
                                title: designTask ? `设计任务: ${designTask.name}` : "设计状态",
                                role: designTask ? "button" : undefined,
                                tabIndex: designTask ? 0 : undefined,
                                onClick: designTask ? (e) => selectTaskByCardTask(designTask, e) : undefined,
                                onKeyDown: designTask
                                  ? (e) => {
                                      if (e.key === "Enter" || e.key === " ") {
                                        e.preventDefault();
                                        selectTaskByCardTask(designTask, e);
                                      }
                                    }
                                  : undefined,
                              },
                              `设 ${taskStatusLabel(
                                String(
                                  (row && row.designStatus) ||
                                    (row ? "pending" : pairedRoleDisplayStatus(designTask, reviewTask, "design"))
                                )
                              )}${
                                (row && row.designRoundCurrent) || card.designRoundCurrent
                                  ? ` · R${(row && row.designRoundCurrent) || card.designRoundCurrent}`
                                  : (row && row.designRoundTotal) || card.designRoundTotal
                                    ? ` · ${((row && row.designRoundTotal) || card.designRoundTotal)}轮`
                                    : ""
                              }`
                            ),
                            h(
                              "span",
                              {
                                className: `flow-dual-pill review clickable ${String(
                                  (row && row.reviewStatus) ||
                                    (row ? "pending" : pairedRoleDisplayStatus(reviewTask, designTask, "review"))
                                )}${
                                  reviewTask ? " is-action" : ""
                                }`,
                                title: reviewTask ? `Review任务: ${reviewTask.name}` : "Review状态",
                                role: reviewTask ? "button" : undefined,
                                tabIndex: reviewTask ? 0 : undefined,
                                onClick: reviewTask ? (e) => selectTaskByCardTask(reviewTask, e) : undefined,
                                onKeyDown: reviewTask
                                  ? (e) => {
                                      if (e.key === "Enter" || e.key === " ") {
                                        e.preventDefault();
                                        selectTaskByCardTask(reviewTask, e);
                                      }
                                    }
                                  : undefined,
                              },
                              `审 ${taskStatusLabel(
                                String(
                                  (row && row.reviewStatus) ||
                                    (row ? "pending" : pairedRoleDisplayStatus(reviewTask, designTask, "review"))
                                )
                              )}${
                                (row && row.reviewRoundCurrent) || card.reviewRoundCurrent
                                  ? ` · R${(row && row.reviewRoundCurrent) || card.reviewRoundCurrent}`
                                  : (row && row.reviewRoundTotal) || card.reviewRoundTotal
                                    ? ` · ${((row && row.reviewRoundTotal) || card.reviewRoundTotal)}轮`
                                    : ""
                              }`
                            )
                          );

                        if (card.type === "subsystem_group") {
                          return h(
                            "section",
                            {
                              key: card.key,
                              className: `flow-composite-card subsystem-group ${card.status || "pending"}${selected ? " active" : ""}`,
                            },
                            h(
                              "button",
                              {
                                type: "button",
                                className: "flow-composite-head",
                                onClick: onSelect,
                              },
                              h("span", { className: "flow-composite-title" }, card.title),
                              renderDualStatus(card.designTask, card.reviewTask, null)
                            ),
                            h(
                              "div",
                              { className: "flow-subsystem-card-list" },
                              ...((card.cards || []).length
                                ? card.cards
                                : [
                                    {
                                      subsystemId: "",
                                      subsystemName: "（等待子系统拆分结果）",
                                      srIds: [],
                                      designStatus: card.designTask ? card.designTask.status : "pending",
                                      reviewStatus: card.reviewTask ? card.reviewTask.status : "pending",
                                    },
                                  ]).map((row, idx) =>
                                h(
                                  "div",
                                  { className: "flow-subsystem-card", key: `${card.key}-sub-${idx}-${row.subsystemId || "na"}` },
                                  h(
                                    "div",
                                    { className: "flow-subsystem-card-top" },
                                    h(
                                      "div",
                                      { className: "flow-subsystem-title-wrap" },
                                      h("span", { className: "flow-subsystem-title" }, row.subsystemName || row.subsystemId || "subsystem"),
                                      row.subsystemId
                                        ? h("span", { className: "flow-subsystem-id" }, row.subsystemId)
                                        : null
                                    ),
                                    renderDualStatus(card.designTask, card.reviewTask, row)
                                  ),
                                  h(
                                    "div",
                                    { className: "flow-subsystem-meta" },
                                    row.srIds && row.srIds.length
                                      ? `SR: ${row.srIds.join(", ")}`
                                      : "SR: （待分配）",
                                    row.extraStatus ? ` · 修订: ${row.extraStatus}` : "",
                                    card.tailTask ? ` · 后续: ${taskStatusLabel(card.tailTask.status)}` : ""
                                  ),
                                  (card.designTask && card.designTask.progressText) ||
                                  (card.reviewTask && card.reviewTask.progressText)
                                    ? h(
                                        "div",
                                        { className: "flow-subsystem-progress" },
                                        inferLiveSubsystem(card.designTask) === row.subsystemId && card.designTask && card.designTask.progressText
                                          ? card.designTask.progressText
                                          : inferLiveSubsystem(card.reviewTask) === row.subsystemId &&
                                              card.reviewTask &&
                                              card.reviewTask.progressText
                                            ? card.reviewTask.progressText
                                            : ""
                                      )
                                    : null
                                )
                              )
                            )
                          );
                        }

                        if (card.type === "paired") {
                          return h(
                            "button",
                            {
                              type: "button",
                              key: card.key,
                              className: `flow-composite-card paired ${card.status || "pending"}${selected ? " active" : ""}`,
                              onClick: onSelect,
                            },
                            h(
                              "div",
                              { className: "flow-composite-card-top" },
                              h("span", { className: "flow-composite-title" }, card.title),
                              renderDualStatus(card.designTask, card.reviewTask, null)
                            ),
                            h(
                              "div",
                              { className: "flow-composite-meta" },
                              card.designTask && card.designTask.inputHints && card.designTask.inputHints.length
                                ? `输入: ${card.designTask.inputHints.slice(0, 2).join(", ")}`
                                : "输入: -",
                              card.designTask && card.designTask.liveState && typeof card.designTask.liveState.event_count === "number"
                                ? ` · 轨迹:${card.designTask.liveState.event_count}`
                                : ""
                            )
                          );
                        }

                        return h(
                          "button",
                          {
                            type: "button",
                            key: card.key,
                            className: `flow-composite-card single ${card.status || "pending"}${selected ? " active" : ""}`,
                            onClick: onSelect,
                          },
                          h(
                            "div",
                            { className: "flow-composite-card-top" },
                            h("span", { className: "flow-composite-title" }, card.title),
                            h("span", { className: `flow-task-node-state ${card.status || "pending"}` }, taskStatusLabel(card.status))
                          ),
                          h(
                            "div",
                            { className: "flow-composite-meta" },
                            ...(Array.isArray(card.meta) && card.meta.length ? [card.meta.join(" · ")] : [primary && primary.progressText ? primary.progressText : ""])
                          )
                        );
                      })
                    )
                  : phase.agentTasks && phase.agentTasks.length
                  ? h(
                      "div",
                      { className: "flow-lane-grid" },
                      ...phase.agentTasks.map((agentBlock) =>
                        h(
                          "section",
                          {
                            className: `flow-lane ${agentBlock.laneType || "task"}${
                              agentBlock.parallelized ? " parallel" : ""
                            }`,
                            key: `${phase.key}-${agentBlock.agent}`,
                          },
                          h(
                            "div",
                            { className: "flow-lane-header" },
                            h("div", { className: "flow-agent-label" }, agentBlock.agent),
                            h(
                              "div",
                              { className: "flow-lane-meta" },
                              h("span", { className: "flow-lane-kind" }, agentBlock.laneType || "task"),
                              agentBlock.parallelized ? h("span", { className: "flow-lane-kind parallel" }, "并发实例") : null
                            )
                          ),
                          h(
                            "ol",
                            { className: "flow-lane-task-list" },
                            ...(agentBlock.tasks || []).map((task) => {
                              const selected =
                                selectedTask && selectedTask.phaseKey === task.phaseKey && selectedTask.taskKey === task.key;
                              return h(
                                "li",
                                { key: `${task.phaseKey}-${task.key}` },
                                h(
                                  "button",
                                  {
                                    type: "button",
                                    className: `flow-task-node ${task.status}${selected ? " active" : ""}`,
                                    onClick: () => setSelectedTask({ phaseKey: task.phaseKey, taskKey: task.key }),
                                  },
                                  h(
                                    "span",
                                    { className: "flow-task-node-top" },
                                    h("span", { className: "flow-task-node-name" }, task.name),
                                    h(
                                      "span",
                                      { className: `flow-task-node-state ${task.status}` },
                                      taskStatusLabel(task.status)
                                    )
                                  ),
                                  h(
                                    "span",
                                    { className: "flow-task-node-meta" },
                                    task.parallelized ? "并发节点" : "串行节点",
                                    task.liveState && typeof task.liveState.event_count === "number"
                                      ? ` · 轨迹:${task.liveState.event_count}`
                                      : "",
                                    task.inputHints && task.inputHints.length
                                      ? ` · 输入: ${task.inputHints.slice(0, 2).join(", ")}`
                                      : ""
                                  ),
                                  task.progressText
                                    ? h(
                                        "span",
                                        { className: "flow-task-node-progress", title: task.progressText },
                                        task.progressText
                                      )
                                    : null
                                )
                              );
                            })
                          )
                        )
                      )
                    )
                  : h(
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
          { className: "card run-task-card" },
        h("h2", null, "任务详细信息"),
        h(
          "div",
          { className: "task-detail-panel" },
          selectedTaskDetail
            ? h(
                "div",
                null,
                h("p", null, `阶段: ${selectedTaskDetail.phaseTitle} (${selectedTaskDetail.phaseKey})`),
                h("p", null, `Agent: ${selectedTaskDetail.agent}`),
                h("p", null, `任务: ${selectedTaskDetail.name}`),
                h("p", null, `任务Key: ${selectedTaskDetail.key}`),
                h("p", null, `状态: ${selectedTaskDetail.status}`),
                selectedTaskDetail.taskStateItem
                  ? h(
                      "p",
                      { className: "muted" },
                      `重试记录: ${selectedTaskDetail.taskStateItem.attempt_count || 0} 次 · 最新Attempt #${
                        selectedTaskDetail.taskStateItem.latest_attempt_no || 0
                      }`
                    )
                  : null,
                h(
                  "div",
                  { className: "task-retry-controls" },
                  h(
                    "label",
                    { className: "task-retry-mode" },
                    "重试模式",
                    h(
                      "select",
                      {
                        value: retryMode,
                        onChange: (e) => setRetryMode(String(e.target.value || "current")),
                        disabled: !!(activeOperation && activeOperation.status === "running") || retrySubmitting,
                      },
                      h("option", { value: "current" }, "仅当前任务"),
                      h("option", { value: "downstream" }, "当前任务 + 后续任务（跨阶段）")
                    )
                  ),
                  h(
                    "button",
                    {
                      type: "button",
                      className: "secondary",
                      onClick: submitRetry,
                      disabled: !!(activeOperation && activeOperation.status === "running") || retrySubmitting,
                    },
                    retrySubmitting ? "提交中..." : "重试任务"
                  )
                ),
                activeOperation && activeOperation.status === "running"
                  ? h(
                      "p",
                      { className: "warning" },
                      `当前有执行中的重试: ${activeOperation.phase_key || ""} / ${activeOperation.task_key || ""}`
                    )
                  : null,
                retryError ? h("p", { className: "warning" }, retryError) : null,
                retryNotice ? h("p", { className: "muted" }, retryNotice) : null,
                selectedTaskDetail.liveState && selectedTaskDetail.liveState.last_event
                  ? h(
                      "div",
                      { className: "task-live-summary" },
                      h("p", null, "最近进展"),
                      h(
                        "pre",
                        { className: "task-detail-json" },
                        JSON.stringify(selectedTaskDetail.liveState.last_event, null, 2)
                      )
                    )
                  : null,
                selectedTaskDetail.runtimeTaskKey
                  ? h("p", { className: "muted" }, `运行时匹配任务: ${selectedTaskDetail.runtimeTaskKey}`)
                  : null,
                selectedTaskDetail.inputHints && selectedTaskDetail.inputHints.length
                  ? h("p", null, `推荐输入字段: ${selectedTaskDetail.inputHints.join(", ")}`)
                  : h("p", { className: "muted" }, "推荐输入字段: 无"),
                selectedTaskDetail.runtimeResult && selectedTaskDetail.runtimeResult.artifact_id
                  ? h("p", null, `产物ID: ${selectedTaskDetail.runtimeResult.artifact_id}`)
                  : null,
                selectedTaskDetail.runtimeResult && selectedTaskDetail.runtimeResult.error
                  ? h("pre", { className: "error" }, String(selectedTaskDetail.runtimeResult.error))
                  : null,
                h(
                  "div",
                  { className: "task-memory-panel" },
                  h(
                    "div",
                    { className: "task-memory-header" },
                    h("h3", null, "任务记忆体"),
                    h(
                      "button",
                      {
                        type: "button",
                        className: "task-memory-toggle",
                        onClick: () => setTaskMemoryExpanded((v) => !v),
                        "aria-expanded": taskMemoryExpanded ? "true" : "false",
                      },
                      taskMemoryExpanded ? "收起" : "展开"
                    )
                  ),
                  taskMemoryExpanded
                    ? [
                        taskStateLoading ? h("p", { className: "muted", key: "loading" }, "加载中...") : null,
                        taskStateError ? h("p", { className: "warning", key: "err" }, `加载失败: ${taskStateError}`) : null,
                        taskStateDetail && taskStateDetail.task_state
                          ? h(
                              "div",
                              { key: "json" },
                              h(
                                "pre",
                                { className: "task-detail-json" },
                                JSON.stringify(taskStateDetail.task_state, null, 2)
                              )
                            )
                          : !taskStateLoading && !taskStateError
                            ? h("p", { className: "muted", key: "empty" }, "暂无任务记忆体（首次重试后将生成）。")
                            : null,
                      ]
                    : h(
                        "p",
                        { className: "muted" },
                        taskStateLoading
                          ? "任务记忆体加载中（默认折叠）"
                          : taskStateDetail && taskStateDetail.task_state
                            ? "任务记忆体已加载（默认折叠）"
                            : "任务记忆体默认折叠"
                      )
                ),
                h(
                  "div",
                  { className: "task-log-panel" },
                  h(
                    "div",
                    { className: "task-log-header" },
                    h("h3", null, "任务日志"),
                    h(
                      "p",
                      { className: "muted" },
                      `${taskLogLoading ? "刷新中" : "已同步"} · ${visibleTaskLogs.length} 条（步骤/LLM）`
                    )
                  ),
                  taskLogError ? h("p", { className: "warning" }, `日志加载失败: ${taskLogError}`) : null,
                  visibleTaskLogs.length
                    ? h(
                        "div",
                        { className: "task-log-list" },
                        ...visibleTaskLogs.map((evt) => {
                          const evtId = String(evt.id || `${evt.ts}-${evt.message}`);
                          const isTrace = String(evt.source || "") === "trace";
                          const expanded = !!expandedTraceLogIds[evtId];
                          const details = getTaskLogDetailsForDisplay(evt);
                          return h(
                            "article",
                            {
                              key: evtId,
                              className: `task-log-item ${String(evt.level || "info")}`,
                            },
                            h(
                              "div",
                              { className: "task-log-item-head" },
                              h("span", { className: "task-log-ts" }, String(evt.ts || "")),
                              h("span", { className: "task-log-source" }, isTrace ? "LLM" : "步骤"),
                              h("span", { className: `task-log-level ${String(evt.level || "info")}` }, String(evt.level || "info"))
                            ),
                            h("div", { className: "task-log-message" }, String(evt.message || "")),
                            isTrace && details
                              ? (() => {
                                  const meta = details.purpose_meta && typeof details.purpose_meta === "object" ? details.purpose_meta : {};
                                  const providerMeta =
                                    details.provider_response_meta && typeof details.provider_response_meta === "object"
                                      ? details.provider_response_meta
                                      : {};
                                  const tags = [];
                                  ["subagent", "step", "round", "subsystem", "fn", "module", "reviewer", "owner"].forEach((k) => {
                                    if (meta[k]) tags.push(`${k}:${meta[k]}`);
                                  });
                                  if (providerMeta.finish_reason) tags.push(`finish:${providerMeta.finish_reason}`);
                                  return h(
                                    "div",
                                    { className: "task-log-trace-block" },
                                    tags.length
                                      ? h(
                                          "div",
                                          { className: "task-log-tags" },
                                          ...tags.map((tag) => h("span", { key: `${evtId}-${tag}`, className: "task-log-tag" }, tag))
                                        )
                                      : null,
                                    h(
                                      "button",
                                      {
                                        type: "button",
                                        className: "task-log-toggle",
                                        onClick: () =>
                                          setExpandedTraceLogIds((prev) => ({ ...prev, [evtId]: !prev[evtId] })),
                                      },
                                      expanded ? "收起 LLM 记录" : "展开 LLM 记录"
                                    ),
                                    expanded
                                      ? h(
                                          "div",
                                          {
                                            className: "task-log-markdown",
                                            dangerouslySetInnerHTML: {
                                              __html: simpleMarkdownToHtml(traceMarkdownFromEvent(evt)),
                                            },
                                          }
                                        )
                                      : null
                                  );
                                })()
                              : null,
                            !isTrace && details && Object.keys(details).length
                              ? h("pre", { className: "task-log-details" }, JSON.stringify(details, null, 2))
                              : null
                          );
                        })
                      )
                    : h("p", { className: "muted" }, "暂无执行步骤/LLM调用日志，等待任务启动或 trace 写入。")
                ),
                selectedTaskDetail.runtimeResult
                  ? h(
                      "pre",
                      { className: "task-detail-json" },
                      JSON.stringify(selectedTaskDetail.runtimeResult, null, 2)
                    )
                  : null
              )
            : h("p", { className: "muted" }, "点击上方任意任务以查看详细信息。")
        )
      )
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
