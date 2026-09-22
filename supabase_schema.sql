-- Run this once in Supabase: SQL Editor -> New query -> Run.
-- Every policy uses auth.uid(), so students can never read one another's data.

create table if not exists public.reviews (
  id bigint generated always as identity primary key,
  user_id uuid not null references auth.users(id) on delete cascade,
  question_id text not null,
  user_answer text not null default '', score double precision not null,
  grade text not null, hit_points jsonb not null default '[]'::jsonb,
  miss_points jsonb not null default '[]'::jsonb, wrong_points jsonb not null default '[]'::jsonb,
  feedback text not null default '', ref_hit double precision not null default 0,
  elapsed_sec integer not null default 0, model text not null default '', created_at timestamp not null default now()
);
create index if not exists reviews_user_question_idx on public.reviews(user_id, question_id);

create table if not exists public.card_state (
  user_id uuid not null references auth.users(id) on delete cascade,
  question_id text not null, due timestamp, last_review timestamp,
  reps integer not null default 0, lapses integer not null default 0,
  primary key (user_id, question_id)
);

alter table public.reviews enable row level security;
alter table public.card_state enable row level security;
create policy "own reviews only" on public.reviews for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "own cards only" on public.card_state for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
