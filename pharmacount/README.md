# PharmaCount – kiểm kê kho Dược (bản MVP)

## Bản phát triển chung nhiều thiết bị (23/11/2026)

**Nhánh:** `feature/pharmacount-inventory`. Ứng dụng vẫn là MVP, **chưa được kiểm thử toàn trình với nhiều tài khoản thực**.

### Kiến trúc
- **Frontend:** ứng dụng tĩnh HTML/JavaScript trong `pharmacount/index.html`, có thể triển khai trên GitHub Pages sau khi duyệt Pull Request.
- **Backend:** dự án Supabase *PharmaCount* (PostgreSQL + Supabase Auth + Row Level Security + Realtime).
- **Dữ liệu gốc:** nhập `.xlsx` danh mục kiểm kê. Có thể ghép `.xlsx` danh mục quy cách trong luồng Web Worker (`pack-worker.js`), xác minh mã thuốc và không tự chọn một hệ số nếu có nhiều quy cách.
- **Một đợt chung:** trưởng nhóm tạo đợt cloud; thành viên đã mời đăng nhập và mở qua UUID đợt. Danh mục thuốc được lưu trên máy chủ; mỗi lần đếm lưu sự kiện mới và người kiểm.
- **Chống xung đột:** dùng Supabase RPC `pc_submit_count` với phiên bản trước đó và operation ID; nếu người khác đã lưu, trả `conflict`, không tự ghi đè.
- **Đồng bộ:** Supabase Realtime nhận sự kiện mới; định kỳ kiểm tra bản ghi cuối **của từng thuốc** bằng `pc_latest_counts` sau 20 giây (không dùng cursor ID toàn cục, tránh bỏ sót giao dịch hoàn tất muộn), nhằm giảm nguy cơ mất cập nhật khi websocket gián đoạn.
- **Phân biệt tồn:** mẫu tháng 10 thiếu tồn máy độc lập nên được ghi `stock=null`, **không được kết luận chênh lệch** cho các dòng này.

### Cách thiết lập và vận hành thử
1. Trong Supabase, dùng dự án *PharmaCount* đã có. Nếu tạo dự án mới, áp dụng `pharmacount/supabase.sql`, **sau đó** `pharmacount/supabase-count-rpc.sql`, **sau đó** `pharmacount/supabase-latest-counts.sql`. Không đưa `service_role` hoặc Supabase secret key vào website. Chỉ dùng publishable/anon key và bật email OTP.
2. Cấu hình Supabase Auth → URL Configuration, Site URL / Redirect URLs theo URL trang web triển khai thực tế (ví dụ trang GitHub Pages sau khi PR được merge). Đăng nhập thử bằng email của người tạo đợt và một nhân viên khác.
3. Trưởng nhóm: nhập mẫu `.xlsx` kiểm kê (tất cả sheet), ghép danh mục quy cách `.xlsx`, xử lý các trường hợp hệ số chưa rõ, sau đó vào **Xuất / Đồng bộ** để kết nối Supabase và **Tạo đợt trên đám mây**.
4. Trưởng nhóm dùng email mời từng người. Mỗi nhân viên mở cùng URL web, đăng nhập OTP bằng email được mời, dán mã UUID đợt, chọn **Mở đợt được phân quyền**. Có thể nhập trên máy tính, điện thoại, máy tính bảng.
5. Nhập **số hộp** và **số lẻ**, bấm xác nhận. Chỉ xem là đã lưu khi máy chủ trả thành công. Nếu người khác đã đếm trước, đối chiếu bản ghi mới rồi chọn kiểm lại. Kiểm tra cột người kiểm và thời gian trong Excel xuất.
6. Thử bằng **dữ liệu giả** với ít nhất 2 tài khoản và 2 thiết bị trước khi dùng dữ liệu kho thật. Không xóa hoặc đổi quy cách của mặt hàng đã được kiểm. Sao lưu Excel thường xuyên.

### Các giới hạn phải xử lý trước vận hành chính thức
- Chưa có chế độ làm việc hoàn toàn ngoại tuyến: khi mất mạng, **không** coi số đếm đã được lưu lên Supabase.
- Quyền mời người dựa trên email đăng nhập; cần xác nhận cấu hình OTP, RLS, quyền dữ liệu và xem xét danh sách thành viên.
- Chưa có khóa giữ thuốc trong lúc một người đang đếm, nhưng có **kiểm tra xung đột tại thời điểm lưu**.
- Màn hình và luồng dữ liệu chưa được kiểm thử end-to-end trên thiết bị thật với Excel thực; cần test CSV/Excel đa sheet, số lô, nhiều quy cách, hơn 1.000 mặt hàng, thu hồi quyền, xem sửa lịch sử và đánh giá chi phí.
- Supabase Security Advisor có thể cảnh báo các hàm `SECURITY DEFINER` dùng để kiểm quyền. Các hàm này cần được rà soát độc lập trước khi đưa vào môi trường bệnh viện.
- Không đưa dữ liệu bệnh nhân, thông tin nhạy cảm, thông tin đăng nhập hoặc khóa bí mật vào GitHub và bản demo. Dữ liệu kho phải được đơn vị cho phép xử lý trên nền tảng bên ngoài.

---


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


### Cập nhật quyền thành viên và đồng bộ (23/11/2026)
- Trong Supabase, với dự án tạo mới, áp dụng SQL theo thứ tự: `supabase.sql`, `supabase-count-rpc.sql`, `supabase-latest-counts.sql`, `supabase-team-permissions.sql`. Dự án Supabase PharmaCount hiện có đã được áp dụng các bản bổ sung.
- Trưởng nhóm mời nhân viên theo email, dùng nút **Sao chép liên kết cho thành viên** để chia sẻ URL có `?join=<UUID>`. Liên kết không tự cấp quyền; chỉ email đã được mời và đăng nhập mới được xem/sửa.
- Trong **Xuất / Đồng bộ**, chọn **Xem thành viên đã được mời** để xem danh sách. **Chỉ chủ đợt** mới thấy nút **Thu hồi quyền** và được RLS cho phép xóa quyền mời.
- `pc_latest_counts` đọc bản ghi cuối cùng theo từng mã dòng thuốc, phân trang 500. Không sử dụng cursor ID toàn cục vì giao dịch có thể hoàn tất lệch thứ tự.
- Nếu mất đăng nhập, ứng dụng phải báo lỗi khi lưu cloud, không được báo nhầm là đã đồng bộ.
