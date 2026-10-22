import type { ApiClient } from "../api/client";
import { ExercisePage } from "./ExercisePage";

export function StudentPage({ api, ownerId }: { api: ApiClient; ownerId: string }) {
  return <ExercisePage api={api} ownerId={ownerId} />;
}
