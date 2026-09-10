import React, { useState } from "react";

export default function ModelSelect({
  provider,
  value,
  onChange,
  label = "Model",
}) {
  const [custom, setCustom] = useState(false);
  const details = provider?.model_details || [];
  const models = (provider?.models || []).map(
    (id) => details.find((m) => m.id === id) || { id, name: id, free: false },
  );
  const free = models.filter((m) => m.free),
    other = models.filter((m) => !m.free);
  const known = models.some((m) => m.id === value);
  return (
    <>
      <select
        aria-label={label}
        value={custom ? "__custom" : value || ""}
        onChange={(e) => {
          if (e.target.value === "__custom") {
            setCustom(true);
            onChange("");
          } else {
            setCustom(false);
            onChange(e.target.value);
          }
        }}
      >
        <option value="">
          {provider ? "Choose a model" : "Loading models…"}
        </option>
        {free.length > 0 && (
          <optgroup label="Free models">
            {free.map((m) => (
              <option key={m.id} value={m.id}>
                {m.name} · Free
              </option>
            ))}
          </optgroup>
        )}
        {other.length > 0 && (
          <optgroup label="Available models">
            {other.map((m) => (
              <option key={m.id} value={m.id}>
                {m.name}
              </option>
            ))}
          </optgroup>
        )}
        {!custom && value && !known && (
          <option value={value}>{value} (saved)</option>
        )}
        <option value="__custom">Enter a model ID…</option>
      </select>
      {custom && (
        <input
          aria-label="Custom model ID"
          placeholder="provider/model or model ID"
          value={value || ""}
          onChange={(e) => onChange(e.target.value)}
        />
      )}
      {provider && models.length === 0 && (
        <small>No models returned. Refresh the provider or enter an ID.</small>
      )}
    </>
  );
}
