import ModelSelect from "./ModelSelect";
import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  Play,
  Download,
  Check,
  RotateCcw,
  LoaderCircle,
  Sun,
  Moon,
  Monitor,
  ExternalLink,
} from "lucide-react";
import { request } from "./api";
import { ErrorNotice, Modal, Field, Toggle } from "./components";
export default function SettingsPanel({ onClose, onSaved, initial }) {
  const [tab, setTab] = useState("general"),
    [values, setValues] = useState(initial),
    [providers, setProviders] = useState([]),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [status, setStatus] = useState(""),
    [login, setLogin] = useState(null),
    [installing, setInstalling] = useState(false);
  const set = (key, value) => setValues((v) => ({ ...v, [key]: value }));
  useEffect(() => {
    let alive = true;
    request("/api/settings")
      .then((d) => {
        if (alive) {
          // Provider discovery may finish after the user starts editing.
          setValues((current) => ({ ...d.settings, ...current }));
          setProviders(d.providers);
          setLogin(d.login);
        }
      })
      .catch((e) => alive && setError(e.message));
    return () => {
      alive = false;
    };
  }, []);
  useEffect(() => {
    if (!installing && login?.status !== "waiting") return;
    let alive = true;
    const timer = setInterval(
      () =>
        request("/api/settings")
          .then((d) => {
            if (!alive) return;
            setLogin(d.login);
            setProviders(d.providers);
            const pending = Object.entries(d.runtimes);
            setStatus(
              pending.map(([name, s]) => `${name}: ${s.status}`).join(" · "),
            );
            setInstalling(pending.some(([, s]) => s.status === "installing"));
          })
          .catch((e) => alive && setError(e.message)),
      2500,
    );
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [installing, login?.status]);
  async function action(fn) {
    setError("");
    setBusy(true);
    try {
      await fn();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  async function save(e) {
    e.preventDefault();
    await action(async () => {
      await request("/api/settings", "PATCH", values);
      onSaved();
      onClose();
    });
  }
  const provider = providers.find((p) => p.id === values.provider);
  return (
    <Modal title="Settings" onClose={onClose}>
      <div className="settings-tabs" role="tablist">
        {[
          ["general", "General"],
          ["models", "Models"],
          ["automation", "Automation"],
        ].map(([id, label]) => (
          <button
            key={id}
            role="tab"
            aria-selected={tab === id}
            className={tab === id ? "selected" : ""}
            onClick={() => {
              setTab(id);
              setError("");
            }}
          >
            {label}
          </button>
        ))}
      </div>
      <form onSubmit={save}>
        <div className="settings-body">
          {tab === "general" && (
            <>
              <h3 className="section-label">Make yourself at home</h3>
              <Field label="Appearance">
                <div className="appearance-options">
                  {[
                    [Sun, "light", "Light"],
                    [Moon, "dark", "Dark"],
                    [Monitor, "system", "System"],
                  ].map(([Icon, key, label]) => (
                    <button
                      type="button"
                      key={key}
                      aria-label={label}
                      aria-pressed={values.theme === key}
                      className={values.theme === key ? "chosen" : ""}
                      onClick={() => set("theme", key)}
                    >
                      <Icon size={20} />
                      {label}
                      {values.theme === key && <Check size={13} />}
                    </button>
                  ))}
                </div>
              </Field>
              <Field
                label="Your timezone"
                hint="Used for new tasks. Each task can have its own timezone."
              >
                <input
                  required
                  value={values.timezone || ""}
                  onChange={(e) => set("timezone", e.target.value)}
                />
              </Field>
              <div className="setting-divider" />
              <Toggle
                label="Keep this computer awake"
                hint="Requests a sleep inhibitor while OnCue is running. Does not power on the computer."
                checked={values.keep_awake}
                onChange={(v) => set("keep_awake", v)}
              />
              <button
                type="button"
                className="text-action"
                disabled={busy}
                onClick={() =>
                  action(async () => {
                    await request("/api/startup", "POST", {});
                    setStatus("OnCue will start at your next Linux sign-in.");
                  })
                }
              >
                <Play size={14} />
                Start automatically at Linux sign-in
              </button>
              <Toggle
                label="Result notifications"
                hint="Only changes and completion for monitors. Requires this tab to stay open."
                checked={values.notifications}
                onChange={(v) => set("notifications", v)}
              />
              <Toggle
                label="Native desktop notifications"
                hint="Delivered by Linux even when this browser tab is closed."
                checked={values.desktop_notifications || false}
                onChange={(v) => set("desktop_notifications", v)}
              />
              <Field label="Outgoing webhooks" hint="One JSON destination per line: {&quot;name&quot;:&quot;My endpoint&quot;,&quot;url&quot;:&quot;https://…&quot;}. Complete results are sent.">
                <textarea rows="3" value={(values.webhooks || []).map((item) => JSON.stringify(item)).join("\n")} onChange={(e) => {
                  try { set("webhooks", e.target.value.trim() ? e.target.value.split("\n").map(JSON.parse) : []); } catch (_) { set("webhooks", []); }
                }} />
              </Field>
              <button
                className="text-action"
                type="button"
                onClick={() =>
                  action(async () => {
                    if (!("Notification" in window))
                      throw new Error(
                        "Notifications are not available in this browser.",
                      );
                    const result = await Notification.requestPermission();
                    setStatus(
                      result === "granted"
                        ? "Browser notifications enabled."
                        : "Notifications were not enabled in this browser.",
                    );
                  })
                }
              >
                Enable browser notifications <ExternalLink size={13} />
              </button>
            </>
          )}
          {tab === "models" && (
            <>
              <h3 className="section-label">Choose who does the work</h3>
              <div className="field-grid">
                <Field label="Default provider">
                  <select
                    value={values.provider}
                    onChange={(e) => {
                      set("provider", e.target.value);
                      set("model", "");
                    }}
                  >
                    <option value="codex">Codex / ChatGPT</option>
                    <option value="opencode">OpenCode</option>
                  </select>
                </Field>
                <Field label="Default model">
                  <ModelSelect
                    key={values.provider}
                    label="Default model"
                    provider={provider}
                    value={values.model}
                    onChange={(v) => set("model", v)}
                  />
                </Field>
              </div>
              <div className="connection-state">
                <span
                  className={`status-dot ${provider?.installed ? "ready" : ""}`}
                />
                {provider?.status || "Checking provider…"}
              </div>
              <div className="row-actions">
                <button
                  type="button"
                  disabled={busy}
                  onClick={() =>
                    action(async () =>
                      setProviders(
                        await request("/api/providers/refresh", "POST", {}),
                      ),
                    )
                  }
                >
                  <RotateCcw size={14} />
                  Refresh
                </button>
                {provider && !provider.installed && (
                  <button
                    type="button"
                    disabled={busy || installing}
                    onClick={() =>
                      action(async () => {
                        await request("/api/providers/install", "POST", {
                          provider: values.provider,
                        });
                        setInstalling(true);
                        setStatus("Installing runtime…");
                      })
                    }
                  >
                    {installing ? (
                      <LoaderCircle className="spin" size={14} />
                    ) : (
                      <Download size={14} />
                    )}
                    Install runtime
                  </button>
                )}
              </div>
              {values.provider === "codex" ? (
                <>
                  <Field label="Codex sign-in">
                    <select
                      value={values.codex_login}
                      onChange={(e) => set("codex_login", e.target.value)}
                    >
                      <option value="existing">Use my local Codex login</option>
                      <option value="managed">
                        Use a separate OnCue login
                      </option>
                    </select>
                  </Field>
                  <p className="hint">
                    A ChatGPT website login alone isn’t enough. Existing mode
                    uses your local Codex account. A separate login is stored by
                    Codex for OnCue.
                  </p>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() =>
                      action(async () => {
                        setLogin(
                          await request("/api/providers/login", "POST", {}),
                        );
                        set("codex_login", "managed");
                      })
                    }
                  >
                    Connect ChatGPT <ExternalLink size={14} />
                  </button>
                  {login?.url && login.status === "waiting" && (
                    <a
                      className="auth-link"
                      href={login.url}
                      target="_blank"
                      rel="noreferrer"
                    >
                      Continue sign-in with ChatGPT <ExternalLink size={14} />
                    </a>
                  )}
                  {login?.status === "connected" && (
                    <p className="success-text">
                      Connected. Save settings to use this login.
                    </p>
                  )}
                  {login?.status === "failed" && (
                    <p className="error-text">
                      Sign-in did not finish. Please try again.
                    </p>
                  )}
                </>
              ) : (
                <p className="hint">
                  OpenCode’s free models are listed when available. Other models
                  may need an OpenCode login. Access and availability depend on
                  the provider.
                </p>
              )}
              <div className="setting-divider" />
              <Toggle
                label="Use a fallback model"
                hint="Allows the task and recent conversation to be sent to the fallback provider on eligible retries."
                checked={values.allow_fallback}
                onChange={(v) => set("allow_fallback", v)}
              />
              {values.allow_fallback && (
                <div className="field-grid">
                  <Field label="Fallback provider">
                    <select
                      value={values.fallback_provider}
                      onChange={(e) => {
                        set("fallback_provider", e.target.value);
                        set("fallback_model", "");
                      }}
                    >
                      <option value="">Choose provider</option>
                      <option value="codex">Codex</option>
                      <option value="opencode">OpenCode</option>
                    </select>
                  </Field>
                  <Field label="Fallback model">
                    {values.fallback_provider ? (
                      <ModelSelect
                        key={values.fallback_provider}
                        label="Fallback model"
                        provider={providers.find(
                          (p) => p.id === values.fallback_provider,
                        )}
                        value={values.fallback_model}
                        onChange={(v) => set("fallback_model", v)}
                      />
                    ) : (
                      <select aria-label="Fallback model" disabled>
                        <option>Choose a provider first</option>
                      </select>
                    )}
                  </Field>
                </div>
              )}
              <p className="hint">
                Defaults apply to new tasks. Existing tasks keep their model.
              </p>
            </>
          )}
          {tab === "automation" && (
            <>
              <h3 className="section-label">When a run needs another try</h3>
              <Toggle
                label="Retry temporary errors"
                hint="For planning, monitoring, and tasks marked safe to repeat. Sign-in and permission errors need your attention."
                checked={values.retry_enabled}
                onChange={(v) => set("retry_enabled", v)}
              />
              <div className="field-grid">
                <Field label="Retry after (minutes)">
                  <input
                    type="number"
                    min="1"
                    max="1440"
                    value={values.retry_minutes}
                    onChange={(e) =>
                      set("retry_minutes", Number(e.target.value))
                    }
                  />
                </Field>
                <Field label="Maximum retries">
                  <input
                    type="number"
                    min="0"
                    max="10"
                    value={values.max_retries}
                    onChange={(e) => set("max_retries", Number(e.target.value))}
                  />
                </Field>
              </div>
              <Field
                label="Concurrent tasks"
                hint="Tasks sharing a folder always run one at a time."
              >
                <input
                  type="number"
                  min="1"
                  max="8"
                  value={values.max_workers}
                  onChange={(e) => set("max_workers", Number(e.target.value))}
                />
              </Field>
              <p className="hint">
                Changing models may not bypass an account-wide usage limit.
                Missed recurring runs are skipped while this computer is off;
                one-time tasks and queued retries can run after restart.
              </p>
            </>
          )}
          {status && (
            <p className="inline-status" role="status">
              {status}
            </p>
          )}
          <ErrorNotice>{error}</ErrorNotice>
        </div>
        <div className="modal-footer">
          <button type="button" className="quiet" onClick={onClose}>
            Cancel
          </button>
          <button className="primary" disabled={busy}>
            {busy ? (
              <LoaderCircle className="spin" size={15} />
            ) : (
              <Check size={15} />
            )}
            Save changes
          </button>
        </div>
      </form>
    </Modal>
  );
}
