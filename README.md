# LONG × PharmaDesk

Portfolio cá nhân + bộ công cụ dược lâm sàng ABC/VEN, tương tác thuốc, TDM và ADR.

## Trạng thái

- Repository: **Public** theo lựa chọn của chủ dự án.
- Đã có cấu hình Render và workflow nhập mã nguồn.
- **Chưa đưa toàn bộ nguồn vào repository / chưa triển khai Live.**

## Hoàn tất nhập 27 tệp mã nguồn qua trình duyệt GitHub

1. Tải file `PHARMADESK_SOURCE_UPLOAD_GITHUB.zip` đã được chuẩn bị riêng trong cuộc trò chuyện ChatGPT (khoảng 1,4 MB).
2. Vào trang repository → **Add file → Upload files**.
3. Chọn **nguyên file ZIP** (không cần giải nén), đặt **ngay tại thư mục gốc** của repository, tên phải đúng `PHARMADESK_SOURCE_UPLOAD_GITHUB.zip`.
4. Nhấn **Commit changes** vào branch `main`.
5. Workflow [Import PharmaDesk source archive](../../actions/workflows/import-source.yml) sẽ tự kiểm tra đường dẫn tệp, giải nén mã nguồn, biên dịch Python và commit mã vào repository. Theo dõi trong tab Actions; cần cho phép GitHub Actions ghi vào repository nếu bị chặn.

⚠️ **Vì repository đang Public, mọi nội dung tệp ZIP tải lên sẽ trở thành công khai ngay cả khi workflow xóa ZIP khỏi nhánh chính.** Chỉ thực hiện khi bạn đồng ý công bố source code, các bộ quy tắc, mẫu báo cáo và tài liệu kèm theo; không được thêm dữ liệu bệnh nhân, thông tin mật hoặc tệp không có quyền phân phối.

## Kết nối Render

1. Render → **New → Blueprint**, kết nối GitHub repository `nhatlong12311/long-pharmadesk`.
2. Render sử dụng `render.yaml` ở root.
3. Nhập `PHARMADESK_PASSWORD` với mật khẩu đủ mạnh (ít nhất 16 ký tự) trong Environment. **Tuyệt đối không commit mật khẩu**.
4. Truy cập URL Render được cấp (không tự suy đoán URL):
   - `/`: Portfolio public.
   - `/tools?module=abc`: ABC/VEN (Basic Auth).
   - `/tools?module=ttt`: Tương tác thuốc.
   - `/tools?module=tdm`: TDM.
   - `/tools?module=adr`: ADR.
5. Kiểm tra dữ liệu **giả/đã khử định danh**, xuất file và đối chiếu kết quả.

## Giới hạn và an toàn

Bản demo có HTTP Basic Auth cho công cụ nhưng backend dùng trạng thái/thư mục chung, **chưa an toàn cho dữ liệu bệnh nhân** hoặc sử dụng nhiều tài khoản đồng thời. Render Free có lưu trữ tạm; không được coi là kho dữ liệu lâm sàng. Chức năng Crystal Reports Windows không chạy được trên Linux. Cần kiểm thử đúng đắn lâm sàng và đánh giá bảo mật trước khi vận hành bệnh viện.
