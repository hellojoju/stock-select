import { useEffect, useState } from 'react';
import { Globe, Save, Zap } from 'lucide-react';
import Panel from '../components/Panel';
import { PageHeader } from '../components/PageHeader';
import { fetchConfig, updateModel } from '../api/client';
import type { ModelConfig } from '../api/client';

export default function SettingsPage() {
  const [config, setConfig] = useState<ModelConfig | null>(null);
  const [saving, setSaving] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    fetchConfig().then(setConfig).catch(() => {});
  }, []);

  async function handleSwitchModel(model: string) {
    setSaving(model);
    setSaved(false);
    try {
      await updateModel(model);
      setConfig((prev) => prev ? { ...prev, model } : prev);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch {
      /* ignore */
    }
    setSaving(null);
  }

  return (
    <div className="page terminal-page">
      <PageHeader
        eyebrow="SETTINGS"
        title="系统设置"
        date=""
        onDateChange={() => {}}
      />

      <div className="advanced-grid">
        <Panel title="大模型配置" icon={<Zap size={18} />}>
          {config ? (
            <div className="settings-section">
              <div className="setting-row">
                <span className="setting-label">当前提供商</span>
                <span className="setting-value">{config.provider ?? '未配置'}</span>
              </div>
              <div className="setting-row">
                <span className="setting-label">当前模型</span>
                <span className="setting-value mono">{config.model}</span>
              </div>

              {config.available_models && config.available_models.length > 0 && (
                <div className="model-select-group">
                  <span className="setting-label">切换模型</span>
                  <div className="model-options">
                    {config.available_models.map((m) => (
                      <button
                        key={m.key}
                        className={`model-option ${config.model === m.model ? 'active' : ''}`}
                        disabled={saving !== null}
                        onClick={() => handleSwitchModel(m.model)}
                      >
                        <span className="model-option-label">{m.label}</span>
                        <span className="model-option-key">{m.model}</span>
                        {saving === m.model && <span className="model-option-loading">...</span>}
                        {config.model === m.model && <span className="model-option-check">已选中</span>}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {saved && (
                <div className="save-success">
                  <Save size={14} /> 模型切换成功
                </div>
              )}
            </div>
          ) : (
            <p className="empty-state">无法加载配置，请检查后端服务。</p>
          )}
        </Panel>

        <Panel title="关于" icon={<Globe size={18} />}>
          <div className="settings-section">
            <div className="setting-row">
              <span className="setting-label">系统版本</span>
              <span className="setting-value">v0.2</span>
            </div>
            <div className="setting-row">
              <span className="setting-label">系统名称</span>
              <span className="setting-value">Stock Select · 自我进化选股系统</span>
            </div>
          </div>
        </Panel>
      </div>
    </div>
  );
}
