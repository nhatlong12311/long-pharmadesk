'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const base=path.resolve(__dirname,'..');
const html=fs.readFileSync(path.join(base,'index.html'),'utf8');
const worker=fs.readFileSync(path.join(base,'pack-worker.js'),'utf8');
const script=[...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)].map(m=>m[1]).find(Boolean);
function slice(a,b){const i=script.indexOf(a),j=script.indexOf(b,i+a.length);assert.ok(i>=0&&j>i,'Missing code section '+a);return script.slice(i,j)}
function parser(){const code=slice('const num=v=>','const latest=i=>')+'\n'+slice('function normalize(s){','function importRows(rows){');const context={XLSX:{SSF:{parse_date_code:()=>({d:30,m:7,y:2027})}}};vm.createContext(context);vm.runInContext(code+'\nthis.exports={parseRows,sum,integer}',context);return context.exports}
test('app and worker script syntax',()=>{assert.doesNotThrow(()=>new vm.Script(script));assert.doesNotThrow(()=>new vm.Script(worker))});
test('hospital XLSX keeps separate lots, null stock and readable expiry',()=>{const a=parser().parseRows([{'Mã dược':'A','Tên thuốc':'Thuốc A','Số lô':'L1','Hạn dùng':46598,'Kệ':'A','ĐVT':'Viên'},{'Mã dược':'A','Tên thuốc':'Thuốc A','Số lô':'L2','Hạn dùng':46598,'Kệ':'A','ĐVT':'Viên'}]);assert.equal(a.length,2);assert.notEqual(a[0].id,a[1].id);assert.equal(a[0].stock,null);assert.equal(a[0].expiry,'30/07/2027')});
test('3 boxes of 100 plus 5 loose units equals 305',()=>{const f=parser();assert.equal(f.sum({pack:[{factor:100},{factor:1}]},[3,5]),305);assert.equal(f.integer('abc'),0)});
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

