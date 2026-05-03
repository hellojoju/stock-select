import { AlertTriangle } from 'lucide-react';

interface ConfirmActionDialogProps {
  title: string;
  description: string;
  impacts?: string[];
  confirmText?: string;
  danger?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export default function ConfirmActionDialog({
  title,
  description,
  impacts = [],
  confirmText = '确认执行',
  danger = false,
  onConfirm,
  onCancel,
}: ConfirmActionDialogProps) {
  return (
    <div className="dialog-overlay" onClick={onCancel}>
      <div className={`dialog-box ${danger ? 'dialog-danger' : ''}`} onClick={(e) => e.stopPropagation()}>
        <div className="dialog-header">
          <AlertTriangle size={20} className="dialog-icon" />
          <h3>{title}</h3>
        </div>
        <p className="dialog-description">{description}</p>
        {impacts.length > 0 && (
          <div className="dialog-impacts">
            <h4>影响范围：</h4>
            <ul>
              {impacts.map((text, i) => (
                <li key={i}>{text}</li>
              ))}
            </ul>
          </div>
        )}
        <div className="dialog-actions">
          <button className="btn-cancel" onClick={onCancel}>取消</button>
          <button className={`btn-confirm ${danger ? 'btn-danger' : ''}`} onClick={onConfirm}>
            {confirmText}
          </button>
        </div>
      </div>
    </div>
  );
}
