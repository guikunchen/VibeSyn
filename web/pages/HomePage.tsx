import { Bot, Clock3, FlaskConical, MessagesSquare, Wrench } from "lucide-react";
import { Link } from "react-router-dom";

const features = [
  {
    to: "/agents",
    title: "Agent Configuration",
    description: "Choose active agents, edit prompts and routing rules, and inspect the agent graph.",
    icon: Bot,
    color: "green",
  },
  {
    to: "/execution",
    title: "Agent Execution",
    description: "Create tasks, follow the live workflow, respond to agents, and control execution.",
    icon: MessagesSquare,
    color: "blue",
  },
  {
    to: "/history",
    title: "Task History",
    description: "Review, export, edit, roll back, or archive previous chemistry workflows.",
    icon: Clock3,
    color: "orange",
  },
  {
    to: "/hardware",
    title: "Hardware Status",
    description: "Dispatch device tasks, review results, inspect telemetry, and manage connections.",
    icon: FlaskConical,
    color: "cyan",
  },
  {
    to: "/tools",
    title: "Tool Status",
    description: "Work with analysis tools and explore interactive retrosynthesis pathways.",
    icon: Wrench,
    color: "yellow",
  },
];

export default function HomePage() {
  return (
    <div className="page home-page">
      <section className="hero">
        <div>
          <span className="eyebrow">Chemical agent workspace</span>
          <h1>Welcome to ChemAgentSys</h1>
          <p>
            Configure autonomous chemistry agents, coordinate experiments, and follow every
            tool and hardware handoff from one focused workspace.
          </p>
          <Link className="button primary" to="/execution">Open Agent Execution</Link>
        </div>
        <img src="/assets/home.png" alt="Chemistry robot" />
      </section>
      <section>
        <div className="section-heading">
          <div>
            <span className="eyebrow">Workspace</span>
            <h2>Choose what you want to explore</h2>
          </div>
        </div>
        <div className="feature-grid">
          {features.map(({ to, title, description, icon: Icon, color }) => (
            <Link key={to} to={to} className="feature-card">
              <span className={`feature-icon ${color}`}><Icon size={23} /></span>
              <div>
                <h3>{title}</h3>
                <p>{description}</p>
              </div>
              <span className="card-arrow">→</span>
            </Link>
          ))}
        </div>
      </section>
    </div>
  );
}
