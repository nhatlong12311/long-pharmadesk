# PharmaCount – kiểm kê kho Dược (bản MVP)

Ứng dụng web độc lập ở \`pharmacount/index.html\`, **không sửa** các module PharmaDesk hiện có. Mở bằng trình duyệt trên điện thoại hoặc máy tính bảng.

## Tính năng đã lập trình
- Nhập Excel .xlsx/.xls/.csv, đọc sheet đầu tiên, tự nhận diện tên/mã/tồn/đơn vị/lô/HSD/kệ và hệ số đơn vị/hộp theo tên cột thông dụng.
- Tìm thuốc theo tên, mã, lô, kệ, lọc theo trạng thái. Danh sách kiểm được sắp theo thứ tự nhập file; cần cải tiến thành thứ tự kệ chuẩn.
- Nhập chẵn (hộp) và lẻ, tự tính thực kiểm, ẩn tồn máy trước khi bấm xác nhận, hiển thị chênh lệch và danh sách kiểm lại.
- Lưu cục bộ trên trình duyệt, xuất Excel 3 sheet, sao lưu/phục hồi JSON.
- Tùy chọn Supabase: đăng nhập email, tạo đợt, mời thành viên theo email, ghi lịch sử số đếm, tải lại kết quả nhiều thiết bị.

## Cách chạy
1. Trên GitHub chọn nhánh \`feature/pharmacount-inventory\` và mở file \`pharmacount/index.html\`. Để xem chạy được trên web, mở \`https://nhatlong12311.github.io/long-pharmadesk/pharmacount/\` **sau khi PR được merge vào main**, hoặc deploy riêng thư mục \`pharmacount\` lên host HTTPS. Link GitHub Pages chưa được xác nhận hoạt động.
2. Chọn **Dữ liệu mẫu** để thử; sau đó nhập Excel thật (không có dữ liệu bệnh nhân).
3. Mở **Xuất / Đồng bộ** và xuất file Excel.
4. Để nhiều người cùng làm, tạo Supabase project riêng (nên **private**), chạy \`supabase.sql\` trong SQL editor, bật Email OTP/magic link và cấu hình Site URL / Redirect URLs theo domain web triển khai. Điền Supabase URL + publishable key trên trang (KHÔNG dùng service_role key).
5. Chủ đợt đăng nhập, nhập Excel, chọn **Tạo đợt trên đám mây**, mời email. Thành viên đăng nhập bằng email đã được mời, dán UUID đợt và chọn **Mở đợt được phân quyền**. Làm mới qua thao tác **Mở đợt** để thấy kết quả người khác (chưa có realtime).

## Giới hạn quan trọng cần Codex hoàn thiện trước khi vận hành thực
- **MVP, chưa kiểm thử end-to-end với Supabase thực và chưa phù hợp dùng như hệ thống kiểm kê chính thức.**
- Excel có tiêu đề khác bộ nhận diện cần bước map cột tương tác. Nếu thiếu hệ số quy đổi, phần mềm chỉ mặc định đơn vị lẻ = 1; **không suy diễn quy cách hộp từ mô tả**.
- Nếu một thuốc có nhiều kiểu đóng gói, cần cấu hình thùng/hộp/vỉ riêng từng thuốc và kiểm tra khác biệt giữa các lô, quy cách.
- Cần bổ sung khóa phiên bản/điều phối khi nhiều người cùng đếm một mặt hàng, xác nhận kiểm lần 2 độc lập, chốt đợt có chữ ký/phê duyệt, kiểm soát xuất nhập phát sinh trong kỳ.
- Khi mạng lỗi, nhập trên cloud sẽ không tự lưu máy thay thế: hệ thống báo lỗi để nhập lại; cần hàng đợi offline và retry bảo đảm.
- Dữ liệu cloud chỉ làm mới khi bấm Mở đợt, không tự realtime.
- Cần kiểm thử RLS, phân quyền, kiểm tra thời gian/tên người ghi nhận, không dùng key bí mật trên client, thêm rate limit/monitoring.
- Thư viện SheetJS và Supabase được tải từ CDN; muốn hỗ trợ offline toàn phần cần bundle và cache.
- LocalStorage chỉ phù hợp bản thử nghiệm, không đủ cho lưu trữ kiểm kê quan trọng.
- Thuốc gây nghiện, hướng thần và thuốc kiểm soát đặc biệt cần quy trình xác nhận riêng phù hợp quy định và SOP bệnh viện.
- Tuyệt đối không đưa thông tin bệnh nhân hay dữ liệu nhạy cảm lên GitHub public.

## Việc cần Codex làm tiếp
1. Chạy browser tests, unit tests cho các hàm quy đổi/tìm kiếm và import/export với Excel mẫu.
2. Thay \`localStorage\` bằng IndexedDB; thêm offline queue, realtime sync + xử lý xung đột.
3. Thêm bước map cột Excel và màn hình xem trước 20 dòng, cảnh báo cột trống, số tồn bất thường, mã trùng khác lô/quy cách.
4. Thêm cấu hình hệ số quy đổi từ danh mục chuẩn và từng loại đóng gói.
5. Hoàn thiện tính năng kiểm nhiều người, đóng băng tồn tại mốc thời gian, xác nhận 2 vòng, báo cáo Excel lô/HSD/kệ.
6. Audit bảo mật trước khi sử dụng trong bệnh viện.

Phần mềm quản lý kho gốc vẫn là nguồn số liệu chính. PharmaCount chỉ là công cụ ghi nhận, đối chiếu và lập báo cáo; không tự sửa tồn trong phần mềm bệnh viện.
