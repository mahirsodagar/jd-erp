"""Declaration, rules & regulations, and the per-institute disclaimer.

**This module is the single source of truth for that wording.** It is
read by three surfaces that must never disagree: the public application
form, the read-only playback in the student portal, and the application
PDF. The text previously lived only in the React form, which meant the
portal and the PDF would have had to re-type it.

Both institutes are on their own 2026 document; the pre-2026 wording
survives only as the fallback for an institute we don't know yet.

* **JDSD** — "FEES, ACADEMIC RULES, STUDENT REGULATIONS AND
  UNDERTAKING": eleven numbered sections, its own undertaking, and a fee
  note. See `_JDSD_2026_*`.
* **JDIFT** — "RULES & REGULATIONS, FEE POLICY AND STUDENT UNDERTAKING":
  ten sections lettered A, B, C, C-1, D–I (each carries its own
  `label`), its own student/parent declaration, no fee note. See
  `_JDIFT_2026_*`.

Both were re-transcribed on 2026-10-30 from the "Clean" PDFs
(`JDI Application Form T&C 2026-Clean.pdf`, `JDSD Application Form T&C
2026 -Clean.pdf`), which supersede the earlier 2026 drafts.
* **Anyone else** — the older wording carried over verbatim from the PHP
  application links (`jdift_application_link.php` /
  `jdsd_application_link.php`).

Don't "fix" spacing, grammar or punctuation in any of it — the trust
signed off on these exact wordings, and divergence triggers a compliance
review. That includes the stray closing quote in JDSD rule 1.2 and the
lower-case "academics" in 7.6; both are in the signed document.

`terms_for(institute_code)` returns the whole bundle as plain dicts,
ready to serialise.
"""

#: Pre-2026 wording, still current for JDIFT.
DECLARATION_TEXT = (
    "I hereby solemnly and sincerely affirm that the statements made and "
    "information furnished in my application and also in the enclosures "
    "submitted by me are true. Should it, however be found that the "
    "information furnished therein is not factually true, I am aware that I "
    "will be liable for prosecution and forfeiture of my admission process "
    "and the fee shall not be refunded by the College / University."
)

#: JDSD 2026 — "UNDERTAKING BY THE STUDENT", the closing section of the
#: signed document. Replaces DECLARATION_TEXT for JDSD only. Paragraphs
#: are kept separate so every surface can space them the same way.
_JDSD_2026_UNDERTAKING = (
    "I hereby solemnly and sincerely affirm that the statements made and "
    "information furnished by me in my application form and in all "
    "documents/enclosures submitted by me are true, complete, and correct "
    "to the best of my knowledge and belief.\n\n"
    "I understand that admission to the Institute is subject to the rules, "
    "regulations, academic requirements, fee regulations, disciplinary "
    "policies, and applicable University regulations.\n\n"
    "I further undertake to abide by all rules and regulations of the "
    "Institute and the concerned University. I understand that if any "
    "information or document furnished by me is subsequently found to be "
    "false, incorrect, misleading, or factually inaccurate, I may be liable "
    "for cancellation/forfeiture of admission and such other action as may "
    "be applicable. In such circumstances, the fees paid by me shall be "
    "subject to the Institute's applicable fee/refund policy and University "
    "regulations.\n\n"
    "I also undertake to fulfil all prescribed academic, attendance, "
    "examination, internship, project, financial, and administrative "
    "requirements during my period of study.\n\n"
    "I confirm that I have read and understood the above rules and "
    "regulations and agree to comply with them."
)

#: JDIFT 2026 — "STUDENT / PARENT DECLARATION", the closing section of
#: that document. Note the I/We phrasing: it is signed by the student AND
#: the parent/guardian, unlike JDSD's student-only undertaking.
_JDIFT_2026_UNDERTAKING = (
    "I/We hereby confirm that I/we have carefully read and understood the "
    "above-mentioned Rules & Regulations, Fee Policy, and Student "
    "Requirements of the Institute.\n\n"
    "I/We agree to abide by all the rules, regulations, academic "
    "requirements, fee conditions, disciplinary provisions, and other "
    "policies of the Institute, as applicable.\n\n"
    "I/We understand that failure to comply with the prescribed "
    "requirements may result in penalties, restrictions on examination "
    "eligibility, cancellation of admission, suspension, or other "
    "appropriate disciplinary action, as applicable.\n\n"
    "I/We further confirm that the information and declarations furnished "
    "by me/us at the time of admission are true and complete to the best "
    "of my/our knowledge."
)

#: JDSD 2026 — the note printed above the document's fee table. The table
#: itself is blank in the signed PDF; the live figures come from
#: FeeTemplate, so only the note travels with the terms.
_JDSD_2026_FEE_NOTE = [
    "The table below shows the fees for one year. The course fee shown "
    "will apply for each year of the course for this batch. University "
    "fees are fixed by the University and may change.",
    "* Students admitted to the University program shall be responsible "
    "for paying all university-related fees directly through the "
    "university’s official online portal or Demand Draft. Such fees are "
    "separate from, and not included in, the tuition fee and subject to "
    "the University rules. *",
]

#: Opening paragraph of each 2026 document, defining "Institute",
#: "University" and "Management". Served as `preamble`; blank where the
#: wording has none.
_PREAMBLES = {
    "JDSD": (
        "In this document, the “Institute” means JD School of Design, "
        "operated by JD Educational Trust, Bengaluru; the “University” "
        "means the university to which the student’s programme is "
        "affiliated, where applicable; and the “Management” means the "
        "management of JD Educational Trust."
    ),
    "JDIFT": (
        "In this document, the “Institute” means JD Institute of Fashion "
        "Technology operated by JD Educational Trust Bengaluru, including "
        "its centres; and the “Management” means the management of the "
        "Institute."
    ),
}

#: Cheque payee, per institute. Interpolated into fee sub-rule A.
_FEE_RECIPIENT = {
    "JDIFT": "JD INSTITUTE OF FASHION TECHNOLOGY",
    "JDSD": "JD EDUCATIONAL TRUST",
}
_DEFAULT_FEE_RECIPIENT = "JD"

