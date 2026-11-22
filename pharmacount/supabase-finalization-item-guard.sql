-- Prevent inserting new items into a finalized stocktake, including if
-- a concurrent close transaction commits at the same time.
create or replace function public.pc_guard_item_insert()
returns trigger language plpgsql security invoker set search_path = ''
as $$
declare finished_at timestamptz;
begin
 select closed_at into finished_at
 from public.inventory_sessions where id=new.session_id for update;
 if not found then
  raise exception 'Inventory session not found';
 end if;
 if finished_at is not null then
  raise exception 'Inventory session is finalized';
 end if;
 return new;
end;
$$;
drop trigger if exists pc_item_insert_guard on public.inventory_items;
create trigger pc_item_insert_guard before insert on public.inventory_items
 for each row execute function public.pc_guard_item_insert();

drop policy if exists pc_items_create on public.inventory_items;
create policy pc_items_create on public.inventory_items
 for insert to authenticated
 with check (
  public.pc_is_owner(session_id)
  and exists (
   select 1 from public.inventory_sessions s
   where s.id=session_id and s.closed_at is null
  )
 );
