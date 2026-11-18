# LONG + PharmaDesk 3.0 — triển khai website online

## Quan trọng trước khi đưa lên mạng

- Trang portfolio `/` công khai. Khu `/tools` và toàn bộ `/api/*` (trừ `/api/health`) yêu cầu **HTTP Basic Auth**.
- Đây là bản **dùng thử online cho MỘT tài khoản**, không phải nền tảng đa người dùng. Backend gốc dùng thư mục và trạng thái dùng chung, không có cơ chế cách ly bệnh nhân/người sử dụng.
- **KHÔNG nhập dữ liệu nhận diện người bệnh, bệnh án thực hoặc hồ sơ ADR thật** trên môi trường thử nghiệm/cloud này. Dữ liệu báo cáo, bản nháp và lịch sử module có thể nằm tạm trên ổ đĩa máy chủ; mật khẩu đơn lẻ không đáp ứng yêu cầu bảo vệ dữ liệu y tế.
- Render Free có **filesystem tạm**: file tải lên, kết quả, lịch sử hoặc bản nháp có thể mất khi service khởi động lại / redeploy. Hãy tải kết quả ngay sau khi tạo. Không xem nơi này là kho lưu trữ lâu dài.
- Chức năng RPT → XLS sử dụng Crystal Reports/Windows **không hoạt động trên Linux**. ABC/VEN, tương tác thuốc, TDM, ADR chạy bằng Python cần kiểm thử thực tế trên máy chủ trước khi dùng nghiệp vụ.
- Workspace cá nhân trong trang portfolio V11 vẫn là `localStorage` theo trình duyệt, **chưa đồng bộ**, **chưa có bảo vệ tài khoản**. Đừng lưu thông tin riêng tư tại đó trên thiết bị dùng chung.

## Triển khai lên Render

1. Giải nén ZIP. Tạo **repository GitHub private**, đưa các file trong thư mục `LONG_PharmaDesk_Clinical` vào **thư mục gốc** của repository. Không đưa dữ liệu bệnh nhân hoặc mật khẩu vào repo.
2. Mở https://dashboard.render.com/ và chọn **New → Blueprint**; kết nối repo vừa tạo. Render đọc `render.yaml`.
3. Tại biến môi trường `PHARMADESK_PASSWORD`, nhập mật khẩu **tự chọn, tối thiểu 16 ký tự**, có độ ngẫu nhiên cao. Không lưu mật khẩu vào HTML, repo hay file `.env` public. Username mặc định `clinical`, có thể đổi `PHARMADESK_USERNAME`.
4. Chạy deploy và chờ trạng thái **Live**. Render sẽ cấp một URL `https://...onrender.com` (tên cụ thể do Render cấp, không có URL cố định trước khi deploy).
5. Mở URL đó để xem portfolio; mở `<URL>/tools` để đăng nhập. ABC/VEN, tương tác thuốc, TDM và ADR dùng trong cùng giao diện.
6. Trước khi sử dụng thực tế, thử bằng dữ liệu giả: nhập Excel mẫu không có thông tin bệnh nhân, xuất `.xlsx/.docx/.pdf`, tải ngay, rồi kiểm tra lỗi trong Render Logs.

## Ghi chú vận hành

- Chọn Python 3.12, một Gunicorn worker vì code gốc dùng trạng thái dùng chung và khóa trong tiến trình.
- Nếu tải Excel quá lớn, giới hạn upload trực tuyến mặc định là 20 MB. Đổi giới hạn phải cân nhắc tài nguyên máy chủ.
- Không sử dụng nhiều người đồng thời. Nếu cần công khai cho nhiều đồng nghiệp, phải thiết kế lại: đăng nhập có vai trò, phân vùng dữ liệu từng người, kiểm tra upload, lưu trữ an toàn, mã hóa, logging tối thiểu, tự động xóa, chính sách sao lưu/khôi phục và kiểm thử lâm sàng.
- Để dùng tên miền riêng, thêm Custom Domain trong Render rồi cấu hình DNS theo hướng dẫn của Render.
- Render Free có thể ngủ khi không hoạt động và không có persistent disk. Nếu cần dữ liệu bền vững, phải chuyển sang hạ tầng có lưu trữ phù hợp và sửa mã để sử dụng ổ đĩa/data store riêng.

## Các đường dẫn

- `/`: portfolio cá nhân (công khai)
- `/tools?module=abc`: ABC/VEN (mật khẩu)
- `/tools?module=ttt`: tương tác thuốc (mật khẩu)
- `/tools?module=tdm`: TDM (mật khẩu)
- `/tools?module=adr`: ADR (mật khẩu)
- `/api/health`: trạng thái máy chủ, không có dữ liệu riêng

## Cảnh báo

**Mức độ hoàn thiện:** đây là gói triển khai online có chặn truy cập cơ bản, **chưa phải hệ thống lâm sàng production-ready**. Cần đánh giá bảo mật, kiểm thử module và tuân thủ quy định bảo vệ dữ liệu trước khi sử dụng trên hồ sơ bệnh nhân thật.