#: Extra fee sub-rules unique to one institute, inserted between the
#: shared sub-rules and the final "failing to pay" line.
#:
#: NOTE: the JDSD entry is currently unreachable — JDSD moved to the 2026
#: document, which carries its own fee section, so `_fee_sub_rules` is
#: only ever called for other institutes. Kept so the pre-2026 bundle
#: stays reconstructable if JDSD is ever rolled back; delete it, not just
#: the key, once that is off the table.
_EXTRA_FEE_RULES = {
    "JDSD": [
        "Examination fees for each semester are payable by the students.",
    ],
}


def _fee_sub_rules(institute_code: str) -> list[str]:
    recipient = _FEE_RECIPIENT.get(institute_code, _DEFAULT_FEE_RECIPIENT)
    return [
        f"It can be paid by cash, cheque, demand draft, RTGS, NEFT, IMPS, or "
        f"online transfer in favour of {recipient}, payable in Bengaluru.",
        "In case of any cheque bounce, there will be a penalty of Rs 1000/-",
        "In the event of withdrawal of candidature or cancellation of "
        "admission, fees paid are non-refundable or transferable under any "
        "circumstances.",
        "In the case of full payment, if the students do not meet the course "
        "requirements,they will not be eligible for any kind of certification.",
        "Kindly collect the receipt for the fee payment.",
        "If a student wants to shift to the next month's batch instead of the "
        "month when he/she was scheduled to start the academic session, an "
        "amount of Rs. 10,000 will be charged for the first batch, Rs. 20,000 "
        "for the second batch, and so on.",
        "If a student wishes to shift from one centre to another, he/she will "
        "have to pay an amount of Rs. 25,000 as transfer charges.",
        "The collected student academic fees include (but are not limited to) "
        "tuition fees, usage and access to the library, and lab fees.Repeaters "
        "have to pay a separate fee.",
        *_EXTRA_FEE_RULES.get(institute_code, []),
        "Students failing to pay fees on time will be liable to pay a penalty.",
    ]


#: Rules 2..n — identical across institutes. Only rule 1's sub-bullets
#: and the disclaimer vary, which is why those are built per institute.
_SHARED_RULES = [
    "All students are to be seated 10 minutes before the class starts. If "
    "found to be late, the students will not be allowed to attend the class.",
    "Mobile phones, games and music are strictly prohibited in the class.",
    "Timely submission of assignments, as per dates shared by the faculty "
    "member is a must.",
    "Any delay in submission of assignments will mean that the assignment "
    "will not be graded, and the overall performance of the student will "
    "suffer. Additionally, this will also be brought to the notice of the "
    "parents.",
    "A minimum overall attendance of 85% and subject wise attendance of 85% "
    "is necessary in order to appear for Examination.",
    "It is mandatory to wear an ID card during ALL CLASS HOURS, VISITS, and "
    "EXAMINATIONS; otherwise, a Rs. 200/- fine will be levied. The student "
    "must pay Rs. 500 to get a replacement identity card for any lost cards.",
    "Library timings are before and after class hours or as scheduled in the "
    "timetable.",
    "Students who are responsible for mishandling, accidental damages, "
    "vandalism, or losses to furnishings, structures, tools, and equipment "
    "will be charged the appropriate penalty based on the expenses incurred "
    "for labour and materials, including replacement costs.",
    "Annual Design Awards, Exhibitions, Seminars,and Study Tours have to be "
    "attended compulsorily for skill development and exposure to the industry.",
    {
        "text": "The award of a certificate will be based on meeting the "
                "following requirements:",
        "subs": [
            "The candidate must pass all the subjects without any backlog",
            "The final portfolio has to be submitted within the stipulated time",
            "Students must participate in the annual design awards to showcase "
            "their collections.",
            "The student has to complete 2 months of internships and receive "
            "the internship experience certificate from the concerned "
            "organisation.",
        ],
    },
    "The student should be responsible for paying for all materials, "
    "educational tours, and software. During the study tour, excursion, "
    "seminar, or exhibition, the institute shall not be responsible for any "
    "mishap or unforeseen calamity.",
    "All results, regular and repeated academic affairs, will be communicated "
    "through the Main Notice Board (some universities will declare results "
    "online as well).",
    "In case of any change in address or contact details, the same will have "
    "to be brought to the notice of the management by way of a written "
    "application.",
    "The design project is mandatory and should be illustrated, "
    "well-researched, have a complete photoshoot, and have a final design "
    "project made up of all components.",
    "Semester hall tickets and mark cards should be collected from the "
    "institute as per the notice.",
    "Any sort of in-disciplinary activity will lead to strict action and may "
    "also result in expulsion (based on the seriousness of the activity).",
    "The Institute reserves the right to cancel the admission of any candidate "
    "at any stage (even after admission) if there is any discrepancy or matter "
    "about the student's code of conduct, parent misbehaviour, or arrogance "
    "shown towards management or any staff.",
]

#: Legal disclaimer, only where the institute has one. Verbatim from PHP,
#: including the legal phrasing the trust signed off on.
_DISCLAIMERS = {
    "JDSD": {
        "title": "Disclaimer",
        "note": "All degrees are provided by respective universities which "
                "the centre is associated with.",
        "intro":
            "JD School of Design is a private institution offering "
            "specialized design programs in affiliation with Dr. Manmohan "
            "Singh Bengaluru City University and in collaboration with BEST "
            "Innovation University and other recognized academic partners. "
            "The following important information applies to all prospective "
            "and current students:",
        "sections": [
            {
                "heading": "Affiliations & Collaborations",
                "bullets": [
                    "Programs offered may be conducted in collaboration with "
                    "or under affiliation to recognized universities or "
                    "institutional partners.",
                    "All official degree certificates and convocation "
                    "documents will be issued by the respective university, "
                    "and will bear the university's name and official seal.",
                ],
            },
            {
                "heading": "Certificates & Diplomas",
                "bullets": [
                    "JD School of Design may offer certificates and diplomas "
                    "for skill-based or standalone programs. These are "
                    "awarded under the Indian Trust Act and Accredited to "
                    "Education Quality Accreditation Commision.",
                ],
            },
            {
                "heading": "Accreditation & Recognition",
                "bullets": [
                    "JD School of Design maintains high standards aligned "
                    "with industry practices.",
                ],
            },
            {
                "heading": "Non-Degree Granting Status",
                "bullets": [
                    "JD School of Design does not independently award or "
                    "confer academic degrees such as B.Sc., M.Sc., B.Des., "
                    "M.Des., MBA, or MA under its own name.",
                    "All degree qualifications, where applicable, are "
                    "conferred solely by affiliated/Collaborated universities "
                    "upon successful fulfilment of their academic "
                    "requirements.",
                ],
            },
            {
                "heading": "Student Responsibility",
                "bullets": [
                    "Prospective and current students are advised to "
                    "independently verify the recognition, validity, and "
                    "applicability of any certifications (degree or "
                    "non-degree) for employment or further education with "
                    "relevant authorities or institutions.",
                ],
            },
        ],
        "footer_lines": [
            "For further information or clarification, please contact:",
            "Admissions Office: bangalore@jdinstitute.edu.in",
            "Official Website: www.jdsd.in",
        ],
    },
}


