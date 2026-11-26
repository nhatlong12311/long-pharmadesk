-- Apply after supabase-per-person-counts.sql in a single transaction.
alter table public.inventory_counts
  drop constraint valid_actual,
  add constraint valid_actual check (actual between -9007199254740991 and 9007199254740991);

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
  own_key text;
  combined_total numeric;
  largest_pack_count numeric;
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
  own_key := pharmacount_private.pc_counter_key(auth.uid(),
    case when pharmacount_private.pc_is_guest() then pharmacount_private.pc_guest_name(p_session) end);
  select * into previous
  from public.inventory_counts
  where session_id=p_session and item_id=p_item and counter_key=own_key
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
    if jsonb_typeof(q)<>'number' or q::text !~ '^-?[0-9]+$'
       or abs(q::text::numeric) > 9007199254740991 then
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
  if abs(total) > 9007199254740991 then
    raise exception 'Count total out of range';
  end if;

  -- Validate the exact projection before sending totals and pack counts to JavaScript.
  with latest_others as (
    select distinct on (counter_key) actual,values from public.inventory_counts
    where session_id=p_session and item_id=p_item and counter_key<>own_key
    order by counter_key,id desc
  ), current_counts as (
    select c.actual,c.values from latest_others c
    union all select total,p_values
  ), pack_totals as (
    select sum(v.quantity::numeric) as quantity
    from current_counts c cross join lateral jsonb_array_elements_text(c.values)
      with ordinality as v(quantity,position)
    group by v.position
  )
  select (select sum(c.actual) from current_counts c),max(abs(p.quantity))
  into combined_total,largest_pack_count from pack_totals p;

  if abs(combined_total) > 9007199254740991 or largest_pack_count > 9007199254740991 then
    raise exception 'Combined count total out of range';
  end if;

  insert into public.inventory_counts
    (session_id,item_id,user_id,values,actual,note,operation_id)
  values
    (p_session,p_item,auth.uid(),p_values,total,coalesce(p_note,''),p_operation)
  returning * into previous;

  return jsonb_build_object('status','saved','version',previous.id::text);
end
$function$;
