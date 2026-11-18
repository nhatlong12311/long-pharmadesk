# Chia sẻ PharmaDesk Tools với đồng nghiệp, không hiển thị Portfolio

Đã có chế độ `PHARMADESK_TOOLS_ONLY=1` trong `app.py`.

## Mô hình hai dịch vụ tách biệt

1. **Portfolio hiện tại**: `https://long-pharmadesk.onrender.com/`
   - Giữ nguyên giao diện portfolio.
   - Có thể vào công cụ qua `/tools` như hiện nay.
2. **PharmaDesk Tools dành cho đồng nghiệp**: tạo một **Render Web Service thứ hai**, kết nối **cùng repository** `nhatlong12311/long-pharmadesk`.
   - Địa chỉ thực tế Render cấp phát sẽ khác dịch vụ trên; không tự suy đoán URL.
   - `/` chuyển hướng sang `/tools?module=abc`, hoàn toàn không trả về HTML portfolio.
   - Giao diện bỏ liên kết về portfolio, bỏ các nút Tổng hợp phiếu / Trừ tổng không chạy trên Render.
   - Giữ bốn module: ABC/VEN, Tương tác thuốc, TDM, ADR.

## Các bước trên Render Dashboard (trình duyệt máy tính)

1. Chọn **New > Web Service** (tạo dịch vụ mới, **không thay** dịch vụ `long-pharmadesk` cũ).
2. Connect GitHub repo `nhatlong12311/long-pharmadesk`, branch `main`.
3. Đặt tên ví dụ `pharmadesk-clinical-tools` (chỉ là gợi ý; tên thực tế tùy bạn).
4. Runtime **Python**; build command:
   ```sh
   pip install -r requirements.txt
   ```
5. Start command:
   ```sh
   gunicorn --workers 1 --threads 4 --timeout 180 --bind 0.0.0.0:$PORT app:app
   ```
6. Health Check Path: `/api/health` (nếu có).
7. Environment Variables:
   - `PHARMADESK_ONLINE=1`
   - `PHARMADESK_TOOLS_ONLY=1`
   - `PHARMADESK_USERNAME=clinical` (có thể chọn tên khác)
   - `PHARMADESK_PASSWORD=<mật khẩu mới dài từ 16 ký tự>`, chỉ nhập trực tiếp trên Render
   - `PYTHON_VERSION=3.12.9`
8. Deploy, đợi trạng thái **Live**, mở URL do Render cấp để kiểm tra login và các tab.
9. Chỉ chia sẻ URL **của dịch vụ Tools thứ hai** cho đồng nghiệp.

### Kiểm tra sau triển khai

- Trang chủ `/`: chuyển sang `/tools?module=abc`, không thấy portfolio.
- `/tools?module=tdm` và `/tools?module=adr`: mở sau khi nhập mật khẩu.
- `/api/health`: trả JSON `ok=true`.
- Kiểm tra file PDF ADR hiển thị nhúng (header `SAMEORIGIN`).
- Các công cụ: test bằng dữ liệu giả/đã khử định danh và so kết quả với bản desktop.

## Giới hạn bảo mật cực kỳ quan trọng

- GitHub repository đang **Public**. Chế độ Tools Only chỉ che portfolio ở dịch vụ Render mới; **không giấu nội dung portfolio trong mã nguồn GitHub** và không đổi trang portfolio trên dịch vụ cũ.
- Bảo vệ Basic Auth dùng một tài khoản/mật khẩu chung, **không phân quyền từng đồng nghiệp**.
- Tất cả người biết mật khẩu có thể xem/tải báo cáo hoặc bản nháp đang lưu trong thư mục chung trên cùng dịch vụ. Không dùng dữ liệu bệnh nhân có định danh hay báo cáo ADR thực tế.
- Hệ thống chưa có audit log, user isolation, database an toàn, retention/deletion policy, kiểm soát truy cập theo vai trò. Render Free có thể làm mất dữ liệu khi redeploy.
- Trước khi triển khai cho sử dụng trong bệnh viện, cần tách dữ liệu từng tài khoản, quản lý phiên đăng nhập, xác thực riêng, bảo mật & kiểm thử nghiệp vụ.