# === JDSD 2026 (clean) ==================================================
#
# "FEES, ACADEMIC RULES, STUDENT REGULATIONS AND UNDERTAKING" — the
# "Clean" document signed off in October 2026. Eleven numbered sections.

_JDSD_2026_RULES = [
    {
        "text": "FEES AND PAYMENT REGULATIONS",
        "emphasis": True,
        "subs": [
            "Fees may be paid by Cash, Cheque, Demand Draft, RTGS, NEFT, "
            "IMPS, or Online Transfer in favour of JD EDUCATIONAL TRUST, "
            "payable at their respective centres.",
            "UG/PG students shall separately pay the applicable University "
            "annual registration, admission, examination, sports and "
            "cultural, NSS, Youth Red Cross and other fees notified by the "
            "University from time to time. University fees are fixed by the "
            "University, are not included in the course fee, and may change "
            "from year to year.",
            "University annual registration fee Every Year, or other "
            "applicable university/academic fees shall be paid by the "
            "student separately as prescribed by the respective University.",
            "In case of delayed payment or cheque dishonour, the student "
            "shall be liable to pay the late payment charge specified below "
            "and any bank charges actually incurred by the Institute.",
            "Refund of fees on withdrawal of candidature or cancellation of "
            "admission shall be governed by the Institute’s Fee Refund "
            "Policy. For programmes affiliated to a University, refunds "
            "shall be made in accordance with the applicable UGC and "
            "University regulations on refund of fees. Fees paid are not "
            "transferable to another student.",
            "Payment of fees, including payment in full, does not by itself "
            "entitle a student to any certificate. A student who does not "
            "fulfil the academic/course requirements shall not be eligible "
            "for any certificate or certification from the Institute.",
            "Students must collect and retain the official fee receipt for "
            "every fee payment made to the Institute.",
            "Delayed fee payments will incur a late fee of 12 % per annum "
            "on the overdue amount, calculated from the due date until the "
            "date of payment",
            "An additional annual fee of Rs. 100/- towards the DKUL/LMS "
            "platform shall be payable as applicable.",
            "The annual vehicle parking sticker fee shall be Rs. 50/- per "
            "vehicle, subject to the applicable parking rules.",
            {
                "text": "The academic fees collected from students may "
                        "include:",
                "bullets": [
                    "Tuition fees",
                    "Library access and usage charges",
                    "Laboratory fees",
                    "Other academic and institutional facilities/services as "
                    "applicable.",
                ],
            },
            "Students who repeat a subject, semester, or academic year shall "
            "be required to pay the applicable repeat/readmission fee "
            "separately.",
            "Tuition fees may be revised from time to time in accordance "
            "with institutional policies and applicable regulations.",
        ],
    },
    {
        "text": "ATTENDANCE AND CLASSROOM REGULATIONS",
        "emphasis": True,
        "subs": [
            "As per the Institute's academic requirement, students are "
            "expected to maintain a minimum overall attendance of 75% for "
            "every semester. Students failing to maintain the prescribed "
            "attendance shall not be permitted to appear for the "
            "Semester-End Examination, subject to applicable University "
            "regulations.",
            "Students who are not eligible to appear for the examination "
            "due to shortage of attendance may be required to repeat the "
            "semester and academic requirements and pay the applicable "
            "readmission/repeat fees.",
            "Students must be seated in the classroom at least 10 minutes "
            "before the scheduled commencement of the class. Students "
            "arriving late may not be permitted to attend the class.",
            "Mobile phones, games, music, and other activities unrelated to "
            "the class are strictly prohibited during class hours.",
            "Students must submit all assignments within the deadlines "
            "communicated by the concerned faculty member.",
            "Late submission of assignments may result in the assignment "
            "not being graded, which may adversely affect the student's "
            "overall academic performance. Such cases may also be brought "
            "to the attention of the parent/guardian.",
            "Students must participate in all academic activities "
            "prescribed by the Institute, including classes, practical "
            "sessions, workshops, seminars, exhibitions, Annual Design "
            "Awards, wherever applicable.",
        ],
    },
    {
        "text": "IDENTITY CARD REGULATIONS",
        "emphasis": True,
        "subs": [
            {
                "text": "Wearing the Institute-issued Identity Card is "
                        "mandatory throughout the student's presence on "
                        "campus, including:",
                "bullets": [
                    "All class hours",
                    "Lunch and break periods",
                    "Movement from one building to another",
                    "Institute visits and activities",
                    "Examinations",
                    "Workshops, seminars, exhibitions, and other "
                    "institutional activities",
                ],
            },
            "Failure to wear the Identity Card may attract a fine of "
            "Rs. 500/- per instance.",
            "In case of loss of the Identity Card, the student shall pay "
            "Rs. 1,000/- towards issuance of a replacement Identity Card.",
            "Misuse, exchange, lending, borrowing, or transfer of Identity "
            "Cards is strictly prohibited. Any such violation may attract a "
            "fine of up to Rs. 5,000/- on each student involved, and the "
            "Institute may take further disciplinary action, including "
            "suspension/expulsion, in accordance with Section 9, depending "
            "on the seriousness of the violation.",
        ],
    },
    {
        "text": "LIBRARY, LABORATORY AND PROPERTY REGULATIONS",
        "emphasis": True,
        "subs": [
            "Library facilities may be used before and after class hours or "
            "during the timings specified in the timetable/library "
            "schedule.",
            "Students shall be responsible for the proper use and safe "
            "custody of Institute property, including furniture, "
            "structures, tools, equipment, laboratory facilities, and other "
            "resources. Any mishandling, accidental damage, vandalism, or "
            "loss caused by a student shall render them liable to pay the "
            "appropriate charges towards labour, materials, repair, "
            "restoration, or replacement, as assessed by the Institute "
            "after giving the student an opportunity to be heard.",
            "Students shall be responsible for the cleanliness and orderly "
            "maintenance of the campus premises and shall cooperate with "
            "the faculty and staff in ensuring that this standard is "
            "upheld.",
        ],
    },
    {
        "text": "MATERIALS, SOFTWARE, TOURS AND OTHER EXPENSES",
        "emphasis": True,
        "subs": [
            "Participation in Annual Design Awards (Only eligible student "
            "collections that meet all the prescribed criteria will be "
            "showcased), exhibitions, workshops, seminars organised or "
            "prescribed by the Institute is compulsory, as these activities "
            "form an important part of the student's skill development and "
            "industry exposure.",
            {
                "text": "Students shall bear the expenses prescribed by the "
                        "Institute towards the following, the estimated "
                        "amounts of which will be communicated in advance "
                        "for each academic year:",
                "bullets": [
                    "Materials",
                    "Educational/study tours",
                    "Software",
                    "Workshops or other activities, wherever applicable.",
                ],
            },
            "During study tours, excursions, seminars, exhibitions or other "
            "off-campus activities, the Institute shall not be responsible "
            "for any mishap, accident, loss, injury or unforeseen "
            "circumstance, except to the extent of responsibility imposed "
            "by applicable law.",
        ],
    },
    {
        "text": "ACADEMIC AND DESIGN PROJECT REQUIREMENTS",
        "emphasis": True,
        "subs": [
            "The Design Project is mandatory for eligible programmes and "
            "must be completed in accordance with the academic requirements "
            "prescribed by the Institute.",
            {
                "text": "The Design Project shall be:",
                "bullets": [
                    "Properly illustrated",
                    "Well researched and documented",
                    "Supported by a complete photoshoot, wherever applicable",
                    "Presented with all required components",
                    "Submitted within the prescribed deadline",
                    "Only eligible students' collection that meet all the "
                    "prescribed criteria will be showcased.",
                ],
            },
        ],
    },
    {
        "text": "CERTIFICATION REQUIREMENTS",
        "emphasis": True,
        "intro": "The award of the final course/programme certificate shall "
                 "be subject to fulfilment of all prescribed academic and "
                 "institutional requirements, including:",
        "subs": [
            "The student must successfully pass all required subjects "
            "without any backlog, wherever applicable.",
            "The final portfolio must be completed and submitted within the "
            "stipulated time.",
            "Students must successfully complete and submit the mandatory "
            "design projects.",
            "Participation in the Annual Design Awards is mandatory, as it "
            "forms an important part of the students’ portfolio. However, "
            "only eligible and shortlisted students will be permitted to "
            "showcase their collections/projects at the final event.",
            "Students must maintain a minimum attendance of 75%, as "
            "prescribed in Section 2.",
            "All academic, administrative, financial, examination, project, "
            "internship, and other institutional requirements must be "
            "completed before the certificate is issued.",
            "For University-affiliated programmes, Marks Cards, degree "
            "certificates and other academic credentials are issued by the "
            "University. Certificates for the Institute’s own programmes "
            "are issued by the Institute.",
        ],
    },
    {
        "text": "EXAMINATION AND ACADEMIC COMMUNICATION",
        "emphasis": True,
        "subs": [
            "All academic results, regular and repeat/reappear academic "
            "matters, examination-related information, and other important "
            "notices shall be communicated through the Institute's official "
            "academic portal - DKUL and/or other official communication "
            "channels. Where applicable, the concerned University may also "
            "publish results online.",
            "Students are responsible for regularly checking official "
            "Institute notices and communications.",
            "Any change in the student's residential address, telephone "
            "number, email address or other contact details must be "
            "communicated to the Administration office through a written "
            "application without delay.",
            "Semester Exam Hall Tickets and Marks Card shall be collected "
            "from the Institute within the period specified in the official "
            "notice.",
            "It is mandatory for all the students to obtain the required No "
            "Objection Certificate (NOC) from the concerned "
            "department/faculty/staff for every examination, wherever "
            "prescribed.",
            "Students who do not obtain the required NOC may not be issued "
            "the Hall Ticket and may not be permitted to appear for the "
            "Semester-End Examination, subject to applicable University "
            "regulations.",
        ],
    },
    {
        "text": "CODE OF CONDUCT AND DISCIPLINE",
        "emphasis": True,
        "subs": [
            "Students are expected to maintain discipline, dignity, "
            "respect, and professional conduct at all times within and "
            "outside the campus while participating in Institute-related "
            "activities.",
            "Any form of indiscipline, misconduct, misbehaviour, "
            "harassment, intimidation, damage to property, or violation of "
            "Institute rules shall invite strict disciplinary action and "
            "may, depending on the seriousness of the offence, result in "
            "suspension or expulsion.",
            "Misbehaviour or inappropriate conduct by a parent/guardian "
            "towards the management, faculty, or staff may also be "
            "considered while reviewing the student's continuation with "
            "the Institute.",
            "The Institute reserves the right to cancel the admission of a "
            "candidate/student at any stage, including after admission, if "
            "any material discrepancy is found in the student’s documents, "
            "declarations, or eligibility, or in cases involving serious "
            "misconduct by the student, after giving the student a "
            "reasonable opportunity to be heard.",
            "Students and parents/guardians are expected to cooperate with "
            "the Institute and its staff in maintaining a safe, "
            "disciplined, clean, and professional campus environment.",
            "Students must maintain punctuality and regularity in "
            "attendance",
            "Students are expected to maintain proper discipline, decorum, "
            "and professional conduct within the campus and during all "
            "Institute-related activities.",
            "Students shall treat faculty, staff, fellow students, "
            "visitors, and other members of the Institute community with "
            "respect and courtesy.",
            "Any form of misconduct, indiscipline, harassment, bullying, "
            "intimidation, threatening behaviour, physical altercation, or "
            "verbal abuse shall be subject to disciplinary action.",
            "Students must comply with the Institute's rules, regulations, "
            "and instructions issued by authorized faculty or "
            "administrative personnel.",
            "Disrupting classes, examinations, or Institute functions "
            "through inappropriate behaviour or repeated non-compliance "
            "with instructions shall constitute misconduct.",
            "Unauthorized recording, photographing, or sharing of photos, "
            "videos, or Institute-related content may be restricted where "
            "it violates privacy or confidentiality.",
            "Students must use the Institute's official communication "
            "channels responsibly and shall not misuse them for abusive, "
            "offensive, or misleading communication.",
            "Cheating, plagiarism, academic malpractice, impersonation, or "
            "submission of fraudulent documents shall be treated as a "
            "serious disciplinary matter.",
            "Possession or use of prohibited substances, weapons, or other "
            "restricted items on campus shall be dealt with as per "
            "applicable law and Institute regulations.",
            "Students may be required to explain their conduct or appear "
            "before the designated disciplinary authority when an "
            "allegation of misconduct is reported.",
            "Disciplinary action for proven misconduct may range from a "
            "warning, counselling, or fine to suspension or "
            "termination/expulsion, depending on the severity, subject to "
            "due process.",
            "Repeated or serious misconduct may attract stricter action, "
            "even where a prior warning has already been issued.",
            "The Institute reserves the right to act on misconduct "
            "occurring during Institute-organized events, field visits, "
            "internships, or online activities that affect the Institute "
            "or its community.",
            "All disciplinary matters shall be decided by the designated "
            "authority as per applicable procedure, and the decision shall "
            "be communicated through official Institute channels.",
            "Ragging in any form is strictly prohibited on and off the "
            "campus and is a punishable offence. The Institute follows the "
            "UGC Regulations on Curbing the Menace of Ragging in Higher "
            "Educational Institutions, 2009. Every student and "
            "parent/guardian shall submit the anti-ragging undertaking in "
            "the prescribed form at the time of admission and at the start "
            "of each academic year. A student found guilty of ragging shall "
            "be liable to disciplinary action, including expulsion, and the "
            "matter may be reported to the police.",
            "The Institute has constituted an Internal Complaints Committee "
            "to address complaints of sexual harassment, in accordance with "
            "the UGC (Prevention, Prohibition and Redressal of Sexual "
            "Harassment of Women Employees and Students in Higher "
            "Educational Institutions) Regulations, 2015, and a Student "
            "Grievance Redressal Committee in accordance with applicable "
            "UGC regulations. Students and parents/guardians may raise any "
            "complaint or grievance, including in relation to fees, "
            "academics, or discipline, with the relevant committee. Details "
            "are available on the Institute’s website and notice board.",
        ],
    },
    {
        "text": "PERSONAL INFORMATION AND DECLARATIONS",
        "emphasis": True,
        "subs": [
            "Any change in the student's address, telephone number, email "
            "address, or other contact details must be communicated to the "
            "Administration office in writing without delay.",
            "Parents/guardians and students are required to provide all "
            "information and declarations required by the Institute and/or "
            "University at the time of admission, including applicable "
            "declarations relating to physical or mental health conditions, "
            "learning disabilities, and legal/criminal matters, as required "
            "by law and institutional policy.",
            "Students and parents/guardians shall ensure that all "
            "information furnished in admission and academic records is "
            "complete, accurate, and truthful.",
        ],
    },
    {
        "text": "MANAGEMENT'S RIGHT AND FINAL DECISION",
        "emphasis": True,
        "subs": [
            "The Institute reserves the right to amend, modify, introduce, "
            "or withdraw rules, regulations, academic requirements, and "
            "procedures from time to time in accordance with institutional "
            "policies and applicable University/statutory regulations. "
            "Changes will be notified through the Institute’s official "
            "channels. Fees shall be revised only as stated in Section 1.",
            "The decision of the Management shall be final and binding in "
            "all matters concerning the administration and internal "
            "functioning of the Institute, subject to the grievance "
            "redressal mechanism, applicable University regulations, and "
            "law.",
            "These rules and this undertaking are governed by the laws of "
            "India, and the courts at Bengaluru shall have jurisdiction.",
        ],
    },
]


