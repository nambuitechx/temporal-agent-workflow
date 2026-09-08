import { useRoute } from "@/lib/router";
import { UsecaseListScreen } from "@/screens/UsecaseListScreen";
import { UsecaseDetailScreen } from "@/screens/UsecaseDetailScreen";
import { AgentListScreen } from "@/screens/AgentListScreen";
import { CaseWorkspaceScreen } from "@/screens/CaseWorkspaceScreen";

export default function App() {
  const segments = useRoute();
  const [root, param] = segments;

  if (root === "agents") return <AgentListScreen />;
  if (root === "usecases" && param) return <UsecaseDetailScreen usecaseId={param} />;
  if (root === "cases" && param) return <CaseWorkspaceScreen usecaseKey={decodeURIComponent(param)} />;
  return <UsecaseListScreen />;
}
