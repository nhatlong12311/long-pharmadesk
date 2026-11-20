-- PharmaCount schema; run in Supabase SQL editor.
-- Each user authenticates with email OTP. Membership is per inventory session.
create table if not exists public.inventory_sessions (
 id uuid primary key default gen_random_uuid(),
 name text not null,
 owner_id uuid not null references auth.users(id),
 created_at timestamptz not null default now()
);
create table if not exists public.inventory_members (
 session_id uuid not null references public.inventory_sessions(id) on delete cascade,
 email text not null,
 created_at timestamptz not null default now(),
 primary key (session_id,email),
 constraint normalized_email check (email=lower(email))
);
create table if not exists public.inventory_items (
 session_id uuid not null references public.inventory_sessions(id) on delete cascade,
 id text not null,
 drug jsonb not null,
 primary key(session_id,id)
);
create table if not exists public.inventory_counts (
 id bigint generated always as identity primary key,
 session_id uuid not null,
 item_id text not null,
 user_id uuid not null references auth.users(id),
 users_email text not null default '',
 values jsonb not null,
 actual numeric not null,
 note text not null default '',
 created_at timestamptz not null default now(),
 foreign key(session_id,item_id) references public.inventory_items(session_id,id) on delete cascade,
 constraint valid_actual check(actual>=0)
);
create index if not exists inventory_counts_session_time on public.inventory_counts(session_id,created_at desc);
create index if not exists inventory_items_session on public.inventory_items(session_id);
create index if not exists inventory_members_email on public.inventory_members(email);
-- SECURITY DEFINER functions prevent recursive policies on session/member tables.
create or replace function public.pc_is_owner(s uuid)
returns boolean language sql stable security definer set search_path=public
as $$ select exists(select 1 from public.inventory_sessions where id=s and owner_id=auth.uid()) $$;
create or replace function public.pc_can_view(s uuid)
returns boolean language sql stable security definer set search_path=public
as $$ select exists(select 1 from public.inventory_sessions where id=s and (owner_id=auth.uid()
 or exists(select 1 from public.inventory_members where session_id=s and email=lower(coalesce(auth.jwt()->>'email',''))))) $$;
revoke all on function public.pc_is_owner(uuid) from public;
revoke all on function public.pc_can_view(uuid) from public;
grant execute on function public.pc_is_owner(uuid) to authenticated;
grant execute on function public.pc_can_view(uuid) to authenticated;
alter table public.inventory_sessions enable row level security;
alter table public.inventory_members enable row level security;
alter table public.inventory_items enable row level security;
alter table public.inventory_counts enable row level security;
drop policy if exists pc_session_read on public.inventory_sessions;
drop policy if exists pc_session_create on public.inventory_sessions;
drop policy if exists pc_members_read on public.inventory_members;
drop policy if exists pc_members_create on public.inventory_members;
drop policy if exists pc_items_read on public.inventory_items;
drop policy if exists pc_items_create on public.inventory_items;
drop policy if exists pc_counts_read on public.inventory_counts;
drop policy if exists pc_counts_create on public.inventory_counts;
create policy pc_session_read on public.inventory_sessions for select to authenticated using(public.pc_can_view(id));
create policy pc_session_create on public.inventory_sessions for insert to authenticated with check(owner_id=auth.uid());
create policy pc_members_read on public.inventory_members for select to authenticated using(public.pc_can_view(session_id));
create policy pc_members_create on public.inventory_members for insert to authenticated with check(public.pc_is_owner(session_id));
create policy pc_items_read on public.inventory_items for select to authenticated using(public.pc_can_view(session_id));
create policy pc_items_create on public.inventory_items for insert to authenticated with check(public.pc_is_owner(session_id));
create policy pc_counts_read on public.inventory_counts for select to authenticated using(public.pc_can_view(session_id));
create policy pc_counts_create on public.inventory_counts for insert to authenticated
 with check(public.pc_can_view(session_id) and user_id=auth.uid() and users_email=lower(coalesce(auth.jwt()->>'email','')));
-- The counts table is append-only: correction adds a new event; keep audit history.
-- Prevent a participant forging who recorded a count.
create or replace function public.pc_fill_count_email()
returns trigger language plpgsql security definer set search_path=public
as $$ begin new.users_email := lower(coalesce(auth.jwt()->>'email','')); return new; end; $$;
drop trigger if exists pc_fill_count_email_trigger on public.inventory_counts;
create trigger pc_fill_count_email_trigger before insert on public.inventory_counts
for each row execute function public.pc_fill_count_email();
-- Note: the INSERT check runs after BEFORE triggers in PostgreSQL.
