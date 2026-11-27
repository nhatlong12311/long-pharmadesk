'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const base=path.resolve(__dirname,'..');
const html=fs.readFileSync(path.join(base,'index.html'),'utf8');
const worker=fs.readFileSync(path.join(base,'pack-worker.js'),'utf8');
const script=[...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)].map(m=>m[1]).find(Boolean);
function slice(a,b){const i=script.indexOf(a),j=script.indexOf(b,i+a.length);assert.ok(i>=0&&j>i,'Missing code section '+a);return script.slice(i,j)}
function parser(){const code=slice('const num=v=>','const latest=i=>')+'\n'+slice('function normalize(s){','function importRows(rows){');const context={XLSX:{SSF:{parse_date_code:()=>({d:30,m:7,y:2027})}}};vm.createContext(context);vm.runInContext(code+'\nthis.exports={parseRows,sum,integer,countQuantity}',context);return context.exports}
test('app and worker script syntax',()=>{assert.doesNotThrow(()=>new vm.Script(script));assert.doesNotThrow(()=>new vm.Script(worker))});
test('hospital XLSX keeps separate lots, null stock and readable expiry',()=>{const a=parser().parseRows([{'Mã dược':'A','Tên thuốc':'Thuốc A','Số lô':'L1','Hạn dùng':46598,'Kệ':'A','ĐVT':'Viên'},{'Mã dược':'A','Tên thuốc':'Thuốc A','Số lô':'L2','Hạn dùng':46598,'Kệ':'A','ĐVT':'Viên'}]);assert.equal(a.length,2);assert.notEqual(a[0].id,a[1].id);assert.equal(a[0].stock,null);assert.equal(a[0].expiry,'30/07/2027')});
test('3 boxes of 100 plus 5 loose units equals 305',()=>{const f=parser();assert.equal(f.sum({pack:[{factor:100},{factor:1}]},[3,5]),305);assert.equal(f.integer('abc'),0)});
test('signed counts subtract loose units and reject fractional input',()=>{
 const {sum,integer,countQuantity}=parser();
 const item={pack:[{factor:10},{factor:1}]};
 assert.equal(sum(item,[2,-3]),17);
 assert.equal(sum(item,[-1,3]),-7);
 assert.equal(countQuantity('-3'),-3);
 assert.ok(Number.isNaN(countQuantity('-1.5')));
 assert.ok(Number.isNaN(countQuantity('')));
 assert.equal(integer(-3),0);
});
test('catalog worker detects ambiguous multiple pack sizes',()=>{const rows=[['STT','MÃ','TÊN DƯỢC, VTYT, HC','','','','','','ĐVT','','QUY CÁCH ĐÓNG GÓI'],[1,'A','Drug A','','','','','','Viên','','Hộp 10 vỉ x 10 viên'],[2,'B','Drug B','','','','','','Viên','','Hộp 3 vỉ x 10 viên, hộp 10 vỉ x 10 viên'],[3,'C','Drug C','','','','','','Lọ','','Hộp 1 lọ'],[4,'X','Other','','','','','','Viên','','Hộp 100 viên']];const messages=[];const ctx={self:{postMessage:m=>messages.push(m)},importScripts:()=>{},XLSX:{read:()=>({SheetNames:['Sheet2'],Sheets:{Sheet2:{'!ref':'A1:K5'}}}),utils:{decode_range:()=>({e:{r:4,c:10}}),sheet_to_json:()=>rows}}};vm.createContext(ctx);vm.runInContext(worker,ctx);ctx.self.onmessage({data:{buffer:new ArrayBuffer(1),codes:['A','B','C']}});const result=messages.find(m=>m.type==='done');assert.ok(result,JSON.stringify(messages));assert.deepEqual(Array.from(result.entries,e=>e.factor),[100,0,1])});
test('catalog worker extracts display data even without a packaging column',()=>{
 const rows=[['MÃ','TÊN DƯỢC, VTYT, HC','Hàm lượng','ĐVT','Hãng sản xuất'],
   ['A-1','Thuốc mẫu','500 mg','Viên','Hãng giả'],['A/1','Thuốc khác','5 mg','Lọ','Hãng khác']];
 const messages=[];
 const ctx={self:{postMessage:message=>messages.push(message)},importScripts:()=>{},
   XLSX:{read:()=>({SheetNames:['Danh mục'],Sheets:{'Danh mục':{'!ref':'A1:E3'}}}),
    utils:{decode_range:()=>({e:{r:2,c:4}}),sheet_to_json:()=>rows}}};
 vm.createContext(ctx);vm.runInContext(worker,ctx);
 ctx.self.onmessage({data:{buffer:new ArrayBuffer(1),codes:['A-1']}});
 const records=messages.find(message=>message.type==='done').entries;
 assert.equal(records.length,1);
 assert.equal(records[0].name,'Thuốc mẫu');
 assert.equal(records[0].strength,'500 mg');
 assert.equal(records[0].unit,'Viên');
 assert.equal(records[0].manufacturer,'Hãng giả');
});

