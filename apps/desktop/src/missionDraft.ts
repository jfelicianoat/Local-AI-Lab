import type { MissionRecord, MissionStrategy } from "./contracts";

export interface MissionFields {
  strategy: MissionStrategy; task: string; success: string; constraints: string;
  teacherSource: "broker" | "local"; teacherModel: string; studentModel: string;
}
export interface MissionDraft {
  missionId: string | null; expectedRevision: number;
  fields: MissionFields; base: MissionFields | null;
}
type DraftStorage = Pick<Storage, "getItem" | "setItem" | "removeItem">;
const prefix = "local-ai-lab.mission-recovery.v1.";
const selectedKey = "local-ai-lab.selected-mission.v1";

export function missionStorage(): DraftStorage {
  // Access to localStorage itself can throw in a restricted WebView.
  return { getItem: (key) => window.localStorage.getItem(key),
    setItem: (key, value) => window.localStorage.setItem(key, value),
    removeItem: (key) => window.localStorage.removeItem(key) };
}
export function readSelectedMission(storage: DraftStorage): string | null {
  try { return storage.getItem(selectedKey); } catch { return null; }
}
export function selectMission(storage: DraftStorage, missionId: string | null): boolean {
  try {
    if (missionId) storage.setItem(selectedKey, missionId);
    else storage.removeItem(selectedKey);
    return true;
  } catch { return false; }
}
export function resolveMissionSelection(id: string | null, missions: Pick<MissionRecord, "mission_id">[]): {
  missionId: string | null; missing: boolean;
} {
  const found = id !== null && missions.some((mission) => mission.mission_id === id);
  return { missionId: found ? id : null, missing: id !== null && !found };
}

export function missionFields(record: MissionRecord): MissionFields {
  return { strategy: record.strategy, task: record.task, success: record.success,
    constraints: record.constraints, teacherSource: record.teacher_source ?? "broker",
    teacherModel: record.teacher_model ?? "", studentModel: record.student_model ?? "" };
}
export function sameMissionFields(a: MissionFields, b: MissionFields | null): boolean {
  if (!b) return false;
  const normalize = (value: MissionFields) => [value.strategy, value.task.trim(),
    value.success.trim(), value.constraints.trim(), ...(value.strategy === "distillation"
      ? [value.teacherSource, value.teacherModel.trim(), value.studentModel.trim()] : [])];
  return JSON.stringify(normalize(a)) === JSON.stringify(normalize(b));
}
function isFields(value: unknown): value is MissionFields {
  if (!value || typeof value !== "object") return false;
  const fields = value as MissionFields;
  return ["recommend", "prompting", "rag", "lora", "distillation"].includes(fields.strategy)
    && ["task", "success", "constraints", "teacherModel", "studentModel"].every((key) =>
      typeof fields[key as keyof MissionFields] === "string")
    && ["broker", "local"].includes(fields.teacherSource);
}
export function readMissionDraft(storage: DraftStorage, missionId: string | null): MissionDraft | null {
  try {
    const draft = JSON.parse(storage.getItem(prefix + (missionId ?? "new")) ?? "null") as MissionDraft | null;
    return draft && draft.missionId === missionId && Number.isSafeInteger(draft.expectedRevision)
      && draft.expectedRevision >= 0 && isFields(draft.fields)
      && (draft.base === null || isFields(draft.base)) ? draft : null;
  } catch { return null; }
}
export function writeMissionDraft(storage: DraftStorage, draft: MissionDraft): boolean {
  try { storage.setItem(prefix + (draft.missionId ?? "new"), JSON.stringify(draft)); return true; }
  catch { return false; }
}
export function removeMissionDraft(storage: DraftStorage, missionId: string | null): void {
  try { storage.removeItem(prefix + (missionId ?? "new")); } catch { /* Retain recovery if storage is unavailable. */ }
}
