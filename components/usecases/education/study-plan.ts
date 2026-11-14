// Validate received data before rendering. This is not the domain/business service.
export interface StudyPlan {
  topic: string;
  total_minutes: number;
  sessions: { day: number; focus: string; minutes: number }[];
}
export function parseStudyPlan(data: Record<string, unknown> | undefined): StudyPlan | null {
  if (
    !data ||
    typeof data.topic !== 'string' ||
    !data.topic.trim() ||
    data.topic.length > 80 ||
    typeof data.total_minutes !== 'number' ||
    !Number.isInteger(data.total_minutes) ||
    data.total_minutes < 10 ||
    data.total_minutes > 840 ||
    !Array.isArray(data.sessions) ||
    data.sessions.length < 1 ||
    data.sessions.length > 7
  )
    return null;
  const sessions: StudyPlan['sessions'] = [];
  for (const item of data.sessions) {
    if (
      !item ||
      typeof item !== 'object' ||
      !Number.isInteger(item.day) ||
      item.day < 1 ||
      item.day > 7 ||
      typeof item.focus !== 'string' ||
      item.focus.length > 100 ||
      !Number.isInteger(item.minutes) ||
      item.minutes < 10 ||
      item.minutes > 120
    )
      return null;
    sessions.push({ day: item.day, focus: item.focus, minutes: item.minutes });
  }
  if (
    new Set(sessions.map((s) => s.day)).size !== sessions.length ||
    sessions.reduce((sum, s) => sum + s.minutes, 0) !== data.total_minutes
  )
    return null;
  return { topic: data.topic, total_minutes: data.total_minutes, sessions };
}
