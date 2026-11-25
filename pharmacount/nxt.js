'use strict';

const inventoryNxt = (() => {
  const key = value => String(value??'').normalize('NFKC').trim().toLowerCase();
  const title = value => key(value).normalize('NFD').replace(/[\u0300-\u036f]/g,'')
    .replace(/đ/g,'d').replace(/[^a-z0-9]+/g,' ').trim();

  function quantity(value){
    if(typeof value==='number')return Number.isFinite(value)?value:null;
    const text=String(value??'').trim().replace(/\s/g,'');
    if(!text)return null;
    const normalized=/^-?\d{1,3}(\.\d{3})+(,\d+)?$/.test(text)?text.replace(/\./g,'').replace(',','.'):text.replace(',','.');
    return /^-?\d+(\.\d+)?$/.test(normalized)&&Number.isFinite(Number(normalized))?Number(normalized):null;
  }

  function read(book,XLSX){
    const output=[];
    for(const name of book.SheetNames){
      const grid=XLSX.utils.sheet_to_json(book.Sheets[name],{header:1,defval:'',blankrows:false});
      for(let index=0;index<Math.min(35,grid.length);index++){
        const row=grid[index].map(title);
        // The hospital export's printed column labels are shifted relative to its detail rows.
        if(row[1]==='stt'&&row[2]==='ma duoc'&&row[4]==='dvt'&&
           /^(s luong|sl|so luong)$/.test(row[12]??'')&&row[13]==='thanh tien'){
          const details=grid.slice(index+1).flatMap(values=>{
            const serial=quantity(values[0]),code=key(values[1]),amount=quantity(values[12]);
            if(!Number.isInteger(serial)||serial<1||!code||amount===null)return [];
            return [{code,lot:'',unit:title(values[4]),label:values[2]||'',amount}];
          });
          if(details.length)return details;
          continue;
        }
        const code=row.findIndex(v=>/^(ma|ma duoc|ma thuoc|ma hang|ma vat tu|ma san pham|ma vt|ma vt hh|ma hang hoa|ma duoc pham)$/.test(v));
        if(code<0)continue;
        let stock=row.findIndex(v=>/^(ton cuoi ky|ton cuoi|ton kho cuoi ky|cuoi ky|sl ton cuoi ky|sl ton cuoi|so luong ton cuoi ky|so luong ton cuoi|sl cuoi ky|slck|ton kho|ton hien tai|ton)$/.test(v));
        if(stock<0)continue;
        const next=grid[index+1]?.map(title)??[];
        const quantityHeader=v=>/^(sl|so luong|sl ton|luong)$/.test(v);
        let from=index+1;
        if(quantityHeader(next[stock]))from++;
        else if(quantityHeader(next[stock+1])&&!row[stock+1]){stock++;from++;}
        else if(/tien|gia tri/.test(next[stock]??''))continue;
        if(from===index+1&&next.some(quantityHeader)&&!/^sl |^so luong |^slck$/.test(row[stock]))continue;
        const lot=row.findIndex(v=>/^(lo|so lo|lo san xuat|batch|lot)$/.test(v));
        const unit=row.findIndex(v=>/^(dvt|don vi|don vi tinh)$/.test(v));
        const label=row.findIndex(v=>/^ten(?: |$)/.test(v));
        for(const values of grid.slice(from)){
          const codeValue=key(values[code]);
          const amount=quantity(values[stock]);
          if(!codeValue||amount===null||/^(tong|tong cong|cong|total)$/.test(title(codeValue)))continue;
          output.push({code:codeValue,lot:key(values[lot]),unit:title(values[unit]),label:values[label]||'',amount});
        }
        break;
      }
      if(output.length)return output;
    }
    throw Error('Không tìm thấy cột mã dược và số lượng tồn cuối trong file NXT.');
  }

  function compare(rows,items,counts){
    const groups=new Map(), byCode=new Map();
    for(const item of items){
      const code=key(item.code);
      if(!byCode.has(code))byCode.set(code,[]);
      byCode.get(code).push(item);
    }
    for(const row of rows){
      const id=JSON.stringify([row.code,row.lot]);
      if(!groups.has(id))groups.set(id,{...row,id,amount:0,units:new Set()});
      const group=groups.get(id);
      group.amount+=row.amount;
      if(row.unit)group.units.add(row.unit);
    }
    const output=[];
    for(const group of groups.values()){
      const matches=(byCode.get(group.code)??[]).filter(item=>!group.lot||key(item.lot)===group.lot);
      const overlap=group.lot?groups.has(JSON.stringify([group.code,''])):
        matches.some(item=>key(item.lot)&&groups.has(JSON.stringify([group.code,key(item.lot)])));
      const units=new Set(matches.map(item=>title(item.unit)).filter(Boolean));
      const unitMismatch=group.units.size>1||units.size>1||
        (group.units.size===1&&units.size===1&&![...group.units].every(unit=>units.has(unit)));
      const ready=matches.length&&!overlap&&!unitMismatch&&matches.every(item=>Number.isFinite(counts[item.id]?.actual));
      const actual=ready?matches.reduce((total,item)=>total+counts[item.id].actual,0):null;
      const delta=actual===null?null:Number((actual-group.amount).toFixed(9));
      const reason=overlap?'NXT có cả dòng tổng và dòng theo lô':!matches.length?'Không tìm thấy mã/lô':
        unitMismatch?'Đơn vị tính khác nhau':!ready?'Chưa kiểm đủ':delta<0?'Thiếu':delta>0?'Thừa':'Khớp';
      output.push({...group,matches,actual,delta,reason});
    }
    return output;
  }
  return {read,compare};
})();

if(typeof module!=='undefined')module.exports=inventoryNxt;
