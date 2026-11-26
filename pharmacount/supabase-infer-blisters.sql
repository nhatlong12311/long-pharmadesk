-- Populate missing count slots on open legacy rows, keeping every existing slot in place.
do $$
declare
  run_id uuid;
  row_data record;
  captures text[];
  box integer;
  blister integer;
  extra jsonb;
  zeros jsonb;
  changed boolean;
  pattern constant text := '^(?:h[oộ]p\s*)?([1-9][0-9]{0,6})\s*v[ỉi]\s*[x×]\s*([1-9][0-9]{0,6})\s*vi[eê]n$';
begin
  for run_id in select s.id from public.inventory_sessions s where s.closed_at is null
    and exists (select 1 from public.inventory_items i where i.session_id=s.id
      and lower(btrim(i.drug->>'packText')) ~ pattern)
    order by s.id for update
  loop
    changed := false;
    for row_data in select i.id,i.drug->'pack' as pack,
      regexp_match(lower(btrim(i.drug->>'packText')),pattern) as parts
      from public.inventory_items i where i.session_id=run_id
      and lower(btrim(i.drug->>'unit')) in ('viên','vien')
      and lower(btrim(i.drug->>'packText')) ~ pattern for update
    loop
      captures := row_data.parts;
      if captures[1]::bigint*captures[2]::bigint>100000000 then continue; end if;
      blister := captures[2]::integer;
      box := captures[1]::integer*blister;
      extra := jsonb_build_array(jsonb_build_object('name','Vỉ','factor',blister));
      zeros := '[0]'::jsonb;
      if row_data.pack='[{"name":"Đơn vị lẻ","factor":1}]'::jsonb then
        extra := jsonb_build_array(jsonb_build_object('name','Hộp','factor',box)) || extra;
        zeros := '[0,0]'::jsonb;
      elsif row_data.pack is distinct from jsonb_build_array(jsonb_build_object('name','Hộp','factor',box),
        jsonb_build_object('name','Đơn vị lẻ','factor',1)) then continue;
      end if;
      update public.inventory_counts set recorded_values=coalesce(recorded_values,values),
        recorded_actual=coalesce(recorded_actual,actual),values=values || zeros
        where session_id=run_id and item_id=row_data.id;
      update public.inventory_items set drug=jsonb_set(drug,'{pack}',row_data.pack || extra)
        where session_id=run_id and id=row_data.id;
      changed := true;
    end loop;
    if changed then update public.inventory_sessions set pack_revision=gen_random_uuid() where id=run_id; end if;
  end loop;
end $$;