# === JDIFT 2026 (clean) =================================================
#
# "RULES & REGULATIONS, FEE POLICY AND STUDENT UNDERTAKING" — the
# "Clean" document signed off in October 2026. Sections are lettered
# A, B, C, C-1, D, E, F, G, H, I in the signed document, so every
# section carries its own `label`. Sections C and C-1 are flat bullet
# lists rather than numbered items, so they carry `ordered: False`.

_JDIFT_2026_RULES = [
    {
        "label": "A",
        "text": "FEE PAYMENT AND FINANCIAL REGULATIONS",
        "emphasis": True,
        "subs": [
            "Mode of Payment: Fees may be paid by Cash, Cheque, Demand "
            "Draft, RTGS, NEFT, IMPS, or Online Transfer in favour of JD "
            "INSTITUTE OF FASHION TECHNOLOGY, payable at their respective "
            "centres.",
            "All students are required to pay a Registration Fee of "
            "Rs. 11,800/-(inclusive of GST) at the time of admission. The "
            "Registration Fee is non-refundable.",
            "Cheque Dishonour / Delayed Payment: In the event of cheque "
            "dishonour, the student shall be liable to pay the bank charges "
            "actually incurred by the Institute, and in case of delayed "
            "payment, the late fee specified below.",
            "Non-Refundable and Non-Transferable Fees: In the event of "
            "withdrawal of candidature or cancellation of admission, fees "
            "once paid shall be non-refundable and non-transferable under "
            "any circumstances whatsoever",
            "Course Eligibility and Certification: Payment of fees, "
            "including payment in full, does not by itself entitle a "
            "student to certification. A student who does not fulfil the "
            "academic requirements, such as attendance, examination, "
            "internship, portfolio, or other prescribed course "
            "requirements, shall not be eligible for certification.",
            "Fee Receipts: Students must collect and retain official fee "
            "receipts for all payments made through any of the modes "
            "mentioned above.",
            {
                "text": "Change of Batch / Course: If a student wishes to "
                        "shift to a subsequent batch or change the course "
                        "from the batch/course to which the student was "
                        "originally admitted, such transfer/change shall be "
                        "considered only in cases where the request is "
                        "genuine and supported by valid reasons. The "
                        "Management will decide any such request reasonably "
                        "and communicate its decision in writing.\n\n"
                        "The following transfer/change fee shall be "
                        "applicable:",
                "bullets": [
                    "First change of batch/course: ₹10,000/-",
                    "Second change of batch/course: ₹20,000/-",
                    "Any subsequent change of batch/course: Charges as may "
                    "be determined by the Management from time to time.",
                ],
                "after": "The Management reserves the right to accept or "
                         "reject any request based on the genuineness and "
                         "validity of the circumstances stated by the "
                         "student.",
            },
            "Change of Centre: If a student wishes to transfer from one "
            "Institute centre to another, a transfer charge of ₹25,000/- "
            "shall be payable, only in cases where the request is genuine "
            "and supported by valid reasons. The Management will decide any "
            "such request reasonably and communicate its decision in "
            "writing.",
            "Tuition Fees: The academic fee includes tuition fees "
            "applicable for the respective academic year. The Management "
            "reserves the right to revise tuition fees in accordance with "
            "institutional policies and applicable academic requirements.",
            "Examination and Re-examination Fees: Students shall pay the "
            "prescribed examination fee for each semester. Students who "
            "fail or are required to reappear for an examination shall be "
            "liable to pay the prescribed re-examination fee.",
            "Late Fee: Students who fail to remit the prescribed fees on or "
            "before the due date shall be liable to pay a late payment "
            "penalty of ₹500/- per day, calculated from the date on which "
            "the respective instalment falls due.",
            "Additional Charges: An additional annual fee of Rs. 100/- "
            "towards the DKUL/LMS platform shall be payable as applicable.",
            "The annual vehicle parking sticker fee shall be Rs. 50/- per "
            "vehicle, subject to the applicable parking rules.",
            "FEES MAY BE REVISED FROM TIME TO TIME IN ACCORDANCE WITH "
            "INSTITUTIONAL POLICIES AND APPLICABLE REGULATIONS.",
        ],
    },
    {
        "label": "B",
        "text": "ATTENDANCE AND ACADEMIC REQUIREMENTS",
        "emphasis": True,
        "subs": [
            "A student who fails to maintain the prescribed 85% attendance "
            "shall not be eligible to appear for the semester-end "
            "examination and may be required to repeat the semester by "
            "paying the applicable re-admission fee, subject to "
            "institutional rules.",
            "Students must be seated in the classroom at least 10 minutes "
            "before the scheduled commencement of the class. Students "
            "arriving late may not be permitted to attend the class.",
            "Mobile phones, games, music and other unauthorised electronic "
            "activities are strictly prohibited during class hours.",
            "Timely submission of assignments, as per the deadlines "
            "prescribed by the respective Subject Mentor, is mandatory.",
            "Late submission of assignments may not be evaluated or awarded "
            "marks/grades, and may adversely affect the student's overall "
            "academic performance.",
            "Semester hall tickets and mark cards must be collected from "
            "the Institute within the stipulated period as communicated "
            "through official notices.",
            "Students must obtain the required No Objection Certificate "
            "(NOC) from the respective department/staff for every "
            "examination, wherever prescribed. A student who fails to "
            "obtain the required NOC may not be issued the hall ticket and "
            "may not be permitted to appear for the semester-end "
            "examination.",
        ],
    },
    {
        "label": "C",
        "text": "IDENTITY CARD AND CAMPUS DISCIPLINE",
        "emphasis": True,
        "intro": "It is mandatory for all students to wear and visibly "
                 "display their Institute Identity Card at all times while "
                 "in the institute, including during class hours, lunch "
                 "breaks, movement from one building to another, Industry "
                 "visits, examinations, workshops, events, and other "
                 "academic or official activities.",
        "ordered": False,
        "subs": [
            "Failure to wear or produce the Identity Card when required "
            "shall attract a fine of ₹500/-.",
            "In case of loss of the Identity Card, the student shall pay "
            "₹1,000/- towards the issuance of a replacement Identity Card.",
            "The Identity Card is strictly non-transferable and must be "
            "used only by the student to whom it is issued.",
            "Any misuse, alteration, lending, sharing, tampering, "
            "fraudulent use, or other unauthorised use of the Identity Card "
            "shall be treated as serious misconduct.",
            "Misuse, exchange, lending, borrowing, or transfer of Identity "
            "Cards is strictly prohibited. Any such violation may attract a "
            "fine of up to Rs. 5,000/- on each student involved, and the "
            "Institute may take further disciplinary action, including "
            "suspension/expulsion, in accordance with Section 9, depending "
            "on the seriousness of the violation.",
        ],
    },
    {
        "label": "C-1",
        "text": "CODE OF CONDUCT AND DISCIPLINE",
        "emphasis": True,
        "ordered": False,
        "subs": [
            "Students must maintain punctuality and regularity in "
            "attendance",
            "Students are expected to maintain proper discipline, decorum, "
            "and professional conduct within the campus and during all "
            "Institute-related activities.",
            "Students shall treat faculty, staff, fellow students, "
            "visitors, and other members of the Institute community with "
            "respect and courtesy.",
            "Any form of misconduct, indiscipline, harassment, bullying, "
            "intimidation, threatening behaviour, physical altercation, or "
            "verbal abuse shall be subject to disciplinary action.",
            "Students must comply with the Institute's rules, regulations, "
            "and instructions issued by authorized faculty or "
            "administrative personnel.",
            "Disrupting classes, examinations, or Institute functions "
            "through inappropriate behaviour or repeated non-compliance "
            "with instructions shall constitute misconduct.",
            "Students shall not record, photograph, or share photos, "
            "videos, or other content of classes, faculty, staff, or other "
            "students, or confidential Institute material, without the "
            "consent of the persons concerned and the Institute.",
            "Students must use the Institute's official communication "
            "channels responsibly and shall not misuse them for abusive, "
            "offensive, or misleading communication.",
            "Cheating, plagiarism, academic malpractice, impersonation, or "
            "submission of fraudulent documents shall be treated as a "
            "serious disciplinary matter.",
            "Possession or use of prohibited substances, weapons, or other "
            "restricted items on campus shall be dealt with as per "
            "applicable law and Institute regulations.",
            "Students may be required to explain their conduct or appear "
            "before the designated disciplinary authority when an "
            "allegation of misconduct is reported.",
            "Disciplinary action for proven misconduct may range from a "
            "warning, counselling, or fine to suspension or "
            "termination/expulsion, depending on the severity, subject to "
            "due process.",
            "Repeated or serious misconduct may attract stricter action, "
            "even where a prior warning has already been issued.",
            "The Institute reserves the right to act on misconduct "
            "occurring during Institute-organized events, field visits, "
            "internships, or online activities that affect the Institute "
            "or its community.",
            "All disciplinary matters shall be decided by the designated "
            "authority as per applicable procedure, and the decision shall "
            "be communicated through official Institute channels.",
            "A student aggrieved by a disciplinary decision may appeal in "
            "writing to the Management within 15 days of the decision. The "
            "decision of the Management on appeal shall be final, subject "
            "to applicable law.",
            "Ragging in any form is strictly prohibited on and off the "
            "campus and is a punishable offence. A student found guilty of "
            "ragging shall be liable to disciplinary action, including "
            "expulsion, and the matter may be reported to the police.",
            "The Institute has constituted an Internal Complaints Committee "
            "under the Sexual Harassment of Women at Workplace (Prevention, "
            "Prohibition and Redressal) Act, 2013. Students may raise "
            "complaints of sexual harassment with the Committee, and any "
            "other grievance (including on fees, academics or discipline) "
            "with the Grievance Officer, whose details are available on the "
            "Institute’s notice board and website.",
        ],
    },
    {
        "label": "D",
        "text": "LIBRARY, CAMPUS PROPERTY AND RESPONSIBILITY",
        "emphasis": True,
        "subs": [
            "Library services shall be available before and after class "
            "hours or during the timings specified in the timetable/library "
            "schedule.",
            "Students shall be responsible for the cleanliness and orderly "
            "maintenance of the campus premises and shall cooperate with "
            "the faculty and staff in ensuring that this standard is "
            "upheld.",
            "Students responsible for mishandling, accidental damage, "
            "vandalism or loss of Institute furnishings, structures, tools, "
            "equipment or other property shall be liable to pay the "
            "appropriate charges towards labour, materials, repair and/or "
            "replacement costs, as applicable.",
        ],
    },
    {
        "label": "E",
        "text": "WORKSHOPS, EVENTS, STUDY TOURS AND INDUSTRY EXPOSURE",
        "emphasis": True,
        "subs": [
            "Participation in Annual Design Awards, exhibitions, workshops, "
            "seminars organised or prescribed by the Institute is "
            "compulsory, as these activities form an important part of the "
            "student's skill development and industry exposure.",
            {
                "text": "Students shall bear the expenses prescribed by the "
                        "Institute towards the following, the estimated "
                        "amounts of which will be communicated in advance "
                        "for each academic year:",
                "bullets": [
                    "Materials",
                    "Educational/study tours",
                    "Software",
                    "Workshops or other activities, wherever applicable.",
                ],
            },
            "During study tours, excursions, seminars, exhibitions or other "
            "off-campus activities, the Institute shall not be responsible "
            "for any mishap, accident, loss, injury or unforeseen "
            "circumstance, except to the extent of responsibility imposed "
            "by applicable law.",
            "Participation in the JD Design Awards is mandatory, as it "
            "forms an important part of the students’ portfolio. However, "
            "only eligible and shortlisted students will be permitted to "
            "showcase their collections/projects at the final event.",
        ],
    },
    {
        "label": "F",
        "text": "CERTIFICATION REQUIREMENTS",
        "emphasis": True,
        "intro": "The award of the final course certificate shall be subject "
                 "to the student fulfilling all prescribed academic and "
                 "institutional requirements, including:",
        "subs": [
            "Passing all subjects without any backlog.",
            "Maintaining the prescribed minimum attendance.",
            "Submitting the final portfolio within the stipulated deadline.",
            "Successfully completing and submitting the mandatory design "
            "project.",
            "Participation in the JD Design Awards, which is mandatory as "
            "it forms an important part of the students’ portfolio. "
            "However, only eligible and shortlisted students will be "
            "permitted to showcase their collections/projects at the final "
            "event.",
            "It shall be mandatory for students to complete a minimum of "
            "one month of internship and to submit the internship "
            "experience certificate obtained from the concerned "
            "organisation.",
            "Fulfilling all other academic, examination, administrative and "
            "institutional requirements applicable to the programme.",
        ],
    },
    {
        "label": "G",
        "text": "COMMUNICATION AND STUDENT RESPONSIBILITIES",
        "emphasis": True,
        "subs": [
            "All academic results and regular/repeat academic-related "
            "communications shall be communicated through the Institute's "
            "official academic portal - DKUL and/or other official "
            "communication channels.",
            "Students are responsible for regularly checking official "
            "Institute notices and communications.",
            "Any change in the student’s residential address, telephone "
            "number, email address or other contact details must be "
            "communicated to the Administration office in writing without "
            "delay.",
            "Students are responsible for complying with all applicable "
            "Institute and statutory rules and regulations.",
        ],
    },
    {
        "label": "H",
        "text": "DECLARATION OF PERSONAL INFORMATION",
        "emphasis": True,
        "subs": [
            "Students and parents/guardians shall provide all information "
            "and declarations required under applicable law and "
            "institutional regulations at the time of admission.",
            "Where required by law or institutional policy, students and "
            "parents/guardians shall disclose relevant information "
            "pertaining to physical or mental health conditions, learning "
            "disabilities, and/or criminal records at the time of "
            "admission.",
            "Any deliberate suppression or misrepresentation of material "
            "information shall render the student liable to appropriate "
            "action, including cancellation of admission after a written "
            "show-cause notice and an opportunity to be heard, subject to "
            "applicable law and regulations.",
        ],
    },
    {
        "label": "I",
        "text": "GENERAL TERMS",
        "emphasis": True,
        "subs": [
            "The Management reserves the right to amend, modify, or revise "
            "these Rules & Regulations, fee structure, academic "
            "requirements, administrative procedures, and other "
            "institutional policies from time to time, subject to "
            "applicable statutory regulations.",
            "Students and parents/guardians agree to comply with these "
            "Rules & Regulations by signing the declaration below.",
            "The decision of the Management shall be final in all matters "
            "relating to the administration and implementation of these "
            "Rules & Regulations, subject to applicable laws and "
            "institutional regulations.",
            "Please note that our institution functions exclusively as a "
            "training centre and does not award or confer academic "
            "degrees. We provide professional training programmes designed "
            "to develop practical knowledge and industry-relevant skills.",
            "Academic degree certificates are not awarded by our centre. "
            "Upon successful completion of the applicable Diploma Course, "
            "the Institute awards its own Diploma Certificate in accordance "
            "with the terms and requirements of the respective programme.",
            "These Rules & Regulations are governed by the laws of India, "
            "and the courts at Bengaluru shall have exclusive jurisdiction. "
            "If any provision is held invalid, the remaining provisions "
            "shall continue in force. Nothing in these Rules & Regulations "
            "limits any right of the student under applicable law.",
        ],
    },
]


