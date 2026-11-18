# PharmaDesk 3.0

PharmaDesk gồm Tổng hợp phiếu, Trừ tổng, ABC/VEN, Tương tác thuốc, TDM và Báo cáo ADR. Bản Windows có giao diện của cả sáu chức năng. Bản GitHub Pages chạy bốn phân hệ lâm sàng ngay trong trình duyệt.

| Nơi chạy | Chức năng |
| --- | --- |
| [PharmaDesk cho Windows](https://github.com/nhatlong12311/long-pharmadesk/releases) | Tổng hợp phiếu, Trừ tổng, ABC/VEN, Tương tác thuốc, TDM và ADR |
| [PharmaDesk trên Render](https://long-pharmadesk.onrender.com/tools?module=abc) | ABC/VEN, Tương tác thuốc, TDM và ADR PDF/Word. Đăng nhập bằng tài khoản được cấp. |
| [GitHub Pages](https://nhatlong12311.github.io/long-pharmadesk/) | Chạy ABC/VEN, Tương tác thuốc, TDM và ADR bằng Python ngay trong trình duyệt. [Hướng dẫn GitHub Pages](docs/README.md). |

## Chạy trên Windows

1. Tải `PharmaDesk_V3_0_Windows.zip` từ [Releases](https://github.com/nhatlong12311/long-pharmadesk/releases), giải nén vào thư mục bạn có quyền ghi và giữ nguyên các tệp đi kèm.
2. Mở `PharmaDesk_V3_0.exe`. Ứng dụng chạy trên máy này và mở giao diện trong trình duyệt. Bản phát hành có sẵn mẫu gốc `Mau tong.xlsx` dùng cho Tổng hợp phiếu và Trừ tổng.
3. Để chuyển phiếu `.rpt` sang `.xls`, Windows cần Crystal Reports 10 RDC 32-bit đã được cài đặt và đăng ký. Tổng hợp phiếu có chế độ **Chỉ gộp** cho file Excel đã xuất. Xem [hướng dẫn Trừ tổng](HUONG_DAN_TRU_TONG.txt) để kiểm tra quy trình trước và sau.

Nếu chạy từ mã nguồn, tải và giải nén mã, cài Python 3.12, rồi mở `Mo_phan_mem.bat`. Có thể tự đóng gói bằng `Build_exe.bat`. Bản đóng gói nằm trong `dist\PharmaDesk_V3_0`.

## Triển khai bản web

Render chạy `app.py` theo [render.yaml](render.yaml). Cấu hình `PHARMADESK_ONLINE=1`, tài khoản và mật khẩu trong môi trường của Render. Đặt `PHARMADESK_TOOLS_ONLY=1` trên dịch vụ dành cho đồng nghiệp để mở thẳng các công cụ. [Hướng dẫn Tools Only](RENDER_TOOLS_ONLY.md)

Bản web dùng chung tài khoản và vùng lưu trữ. Chỉ dùng dữ liệu giả trong phiên bản thử nghiệm online. Tải báo cáo và bản nháp cần giữ về thiết bị vì Render Free có vùng lưu trữ tạm. [Hướng dẫn triển khai online](HUONG_DAN_TRIEN_KHAI_ONLINE.md)

## Kiểm thử và phát hành

Chạy `python -m unittest discover -s tests -v` sau khi cài `requirements.txt`. Các test dùng Excel và dữ liệu giả. Cần máy Windows có Crystal Reports 10 RDC để kiểm thử chuyển RPT từ đầu đến cuối.

Workflow **Build PharmaDesk for Windows** chạy test, đóng gói ứng dụng và kiểm tra khởi động bản EXE. Chạy workflow từ `main` với `release_tag` để phát hành ZIP trên GitHub Releases.
