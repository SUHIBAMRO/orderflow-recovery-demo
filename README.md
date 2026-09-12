# OrderFlow Recovery

Working **synthetic** order-recovery prototype, with an operations console, durable business state, real local HTTP provider simulation, bounded retries, human actions, role-gated roadtax refunds and audit evidence.

**Status:** 25 portable/core and real-HTTP tests passed during creation. JavaScript syntax and Python compilation passed. Full Docker/FastAPI/PostgreSQL/Temporal deployment and browser visual QA are **not yet verified**. No public deployment or GitHub repository was created.

`railway.json` and `Dockerfile.demo` provide a lightweight public mode that opens without a token. It runs SQLite plus synthetic local HTTP provider APIs and is explicitly not the full Temporal/PostgreSQL stack. Public visitors share synthetic data; never enter real information.

## ابدأ من هنا

هذه نسخة أولى قابلة للتجربة من نظام معالجة طلبات التأمين المتعطلة. الواجهة مرتبطة بـbackend، والحالات والأحداث محفوظة فعلًا. خدمات التأمين وJPJ والدفع والإشعارات **تجريبية** ولا تتعامل مع مال أو وثائق حقيقية.

**ما اختُبر:** 25 اختبارًا لمنطق المعالجة وواجهات HTTP، تشمل منع التكرار، الاستكمال بعد تصحيح البيانات، صلاحيات الاسترجاع، واستعادة الحالة بعد الفشل.

**ما لم يُختبر هنا:** تشغيل Docker وPostgreSQL وTemporal معًا، والفحص البصري داخل المتصفح. تفسير النصوص قاعدة بسيطة معلنة، وليس نموذج ذكاء اصطناعي. لا تستخدم المشروع مع عملاء حقيقيين قبل إكمال المراجعة والتكامل والحماية.

### تجربة سريعة — Python فقط

تحتاج Python 3.11 أو أحدث على الكمبيوتر. فك الضغط، افتح الطرفية داخل مجلد المشروع، ثم:

```sh
python scripts/setup_env.py
python scripts/run_local.py
```

افتح `http://127.0.0.1:8080` في متصفح **نفس الكمبيوتر**. افتح ملف `.env` محليًا وانسخ قيمة `OPERATOR_TOKEN` إلى حقل الدخول. لا ترسل هذه القيم في المحادثات ولا تنشرها. للاسترجاع استخدم `SUPERVISOR_TOKEN`.

هذا الوضع يشغّل قاعدة SQLite وخدمات HTTP تجريبية بنفس منطق المعالجة، لكنه **لا يشغّل Temporal**. البيانات تبقى داخل `data/` بعد إعادة التشغيل. لإيقافه استخدم Ctrl+C.

### تشغيل الحزمة الكاملة — Docker

تحتاج Docker مع Compose v2. بعد إنشاء `.env` بالأمر السابق:

```sh
docker compose up --build -d
python scripts/smoke_compose.py
```

افتح نفس عنوان الواجهة. هذا المسار يشغّل FastAPI وPostgreSQL وTemporal وخدمة المحاكاة. سكربت الفحص يختبر السيناريوهات والاستكمال بعد إعادة تشغيل العامل. **أُرفق السكربت ولكنه لم يُشغّل في بيئة الإنشاء لعدم توفر Docker.** أول تشغيل يحتاج اتصالًا لتنزيل الصور والحزم.

إذا كنت تشغّل الوضع السريع، أوقفه قبل Docker لأن كليهما يستخدم المنفذ 8080. لإيقاف حاويات التجربة مع الاحتفاظ بالبيانات:

```sh
docker compose down
```

## Quick start (English)

Python-only verification: run `python scripts/setup_env.py`, then `python scripts/run_local.py`. Open `http://127.0.0.1:8080` on the same computer and sign in with a role token from local `.env`. This runs the same decision engine with SQLite and real synthetic HTTP endpoints, **not Temporal**.

Full deployment: run `docker compose up --build -d`, then `python scripts/smoke_compose.py`. This stack was prepared, not executed in the creation environment. Never expose it publicly or handle real customer data without the hardening work listed in `docs/ARCHITECTURE.md`.

## Demo walkthrough / سيناريو العرض

1. **Owner mismatch:** create a test order → wait for Data correction → inspect evidence → Correct & continue → enter four synthetic digits and an audit note → observe Completed. The policy reference stays unchanged.
   **اختلاف البيانات:** أنشئ طلبًا، افحص سبب التوقف، صحّح آخر أربع خانات تجريبية واكتب سبب الإجراء. يكمل الطلب دون إصدار التأمين مرة ثانية.
2. **Temporary outage:** create an Insurer timeout order → observe two scheduled retries → third call succeeds.
   **عطل مؤقت:** شاهد محاولتي الانتظار ثم نجاح المحاولة الثالثة.
3. **Lost acknowledgement:** the mock issues the policy before losing its response. The next call returns the same policy reference, rather than creating another policy.
   **ضياع الرد:** تصدر الوثيقة تجريبيًا، ثم تضيع الاستجابة؛ الاستعادة تعيد نفس المرجع ولا تنشئ وثيقة ثانية.
4. **Blacklist:** observe Refund approval. An operator cannot approve. Sign out, use the supervisor token, select the order and authorize the roadtax-only refund.
   **الحظر:** تنشأ حالة انتظار موافقة استرجاع. حساب المشغّل لا يستطيع الموافقة. المشرف يوافق على مبلغ ضريبة المركبة فقط دون إلغاء التأمين.
5. **Missing photos:** synthetic notification is recorded, then the order waits for an operator's receipt confirmation. This is not real upload/verification.
   **الصور الناقصة:** يُسجل طلب إشعار تجريبي، ثم ينتظر النظام تأكيد المشغّل. رفع الصور وفحصها الحقيقي ليسا ضمن هذه النسخة.

## Tests / الاختبارات

```sh
python -m unittest discover -s tests -v
python -m compileall -q orderflow scripts tests
node --check web/app.js
```

Node is needed only for the last JavaScript syntax check, not to run the UI. The Python tests use temporary databases and synthetic identities; no external accounts or paid APIs are called.

See `docs/VALIDATION.md` for the actual verification boundary and `docs/ARCHITECTURE.md` for guarantees and limitations.

## API contract

All `/api/*` requests require `Authorization: Bearer <role token>`. POST order/action requests also require a client-generated `Idempotency-Key`. FastAPI exposes its generated OpenAPI at `/openapi.json` when the full stack runs.

| Endpoint | Purpose |
|---|---|
| `GET /api/session` | Current demo role and runtime mode |
| `GET /api/orders` | Latest 500 persisted orders |
| `POST /api/orders` | Create a synthetic order; duplicate keys return the original |
| `GET /api/orders/{id}` | Current order and append-only application audit events |
| `POST /api/orders/{id}/actions/{action}` | Version-checked, role-checked operator command |
| `POST /api/classify` | Read-only deterministic text interpretation, not an LLM |
| `GET /healthz` | API/database readiness; not worker readiness |

Actions: `confirm_photos`, `correct_owner`, `approve_refund`, `retry`, `escalate`.

Action JSON includes `expected_version` and an 8–500 character `note`; correction also requires `owner_last4`. Creation supports `scenario`, `customer`, `vehicle`, `owner_last4`, `roadtax_cents`. Currency is fixed to MYR; amounts are integer cents.

This is an independent prototype, not a BJAK product, approved integration or compliance certification.