def _normalise_sub(sub) -> dict:
    """Sub-items are either plain text, or text plus their own bullets
    and an optional closing paragraph after them (JDIFT rule A.7)."""
    if isinstance(sub, str):
        return {"text": sub, "bullets": [], "after": ""}
    return {
        "text": sub["text"],
        "bullets": list(sub.get("bullets") or []),
        "after": sub.get("after", ""),
    }


def _normalise(rule, label: str = "") -> dict:
    """Every rule leaves this module in the same shape, so no consumer
    has to branch on "is it a string or an object".

    `label` is the section marker the document prints ("A", "C-1",
    "3"). The rule's own `label` wins; otherwise the caller supplies
    the running number/letter."""
    if isinstance(rule, str):
        rule = {"text": rule}
    return {
        "label": rule.get("label") or label,
        "text": rule["text"],
        "intro": rule.get("intro", ""),
        "subs": [_normalise_sub(s) for s in (rule.get("subs") or [])],
        "emphasis": bool(rule.get("emphasis")),
        # Numbered by default; False renders the items as bullets, as
        # JDIFT's section C is written.
        "ordered": bool(rule.get("ordered", True)),
    }


#: How each bundle's top-level sections are labelled. JDIFT's 2026
#: document letters them A-I; everything else numbers them.
_LIST_STYLES = {"JDIFT": "upper-alpha"}
_DEFAULT_LIST_STYLE = "decimal"

