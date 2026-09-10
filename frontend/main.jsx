import { IconButton, ErrorNotice, Modal } from "./components";
import ComposerModelPicker from "./ComposerModelPicker";
import SettingsPanel from "./SettingsPanel";
import TaskPanel from "./TaskPanel";
import ProjectPanel from "./ProjectPanel";
import RunMessage from "./RunMessage";
import React, { useCallback, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { Auth0Provider, useAuth0 } from "@auth0/auth0-react";
import {
  ArrowUp,
  Plus,
  Clock3,
  Search,
  Settings2,
  ChevronDown,
  ChevronRight,
  PanelLeftClose,
  PanelLeftOpen,
  CalendarDays,
  MoreHorizontal,
  Play,
  Pause,
  Archive,
  Download,
  Check,
  LoaderCircle,
  MessageSquare,
  Terminal,
  SlidersHorizontal,
  Eye,
  Square,
  Folder,
  X,
  Trash2,
  SquarePen,
  Sparkles,
  Paperclip,
  ArrowRight,
  Laptop,
} from "lucide-react";
import {
  request,
  exportHistory,
  formatDate,
  scheduleLabel,
  setAccessTokenProvider,
} from "./api";
import "./style.css";

const empty = {
  jobs: [],
  runs: [],
  projects: [],
  settings: {},
  scheduler_active: false,
};
const stateNames = {
  enabled: "Scheduled",
  paused: "Paused",
  completed: "Completed",
  archived: "Archived",
  draft: "Conversation",
  failed: "Needs attention",
};
const errorStates = ["failed", "timed_out"];
function useTheme(theme) {
  useEffect(() => {
    const media = matchMedia("(prefers-color-scheme: dark)");
    const apply = () => {
      document.documentElement.dataset.theme =
        theme === "system" ? (media.matches ? "dark" : "light") : theme;
      localStorage.setItem("oncue-theme", theme);
    };
    apply();
    media.addEventListener("change", apply);
    return () => media.removeEventListener("change", apply);
  }, [theme]);
}

function App({ accountUser = null, onLogout = null }) {
  const [data, setData] = useState(empty),
    [selected, setSelected] = useState(null),
    [query, setQuery] = useState(""),
    [taskFilter, setTaskFilter] = useState("all"),
    [archived, setArchived] = useState(false),
    [sidebar, setSidebar] = useState(false),
    [collapsed, setCollapsed] = useState(false),
    [settingsOpen, setSettingsOpen] = useState(false),
    [draftModel, setDraftModel] = useState(null),
    [editor, setEditor] = useState(false),
    [projectEditor, setProjectEditor] = useState(null),
    [projectCreating, setProjectCreating] = useState(false),
    [projectName, setProjectName] = useState(""),
    [projectFilter, setProjectFilter] = useState("all"),
    [deleteTarget, setDeleteTarget] = useState(null),
    [messages, setMessages] = useState([]),
    [active, setActive] = useState([]),
    [before, setBefore] = useState(null),
    [text, setText] = useState(""),
    [sending, setSending] = useState(false),
    [error, setError] = useState(""),
    [connected, setConnected] = useState(true),
    [log, setLog] = useState(null),
    [menu, setMenu] = useState(false),
    [loading, setLoading] = useState(false),
    [olderBusy, setOlderBusy] = useState(false),
    [selectedComputer, setSelectedComputer] = useState("");
  const selectedRef = useRef(selected),
    knownRuns = useRef(null),
    lastData = useRef(""),
    loadedRef = useRef(null),
    scroller = useRef(null),
    nearBottom = useRef(true),
    input = useRef(null),
    computerRef = useRef(selectedComputer);
  selectedRef.current = selected;
  computerRef.current = selectedComputer;
  const task = data.jobs.find((j) => j.slug === selected),
    prefs = data.settings;
  const currentModel = task
    ? { provider: task.provider, model: task.model }
    : draftModel || { provider: prefs.provider || "codex", model: prefs.model };
  useTheme(prefs.theme || localStorage.getItem("oncue-theme") || "system");
  const refresh = useCallback(async () => {
    try {
      const result = await request("/api/tasks");
      delete result.generated_at;
      const signature = JSON.stringify(result);
      if (signature !== lastData.current) {
        lastData.current = signature;
        setData(result);
        if (!computerRef.current && result.computers?.length) {
          computerRef.current = result.computers[0].id;
          setSelectedComputer(result.computers[0].id);
          if (result.computers[0].defaults?.model)
            setDraftModel(result.computers[0].defaults);
        }
      }
      setConnected(true);
      const terminal = result.runs.filter((r) =>
        ["succeeded", "failed", "timed_out"].includes(r.status),
      );
      if (
        knownRuns.current &&
        result.settings.notifications &&
        !result.settings.desktop_notifications &&
        "Notification" in window &&
        Notification.permission === "granted"
      )
        for (const run of terminal)
          if (!knownRuns.current.has(run.id) && run.notify !== 0)
            new Notification("OnCue", { body: `${run.job}: ${run.status}` });
      knownRuns.current = new Set(terminal.map((r) => r.id));
      const slug = selectedRef.current;
      if (slug) {
        const conversation = await request("/api/conversation/" + slug);
        if (selectedRef.current !== slug) return;
        setMessages((old) => {
          const merged = new Map(
            [...old, ...conversation.messages].map((m) => [m.id, m]),
          );
          return [...merged.values()].sort((a, b) => a.id - b.id);
        });
        setActive(conversation.active_runs);
        if (loadedRef.current !== slug) {
          setBefore(conversation.before);
          loadedRef.current = slug;
        }
        setLoading(false);
      }
    } catch (e) {
      setConnected(false);
      setError(e.message);
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    refresh();
    let running = false;
    const timer = setInterval(async () => {
      if (running || document.hidden) return;
      running = true;
      try {
        await refresh();
      } finally {
        running = false;
      }
    }, 2000);
    const visible = () => {
      if (!document.hidden) refresh();
    };
    document.addEventListener("visibilitychange", visible);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", visible);
    };
  }, [refresh]);
  useEffect(() => {
    if (nearBottom.current && scroller.current)
      scroller.current.scrollTo({
        top: scroller.current.scrollHeight,
        behavior: "smooth",
      });
  }, [messages.length, active.length, sending]);
  function select(slug) {
    selectedRef.current = slug;
    setSelected(slug);
    setDraftModel(null);
    setMessages([]);
    setActive([]);
    setBefore(null);
    loadedRef.current = null;
    setError("");
    setMenu(false);
    setSidebar(false);
    nearBottom.current = true;
    setLoading(!!slug);
    setText("");
    if (slug) refresh();
    else input.current?.focus();
  }
  async function action(fn) {
    setError("");
    try {
      await fn();
      await refresh();
    } catch (e) {
      setError(e.message);
    }
  }
  useEffect(() => {
    if (!input.current) return;
    input.current.style.height = "auto";
    input.current.style.height = `${Math.min(input.current.scrollHeight, 220)}px`;
  }, [text, selected]);
  async function send(e) {
    e.preventDefault();
    if (!text.trim() || sending) return;
    if (!currentModel.model) {
      setError("Choose a model below the message box to get started.");
      return;
    }
    const value = text;
    setSending(true);
    setError("");
    nearBottom.current = true;
    try {
      const result = await request("/api/message", "POST", {
        slug: selected,
        text: value,
        options: selected
          ? undefined
          : {
              ...(draftModel || {}),
              ...(selectedComputer ? { computer_id: selectedComputer } : {}),
            },
      });
      setText("");
      if (result.slug !== selected) {
        selectedRef.current = result.slug;
        setSelected(result.slug);
        loadedRef.current = null;
        setMessages([]);
      }
      await refresh();
    } catch (e) {
      setError(e.message);
    } finally {
      setSending(false);
    }
  }
  async function earlier() {
    if (!before) return;
    const slug = selected;
    setOlderBusy(true);
    nearBottom.current = false;
    const el = scroller.current,
      height = el?.scrollHeight;
    try {
      const result = await request(
        `/api/conversation/${selected}?before=${before}`,
      );
      if (selectedRef.current !== slug) return;
      setMessages((old) => [...result.messages, ...old]);
      setBefore(result.before);
      requestAnimationFrame(() => {
        if (el) el.scrollTop += el.scrollHeight - height;
      });
    } catch (e) {
      setError(e.message);
    } finally {
      setOlderBusy(false);
    }
  }
  const closeSettings = useCallback(() => setSettingsOpen(false), []),
    closeEditor = useCallback(() => setEditor(false), []),
    closeLog = useCallback(() => setLog(null), []);
  useEffect(() => {
    const escape = (event) => {
      if (event.key === "Escape" && !document.querySelector("dialog[open]")) {
        setMenu(false);
        if (sidebar) {
          setSidebar(false);
          document.querySelector('[aria-label="Open sidebar"]')?.focus();
        }
      }
    };
    document.addEventListener("keydown", escape);
    return () => document.removeEventListener("keydown", escape);
  }, [sidebar]);
  const filtered = data.jobs
    .filter(
      (j) =>
        (archived ? j.state === "archived" : j.state !== "archived") &&
        (projectFilter === "all" ||
          (projectFilter === "unassigned"
            ? !j.task_project_id
            : j.task_project_id === projectFilter)) &&
        (taskFilter === "all" ||
          (taskFilter === "attention"
            ? errorStates.includes(j.last_status)
            : j.state === "enabled")) &&
        j.title.toLowerCase().includes(query.toLowerCase()),
    )
    .sort((a, b) => a.title.localeCompare(b.title));
  async function createProject(e) {
    e.preventDefault();
    const name = projectName.trim();
    if (!name) return;
    try {
      const result = await request("/api/projects", "POST", { name });
      setProjectName("");
      setProjectCreating(false);
      setProjectFilter(result.id);
      await refresh();
    } catch (e) {
      setError(e.message);
    }
  }
  const disabled =
    sending ||
    active.some((r) => r.kind === "plan") ||
    task?.state === "archived" ||
    task?.runner === "command";
  const composer = (
    <form className={`composer ${sending ? "submitting" : ""}`} onSubmit={send}>
      <textarea
        ref={input}
        aria-label="Message"
        placeholder={
          task
            ? "Ask a follow-up or change the schedule…"
            : "What should I do, and when?"
        }
        value={text}
        disabled={task?.state === "archived" || task?.runner === "command"}
        rows={text.split("\n").length > 2 ? 4 : 2}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault();
            if (!disabled) send(e);
          }
        }}
      />
      <div className="composer-tools">
        <IconButton
          label="Task settings"
          onClick={() => setEditor(true)}
          type="button"
        >
          <Plus size={18} />
        </IconButton>
        <button
          className="attach-files-button"
          type="button"
          onClick={() => setEditor(true)}
          aria-label="Attach files"
        >
          <Paperclip size={17} />
          <span>Attach files</span>
        </button>
        <ComposerModelPicker
          key={selected || "new"}
          {...currentModel}
          disabled={disabled}
          onChange={async (choice) => {
            if (task) {
              await request("/api/tasks/" + task.slug, "PATCH", {
                ...choice,
                effort: "",
              });
              await refresh();
            } else setDraftModel(choice);
          }}
        />
        <span className="compose-spacer" />
        <button
          className="send-button"
          type="submit"
          disabled={disabled || !text.trim()}
          aria-label="Send message"
        >
          {sending ? (
            <LoaderCircle className="spin" size={18} />
          ) : (
            <ArrowUp size={19} />
          )}
        </button>
      </div>
    </form>
  );
  return (
    <div className={`app ${collapsed ? "sidebar-collapsed" : ""}`}>
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      <div
        className={`sidebar-backdrop ${sidebar ? "visible" : ""}`}
        onClick={() => setSidebar(false)}
      />
      <aside
        aria-label="Workspace navigation"
        className={sidebar ? "open" : ""}
      >
        <div className="brand-row">
          <button className="brand" onClick={() => select(null)}>
            <span className="brand-mark">
              <Clock3 size={21} />
            </span>
            OnCue
          </button>
          <IconButton
            label="Collapse sidebar"
            onClick={() => {
              setCollapsed(true);
              setSidebar(false);
            }}
          >
            <PanelLeftClose size={17} />
          </IconButton>
        </div>
        <button className="new-task" onClick={() => select(null)}>
          <SquarePen size={18} />
          New task
        </button>
        <label className="search">
          <Search size={14} />
          <input
            aria-label="Search tasks"
            placeholder="Search tasks"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>
        {!archived && (
          <section className="sidebar-section projects-section">
            <div className="section-heading">
              <button
                className="section-title"
                onClick={() => setProjectFilter("all")}
              >
                Projects
              </button>
              {!data.remote && <button
                className="section-action"
                aria-label="New project"
                title="New project"
                onClick={() => setProjectCreating(true)}
              >
                <Plus size={15} />
              </button>}
            </div>
            {projectCreating && (
              <form className="inline-project-form" onSubmit={createProject}>
                <Folder size={15} />
                <input
                  autoFocus
                  aria-label="Project name"
                  placeholder="Project name"
                  value={projectName}
                  onChange={(e) => setProjectName(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Escape") {
                      setProjectCreating(false);
                      setProjectName("");
                    }
                  }}
                />
                <button
                  type="submit"
                  aria-label="Create project"
                  disabled={!projectName.trim()}
                >
                  <Check size={14} />
                </button>
                <button
                  type="button"
                  aria-label="Cancel"
                  onClick={() => {
                    setProjectCreating(false);
                    setProjectName("");
                  }}
                >
                  <X size={14} />
                </button>
              </form>
            )}
            <div className="project-list">
              {data.projects.map((project) => (
                <div
                  className={`project-row ${projectFilter === project.id ? "selected" : ""}`}
                  key={project.id}
                >
                  <button
                    className="project-select"
                    onClick={() => setProjectFilter(project.id)}
                  >
                    <span
                      className="project-sidebar-icon"
                      style={{ color: project.color || undefined }}
                    >
                      {project.icon || <Folder size={15} />}
                    </span>
                    <span>{project.name}</span>
                    <small>{project.task_count}</small>
                  </button>
                  {!data.remote && <button
                    className="project-menu"
                    aria-label={`Edit ${project.name}`}
                    onClick={() => setProjectEditor(project)}
                  >
                    <MoreHorizontal size={15} />
                  </button>}
                </div>
              ))}
              <button
                className={`project-select unassigned ${projectFilter === "unassigned" ? "selected" : ""}`}
                onClick={() => setProjectFilter("unassigned")}
              >
                <Folder size={15} />
                <span>Unassigned</span>
              </button>
            </div>
          </section>
        )}
        <div className="section-heading tasks-heading">
          <button
            className="section-title"
            onClick={() => setProjectFilter("all")}
          >
            {archived
              ? "Archived"
              : projectFilter === "all"
                ? "Tasks"
                : data.projects.find((p) => p.id === projectFilter)?.name ||
                  "Unassigned"}
          </button>
          <button
            className={archived ? "active-filter" : ""}
            aria-label={archived ? "Show current tasks" : "Show archived tasks"}
            title={archived ? "Show current tasks" : "Show archived tasks"}
            onClick={() => {
              setArchived(!archived);
              setProjectFilter("all");
              setTaskFilter("all");
            }}
          >
            <Archive size={13} />
          </button>
        </div>
        <div className="task-filters" aria-label="Filter tasks">
          {[
            ["all", "All"],
            ["scheduled", "Scheduled"],
            ["attention", "Attention"],
          ].map(([id, label]) => (
            <button
              key={id}
              aria-pressed={taskFilter === id}
              onClick={() => setTaskFilter(id)}
            >
              {label}
            </button>
          ))}
        </div>
        <nav aria-label="Task conversations">
          {filtered.map((j) => (
            <button
              key={j.slug}
              className={`task-link ${selected === j.slug ? "selected" : ""}`}
              aria-current={selected === j.slug ? "page" : undefined}
              title={j.title}
              onClick={() => select(j.slug)}
            >
              {j.config.mode === "monitor" ? (
                <Eye size={15} />
              ) : j.state === "draft" ? (
                <MessageSquare size={15} />
              ) : (
                <Clock3 size={15} />
              )}
              <span>
                <strong>{j.title}</strong>
                <small>
                  {errorStates.includes(j.last_status)
                    ? "Needs attention"
                    : stateNames[j.state]}
                </small>
              </span>
              <span
                className={`task-dot ${errorStates.includes(j.last_status) ? "error" : j.state}`}
              />
            </button>
          ))}
          {filtered.length === 0 && (
            <p className="nav-empty">
              {query || taskFilter !== "all"
                ? "No matching tasks"
                : archived
                  ? "Nothing archived"
                  : "Your tasks will appear here"}
            </p>
          )}
        </nav>
        <div className="sidebar-bottom">
          {onLogout ? (
            <button
              className="account-summary"
              title={accountUser?.email || "OnCue account"}
              onClick={onLogout}
            >
              {accountUser?.picture ? (
                <img src={accountUser.picture} alt="" referrerPolicy="no-referrer" />
              ) : (
                <span>{(accountUser?.email || "O")[0].toUpperCase()}</span>
              )}
              <span>{accountUser?.email || "Sign out"}</span>
            </button>
          ) : (
            <div className="account-summary" title="Available on this computer">
              <span>L</span>
              <span>Local only</span>
            </div>
          )}
          {!data.remote && <button onClick={() => setSettingsOpen(true)}>
            <Settings2 size={16} />
            Settings
          </button>}
          <div className="service-status">
            <span
              className={`status-dot ${connected && data.scheduler_active ? "ready" : ""}`}
            />
            {connected
              ? data.remote
                ? data.scheduler_active
                  ? `${data.computers.filter((computer) => computer.online).length} computer${data.computers.filter((computer) => computer.online).length === 1 ? "" : "s"} online`
                  : "Computers are offline"
                : data.scheduler_active
                ? data.account?.configured
                  ? data.account.sync_error
                    ? "Running · sync needs attention"
                    : data.account.last_sync_at
                      ? `Running · synced ${formatDate(data.account.last_sync_at)}`
                      : "Running · waiting to sync"
                  : "Running on this computer"
                : "Scheduler is offline"
              : "Reconnecting…"}
          </div>
        </div>
      </aside>
      <main id="main-content" tabIndex={-1}>
        <header className="topbar">
          <IconButton
            label="Open sidebar"
            className="icon-button show-sidebar"
            onClick={() => {
              setCollapsed(false);
              setSidebar(true);
            }}
          >
            <PanelLeftOpen size={18} />
          </IconButton>
          <div className="breadcrumb">
            {task ? (
              <>
                <span>Tasks</span>
                <ChevronRight size={13} />
                <strong>{task.title}</strong>
              </>
            ) : (
              <strong className="home-title">
                OnCue <span>Your time, back.</span>
              </strong>
            )}
          </div>
          <div className="top-actions">
            {task && (
              <>
                {task.state !== "draft" && task.state !== "archived" && (
                  <button
                    className="quiet run-now-button"
                    disabled={sending || active.length > 0}
                    onClick={() =>
                      action(() =>
                        request(`/api/tasks/${task.slug}/run`, "POST", {}),
                      )
                    }
                  >
                    <Play size={14} /> Run now
                  </button>
                )}
                <button
                  className="quiet task-details-button"
                  aria-label="Task details"
                  onClick={() => setEditor(true)}
                >
                  <SlidersHorizontal size={14} />
                  <span>Task details</span>
                </button>
                <div className="menu-anchor">
                  <IconButton
                    label="More task actions"
                    onClick={() => setMenu(!menu)}
                  >
                    <MoreHorizontal size={20} />
                  </IconButton>
                  {menu && (
                    <>
                      <button
                        className="menu-dismiss"
                        aria-label="Close task menu"
                        onClick={() => setMenu(false)}
                      />
                      <div className="action-menu">
                        {task.state !== "archived" && (
                          <>
                            <button
                              onClick={() => {
                                setMenu(false);
                                action(() =>
                                  request(
                                    `/api/tasks/${task.slug}/${task.state === "paused" ? "resume" : "pause"}`,
                                    "POST",
                                    {},
                                  ),
                                );
                              }}
                            >
                              {task.state === "paused" ? (
                                <Play size={14} />
                              ) : (
                                <Pause size={14} />
                              )}{" "}
                              {task.state === "paused" ? "Resume" : "Pause"}
                            </button>
                          </>
                        )}
                        {!data.remote && <button
                          onClick={() => {
                            setMenu(false);
                            action(() => exportHistory(task.slug));
                          }}
                        >
                          <Download size={14} />
                          Export history
                        </button>}
                        {task.state !== "archived" && (
                          <button
                            onClick={() => {
                              setMenu(false);
                              action(() =>
                                request(
                                  `/api/tasks/${task.slug}/archive`,
                                  "POST",
                                  {},
                                ),
                              );
                            }}
                          >
                            <Archive size={14} />
                            Archive task
                          </button>
                        )}
                        {!data.remote && <button
                          className="danger-action"
                          onClick={() => {
                            setMenu(false);
                            setDeleteTarget(task);
                          }}
                        >
                          <Trash2 size={14} />
                          Delete task
                        </button>}
                      </div>
                    </>
                  )}
                </div>
              </>
            )}
          </div>
        </header>
        {!selected ? (
          <div className="landing">
            <div className="welcome">
              <span className="welcome-mark">
                <Sparkles size={27} />
              </span>
              <h1>What can I take off your plate?</h1>
              <p>Make room for what matters. Give me a task and a time.</p>
            </div>
            <div className="landing-composer">
              {composer}
              <ErrorNotice onClose={() => setError("")}>{error}</ErrorNotice>
              <div className="suggestions">
                {[
                  [
                    "daily",
                    Clock3,
                    "Start your day informed",
                    "A daily briefing, ready when you are.",
                    "Every weekday at 8 AM, give me a short briefing on the latest AI news, with sources.",
                  ],
                  [
                    "monitor",
                    Eye,
                    "Keep an eye on something",
                    "Follow updates and know when things change.",
                    "Check every Monday at 9 AM whether an official release date has been announced for ",
                  ],
                  [
                    "once",
                    CalendarDays,
                    "Plan something for later",
                    "The right task, at the right time.",
                    "Tomorrow at 9 AM, give me ",
                  ],
                ].map(([id, Icon, title, description, prompt]) => (
                  <button
                    key={id}
                    onClick={() => {
                      setText(prompt);
                      input.current?.focus();
                    }}
                  >
                    <span className={`suggestion-icon ${id}`}>
                      <Icon size={19} />
                    </span>
                    <strong>{title}</strong>
                    <small>{description}</small>
                    <ArrowRight size={16} className="suggestion-arrow" />
                  </button>
                ))}
              </div>
            </div>
            <p className="landing-footnote">
              <Laptop size={14} />
              Runs locally. Your computer needs to be awake and connected.
            </p>
            {data.computers?.length > 1 && (
              <label className="computer-picker">
                Run new tasks on
                <select
                  value={selectedComputer}
                  onChange={(event) => {
                    computerRef.current = event.target.value;
                    setSelectedComputer(event.target.value);
                    const computer = data.computers.find((item) => item.id === event.target.value);
                    if (computer?.defaults?.model) setDraftModel(computer.defaults);
                  }}
                >
                  {data.computers.map((computer) => (
                    <option key={computer.id} value={computer.id}>
                      {computer.name} · {computer.online ? "online" : "offline"}
                    </option>
                  ))}
                </select>
              </label>
            )}
          </div>
        ) : (
          <>
            <div
              className="conversation-scroll"
              ref={scroller}
              onScroll={(e) => {
                const el = e.currentTarget;
                nearBottom.current =
                  el.scrollHeight - el.scrollTop - el.clientHeight < 100;
              }}
            >
              <div className="conversation-content">
                <div className="conversation-heading">
                  <h1>{task?.title || "Your task"}</h1>
                  {task && task.state !== "draft" && (
                    <button
                      className="schedule-pill"
                      onClick={() => setEditor(true)}
                    >
                      <CalendarDays size={13} />
                      {scheduleLabel(task)}
                      <span className="pill-divider" />
                      {stateNames[task.state]}
                      <ChevronDown size={12} />
                    </button>
                  )}
                  {task?.next_run && (
                    <p className="next-run">
                      Next run {formatDate(task.next_run)} · {task.timezone}
                    </p>
                  )}
                  {task?.config.condition && (
                    <p className="stop-condition">
                      <Eye size={13} />
                      Stop when {task.config.condition}
                    </p>
                  )}
                </div>
                {before && (
                  <button
                    className="load-older"
                    disabled={olderBusy}
                    onClick={earlier}
                  >
                    {olderBusy ? (
                      <LoaderCircle size={13} className="spin" />
                    ) : (
                      <Clock3 size={13} />
                    )}
                    Earlier messages
                  </button>
                )}
                {loading && (
                  <div className="loading-history">
                    <LoaderCircle size={18} className="spin" />
                    Loading conversation
                  </div>
                )}
                {!loading && messages.length === 0 && (
                  <div className="empty-conversation">
                    <MessageSquare size={25} />
                    <p>This is where your task’s story unfolds.</p>
                    <small>Every response and update will stay here.</small>
                  </div>
                )}
                {messages.map((m) => (
                  <RunMessage
                    key={m.id}
                    message={m}
                    retryMinutes={prefs.retry_minutes || 30}
                    onRetry={(id, minutes) =>
                      action(() =>
                        request(`/api/runs/${id}/retry`, "POST", { minutes }),
                      )
                    }
                    onLog={data.remote ? undefined : (id) =>
                      action(async () =>
                        setLog(await request(`/api/runs/${id}/log`)),
                      )
                    }
                  />
                ))}
                {active.map((run) => (
                  <div className="active-run" key={run.id}>
                    {run.status === "running" ? (
                      <LoaderCircle className="spin" size={16} />
                    ) : (
                      <Clock3 size={16} />
                    )}
                    <div>
                      <strong>
                        {run.retry_at
                          ? `Retry ${formatDate(run.retry_at)}`
                          : run.status === "running"
                            ? run.kind === "plan"
                              ? "Thinking it through…"
                              : "Working on your task…"
                            : "Ready to run"}
                      </strong>
                      <small>
                        {run.retry_at
                          ? "The failed attempt stays in your history."
                          : run.status === "running"
                            ? "You can leave this open or come back later."
                            : "Waiting for an available worker."}
                      </small>
                    </div>
                    <IconButton
                      label="Cancel run"
                      onClick={() =>
                        action(() =>
                          request(`/api/runs/${run.id}/cancel`, "POST", {}),
                        )
                      }
                    >
                      <Square size={13} />
                    </IconButton>
                  </div>
                ))}
              </div>
            </div>
            <div className="conversation-bottom">
              <ErrorNotice onClose={() => setError("")}>{error}</ErrorNotice>
              {task?.state === "archived" ? (
                <div className="archived-notice">
                  <Archive size={15} />
                  Archived. Your conversation and responses are preserved.
                </div>
              ) : task?.runner === "command" ? (
                <button className="quiet" onClick={() => setEditor(true)}>
                  <Terminal size={15} />
                  Edit shell task
                </button>
              ) : (
                composer
              )}
              <div className="composer-caption">
                {active.some((r) => r.kind === "plan")
                  ? "Your message is being processed."
                  : "Shift + Enter for a new line"}
                <span>Responses stay in this conversation.</span>
              </div>
            </div>
          </>
        )}
      </main>
      {settingsOpen && (
        <SettingsPanel
          initial={prefs}
          onClose={closeSettings}
          onSaved={refresh}
        />
      )}{" "}
      {editor && (
        <TaskPanel
          task={task}
          settings={{ ...prefs, ...draftModel }}
          initialText={text}
          remote={!!data.remote}
          computerId={task?.computer_id || selectedComputer}
          onClose={closeEditor}
          onSaved={(slug) => {
            select(slug);
            refresh();
          }}
        />
      )}
      {projectEditor && (
        <ProjectPanel
          project={projectEditor}
          onClose={() => setProjectEditor(null)}
          onSaved={refresh}
        />
      )}
      {deleteTarget && (
        <Modal title="Delete task?" onClose={() => setDeleteTarget(null)}>
          <div className="confirm-dialog">
            <p>
              <strong>{deleteTarget.title}</strong> and its conversation, run
              history, outputs, and task files will be permanently deleted.
            </p>
            <div className="modal-footer">
              <button
                type="button"
                className="quiet"
                onClick={() => setDeleteTarget(null)}
              >
                Cancel
              </button>
              <button
                type="button"
                className="danger-button"
                onClick={() =>
                  action(async () => {
                    await request(
                      `/api/tasks/${deleteTarget.slug}`,
                      "DELETE",
                      {},
                    );
                    setDeleteTarget(null);
                    select(null);
                  })
                }
              >
                Delete permanently
              </button>
            </div>
          </div>
        </Modal>
      )}
      {log && (
        <Modal title="Execution log" onClose={closeLog} wide>
          <div className="log-body">
            <p className="hint">
              {log.truncated
                ? "Preview limited to 256 KiB. Export history for the complete log."
                : log.status}
            </p>
            <pre>{log.text || "No output yet."}</pre>
          </div>
        </Modal>
      )}
    </div>
  );
}

