LONG — WEBSITE CÁ NHÂN + PHARMADESK 3.0
========================================

1. Cài Python 3.11 hoặc 3.12 từ python.org trên Windows (tick "Add Python to PATH").
2. Giải nén toàn bộ file ZIP vào một thư mục riêng; KHÔNG chạy file trong ZIP.
3. Nhấp đúp MO_WEBSITE.bat. Lần đầu cần Internet để cài thư viện.
4. Website mở tại http://127.0.0.1:5173/ (cổng có thể thay đổi nếu cổng bận).
5. Trên Home chọn Clinical Tools hoặc vào PharmaDesk Case Study > Mở bộ công cụ.
6. Tại /tools bạn có thể chọn ABC/VEN, Tương tác thuốc, TDM, ADR, cũng như Tổng hợp phiếu và Trừ tổng.
7. Dữ liệu PharmaDesk được lưu bằng cơ chế của ứng dụng gốc trong thư mục LOCALAPPDATA\PharmaDesk.
8. Để đóng ứng dụng, đóng cửa sổ Python/Terminal đang chạy (Ctrl+C).

CÔNG CỤ TÍCH HỢP
- ABC/VEN: nhập một file hoặc 4 file, phân tích, xuất Excel/Word, so sánh kỳ trước.
- Tương tác thuốc: nhập file theo định dạng hỗ trợ, đối chiếu quy tắc tích hợp, xuất báo cáo.
- TDM: tính toán hỗ trợ vancomycin/aminoglycoside theo module PharmaDesk 3.0.
- ADR: nhập thông tin, lưu bản nháp, xuất PDF/Word theo mẫu gốc.

LƯU Ý
- Phần mềm sử dụng trên MÁY CÁ NHÂN; KHÔNG tự động tạo tên miền hay dịch vụ web công khai.
- Không đưa dữ liệu định danh bệnh nhân lên hosting công khai; không có đăng nhập, phân quyền hay mã hóa dữ liệu ứng dụng.
- Dữ liệu Workspace trong file HTML cũ ở nguồn file:// là một localStorage khác; muốn chuyển, xuất JSON từ bản cũ và nhập tại Workspace trong bản này.
- TDM và tương tác thuốc hỗ trợ thao tác chuyên môn, không thay đánh giá lâm sàng và phải rà soát quy tắc/ngưỡng theo phác đồ hiện hành.
- Hệ thống ABC/VEN và ADR dựa trên file mẫu/qui trình gốc do bạn cung cấp.
- Trình chạy không mở cổng mạng; chỉ lắng nghe 127.0.0.1.
