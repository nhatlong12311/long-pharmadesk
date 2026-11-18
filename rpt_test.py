"""test: negate BEFORE quantity and reuse the normal requisition merge."""
import os
import re
import shutil
import subprocess
import tempfile
import threading
import uuid
import runpy
from pathlib import Path
from flask import Blueprint, jsonify, request, send_file, render_template_string

ROOT = DATA = None
LOCK = threading.Lock()

def init(root, data):
    global ROOT, DATA
    ROOT, DATA = Path(root), Path(data)
    DATA.mkdir(parents=True, exist_ok=True)

def merge_test(folder, output, before_name, after_name, khoa=""):
    state = runpy.run_path(str(ROOT / 'Gop_va_sort_AZ.py'), init_globals={'MERGE_JOB': {
        'test': True, 'mode': 'khoa', 'root': ROOT,
        'source_dir': folder / 'Excel_xuat', 'log_dir': folder / 'Logs',
        'output': output, 'before_name': before_name, 'after_name': after_name, 'khoa': khoa,
    }})
    return state['records']

def convert_rpt(files, folder):
    if os.name != 'nt': raise ValueError('Chuyển RPT cần chạy trên Windows có Crystal Reports 10 như chức năng tổng hợp hiện tại.')
    (folder/'RPT').mkdir()
    for key,upload in files.items(): upload.save(folder/'RPT'/f'{key}.rpt')
    script=folder/'Xuat_RPT_sang_XLS.vbs'
    shutil.copy2(ROOT/script.name,script)
    cs=Path(os.environ.get('SystemRoot',r'C:\Windows'))/'SysWOW64'/'cscript.exe'
    p=subprocess.run([str(cs) if cs.exists() else 'cscript','//nologo',str(script)],cwd=folder,
                     capture_output=True,timeout=180,creationflags=0x08000000)
    if p.returncode:
        raise ValueError('Không xuất được hai RPT. Kiểm tra Crystal Reports và dữ liệu đã lưu trong phiếu.\n'+(p.stdout+p.stderr).decode('utf-8','replace'))
    paths={k:folder/'Excel_xuat'/f'{k}.xls' for k in files}
    if not all(p.is_file() for p in paths.values()): raise ValueError('Thiếu file Excel sau khi chuyển RPT.')
    return paths

PRINT_TEMPLATE = """<!doctype html><html lang="vi"><meta charset="utf-8"><title>Trừ tổng</title>
<style>body{font:14px 'Times New Roman';margin:24px}table{border-collapse:collapse;width:100%}th,td{border:1px solid #888;padding:7px}thead{display:table-header-group}tr{break-inside:avoid}@page{size:A4;margin:12mm}@media print{button{display:none}}</style>
<button onclick="window.print()">In kết quả</button><h2>{{title}}</h2>

<table><thead><tr><th>Nhóm</th><th>Mã</th><th>Tên thuốc</th><th>Thực xuất</th><th>ĐVT</th><th>Đơn giá</th></tr></thead><tbody>
{% for r in rows %}<tr><td>{{r.group}}</td><td>{{r.code}}</td><td>{{r.name}}</td><td>{{'%g'|format(r.qty)}}</td><td>{{r.unit or ''}}</td><td>{{'%g'|format(r.price)}}</td></tr>{% else %}<tr><td colspan="6">Không có chênh lệch.</td></tr>{% endfor %}</tbody></table></html>"""

def make_blueprint():
    bp=Blueprint('rpt_test',__name__)
    @bp.post('/api/test/compare')
    def compare():
        if not LOCK.acquire(blocking=False): return jsonify(ok=False,msg='Đang tổng hợp, vui lòng chờ.')
        try:
            files={k:request.files.get(k) for k in ('before','after')}
            if not all(files.values()): raise ValueError('Chọn đủ file trước và file sau.')
            if any(Path(f.filename).suffix.lower()!='.rpt' for f in files.values()): raise ValueError('Chỉ nhận file .rpt.')
            before,after=(files[k].filename.replace('\\','/').split('/')[-1] for k in ('before','after'))
            token=uuid.uuid4().hex
            with tempfile.TemporaryDirectory(prefix='pharmadesk_test_') as tmp:
                folder=Path(tmp)
                paths=convert_rpt(files,folder)
                try:
                    rows=merge_test(folder,folder/'test.xlsx',before,after,request.form.get('khoa','').strip())
                    from openpyxl import load_workbook
                    wb=load_workbook(folder/'test.xlsx',read_only=True,data_only=True)
                    title=wb['In']['A1'].value
                    wb.close()
                    shutil.copy2(folder/'test.xlsx',DATA/(token+'.xlsx'))
                except Exception as e:
                    for key, source in paths.items():
                        shutil.copy2(source,DATA/(token+'_'+key+'.xls'))
                    return jsonify(ok=False,msg=str(e),diagnostic_token=token)
            html=render_template_string(PRINT_TEMPLATE,rows=rows,title=title)
            (DATA/(token+'.html')).write_text(html,encoding='utf-8')
            return jsonify(ok=True,rows=rows,token=token)
        except subprocess.TimeoutExpired: return jsonify(ok=False,msg='Chuyển RPT quá 180 giây. Kiểm tra phiếu trong Crystal Reports rồi thử lại.')
        except Exception as e: return jsonify(ok=False,msg=str(e))
        finally: LOCK.release()
    @bp.post('/api/test/<token>/open')
    def open_excel(token):
        if not re.fullmatch('[a-f0-9]{32}', token):
            return jsonify(ok=False, msg='Kết quả không hợp lệ.'), 400
        path = DATA / (token + '.xlsx')
        if not path.is_file():
            return jsonify(ok=False, msg='Chưa có file kết quả. Hãy tổng hợp lại.')
        if os.name != 'nt':
            return jsonify(ok=False, msg='Chỉ mở trực tiếp bằng Excel trên Windows. Bạn có thể bấm Tải Excel Trừ tổng.')
        try:
            os.startfile(str(path))
            return jsonify(ok=True)
        except OSError as e:
            return jsonify(ok=False, msg='Không mở được Excel. Kiểm tra ứng dụng mở file .xlsx hoặc tải file về. ' + str(e))

    @bp.get('/api/test/<token>/<kind>')
    def output(token,kind):
        if not re.fullmatch('[a-f0-9]{32}',token) or kind not in ('print','excel','before','after'): return 'Không tìm thấy',404
        if kind in ('before','after'):
            path=DATA/(token+'_'+kind+'.xls')
            if not path.is_file(): return 'Không tìm thấy',404
            return send_file(path,as_attachment=True,download_name=kind+'.xls')
        path=DATA/(token+('.html' if kind=='print' else '.xlsx'))
        if not path.is_file(): return 'Không tìm thấy',404
        return send_file(path,as_attachment=kind=='excel',download_name='Tru_tong.xlsx' if kind=='excel' else 'Tru_tong.html')
    return bp