test('older inventory names separate manufacturer, lot and expiry without changing saved fields',()=>{
 const context={};
 vm.createContext(context);
 vm.runInContext(slice('function normalize(s){','function field(o,aliases)')+
   slice('function drugDisplay(item){','const pageTitles=')+
   '\nthis.labels={drugDisplay,drugTitle}',context);
 const {drugDisplay,drugTitle}=context.labels;
 const a={name:'PARTAMOL TAB. 500mg (Công ty Mẫu - Chi nhánh 1, Việt Nam), 680526, 22/05/2031',
   code:'TEST-A',lot:'680526',expiry:'22/05/2031',unit:'Viên'};
 const b={...a,name:a.name.replace('680526, 22/05/2031','760526, 27/05/2031'),lot:'760526',expiry:'27/05/2031'};
 for(const item of [a,b]){
   assert.equal(drugTitle(item),'PARTAMOL TAB. 500mg · Viên');
   assert.equal(drugDisplay(item).manufacturer,'Công ty Mẫu - Chi nhánh 1, Việt Nam');
   assert.ok(item.name.includes(item.lot));
 }
 assert.equal(drugTitle({...a,catalog:{name:'Tên chuẩn 250 mg',strength:'250mg',unit:'Lọ',manufacturer:'Hãng chuẩn'}}),'Tên chuẩn 250 mg · Lọ');
 assert.equal(drugTitle({...a,display:{name:'Tên chuẩn cũ',strength:'5 mg',unit:'Ống'}}),'Tên chuẩn cũ · 5 mg · Ống');
 assert.equal(drugTitle({name:'Thuốc 1 (XR), lô A, 27/05/2031',lot:'lô A',unit:'Viên'}),'Thuốc 1 (XR) · Viên');
});

