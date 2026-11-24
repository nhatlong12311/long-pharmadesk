-- Apply after supabase-finalization-item-guard.sql.
-- Keep this schema out of the PostgREST exposed-schema list.
create schema pharmacount_private;
revoke all on schema pharmacount_private from public, anon, authenticated;
grant usage on schema pharmacount_private to authenticated;

-- Moving these functions preserves the OIDs referenced by existing RLS policies.
alter function public.pc_is_owner(uuid) set schema pharmacount_private;
alter function public.pc_can_view(uuid) set schema pharmacount_private;

create or replace function pharmacount_private.pc_is_owner(s uuid)
returns boolean language sql stable security definer set search_path = ''
as $$
  select exists (
    select 1 from public.inventory_sessions
    where id = s and owner_id = (select auth.uid())
  );
$$;

create or replace function pharmacount_private.pc_can_view(s uuid)
returns boolean language sql stable security definer set search_path = ''
as $$
  select (select auth.uid()) is not null and exists (
    select 1 from public.inventory_sessions
    where id = s and (
      owner_id = (select auth.uid())
      or exists (
        select 1 from public.inventory_members
        where session_id = s and email = lower(coalesce((select auth.jwt())->>'email',''))
      )
    )
  );
$$;

revoke all on function pharmacount_private.pc_is_owner(uuid),
  pharmacount_private.pc_can_view(uuid) from public, anon;
grant execute on function pharmacount_private.pc_is_owner(uuid),
  pharmacount_private.pc_can_view(uuid) to authenticated;

-- Preserve the exposed RPC contract while keeping privileged writes internal.
create or replace function pharmacount_private.pc_submit_count(p_session uuid, p_item text, p_expected text, p_operation uuid,
  p_values jsonb, p_note text
) returns jsonb
language plpgsql security definer set search_path = ''
as $function$
declare
  item jsonb;
  previous public.inventory_counts;
  prior_operation public.inventory_counts;
  factors jsonb;
  total numeric := 0;
  q jsonb;
  factor numeric;
  ix integer;
  session_closed_at timestamptz;
begin
  if auth.uid() is null or not pharmacount_private.pc_can_view(p_session) then
    raise exception 'Inventory access denied' using errcode = '42501';
  end if;
  -- Serialize saves against finalization by locking the parent session first.
  select s.closed_at into session_closed_at
  from public.inventory_sessions s where s.id=p_session for update;
  if not found then raise exception 'Inventory session not found'; end if;
  if p_operation is null or p_item is null or length(p_item)>200 then
    raise exception 'Invalid operation ID or item';
  end if;
  if length(coalesce(p_note,''))>1000 then
    raise exception 'Note too long';
  end if;

  select drug into item from public.inventory_items
  where session_id=p_session and id=p_item for update;
  if not found then raise exception 'Inventory item not found'; end if;

  -- A retry of a successful request is idempotent, not another counted row.
  select * into prior_operation
  from public.inventory_counts where operation_id=p_operation;
  if found then
    if prior_operation.user_id<>auth.uid()
       or prior_operation.session_id<>p_session
       or prior_operation.item_id<>p_item
       or prior_operation.values is distinct from p_values
       or prior_operation.note is distinct from coalesce(p_note,'') then
      raise exception 'Operation ID already used';
    end if;
    return jsonb_build_object('status','saved','version',prior_operation.id::text);
  end if;

  if session_closed_at is not null then
    raise exception 'Inventory session has been finalized' using errcode='P0001';
  end if;
  select * into previous
  from public.inventory_counts
  where session_id=p_session and item_id=p_item
  order by id desc limit 1;

  if previous.id::text is distinct from p_expected then
    return jsonb_build_object('status','conflict','version',previous.id::text);
  end if;

  factors := item->'pack';
  if jsonb_typeof(p_values) is distinct from 'array'
     or jsonb_typeof(factors) is distinct from 'array'
     or jsonb_array_length(p_values) <> jsonb_array_length(factors)
     or jsonb_array_length(p_values) = 0
     or jsonb_array_length(p_values) > 20 then
    raise exception 'Invalid count format';
  end if;

  for ix in 0..jsonb_array_length(p_values)-1 loop
    q := p_values->ix;
    if jsonb_typeof(q)<>'number' or q::text !~ '^[0-9]+$'
       or q::text::numeric > 9007199254740991 then
      raise exception 'Invalid quantity';
    end if;
    if (factors->ix->>'factor') !~ '^[0-9]+$' then
      raise exception 'Invalid package factor';
    end if;
    factor := (factors->ix->>'factor')::numeric;
    if factor < 1 or factor > 9007199254740991 then
      raise exception 'Invalid package factor';
    end if;
    total := total + q::text::numeric * factor;
  end loop;
  if total > 9007199254740991 then
    raise exception 'Count total out of range';
  end if;

  insert into public.inventory_counts
    (session_id,item_id,user_id,values,actual,note,operation_id)
  values
    (p_session,p_item,auth.uid(),p_values,total,coalesce(p_note,''),p_operation)
  returning * into previous;

  return jsonb_build_object('status','saved','version',previous.id::text);
end
$function$;

revoke all on function pharmacount_private.pc_submit_count(uuid,text,text,uuid,jsonb,text)
  from public, anon;
grant execute on function pharmacount_private.pc_submit_count(uuid,text,text,uuid,jsonb,text)
  to authenticated;

create or replace function public.pc_submit_count(
  p_session uuid, p_item text, p_expected text, p_operation uuid,
  p_values jsonb, p_note text
) returns jsonb
language sql security invoker set search_path = ''
as $$
  select pharmacount_private.pc_submit_count(p_session,p_item,p_expected,p_operation,p_values,p_note);
$$;
revoke all on function public.pc_submit_count(uuid,text,text,uuid,jsonb,text)
  from public, anon;
grant execute on function public.pc_submit_count(uuid,text,text,uuid,jsonb,text)
  to authenticated;

create or replace function public.pc_latest_counts(
  p_session uuid, p_offset integer default 0, p_limit integer default 500
)
returns table (
 id bigint, item_id text, count_values jsonb, note text, actual numeric,
 created_at timestamptz, users_email text
)
language plpgsql stable security invoker set search_path = ''
as $$
begin
 if auth.uid() is null or not pharmacount_private.pc_can_view(p_session) then
   raise exception 'Inventory access denied' using errcode='42501';
 end if;
 if p_session is null or p_offset < 0 or p_offset > 100000
     or p_limit < 1 or p_limit > 750 then
   raise exception 'Invalid inventory snapshot pagination';
 end if;
 return query
 select l.id,l.item_id,l.count_values,l.note,l.actual,l.created_at,l.users_email
 from (
   select distinct on (c.item_id)
     c.id,c.item_id,c.values as count_values,c.note,c.actual,c.created_at,c.users_email
   from public.inventory_counts as c
   where c.session_id=p_session
   order by c.item_id,c.id desc
 ) as l
 order by l.item_id
 limit p_limit offset p_offset;
end;
$$;