#: Heading for the consent block, as each signed document titles it.
#: JDIFT's is signed by the parent/guardian too, hence the different name.
_DECLARATION_TITLES = {
    "JDSD": "Undertaking by the Student",
    "JDIFT": "Student / Parent Declaration",
}


def rules_for(institute_code: str) -> list[dict]:
    """The rules as `{text, intro, subs, emphasis, ordered}`.

    Both institutes are on their own 2026 document; an institute we
    don't know falls back to the earlier wording, whose first rule is
    the generic fee block.
    """
    if institute_code == "JDSD":
        return [_normalise(r, str(n)) for n, r in enumerate(_JDSD_2026_RULES, 1)]
    if institute_code == "JDIFT":
        # Every JDIFT section carries its own letter (A … C, C-1, D … I).
        return [_normalise(r) for r in _JDIFT_2026_RULES]

    fees = {
        "text": "Fees:",
        "subs": _fee_sub_rules(institute_code),
        # Rendered bold — it is a heading for its sub-rules, not a rule
        # in its own right.
        "emphasis": True,
    }
    rules = [fees] + list(_SHARED_RULES)
    return [_normalise(r, str(n)) for n, r in enumerate(rules, 1)]


def declaration_for(institute_code: str) -> str:
    """What the student affirms — each institute's own 2026 wording."""
    if institute_code == "JDSD":
        return _JDSD_2026_UNDERTAKING
    if institute_code == "JDIFT":
        return _JDIFT_2026_UNDERTAKING
    return DECLARATION_TEXT


def terms_for(institute_code: str) -> dict:
    """Declaration + rules + fee note + disclaimer for one institute.

    An unknown code is not an error: it falls back to the generic
    recipient and no disclaimer, so a newly-added institute shows correct
    (if generic) terms rather than a blank section.
    """
    code = institute_code or ""
    return {
        # JDSD's 2026 document titles this section "Undertaking by the
        # student". Served rather than branched on in each UI, so the
        # form, the portal and the PDF cannot label it differently.
        "preamble": _PREAMBLES.get(code, ""),
        "declaration_title": _DECLARATION_TITLES.get(code, "Declaration"),
        "declaration": declaration_for(code),
        "fee_recipient": _FEE_RECIPIENT.get(code, _DEFAULT_FEE_RECIPIENT),
        "rules": rules_for(code),
        "list_style": _LIST_STYLES.get(code, _DEFAULT_LIST_STYLE),
        # Sits with the live fee figures, which come from FeeTemplate.
        "fee_note": _JDSD_2026_FEE_NOTE if code == "JDSD" else [],
        "disclaimer": _DISCLAIMERS.get(code),
    }
