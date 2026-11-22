-- Allow only inventory session owners to remove invited users.
-- Use both SELECT and DELETE RLS policies; this grants no delete permission
-- to ordinary members. Sessions without an owner remain inaccessible.
drop policy if exists pc_members_delete on public.inventory_members;
create policy pc_members_delete on public.inventory_members
 for delete to authenticated
 using (public.pc_is_owner(session_id));

grant delete on table public.inventory_members to authenticated;
