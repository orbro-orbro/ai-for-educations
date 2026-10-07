import type { ApiClient } from "../api/client";
import { ExercisePage } from "./ExercisePage";

export function StudentPage({ api }: { api: ApiClient }) {
  return <ExercisePage api={api} />;
}
