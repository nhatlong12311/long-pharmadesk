# PharmaDesk trên GitHub Pages

[Mở PharmaDesk](https://nhatlong12311.github.io/long-pharmadesk/) để dùng ABC/VEN, Tương tác thuốc, TDM và Báo cáo ADR. Trang tải Python WebAssembly và mẫu báo cáo từ GitHub Pages, sau đó xử lý Excel, tính toán và tạo báo cáo trong trình duyệt. Trình duyệt lưu bộ chạy để dùng lại trong các lần mở sau. Mỗi tab vẫn khởi tạo Python, và thư viện báo cáo được tải khi cần. Bạn có thể mở thẳng [Báo cáo ADR](https://nhatlong12311.github.io/long-pharmadesk/?module=adr).

Các phân hệ dùng lại mã Python và mẫu của bản Windows. Tải báo cáo Excel, Word hoặc PDF về thiết bị sau khi tạo. Bản nháp ADR, tùy chọn và lịch sử được lưu theo trình duyệt. Khi trình duyệt chặn lưu trữ thì dữ liệu chỉ tồn tại trong tab. Dùng dữ liệu giả khi thử nghiệm.

[Bản web nhẹ](https://nhatlong12311.github.io/long-pharmadesk/browser.html) mở các công cụ JavaScript thử nghiệm cho thiết bị không chạy được Python WebAssembly. [Bản Windows](https://github.com/nhatlong12311/long-pharmadesk/releases/latest) có thêm Tổng hợp phiếu, Trừ tổng và kết nối Crystal Reports để chuyển RPT.

## Triển khai và kiểm thử

Đặt nguồn GitHub Pages là **GitHub Actions** trong Settings → Pages. Workflow **PharmaDesk GitHub Pages** đóng gói Python, mã ứng dụng, thư viện và mẫu báo cáo thành một trang tĩnh. Workflow chỉ triển khai từ `main`. Bản build được kiểm tra trên Chromium với dữ liệu giả trước khi triển khai.

Chạy bản build cục bộ bằng Python 3.12, pip và curl.

```sh
python web/build.py dist-pages
python -m http.server --directory dist-pages
```

Mở `http://localhost:8000/`. Bộ kiểm thử trình duyệt dùng Playwright Chromium.

```sh
npm install --no-save --no-package-lock playwright@1.58.2
npx playwright install chromium
node web/smoke.cjs dist-pages
```
