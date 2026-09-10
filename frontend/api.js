const token = document.querySelector('meta[name="csrf-token"]').content;
let accessToken = async () => null;
export function setAccessTokenProvider(provider) {
  accessToken = provider || (async () => null);
}
export async function request(path, method = "GET", body, signal) {
  const bearer = await accessToken();
  const response = await fetch(path, {
    method,
    signal,
    cache: "no-store",
    headers: {
      "X-CSRF-Token": token,
      ...(bearer ? { Authorization: `Bearer ${bearer}` } : {}),
      ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
    },
    ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
  });
  const data = await response.json();
  if (!response.ok)
    throw new Error(data.error || "Something went wrong. Please try again.");
  return data;
}
export async function exportHistory(slug) {
  const bearer = await accessToken();
  const response = await fetch("/api/export/" + slug, {
    headers: { "X-CSRF-Token": token, ...(bearer ? { Authorization: `Bearer ${bearer}` } : {}) },
  });
  if (!response.ok)
    throw new Error("Could not export history. Please try again.");
  const url = URL.createObjectURL(await response.blob()),
    link = document.createElement("a");
  link.href = url;
  link.download = slug + ".zip";
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export function formatDate(value) {
  if (!value) return "";
  // SQLite timestamps are UTC even when the stored string has no explicit suffix.
  const raw = /^\d{4}-\d\d-\d\d \d\d:/.test(value)
    ? value.replace(" ", "T") + "Z"
    : value;
  return new Date(raw).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}
export function scheduleLabel(task) {
  const t = task?.timing;
  if (!t) return task?.schedule || "";
  const at = t.time
    ? new Date("2000-01-01T" + t.time).toLocaleTimeString(undefined, {
        hour: "numeric",
        minute: "2-digit",
      })
    : "";
  if (t.frequency === "once") return `${t.date} at ${at}`;
  if (t.frequency === "daily") return `Every day at ${at}`;
  if (t.frequency === "weekdays") return `Weekdays at ${at}`;
  if (t.frequency === "weekly")
    return `Every ${["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"][t.weekday]} at ${at}`;
  return t.cron;
}
