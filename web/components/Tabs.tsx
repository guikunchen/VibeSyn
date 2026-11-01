import type { ReactNode } from "react";

export interface TabOption<T extends string> {
  id: T;
  label: string;
  icon?: ReactNode;
}

export function Tabs<T extends string>({
  options,
  value,
  onChange,
}: {
  options: Array<TabOption<T>>;
  value: T;
  onChange: (value: T) => void;
}) {
  return (
    <div className="tabs" role="tablist">
      {options.map((option) => (
        <button
          key={option.id}
          type="button"
          role="tab"
          aria-selected={value === option.id}
          className={value === option.id ? "active" : ""}
          onClick={() => onChange(option.id)}
        >
          {option.icon}
          {option.label}
        </button>
      ))}
    </div>
  );
}
