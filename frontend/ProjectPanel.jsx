import React, { useEffect, useState } from "react";
import { Folder } from "lucide-react";
import { request } from "./api";
import { ErrorNotice, Field, Modal } from "./components";

const ICONS = ["📁", "💼", "🚀", "💡", "🎯", "📚", "🧪", "🧠", "💻", "🎨", "✈️", "🌎", "❤️", "🌱", "🏠", "⚙️"];
const COLORS = ["#ef5350", "#ff8a50", "#f4c84d", "#58bf78", "#4f94ed", "#9b71e8", "#e56da0", "#8a929d"];

export default function ProjectPanel({ project, onClose, onSaved }) {
  const [value, setValue] = useState({ name: "", instructions: "", icon: "", color: "" });
  const [files, setFiles] = useState([]), [tasks, setTasks] = useState([]), [error, setError] = useState("");
  useEffect(() => {
    request("/api/projects/" + project.id).then((data) => {
      setValue(data.project); setFiles(data.attachments); setTasks(data.tasks);
    }).catch((e) => setError(e.message));
  }, [project.id]);
  async function save(e) {
    e.preventDefault();
    try { await request("/api/projects/" + project.id, "PATCH", value); onSaved(); onClose(); }
    catch (e) { setError(e.message); }
  }
  async function addFile(file) {
    if (!file) return;
    const bytes = new Uint8Array(await file.arrayBuffer()); let content = "";
    bytes.forEach((byte) => content += String.fromCharCode(byte));
    try {
      await request("/api/attachments", "POST", { owner_type: "project", owner: project.id, name: file.name, content: btoa(content) });
      const data = await request("/api/projects/" + project.id); setFiles(data.attachments);
    } catch (e) { setError(e.message); }
  }
  async function remove(id) {
    try { await request("/api/attachments/" + id, "DELETE"); setFiles(files.filter((file) => file.id !== id)); }
    catch (e) { setError(e.message); }
  }
  async function destroy() {
    if (!window.confirm("Delete this project? Its tasks will become Unassigned.")) return;
    try { await request("/api/projects/" + project.id, "DELETE"); onSaved(); onClose(); }
    catch (e) { setError(e.message); }
  }
  const set = (key, next) => setValue((current) => ({ ...current, [key]: next }));
  return <Modal title="Project settings" onClose={onClose}>
    <form onSubmit={save} className="settings-body">
      <ErrorNotice onClose={() => setError("")}>{error}</ErrorNotice>
      <Field label="Name"><div className="project-name-field"><span className="project-identity-preview" style={{ color: value.color || undefined }}>{value.icon || <Folder size={17} />}</span><input value={value.name || ""} onChange={(e) => set("name", e.target.value)} /></div></Field>
      <div className="project-identity-picker">
        <span className="picker-label">Color</span>
        <div className="color-options">
          {COLORS.map((color) => <button type="button" key={color} aria-label={`Use ${color}`} aria-pressed={value.color === color} className={value.color === color ? "chosen" : ""} style={{ backgroundColor: color }} onClick={() => set("color", color)} />)}
          <label className="custom-color" title="Custom color"><input type="color" value={value.color || "#4f94ed"} onChange={(e) => set("color", e.target.value)} /><span>+</span></label>
        </div>
        <span className="picker-label">Icon</span>
        <div className="emoji-options">{ICONS.map((icon) => <button type="button" key={icon} aria-label={`Use ${icon}`} aria-pressed={value.icon === icon} className={value.icon === icon ? "chosen" : ""} onClick={() => set("icon", icon)}>{icon}</button>)}</div>
      </div>
      <Field label="Shared instructions"><textarea rows="5" value={value.instructions || ""} onChange={(e) => set("instructions", e.target.value)} /></Field>
      <Field label="Project reference files"><input type="file" accept=".txt,.md" onChange={(e) => addFile(e.target.files[0])} />{files.map((file) => <small key={file.id}>{file.name} <button type="button" onClick={() => remove(file.id)}>Remove</button></small>)}</Field>
      <p className="hint">{tasks.length ? "Tasks: " + tasks.map((task) => task.title).join(", ") : "No tasks yet."}</p>
      <div className="modal-footer"><button type="button" className="quiet" onClick={destroy}>Delete project</button><button className="primary-button" type="submit">Save project</button></div>
    </form>
  </Modal>;
}
