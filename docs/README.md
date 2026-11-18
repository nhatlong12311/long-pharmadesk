# PharmaDesk Browser Edition (GitHub Pages)

Đây là **bản thử nghiệm** dành cho đồng nghiệp; chỉ hiển thị bốn công cụ, không có link portfolio.

## Xuất bản

1. Mở https://github.com/nhatlong12311/long-pharmadesk/settings/pages
2. Trong **Build and deployment**, chọn **Deploy from a branch**.
3. Branch: **main**; folder: **/docs**; bấm **Save**.
4. Trang dự kiến sau khi Pages kích hoạt: https://nhatlong12311.github.io/long-pharmadesk/
5. Kiểm tra thao tác với dữ liệu giả trước khi chia sẻ.

**Không cần Render cho bản Browser Edition.** Không cần đăng nhập vì GitHub Pages là hosting tĩnh. Không nhập dữ liệu nhạy cảm; tài nguyên SheetJS được tải từ CDN. Dữ liệu nhập Excel xử lý trong trình duyệt, kết quả tải về máy.

## Chức năng hiện có

| Phân hệ | Đã có trên bản Browser Edition | Chưa có / cần đối chiếu |
|---|---|---|
| ABC/VEN | Nhập Excel/CSV, phân loại ngưỡng 80/95, giữ quy cách, xuất Excel/CSV | Logic phân nhóm và giao diện báo cáo chuyên sâu từ Python, so sánh tháng |
| Tương tác thuốc | Chọn thuốc, kiểm tra cặp trong 252 thuốc / 368 cặp quy tắc gốc | Cơ chế, hậu quả, xử trí từ cơ sở tri thức và báo cáo Word |
| TDM | Ước tính CrCl, CL, Vd, t½, AUC và Cmax/Cmin mô hình một ngăn vancomycin | Hiệu chỉnh hai mẫu, Aminoglycoside, kiểm thử tương đương và xác thực lâm sàng |
| ADR | Biểu mẫu mở rộng (diễn biến, mức độ, xét nghiệm, thuốc nghi ngờ, dechallenge/rechallenge), bản in PDF qua Print, **lưu/mở bản nháp JSON cục bộ** | **Mẫu PDF chính thức 115 trường**, file Word .docx chỉnh sửa, xác thực bản tóm tắt theo quy trình báo cáo |

Không được hiểu kết quả tương tác thuốc không tìm thấy là an toàn, hay kết quả TDM là khuyến cáo liều điều trị. Bản này không dùng cho quyết định điều trị hoặc báo cáo chính thức khi chưa kiểm thử.

## Giới hạn quyền riêng tư

- Repo GitHub hiện **Public**; portfolio vẫn có trong mã nguồn công khai mặc dù **không hiển thị trong giao diện** GitHub Pages.
- GitHub Pages không có mật khẩu server, phân quyền, dữ liệu lưu trữ riêng hay kiểm soát truy cập.
- Không chia sẻ link Pages để nhập dữ liệu định danh bệnh nhân.
- Nếu muốn thật sự giấu mã nguồn portfolio, phải chuyển phần portfolio sang repository riêng Private hoặc loại mã nguồn portfolio khỏi repository công khai. Chế độ chỉ ẩn giao diện chưa đạt yêu cầu giấu mã nguồn.

## Vận hành và tốc độ

- Không có cold start của Flask/Render.
- Thư viện Excel SheetJS được nạp từ https://cdn.sheetjs.com/xlsx-0.20.3/package/dist/xlsx.full.min.js; nếu CDN lỗi, CSV vẫn dùng được.
- Bộ quy tắc ở `docs/rules.json` được tải cùng website.
- Tài liệu hướng dẫn sửa lỗi trên Render: `RENDER_TOOLS_ONLY.md`; hệ thống Render vẫn là một sản phẩm khác.

## ADR Browser Edition — cách dùng

1. Mở tab **Báo cáo ADR** trên Pages.
2. Nhập dữ liệu **giả**; điền tên thuốc nghi ngờ và mô tả phản ứng.
3. Chọn **Tạo bản tóm tắt**; kiểm tra phần xem trước rồi **In / Lưu PDF** để dùng chức năng in của trình duyệt.
4. Chọn **Lưu bản nháp .json** để tải file về máy; sau đó có thể dùng **Mở bản nháp .json** để nạp lại dữ liệu. Không gửi JSON có dữ liệu định danh lên GitHub hoặc qua ứng dụng nhắn tin.

**Lưu ý:** Đây chưa phải mẫu ADR chính thức và chưa xuất file Word. Phần tiếp theo cần tái tạo mẫu PDF chuẩn và đối chiếu toàn bộ trường biểu mẫu với bản PharmaDesk Python.
