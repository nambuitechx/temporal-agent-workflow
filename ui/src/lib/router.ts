import { useEffect, useState } from "react";

// Router tối giản dựa trên location.hash — POC này không đủ phức tạp để cần
// react-router (chỉ 4 screen phẳng, không nested route/loader). Format:
//   #/usecases                    -> danh sách usecase (mục 1 UI mới)
//   #/usecases/<usecaseId>        -> chi tiết usecase: version + agent gán (mục 1)
//   #/agents                      -> danh sách agentcore_agents đã deploy (mục 2)
//   #/cases/<usecaseKey>          -> màn Incident Analysis hiện tại, scope theo usecase (mục 3)

export function navigate(path: string): void {
  window.location.hash = path;
}

function currentPath(): string {
  const raw = window.location.hash.slice(1); // bỏ "#"
  return raw.startsWith("/") ? raw : "/usecases";
}

export function useRoute(): string[] {
  const [path, setPath] = useState(currentPath);

  useEffect(() => {
    const onHashChange = () => setPath(currentPath());
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  return path.split("/").filter(Boolean); // "/usecases/abc" -> ["usecases", "abc"]
}
