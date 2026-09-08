interface Props {
  active: "usecases" | "agents" | "cases";
}

export function NavBar({ active }: Props) {
  return (
    <nav className="navbar">
      <a href="#/usecases" className={active === "usecases" || active === "cases" ? "active" : ""}>
        Usecases
      </a>
      <a href="#/agents" className={active === "agents" ? "active" : ""}>
        Deployed Agents
      </a>
    </nav>
  );
}
