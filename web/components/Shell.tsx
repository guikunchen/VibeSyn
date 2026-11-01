import { useState, type ReactNode } from "react";
import { NavLink } from "react-router-dom";
import {
  Bot,
  Clock3,
  FlaskConical,
  House,
  Menu,
  MessagesSquare,
  PanelLeftClose,
  PanelLeftOpen,
  Wrench,
} from "lucide-react";

const navigation = [
  { to: "/", label: "Home", icon: House },
  { to: "/agents", label: "Agent Configuration", icon: Bot },
  { to: "/execution", label: "Agent Execution", icon: MessagesSquare },
  { to: "/history", label: "Task History", icon: Clock3 },
  { to: "/hardware", label: "Hardware Status", icon: FlaskConical },
  { to: "/tools", label: "Tool Status", icon: Wrench },
];

export default function Shell({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(false);

  return (
    <div className={`app-shell ${collapsed ? "sidebar-collapsed" : ""}`}>
      <button
        className="mobile-menu icon-button"
        aria-label="Open navigation"
        onClick={() => setOpen(true)}
      >
        <Menu size={20} />
      </button>
      {open && <button className="nav-scrim" aria-label="Close navigation" onClick={() => setOpen(false)} />}
      <aside className={`sidebar ${open ? "is-open" : ""}`}>
        <div className="brand">
          <img src="/assets/home.png" alt="ChemAgentSys" />
          <div>
            <strong>ChemAgentSys</strong>
            <span>Zhejiang University</span>
          </div>
          <button
            className="icon-button collapse-nav"
            onClick={() => setCollapsed((value) => !value)}
            aria-label={collapsed ? "Expand navigation" : "Collapse navigation"}
            aria-expanded={!collapsed}
          >
            {collapsed ? <PanelLeftOpen size={19} /> : <PanelLeftClose size={19} />}
          </button>
        </div>
        <nav>
          {navigation.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === "/"}
              onClick={() => setOpen(false)}
              className={({ isActive }) => (isActive ? "active" : "")}
            >
              <Icon size={19} />
              <span>{label}</span>
            </NavLink>
          ))}
        </nav>
      </aside>
      <main className="content">{children}</main>
    </div>
  );
}
