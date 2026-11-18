# Judge audit

Hai CSV replay công khai có 100 reply mỗi bộ. FAIL là lớp dương. Human là nhãn tham chiếu lúc đo.

| Tiêu chí | TP / FP / FN / TN | κ | Precision | Recall | Tỉ lệ FAIL quan sát → hiệu chỉnh | Quyết định |
| --- | --- | ---: | ---: | ---: | --- | --- |
| tone_ok | 24 / 4 / 6 / 66 | 0,757 | 0,857 | 0,800 | 0,280 → 0,300 | Đạt cả ba sàn. Dùng để đánh giá giọng điệu trong phạm vi replay. |
| helpful | 9 / 0 / 21 / 70 | 0,375 | 1,000 | 0,300 | 0,090 → 0,300 | Loại khỏi gate vì bỏ sót 21 trong 30 lỗi human ghi nhận. |

Sàn của đề là κ ≥ 0,60, precision ≥ 0,80 và recall ≥ 0,70. Hiệu chỉnh Rogan–Gladen dùng sensitivity = recall và specificity = TN/(TN+FP). Cả hai lấy từ cùng tập replay.

Chạy từ `src/`.

~~~powershell
python -m lab9.judge --csv data/eval/judge_tone_public.csv --audit 5
python -m lab9.judge --csv data/eval/judge_helpful_public.csv --audit 5
~~~

## Audit bất đồng

| Case | Judge / Human | Phán định theo reply và ghi chú | Cách chỉnh rubric |
| --- | --- | --- | --- |
| H-008 | PASS / FAIL | Human hợp lý. Cách xưng “em” và cụm “rồi nha” quá suồng sã theo giọng dịch vụ LogiX. | Chấm xưng hô và mức trang trọng theo chuẩn LogiX, kèm ví dụ thân thiện vẫn đạt. |
| H-029 | PASS / FAIL | Human hợp lý. “Không cần nhắn thêm” gạt yêu cầu dù đầu câu có “Dạ”. | Đọc toàn câu, kiểm xem reply có tôn trọng khách hay gạt đi yêu cầu. |
| H-042 | FAIL / PASS | Human hợp lý về tone. Reply lịch sự, báo kết quả và thời gian dự kiến. | Yêu cầu lời xin lỗi theo tình huống, cho qua câu ngắn đủ ý và lịch sự. |
| H-051 | FAIL / PASS | Human hợp lý. Ghi chú bộ dữ liệu xác nhận “refund” là thuật ngữ LogiX chấp nhận. | Thêm ví dụ từ vay mượn được phép và kiểm độ rõ theo ngữ cảnh. |
| H-081 | FAIL / PASS | Ghi chú CSV nêu nhãn human sai do đọc nhầm ticket. Câu reply tự nó lịch sự. Cần người rà thứ hai đối chiếu ticket và xác định đúng tiêu chí đang xét. | Tách tone khỏi tính đúng nghiệp vụ, rà lại ca tranh cãi và lưu phiên bản nhãn gốc. |
| HL-015 | PASS / FAIL | Human hợp lý. Reply báo 55.000đ, ghi chú ledger là 40.000đ. | Dùng grader code đọc ledger để đối chiếu tiền. |
| HL-016 | PASS / FAIL | Human hợp lý. Reply xin lỗi nhiều nhưng báo 55.000đ khi ledger ghi 35.000đ. | Kiểm tra đúng tiền trước, sau đó chấm mức hữu ích từ dữ kiện và bước tiếp theo. |
| HL-047 | PASS / FAIL | Human hợp lý. Cách xưng “Ok bạn” lệch chuẩn, “xử lý rồi nhé” thiếu trạng thái hoặc hành động cụ thể. | Yêu cầu reply nêu trạng thái hoặc hướng xử lý tiếp theo bằng cách xưng hô phù hợp. |

Giữ nguyên nhãn CSV để tái lập số đo. Cần held-out mới với nhãn người và rà lại các ca tranh cãi trước khi dùng judge cho quyết định thực tế. Tiền và approval do grader code kiểm.