function cloud(client,counts={}){const ctx={client,user:{email:'tester@example.org'},state:{source:'cloud',sessionId:'test-run',items:[{id:'A'}],counts},fetchCloudCountSnapshot:async(id,item)=>{const {data}=await client.rpc("pc_inventory_count_snapshot",{p_session:id,p_item:item});return data},pendingCountOperation:null,crypto:{randomUUID:()=> 'same-op-id'},selected:0,saves:0,selections:0,save(){ctx.saves++},selectItem(){ctx.selections++}};vm.createContext(ctx);vm.runInContext(slice('function countFromSnapshot(r){','async function fetchCloudRows(')+'\nthis.call=cloudWrite',ctx);return ctx}
test('retry of uncertain write reuses operation ID',async()=>{let n=0;const ops=[];const ctx=cloud({rpc:async(_,args)=>{ops.push(args.p_operation);return ++n===1?{error:{message:'timeout'}}:{data:{status:'saved',version:'5'}}}});await assert.rejects(ctx.call({id:'A'},{values:[3,5],note:'test'}));assert.equal((await ctx.call({id:'A'},{values:[3,5],note:'test'})).version,'5');assert.deepEqual(ops,['same-op-id','same-op-id'])});
test('concurrent save under the same identity loads personal and group counts',async()=>{
 const row={id:7,count_values:[3,4],actual:304,own_values:[2,4],own_note:'mine',own_version:'6'};
 const ctx=cloud({rpc:async(name,input)=>{
  if(name==='pc_inventory_count_snapshot'){assert.equal(input.p_item,'A');return {data:[row]}}
  assert.equal(input.p_expected,'5');
  return {data:{status:'conflict',version:'6'}};
 }},{A:{own:{version:'5'}}});
 await assert.rejects(ctx.call({id:'A'},{values:[3,5],note:'test'}),/tên này vừa được cập nhật/);
 assert.equal(ctx.state.counts.A.actual,304);
 assert.equal(ctx.state.counts.A.own.version,'6');
 assert.deepEqual(ctx.state.counts.A.own.values,[2,4]);
 assert.equal(ctx.selections,1);
});

test('late count acknowledgement is ignored after the user changes runs',async()=>{
 let answer;
 const ctx=cloud({rpc:()=>new Promise(resolve=>{answer=resolve})});
 const pending=ctx.call({id:'A'},{values:[2],note:''});
 ctx.state={source:'cloud',sessionId:'other-run',counts:{}};
 answer({data:{status:'saved',version:'6'}});
 await assert.rejects(pending,/Đợt hoặc phiên đăng nhập đã thay đổi/);
 assert.deepEqual(ctx.state.counts,{});
});

test('actual hospital header with strength is recognized across sheets', async () => {
  const start=script.indexOf("$('importBtn').onclick=async()=>");
  const end=script.indexOf("$('sampleBtn').onclick=",start);
  assert.ok(start>=0&&end>start);
  let imported=null;let alertMessage=null;
  const workbook={
    SheetNames:['TT','UT'],
    Sheets:{TT:{index:0},UT:{index:1}}
  };
  const grids=[
    [['Danh mục'],['STT','Mã dược','Tên thuốc, nồng độ,\nhàm lượng','ĐVT','SỐ LÔ','Hạn dùng','Số lượng'],
      ['','','','','','','Chẵn','Lẻ'],[1,'TH001','Paracetamol 500mg','Viên','A1',46598]],
    [['Danh mục'],['STT','Mã dược','Tên thuốc, nồng độ,\nhàm lượng','ĐVT','SỐ LÔ','Hạn dùng','Số lượng'],
      ['','','','','','','Chẵn','Lẻ'],[1,'TH002','Ceftriaxon 1g','Lọ','A2',46598]]
  ];
  const excelInput={files:[{name:'Dmkk t10.xlsx',arrayBuffer:async()=>new ArrayBuffer(1)}]};
  const elements={excel:excelInput,importBtn:{}};
  const ctx={
    XLSX:{read:()=>workbook,utils:{sheet_to_json:sheet=>grids[sheet.index]}},
    $:id=>elements[id]||(elements[id]={}),
    normalize:s=>String(s??'').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g,'').replace(/đ/g,'d').replace(/[^a-z0-9]+/g,' '),
    importRows:rows=>{imported=rows},
    state:{source:'local'},alert:msg=>{alertMessage=msg}
  };
  vm.createContext(ctx);
  vm.runInContext(script.slice(start,end),ctx);
  await ctx.$('importBtn').onclick();
  assert.equal(alertMessage,null);
  assert.equal(imported.length,2);
  assert.equal(imported[0]['Mã dược'],'TH001');
  assert.equal(imported[1]['Kệ'],'UT');
});
test('cloud submit keeps the version captured when a draft was opened', async()=>{
  let expectedVersion=null;
  const ctx=cloud({rpc:async(name,input)=>{
    if(name==='pc_inventory_count_snapshot')return {data:[]};
    expectedVersion=input.p_expected;
    return {data:{status:'conflict',version:'6'}};
  }},{A:{own:{version:'6'}}});
  await assert.rejects(ctx.call({id:'A'},{values:[3],note:'previous'},'5'),/tên này vừa được cập nhật/);
  assert.equal(expectedVersion,'5');
});
test('latest-count snapshot reads page 2, never uses global ID cursor',async()=>{
  const begin=script.indexOf('async function fetchCloudCountSnapshot(id,itemId=null){');
  const end=script.indexOf('async function refreshCloudCounts(force=false)',begin);
  assert.ok(begin>0&&end>begin);
  const offsets=[];
  const ctx={
    client:{rpc:async(_,input)=>{
      offsets.push(input.p_offset);
      return {data:input.p_offset===0?Array.from({length:500},(_,i)=>({item_id:'T'+i,id:i+1,count_values:[1]})):[{item_id:'T500',id:501,count_values:[2]}]};
    }},
    Error
  };
  vm.createContext(ctx);
  vm.runInContext(script.slice(begin,end)+'\nthis.getCounts=fetchCloudCountSnapshot',ctx);
  const result=await ctx.getCounts('test-session');
  assert.equal(result.length,501);
  assert.deepEqual(offsets,[0,500]);
});

