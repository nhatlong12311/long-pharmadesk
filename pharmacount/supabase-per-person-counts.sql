-- Apply after supabase-guest-links.sql. Existing count history is retained.
create function pharmacount_private.pc_counter_key(p_user uuid,p_name text)
returns text language sql immutable set search_path = ''
as $$
  select case when p_name is null then 'account:' || p_user::text
    else 'guest:' || lower(normalize(trim(regexp_replace(p_name,'[[:space:]]+',' ','g')))) end;
$$;
revoke all on function pharmacount_private.pc_counter_key(uuid,text) from public, anon, authenticated;

alter table public.inventory_counts add column counter_key text generated always as
  (pharmacount_private.pc_counter_key(user_id,counter_name)) stored;

create index inventory_counts_latest_per_person
  on public.inventory_counts(session_id,item_id,counter_key,id desc);

create function pharmacount_private.pc_inventory_count_snapshot(
  p_session uuid,p_offset integer,p_limit integer,p_item text
)
returns table (
  id bigint,item_id text,count_values jsonb,note text,actual numeric,
  created_at timestamptz,users_email text,own_version text,own_values jsonb,own_note text
)
language plpgsql stable security definer set search_path = ''
as $$
declare
  guest boolean := (select pharmacount_private.pc_is_guest());
  own_key text;
begin
  if not pharmacount_private.pc_can_view(p_session) then
    raise exception 'Inventory access denied' using errcode='42501';
  end if;
  if p_offset is null or p_offset not between 0 and 100000 or p_limit is null or p_limit not between 1 and 750 then
    raise exception 'Invalid inventory snapshot pagination';
  end if;
  own_key := pharmacount_private.pc_counter_key(auth.uid(),
    case when guest then pharmacount_private.pc_guest_name(p_session) end);
  return query
    with page as (
      select distinct c.item_id from public.inventory_counts c
      where c.session_id=p_session and (p_item is null or c.item_id=p_item)
      order by c.item_id limit p_limit offset p_offset
    ), contributions as (
      select distinct on (c.item_id,c.counter_key) c.*
      from public.inventory_counts c join page p on p.item_id=c.item_id
      where c.session_id=p_session
      order by c.item_id,c.counter_key,c.id desc
    ), totals as (
      select c.item_id,sum(c.actual) as actual,count(*) as people
      from contributions c group by c.item_id
    ), pack_sums as (
      select c.item_id,v.position,sum(v.quantity::numeric) as quantity
      from contributions c cross join lateral jsonb_array_elements_text(c.values)
        with ordinality as v(quantity,position)
      group by c.item_id,v.position
    ), packs as (
      select v.item_id,jsonb_agg(v.quantity order by v.position) as quantities
      from pack_sums v group by v.item_id
    ), last_count as (
      select distinct on (c.item_id) c.* from contributions c order by c.item_id,c.id desc
    )
    select last_count.id,t.item_id,p.quantities,
      case when t.people=1 then last_count.note else '' end,t.actual,last_count.created_at,
      case when t.people>1 then t.people::text || ' người'
        else coalesce(last_count.counter_name,case when guest then 'Thành viên' else last_count.users_email end) end,
      own.id::text,own.values,own.note
    from totals t join packs p on p.item_id=t.item_id
    join last_count on last_count.item_id=t.item_id
    left join contributions own on own.item_id=t.item_id and own.counter_key=own_key
    order by t.item_id;
end;
$$;

create function public.pc_inventory_count_snapshot(
  p_session uuid,p_offset integer default 0,p_limit integer default 500,p_item text default null
)
returns table (
  id bigint,item_id text,count_values jsonb,note text,actual numeric,
  created_at timestamptz,users_email text,own_version text,own_values jsonb,own_note text
)
language sql stable security invoker set search_path = ''
as $$ select * from pharmacount_private.pc_inventory_count_snapshot(p_session,p_offset,p_limit,p_item); $$;

revoke all on function pharmacount_private.pc_inventory_count_snapshot(uuid,integer,integer,text),
  public.pc_inventory_count_snapshot(uuid,integer,integer,text) from public, anon;
grant execute on function pharmacount_private.pc_inventory_count_snapshot(uuid,integer,integer,text),
  public.pc_inventory_count_snapshot(uuid,integer,integer,text) to authenticated;

create or replace function pharmacount_private.pc_latest_counts(p_session uuid,p_offset integer,p_limit integer)
returns table (id bigint,item_id text,count_values jsonb,note text,actual numeric,
  created_at timestamptz,users_email text)
language sql stable security definer set search_path = ''
as $$
  select r.id,r.item_id,r.count_values,r.note,r.actual,r.created_at,r.users_email
  from pharmacount_private.pc_inventory_count_snapshot(p_session,p_offset,p_limit,null) r;
$$;

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
  other_total numeric;
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

  select coalesce(sum(c.actual),0) into other_total from (
    select distinct on (counter_key) actual from public.inventory_counts
    where session_id=p_session and item_id=p_item and counter_key<>own_key
    order by counter_key,id desc
  ) c;
  if total + other_total > 9007199254740991 then
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

