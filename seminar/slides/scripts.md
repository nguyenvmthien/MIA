# Presentation Scripts — Meeting AI Agent

---

## Slide 00 — Cover

> "Xin chào thầy cô và các bạn. Trước khi bắt đầu, cho em hỏi nhanh: sau cuộc họp gần nhất, mọi người có nhớ chính xác ai làm gì không ạ?"

> "Đó chính là lý do nhóm em làm Meeting AI Agent: biến audio cuộc họp thành danh sách đầu việc rõ ràng, có người phụ trách và deadline."

> "Điểm khác biệt quan trọng: chạy local, không đẩy dữ liệu nội bộ lên cloud."

> "Tiếp theo, mình nhìn vào vấn đề thực tế để thấy vì sao bài toán này đáng làm."

---

## Slide 01 — The Problem

> "Vấn đề không nằm ở việc thiếu họp, mà nằm ở việc sau họp không ai chắc task thuộc về ai."

> "Mình thường gặp 3 chuyện: ghi chú thiếu, giao việc mơ hồ, và follow-up đứt đoạn."

> "Khi dùng công cụ cloud, lại thêm một nỗi lo khác: dữ liệu nội bộ đi ra ngoài."

> "Nên mục tiêu của nhóm là giải đồng thời 2 bài toán: tự động hóa và bảo mật."

> "Vậy giải pháp kỳ vọng của người dùng trông như thế nào? Mình qua slide Vision."

---

## Slide 02 — Vision

> "Vision rất đơn giản: upload audio vào, vài phút sau nhận kết quả có cấu trúc."

> "Kết quả gồm: tóm tắt, action items, assignee, deadline, priority, và confidence."

> "Task nào hệ thống chưa chắc thì không chốt bừa, mà đưa sang human review."

> "Nói dễ nhớ: bớt việc tay chân, tăng trách nhiệm rõ ràng."

> "Để làm được điều đó, kiến trúc hệ thống được tổ chức ra sao?"

---

## Slide 03 — System Overview

> "Mình đi theo một hành trình: user upload audio -> backend nhận job -> worker xử lý -> trả kết quả."

> "Backend không bắt người dùng chờ toàn bộ pipeline. Nó tạo job_id ngay, còn phần nặng chạy ở nền."

> "Ở lõi AI: ASR chuyển giọng nói thành text, LLM trích xuất task, guardrails kiểm tra trước khi trả về."

> "Ở lớp dữ liệu: PostgreSQL lưu kết quả chính; Redis lo queue và cache để phản hồi nhanh hơn."

> "Ở lớp quan sát: Prometheus + Grafana theo dõi sức khỏe hệ thống, LangSmith theo dõi hành vi từng lần gọi LLM."

> "Có bức tranh tổng thể rồi, giờ mình zoom vào pipeline từng bước."

---

## Slide 04 — Pipeline Detail

> "Pipeline có 7 bước, nhưng có thể nhớ gọn thành 3 pha: nghe -> hiểu -> kiểm tra."

> "Pha nghe: ingest và preprocess để chuẩn hóa audio."

> "Pha hiểu: STT + LLM để tạo transcript, summary, action items."

> "Pha kiểm tra: guardrails + confidence scoring + human review cho các task mơ hồ."

> "Cuối cùng, hệ thống lưu output và ghi metrics để lần sau đo được tốt hơn hay chưa."

> "Nhắc lại một điểm quan trọng: pipeline chạy async bằng Celery, nên UX mượt hơn rất nhiều."

> "Tiếp theo, mình giải thích ngắn gọn AI stack bên trong để người không chuyên cũng theo được."

---

## Slide 05 — AI/ML Stack

> "AI stack của nhóm có 3 lớp."

> "Lớp 1: ASR, dùng WhisperX để đổi audio thành transcript có mốc thời gian."

> "Lớp 2: RAG cho assignment. Ở đây có 2 khái niệm: embedding và FAISS."

> "Embedding là đổi text thành vector; FAISS là công cụ tìm vector gần nhất rất nhanh."

> "Nhờ vậy, khi transcript gọi nickname như 'anh Bob', hệ thống vẫn map được về đúng người trong roster."

> "Lớp 3: LLM Qwen qua Ollama để sinh kết quả JSON theo schema mong muốn."

> "Model mạnh là một phần, nhưng nếu không có guardrails thì vẫn rủi ro. Mình qua phần đó ngay sau đây."

---

## Slide 06 — Prompt Engineering & Guardrails

> "Ở slide này, tụi em tập trung vào câu hỏi: làm sao để output vừa đúng, vừa an toàn?"

> "Prompt được thiết kế có roster + schema rõ ràng để giảm bịa assignee."

> "Guardrails kiểm tra 2 đầu: đầu vào (PII masking) và đầu ra (schema, assignee, date sanity)."

> "Nếu lỗi, hệ thống retry có kiểm soát. Nếu vẫn không ổn, chuyển human review."