test('forced refresh waits for the background refresh and reads a fresh snapshot',async()=>{
 const start=script.indexOf('async function refreshCloudCounts(force=false)');
 const end=script.indexOf('function handleCloudAccessError(error)',start);
 let release,reads=0;
 const pending=new Promise(resolve=>{release=resolve});
 const ctx={
  client:{},user:{id:'owner'},state:{source:'cloud',sessionId:'session',counts:{},items:[]},selected:0,
  lock:false,cloudRefreshInFlight:null,cloudCountEpoch:0,
  fetchCloudCountSnapshot:async()=>{reads++;return reads===1?pending:[]},
  loadCloudSessionStatus:async()=>{},save:()=>{},renderResults:()=>{},renderStats:()=>{},
  document:{getElementById:()=>({classList:{contains:()=>false}})}
 };
 vm.createContext(ctx);
 vm.runInContext(script.slice(start,end)+'\nthis.refresh=refreshCloudCounts',ctx);
 const background=ctx.refresh();
 const explicit=ctx.refresh(true);
 assert.equal(reads,1);
 release([]);
 assert.equal(await background,true);
 assert.equal(await explicit,true);
 assert.equal(reads,2);
});

test('cloud count cannot silently save locally after authentication expires',async()=>{
  const ctx=cloud(null,{});
  await assert.rejects(ctx.call({id:'A'},{values:[1],note:'test'}),/Phiên đăng nhập đã hết hạn/);
  assert.equal(Object.keys(ctx.state.counts).length,0);
});

test('shared invitation auto-opens only for signed-in invited-session user',()=>{
 const a=script.indexOf('function maybeAutoJoinCloud(){');
 const b=script.indexOf("$('joinCloud').onclick=",a);
 assert.ok(a>=0&&b>a,'auto-join helper missing');
 const called=[];
 const context={
   user:{id:'u1'},joiningCloud:false,
   validJoinFromUrl:'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
   state:{source:'local',sessionId:null},
   joinCloudById:(id,automatic)=>{called.push({id,automatic})}
 };
 vm.createContext(context);
 vm.runInContext(script.slice(a,b)+'\nthis.trigger=maybeAutoJoinCloud',context);
 context.trigger();
 assert.equal(called.length,1);
 assert.equal(called[0].id,'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee');
 assert.equal(called[0].automatic,true);
 context.user=null;
 context.trigger();
 assert.equal(called.length,1);
});
test('guest link action stays visible when sign-in is needed',()=>{
 const controls={};
 const element=id=>controls[id]||(controls[id]={value:'',classList:{toggle(){}}});
 const context={state:{source:'local',items:[{}]},user:null,guestLinkBusy:false,$:element};
 vm.createContext(context);
 vm.runInContext(slice('function renderGuestSharing(){','function resetGuestSharing(){')+'\nthis.refresh=renderGuestSharing',context);
 context.refresh();
 assert.equal(element('copyGuestLink').textContent,'Tạo link kiểm kê');
 assert.equal(element('copyGuestLink').disabled,false);
 assert.match(element('guestLinkHint').textContent,/Đăng nhập email/);
 context.user={id:'owner'};
 context.refresh();
 assert.match(element('guestLinkHint').textContent,/danh mục hiện tại/);
 context.state={source:'cloud',ownerId:'another-owner',items:[{}]};
 context.refresh();
 assert.equal(element('copyGuestLink').disabled,true);
});