function AccountGate({ config }) {
  const {
    isLoading,
    isAuthenticated,
    loginWithRedirect,
    logout,
    getAccessTokenSilently,
    user,
    error,
  } = useAuth0();
  const [ready, setReady] = useState(config.mode === "cloud"),
    [claimed, setClaimed] = useState(config.mode === "cloud"),
    [problem, setProblem] = useState("");
  useEffect(() => {
    if (!isAuthenticated) {
      setAccessTokenProvider(null);
      setReady(false);
      return;
    }
    setAccessTokenProvider(() =>
      getAccessTokenSilently({
        authorizationParams: { audience: config.auth0_audience },
      }),
    );
    if (config.mode === "cloud") {
      setReady(true);
      setClaimed(true);
      return;
    }
    getAccessTokenSilently({
      authorizationParams: { audience: config.auth0_audience },
    })
      .then(() => request("/api/account/session", "POST", {}))
      .then((value) => {
        setClaimed(value.claimed);
        setReady(true);
      })
      .catch((e) => setProblem(e.message));
  }, [isAuthenticated, getAccessTokenSilently, config]);
  async function claim() {
    try {
      await request("/api/account/claim", "POST", {
        name: navigator.userAgentData?.platform || "OnCue computer",
      });
      setClaimed(true);
    } catch (e) {
      setProblem(e.message);
    }
  }
  if (isLoading)
    return (
      <div className="account-gate">
        <LoaderCircle className="spin" />
        <p>Checking your account…</p>
      </div>
    );
  if (!isAuthenticated)
    return (
      <div className="account-gate">
        <span className="welcome-mark">
          <Clock3 size={29} />
        </span>
        <h1>Welcome to OnCue</h1>
        <p>Sign in to reach your tasks from any device.</p>
        {(error || problem) && (
          <ErrorNotice>{error?.message || problem}</ErrorNotice>
        )}
        <button
          className="primary"
          onClick={() =>
            loginWithRedirect({
              authorizationParams: { connection: "google-oauth2" },
            })
          }
        >
          Continue with Google
        </button>
      </div>
    );
  if (!ready)
    return (
      <div className="account-gate">
        <LoaderCircle className="spin" />
        <p>Connecting this installation…</p>
        {problem && <ErrorNotice>{problem}</ErrorNotice>}
      </div>
    );
  if (!claimed)
    return (
      <div className="account-gate">
        <Laptop size={32} />
        <h1>Link this computer</h1>
        <p>
          Claim the existing tasks for <strong>{user?.email}</strong> and upload
          their task history. Provider credentials, logs, workspaces, and
          attachments stay here.
        </p>
        {problem && <ErrorNotice>{problem}</ErrorNotice>}
        <button className="primary" onClick={claim}>
          Claim tasks and link computer
        </button>
        <button
          className="quiet"
          onClick={() =>
            logout({ logoutParams: { returnTo: location.origin } })
          }
        >
          Use another account
        </button>
      </div>
    );
  return (
    <App
      accountUser={user}
      onLogout={() => logout({ logoutParams: { returnTo: location.origin } })}
    />
  );
}

