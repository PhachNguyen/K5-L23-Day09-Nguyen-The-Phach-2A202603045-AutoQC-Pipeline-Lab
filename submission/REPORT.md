# Báo cáo Day 09 — NguyenThePhach, 2A202603045

## 1. Kết luận trước

Pipeline kết luận **Hold**. Ở lần chạy cuối, đã quét 224 ảnh raw, nhận 202 ảnh và loại 22 ảnh ở cửa vào; export nháp `clean_v1` có 202 ảnh. Sau khi mô phỏng duyệt 80/125 ảnh trong hàng đợi, vẫn còn cảnh báo trên 38/202 ảnh (18.81%), cao hơn ngưỡng Hold 10%; không còn lỗi bắt buộc.

## 2. Lỗi và phân việc

| Mã lỗi                                                                                                     |  Số ảnh/dòng | Ai sửa (máy/người)       | Vì sao                                                                 |
| ---------------------------------------------------------------------------------------------------------- | -----------: | ------------------------ | ---------------------------------------------------------------------- |
| `CORRUPT_IMAGE` (2), `BAD_SIZE` (3), `DUP_IMAGE_EXACT` (8), `DUP_IMAGE_NEAR` (4), `LEAK_TEST` (5)          |       22 ảnh | Máy                      | Bị loại ở bước intake vì hỏng, quá nhỏ, trùng hoặc trùng với test/val. |
| `BAD_FORMAT` (3), `BAD_CLASS_ID` (6), `BOX_ZERO` (4), `DUP_BOX` (7)                                        |      20 dòng | Máy                      | Dòng không hợp lệ hoặc box trùng bị xóa.                               |
| `BOX_OUT_OF_IMAGE`                                                                                         |       8 dòng | Máy                      | Box được cắt về trong ảnh.                                             |
| `BAD_CLASS_NAME`                                                                                           |       2 lỗi  | Máy                      | Tên lớp trong `data.yaml` được ghi lại một lần theo cấu hình.          |
| `MISSING_LABEL_FILE`                                                                                       |       6 ảnh  | Người                    | Máy không tự bịa nhãn; chuyển người gán.                               |
| `POSSIBLE_MISSING` (53), `POSSIBLE_LOOSE_BOX` (28), `POSSIBLE_WRONG_CLASS` (18), `POSSIBLE_FALSE_POS` (29) | 128 cảnh báo | Người                    | Ý kiến model chỉ là cảnh báo ngữ nghĩa cần người xác minh.             |
| `EMPTY_LABEL` (12), `BOX_TINY` (6), `BOX_HUGE` (3)                                                         |  21 cảnh báo | Người                    | Cần xem ảnh để quyết định; máy không tự sửa.                           |
| `CLASS_RARE`                                                                                               |   4 cảnh báo | Không gắn vào ảnh cụ thể | Thống kê cấp dataset, không phải lỗi nhãn của một ảnh riêng.           |

`05_review_queue.csv` có 125 ảnh; `img_0020` đứng đầu (priority 11.524) vì cùng có `FIXED_DROP_LINE`, `POSSIBLE_MISSING` và `POSSIBLE_WRONG_CLASS`; điểm ưu tiên cộng trọng số mã lỗi và confidence. Pipeline mô phỏng duyệt 80 ảnh, để lại 45 ảnh chưa duyệt.

## 3. Calibration (2 ngưỡng)

| Tham số                 | Khởi đầu | Đã chọn | Precision / Recall (trước → sau)                                                                                              | Lý do (đánh đổi)                                                                                                                                                               |
| ----------------------- | -------- | ------- | ----------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `duplicates.phash_dist` | 2        | 14      | Near: 1.00/0.50 → 1.00/0.67; exact giữ 1.00/1.00                                                                              | Bắt 4/6 near-duplicate thay vì 3/6 ở ngưỡng 2; so với 16, recall near giảm 0.83→0.67 nhưng tránh hai cặp khác cảnh bị gắn cờ ở raw. Ưu tiên tránh loại nhầm ảnh.               |
| `second_opinion.conf`   | 0.25     | 0.6     | WRONG_CLASS: 0.56/0.83 → 0.62/0.83; MISSING: 0.50/1.00 → 0.57/1.00; LOOSE_BOX: 0.29/0.40 → 0.20/0.20; FALSE_POS giữ 0.31/1.00 | Ưu tiên WRONG_CLASS/MISSING: precision tăng, recall giữ nguyên; đổi lại LOOSE_BOX bắt 1/5 thay vì 2/5. Đây vẫn là cảnh báo cho người duyệt, không phải kết luận lỗi chắc chắn. |