test('revoking team access clears locally visible cloud inventory',()=>{
 const a=script.indexOf('function handleCloudAccessError(error){');
 const b=script.indexOf('function startCloudSync()',a);
 assert.ok(a>=0&&b>a,'revoked-access handler missing');
 const elements={membersList:{textContent:'Team',replaceChildren(){this.textContent=''}},cloudId:{value:'test'}};
 const ctx={
   state:{source:'cloud',items:[{id:'A',name:'Drug'}],counts:{A:{values:[3]}}},
   selected:3,draft:{0:'3'},draftVersion:'5',pendingCountOperation:{id:'op'},revealed:true,
   cloudRefreshTimer:null,cloudChannel:null,user:{},newData:()=>({source:'local',items:[],counts:{},sessionId:null}),
   resetGuestSharing:()=>{},save:()=>{},renderCount:()=>{},renderReview:()=>{},showFinalizeControls:()=>{},show:()=>{},
   $:id=>elements[id]||(elements[id]={textContent:''})
 };
 vm.createContext(ctx);
 vm.runInContext(script.slice(a,b)+'\nthis.revoke=handleCloudAccessError',ctx);
 assert.equal(ctx.revoke({code:'42501'}),true);
 assert.equal(ctx.state.items.length,0);
 assert.equal(Object.keys(ctx.state.counts).length,0);
 assert.equal(ctx.draftVersion,null);
 assert.equal(elements.membersList.textContent,'');
 assert.equal(elements.cloudId.value,'');
 assert.equal(ctx.revoke({code:'NETWORK_ERROR'}),false);
 ctx.state={source:'local',items:[{id:'LOCAL',name:'Unsynced'}],counts:{LOCAL:{values:[8]}}};
 assert.equal(ctx.revoke({code:'42501'}),false);
 assert.equal(ctx.state.counts.LOCAL.values[0],8);
});

