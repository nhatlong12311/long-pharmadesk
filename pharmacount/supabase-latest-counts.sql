-- Latest count snapshot per inventory item, robust to transaction commit ordering.
-- Unlike a global BIGSERIAL cursor, this query can never skip a late-committing count.
create index if not exists inventory_counts_latest_by_item_idx
 on public.inventory_counts (session_id,item_id,id desc);

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
 if auth.uid() is null or not public.pc_can_view(p_session) then
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

revoke all on function public.pc_latest_counts(uuid,integer,integer)
 from public,anon;
grant execute on function public.pc_latest_counts(uuid,integer,integer)
 to authenticated;