Điểm có thể đánh lừa: calib chỉ có 39 ảnh và 6 near-duplicate, nên một ảnh làm recall thay đổi 1/6 (16.7 điểm phần trăm). Precision 1.00 trên calib không đảm bảo các cặp raw đều trùng thật: kiểm tra bằng mắt 7 cặp ở ngưỡng 16 cho thấy 4 cặp trông cùng cảnh/biến thể ảnh (`img_0084`–`img_0074`, `img_0186`–`img_0061`, `img_0223`–`img_0077`, `img_0076`–`img_0042`), còn `img_0011`–`img_0008` và `img_0177`–`img_0113` là cảnh khác; `img_0143`–`img_0037` cũng là hai ảnh xe buýt khác dù pHash bằng 0. Hạ ngưỡng không loại được va chạm pHash bằng 0, nên các cặp bị gắn cờ vẫn cần người xác minh.

## 4. Cửa chặn và điều pipeline KHÔNG bắt được

(a) Chạy với `--budget 0` cho kết luận **Rework**, còn 6 lỗi bắt buộc, mã thoát 20; `work/exp_nb/clean_v1` không được tạo. Kết quả được lưu ở `work/rep_nb/08_summary.json`. (b) Calibration cho thấy `POSSIBLE_LOOSE_BOX` ở `conf=0.6` chỉ bắt 1/5 lỗi chèn (recall 0.20), nên checker còn bỏ sót phần lớn box lỏng. Ngoài ra, calib không có ca `LEAK_TEST`, trong khi intake của lần chạy cuối gắn cờ 5 ảnh là `LEAK_TEST`; precision/recall cho nhóm này chưa được đo bằng calibration. (c) Ba quan sát trực quan về cờ trùng sai ở raw khi thử ngưỡng 16: `img_0011` (tennis)–`img_0008` (ski), `img_0177` (surfer)–`img_0113` (diner), và `img_0143`–`img_0037` (hai cảnh xe buýt khác nhau dù pHash bằng 0).

## 5. Train: raw vs clean (tùy chọn, chấm riêng)

| Biến thể | # ảnh train | Số seed | mAP50 (TB ± độ lệch) | mAP50-95 (TB ± độ lệch) | Precision (TB ± độ lệch) | Recall (TB ± độ lệch) |
|---|---:|---:|---:|---:|---:|---:|
| raw | 224 | 2 | 0.726 ± 0.000 | 0.512 ± 0.004 | 0.764 ± 0.061 | 0.649 ± 0.028 |
| clean | 202 | 2 | 0.701 ± 0.025 | 0.487 ± 0.008 | 0.759 ± 0.003 | 0.625 ± 0.019 |

`mAP50` clean − raw = **−0.0252** (0.7006 − 0.7258). Độ lệch mAP50 giữa hai seed của clean là 0.0246, gần bằng mức chênh trung bình; với chỉ 2 seed, chưa thể kết luận clean làm giảm chất lượng. mAP50-95 và recall cũng thấp hơn ở clean, còn precision gần như giữ nguyên.

Hai giả thuyết cần kiểm tra: (1) clean có ít hơn 22 ảnh; việc loại ảnh trùng/rò rỉ/hỏng có thể đồng thời làm giảm độ đa dạng, nhất là ví dụ của lớp truck — kiểm tra số box theo lớp và ảnh truck bị loại trong báo cáo intake; (2) nhãn clean vẫn còn cảnh báo sau duyệt, có thể ảnh hưởng chất lượng — mở kiểm tra các ảnh truck có cảnh báo trong `07_error_list_v3.csv`. Bộ test nhỏ và chỉ 2 seed cũng khiến kết quả dao động; cần thêm seed hoặc tập đánh giá độc lập trước khi kết luận chắc chắn.

## 6. Quyết định và ghi chú AI

Quyết định hiện tại là **Hold**; với lần chạy cuối, cần xác minh và xử lý cảnh báo để còn tối đa 20/202 ảnh (dưới 10%), không hạ ngưỡng cổng hoặc bỏ qua cảnh báo để ép Release.

- Prompt chính: nhờ AI triển khai bốn module theo docstring và test có sẵn; không sửa test.
- Kiểm chứng: 4 test mục tiêu và toàn bộ `pytest` đều xanh (79 passed); sau đó chạy calibration và pipeline.
- Lần AI sai: ban đầu hướng dẫn `make calibrate`, nhưng PowerShell không có `make`; dùng lệnh Python trực tiếp với `PYTHONUTF8=1` để chạy được trên Windows.
