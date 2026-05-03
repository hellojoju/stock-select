import { useEffect, useRef, useState } from 'react';
import { ChevronDown, ChevronRight, Loader2, Terminal } from 'lucide-react';
import { fetchReviewSteps } from '../api/client';

export default function ExecutionStepsPanel({
  sessionId,
  loading,
}: {
  sessionId: string | null;
  loading: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [steps, setSteps] = useState<Array<{
    message: string;
    detail: string;
    completed: boolean;
    timestamp: number;
    time_display: string;
    request?: Record<string, unknown>;
    response?: Record<string, unknown>;
  }>>([]);
  const [expandedStep, setExpandedStep] = useState<number | null>(null);
  const [expandedSection, setExpandedSection] = useState<'request' | 'response' | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const activeSession = useRef<string | null>(null);

  useEffect(() => {
    if (loading) {
      setOpen(true);
      setSteps([]);
    }
  }, [loading]);

  useEffect(() => {
    if (!sessionId) return;
    activeSession.current = sessionId;

    const poll = () => {
      fetchReviewSteps(sessionId)
        .then((d: unknown) => {
          const data = d as { steps?: Array<typeof steps[number]> };
          if (activeSession.current === sessionId) {
            setSteps(data.steps ?? []);
          }
        })
        .catch(() => {});
    };

    poll();
    pollRef.current = setInterval(poll, 300);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [sessionId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [steps.length]);

  if (!sessionId && !loading) return null;

  return (
    <>
      <button className="exec-fab" onClick={() => setOpen(!open)} title="执行过程">
        {loading ? <Loader2 size={18} className="spin" /> : <Terminal size={18} />}
      </button>

      {open && (
        <div className="exec-panel">
          <div className="exec-panel-header">
            <span className="exec-panel-title">
              <Terminal size={14} /> 执行过程
            </span>
            <button className="exec-panel-close" onClick={() => setOpen(false)}>×</button>
          </div>
          <div className="exec-panel-body">
            {steps.length === 0 && loading && (
              <div className="exec-panel-loading">
                <Loader2 size={16} className="spin" /> 等待后端响应...
              </div>
            )}
            {steps.length === 0 && !loading && sessionId && (
              <div className="exec-panel-loading">暂无步骤记录</div>
            )}
            {steps.map((step, i) => (
              <div key={i} className={`exec-step ${step.completed && i === steps.length - 1 ? 'done' : ''}`}>
                <button className="exec-step-message" onClick={() => setExpandedStep(expandedStep === i ? null : i)}>
                  {step.detail || step.response ? (
                    expandedStep === i ? <ChevronDown size={12} /> : <ChevronRight size={12} />
                  ) : <span style={{ width: 12 }} />}
                  <span className="exec-step-text">
                    {loading && !step.completed && i === steps.length - 1 ? (
                      <Loader2 size={12} className="spin" />
                    ) : step.completed && i === steps.length - 1 ? (
                      <span className="exec-step-check" />
                    ) : null}
                    {step.message}
                    {step.response && Object.keys(step.response).length > 0 && !step.detail && (
                      <span className="exec-step-response-preview">{formatResponsePreview(step.response)}</span>
                    )}
                  </span>
                  <span className="exec-step-time">{step.time_display}</span>
                </button>
                {expandedStep === i && (step.detail || step.request || step.response) && (
                  <div className="exec-step-detail">
                    {step.detail && (
                      <div className="exec-step-detail-text">{step.detail}</div>
                    )}
                    {step.request && (
                      <div className="exec-step-json-block">
                        <button
                          className="exec-step-json-toggle"
                          onClick={() => setExpandedSection(expandedSection === 'request' ? null : 'request')}
                        >
                          {expandedSection === 'request' ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
                          请求参数
                        </button>
                        {expandedSection === 'request' && (
                          <pre className="exec-step-pre">{formatJson(step.request)}</pre>
                        )}
                      </div>
                    )}
                    {step.response && (
                      <div className="exec-step-json-block">
                        <button
                          className="exec-step-json-toggle"
                          onClick={() => setExpandedSection(expandedSection === 'response' ? null : 'response')}
                        >
                          {expandedSection === 'response' ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
                          返回数据
                        </button>
                        {expandedSection === 'response' && (
                          <pre className="exec-step-pre">{formatJson(step.response)}</pre>
                        )}
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))}
            <div ref={bottomRef} />
          </div>
        </div>
      )}
    </>
  );
}

function formatJson(obj: Record<string, unknown>): string {
  try {
    return JSON.stringify(obj, null, 2);
  } catch {
    return String(obj);
  }
}

/** 从 response_data 中提取关键信息作为行内预览 */
function formatResponsePreview(obj: Record<string, unknown>): string {
  const parts: string[] = [];
  for (const [key, value] of Object.entries(obj)) {
    if (value === true) parts.push(key);
    else if (value === false) continue;
    else if (typeof value === 'string') parts.push(value.slice(0, 60));
    else if (typeof value === 'number') parts.push(`${key}: ${value}`);
    else if (Array.isArray(value)) parts.push(`${key}: ${value.length}项`);
    else if (value && typeof value === 'object') {
      const nested = Object.entries(value as Record<string, unknown>)
        .filter(([, v]) => v !== undefined && v !== null)
        .slice(0, 3)
        .map(([k, v]) => `${k}: ${typeof v === 'object' ? JSON.stringify(v).slice(0, 40) : String(v).slice(0, 40)}`)
        .join(', ');
      if (nested) parts.push(nested);
    }
  }
  return parts.length > 0 ? ` — ${parts.join(' | ')}` : '';
}
