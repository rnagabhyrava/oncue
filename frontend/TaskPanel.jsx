import ModelSelect from "./ModelSelect";
import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  ChevronDown,
  CalendarDays,
  LoaderCircle,
  Monitor,
  SlidersHorizontal,
} from "lucide-react";
import { request, formatDate } from "./api";
import { ErrorNotice, Modal, Field, Toggle } from "./components";
export default function TaskPanel({
  task,
  settings,
  initialText,
  onClose,
  onSaved,
}) {
  const [values, setValues] = useState({
    instructions: initialText || "",
    title: "",
    provider: settings.provider || "codex",
    model: settings.model || "",
    frequency: "daily",
    time: "09:00",
    date: new Date().toLocaleDateString("en-CA"),
    weekday: 1,
    cron: "",
    timezone: settings.timezone || "UTC",
    mode: "task",
    condition: "",
    remember: true,
    retry_safe: false,
    max_checks: 365,
    runner: "codex",
    timeout: 1800,
    effort: "",
    sandbox: "read-only",
    auto_approve: false,
    enabled: true,
    ...task,
    ...task?.timing,
    ...task?.config,
    mode: task?.config?.mode === "monitor" ? "monitor" : "task",
    effort: task?.reasoning_effort || "",
    enabled: task?.state !== "paused",
  });
  const [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [loading, setLoading] = useState(!!task),
    [next, setNext] = useState(""),
    [providers, setProviders] = useState([]),
    [projects, setProjects] = useState([]),
    [attachments, setAttachments] = useState([]);
  const set = (key, value) => setValues((v) => ({ ...v, [key]: value }));
  useEffect(() => {
    let alive = true;
    if (task)
      request("/api/tasks/" + task.slug)
        .then((d) => {
          if (alive) {
            set("instructions", d.instructions);
            setLoading(false);
          }
        })
        .catch((e) => alive && setError(e.message));
    request("/api/settings")
      .then((d) => alive && setProviders(d.providers))
      .catch(() => {});
    request("/api/projects").then((d) => alive && setProjects(d.projects)).catch(() => {});
    if (task) request("/api/tasks/" + task.slug).then((d) => alive && setAttachments(d.attachments || [])).catch(() => {});
    return () => {
      alive = false;
    };
  }, [task?.slug]);
  useEffect(() => {
    let alive = true;
    const timer = setTimeout(
      () =>
        request("/api/preview", "POST", values)
          .then(
            (d) =>
              alive &&
              setNext(
                d.next_run
                  ? `Next run ${formatDate(d.next_run)}`
                  : "No upcoming occurrence",
              ),
          )
          .catch((e) => alive && setNext(e.message)),
      200,
    );
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [
    values.frequency,
    values.time,
    values.date,
    values.weekday,
    values.cron,
    values.timezone,
  ]);
  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const data = { ...values };
      if (data.runner === "command") {
        data.model = null;
        data.sandbox = "read-only";
        data.auto_approve = false;
      }
      const result = await request(
        task ? "/api/tasks/" + task.slug : "/api/tasks",
        task ? "PATCH" : "POST",
        data,
      );
      onSaved(result.slug);
      onClose();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  async function addFile(file) {
    if (!file) return;
    const bytes = new Uint8Array(await file.arrayBuffer());
    let binary = ""; bytes.forEach((b) => binary += String.fromCharCode(b));
    const result = await request("/api/attachments", "POST", {owner_type:"task",owner:task.slug,name:file.name,content:btoa(binary)});
    setAttachments((items) => [...items, {id:result.id,name:file.name,size:file.size}]);
  }
  return (
    <Modal title={task ? "Task details" : "Schedule a task"} onClose={onClose}>
      <form onSubmit={submit} noValidate>
        <div className="settings-body">
          <Field label="What should happen?">
            <textarea
              rows="4"
              required
              value={values.instructions}
              onChange={(e) => set("instructions", e.target.value)}
              disabled={loading}
            />
          </Field>
          <Field
            label="Name"
            hint="Optional. A name is generated if you leave this blank."
          >
            <input
              value={values.title}
              maxLength="160"
              onChange={(e) => set("title", e.target.value)}
            />
          </Field>
          <Field label="Project">
            <select value={values.task_project_id || ""} onChange={(e) => set("task_project_id", e.target.value ? Number(e.target.value) : null)}>
              <option value="">Unassigned</option>
              {projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}
            </select>
          </Field>
          {task && <Field label="Reference files" hint="UTF-8 .txt or .md, up to 64 KiB each.">
            <input type="file" accept=".txt,.md,text/plain,text/markdown" onChange={(e) => addFile(e.target.files[0]).catch((error) => setError(error.message))} />
            {attachments.map((file) => <small key={file.id}>{file.name} </small>)}
          </Field>}
          <div className="field-grid">
            <Field label="Repeat">
              <select
                value={values.frequency}
                onChange={(e) => set("frequency", e.target.value)}
              >
                {[
                  ["once", "Just once"],
                  ["daily", "Every day"],
                  ["weekdays", "Weekdays"],
                  ["weekly", "Every week"],
                  ["custom", "Custom schedule"],
                ].map(([v, label]) => (
                  <option value={v} key={v}>
                    {label}
                  </option>
                ))}
              </select>
            </Field>
            {values.frequency !== "custom" && (
              <Field label="At">
                <input
                  type="time"
                  required
                  value={values.time}
                  onChange={(e) => set("time", e.target.value)}
                />
              </Field>
            )}
            {values.frequency === "once" && (
              <Field label="Date">
                <input
                  type="date"
                  required
                  value={values.date}
                  onChange={(e) => set("date", e.target.value)}
                />
              </Field>
            )}
            {values.frequency === "weekly" && (
              <Field label="Day">
                <select
                  value={values.weekday}
                  onChange={(e) => set("weekday", Number(e.target.value))}
                >
                  {[
                    "Sunday",
                    "Monday",
                    "Tuesday",
                    "Wednesday",
                    "Thursday",
                    "Friday",
                    "Saturday",
                  ].map((label, i) => (
                    <option key={label} value={i}>
                      {label}
                    </option>
                  ))}
                </select>
              </Field>
            )}
          </div>
          {values.frequency === "custom" && (
            <Field label="Five-field cron">
              <input
                required
                value={values.cron}
                placeholder="0 9 * * 1-5"
                onChange={(e) => set("cron", e.target.value)}
              />
            </Field>
          )}
          <div className="schedule-preview">
            <CalendarDays size={15} />
            <span>
              {next || "Checking schedule…"} · {values.timezone}
            </span>
          </div>
          <Toggle
            label="Monitor until a condition is met"
            checked={values.mode === "monitor"}
            onChange={(v) => set("mode", v ? "monitor" : "task")}
          />
          {values.mode === "monitor" && (
            <>
              <Field label="Stop when…">
                <input
                  required
                  placeholder="The official event date is announced"
                  value={values.condition}
                  onChange={(e) => set("condition", e.target.value)}
                />
              </Field>
              <Field label="Maximum checks">
                <input
                  type="number"
                  min="1"
                  max="10000"
                  value={values.max_checks}
                  onChange={(e) => set("max_checks", Number(e.target.value))}
                />
              </Field>
            </>
          )}
          <details className="advanced-fields">
            <summary>
              <SlidersHorizontal size={14} />
              Advanced settings
              <ChevronDown size={14} />
            </summary>
            <div className="field-grid">
              <Field label="Provider">
                <select
                  value={values.provider}
                  onChange={(e) => {
                    set("provider", e.target.value);
                    set("model", "");
                    set("sandbox", "read-only");
                    set("auto_approve", false);
                  }}
                >
                  <option value="codex">Codex</option>
                  <option value="opencode">OpenCode</option>
                </select>
              </Field>
              <Field label="Model">
                <ModelSelect
                  key={values.provider}
                  label="Model"
                  provider={providers.find((p) => p.id === values.provider)}
                  value={values.model}
                  onChange={(v) => set("model", v)}
                />
              </Field>
            </div>
            <Field label="Timezone">
              <input
                value={values.timezone}
                required
                onChange={(e) => set("timezone", e.target.value)}
              />
            </Field>
            <Toggle
              label="Remember recent conversations"
              checked={values.remember}
              onChange={(v) => set("remember", v)}
            />
            <Toggle
              label="Safe to retry automatically"
              hint="Only enable when repeating this task won't duplicate external actions."
              checked={values.retry_safe}
              onChange={(v) => set("retry_safe", v)}
            />
            <div className="field-grid">
              <Field label="Task type">
                <select
                  value={values.runner}
                  onChange={(e) => set("runner", e.target.value)}
                >
                  <option value="codex">AI task</option>
                  <option value="command">Shell command</option>
                </select>
              </Field>
              <Field label="Timeout (seconds)">
                <input
                  type="number"
                  min="1"
                  max="86400"
                  value={values.timeout}
                  onChange={(e) => set("timeout", Number(e.target.value))}
                />
              </Field>
            </div>
            {values.provider === "codex" && values.runner === "codex" && (
              <div className="field-grid">
                <Field label="Reasoning effort">
                  <select
                    value={values.effort}
                    onChange={(e) => set("effort", e.target.value)}
                  >
                    <option value="">Model default</option>
                    {[
                      "minimal",
                      "low",
                      "medium",
                      "high",
                      "xhigh",
                      "max",
                      "ultra",
                    ].map((v) => (
                      <option key={v}>{v}</option>
                    ))}
                  </select>
                </Field>
                <Field label="File access">
                  <select
                    value={values.sandbox}
                    onChange={(e) => {
                      set("sandbox", e.target.value);
                      if (e.target.value === "read-only")
                        set("auto_approve", false);
                    }}
                  >
                    <option value="read-only">Read only</option>
                    <option value="workspace-write">
                      Allow task folder edits
                    </option>
                  </select>
                </Field>
                {values.sandbox === "workspace-write" && (
                  <Toggle
                    label="Automatic action review"
                    checked={values.auto_approve}
                    onChange={(v) => set("auto_approve", v)}
                  />
                )}
              </div>
            )}
            <Toggle
              label="Enable task"
              checked={values.enabled}
              onChange={(v) => set("enabled", v)}
            />
            <p className="hint">
              Each task gets a private working folder automatically.
            </p>
          </details>
          <ErrorNotice>{error}</ErrorNotice>
        </div>
        <div className="modal-footer">
          <button type="button" className="quiet" onClick={onClose}>
            Cancel
          </button>
          <button className="primary" disabled={busy || loading}>
            {busy ? (
              <LoaderCircle className="spin" size={15} />
            ) : (
              <CalendarDays size={15} />
            )}{" "}
            {task ? "Save changes" : "Schedule task"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
