-- Include the committed operation's current item totals in the save response.
-- Existing clients continue to read status and version.
create or replace function public.pc_submit_count(
  p_session uuid,p_item text,p_expected text,p_operation uuid,p_values jsonb,p_note text
) returns jsonb language plpgsql security invoker set search_path='' as $$
declare
  receipt jsonb;
  snapshot jsonb;
begin
  receipt := pharmacount_private.pc_submit_count(p_session,p_item,p_expected,p_operation,p_values,p_note);
  if receipt->>'status' in ('saved','conflict') then
    select to_jsonb(r) into snapshot
      from pharmacount_private.pc_inventory_count_snapshot(p_session,0,1,p_item) r;
    return receipt || jsonb_build_object('snapshot',snapshot);
  end if;
  return receipt;
end;
$$;
