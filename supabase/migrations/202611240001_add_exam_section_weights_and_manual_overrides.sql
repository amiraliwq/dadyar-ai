-- Multi-subject weighting and teacher answer overrides.
-- The live project already contains subjects, lessons and exam_sections.
alter table public.exam_sections
  add column if not exists weight numeric(8,3) not null default 1 check (weight > 0);

alter table public.submissions
  add column if not exists ocr_answers jsonb,
  add column if not exists question_states jsonb not null default '[]'::jsonb,
  add column if not exists manual_override boolean not null default false,
  add column if not exists manually_reviewed_by uuid references auth.users(id) on delete set null,
  add column if not exists manually_reviewed_at timestamptz;

update public.submissions set ocr_answers=answers
where ocr_answers is null and answers is not null;

create table if not exists public.submission_answer_audit (
 id uuid primary key default gen_random_uuid(),
 submission_id uuid not null references public.submissions(id) on delete cascade,
 question_number integer not null check(question_number>=1),
 old_value jsonb,
 new_value jsonb not null,
 changed_by uuid not null references auth.users(id) on delete restrict,
 changed_at timestamptz not null default now()
);
create index if not exists submission_answer_audit_submission_idx
 on public.submission_answer_audit(submission_id,changed_at desc);

alter table public.submission_answer_audit enable row level security;
drop policy if exists "submission answer audit tenant access" on public.submission_answer_audit;
create policy "submission answer audit tenant access" on public.submission_answer_audit
for all to authenticated
using (exists(
 select 1 from public.submissions s
 join public.profiles p on p.institution_id=s.institution_id
 where s.id=submission_id and p.user_id=(select auth.uid())
))
with check (
 changed_by=(select auth.uid()) and exists(
  select 1 from public.submissions s
  join public.profiles p on p.institution_id=s.institution_id
  where s.id=submission_id and p.user_id=(select auth.uid())
 )
);
grant select,insert on public.submission_answer_audit to authenticated;