function cloud(client,counts={}){const ctx={client,user:{email:'tester@example.org'},state:{source:'cloud',sessionId:'test-run',items:[{id:'A'}],counts},pendingCountOperation:null,crypto:{randomUUID:()=> 'same-op-id'},selected:0,saves:0,selections:0,save(){ctx.saves++},selectItem(){ctx.selections++}};vm.createContext(ctx);vm.runInContext(slice('async function cloudWrite(x,record,expectedDraftVersion){','async function fetchCloudRows(')+'\nthis.call=cloudWrite',ctx);return ctx}
test('retry of uncertain write reuses operation ID',async()=>{let n=0;const ops=[];const ctx=cloud({rpc:async(_,args)=>{ops.push(args.p_operation);return ++n===1?{error:{message:'timeout'}}:{data:{status:'saved',version:'5'}}}});await assert.rejects(ctx.call({id:'A'},{values:[3,5],note:'test'}));assert.equal(await ctx.call({id:'A'},{values:[3,5],note:'test'}),'5');assert.deepEqual(ops,['same-op-id','same-op-id'])});
test('conflicting concurrent save loads latest teammate result',async()=>{const row={id:6,values:[2,4],note:'teammate',actual:204,users_email:'other@example.org',created_at:'2026-11-23T10:00:00Z'};const query={select(){return this},eq(){return this},order(){return this},limit(){return this},async maybeSingle(){return {data:row}}};const ctx=cloud({rpc:async()=>({data:{status:'conflict',version:'6'}}),from:()=>query},{A:{version:'5'}});await assert.rejects(ctx.call({id:'A'},{values:[3,5],note:'test'}),/Người khác vừa lưu/);assert.equal(ctx.state.counts.A.version,'6');assert.equal(ctx.selections,1)});

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
  const ctx=cloud({rpc:async(_,input)=>{
    expectedVersion=input.p_expected;
    return {data:{status:'conflict',version:'6'}};
  },from:()=>({
    select(){return this},eq(){return this},order(){return this},limit(){return this},
    async maybeSingle(){return {data:{id:6,values:[2],note:'new',actual:2,users_email:'other@example.org',created_at:'2026-11-23T10:00:00Z'}}}
  })},{A:{version:'6'}});
  await assert.rejects(ctx.call({id:'A'},{values:[3],note:'previous'},'5'),/Người khác vừa lưu/);
  assert.equal(expectedVersion,'5');
});
test('latest-count snapshot reads page 2, never uses global ID cursor',async()=>{
  const begin=script.indexOf('async function fetchCloudCountSnapshot(id){');
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
  client:{},user:{id:'owner'},state:{source:'cloud',sessionId:'session',counts:{}},
  lock:false,cloudRefreshInFlight:null,
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
test('revoking team access clears locally visible cloud inventory',()=>{
 const a=script.indexOf('function handleCloudAccessError(error){');
 const b=script.indexOf('function startCloudSync()',a);
 assert.ok(a>=0&&b>a,'revoked-access handler missing');
 const elements={membersList:{textContent:'Team',replaceChildren(){this.textContent=''}},cloudId:{value:'test'}};
 const ctx={
   state:{source:'cloud',items:[{id:'A',name:'Drug'}],counts:{A:{values:[3]}}},
   selected:3,draft:{0:'3'},draftVersion:'5',pendingCountOperation:{id:'op'},revealed:true,
   cloudRefreshTimer:null,cloudChannel:null,user:{},newData:()=>({source:'local',items:[],counts:{},sessionId:null}),
   save:()=>{},renderCount:()=>{},renderReview:()=>{},showFinalizeControls:()=>{},show:()=>{},
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
 assert.ok(script.includes("$('confirm').disabled=lock||!!(state.source==='cloud'&&state.closedAt)"));
 const sql=fs.readFileSync(path.join(base,'supabase-finalization.sql'),'utf8');
 const guard=fs.readFileSync(path.join(base,'supabase-finalization-item-guard.sql'),'utf8');
 assert.match(sql,/pc_finalize_session/);
 assert.match(sql,/for update/i);
 assert.match(sql,/session_closed_at is not null/);
 assert.match(guard,/pc_guard_item_insert/);
 assert.match(guard,/finished_at is not null/);
});

test('finalized XLSX export includes every audit event and clear finalized marker',async()=>{
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
  {id:1,item_id:'A',values:[1,0],actual:100,users_email:'a@example.invalid',created_at:'2026-11-23T01:00:00Z',note:''},
  {id:2,item_id:'A',values:[1,5],actual:105,users_email:'b@example.invalid',created_at:'2026-11-23T02:00:00Z',note:'kiểm lại'},
  {id:3,item_id:'B',values:[10],actual:10,users_email:'a@example.invalid',created_at:'2026-11-23T02:10:00Z',note:''},
  {id:4,item_id:'C',values:[5],actual:5,users_email:'b@example.invalid',created_at:'2026-11-23T02:20:00Z',note:''}
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
 const ctx={XLSX,state,client:{},user:{},drugManufacturer:item=>item.catalog?.manufacturer||item.manufacturer||'',
   refreshCloudCounts:async()=>true,fetchCloudRows:async()=>records,
   sum:(item,values)=>item.pack.reduce((n,p,i)=>n+values[i]*p.factor,0),
   $:id=>elems[id]||(elems[id]={}),alert:message=>alerts.push(message)};
 vm.createContext(ctx);
 vm.runInContext(script.slice(a,b),ctx);
 await ctx.exportXlsx();
 assert.equal(alerts.length,0);
 assert.deepEqual(sheets.map(x=>x.name),
  ['Tổng hợp','Chi tiết kiểm','Cần kiểm lại','Lịch sử kiểm','Thông tin đợt']);
 assert.deepEqual(Array.from(sheets[2].rows,row=>row['Mã kiểm kê']),['A']);
 assert.equal(sheets[3].rows.length,4);
 assert.equal(sheets[3].rows[1]['Tổng thực kiểm'],105);
 assert.equal(sheets[0].rows[0]['Thực kiểm'],105);
 assert.equal(sheets[0].rows[0]['Số lô'],'LOT1');
 assert.ok(outputs[0].includes('CHOT_'));
});
