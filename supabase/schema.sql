-- Dadyar AI initial schema
-- Run in a dedicated Supabase project after reviewing RLS policies.

create extension if not exists pgcrypto;

create table if not exists public.institutions (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  website text,
  site_name text,
  logo_path text,
  created_at timestamptz not null default now()
);

create table if not exists public.classes (
  id uuid primary key default gen_random_uuid(),
  institution_id uuid references public.institutions(id) on delete cascade,
  title text not null,
  grade text,
  created_at timestamptz not null default now()
);

create table if not exists public.students (
  id uuid primary key default gen_random_uuid(),
  class_id uuid not null references public.classes(id) on delete cascade,
  student_code text not null,
  first_name text not null,
  last_name text not null,
  created_at timestamptz not null default now(),
  unique(class_id, student_code)
);

create table if not exists public.exams (
  id uuid primary key default gen_random_uuid(),
  class_id uuid references public.classes(id) on delete set null,
  title text not null,
  exam_date date,
  question_count integer not null check (question_count between 1 and 120),
  negative_coefficient numeric(5,2) not null default 3 check (negative_coefficient > 0),
  created_at timestamptz not null default now()
);

create table if not exists public.answer_keys (
  id uuid primary key default gen_random_uuid(),
  exam_id uuid not null unique references public.exams(id) on delete cascade,
  answers jsonb not null,
  created_at timestamptz not null default now()
);

create table if not exists public.submissions (
  id uuid primary key default gen_random_uuid(),
  exam_id uuid not null references public.exams(id) on delete cascade,
  student_id uuid not null references public.students(id) on delete cascade,
  sheet_code text not null unique,
  answers jsonb,
  correct_count integer not null default 0,
  wrong_count integer not null default 0,
  blank_count integer not null default 0,
  raw_score numeric(8,2),
  review_required boolean not null default false,
  source_file_path text,
  created_at timestamptz not null default now(),
  unique(exam_id, student_id)
);

-- Enable RLS before exposing tables through the Supabase client.
alter table public.institutions enable row level security;
alter table public.classes enable row level security;
alter table public.students enable row level security;
alter table public.exams enable row level security;
alter table public.answer_keys enable row level security;
alter table public.submissions enable row level security;

-- No public policies are added here intentionally. Add owner-scoped policies
-- after the authentication/tenant ownership model is finalized.
