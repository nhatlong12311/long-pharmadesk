# LONG × PharmaDesk

Website portfolio của Nguyễn Đăng Nhật Long và bộ công cụ PharmaDesk hỗ trợ nghiệp vụ dược bệnh viện.

## Trạng thái
**Đang chuẩn bị triển khai.** Repository này hiện là Public. Website và các công cụ **chưa được xuất bản lên Render**.

## Cấu trúc dự kiến
- `/`: portfolio công khai (Home, About Me, PharmaDesk)
- `/tools?module=abc`: ABC/VEN
- `/tools?module=ttt`: tương tác thuốc
- `/tools?module=tdm`: TDM
- `/tools?module=adr`: báo cáo ADR

Bốn công cụ dùng mã nguồn Python/Flask của PharmaDesk 3.0 và **phải được bảo vệ bằng xác thực khi triển khai**, không phải HTML mô phỏng.

## Triển khai dự kiến
1. Rà soát quyền công bố mã nguồn, tài liệu mẫu, cơ sở tri thức tương tác và font.
2. Đưa **chỉ những tệp có quyền công bố** và không chứa thông tin nhạy cảm vào repository.
3. Cấu hình Render Web Service/Blueprint với `render.yaml`.
4. Tạo biến môi trường `PHARMADESK_PASSWORD` trên Render (không ghi vào GitHub), ít nhất 16 ký tự.
5. Kiểm thử bằng **dữ liệu giả hoặc đã khử định danh** trước khi sử dụng.

**Cảnh báo:** Bản thử nghiệm online không được sử dụng để tải lên dữ liệu định danh người bệnh, hồ sơ ADR thực hoặc thông tin y tế nhạy cảm. Chưa được đánh giá bảo mật, phân quyền và tính chính xác lâm sàng để dùng trong môi trường bệnh viện.

## Tác giả
Nguyễn Đăng Nhật Long — Clinical Pharmacist.
