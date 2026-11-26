-- Apply after supabase-signed-counts.sql.
alter table public.inventory_sessions add column if not exists pack_revision uuid;

alter table public.inventory_counts add column if not exists recorded_values jsonb,
  add column if not exists recorded_actual numeric;

create or replace function pharmacount_private.pc_set_pack_factor(
  p_session uuid,p_item text,p_expected jsonb,p_factor integer
) returns void language plpgsql security definer set search_path = '' as $$
declare
  finished timestamptz;
  drug_row jsonb;
  packs jsonb;
  loose_only boolean;
  combined numeric;
begin
  select closed_at into finished from public.inventory_sessions
    where id=p_session and owner_id=auth.uid() and not pharmacount_private.pc_is_guest()
    for update;
  if not found then raise exception 'Chỉ chủ đợt được sửa quy cách.' using errcode='42501'; end if;
  if finished is not null then raise exception 'Đợt kiểm kê đã chốt.'; end if;
  if p_factor is null or p_factor not between 1 and 100000000 then raise exception 'Hệ số không hợp lệ.'; end if;
  select drug into strict drug_row from public.inventory_items where session_id=p_session and id=p_item for update;
  packs := drug_row->'pack';
  if packs is distinct from p_expected then raise exception 'Quy cách vừa thay đổi. Hãy tải lại dòng thuốc.'; end if;
  loose_only := jsonb_array_length(packs)=1 and packs->0->>'factor'='1';
  if not coalesce(loose_only or (jsonb_array_length(packs)=2 and packs->0->>'name'='Hộp'
      and packs->1->>'factor'='1'),false) then raise exception 'Dòng thuốc có cấu trúc quy cách khác.'; end if;

  -- Keep existing loose units in the loose slot when introducing boxes.
  update public.inventory_counts set
    recorded_values=coalesce(recorded_values,values),
    recorded_actual=coalesce(recorded_actual,actual),
    values=case when loose_only then '[0]'::jsonb || values else values end,
    actual=case when loose_only then (values->>0)::numeric
      else (values->>0)::numeric*p_factor+(values->>1)::numeric end
    where session_id=p_session and item_id=p_item;

  select sum(c.actual) into combined from (
    select distinct on (counter_key) actual from public.inventory_counts
    where session_id=p_session and item_id=p_item order by counter_key,id desc
  ) c;
  if abs(combined)>9007199254740991 then raise exception 'Tổng thực kiểm vượt giới hạn.'; end if;

  packs := jsonb_build_array(jsonb_build_object('name','Hộp','factor',p_factor),
    case when loose_only then packs->0 else packs->1 end);
  update public.inventory_items set drug=drug_row || jsonb_build_object('pack',packs,
    'packText','1 hộp = ' || p_factor || ' ' || coalesce(drug_row->>'unit','đơn vị'))
    where session_id=p_session and id=p_item;
  update public.inventory_sessions set pack_revision=gen_random_uuid() where id=p_session;
end;
$$;

create or replace function public.pc_set_pack_factor(p_session uuid,p_item text,p_expected jsonb,p_factor integer)
returns void language sql security invoker set search_path = '' as $$
  select pharmacount_private.pc_set_pack_factor(p_session,p_item,p_expected,p_factor);
$$;
revoke all on function public.pc_set_pack_factor(uuid,text,jsonb,integer),
  pharmacount_private.pc_set_pack_factor(uuid,text,jsonb,integer) from public,anon;
grant execute on function public.pc_set_pack_factor(uuid,text,jsonb,integer),
  pharmacount_private.pc_set_pack_factor(uuid,text,jsonb,integer) to authenticated;
