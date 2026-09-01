"""Declaration, rules & regulations, and the per-institute disclaimer.

**This module is the single source of truth for that wording.** It is
read by three surfaces that must never disagree: the public application
form, the read-only playback in the student portal, and the application
PDF. The text previously lived only in the React form, which meant the
portal and the PDF would have had to re-type it.

All wording is copied verbatim from the PHP application links
(`jdift_application_link.php` / `jdsd_application_link.php`), including
punctuation quirks. Don't "fix" spacing or grammar — the trust signed off
on these exact wordings, and divergence triggers a compliance review.

`terms_for(institute_code)` returns the whole bundle as plain dicts,
ready to serialise.
"""

DECLARATION_TEXT = (
    "I hereby solemnly and sincerely affirm that the statements made and "
    "information furnished in my application and also in the enclosures "
    "submitted by me are true. Should it, however be found that the "
    "information furnished therein is not factually true, I am aware that I "
    "will be liable for prosecution and forfeiture of my admission process "
    "and the fee shall not be refunded by the College / University."
)

#: Cheque payee, per institute. Interpolated into fee sub-rule A.
_FEE_RECIPIENT = {
    "JDIFT": "JD INSTITUTE OF FASHION TECHNOLOGY",
    "JDSD": "JD EDUCATIONAL TRUST",
}
_DEFAULT_FEE_RECIPIENT = "JD"

#: Extra fee sub-rules unique to one institute, inserted between the
#: shared sub-rules and the final "failing to pay" line.
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


def _normalise(rule) -> dict:
    """Every rule leaves this module in the same shape, so no consumer
    has to branch on "is it a string or an object"."""
    if isinstance(rule, str):
        return {"text": rule, "subs": [], "emphasis": False}
    return {
        "text": rule["text"],
        "subs": list(rule.get("subs") or []),
        "emphasis": bool(rule.get("emphasis")),
    }


def rules_for(institute_code: str) -> list[dict]:
    """The numbered rules, fee rules first, as `{text, subs, emphasis}`."""
    fees = {
        "text": "Fees:",
        "subs": _fee_sub_rules(institute_code),
        # Rendered bold — it is a heading for its sub-rules, not a rule
        # in its own right.
        "emphasis": True,
    }
    return [fees] + [_normalise(r) for r in _SHARED_RULES]


def terms_for(institute_code: str) -> dict:
    """Declaration + rules + disclaimer for one institute.

    An unknown code is not an error: it falls back to the generic
    recipient and no disclaimer, so a newly-added institute shows correct
    (if generic) terms rather than a blank section.
    """
    code = institute_code or ""
    return {
        "declaration": DECLARATION_TEXT,
        "fee_recipient": _FEE_RECIPIENT.get(code, _DEFAULT_FEE_RECIPIENT),
        "rules": rules_for(code),
        "disclaimer": _DISCLAIMERS.get(code),
    }