> "Điểm mấu chốt: không cố tỏ ra thông minh bằng mọi giá, mà ưu tiên an toàn và kiểm chứng được."

> "Khi inference ổn, bước tiếp theo để nâng chất lượng là training pipeline."

---

## Slide 07 — Training Pipeline

> "Training pipeline của nhóm đi theo nguyên tắc: data sạch trước, train sau."

> "Validator xử lý duplicate, leakage, schema lỗi trước khi fine-tune."

> "Fine-tune dùng QLoRA để giảm chi phí tài nguyên, tracking bằng MLflow để so sánh version rõ ràng."

> "Model mới chỉ release khi vượt eval gate. Nếu kém hơn model cũ thì dừng."

> "Vậy dữ liệu đến từ đâu để vòng train này thực sự hiệu quả?"

---

## Slide 08 — Data Pipeline

> "Nhóm dùng 3 nguồn data: real meetings, public corpus và synthetic."

> "Real data cho độ sát nghiệp vụ cao nhất; synthetic giúp phủ edge cases ít gặp."

> "Phần quan trọng nhất là feedback loop: user sửa sai -> hệ thống ghi nhận -> đủ ngưỡng thì retrain."

> "Nhờ vậy mô hình tốt dần theo chính cách team làm việc thực tế."

> "Đã có data + training, giờ cần một thứ để biết hệ thống có vận hành khỏe hay không: monitoring."

---

## Slide 09 — Monitoring & Observability

> "Nhóm chia observability thành 3 lớp để dễ quản trị."

> "Prometheus thu metrics, Grafana trực quan hóa và cảnh báo."

> "LangSmith theo dõi từng LLM call: prompt, response, token, latency."

> "Nếu Prometheus trả lời câu hỏi 'hệ thống có khỏe không', thì LangSmith trả lời 'nó đang nghĩ gì khi ra quyết định'."

> "Có lớp quan sát rồi, mình quay lại vòng cải tiến để thấy hệ thống không đứng yên."

---

## Slide 10 — Feedback Loop

> "Đây là vòng lặp cốt lõi của dự án: upload -> xử lý -> review -> correction -> retrain -> deploy."

> "Mỗi correction của user không bị lãng phí, mà trở thành dữ liệu học cho phiên bản sau."

> "Nghĩa là chất lượng không phụ thuộc một lần train ban đầu, mà tăng dần theo thời gian sử dụng."

> "Vậy hiện tại kết quả đang ở mức nào?"

---

## Slide 11 — Evaluation Results

> "Điểm mạnh hiện tại: schema ổn định, hallucination thấp."

> "Điểm còn cần cải thiện: precision/recall trong vài tình huống paraphrase và merge task."

> "Nhưng điều tích cực là nhóm đã đo được baseline rõ ràng, nên roadmap tối ưu có mục tiêu cụ thể."

> "Sau phần chất lượng, mình đối chiếu lại với checklist LLMOps của môn học."

---

## Slide 12 — LLMOps Coverage

> "Điểm quan trọng của đồ án này là không dừng ở inference demo."

> "Nhóm đã có đầy đủ chu trình LLMOps: data, train, eval, deploy, monitor, feedback, retrain."

> "Nghĩa là sản phẩm có khả năng sống lâu, không phải làm một lần rồi bỏ."

> "Tiếp theo là câu hỏi triển khai thực tế: scale thế nào?"

---

## Slide 13 — Scalability & Deployment

> "Deployment dùng Docker Compose để lên nhanh trên nhiều môi trường."

> "CPU chạy mặc định; máy có GPU thì bật thêm override file."

> "Khi tải tăng, có thể scale worker và thêm endpoint Ollama để chia tải."

> "Mục tiêu của nhóm là từ laptop demo đến server production vẫn giữ cùng một luồng vận hành."

> "Bây giờ mình cho mọi người xem đầu ra thật sự mà user nhận được."

---

## Slide 14 — Demo Output

> "Đây là thứ user quan tâm nhất: kết quả có dùng được không."

> "Output có transcript, summary, action items, confidence, và nhóm human review."

> "Sự khác biệt lớn là hệ thống biết nói 'tôi chưa chắc' thay vì trả một kết quả nghe có vẻ đúng nhưng sai."

> "Từ demo này, mình chốt lại giá trị và hướng đi tiếp theo ở slide cuối."

---

## Slide 15 — Roadmap & Conclusion

> "Tổng kết nhanh bằng 4 từ khóa: privacy, automation, accountability, continuous learning."

> "Roadmap tiếp theo của nhóm là nâng F1 bằng dữ liệu thật, tích hợp sâu hơn vào workflow doanh nghiệp, và mở rộng quy mô vận hành."

> "Cảm ơn thầy cô và các bạn đã lắng nghe. Nếu thầy cô muốn, nhóm em xin demo trực tiếp một job từ audio đến action items ngay tại chỗ."
