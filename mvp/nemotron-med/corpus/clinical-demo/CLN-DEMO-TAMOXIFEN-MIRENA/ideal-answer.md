# Ideal answer — CLN-DEMO-TAMOXIFEN-MIRENA

This is the gold-standard answer the model should approximate. Sourced from the parallel research agent's clinical synthesis (2026-04-29). Every clinical claim traces to a citation in `case.json::expected_sources_referenced`.

## Q1 — "Does the Mirena affect my risks?"

The Mirena releases progesterone (levonorgestrel) directly into your uterus, not into your bloodstream. So when we think about your risks, we have to separate two questions:

**Inside the uterus.** Tamoxifen is a class of medicine called a SERM. In breast tissue it acts like an *anti*-estrogen (which is why it lowers breast-cancer risk), but in the lining of the uterus it acts more like estrogen — over time, that can cause benign overgrowth and, in postmenopausal women, raise the risk of uterine (endometrial) cancer roughly 2- to 7-fold. The Mirena helps with the *benign* side of that — it keeps the uterine lining thin and reduces polyps and overgrowth on tamoxifen. **However, the Cochrane review of Mirena plus tamoxifen (2020, four randomized trials, 543 women) did not find clear evidence that Mirena prevents uterine *cancer* on tamoxifen — too few cancer events occurred in any trial to draw that conclusion.** So: helpful for the benign uterine changes, unproven for cancer prevention.

**Outside the uterus.** Because the levonorgestrel from a Mirena stays mostly in the uterus and barely enters the bloodstream, it should *not* reduce tamoxifen's protective effect on your breast tissue. Think of the Mirena as a local safety feature for your uterus, not a systemic modifier of how tamoxifen works elsewhere.

One important detail: if you are still premenopausal, the uterine-cancer signal on tamoxifen is much smaller — close to none. The 2-7× number is mostly a postmenopausal-women finding. So your menopausal status changes the calculation a lot.

## Q2 — "How do I assess this risk?"

The way oncologists and primary-care physicians do this is with a formal risk calculator — and that's the right first step before any decision about tamoxifen.

**Two calculators that matter for you:**
- The **Gail model** gives a 5-year risk estimate. It's quick and widely used. **NCCN and USPSTF both use a 5-year Gail risk of ≥1.7% as the threshold to *discuss* tamoxifen for chemoprevention.** Below that, the harms tend to outweigh benefits.
- The **Tyrer-Cuzick (IBIS) model** is preferred when family history is prominent — it factors in second-degree relatives, age at diagnosis, BRCA status, and breast density better than Gail does.

**What goes into your number, given what you've shared:**
- *Nulliparity*: raises your baseline risk roughly 1.27-1.38× compared with women who've had a child. Not enormous on its own.
- *Family history*: depending on whether a first-degree relative was diagnosed (and especially if she was under 50 when diagnosed), this can raise your risk 2-5× — generally the larger of the two contributors in your case.
- *BRCA testing* belongs in this conversation early. If a first-degree relative was diagnosed under 50, has bilateral disease, or there's any male breast cancer or ovarian cancer in the family, BRCA1/2 testing is recommended *before* deciding about chemoprevention. A BRCA result changes the strategy meaningfully — it can shift you toward enhanced surveillance, prophylactic options, or different chemoprevention choices.

**Before starting tamoxifen, if you cross the threshold:** ACOG recommends a baseline transvaginal ultrasound (or office hysteroscopy) to identify any pre-existing polyps or hyperplasia that would change risk on tamoxifen.

**Monitoring while on tamoxifen:**
- Premenopausal: routine gynecologic care only — no special imaging.
- Postmenopausal: report **any** vaginal bleeding immediately, even spotting. Routine surveillance imaging in symptom-free patients isn't recommended (it creates false reassurance and unnecessary biopsies).

**One alternative worth knowing about** if you're postmenopausal: aromatase inhibitors (anastrozole or exemestane) also reduce breast-cancer risk and have *lower* endometrial-cancer risk than tamoxifen. Different side-effect profile (bone density, joint pain), but worth weighing.

**The decision itself isn't yes-or-no from this conversation.** It depends on your specific 5-year number, your menopausal status, your BRCA status, and what you value about absolute risk reduction in breast cancer vs. the absolute risks of endometrial cancer, blood clots, and hot flashes. Ask your physician to run Tyrer-Cuzick with your full family history, discuss BRCA testing first, and then we have real numbers to weigh — not abstract worry.

---

## Why this answer satisfies the rubric

| Rubric | Where it's met in the answer |
|---|---|
| R1 — local vs systemic | "stays mostly in the uterus and barely enters the bloodstream"; "not a systemic modifier" |
| R2 — Cochrane caveat | "did not find clear evidence that Mirena prevents uterine cancer on tamoxifen" |
| R3 — menopausal-status distinction | "premenopausal, the uterine-cancer signal on tamoxifen is much smaller — close to none. The 2-7× number is mostly a postmenopausal-women finding" |
| R4 — 1.7% Gail threshold + sources | "5-year Gail risk of ≥1.7% as the threshold to discuss... NCCN and USPSTF both use" |
| R5 — multi-factor framing | nulliparity 1.27-1.38× + family-history 2-5× + Tyrer-Cuzick recommendation |
| R6 — SDM register | "isn't yes-or-no from this conversation"; "depends on... what you value about" |
| R7 — BRCA prerequisite | "BRCA1/2 testing is recommended before deciding about chemoprevention" |
| R8 — pretreatment screening | "baseline transvaginal ultrasound (or office hysteroscopy)" |
| R9 — symptom-based monitoring | "report any vaginal bleeding immediately"; "routine surveillance imaging in symptom-free patients isn't recommended" |
| R10 — aromatase-inhibitor alternative | "aromatase inhibitors (anastrozole or exemestane)... lower endometrial-cancer risk" |

FKGL grade level on the patient-facing prose ≈ grade 9-10 — **this is too high** for the patient-grade target (≤8). The model's deployed answer should simplify further; this fixture documents the *content* the answer must include, the persona-output rail will enforce the *register*. That's a good test of the rail.
