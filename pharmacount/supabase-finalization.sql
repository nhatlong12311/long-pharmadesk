-- PharmaCount owner-only session finalization; SQL migration after prior steps.
-- Every item must have one verified count. Finalized sessions become immutable.
alter table public.inventory_sessions
 add column if not exists closed_at timestamptz,
 add column if not exists closed_by uuid references auth.users(id);

drop policy if exists pc_sessions_close on public.inventory_sessions;
create policy pc_sessions_close on public.inventory_sessions
 for update to authenticated
 using (owner_id=(select auth.uid()) and closed_at is null)
 with check (owner_id=(select auth.uid()));

grant update (closed_at) on public.inventory_sessions to authenticated;

create or replace function public.pc_validate_session_finalize()
returns trigger language plpgsql security invoker set search_path = ''
as $function$
declare missing_count integer;
begin
 if old.closed_at is not null then
  if new is distinct from old then
    raise exception 'Finalized session cannot be edited';
  end if;
  return new;
 end if;
 if new.closed_at is not null then
   if auth.uid() is null or old.owner_id is distinct from auth.uid() then
     raise exception 'Only inventory owner can finalize' using errcode='42501';
   end if;
   select count(*) into missing_count
   from public.inventory_items i
   where i.session_id=old.id and not exists(
    select 1 from public.inventory_counts c
    where c.session_id=i.session_id and c.item_id=i.id
   );
   if missing_count>0 then
    raise exception 'Cannot finalize: % drugs have not been counted',missing_count;
   end if;
   new.closed_by:=auth.uid();
 end if;
 return new;
end
$function$;
drop trigger if exists pc_session_finalize_guard on public.inventory_sessions;
create trigger pc_session_finalize_guard before update on public.inventory_sessions
 for each row execute function public.pc_validate_session_finalize();

create or replace function public.pc_finalize_session(p_session uuid)
returns jsonb language plpgsql security invoker set search_path = ''
as $function$
declare s public.inventory_sessions;
begin
 if auth.uid() is null then
  raise exception 'Sign-in required' using errcode='42501';
 end if;
 select * into s from public.inventory_sessions where id=p_session for update;
 if not found or s.owner_id is distinct from auth.uid() then
  raise exception 'Only inventory owner can finalize' using errcode='42501';
 end if;
 if s.closed_at is not null then
  return jsonb_build_object('status','finalized','closed_at',s.closed_at);
 end if;
 update public.inventory_sessions
 set closed_at=clock_timestamp() where id=p_session
 returning * into s;
 return jsonb_build_object('status','finalized','closed_at',s.closed_at);
end
$function$;

revoke all on function public.pc_finalize_session(uuid) from public,anon;
grant execute on function public.pc_finalize_session(uuid) to authenticated;

-- Replaces the existing count RPC; locks session before item to prevent
-- a count from committing after the session has been finalized.
create or replace function public.pc_submit_count(
  p_session uuid, p_item text, p_expected text, p_operation uuid,
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
  if auth.uid() is null or not public.pc_can_view(p_session) then
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


