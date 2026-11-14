'use client';

import { type StudyPlan } from './study-plan';

export function StudyPlanCard({ plan }: { plan: StudyPlan }) {
  return (
    <article aria-label="Suggested study plan" className="rounded-xl border border-teal-600/30 p-4">
      <p className="text-muted-foreground text-xs font-medium tracking-wide uppercase">
        Suggested routine
      </p>
      <h3 className="mt-1 text-sm font-semibold">{plan.topic}</h3>
      <p className="text-muted-foreground mt-1 text-xs">
        {plan.total_minutes} minutes across {plan.sessions.length} sessions
      </p>
      <ol className="mt-4 space-y-3">
        {plan.sessions.map((session) => (
          <li key={session.day} className="flex justify-between gap-3 text-sm">
            <span>
              <span className="font-medium">Day {session.day}:</span> {session.focus}
            </span>
            <span className="text-muted-foreground shrink-0">{session.minutes} min</span>
          </li>
        ))}
      </ol>
      <p className="text-muted-foreground mt-4 text-xs">
        Demo suggestion only. Nothing was scheduled or saved.
      </p>
    </article>
  );
}
