import { api } from "../api/client";
import { useAsync } from "./useAsync";

export function useHealth() {
  return useAsync(() => api.getHealth(), [], true);
}
