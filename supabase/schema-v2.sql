-- Dadyar AI production bootstrap schema
-- Run once in the SQL Editor of the dedicated Dadyar Supabase project.
-- Never put a service-role key in the browser or commit it to GitHub.

create extension if not exists pgcrypto;

create table if not exists public.institutions (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete cascade,
  name text not null,
  website text,
  site_name text default 'دادیار AI',
  logo_url text,
  created_at timestamptz not null default now()
);

create table if not exists public.profiles (
  user_id uuid primary key references auth.users(id) on delete cascade,
  institution_id uuid not null references public.institutions(id) on delete cascade,
  full_name text,
  role text not null default 'owner' check (role in ('owner','manager','teacher','reviewer')),
  created_at timestamptz not null default now()
);

create table if not exists public.classes (
  id uuid primary key default gen_random_uuid(),
  institution_id uuid not null references public.institutions(id) on delete cascade,
  title text not null,
  grade text,
  created_at timestamptz not null default now(),
  unique (institution_id, title)
);

create table if not exists public.students (
  id uuid primary key default gen_random_uuid(),
  institution_id uuid not null references public.institutions(id) on delete cascade,
  class_id uuid not null references public.classes(id) on delete cascade,
  student_code text not null,
  first_name text not null,
  last_name text not null,
  created_at timestamptz not null default now(),
  unique (institution_id, student_code)
);

create table if not exists public.exams (
  id uuid primary key default gen_random_uuid(),
  institution_id uuid not null references public.institutions(id) on delete cascade,
  class_id uuid references public.classes(id) on delete set null,
  title text not null,
  subject text,
  exam_date date,
  question_count integer not null check (question_count between 1 and 120),
  negative_coefficient numeric(5,2) not null default 3 check (negative_coefficient >= 0),
  created_at timestamptz not null default now()
);

create table if not exists public.answer_keys (
  id uuid primary key default gen_random_uuid(),
  exam_id uuid not null unique references public.exams(id) on delete cascade,
  answers jsonb not null check (jsonb_typeof(answers) = 'array'),
  created_at timestamptz not null default now()
);

create table if not exists public.submissions (
  id uuid primary key default gen_random_uuid(),
  institution_id uuid not null references public.institutions(id) on delete cascade,
  exam_id uuid not null references public.exams(id) on delete cascade,
  student_id uuid not null references public.students(id) on delete cascade,
  sheet_code text not null unique,
  answers jsonb,
  correct_count integer not null default 0 check (correct_count >= 0),
  wrong_count integer not null default 0 check (wrong_count >= 0),
  blank_count integer not null default 0 check (blank_count >= 0),
  raw_score numeric(8,2),
  review_required boolean not null default false,
  uncertain_answers jsonb not null default '[]'::jsonb,
  source_file_name text,
  source_file_path text,
  created_at timestamptz not null default now(),
  unique (exam_id, student_id)
);

create index if not exists classes_institution_idx on public.classes(institution_id);
create index if not exists students_institution_idx on public.students(institution_id);
create index if not exists students_class_idx on public.students(class_id);
create index if not exists exams_institution_idx on public.exams(institution_id);
create index if not exists submissions_exam_idx on public.submissions(exam_id);
create index if not exists submissions_institution_idx on public.submissions(institution_id);

alter table public.institutions enable row level security;
alter table public.profiles enable row level security;
alter table public.classes enable row level security;
alter table public.students enable row level security;
alter table public.exams enable row level security;
alter table public.answer_keys enable row level security;
alter table public.submissions enable row level security;

-- An authenticated user may only read/update their own profile.
drop policy if exists "profile_select_self" on public.profiles;
create policy "profile_select_self" on public.profiles
for select to authenticated using (user_id = (select auth.uid()));

drop policy if exists "profile_insert_self_owned_institution" on public.profiles;
create policy "profile_insert_self_owned_institution" on public.profiles
for insert to authenticated with check (
  user_id = (select auth.uid())
  and exists (
    select 1 from public.institutions i
    where i.id = institution_id and i.owner_id = (select auth.uid())
  )
);

drop policy if exists "profile_update_self" on public.profiles;
create policy "profile_update_self" on public.profiles
for update to authenticated
using (user_id = (select auth.uid()))
with check (
  user_id = (select auth.uid())
  and exists (
    select 1 from public.institutions i
    where i.id = institution_id and i.owner_id = (select auth.uid())
  )
);

drop policy if exists "institution_owner_all" on public.institutions;
create policy "institution_owner_all" on public.institutions
for all to authenticated
using (owner_id = (select auth.uid()))
with check (owner_id = (select auth.uid()));

-- Tenant isolation: every row must belong to the signed-in user's institution.
do $$
declare t text;
begin
  foreach t in array array['classes','students','exams','submissions'] loop
    execute format('drop policy if exists %I on public.%I', t || '_tenant_all', t);
    execute format(
      'create policy %I on public.%I for all to authenticated using (institution_id in (select p.institution_id from public.profiles p where p.user_id = (select auth.uid()))) with check (institution_id in (select p.institution_id from public.profiles p where p.user_id = (select auth.uid())))',
      t || '_tenant_all', t
    );
  end loop;
end $$;

drop policy if exists "answer_keys_tenant_all" on public.answer_keys;
create policy "answer_keys_tenant_all" on public.answer_keys
for all to authenticated
using (
  exists (
    select 1 from public.exams e
    join public.profiles p on p.institution_id = e.institution_id
    where e.id = exam_id and p.user_id = (select auth.uid())
  )
)
with check (
  exists (
    select 1 from public.exams e
    join public.profiles p on p.institution_id = e.institution_id
    where e.id = exam_id and p.user_id = (select auth.uid())
  )
);

-- Private bucket for uploaded scans and generated assets.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('answer-sheets', 'answer-sheets', false, 15728640,
        array['image/jpeg','image/png','image/webp','application/pdf'])
on conflict (id) do update set public = false, file_size_limit = 15728640;

drop policy if exists "answer_sheet_objects_select" on storage.objects;
create policy "answer_sheet_objects_select" on storage.objects
for select to authenticated
using (
  bucket_id = 'answer-sheets'
  and exists (
    select 1 from public.profiles p
    where p.user_id = (select auth.uid())
      and p.institution_id::text = (storage.foldername(name))[1]
  )
);

drop policy if exists "answer_sheet_objects_insert" on storage.objects;
create policy "answer_sheet_objects_insert" on storage.objects
for insert to authenticated
with check (
  bucket_id = 'answer-sheets'
  and exists (
    select 1 from public.profiles p
    where p.user_id = (select auth.uid())
      and p.institution_id::text = (storage.foldername(name))[1]
  )
);

drop policy if exists "answer_sheet_objects_delete" on storage.objects;
create policy "answer_sheet_objects_delete" on storage.objects
for delete to authenticated
using (
  bucket_id = 'answer-sheets'
  and exists (
    select 1 from public.profiles p
    where p.user_id = (select auth.uid())
      and p.institution_id::text = (storage.foldername(name))[1]
  )
);

grant select, insert, update, delete on public.institutions, public.profiles,
  public.classes, public.students, public.exams, public.answer_keys, public.submissions
to authenticated;

-- Data API grants are explicit; RLS remains the row-level security boundary.
