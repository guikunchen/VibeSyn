import { CircleAlert, CircleCheck, Info, X } from "lucide-react";

export function Notice({
  tone = "info",
  children,
  onClose,
}: {
  tone?: "info" | "success" | "error";
  children: React.ReactNode;
  onClose?: () => void;
}) {
  const Icon = tone === "success" ? CircleCheck : tone === "error" ? CircleAlert : Info;
  return (
    <div className={`notice ${tone}`}>
      <Icon size={18} />
      <div>{children}</div>
      {onClose && (
        <button type="button" className="icon-button" onClick={onClose} aria-label="Dismiss">
          <X size={16} />
        </button>
      )}
    </div>
  );
}
