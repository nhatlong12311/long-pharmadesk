# PharmaCount — vận hành và nghiệm thu

## Địa chỉ sau khi triển khai
- GitHub Pages: `https://nhatlong12311.github.io/long-pharmadesk/pharmacount/`
- Vercel: `/pharmacount/` dưới domain đã cấu hình cho PharmaDesk.
- Trang có sẵn Supabase URL và **publishable key** (không phải khóa quản trị).
- Mã nguồn ở PR #25, thư mục `pharmacount/`, xuất bản từ `web/build.py` (chỉ phát hành `index.html`, `pack-worker.js` và `theme.css`).

**Không sử dụng dữ liệu kho thật khi chưa hoàn tất nghiệm thu 2 tài khoản và được bệnh viện đồng ý dùng Supabase.** GitHub repo và giao diện web là công khai; bảng thuốc chỉ được giới hạn bởi Supabase Auth và RLS.

## Cấu hình Supabase Auth trước khi đăng nhập
Trong Supabase Dashboard dự án `jpsywcjmcmvgjswkrnzo`:
1. Authentication → URL Configuration: cho phép chính xác `https://nhatlong12311.github.io/long-pharmadesk/pharmacount/` trong Redirect URLs. Nếu dùng Vercel/domain riêng, thêm đúng URL thực tế. Không cho phép wildcard domain không kiểm soát.
2. Authentication → Sign In / Providers: bật Anonymous Sign-Ins để dùng link khách. Authentication → Providers → Email: xác nhận email OTP/magic link hoạt động và chính sách tạo tài khoản phù hợp. Đăng ký mới cần được quản trị viên kiểm soát; mời thành viên vào đợt kiểm KHÁC với đăng ký tài khoản Auth.
3. Với cơ sở dữ liệu mới, chạy theo thứ tự `supabase.sql`, `supabase-count-rpc.sql`, `supabase-latest-counts.sql`, `supabase-team-permissions.sql`, `supabase-finalization.sql`, `supabase-finalization-item-guard.sql`, `supabase-rpc-permissions.sql`, `supabase-guest-links.sql`. Với cơ sở dữ liệu hiện có, kiểm tra các bản đã áp dụng và chỉ chạy phần còn thiếu. Giữ `pharmacount_private` ngoài danh sách schema được Data API công bố.
4. Kiểm tra Security Advisor, RLS, phương án sao lưu, giới hạn dung lượng và chính sách lưu dữ liệu. Không đưa thông tin bệnh nhân hoặc tài liệu nội bộ không cần thiết vào ứng dụng.

## Checklist nghiệm thu bắt buộc trước dùng thật
- [ ] Chủ đợt đăng nhập email OTP trên máy A; nhân viên được mời đăng nhập bằng email khác trên máy B.
- [ ] Nhập `.xlsx` kiểm kê nhiều sheet, bảo toàn từng mã thuốc/lô/HSD/dòng nguồn; so số dòng trước/sau; không biến tồn trống thành 0.
- [ ] Ghép danh mục quy cách `.xlsx`; rà soát mã không khớp, nhiều lựa chọn hộp, hệ số chưa xác nhận; xuất file cần rà soát.
- [ ] Tạo đợt bằng chủ đợt, mời email nhân viên, gửi link. Nhân viên mở link và thấy đúng danh mục.
- [ ] Cùng nhập một thuốc trên hai máy: một người được lưu, người còn lại nhận thông báo xung đột và phải đối chiếu.
- [ ] Kiểm mạng chập chờn/mất kết nối: không xuất hiện trạng thái đã lưu khi Supabase chưa xác nhận; thử lại giữ nguyên mã thao tác.
- [ ] Trưởng nhóm thu hồi email của máy B: máy B không thể lưu tiếp hoặc đọc đồng bộ; mở link lần nữa không thể truy cập.
- [ ] Chủ đợt chốt khi còn thuốc chưa kiểm: máy chủ từ chối. Sau khi đếm đủ, chỉ chủ đợt chốt thành công; sau chốt, không ai được lưu/chèn thêm.
- [ ] Xuất Excel từ đợt đã chốt: đúng số hộp, số lẻ, tổng kiểm, người kiểm, thời gian, từng lượt đếm trong **Lịch sử kiểm** và trạng thái **ĐÃ CHỐT**.
- [ ] Chạy kiểm thử ít nhất 1.000 thuốc và kiểm tra trên điện thoại, máy tính bảng, PC; xác nhận website mới không làm hỏng ABC/VEN, ADR, TDM và các chức năng PharmaDesk khác.
- [ ] Đơn vị phụ trách ký nghiệm thu, phê duyệt luồng dữ liệu, sao lưu, phân quyền; xác nhận tuân thủ quy định bệnh viện.

## Thực hiện kiểm kê sau nghiệm thu
- **Trưởng nhóm:** đăng nhập → tải danh mục Excel → ghép quy cách → sửa những yếu tố chưa xác định → Tạo đợt chung → Mời thành viên → Sao chép link.
- **Khách có link:** mở link kiểm kê do chủ đợt bật trong Xuất / Đồng bộ, nhập tên và vào kiểm. Chủ đợt có thể tắt link để thu hồi quyền của khách.
- **Nhân viên:** mở link bằng điện thoại/PC → đăng nhập đúng email → kiểm hộp chẵn, thuốc lẻ → xác nhận → xem thông báo máy chủ lưu thành công.
- **Trưởng nhóm khi kết thúc:** kiểm đủ danh sách, xử lý đếm lại → Chốt và khóa → xuất Excel cuối cùng → lưu trữ theo quy định. Sau chốt không có nút mở lại.
- **Tài khoản bị thu hồi:** dữ liệu đã hiển thị trên máy sẽ được đóng sau khi máy chủ từ chối yêu cầu tiếp theo; đây không phải cơ chế xóa bản đã tải xuống hoặc ảnh chụp màn hình.

## Điều hành sự cố và phục hồi
- Mất mạng: tuyệt đối không tuyên bố đã lưu. Không xóa tab/kết quả đang nhập nếu chưa nhận xác nhận. Tạm kiểm giấy và nhập lại sau khi có mạng nếu cần.
- Nhập sai số: khi đợt chưa chốt có thể đếm lại, lịch sử lưu mọi lần. Sau chốt, không sửa kết quả, lập biên bản và tạo đợt mới nếu cần.
- Sao lưu: xuất Excel chốt bao gồm `Thông tin đợt`, `Tổng hợp`, `Chi tiết kiểm`, `Cần kiểm lại`, `Lịch sử kiểm`; theo dõi sao lưu PostgreSQL/Supabase theo chính sách bệnh viện.
- Rollback phần giao diện: quay lại commit trước khi merge PR #25; giữ nguyên PostgreSQL và dữ liệu (không xóa bảng). Nếu cấu hình/auth gặp sự cố, tạm ngừng dùng dịch vụ.

## Cổng quyết định phát hành
Mã nguồn và CI không thay thế thử nghiệm đăng nhập OTP qua website, thử hai thiết bị và phê duyệt của bệnh viện. **Có thể triển khai giao diện công khai chỉ để chạy dữ liệu giả**, nhưng quyền sử dụng dữ liệu kho thật chỉ mở sau khi checklist trên hoàn tất.