function AccountBootstrap() {
  const [config, setConfig] = useState(null),
    [error, setError] = useState("");
  useEffect(() => {
    fetch("/api/account/status", { cache: "no-store" })
      .then(async (r) => {
        if (!r.ok) throw new Error("Account configuration is unavailable");
        return r.json();
      })
      .then(setConfig)
      .catch((e) => setError(e.message));
  }, []);
  if (error)
    return (
      <div className="account-gate">
        <h1>OnCue needs account configuration</h1>
        <p>{error}</p>
      </div>
    );
  if (!config)
    return (
      <div className="account-gate">
        <LoaderCircle className="spin" />
      </div>
    );
  if (!config.configured) return <App />;
  return (
    <Auth0Provider
      domain={config.auth0_domain}
      clientId={config.auth0_client_id}
      cacheLocation="memory"
      useRefreshTokens
      useRefreshTokensFallback
      authorizationParams={{
        redirect_uri: location.origin,
        audience: config.auth0_audience,
        scope: "openid profile email",
      }}
    >
      <AccountGate config={config} />
    </Auth0Provider>
  );
}

class ErrorBoundary extends React.Component {
  state = { error: null };
  static getDerivedStateFromError(error) {
    return { error };
  }
  render() {
    return this.state.error ? (
      <div className="fatal-error">
        <h1>Let’s get you back on track.</h1>
        <p>The interface couldn’t load. Your tasks and history remain saved.</p>
        <button onClick={() => location.reload()}>Reload OnCue</button>
      </div>
    ) : (
      this.props.children
    );
  }
}
createRoot(document.getElementById("root")).render(
  <ErrorBoundary>
    <AccountBootstrap />
  </ErrorBoundary>,
);
