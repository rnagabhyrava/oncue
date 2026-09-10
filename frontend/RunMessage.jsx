import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  Clock3,
  CheckCheck,
  AlertCircle,
  RotateCcw,
  Terminal,
} from "lucide-react";
import { formatDate } from "./api";

import Markdown from "react-markdown";
const errorStates = ["failed", "timed_out"];
export default function RunMessage({ message, onRetry, onLog, retryMinutes }) {
  const run = message.run,
    failed = errorStates.includes(run?.status);
  return (
    <article className={`message ${message.role}`}>
      <div className="message-label">
        {message.role === "user" ? (
          <span>You</span>
        ) : (
          <>
            <span className="message-avatar">
              <Clock3 size={15} />
            </span>
            <strong>OnCue</strong>
          </>
        )}
        <time>{formatDate(message.created_at)}</time>
        {run && (
          <span className={`run-badge ${failed ? "failed" : ""}`}>
            {failed ? <AlertCircle size={11} /> : <CheckCheck size={12} />}{" "}
            {failed
              ? "Failed"
              : run.kind === "plan"
                ? "Reply"
                : run.status === "succeeded"
                  ? "Completed"
                  : run.status.replace("_", " ")}
          </span>
        )}
      </div>
      {!(failed && message.content === run.error) && (
        <div className="message-body">
          <Markdown
            components={{
              a: (props) => <a {...props} target="_blank" rel="noreferrer" />,
            }}
          >
            {message.content}
          </Markdown>
        </div>
      )}
      {failed && (
        <div className="run-error">
          <AlertCircle size={16} />
          <div>
            <p>{run.error || "This run could not finish."}</p>
            <div className="row-actions">
              <button onClick={() => onRetry(run.id, 0)}>
                <RotateCcw size={13} />
                Retry now
              </button>
              <button onClick={() => onRetry(run.id, retryMinutes)}>
                <Clock3 size={13} />
                In {retryMinutes} min
              </button>
            </div>
          </div>
        </div>
      )}
      {run && (
        <div className="message-footer">
          <span>
            {run.provider} · {run.model}
          </span>
          <button onClick={() => onLog(run.id)}>
            <Terminal size={12} />
            Execution log
          </button>
        </div>
      )}
    </article>
  );
}
