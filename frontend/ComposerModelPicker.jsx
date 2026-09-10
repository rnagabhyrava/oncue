import React, { useEffect, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";
import ModelSelect from "./ModelSelect";
import { ErrorNotice, Field } from "./components";
import { request } from "./api";

export default function ComposerModelPicker({
  provider,
  model,
  disabled,
  onChange,
}) {
  const [open, setOpen] = useState(false);
  const [providers, setProviders] = useState([]);
  const [choice, setChoice] = useState({ provider, model });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const root = useRef(null);
  useEffect(() => {
    if (!open) return;
    let alive = true;
    request("/api/settings")
      .then((d) => alive && setProviders(d.providers))
      .catch((e) => alive && setError(e.message));
    const dismiss = (e) => {
      if (
        e.type === "keydown"
          ? e.key === "Escape"
          : !root.current?.contains(e.target)
      )
        setOpen(false);
    };
    document.addEventListener("pointerdown", dismiss);
    document.addEventListener("keydown", dismiss);
    return () => {
      alive = false;
      document.removeEventListener("pointerdown", dismiss);
      document.removeEventListener("keydown", dismiss);
    };
  }, [open]);
  return (
    <div className="composer-model" ref={root}>
      <button
        type="button"
        className="model-picker"
        disabled={disabled}
        aria-label="Choose conversation model"
        aria-expanded={open}
        aria-haspopup="dialog"
        onClick={() => {
          setChoice({ provider, model });
          setError("");
          setOpen(!open);
        }}
      >
        {model || "Choose a model"}
        <ChevronDown size={12} />
      </button>
      {open && (
        <div
          className="composer-model-menu"
          role="dialog"
          aria-label="Conversation model"
        >
          <strong>Model for this conversation</strong>
          <Field label="Provider">
            <select
              value={choice.provider}
              disabled={busy}
              onChange={(e) =>
                setChoice({ provider: e.target.value, model: "" })
              }
            >
              <option value="codex">Codex / ChatGPT</option>
              <option value="opencode">OpenCode</option>
            </select>
          </Field>
          <Field label="Model">
            <ModelSelect
              key={choice.provider}
              label="Conversation model"
              provider={providers.find((p) => p.id === choice.provider)}
              value={choice.model}
              onChange={(model) => setChoice((c) => ({ ...c, model }))}
            />
          </Field>
          <small>
            Applies to future messages and runs. Your global default stays the
            same.
          </small>
          <ErrorNotice>{error}</ErrorNotice>
          <button
            type="button"
            disabled={busy || !choice.model}
            onClick={async () => {
              setBusy(true);
              setError("");
              try {
                await onChange(choice);
                setOpen(false);
              } catch (e) {
                setError(e.message);
              } finally {
                setBusy(false);
              }
            }}
          >
            {busy ? "Applying…" : "Use model"}
          </button>
        </div>
      )}
    </div>
  );
}
