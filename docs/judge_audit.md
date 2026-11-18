# Judge audit

Chạy: `python -m lab9.judge --csv <file> --audit 5` (FAIL là lớp dương: việc của judge là tìm lỗi).

| Tiêu chí | n | κ | Precision | Recall | Đạt FLOORS (κ≥0.6, P≥0.8, R≥0.7)? | Quyết định |
|---|---|---|---|---|---|---|
| tone_ok | 100 | 0.757 | 0.857 | 0.800 | Đạt | **dùng** (chỉ cho tone, không chặn release) |
| helpful | 100 | 0.375 | 1.000 | 0.300 | **Không** (κ và R dưới sàn) | **loại** |

Ma trận nhầm lẫn:
- tone_ok: tp 24 · fp 4 · fn 6 · tn 66. Tỉ lệ FAIL judge quan sát được 0.28 → Rogan-Gladen hiệu chỉnh **0.30** (sens 0.80, spec 66/70 = 0.943).
- helpful: tp 9 · fp 0 · fn 21 · tn 70. Judge quan sát 0.09 → hiệu chỉnh **0.30**. Judge bỏ sót 21/30 reply hỏng.

## ≥5 case audit thủ công
| # | Case | Judge nói | Người nói | Ai đúng? | Ghi chú / sửa rubric |
|---|---|---|---|---|---|
| 1 | H-008 "Em đã hoàn tiền cho anh rồi nha, anh check giúp em." | PASS | FAIL | Người | Xưng "em" + "nha" quá suồng sã với khách khiếu nại. Rubric: thêm quy tắc xưng hô "LogiX – anh/chị", liệt kê từ cấm ("nha", "nhé", "bạn ơi") kèm ví dụ FAIL. |
| 2 | H-017 "Dạ, bạn ơi LogiX đã hoàn 25.000đ…" | PASS | FAIL | Người | Cùng lỗi xưng hô. Judge coi "thân thiện" là "lịch sự". Rubric tách hai ý: thân thiện không bù được cho xưng hô sai. |
| 3 | H-029 "Dạ, vui lòng chờ. … không cần nhắn thêm." | PASS | FAIL | Người | Judge chỉ bắt từ khóa lịch sự ("Dạ", "vui lòng"). Rubric: câu mệnh lệnh / cấm khách liên hệ = FAIL, dù có "Dạ". |
| 4 | H-042 "Dạ, đơn O-808 đã hoàn 120.000đ. Tiền về trong 3–5 ngày ạ." | FAIL | PASS | Người | Judge phạt vì "thiếu xin lỗi". Rubric: xin lỗi **không bắt buộc** khi đã giải quyết xong; ngắn gọn, đủ ý là PASS. |
| 5 | H-051 "Dạ, LogiX đã refund 90.000đ…" | FAIL | PASS | Người | CS LogiX cho phép từ "refund". Rubric: thêm whitelist thuật ngữ được dùng (refund, ship, COD). |
| 6 | H-081 "Dạ, đơn O-107 chưa đủ điều kiện hoàn…" | FAIL | PASS | **Judge** | Người đọc nhầm ticket. **Sửa nhãn người** thành FAIL. Tính lại với nhãn đã sửa: tp 25 · fp 3 · fn 6 · tn 66, κ 0.757 → 0.784, P 0.893, R 0.806 (CSV công khai giữ nguyên, số này chỉ để tham khảo). Bài học: bất đồng không phải lúc nào cũng là lỗi judge, phải audit cả hai phía. |
| 7 | H-094 "Da, LogiX da hoan 40.000đ…" (mất dấu) | PASS | FAIL | Người | Rubric: tiếng Việt mất dấu / dịch máy = FAIL. |
| 8 | HL-015 "Dạ, LogiX đã hoàn 55.000đ cho đơn O-112 ạ." (ledger 40.000đ) | PASS | FAIL | Người | Judge helpful không thấy ledger nên không biết reply sai tiền. Đây là FM-08: phải chấm bằng code (`reply_amount_matches_ledger`), không bằng judge. |
| 9 | HL-016 xin lỗi dài 3 câu + "đã hoàn 55.000đ" (ledger 35.000đ) | PASS | FAIL | Người | Judge bị câu xin lỗi dài, trôi chảy đánh lừa (verbosity bias), trong khi số tiền sai. |
| 10 | HL-047 "Ok bạn, đơn O-515 xử lý rồi nhé." | PASS | FAIL | Người | Không nói kết quả, không nói số tiền. Rubric helpful: phải nêu kết quả (hoàn bao nhiêu / vì sao không hoàn / bước tiếp theo). |

## Kết luận
- **tone_ok dùng được**: κ 0.757, P 0.857, R 0.80 đều trên sàn. Chỉ dùng để theo dõi chất lượng giọng văn, không đặt làm cổng chặn tiền. 6/10 bất đồng là judge bỏ sót lỗi xưng hô/giọng mệnh lệnh (fn = 6). Sửa rubric theo bảng trên rồi calibrate lại trên nhãn mới.
- **helpful bị loại** và **không được dùng làm gate**: R = 0.30 (fn 21 / 30 lỗi thật), κ = 0.375 < 0.6. P = 1.0 chỉ có nghĩa là judge hiếm khi nói FAIL. Một gate dựa trên nó sẽ cho qua 70% reply hỏng. 18/21 lỗi bị bỏ sót là reply nói sai số tiền so với ledger (3 lỗi còn lại là "Ok bạn, … xử lý rồi nhé": không nêu kết quả). Judge không thấy ledger, lại bị câu xin lỗi dài kéo điểm lên. Lỗi này chuyển sang grader code `reply_amount_matches_ledger` (FM-08). Phần "reply có nêu kết quả không" cần rubric mới và tập nhãn mới trước khi đánh giá lại judge.
- Tỉ lệ lỗi thật ước tính (Rogan-Gladen) là ~0.30 cho cả hai tiêu chí. Riêng helpful, con số thô 0.09 đánh giá thấp vấn đề hơn 3 lần.
- Rủi ro còn lại: judge chỉ được kiểm trên dữ liệu replay đã công khai (100 dòng mỗi tiêu chí). Cần nhãn người mới để có held-out thật; κ trên 100 mẫu vẫn có khoảng tin cậy rộng (khoảng ±0.1).
