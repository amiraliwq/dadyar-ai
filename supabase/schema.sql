-- Dadyar AI production schema
-- Run only in a dedicated Dadyar Supabase project.
create extension if not exists pgcrypto;

create table if not exists public.institutions (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id) on delete restrict,
  name text not null,
  website text,
  site_name text not null default 'دادیار AI',
  logo_url text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.institution_members (
  institution_id uuid not null references public.institutions(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  role text not null default 'teacher' check (role in ('admin','teacher','viewer')),
  created_at timestamptz not null default now(),
  primary key (institution_id,user_id)
);

create or replace function public.is_institution_member(target_institution uuid)
returns boolean language sql stable security definer set search_path = public
as $$
  select exists (
    select 1 from public.institutions i
    where i.id = target_institution and i.owner_id = auth.uid()
  ) or exists (
    select 1 from public.institution_members m
    where m.institution_id = target_institution and m.user_id = auth.uid()
  );
$$;

create or replace function public.can_edit_institution(target_institution uuid)
returns boolean language sql stable security definer set search_path = public
as $
  select exists (
    select 1 from public.institutions i
    where i.id = target_institution and i.owner_id = auth.uid()
  ) or exists (
    select 1 from public.institution_members m
    where m.institution_id = target_institution and m.user_id = auth.uid()
      and m.role in ('admin','teacher')
  );
$;

create table if not exists public.profiles (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null unique references auth.users(id) on delete cascade,
  institution_id uuid not null references public.institutions(id) on delete cascade,
  role text not null default 'owner' check (role in ('owner','admin','teacher','viewer')),
  full_name text not null default '',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.classes (
  id uuid primary key default gen_random_uuid(),
  institution_id uuid not null references public.institutions(id) on delete cascade,
  title text not null,
  grade text,
  created_at timestamptz not null default now(),
  unique(institution_id,title),
  unique(id,institution_id)
);

create table if not exists public.students (
  id uuid primary key default gen_random_uuid(),
  institution_id uuid not null references public.institutions(id) on delete cascade,
  class_id uuid not null,
  student_code text not null,
  first_name text not null,
  last_name text not null,
  created_at timestamptz not null default now(),
  unique(class_id,student_code),
  foreign key (class_id,institution_id) references public.classes(id,institution_id) on delete cascade
);

create table if not exists public.exams (
  id uuid primary key default gen_random_uuid(),
  institution_id uuid not null references public.institutions(id) on delete cascade,
  class_id uuid references public.classes(id) on delete set null,
  title text not null,
  subject text not null default '',
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
  unresolved_count integer not null default 0 check (unresolved_count >= 0),
  uncertain_answers jsonb not null default '[]'::jsonb,
  raw_score numeric(8,2),
  review_required boolean not null default true,
  source_file_name text,
  source_file_path text,
  reviewed_by uuid references auth.users(id) on delete set null,
  reviewed_at timestamptz,
  created_at timestamptz not null default now(),
  unique(exam_id,student_id)
);

create index if not exists profiles_user_idx on public.profiles(user_id);
create index if not exists classes_institution_idx on public.classes(institution_id);
create index if not exists students_institution_idx on public.students(institution_id);
create index if not exists students_class_idx on public.students(class_id);
create index if not exists exams_institution_date_idx on public.exams(institution_id,exam_date desc);
create index if not exists submissions_exam_idx on public.submissions(exam_id);
create index if not exists submissions_student_idx on public.submissions(student_id);

alter table public.institutions enable row level security;
alter table public.institution_members enable row level security;
alter table public.profiles enable row level security;
alter table public.classes enable row level security;
alter table public.students enable row level security;
alter table public.exams enable row level security;
alter table public.answer_keys enable row level security;
alter table public.submissions enable row level security;

drop policy if exists "institution member read" on public.institutions;
create policy "institution member read" on public.institutions
for select to authenticated using (public.is_institution_member(id));
drop policy if exists "institution owner insert" on public.institutions;
create policy "institution owner insert" on public.institutions
for insert to authenticated with check (owner_id = auth.uid());
drop policy if exists "institution owner update" on public.institutions;
create policy "institution owner update" on public.institutions
for update to authenticated using (owner_id = auth.uid()) with check (owner_id = auth.uid());
drop policy if exists "institution owner delete" on public.institutions;
create policy "institution owner delete" on public.institutions
for delete to authenticated using (owner_id = auth.uid());

drop policy if exists "members view" on public.institution_members;
create policy "members view" on public.institution_members
for select to authenticated using (
  user_id = auth.uid() or exists (
    select 1 from public.institutions i where i.id = institution_id and i.owner_id = auth.uid()
  )
);
drop policy if exists "owners manage members" on public.institution_members;
create policy "owners manage members" on public.institution_members
for all to authenticated using (
  exists (select 1 from public.institutions i where i.id = institution_id and i.owner_id = auth.uid())
) with check (
  exists (select 1 from public.institutions i where i.id = institution_id and i.owner_id = auth.uid())
);

drop policy if exists "profile self access" on public.profiles;
drop policy if exists "profile self read" on public.profiles;
create policy "profile self read" on public.profiles
for select to authenticated using (user_id = auth.uid());
drop policy if exists "profile owner onboarding" on public.profiles;
create policy "profile owner onboarding" on public.profiles
for insert to authenticated with check (
  user_id = auth.uid() and role = 'owner' and exists (
    select 1 from public.institutions i where i.id = institution_id and i.owner_id = auth.uid()
  )
);

drop policy if exists "class member access" on public.classes;
create policy "class member read" on public.classes for select to authenticated
using (public.is_institution_member(institution_id));
create policy "class member write" on public.classes for insert to authenticated
with check (public.can_edit_institution(institution_id));
create policy "class member update" on public.classes for update to authenticated
using (public.can_edit_institution(institution_id)) with check (public.can_edit_institution(institution_id));
create policy "class member delete" on public.classes for delete to authenticated
using (public.can_edit_institution(institution_id));

drop policy if exists "student member access" on public.students;
create policy "student member read" on public.students for select to authenticated
using (public.is_institution_member(institution_id));
create policy "student member write" on public.students for insert to authenticated
with check (public.can_edit_institution(institution_id));
create policy "student member update" on public.students for update to authenticated
using (public.can_edit_institution(institution_id)) with check (public.can_edit_institution(institution_id));
create policy "student member delete" on public.students for delete to authenticated
using (public.can_edit_institution(institution_id));

drop policy if exists "exam member access" on public.exams;
create policy "exam member read" on public.exams for select to authenticated
using (public.is_institution_member(institution_id));
create policy "exam member write" on public.exams for insert to authenticated
with check (public.can_edit_institution(institution_id));
create policy "exam member update" on public.exams for update to authenticated
using (public.can_edit_institution(institution_id)) with check (public.can_edit_institution(institution_id));
create policy "exam member delete" on public.exams for delete to authenticated
using (public.can_edit_institution(institution_id));

drop policy if exists "answer key member access" on public.answer_keys;
create policy "answer key member read" on public.answer_keys for select to authenticated
using (exists (select 1 from public.exams e where e.id = exam_id and public.is_institution_member(e.institution_id)));
create policy "answer key member write" on public.answer_keys for insert to authenticated
with check (exists (select 1 from public.exams e where e.id = exam_id and public.can_edit_institution(e.institution_id)));
create policy "answer key member update" on public.answer_keys for update to authenticated
using (exists (select 1 from public.exams e where e.id = exam_id and public.can_edit_institution(e.institution_id)))
with check (exists (select 1 from public.exams e where e.id = exam_id and public.can_edit_institution(e.institution_id)));
create policy "answer key member delete" on public.answer_keys for delete to authenticated
using (exists (select 1 from public.exams e where e.id = exam_id and public.can_edit_institution(e.institution_id)));

drop policy if exists "submission member access" on public.submissions;
create policy "submission member read" on public.submissions for select to authenticated
using (public.is_institution_member(institution_id));
create policy "submission member write" on public.submissions for insert to authenticated
with check (public.can_edit_institution(institution_id));
create policy "submission member update" on public.submissions for update to authenticated
using (public.can_edit_institution(institution_id)) with check (public.can_edit_institution(institution_id));
create policy "submission member delete" on public.submissions for delete to authenticated
using (public.can_edit_institution(institution_id));

insert into storage.buckets (id,name,public,file_size_limit,allowed_mime_types)
values ('dadyar-private','dadyar-private',false,15728640,
  array['image/jpeg','image/png','image/webp','application/pdf'])
on conflict (id) do update set public=false,file_size_limit=15728640,
  allowed_mime_types=excluded.allowed_mime_types;

drop policy if exists "institution members read dadyar files" on storage.objects;
create policy "institution members read dadyar files" on storage.objects
for select to authenticated using (
  bucket_id='dadyar-private' and exists (
    select 1 from public.institutions i where i.id::text=split_part(name,'/',1)
      and public.is_institution_member(i.id)
  )
);
drop policy if exists "institution members upload dadyar files" on storage.objects;
create policy "institution members upload dadyar files" on storage.objects
for insert to authenticated with check (
  bucket_id='dadyar-private' and exists (
    select 1 from public.institutions i where i.id::text=split_part(name,'/',1)
      and public.can_edit_institution(i.id)
  )
);
drop policy if exists "institution members update dadyar files" on storage.objects;
create policy "institution members update dadyar files" on storage.objects
for update to authenticated using (
  bucket_id='dadyar-private' and exists (
    select 1 from public.institutions i where i.id::text=split_part(name,'/',1)
      and public.can_edit_institution(i.id)
  )
) with check (
  bucket_id='dadyar-private' and exists (
    select 1 from public.institutions i where i.id::text=split_part(name,'/',1)
      and public.can_edit_institution(i.id)
  )
);
drop policy if exists "institution members delete dadyar files" on storage.objects;
create policy "institution members delete dadyar files" on storage.objects
for delete to authenticated using (
  bucket_id='dadyar-private' and exists (
    select 1 from public.institutions i where i.id::text=split_part(name,'/',1)
      and public.can_edit_institution(i.id)
  )
);