test('session closing requires ownership and all inventory items counted',async()=>{
 const start=script.indexOf("$('finalizeRun').onclick=async()=>");
 const end=script.indexOf('async function loadTeamMembers(){',start);
 assert.ok(start>=0&&end>start,'finalization control not found');
 const elements={finalizeRun:{disabled:false}};
 let rpcCalls=0,lastAlert='';
 const ctx={
   client:{rpc:async()=>{rpcCalls++;return {data:{status:'finalized',closed_at:'2026-11-23T00:00:00Z'}}}},
   user:{id:'owner'},state:{source:'cloud',ownerId:'other',closedAt:null,sessionId:'session',items:[{id:'A'}],counts:{}},
   $:id=>elements[id]||(elements[id]={}),alert:message=>{lastAlert=message},
   confirm:()=>true,refreshCloudCounts:async()=>true,
   save:()=>{},showFinalizeControls:()=>{},renderStats:()=>{},renderEditor:()=>{}
 };
 vm.createContext(ctx);
 vm.runInContext(script.slice(start,end),ctx);
 await ctx.$('finalizeRun').onclick();
 assert.equal(rpcCalls,0);
 assert.match(lastAlert,/chủ đợt/);
 ctx.state.ownerId='owner';
 await ctx.$('finalizeRun').onclick();
 assert.equal(rpcCalls,0);
 assert.match(lastAlert,/chưa kiểm/);
 ctx.state.counts.A={values:[1]};
 await ctx.$('finalizeRun').onclick();
 assert.equal(rpcCalls,1);
 assert.equal(ctx.state.closedAt,'2026-11-23T00:00:00Z');
 assert.equal(elements.finalizeRun.disabled,false);
});
test('finalized runs block editing and server migration locks parent row',()=>{
 assert.ok(script.includes("if(state.source==='cloud'&&state.closedAt)return alert('Đợt kiểm kê đã chốt"));
 assert.ok(script.includes("button.disabled=lock||!!(state.source==='cloud'&&state.closedAt)"));
 const sql=fs.readFileSync(path.join(base,'supabase-finalization.sql'),'utf8');
 const guard=fs.readFileSync(path.join(base,'supabase-finalization-item-guard.sql'),'utf8');
 assert.match(sql,/pc_finalize_session/);
 assert.match(sql,/for update/i);
 assert.match(sql,/session_closed_at is not null/);
 assert.match(guard,/pc_guard_item_insert/);
 assert.match(guard,/finished_at is not null/);
});

test('finalized XLSX sums latest contributions and retains every audit event',async()=>{
 const a=script.indexOf('async function exportXlsx(){');
 const b=script.indexOf("$('exportBtn').onclick=exportXlsx;",a);
 assert.ok(a>=0&&b>a,'XLSX export handler missing');
 const sheets=[],outputs=[],alerts=[];
 const XLSX={
  utils:{book_new:()=>({}),json_to_sheet:rows=>rows,
   book_append_sheet:(_wb,rows,name)=>sheets.push({name,rows})},
  writeFile:(_wb,name)=>outputs.push(name)
 };
 const records=[
  {id:1,item_id:'A',counter_key:'guest:an',values:[1,0],actual:100,users_email:'a@example.invalid',created_at:'2026-11-23T01:00:00Z',note:''},
  {id:2,item_id:'A',counter_key:'guest:binh',values:[1,5],actual:105,users_email:'b@example.invalid',created_at:'2026-11-23T02:00:00Z',note:'kiểm lại'},
  {id:3,item_id:'B',counter_key:'guest:an',values:[10],actual:10,users_email:'a@example.invalid',created_at:'2026-11-23T02:10:00Z',note:''},
  {id:4,item_id:'C',counter_key:'guest:binh',values:[5],actual:5,users_email:'b@example.invalid',created_at:'2026-11-23T02:20:00Z',note:''},
  {id:5,item_id:'A',counter_key:'guest:an',values:[0,-10],actual:-10,counter_name:'AN',created_at:'2026-11-23T02:25:00Z',note:''}
 ];
 const state={source:'cloud',sessionId:'session',closedAt:'2026-11-23T03:00:00Z',
  items:[{id:'A',name:'Paracetamol',code:'P001',lot:'LOT1',shelf:'A',raw:{},stock:100,
   pack:[{name:'Hộp',factor:100},{name:'Viên',factor:1}]},
   {id:'B',name:'Mặt hàng giả B',raw:{},stock:10,pack:[{name:'Viên',factor:1}]},
   {id:'C',name:'Mặt hàng giả C',raw:{},stock:null,pack:[{name:'Viên',factor:1}]}],
  counts:{A:{values:[1,0],by:'a@example.invalid',checkedAt:'2026-11-23T01:00:00Z',note:''},
   B:{values:[10]},C:{values:[5]}}
 };
 const elems={exportBtn:{}};
 const ctx={XLSX,state,client:{},user:{},drugDisplay:item=>({name:item.name,strength:'',manufacturer:''}),
   refreshCloudCounts:async()=>true,fetchCloudRows:async()=>records,readNxt:()=>null,
   sum:(item,values)=>item.pack.reduce((n,p,i)=>n+values[i]*p.factor,0),
   $:id=>elems[id]||(elems[id]={}),alert:message=>alerts.push(message)};
 vm.createContext(ctx);
 vm.runInContext(script.slice(a,b),ctx);
 await ctx.exportXlsx();
 assert.equal(alerts.length,0);
 assert.deepEqual(sheets.map(x=>x.name),
  ['Tổng hợp','Chi tiết kiểm','Cần kiểm lại','Lịch sử kiểm','Thông tin đợt']);
 assert.deepEqual(Array.from(sheets[2].rows,row=>row['Mã kiểm kê']),['A']);
 assert.equal(sheets[3].rows.length,5);
 assert.equal(sheets[3].rows[1]['Tổng thực kiểm'],105);
 assert.equal(sheets[3].rows[4]['Tổng thực kiểm'],-10);
 assert.equal(sheets[0].rows[0]['Thực kiểm'],95);
 assert.equal(sheets[0].rows[0]['Số lô'],'LOT1');
 assert.ok(outputs[0].includes('CHOT_'));
});

