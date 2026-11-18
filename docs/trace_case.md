# Trace case: từ trace tới quyết định sai đầu tiên

Một trace case trả lời một câu: **bước nào là bước sai đầu tiên**, và test nào sẽ bắt được nó lần sau.

```bash
cd src
python -m lab9.trace_case --shape seeded_regression --claim C-014 --seed 11
python -m lab9.trace_case --shape fixed --claim C-014 --seed 11   # đối chứng
```

## Case: `seeded_regression` C-014@11 (FM-05)

```
== seeded_regression C-014@11  lab8 grader: FAIL (proposal_mismatch)
   1 handoff            {... "task": "check_applicable_policy" ...}
   2 investigator       {"lookup_order": {"visible": true, "order": {"order_id": "O-515", "status": "delivered_late", ...
   3 quote              {"amount_vnd": 150000, "clause_ids": ["SHIP-LATE-03", "DMG-04"], "parts": {"SHIP-LATE-03": 30000, "DMG-04": 150000}}
   4 refund_history     {"refund_count": 1, "refunded_vnd": 30000}
   5 proposal           {"amount_vnd": 120000}
   6 reply              {"text": "Dạ, LogiX đã hoàn 120.000đ cho đơn O-515."}
  refund_vnd     ledger=90000    label=120000   <-- differs
  status         result=resolved label=resolved
```

| Trường | Nội dung |
|---|---|
| Trial | `seeded_regression C-014@11`, report `E-seeded_regression-20261118-a835` (item E-014, fail ở cả 5 seed) |
| Triệu chứng | `pass_rate` False (`proposal_mismatch`), `refund_amount_correct` False (ledger 90000, nhãn 120000), `reply_amount_matches_ledger` False (reply nói 120.000đ, ledger giữ 90.000đ), `proposal_amount_correct` False (120000, nhãn 150000). Status `resolved` khớp nhãn, nên chỉ nhìn status thì không thấy lỗi. |
| Bước sai đầu tiên | **Event 5 `proposal` `{"amount_vnd": 120000}`**: agent lấy quote 150000 trừ 30000 đã hoàn rồi mới gọi host. |
| Vì sao là bước *đầu tiên* | Event 2: order O-515 đọc từ DB đúng. Event 3: `compute_compensation` trả 150000 = max(30000, 150000), đúng luật "lấy số lớn hơn". Event 4: `lookup_refund_history` là read tool hợp lệ, trả đúng 30000. Lỗi chỉ xuất hiện khi agent dùng số đó để tự trừ (event 5). Host áp trần theo đơn, trừ 30000 thêm lần nữa: 120000 − 30000 = 90000. |
| Failure mode | **FM-05** pre_deducted, kèm **FM-08** (reply nói số agent tự tính, không phải số ledger). |
| Đối chứng | `fixed C-014@11`: event 3 `quote` 150000 → không có `refund_history`/`proposal`, quote đầy đủ được đưa thẳng vào host, ledger 120000, reply "120.000đ", Lab 8 PASS. |
| Regression test | `tests/test_lab9_trace_case.py::test_lab9_trace_case_fm05_pre_deducted_c014`: event `proposal` đứng ngay sau `refund_history` và bằng 120000; `RefundAmountCorrect`, `ProposalAmountCorrect`, `ReplyAmountMatchesLedger` đều False trên `seeded_regression`, đều True trên `fixed`. Đã chạy: pass (marker `student`, nằm trong job `eval-gate`). Item E-014 có `provenance.from_trace = "seeded_regression C-014@11"`. |
| Chưa chắc chắn | Trace không ghi lời gọi `issue_refund` của host, nên phép trừ lần hai được suy ra từ ledger (90000) và luật trần theo đơn, không thấy trực tiếp trong trace. MockLLM deterministic nên không biết model thật có tự trừ ở cùng bước này không. |

## Case phụ: lỗi chỉ grader FM-08 bắt được (C-008@11)
`seeded_regression C-008@11`: Lab 8 grader **PASS** (ledger 20000 đúng nhãn, vì approval chặn ở 20000), nhưng **event 5 `reply`** báo khách "đã hoàn 35.000đ". Bước sai đầu tiên là event 5 (event 3 `quote` 35000 là đúng, `proposal_amount` vẫn là quote theo luật). Test: `test_lab9_trace_case_fm08_reply_lies_while_lab8_passes_c008`.

## Quy tắc

- Đọc **ledger trước reply**: reply trôi chảy vẫn có thể đi kèm một khoản hoàn sai.
- "Bước sai đầu tiên" phải dẫn số event cụ thể, không phải "agent bị nhầm".
- Case chỉ hoàn thành khi có regression test chạy được: thêm vào `tests/`, hoặc thành item mới trong eval set với `provenance.from_trace`.
