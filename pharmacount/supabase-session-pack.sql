-- Internal row update, called only after the session and scope have been checked.
create function pharmacount_private.pc_apply_count_unit(p_session uuid,p_item text,drug_row jsonb,p_name text,p_factor integer)
returns void language plpgsql security invoker set search_path = '' as $$
declare
  packs jsonb := drug_row->'pack';
  position integer;
  old_factor numeric;
  description text;
  combined numeric;
begin
  select ordinality::integer-1,(entry->>'factor')::numeric into position,old_factor
    from jsonb_array_elements(packs) with ordinality as p(entry,ordinality)
    where entry->>'name'=p_name;
  if position is null and jsonb_array_length(packs)>=20 then raise exception 'Đã đạt giới hạn đơn vị đếm.'; end if;

  -- The original two-field client moves a lone loose quantity to slot 1.
  -- For larger layouts append the new slot to preserve existing indexes.
  if position is null then
    if jsonb_array_length(packs)=1 and packs->0->>'name'='Đơn vị lẻ' then
      packs := jsonb_build_array(jsonb_build_object('name',p_name,'factor',p_factor)) || packs;
      position := 0;
    else
      position := jsonb_array_length(packs);
      packs := packs || jsonb_build_array(jsonb_build_object('name',p_name,'factor',p_factor));
    end if;
  else
    packs := jsonb_set(packs,array[position::text,'factor'],to_jsonb(p_factor));
  end if;

  update public.inventory_counts set
    recorded_values=coalesce(recorded_values,values),
    recorded_actual=coalesce(recorded_actual,actual),
    values=case when old_factor is not null then values
      when position=0 then '[0]'::jsonb || values else values || '[0]'::jsonb end,
    actual=case when old_factor is null then actual
      else actual+(values->>position)::numeric*(p_factor-old_factor) end
    where session_id=p_session and item_id=p_item;

  select sum(c.actual) into combined from (
    select distinct on (counter_key) actual from public.inventory_counts
    where session_id=p_session and item_id=p_item order by counter_key,id desc
  ) c;
  if abs(combined)>9007199254740991 then raise exception 'Tổng thực kiểm vượt giới hạn.'; end if;

  select string_agg('1 ' || lower(p->>'name') || ' = ' || (p->>'factor') || ' ' ||
    coalesce(drug_row->>'unit','đơn vị'), ' · ' order by ordinality) into description
    from jsonb_array_elements(packs) with ordinality as units(p,ordinality)
    where p->>'name' in ('Hộp','Vỉ');
  update public.inventory_items set drug=drug_row || jsonb_build_object('pack',packs,'packText',description)
    where session_id=p_session and id=p_item;
end;
$$;
revoke all on function pharmacount_private.pc_apply_count_unit(uuid,text,jsonb,text,integer) from public,anon,authenticated;

create or replace function pharmacount_private.pc_edit_count_unit(
  p_session uuid,p_item text,p_expected jsonb,p_name text,p_factor integer
) returns void language plpgsql security definer set search_path = '' as $$
declare
  finished timestamptz;
  selected_drug jsonb;
  code text;
  target record;
begin
  if auth.uid() is null or not pharmacount_private.pc_can_view(p_session) then
    raise exception 'Không có quyền trong đợt kiểm kê.' using errcode='42501';
  end if;
  select closed_at into strict finished from public.inventory_sessions where id=p_session for update;
  if not pharmacount_private.pc_can_view(p_session) then
    raise exception 'Quyền tham gia đã hết hiệu lực.' using errcode='42501';
  end if;
  if finished is not null then raise exception 'Đợt kiểm kê đã chốt.'; end if;
  if p_name is null or p_name not in ('Hộp','Vỉ') or p_factor is null or p_factor not between 1 and 100000000 then
    raise exception 'Quy cách không hợp lệ.';
  end if;
  select drug into strict selected_drug from public.inventory_items where session_id=p_session and id=p_item;
  if selected_drug->'pack' is distinct from p_expected then raise exception 'Quy cách vừa thay đổi. Hãy tải lại dòng thuốc.'; end if;
  code := nullif(lower(btrim(selected_drug->>'code')),'');
  for target in select id,drug from public.inventory_items where session_id=p_session
    and (id=p_item or lower(btrim(drug->>'code'))=code) order by id for update
  loop
    if lower(btrim(target.drug->>'unit')) is distinct from lower(btrim(selected_drug->>'unit')) then
      raise exception 'Các lô cùng mã có đơn vị tính khác nhau. Hãy kiểm tra lại danh mục.';
    end if;
    perform pharmacount_private.pc_apply_count_unit(p_session,target.id,target.drug,p_name,p_factor);
  end loop;
  update public.inventory_sessions set pack_revision=gen_random_uuid() where id=p_session;
end;
$$;

-- Route the original box-only RPC through the same authorization and lot scope.
create or replace function pharmacount_private.pc_set_pack_factor(p_session uuid,p_item text,p_expected jsonb,p_factor integer)
returns void language sql security invoker set search_path = '' as $$
  select pharmacount_private.pc_edit_count_unit(p_session,p_item,p_expected,'Hộp',p_factor);
$$;