test('NXT reads hospital columns B and M and compares the total across all lots',()=>{
 const nxt=require('../nxt.js');
 const grid=[
  ['Báo cáo nhập xuất tồn'],
  ['', 'STT', 'Mã dược', 'Tên thuốc', 'ĐVT', '', '', '', '', '', '', '', 'S.Lượng', 'Thành tiền'],
  [1, 'A-1', 'Thuốc A', '', 'Viên', '', '', '', '', '', '', '', '1.200', '999999'],
  [2, 'B-1', 'Thuốc B', '', 'Lọ', '', '', '', '', '', '', '', 0, 0]
 ];
 const rows=nxt.read({SheetNames:['Kho'],Sheets:{Kho:{}}},{utils:{sheet_to_json:()=>grid}});
 assert.deepEqual(rows.map(({code,amount})=>[code,amount]),[['a-1',1200],['b-1',0]]);
 const items=[{id:'A1',code:'A-1',lot:'01',unit:'viên'},{id:'A2',code:'A-1',lot:'02',unit:'viên'}];
 const counts={A1:{actual:800}};
 assert.equal(nxt.compare(rows,items,counts)[0].reason,'Chưa kiểm đủ');
 counts.A2={actual:350};
 const [a,b]=nxt.compare(rows,items,counts);
 assert.deepEqual([a.actual,a.delta,a.reason],[1150,-50,'Thiếu']);
 assert.equal(b.reason,'Không tìm thấy mã/lô');
});

test('NXT uses lot headers and flags duplicate scopes and mismatched units',()=>{
 const nxt=require('../nxt.js');
 const grid=[
  ['Mã thuốc','Số lô','ĐVT','Tồn cuối kỳ',''],
  ['','','','Số lượng','Thành tiền'],
  ['A-1','','Viên',15,999],
  ['A-1','L1','Viên',10,999],
  ['B-1','L3','Hộp',5,999],
  ['C-1','L4','Lọ',4,999]
 ];
 const rows=nxt.read({SheetNames:['Kho'],Sheets:{Kho:{}}},{utils:{sheet_to_json:()=>grid}});
 const items=[
  {id:'A',code:'A-1',lot:'L1',unit:'Viên'},
  {id:'B',code:'B-1',lot:'L3',unit:'Viên'},
  {id:'C',code:'C-1',lot:'L4',unit:'Lọ'}
 ];
 const compared=nxt.compare(rows,items,{A:{actual:10},B:{actual:5},C:{actual:4}});
 assert.deepEqual(compared.map(row=>row.reason),[
  'NXT có cả dòng tổng và dòng theo lô','NXT có cả dòng tổng và dòng theo lô','Đơn vị tính khác nhau','Khớp'
 ]);
});

