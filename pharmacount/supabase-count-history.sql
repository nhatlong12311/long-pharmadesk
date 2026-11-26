-- Count events already exist. Keep the unit labels and factors used for future entries.
alter table public.inventory_counts add column entry_pack jsonb;

create function pharmacount_private.pc_capture_entry_pack()
returns trigger language plpgsql security invoker set search_path='' as $$
begin
  select i.drug->'pack' into strict new.entry_pack from public.inventory_items i
    where i.session_id=new.session_id and i.id=new.item_id;
  return new;
end;
$$;
revoke all on function pharmacount_private.pc_capture_entry_pack() from public,anon,authenticated;
create trigger pc_capture_entry_pack before insert on public.inventory_counts
for each row execute function pharmacount_private.pc_capture_entry_pack();

create function pharmacount_private.pc_count_history(p_session uuid,p_before bigint)
returns table(event_id text,item_id text,entered_at timestamptz,person text,quantities jsonb,pack jsonb,
  actual numeric,note text,updated boolean)
language plpgsql stable security definer set search_path='' as $$
declare guest boolean := pharmacount_private.pc_is_guest();
begin
  if auth.uid() is null or not pharmacount_private.pc_can_view(p_session) then
    raise exception 'Không có quyền xem đợt kiểm kê.' using errcode='42501';
  end if;
  return query
    select c.id::text,c.item_id,c.created_at,coalesce(c.counter_name,nullif(c.users_email,''),'Thành viên'),
      coalesce(c.recorded_values,c.values),c.entry_pack,coalesce(c.recorded_actual,c.actual),c.note,
      exists(select 1 from public.inventory_counts old where old.session_id=c.session_id
        and old.item_id=c.item_id and old.counter_key=c.counter_key and old.id<c.id)
    from public.inventory_counts c where c.session_id=p_session
      and (not guest or c.user_id=auth.uid())
      and (p_before is null or c.id<p_before)
    order by c.id desc limit 50;
end;
$$;

create function public.pc_count_history(p_session uuid,p_before bigint default null)
returns table(event_id text,item_id text,entered_at timestamptz,person text,quantities jsonb,pack jsonb,
  actual numeric,note text,updated boolean)
language sql stable security invoker set search_path='' as $$
  select * from pharmacount_private.pc_count_history(p_session,p_before);
$$;
revoke all on function public.pc_count_history(uuid,bigint),
  pharmacount_private.pc_count_history(uuid,bigint) from public,anon;
grant execute on function public.pc_count_history(uuid,bigint),
  pharmacount_private.pc_count_history(uuid,bigint) to authenticated;
