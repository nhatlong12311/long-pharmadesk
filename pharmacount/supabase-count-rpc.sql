-- PharmaCount concurrency extension for Supabase.
-- Apply AFTER pharmacount/supabase.sql in a new Supabase project.
-- Do not paste secrets or patient information into this migration.
alter table public.inventory_counts
  add column if not exists operation_id uuid;
create unique index if not exists inventory_counts_operation_id_unique
  on public.inventory_counts(operation_id) where operation_id is not null;

-- The function is deliberately callable only by authenticated users. It performs
-- authorization itself, including for an invited member, then locks the item row.
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
begin
  if auth.uid() is null or not public.pc_can_view(p_session) then
    raise exception 'Inventory access denied' using errcode = '42501';
  end if;
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

revoke all on function public.pc_submit_count(uuid,text,text,uuid,jsonb,text)
  from public, anon;
grant execute on function public.pc_submit_count(uuid,text,text,uuid,jsonb,text)
  to authenticated;

-- Optional: to enable instant pushes in addition to the 20-second fallback,
-- run the statement below ONCE in Supabase SQL editor:
-- alter publication supabase_realtime add table public.inventory_counts;


-- Create a complete inventory session as ONE PostgreSQL transaction. A failed
-- insert of any item rolls back the session itself; no half-created inventory.
create or replace function public.pc_create_session(
  p_name text, p_items jsonb
) returns uuid
language plpgsql security invoker set search_path = ''
as $function$
declare
  new_session uuid := gen_random_uuid();
begin
  if auth.uid() is null then
    raise exception 'Authentication required' using errcode = '42501';
  end if;
  if p_name is null or length(btrim(p_name)) < 3 or length(p_name) > 140 then
    raise exception 'Invalid inventory session title';
  end if;
  if jsonb_typeof(p_items) is distinct from 'array'
     or jsonb_array_length(p_items) < 1
     or jsonb_array_length(p_items) > 20000 then
    raise exception 'Inventory item count out of range';
  end if;
  if exists (
    select 1 from jsonb_array_elements(p_items) as item
    where jsonb_typeof(item) is distinct from 'object'
       or length(coalesce(item->>'id','')) < 1
       or length(coalesce(item->>'id','')) > 200
       or length(coalesce(item->>'name','')) < 1
       or length(coalesce(item->>'code','')) < 1
       or jsonb_typeof(item->'pack') is distinct from 'array'
  ) then
    raise exception 'Invalid item id, name, code or packaging';
  end if;
  if exists (
    select 1 from jsonb_array_elements(p_items) as item
    group by item->>'id' having count(*) > 1
  ) then
    raise exception 'Duplicate item IDs in inventory upload';
  end if;

  insert into public.inventory_sessions(id,name,owner_id)
  values (new_session,btrim(p_name),auth.uid());

  insert into public.inventory_items(session_id,id,drug)
  select new_session,item->>'id',item
  from jsonb_array_elements(p_items) as item;

  return new_session;
end
$function$;

revoke all on function public.pc_create_session(text,jsonb) from public, anon;
grant execute on function public.pc_create_session(text,jsonb) to authenticated;