test('adding blisters preserves boxes and signed loose quantities',()=>{
 const context={};
 vm.runInNewContext(slice('function remapQuantities(','function ownCount(')+'\nthis.remap=remapQuantities',context);
 const box={name:'Hộp',factor:30}, loose={name:'Đơn vị lẻ',factor:1}, blister={name:'Vỉ',factor:10};
 const units=[box,loose,blister];
 assert.deepEqual(Array.from(context.remap([box,loose],units,[2,-1],0)),[2,-1,0]);
 assert.deepEqual(Array.from(context.remap([loose],[blister,loose],[-1],0)),[0,-1]);
 assert.equal(parser().sum({pack:units},[2,-1,3]),89);
});

test('Thyrozol shows a ten-tablet blister on import and keeps old box and loose counts',()=>{
 const code=slice('function inferBlisterPack(','function parseRows(');
 const ctx={};
 vm.runInNewContext(code+'\nthis.upgrade=upgradeLocalBlisters',ctx);
 const row={'Mã thuốc':'THMG T201','Tên thuốc':'Thyrozol 5mg','ĐVT':'Viên','Quy cách':'Hộp 10 vỉ x 10 viên','Số đơn vị/hộp':100};
 const [item]=parser().parseRows([row]);
 assert.deepEqual(Array.from(item.pack,p=>p.factor),[100,1,10]);
 item.pack=item.pack.slice(0,2);
 const counts={[item.id]:{values:[2,-3],actual:197}};
 const run={source:'local',items:[item],counts};
 ctx.upgrade(run);ctx.upgrade(run);
 assert.deepEqual(counts[item.id].values,[2,-3,0]);
 assert.equal(parser().sum(item,[2,-3,4]),237);
});

async function confirmWithSnapshot({switchItem=false}={}){
 const elements=new Map();
 const $=id=>{
  if(!elements.has(id))elements.set(id,{value:'',classList:{contains:()=>false}});
  return elements.get(id);
 };
 const item={id:'A',name:'A',pack:[{factor:1}]};
 const calls=[];
 const ctx={$,state:{source:'cloud',sessionId:'run',items:[item],counts:{}},user:{id:'U'},selected:0,
  lock:false,cloudCountEpoch:0,guestDisplayName:'Kim',draft:{0:'3'},draftVersion:null,draftConfirmed:false,
  pendingCountOperation:null,crypto:{randomUUID:()=> 'op'},countQuantity:Number,sum:(_,v)=>v[0],
  client:{rpc:async name=>{
   calls.push(name);
   return {data:{status:'saved',version:'2',snapshot:{item_id:'A',actual:8,count_values:[8],own_values:[3],own_version:'2'}}};
  }},ownCount:()=>ctx.state.counts.A.own,save:()=>{},renderCompare:()=>{},showFinalizeControls:()=>{},
  revealed:false,alert:message=>assert.fail(message)};
 vm.createContext(ctx);
 vm.runInContext(slice('function countFromSnapshot(r){','async function fetchCloudRows(')+
  slice("$('confirm').onclick=async()=>{","$('next').onclick="),ctx);
 const saving=$('confirm').onclick();
 assert.equal($('confirm').textContent,'Đang lưu…');
 if(switchItem){
  ctx.state.items.push({...item,id:'B',name:'B'});
  ctx.selected=1;
  ctx.draft={0:'0'};
 }
 await saving;
 assert.deepEqual(calls,['pc_submit_count']);
 assert.equal(ctx.state.counts.A.actual,8);
 assert.equal(ctx.draftConfirmed,!switchItem);
 if(switchItem)assert.ok(!$('saveState').textContent);
 else assert.match($('saveState').textContent,/Đã ghi nhận A/);
 assert.equal(ctx.lock,false);
}
test('cloud confirmation uses the returned team total without a second read',()=>confirmWithSnapshot());
test('late receipt does not show a success message on another item',()=>confirmWithSnapshot({switchItem:true}));
