# JD Institute ERP — Documentation

There are two separate manuals. Pick the one that matches who you are.

---

## 📘 For people who **use** the software

**→ [User Guide](user-guide/README.md)**

Step-by-step instructions for everyday work: finding a screen, adding a lead,
collecting a fee, taking attendance, applying for leave, and so on. Written in
plain language, organised around tasks. No technical knowledge assumed.

For: counsellors, admissions staff, accounts, faculty, HODs, batch mentors, HR,
auditors, administrators, students and parents.

## 🛠 For people who **build and maintain** the software

**→ [Technical Documentation](technical/README.md)**

Architecture, data model, module-by-module reference, API surface, permission
system, integrations, deployment and change-impact analysis.

For: developers, technical leads and anyone taking over maintenance.

---

## Which one answers my question?

| Question | Manual |
|---|---|
| "How do I send a fee link to a lead?" | User Guide |
| "Why can't I see the Leaves menu?" | User Guide |
| "The student says they never got the SMS." | User Guide first, then Technical if it needs investigation |
| "What happens to attendance if I cancel a class?" | Both — User Guide for the effect, Technical for the mechanics |
| "How do I add a new permission?" | Technical |
| "Which server does email go through?" | Technical |
| "How do I set this up on a new machine?" | Technical |

## Other documents in this repository

| File | Contents |
|---|---|
| [`../deploy-VPS.md`](../deploy-VPS.md) | Server deployment guide |
| [`technical/scope_employee.md`](technical/scope_employee.md) | Original scope notes for the Employee module |
| [`technical/scope_leave.md`](technical/scope_leave.md) | Original scope notes for the Leave module |
| `../PROGRESS_REPORT.md` | Historical build-progress report |

The frontend repository (`jd-erp-web`) additionally carries
`BATCH_REPORT_DOCUMENTATION.md`, `CLOSING_REPORT_DOCUMENTATION.md` and
`LEAVE_MODULE_DOCUMENTATION.md` for those three screens.
