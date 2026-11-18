# Báo cáo kiểm tra PharmaDesk 3.0 — 18/11/2026

## Phạm vi và phương pháp

- Kiểm tra **mã Python/Flask hiện có trên GitHub main**, không phải bản mô phỏng GitHub Pages.
- Dùng GitHub Actions Python 3.12 và `tests/test_full_smoke.py`, Flask test client với thư mục và dữ liệu **giả lập**.
- Đối chiếu các thành phần còn thiếu với file nguồn gốc `PharmaDesk_3_0_ChiTietSoLuong(1).zip` đã được người dùng cung cấp.
- **Không** truy cập file bệnh nhân, không dùng dữ liệu bệnh viện, chưa test toàn bộ luồng trên Render live hoặc Crystal Reports trên máy Windows.

## Bảng kết quả

| Hạng mục | Kết quả trong kiểm thử | Giới hạn |
|---|---|---|
| Portfolio / Tools Only | Đạt: `/` tự chuyển tới Tools khi TOOLS_ONLY=1, không có liên kết portfolio, bảo vệ Basic Auth | Chưa kiểm tra trên dịch vụ Render thứ hai |
| Bảo mật API cơ bản | Đạt: từ chối truy cập không mật khẩu và POST thiếu token; chặn thao tác Windows-only online | Mật khẩu chung chưa đủ để bảo vệ hồ sơ thật |
| ABC/VEN nhập Excel | Đạt: 3 dòng giả, nhận dạng cột, giữ quy cách | Cần đối chiếu trên dữ liệu Excel thực có nhiều biến thể |
| ABC/VEN xuất | Đạt: tạo/tải Excel và Word từ Flask | Chưa kiểm tra chi tiết số liệu tất cả bảng Word và so sánh 4 file |
| ABC/VEN so sánh tháng | Đạt: xuất/tải Excel so sánh từ dữ liệu kỳ trước/kỳ này | Chưa test hiệu năng với dữ liệu lớn |
| Tương tác thuốc | Đạt: đọc Excel, nạp quy tắc, xuất Word; test đúng một cặp thật trong bộ quy tắc bằng ca bệnh giả | Chưa xác minh đầy đủ nội dung cơ chế/hậu quả/xử trí và độ bao phủ kiến thức |
| TDM vancomycin | Đạt: phép tính khởi đầu và hai nồng độ với dữ liệu giả; lỗi đầu vào trả JSON | Đây là kiểm tra kỹ thuật, không phải hiệu chuẩn lâm sàng |
| TDM aminoglycoside | Đạt: phép tính khởi đầu và hai nồng độ với dữ liệu giả | Không thay thế thẩm định lâm sàng |
| ADR | Đạt: PDF đúng định dạng, Word đọc được, bản nháp lưu/mở/xóa | Chưa xác minh bản xem trước PDF và download **trên Render live** sau PR #1 |
| Tổng hợp phiếu | **Không đạt điều kiện chạy đầy đủ** | Thiếu file gốc `Gop_va_sort_AZ.py`, `Xuat_RPT_sang_XLS.vbs`, `Mau tong.xlsx` trong repo |
| Trừ tổng | **Lỗi chức năng xác nhận từ mã nguồn** | Thiếu `rpt_test.py` và route `/api/test/compare` trên repo; UI còn gọi API này |
| Chuyển RPT Crystal Reports | Chưa thể kiểm thử trong GitHub Actions Linux | Phụ thuộc Windows + Crystal Reports và các file nguồn đang thiếu |

## Lỗi cần xử lý theo mức độ ưu tiên

**P0 — Không được đánh dấu đã hỗ trợ nếu thiếu backend**
- Bổ sung đầy đủ `rpt_test.py` từ ZIP gốc và đăng ký blueprint trong `app.py` của bản desktop, hoặc ẩn/khóa rõ ràng mục Trừ tổng trên các bản không hỗ trợ; không tạo kết quả mô phỏng.
- Khôi phục `Gop_va_sort_AZ.py`, `Xuat_RPT_sang_XLS.vbs`, `Mau tong.xlsx` từ ZIP gốc sau khi rà soát quyền phân phối repo Public.
- Chạy thử chức năng RPT trên Windows có Crystal Reports; GitHub Actions Ubuntu không thể xác nhận.

**P1 — Triển khai trực tuyến với dữ liệu lâm sàng**
- Report ABC/VEN/TTT và bản nháp ADR lưu thư mục chung theo tên hoặc tháng; tài khoản chung có thể cùng truy cập/sửa dữ liệu.
- Trước khi đồng nghiệp dùng dữ liệu bệnh nhân thật: phải có xác thực và phân quyền từng tài khoản, phân tách dữ liệu, audit log, quản lý thời hạn lưu và bảo mật.
- Không coi Render Free là nơi lưu file báo cáo lâu dài.
- Kiểm tra ADR sau PR #1 bằng dữ liệu giả trên Render, bao gồm HTTP status, tạo PDF chính thức, tải DOCX và iframe.

**P2 — Chất lượng**
- Test định dạng/giới hạn các trường PDF ADR, diacritics tiếng Việt và tickboxes với bộ ca cố định.
- Thử file ABC/VEN đủ 4 nguồn và các quy cách khác nhau; phân loại VEN và xuất Word/Excel.
- Đối chiếu độc lập TDM trên một bộ ca PK chuẩn đã được thẩm định; không suy từ test API thành khuyến cáo lâm sàng.
- Thử tương tác thuốc với dữ liệu mã hoạt chất thực tế, kiểm tra cơ chế/hậu quả/xử trí và sự khác biệt ngoại trú/nội trú.

## Hai lỗi của bộ regression cũ

Trong workflow trước (PR #1) có **22/24 passed, 2 failed**:
1. `test_06_session_token_is_in_the_served_page`: test kiểm tra `/` nhưng app nay phục vụ portfolio ở `/`; token nằm ở `/tools`.
2. `test_23_corrupt_input_blocks_partial_merge`: chạy `Gop_va_sort_AZ.py` không có trong repository.

Không nên âm thầm bỏ qua lỗi thứ hai hoặc thay logic gộp của mã nguồn gốc bằng demo.

## Những việc kiểm tra chưa làm

- Chưa có quyền/đăng nhập để xác minh Render Logs, RAM, cold-start và toàn bộ flow trên dịch vụ đang chạy.
- Chưa kiểm thử Windows/Crystal Reports thật (không có Windows runner được cấu hình).
- Chưa làm penetration test, đánh giá lâm sàng, multi-user/concurrency test với report trùng tên, độ bền dữ liệu Render.
- Bản `docs/index.html` GitHub Pages là **Browser Edition beta khác tính năng**; không đại diện cho toàn bộ PharmaDesk Python.

**Mọi kết quả tích cực trong báo cáo này chỉ được xác nhận trong môi trường thử nghiệm bằng dữ liệu giả.**
