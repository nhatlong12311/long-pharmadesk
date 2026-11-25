-- Apply after supabase-rpc-permissions.sql. Keep pharmacount_private out of the Data API.
-- The browser uses Supabase anonymous sign-in for each guest's session identity.
create table pharmacount_private.inventory_share_links (
  session_id uuid primary key references public.inventory_sessions(id) on delete cascade,
  token uuid not null unique default gen_random_uuid(),
  enabled boolean not null default true
);

create table pharmacount_private.inventory_link_guests (
  session_id uuid not null references pharmacount_private.inventory_share_links(session_id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  token uuid not null,
  display_name text not null check (length(display_name) between 1 and 80),
  primary key (session_id,user_id)
);

alter table pharmacount_private.inventory_share_links enable row level security;
alter table pharmacount_private.inventory_link_guests enable row level security;
revoke all on table pharmacount_private.inventory_share_links,
  pharmacount_private.inventory_link_guests from public, anon, authenticated;

create function pharmacount_private.pc_is_guest()
returns boolean language sql stable set search_path = ''
as $$ select coalesce((select auth.jwt())->>'is_anonymous' = 'true',false); $$;
revoke all on function pharmacount_private.pc_is_guest() from public, anon;
grant execute on function pharmacount_private.pc_is_guest() to authenticated;

create function pharmacount_private.pc_guest_name(p_session uuid)
returns text language sql stable security definer set search_path = ''
as $$
  select g.display_name
  from pharmacount_private.inventory_link_guests g
  join pharmacount_private.inventory_share_links l using (session_id)
  where g.session_id=p_session and g.user_id=(select auth.uid())
    and g.token=l.token and l.enabled;
$$;
revoke all on function pharmacount_private.pc_guest_name(uuid) from public, anon, authenticated;

create or replace function pharmacount_private.pc_can_view(s uuid)
returns boolean language sql stable security definer set search_path = ''
as $$
  select (select auth.uid()) is not null and
  case when (select pharmacount_private.pc_is_guest()) then
    pharmacount_private.pc_guest_name(s) is not null
  else exists (
    select 1 from public.inventory_sessions where id=s and (
      owner_id=(select auth.uid()) or exists (
        select 1 from public.inventory_members
        where session_id=s and email=lower(coalesce((select auth.jwt())->>'email',''))
      )
    )
  ) end;
$$;

alter policy pc_session_create on public.inventory_sessions
  with check (not (select pharmacount_private.pc_is_guest()) and owner_id=(select auth.uid()));
alter policy pc_members_read on public.inventory_members
  using (not (select pharmacount_private.pc_is_guest()) and pharmacount_private.pc_can_view(session_id));
alter policy pc_counts_read on public.inventory_counts
  using (not (select pharmacount_private.pc_is_guest()) and pharmacount_private.pc_can_view(session_id));

create function pharmacount_private.pc_share_inventory(p_session uuid,p_enabled boolean)
returns uuid language plpgsql security definer set search_path = ''
as $$
declare
  closed timestamptz;
  share_token uuid;
begin
  if (select auth.uid()) is null or (select pharmacount_private.pc_is_guest()) then
    raise exception 'Only inventory owner can manage the link' using errcode='42501';
  end if;
  select s.closed_at into closed from public.inventory_sessions s
    where s.id=p_session and s.owner_id=(select auth.uid()) for update;
  if not found then
    raise exception 'Only inventory owner can manage the link' using errcode='42501';
  end if;
  if p_enabled is null then
    return (select token from pharmacount_private.inventory_share_links where session_id=p_session and enabled);
  end if;
  if not p_enabled then
    update pharmacount_private.inventory_share_links set enabled=false,token=gen_random_uuid()
      where session_id=p_session and enabled;
    return null;
  end if;
  if closed is not null then raise exception 'Inventory session is finalized'; end if;
  insert into pharmacount_private.inventory_share_links(session_id) values (p_session)
    on conflict (session_id) do update set enabled=true
    returning token into share_token;
  return share_token;
end;
$$;

create function pharmacount_private.pc_join_inventory(p_token uuid,p_name text)
returns uuid language plpgsql security definer set search_path = ''
as $$
declare
  run_id uuid;
  guest_name text := trim(regexp_replace(coalesce(p_name,''),'[[:space:]]+',' ','g'));
begin
  if (select auth.uid()) is null or not (select pharmacount_private.pc_is_guest()) then
    raise exception 'Guest sign-in required' using errcode='42501';
  end if;
  if length(guest_name) not between 1 and 80 or guest_name ~ '[[:cntrl:]]' then
    raise exception 'Enter a name of 1–80 characters';
  end if;
  select l.session_id into run_id from pharmacount_private.inventory_share_links l
    join public.inventory_sessions s on s.id=l.session_id
    where l.token=p_token and l.enabled and s.closed_at is null
    for share of l;
  if not found then raise exception 'Inventory link is closed or invalid' using errcode='42501'; end if;
  insert into pharmacount_private.inventory_link_guests(session_id,user_id,token,display_name)
    values(run_id,(select auth.uid()),p_token,guest_name)
    on conflict (session_id,user_id) do update set token=excluded.token,display_name=excluded.display_name;
  return run_id;
end;
$$;

create function public.pc_share_inventory(p_session uuid,p_enabled boolean default null)
returns uuid language sql security invoker set search_path = ''
as $$ select pharmacount_private.pc_share_inventory(p_session,p_enabled); $$;

create function public.pc_join_inventory(p_token uuid,p_name text)
returns uuid language sql security invoker set search_path = ''
as $$ select pharmacount_private.pc_join_inventory(p_token,p_name); $$;

revoke all on function public.pc_share_inventory(uuid,boolean), public.pc_join_inventory(uuid,text),
  pharmacount_private.pc_share_inventory(uuid,boolean), pharmacount_private.pc_join_inventory(uuid,text) from public, anon;
grant execute on function public.pc_share_inventory(uuid,boolean), public.pc_join_inventory(uuid,text),
  pharmacount_private.pc_share_inventory(uuid,boolean), pharmacount_private.pc_join_inventory(uuid,text) to authenticated;

alter table public.inventory_counts add column counter_name text;

-- Keep real email separate from a guest's display name.
create or replace function public.pc_fill_count_email()
returns trigger language plpgsql security invoker set search_path = ''
as $$
begin
  if (select pharmacount_private.pc_is_guest()) then
    new.counter_name := pharmacount_private.pc_guest_name(new.session_id);
    if new.counter_name is null then raise exception 'Inventory access denied' using errcode='42501'; end if;
    new.users_email := '';
  else
    new.counter_name := null;
    new.users_email := lower(coalesce((select auth.jwt())->>'email',''));
  end if;
  return new;
end;
$$;
revoke all on function public.pc_fill_count_email() from public, anon, authenticated;

-- Guests may see the latest counts for their run, without member email addresses or audit history.
create function pharmacount_private.pc_latest_counts(p_session uuid,p_offset integer,p_limit integer)
returns table (id bigint,item_id text,count_values jsonb,note text,actual numeric,
  created_at timestamptz,users_email text)
language plpgsql stable security definer set search_path = ''
as $$
declare
  guest boolean := (select pharmacount_private.pc_is_guest());
begin
  if not pharmacount_private.pc_can_view(p_session) then raise exception 'Inventory access denied' using errcode='42501'; end if;
  if p_offset is null or p_offset not between 0 and 100000 or p_limit is null or p_limit not between 1 and 750 then
    raise exception 'Invalid inventory snapshot pagination';
  end if;
  return query
    select latest.id,latest.item_id,latest.values,latest.note,latest.actual,latest.created_at,
      coalesce(latest.counter_name,case when guest then 'Thành viên' else latest.users_email end)
    from (
      select distinct on (c.item_id) c.id,c.item_id,c.values,c.note,c.actual,c.created_at,c.counter_name,c.users_email
      from public.inventory_counts c where c.session_id=p_session order by c.item_id,c.id desc
    ) latest
    order by latest.item_id limit p_limit offset p_offset;
end;
$$;

create or replace function public.pc_latest_counts(p_session uuid,p_offset integer default 0,p_limit integer default 500)
returns table (id bigint,item_id text,count_values jsonb,note text,actual numeric,
  created_at timestamptz,users_email text)
language sql stable security invoker set search_path = ''
as $$ select * from pharmacount_private.pc_latest_counts(p_session,p_offset,p_limit); $$;

revoke all on function pharmacount_private.pc_latest_counts(uuid,integer,integer) from public, anon;
grant execute on function pharmacount_private.pc_latest_counts(uuid,integer,integer) to authenticated;
