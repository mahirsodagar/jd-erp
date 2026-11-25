"""The catalogue of every system e-mail — the single source of truth
for the Email Template Management page (Communication → System Emails).

One `Trigger` per outbound mail: what fires it, who receives it, the
variables its code guarantees to fill, and the default subject/body the
system falls back to when no admin has customised it (globally or for
one institute). Admins edit subject, body, Reply-To and extra CC from
the page; recipients stay code policy (client decision 2026-11-25).

Variable naming follows the client's MSG91 style — `{{Student_Name}}`.
The twelve client-supplied HTML bodies in `email_html/` still use their
original names (`{{name}}`, `{{VAR1}}`…); `Trigger.aliases` maps those
to the canonical name so the shipped defaults keep rendering, and the
lint on save accepts both spellings.

Adding a mail:
  1. add a Trigger here (variables = what your context builder fills),
  2. build the context with `apps.notifications.context` helpers,
  3. call `apps.notifications.services.send_system_email(key, ...)`.
Never add a new f-string mail body anywhere else.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .email_html import has_html, load_html


@dataclass(frozen=True)
class Var:
    name: str
    label: str
    example: str
    required: bool = False


@dataclass(frozen=True)
class Trigger:
    key: str
    group: str
    label: str
    description: str
    recipients: str
    variables: tuple[Var, ...]
    default_subject: str
    #: HTML body. `None` = loaded from email_html/<key>.html.
    default_body: str | None = None
    #: Old placeholder spelling → canonical name (for the shipped HTML).
    aliases: dict[str, str] = field(default_factory=dict)
    #: Whether the institute header/footer layout wraps this body by
    #: default. Off for client designs that carry their own masthead.
    use_layout: bool = True
    #: What the code attaches on its own (shown read-only on the page).
    attachments_note: str = ""

    def body(self) -> str:
        if self.default_body is not None:
            return self.default_body
        return load_html(self.key) if has_html(self.key) else ""

    def var_names(self) -> set[str]:
        return {v.name for v in self.variables}

    def allowed_names(self) -> set[str]:
        """Every placeholder the lint accepts for this trigger."""
        return self.var_names() | set(self.aliases) | COMMON_NAMES


# --- Shared variable sets -----------------------------------------------

#: Filled for EVERY mail from the institute / campus the mail concerns
#: (routing context `institute_code` / `campus_code`). Also what the
#: layout header/footer may use.
COMMON_VARS: tuple[Var, ...] = (
    Var("Institute_Name", "Institute name", "JD Institute of Fashion Technology"),
    Var("Institute_Short_Name", "Institute code", "JDIFT"),
    Var("Institute_Logo_Url", "Institute logo URL", "https://erp.example.com/media/institute/logos/jdift.png"),
    Var("Institute_Address", "Institute address (HTML lines)", "No. 20, 1st Floor, 100 Feet Road<br>Indiranagar, Bengaluru 560038"),
    Var("Institute_Phone", "Institute phone", "+91 80 4040 0000"),
    Var("Institute_Email", "Institute email", "info@jdinstitute.edu.in"),
    Var("Campus_Name", "Campus name", "Bengaluru"),
    Var("Campus_Address", "Campus address (HTML lines)", "No. 20, 1st Floor, 100 Feet Road<br>Indiranagar, Bengaluru 560038"),
    Var("Campus_Phone", "Campus phone", "+91 80 4040 0000"),
    Var("Today", "Today's date", "25-11-2026"),
    Var("Current_Year", "Current year", "2026"),
)
COMMON_NAMES = {v.name for v in COMMON_VARS}

#: Routing keys callers put in the context for Reply-To / CC resolution
#: and institute lookup. Never template variables; the lint ignores them.
ROUTING_KEYS = {"reply_to", "campus_code", "institute_code"}

STUDENT_VARS: tuple[Var, ...] = (
    Var("Student_Name", "Student full name", "Ananya Sharma", required=True),
    Var("First_Name", "Student first name", "Ananya"),
    Var("Student_Email", "Student personal email", "ananya@example.com"),
    Var("Student_Phone", "Student mobile", "9876543210"),
    Var("Application_ID", "Application form number", "JDIFT/2026/00123"),
    Var("Registration_No", "Registration number", "JDB26F0123"),
    Var("Father_Name", "Father's name", "Rajesh Sharma"),
    Var("Mother_Name", "Mother's name", "Priya Sharma"),
    Var("Parent_Name", "Parent's name (father, else mother)", "Rajesh Sharma"),
    Var("Father_Email", "Father's email", "rajesh@example.com"),
    Var("Mother_Email", "Mother's email", "priya@example.com"),
    Var("Father_Phone", "Father's mobile", "9876500000"),
    Var("Mother_Phone", "Mother's mobile", "9876511111"),
)

PROGRAM_VARS: tuple[Var, ...] = (
    Var("Program_Name", "Program name", "B.Des Fashion Design"),
    Var("Program_Code", "Program code", "BDES-FD"),
    Var("Program_Duration", "Program duration", "3 years"),
    Var("Course_Name", "Course / specialisation name", "B.Des Fashion Design"),
    Var("Course_Duration", "Course duration", "3 years"),
    Var("Degree_Name", "Degree", "Bachelor of Design"),
    Var("University_Name", "Affiliating university", "Bengaluru City University"),
    Var("Academic_Year", "Academic year", "2026-2027"),
    Var("Batch_Name", "Batch", "BDES-FD 2026 BLR"),
    Var("Semester_Name", "Semester", "Semester 1"),
)

LEAD_VARS: tuple[Var, ...] = (
    Var("Student_Name", "Lead's full name", "Ananya Sharma", required=True),
    Var("First_Name", "Lead's first name", "Ananya"),
    Var("Lead_Email", "Lead's email", "ananya@example.com"),
    Var("Lead_Phone", "Lead's mobile", "9876543210"),
    Var("Course_Name", "Program enquired for", "B.Des Fashion Design"),
    Var("Program_Name", "Program enquired for", "B.Des Fashion Design"),
    Var("Program_Duration", "Program duration", "3 years"),
    Var("Counsellor_Name", "Assigned counsellor", "Meera Nair"),
    Var("Counsellor_Email", "Assigned counsellor's email", "meera@jdinstitute.edu.in"),
    Var("Lead_Source", "Lead source", "Website"),
)

EMPLOYEE_VARS: tuple[Var, ...] = (
    Var("Employee_Name", "Employee full name", "Rahul Verma", required=True),
    Var("Employee_Code", "Employee code", "JD0042"),
    Var("Employee_Email", "Employee work email", "rahul.v@jdinstitute.edu.in"),
    Var("Designation", "Designation", "Faculty"),
    Var("Department", "Department", "Fashion Design"),
    Var("Date_Of_Joining", "Date of joining", "01 Jun 2022"),
    Var("Manager_Name", "Reporting manager", "Sunita Rao"),
    Var("Manager_Email", "Reporting manager's email", "sunita.r@jdinstitute.edu.in"),
)

USER_VARS: tuple[Var, ...] = (
    Var("User_Name", "Account holder's name", "Rahul Verma", required=True),
    Var("Username", "Login username", "rahul.v"),
    Var("User_Email", "Account email", "rahul.v@jdinstitute.edu.in"),
)

RECEIPT_VARS: tuple[Var, ...] = (
    Var("Receipt_No", "Receipt number", "RCP00123", required=True),
    Var("Amount", "Amount (formatted)", "25,000.00", required=True),
    Var("Particular", "What the payment was towards", "Installment 1"),
    Var("Receipt_Date", "Date received", "25-11-2026"),
    Var("Payment_Mode", "Mode of payment", "Online"),
)

LEAVE_VARS: tuple[Var, ...] = (
    Var("Leave_Type", "Leave type", "Casual Leave"),
    Var("From_Date", "From date", "02-12-2026"),
    Var("To_Date", "To date", "03-12-2026"),
    Var("Days", "Number of days", "2"),
    Var("Session", "Session (full day / 1st half / 2nd half)", "Full day"),
    Var("Reason", "Reason given", "Family function"),
)


def _vars(*sets: tuple[Var, ...] | list[Var]) -> tuple[Var, ...]:
    """Concatenate variable sets, first definition of a name wins."""
    seen: set[str] = set()
    out: list[Var] = []
    for s in sets:
        for v in s:
            if v.name in seen:
                continue
            seen.add(v.name)
            out.append(v)
    return tuple(out)


def _p(*paragraphs: str) -> str:
    """Default body helper: one <p> per paragraph, so the shipped
    defaults are HTML like everything else the editor saves."""
    return "".join(f"<p>{p}</p>" for p in paragraphs)


_SIGN_ACCOUNTS = "Regards,<br>Accounts Office<br>{{Institute_Name}}"
_SIGN_ADMISSIONS = "Regards,<br>Admissions Office<br>{{Institute_Name}}"
_SIGN_HR = "Regards,<br>HR"
_AUTO = "<em>This is an auto-generated mail. Please do not reply.</em>"


# --- Groups (page sections, in display order) ---------------------------

GROUPS: tuple[tuple[str, str], ...] = (
    ("leads", "Leads / CRM"),
    ("admissions", "Admissions"),
    ("fees", "Fees"),
    ("academics", "Academics"),
    ("student_leaves", "Student leaves"),
    ("employee_leaves", "Employee leaves & comp-off"),
    ("relieving", "Relieving"),
    ("tasks", "Tasks"),
    ("accounts", "Accounts & login"),
)
GROUP_LABELS = dict(GROUPS)


_TRIGGERS: list[Trigger] = [
    # ------------------------------------------------------------------
    # Leads / CRM
    # ------------------------------------------------------------------
    Trigger(
        key="lead.application_link.email", group="leads",
        label="Application form link",
        description="Counsellor clicks Send application link on a lead (after the application fee is marked paid).",
        recipients="To the lead. Reply-To: assigned counsellor, else the campus admissions inbox.",
        variables=_vars(LEAD_VARS, [Var("Application_Form_Link", "Tokenised application form URL", "https://jdsd.netlify.app/#/apply/…", required=True)]),
        default_subject="JD Institute Application Form Link",
        aliases={"name": "Student_Name", "url": "Application_Form_Link", "institute": "Institute_Name"},
    ),
    Trigger(
        key="lead.fee_link.email", group="leads",
        label="Application fee payment link",
        description="Counsellor clicks Send fee link on a lead.",
        recipients="To the lead. Reply-To: assigned counsellor, else the campus admissions inbox.",
        variables=_vars(LEAD_VARS, [Var("Payment_Link", "Payment URL (gateway or manual page)", "https://erp.example.com/api/public/pay/…", required=True)]),
        default_subject="Application Fee Payment Link",
        aliases={"name": "Student_Name", "url": "Payment_Link", "institute": "Institute_Name"},
    ),
    Trigger(
        key="lead.entrance_exam_link.email", group="leads",
        label="Entrance exam link",
        description="Counsellor sends a mapped candidate their personal entrance exam link.",
        recipients="To the lead. Reply-To: assigned counsellor, else the campus admissions inbox.",
        variables=_vars(LEAD_VARS, [
            Var("Exam_Name", "Exam name", "JD Design Aptitude Test 2026", required=True),
            Var("Exam_Link", "Personal exam URL", "https://jdsd.netlify.app/#/exam/…", required=True),
            Var("Exam_Duration", "Duration in minutes", "60"),
            Var("Exam_Window", "Sentence describing the open window", "The exam is open from 01 Dec 2026, 10:00 AM to 01 Dec 2026, 06:00 PM."),
        ]),
        default_subject="Your JD entrance exam link — {{Exam_Name}}",
        default_body=_p(
            "Dear {{Student_Name}},",
            "You have been scheduled for the JD entrance exam: <strong>{{Exam_Name}}</strong>.",
            "{{Exam_Window}}<br>Once you begin you will have {{Exam_Duration}} minutes to finish, so please make sure you have a stable internet connection before you start.",
            "Click the link below to take the exam — it is personal to you, please do not share it:<br><a href=\"{{Exam_Link}}\">{{Exam_Link}}</a>",
            "All the best!",
            "With Regards,<br>JD Admissions Team",
        ),
        aliases={"name": "Student_Name", "exam": "Exam_Name", "url": "Exam_Link", "duration": "Exam_Duration", "window": "Exam_Window"},
    ),
    Trigger(
        key="lead.welcome.email", group="leads",
        label="Welcome note",
        description="Counsellor sends the welcome note to a lead (Send → Welcome note).",
        recipients="To the lead. Reply-To: assigned counsellor, else the campus admissions inbox.",
        variables=LEAD_VARS,
        default_subject="Welcome Note for New Students and Parents",
        aliases={"name": "Student_Name"},
    ),
    Trigger(
        key="lead.inactive.email", group="leads",
        label="Lead moved to Inactive",
        description="Fires when a lead's status changes to Inactive.",
        recipients="To the lead. Reply-To: assigned counsellor, else the campus admissions inbox.",
        variables=LEAD_VARS,
        default_subject="We'd love to stay in touch | JD Institute",
    ),
    Trigger(
        key="lead.non_responsive.email", group="leads",
        label="Lead moved to Non Responsive",
        description="Fires when a lead's status changes to Non Responsive.",
        recipients="To the lead. Reply-To: assigned counsellor, else the campus admissions inbox.",
        variables=LEAD_VARS,
        default_subject="JD Institute | Course Inquiry Follow-up",
    ),
    Trigger(
        key="lead_welcome_email", group="leads",
        label="New lead — automatic welcome",
        description="Fires automatically the moment a new lead is created (website, walk-in, import).",
        recipients="To the lead. Reply-To: assigned counsellor, else the campus admissions inbox.",
        variables=LEAD_VARS,
        default_subject="Welcome to JD Institute, {{Student_Name}}!",
        default_body=_p("Hi {{Student_Name}},", "Thanks for your interest in {{Program_Name}}. Our counsellor will be in touch shortly.", "— Team JD"),
        aliases={"name": "Student_Name", "program": "Program_Name"},
    ),
    Trigger(
        key="hot_why_join_jd", group="leads",
        label="Follow-up outcome HOT — Why join JD",
        description="Fires when a counsellor logs a follow-up with outcome HOT.",
        recipients="To the lead. Reply-To: assigned counsellor, else the campus admissions inbox.",
        variables=LEAD_VARS,
        default_subject="Why JD is right for you, {{Student_Name}}",
        default_body=_p("Hi {{Student_Name}},", "Here is why hundreds of students choose JD every year for {{Program_Name}}.", "— Team JD"),
        aliases={"name": "Student_Name", "program": "Program_Name"},
    ),
    Trigger(
        key="campus_visit_confirmation", group="leads",
        label="Campus visit confirmed",
        description="Fires when a HOT follow-up has the disposition “Planning to visit the campus”.",
        recipients="To the lead. Reply-To: assigned counsellor, else the campus admissions inbox.",
        variables=LEAD_VARS,
        default_subject="Your campus visit is confirmed",
        default_body=_p("Hi {{Student_Name}},", "We look forward to meeting you at our {{Campus_Name}} campus.", "— Team JD"),
        aliases={"name": "Student_Name", "campus": "Campus_Name"},
    ),
    Trigger(
        key="post_visit_thanks", group="leads",
        label="Thanks for visiting",
        description="Fires when a HOT follow-up has the disposition “Campus visit done”.",
        recipients="To the lead. Reply-To: assigned counsellor, else the campus admissions inbox.",
        variables=LEAD_VARS,
        default_subject="Thanks for visiting JD",
        default_body=_p("Hi {{Student_Name}},", "Thank you for visiting our {{Campus_Name}} campus today.", "— Team JD"),
        aliases={"name": "Student_Name", "campus": "Campus_Name"},
    ),
    Trigger(
        key="cold_drip_30", group="leads",
        label="Cold lead — day 30 follow-up",
        description="Scheduled 30 days after a follow-up with outcome COLD.",
        recipients="To the lead. Reply-To: assigned counsellor, else the campus admissions inbox.",
        variables=LEAD_VARS,
        default_subject="Still considering {{Program_Name}}?",
        default_body=_p("Hi {{Student_Name}},", "Our team is here whenever you are ready to talk about {{Program_Name}}.", "— Team JD"),
        aliases={"name": "Student_Name", "program": "Program_Name"},
    ),
    Trigger(
        key="cold_drip_60", group="leads",
        label="Cold lead — day 60 follow-up",
        description="Scheduled 60 days after a follow-up with outcome COLD.",
        recipients="To the lead. Reply-To: assigned counsellor, else the campus admissions inbox.",
        variables=LEAD_VARS,
        default_subject="A scholarship for {{Program_Name}}?",
        default_body=_p("Hi {{Student_Name}},", "Fresh scholarships have been announced for {{Program_Name}}.", "— Team JD"),
        aliases={"name": "Student_Name", "program": "Program_Name"},
    ),
    Trigger(
        key="cold_drip_90", group="leads",
        label="Cold lead — day 90 follow-up",
        description="Scheduled 90 days after a follow-up with outcome COLD.",
        recipients="To the lead. Reply-To: assigned counsellor, else the campus admissions inbox.",
        variables=LEAD_VARS,
        default_subject="Final call for {{Program_Name}}",
        default_body=_p("Hi {{Student_Name}},", "This is our last note for now. Reply if you would like us to keep in touch.", "— Team JD"),
        aliases={"name": "Student_Name", "program": "Program_Name"},
    ),
    Trigger(
        key="not_answered_closing_soon", group="leads",
        label="Admissions closing soon",
        description="Reserved for the not-answered follow-up sequence (no automatic sender today).",
        recipients="To the lead. Reply-To: assigned counsellor, else the campus admissions inbox.",
        variables=LEAD_VARS,
        default_subject="Admissions for {{Program_Name}} closing soon",
        default_body=_p("Hi {{Student_Name}},", "Last few seats are left in {{Program_Name}}. Reply to this mail to confirm your seat.", "— Team JD"),
        aliases={"name": "Student_Name", "program": "Program_Name"},
    ),
    Trigger(
        key="enrolled_confirmation", group="leads",
        label="Follow-up outcome ENROLLED",
        description="Fires when a follow-up is logged with outcome ENROLLED.",
        recipients="To the lead. Reply-To: assigned counsellor, else the campus admissions inbox.",
        variables=LEAD_VARS,
        default_subject="Welcome aboard {{Student_Name}} — your admission is confirmed",
        default_body=_p("Hi {{Student_Name}},", "Your enrolment in {{Program_Name}} at {{Campus_Name}} is confirmed.", "— Team JD"),
        aliases={"name": "Student_Name", "program": "Program_Name", "campus": "Campus_Name"},
    ),
    Trigger(
        key="manager_overdue_hot_lead", group="leads",
        label="Overdue hot lead — manager escalation",
        description="Scheduled job: a HOT lead with no follow-up for over 24 hours.",
        recipients="To every user holding leads.escalation.receive at the lead's campus.",
        variables=LEAD_VARS,
        default_subject="Overdue hot lead: {{Student_Name}}",
        default_body=_p("{{Student_Name}} ({{Lead_Phone}}) has been HOT for over 24 hours with no contact.", "Counsellor: {{Counsellor_Name}}"),
        aliases={"name": "Student_Name", "phone": "Lead_Phone", "counsellor": "Counsellor_Name"},
    ),

    # ------------------------------------------------------------------
    # Admissions
    # ------------------------------------------------------------------
    Trigger(
        key="admissions.application_submitted.email", group="admissions",
        label="Application received — student copy",
        description="First submit of the public application form.",
        recipients="To the applicant. Reply-To: campus acknowledgement inbox.",
        variables=_vars(STUDENT_VARS, PROGRAM_VARS, [Var("Submission_Date", "Submission date", "25-11-2026")]),
        default_subject="Application Received - JD Institute",
    ),
    Trigger(
        key="admissions.form_submitted.email", group="admissions",
        label="Application received — office copy (with form PDF)",
        description="First submit of the public application form; carries the application PDF and any fee still payable online.",
        recipients="To the campus acknowledgement inbox (else Operations, else the lead's counsellor); CC Operations + counsellor.",
        variables=_vars(STUDENT_VARS, PROGRAM_VARS, [Var("Fee_Lines", "Fees still payable online, one paragraph each (pre-rendered)", "<p>Registration fee: Rs. 10,000.00<br>Pay online: https://…</p>")]),
        default_subject="Application received — {{Application_ID}} ({{Student_Name}})",
        default_body=_p(
            "Dear {{Student_Name}},",
            "Thank you for applying to {{Institute_Name}}. We have received your application form; a copy is attached for your records.",
            "Application no: {{Application_ID}}<br>Program: {{Program_Name}}<br>Campus: {{Campus_Name}}",
        ) + "{{Fee_Lines}}" + _p(
            "Our admissions team will review it and contact you about the next steps.",
            _SIGN_ADMISSIONS,
        ),
        attachments_note="Application form PDF",
    ),
    Trigger(
        key="admissions.undertaking.email", group="admissions",
        label="Fee Payment Schedule (undertaking)",
        description="Staff click Send undertaking on an enrolment.",
        recipients="To the student; CC the requesting staff member, the campus undertaking inbox and any extra addresses typed. Reply-To: campus undertaking inbox.",
        variables=_vars(STUDENT_VARS, PROGRAM_VARS),
        default_subject="Fee Payment Schedule - {{Student_Name}} ({{Course_Name}})",
        default_body=_p(
            "Dear {{Student_Name}},",
            "Please find your Fee Payment Schedule attached. Reach out to your counsellor if anything needs to be corrected.",
            "Application ID: {{Application_ID}}<br>Program: {{Program_Name}}<br>Campus: {{Campus_Name}}",
        ),
        attachments_note="Fee Payment Schedule PDF",
    ),
    Trigger(
        key="student.portal_credentials.email", group="admissions",
        label="Student portal credentials",
        description="Staff click Send portal credentials on a student.",
        recipients="To the student's personal email. Reply-To: default inbox.",
        variables=_vars(STUDENT_VARS, PROGRAM_VARS, [
            Var("Portal_Email", "Portal login email (institute address)", "ananya.sharma@jdift.in", required=True),
            Var("Username", "Portal username", "ananya.sharma@jdift.in", required=True),
            Var("Password", "Temporary password", "Jd#48213", required=True),
            Var("Login_Url", "Portal login URL", "https://jdsd.netlify.app/#/portal/login/", required=True),
        ]),
        default_subject="Your student portal login",
        aliases={"name": "Student_Name", "institute": "Institute_Name", "email": "Portal_Email", "username": "Username", "password": "Password", "login_url": "Login_Url"},
    ),
    Trigger(
        key="admissions.handbook.email", group="admissions",
        label="Student handbook",
        description="Staff click Send handbook on a student; attaches the institute's handbook PDF.",
        recipients="To the student's personal email. Reply-To: default inbox.",
        variables=_vars(STUDENT_VARS, PROGRAM_VARS),
        default_subject="Your Student Handbook - {{Institute_Name}}",
        default_body=_p(
            "Dear {{Student_Name}},",
            "Welcome to {{Program_Name}} at {{Institute_Name}}!",
            "Please find the Student Handbook attached. It is the official manual for your time with us and covers, among other things:",
        ) + (
            "<ul><li>the attendance policy (85% minimum per module) and leave rules</li>"
            "<li>assessment, submission deadlines and progression</li>"
            "<li>fee payment modes and deadlines</li>"
            "<li>the code of conduct, anti-ragging and anti-harassment policies</li>"
            "<li>support services: counselling, library, Wi-Fi, medical help</li>"
            "<li>the appeals and complaints process</li></ul>"
        ) + _p(
            "Read it carefully before orientation, and share it with your parents/guardians - the closing pages include the undertakings both of you are required to sign and submit.",
            "If you have any questions, reach out to your Class Mentor or the admissions office - we're happy to help.",
            "- {{Institute_Name}}",
        ),
        attachments_note="Institute handbook PDF (Master → Institutes)",
    ),

    # ------------------------------------------------------------------
    # Fees
    # ------------------------------------------------------------------
    Trigger(
        key="fees.receipt.email", group="fees",
        label="Fee receipt",
        description="A fee receipt is created at the counter or settled online.",
        recipients="To the student (else the campus receipts inbox); CC campus receipts inbox + Accounts. Reply-To: campus receipts inbox.",
        variables=_vars(STUDENT_VARS, PROGRAM_VARS, RECEIPT_VARS),
        default_subject="Fee receipt {{Receipt_No}} — {{Student_Name}}",
        default_body=_p(
            "Dear {{Student_Name}},",
            "We have received your payment. The receipt is attached.",
            "Receipt no: {{Receipt_No}}<br>Amount: Rs. {{Amount}}<br>Towards: {{Particular}}<br>Date: {{Receipt_Date}}<br>Mode: {{Payment_Mode}}<br>Program: {{Program_Name}}<br>Campus: {{Campus_Name}}",
            "Please keep this receipt for your records.",
            _SIGN_ACCOUNTS,
        ),
        attachments_note="Receipt PDF",
    ),
    Trigger(
        key="fees.applicant_receipt.email", group="fees",
        label="Receipt for a fee paid before enrolment",
        description="An applicant pays the registration / course / other fee online from the Pay fees page after the application form.",
        recipients="To the student (else the campus receipts inbox); CC campus receipts inbox + Accounts. Reply-To: campus receipts inbox.",
        variables=_vars(STUDENT_VARS, PROGRAM_VARS, RECEIPT_VARS),
        default_subject="Fee receipt {{Receipt_No}} — {{Student_Name}}",
        default_body=_p(
            "Dear {{Student_Name}},",
            "We have received your {{Particular}}. The receipt is attached.",
            "Receipt no: {{Receipt_No}}<br>Amount: Rs. {{Amount}}<br>Towards: {{Particular}}<br>Date: {{Receipt_Date}}<br>Mode: {{Payment_Mode}}<br>Program: {{Program_Name}}<br>Campus: {{Campus_Name}}",
            "Please keep this receipt for your records. Our admissions team will contact you about enrolment.",
            _SIGN_ACCOUNTS,
        ),
        attachments_note="Receipt PDF",
    ),
    Trigger(
        key="fees.application_fee_receipt.email", group="fees",
        label="Application fee receipt",
        description="A lead's application fee is settled by the gateway or marked paid by hand.",
        recipients="To the lead (else the campus receipts inbox); CC campus receipts inbox + Accounts. Reply-To: campus receipts inbox.",
        variables=_vars(LEAD_VARS, RECEIPT_VARS),
        default_subject="Application fee receipt {{Receipt_No}} — {{Student_Name}}",
        default_body=_p(
            "Dear {{Student_Name}},",
            "We have received your application fee. The receipt is attached.",
            "Receipt no: {{Receipt_No}}<br>Amount: Rs. {{Amount}}<br>Towards: {{Particular}}<br>Date: {{Receipt_Date}}<br>Mode: {{Payment_Mode}}<br>Program: {{Program_Name}}<br>Campus: {{Campus_Name}}",
            "Please keep this receipt for your records. Our admissions team will share the application form link with you.",
            _SIGN_ACCOUNTS,
        ),
        attachments_note="Application fee receipt PDF",
    ),
    Trigger(
        key="fees.fee_link.email", group="fees",
        label="Fee payment link (enrolled student)",
        description="Staff click Send link on an installment or other fee of an enrolled student.",
        recipients="To the student. Reply-To: campus receipts inbox.",
        variables=_vars(STUDENT_VARS, PROGRAM_VARS, [
            Var("Fee_type", "Fee type without the word “fee” (template appends it)", "Installment #2", required=True),
            Var("Installment_Label", "Full row label", "Installment #2"),
            Var("Amount", "Amount due (formatted)", "25,000.00"),
            Var("Due_Date", "Due date", "15 Dec 2026"),
            Var("Payment_Link", "Payment URL", "https://erp.example.com/api/public/pay/…", required=True),
        ]),
        default_subject="{{Institute_Name}} — Fee payment link ({{Installment_Label}})",
        aliases={"name": "Student_Name", "institute": "Institute_Name", "course": "Course_Name", "installment": "Installment_Label", "amount": "Amount", "due_date": "Due_Date", "url": "Payment_Link"},
    ),

    # ------------------------------------------------------------------
    # Academics
    # ------------------------------------------------------------------
    Trigger(
        key="academics.assignment_assigned.email", group="academics",
        label="New assignment published",
        description="An assignment is created as published, or flipped to published. One mail per reached student.",
        recipients="To every active student in the batch / program-semester. Reply-To: the faculty who set it.",
        variables=_vars(STUDENT_VARS, PROGRAM_VARS, [
            Var("Subject_Name", "Subject", "Fashion Illustration", required=True),
            Var("Assignment_Title", "Assignment title", "Croquis sheet 2", required=True),
            Var("Due_Date", "Deadline (IST)", "05-12-2026 11:59 PM", required=True),
            Var("Submission_Mode", "How to submit", "Online (Student Portal)"),
            Var("Faculty_Name", "Faculty who set it", "Sunita Rao"),
        ]),
        default_subject="New Assignment: {{Assignment_Title}}",
        aliases={"VAR1": "Student_Name", "VAR2": "Subject_Name", "VAR3": "Assignment_Title", "VAR4": "Due_Date", "VAR5": "Submission_Mode"},
        use_layout=False,
    ),
    Trigger(
        key="academics.assignment_submitted.email", group="academics",
        label="Assignment submitted — to faculty",
        description="A student submits or resubmits an assignment.",
        recipients="To the faculty who created the assignment. Reply-To: the student.",
        variables=_vars(STUDENT_VARS, PROGRAM_VARS, [
            Var("Faculty_Name", "Faculty name", "Sunita Rao", required=True),
            Var("Subject_Name", "Subject", "Fashion Illustration", required=True),
            Var("Assignment_Title", "Assignment title", "Croquis sheet 2", required=True),
        ]),
        default_subject="Assignment submitted: {{Assignment_Title}} — {{Student_Name}}",
    ),

    # ------------------------------------------------------------------
    # Student leaves
    # ------------------------------------------------------------------
    Trigger(
        key="student_leaves.applied.email", group="student_leaves",
        label="Student leave applied — to mentor",
        description="A student applies for leave from the portal.",
        recipients="To the batch mentor; CC module mentor, the student's CC list, the student and the campus leave inbox. Reply-To: the student.",
        variables=_vars(STUDENT_VARS, PROGRAM_VARS, [
            Var("Leave_Start_Date", "Leave from", "02-12-2026", required=True),
            Var("Leave_End_Date", "Leave to", "03-12-2026", required=True),
            Var("Leave_Count", "Days", "2", required=True),
            Var("Reason", "Reason", "Family function"),
        ]),
        default_subject="Student Leave Application Submitted",
    ),
    Trigger(
        key="student_leaves.accepted.email", group="student_leaves",
        label="Student leave approved — to student",
        description="A mentor approves a student's leave.",
        recipients="To the student; CC the campus leave inbox. Reply-To: the batch mentor.",
        variables=_vars(STUDENT_VARS, PROGRAM_VARS, [
            Var("Leave_Start_Date", "Leave from", "02-12-2026", required=True),
            Var("Leave_End_Date", "Leave to", "03-12-2026", required=True),
            Var("Leave_Count", "Days", "2", required=True),
            Var("Reason", "Reason", "Family function"),
        ]),
        default_subject="Leave Application Accepted",
    ),

    # ------------------------------------------------------------------
    # Employee leaves & comp-off
    # ------------------------------------------------------------------
    Trigger(
        key="leaves.application_employee.email", group="employee_leaves",
        label="Leave applied — to manager",
        description="An employee applies for leave.",
        recipients="To the reporting manager on the application; CC the employee's CC list and the campus leave inbox. Reply-To: campus leave inbox.",
        variables=_vars(EMPLOYEE_VARS, LEAVE_VARS),
        default_subject="Leave application — {{Employee_Name}} ({{From_Date}})",
        default_body=_p(
            "{{Employee_Name}} ({{Employee_Code}}) has applied for {{Leave_Type}}.",
            "Dates: {{From_Date}} → {{To_Date}}<br>Days: {{Days}} ({{Session}})<br>Reason: {{Reason}}",
        ),
    ),
    Trigger(
        key="leaves.application_status_employee.email", group="employee_leaves",
        label="Leave approved / rejected — to employee",
        description="A manager decides a leave application.",
        recipients="To the employee; CC the manager and the campus leave inbox. Reply-To: campus leave inbox.",
        variables=_vars(EMPLOYEE_VARS, LEAVE_VARS, [
            Var("Decision", "approved / rejected", "approved", required=True),
            Var("Remarks", "Approver's remarks", "Enjoy the break", ),
        ]),
        default_subject="Leave {{Decision}} — {{From_Date}}",
        default_body=_p(
            "Dear {{Employee_Name}},",
            "Your leave application ({{From_Date}} → {{To_Date}}) has been <strong>{{Decision}}</strong>.",
            "Remarks: {{Remarks}}",
        ),
    ),
    Trigger(
        key="leaves.compoff_application_employee.email", group="employee_leaves",
        label="Comp-off applied — to manager",
        description="An employee applies for compensatory off.",
        recipients="To the reporting manager (else the campus leave inbox); CC the employee's CC list and the campus leave inbox. Reply-To: campus leave inbox.",
        variables=_vars(EMPLOYEE_VARS, [
            Var("Worked_Date", "Date worked", "22-11-2026", required=True),
            Var("Sessions_Worked", "Sessions worked", "1+1"),
            Var("Earned_Days", "Comp-off earned (days)", "1"),
            Var("Reason", "Reason", "Admission open day"),
        ]),
        default_subject="Comp-off application — {{Employee_Name}} ({{Worked_Date}})",
        default_body=_p(
            "{{Employee_Name}} ({{Employee_Code}}) has applied for comp-off.",
            "Worked date: {{Worked_Date}}<br>Sessions worked: {{Sessions_Worked}}<br>Earned: {{Earned_Days}}<br>Reason: {{Reason}}",
        ),
    ),
    Trigger(
        key="leaves.compoff_status_employee.email", group="employee_leaves",
        label="Comp-off approved / rejected — to employee",
        description="A manager decides a comp-off application.",
        recipients="To the employee; CC the manager and the campus leave inbox. Reply-To: campus leave inbox.",
        variables=_vars(EMPLOYEE_VARS, [
            Var("Worked_Date", "Date worked", "22-11-2026", required=True),
            Var("Earned_Days", "Comp-off earned (days)", "1"),
            Var("Decision", "approved / rejected", "approved", required=True),
            Var("Remarks", "Approver's remarks", "(none)"),
        ]),
        default_subject="Comp-off {{Decision}} — {{Worked_Date}}",
        default_body=_p(
            "Dear {{Employee_Name}},",
            "Your comp-off for {{Worked_Date}} has been <strong>{{Decision}}</strong>.",
            "Remarks: {{Remarks}}",
        ),
    ),

    # ------------------------------------------------------------------
    # Relieving
    # ------------------------------------------------------------------
    Trigger(
        key="hr.relieving.application.email", group="relieving",
        label="Relieving / part-time application submitted",
        description="An employee submits a relieving or full-time-to-part-time application.",
        recipients="To the first approver in the chain; CC the remaining approvers. Reply-To: the approver handling it, else the campus Principal.",
        variables=_vars(EMPLOYEE_VARS, [
            Var("Application_Type", "Relieving / Full-time to Part-time", "Relieving", required=True),
            Var("Last_Working_Date", "Last working date requested", "31 Dec 2026", required=True),
            Var("Last_Working_Date_Caption", "Caption for that date", "Last Working Date"),
            Var("Reason", "Reason", "Relocating"),
        ]),
        default_subject="Employee {{Application_Type}} Application — {{Employee_Name}} ({{Employee_Code}})",
        default_body=_p(
            "Employee submitted a {{Application_Type}} application.",
            "Employee Name: {{Employee_Name}} [{{Employee_Code}}]<br>Date of Join: {{Date_Of_Joining}}<br>{{Last_Working_Date_Caption}}: {{Last_Working_Date}}<br>Reason: {{Reason}}",
            _AUTO,
        ),
    ),
    Trigger(
        key="hr.relieving.application_rejected.email", group="relieving",
        label="Relieving / part-time application rejected",
        description="An approver rejects the application.",
        recipients="To the first approver; CC the remaining approvers. Reply-To: the approver handling it, else the campus Principal.",
        variables=_vars(EMPLOYEE_VARS, [
            Var("Application_Type", "Relieving / Full-time to Part-time", "Relieving", required=True),
            Var("Rejected_Level", "Approval level that rejected", "2"),
            Var("Rejection_Reason", "Reason for rejection", "Notice period not served"),
        ]),
        default_subject="Employee {{Application_Type}} Application Rejected — {{Employee_Name}}",
        default_body=_p(
            "Employee {{Application_Type}} application has been rejected.",
            "Employee Name: {{Employee_Name}} [{{Employee_Code}}]<br>Rejected at level: {{Rejected_Level}}<br>Reason for Rejection: {{Rejection_Reason}}",
            _AUTO,
        ),
    ),
    Trigger(
        key="hr.relieving.application_approved.email", group="relieving",
        label="Full-time to part-time approved",
        description="The final approver approves a part-time application.",
        recipients="To the employee; CC all approvers. Reply-To: the approver handling it, else the campus Principal.",
        variables=_vars(EMPLOYEE_VARS, [Var("Last_Working_Date", "Last working date as full-time", "31 Dec 2026", required=True)]),
        default_subject="Full-time to Part-time Approved — {{Employee_Name}} ({{Employee_Code}})",
        default_body=_p(
            "Dear {{Employee_Name}},",
            "Your application to move from full-time to part-time has been approved by all four levels. Your last working date as a full-time employee is {{Last_Working_Date}}.",
            "HR will update your employment record.",
            _SIGN_HR, _AUTO,
        ),
    ),
    Trigger(
        key="hr.relieving.letter.email", group="relieving",
        label="Relieving letter",
        description="The final approver approves a relieving application; the letter PDF is attached.",
        recipients="To the employee's personal email; CC approvers + work email. Reply-To: the approver handling it, else the campus Principal.",
        variables=_vars(EMPLOYEE_VARS, [
            Var("Last_Working_Date", "Last working date", "31 Dec 2026", required=True),
            Var("Letter_No", "Letter number", "RL/2026/0007"),
        ]),
        default_subject="Relieving Letter — {{Employee_Name}}",
        default_body=_p(
            "Dear {{Employee_Name}},",
            "Please find attached your relieving letter from {{Institute_Name}}. Your last working date is {{Last_Working_Date}}.",
            "We wish you the very best in your future endeavours.",
            _SIGN_HR, _AUTO,
        ),
        attachments_note="Relieving letter PDF",
    ),
    Trigger(
        key="hr.relieving.experience_letter.email", group="relieving",
        label="Experience letter",
        description="HR clicks Send experience letter; the letter PDF is attached.",
        recipients="To the employee's personal email; CC the final approver. Reply-To: the approver handling it, else the campus Principal.",
        variables=_vars(EMPLOYEE_VARS, [Var("Letter_No", "Letter number", "EL/2026/0007")]),
        default_subject="Experience Letter — {{Employee_Name}}",
        default_body=_p(
            "Dear {{Employee_Name}},",
            "Please find attached your experience letter from {{Institute_Name}}.",
            _SIGN_HR, _AUTO,
        ),
        attachments_note="Experience letter PDF",
    ),

    # ------------------------------------------------------------------
    # Tasks
    # ------------------------------------------------------------------
    Trigger(
        key="tasks.assigned.email", group="tasks",
        label="Task assigned",
        description="A task is created for, or reassigned to, a user.",
        recipients="To the assignee. Reply-To: default inbox.",
        variables=(
            Var("Assignee_Name", "Assignee", "Rahul Verma", required=True),
            Var("Creator_Name", "Who assigned it", "Sunita Rao", required=True),
            Var("Task_Name", "Task title", "Prepare orientation deck", required=True),
            Var("Due_Date", "Due date", "05-12-2026", required=True),
            Var("Task_Description", "Details", "Slides for the 2026 orientation."),
        ),
        default_subject="New task assigned: {{Task_Name}}",
        default_body=_p(
            "Hi {{Assignee_Name}},",
            "{{Creator_Name}} has assigned a task to you.",
            "Task: {{Task_Name}}<br>Due: {{Due_Date}}",
            "Details:<br>{{Task_Description}}",
            "Open the ERP to update progress or mark it complete.",
            "— JD ERP",
        ),
    ),
    Trigger(
        key="tasks.completed.email", group="tasks",
        label="Task completed",
        description="The assignee marks a task complete.",
        recipients="To the task's creator. Reply-To: default inbox.",
        variables=(
            Var("Creator_Name", "Task creator", "Sunita Rao", required=True),
            Var("Assignee_Name", "Who completed it", "Rahul Verma", required=True),
            Var("Task_Name", "Task title", "Prepare orientation deck", required=True),
            Var("Completed_On", "Completed on", "04-12-2026 16:20"),
            Var("Assigned_On", "Assigned on", "28-11-2026 10:05"),
            Var("Assignee_Remarks", "Assignee's remarks", "Done, shared on Drive."),
        ),
        default_subject="Task completed: {{Task_Name}}",
        default_body=_p(
            "Hi {{Creator_Name}},",
            "{{Assignee_Name}} has marked the following task as completed.",
            "Task: {{Task_Name}}<br>Completed on: {{Completed_On}}<br>Assigned on: {{Assigned_On}}",
            "Assignee remarks:<br>{{Assignee_Remarks}}",
            "— JD ERP",
        ),
    ),

    # ------------------------------------------------------------------
    # Accounts & login
    # ------------------------------------------------------------------
    Trigger(
        key="account.password_reset_by_admin.email", group="accounts",
        label="Password reset by admin",
        description="An admin resets a staff user's password from Admin → Users.",
        recipients="To the user's email (students / parents are skipped). Reply-To: default inbox.",
        variables=_vars(USER_VARS, [
            Var("Password", "New password", "Jd#48213", required=True),
            Var("Login_Url", "ERP login URL", "https://jdsd.netlify.app", required=True),
        ]),
        default_subject="Your JD ERP password has been reset",
        aliases={"name": "User_Name", "username": "Username", "password": "Password", "login_url": "Login_Url"},
    ),
    Trigger(
        key="account.forgot_password.email", group="accounts",
        label="Forgot password link",
        description="A user clicks Forgot password on the login page.",
        recipients="To the user's email. Reply-To: default inbox.",
        variables=_vars(USER_VARS, [Var("Reset_Link", "Password reset URL", "https://jdsd.netlify.app/#/reset-password/…", required=True)]),
        default_subject="Reset your JD ERP password",
        default_body=_p(
            "Hi {{User_Name}},",
            "We received a request to reset the password on your JD account. To choose a new password, open this link:",
            "<a href=\"{{Reset_Link}}\">{{Reset_Link}}</a>",
            "The link expires in a few days. If you didn't request this, you can safely ignore the email — your password won't change.",
            "— JD Admissions",
        ),
    ),
    Trigger(
        key="account.password_changed.email", group="accounts",
        label="Password changed confirmation",
        description="A user completes a password reset from the emailed link.",
        recipients="To the user's email. Reply-To: default inbox.",
        variables=USER_VARS,
        default_subject="Your JD ERP password was changed",
        default_body=_p(
            "Hi {{User_Name}},",
            "Your password was just changed. If this was you, no further action is needed. If you didn't change your password, contact your administrator immediately.",
            "— JD Admissions",
        ),
    ),
]

TRIGGERS: dict[str, Trigger] = {t.key: t for t in _TRIGGERS}

if len(TRIGGERS) != len(_TRIGGERS):  # pragma: no cover — programmer error
    raise RuntimeError("Duplicate trigger key in apps.notifications.registry")


def get(key: str) -> Trigger | None:
    return TRIGGERS.get(key)


def is_system_email(key: str) -> bool:
    return key in TRIGGERS


def example_context(trigger: Trigger) -> dict:
    """Sample values for preview / test-send: every variable's example,
    the common set, and the legacy alias names so the shipped HTML
    renders in the preview too."""
    ctx = {v.name: v.example for v in COMMON_VARS}
    ctx.update({v.name: v.example for v in trigger.variables})
    for old, new in trigger.aliases.items():
        ctx.setdefault(old, ctx.get(new, ""))
    return ctx
