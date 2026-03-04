"""
SG Tuition Match Bot — "You've Been Selected" Model
=====================================================
Payment psychology flow:
  1. Tutor browses jobs and applies FREE — zero friction, no account required
  2. Parent reviews applicant profiles and taps Shortlist on the ones they want
  3. Shortlisted tutor receives an emotional notification:
       - "This parent chose you from X applicants"
       - Estimated first-month earnings (rate_min × 4 sessions)
       - How much they save vs a traditional agency commission
  4. THEN the payment wall appears — tutor pays MATCH_FEE to confirm and unlock contact
  5. Admin approves screenshot → parent's contact sent to tutor instantly
"""

import logging
import os
from datetime import datetime

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    filters,
    ContextTypes,
)
from database import Database

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

db = Database("/data/tuition.db")

# =============================================================================
# CONFIG — set as Railway environment variables
# =============================================================================
ADMIN_ID   = int(os.environ.get("ADMIN_TELEGRAM_ID", "0"))
PAYNOW_NUMBER = os.environ.get("PAYNOW_NUMBER", "9XXXXXXX")
MATCH_FEE  = int(os.environ.get("MATCH_FEE", "30"))  # SGD per confirmed match

AUTO_BAN_THRESHOLD = 3

# =============================================================================
# CONVERSATION STATES
# =============================================================================

# Tutor registration (0–9)
(
    TUTOR_NAME,
    TUTOR_TYPE,
    TUTOR_SUBJECTS,
    TUTOR_LEVELS,
    TUTOR_RATE_MIN,
    TUTOR_RATE_MAX,
    TUTOR_ZONES,
    TUTOR_QUALIFICATIONS,
    TUTOR_PHONE,
    TUTOR_CONFIRM,
) = range(10)

# Job posting (10–17)
(
    JOB_SUBJECT,
    JOB_LEVEL,
    JOB_ZONE,
    JOB_SCHEDULE,
    JOB_BUDGET,
    JOB_TUTOR_TYPE_PREF,
    JOB_CONTACT,
    JOB_CONFIRM,
) = range(10, 18)

# Match payment screenshot (18)
MATCH_AWAIT_SCREENSHOT = 18

# =============================================================================
# SINGAPORE DATA
# =============================================================================

SUBJECTS = [
    "English", "Mathematics", "Additional Mathematics",
    "Physics", "Chemistry", "Biology", "Combined Science",
    "History", "Geography", "Social Studies",
    "Chinese", "Malay", "Tamil",
    "Economics", "Literature", "Accounting",
    "GP (General Paper)",
]

LEVELS = [
    "Primary 1", "Primary 2", "Primary 3", "Primary 4",
    "Primary 5", "Primary 6 / PSLE",
    "Secondary 1", "Secondary 2", "Secondary 3", "Secondary 4 / O-Levels",
    "JC1", "JC2 / A-Levels",
    "IB / IGCSE", "Poly / ITE",
]

ZONES = [
    "Central",
    "North (Woodlands, Yishun)",
    "North-East (Hougang, Sengkang, AMK)",
    "East (Tampines, Bedok, Pasir Ris)",
    "West (Jurong, Clementi)",
    "South (Queenstown, Tiong Bahru)",
    "Anywhere (Island-wide)",
]

TUTOR_TYPES = [
    "Full-time Tutor",
    "Ex-MOE Teacher",
    "University Undergraduate",
    "University Graduate",
    "Poly Student",
]

REPORT_REASONS = [
    "No-show / ghosted me",
    "Unprofessional behaviour",
    "Fake qualifications",
    "Inappropriate conduct",
    "Requested payment outside platform",
    "Other",
]

# =============================================================================
# HELPERS
# =============================================================================

def make_keyboard(options, cols=2, done_button=False):
    rows = [options[i:i+cols] for i in range(0, len(options), cols)]
    if done_button:
        rows.append(["✅ Done"])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True, one_time_keyboard=False)


def tutor_summary(t):
    return (
        f"👤 *{t['name']}*\n"
        f"🎓 {t['tutor_type']}\n"
        f"📚 {t['subjects']}\n"
        f"🏫 {t['levels']}\n"
        f"💰 ${t['rate_min']}–${t['rate_max']}/hr\n"
        f"📍 {t['zones']}\n"
        f"📋 {t['qualifications']}\n"
    )


def job_summary(j):
    return (
        f"📢 *Tuition Job*\n\n"
        f"📚 Subject: {j['subject']}\n"
        f"🏫 Level: {j['level']}\n"
        f"📍 Zone: {j['zone']}\n"
        f"🗓 Schedule: {j['schedule']}\n"
        f"💰 Budget: ${j['budget']}/hr\n"
        f"👩‍🏫 Preferred Tutor: {j['tutor_type_pref']}\n"
    )


def selection_message(tutor, job, applicant_count, payment_id):
    """
    The core conversion message. Shown AFTER parent shortlists,
    BEFORE the payment wall. Maximises emotional investment.

    Earnings formula:  rate_min × 4 sessions = first month estimate
    Agency commission: rate_min × 4 (agencies typically take 4 sessions)
    Savings vs agency: rate_min × 4 - MATCH_FEE
    """
    estimated_earnings = tutor["rate_min"] * 4
    agency_commission  = tutor["rate_min"] * 4
    your_savings       = agency_commission - MATCH_FEE

    competitor_line = (
        f"👥 You were chosen from *{applicant_count} applicant(s)*."
        if applicant_count > 1
        else "👥 You were the parent's first choice."
    )

    return (
        f"🎉 *A parent has selected you!*\n\n"
        f"{competitor_line}\n\n"
        f"*The job:*\n{job_summary(job)}"
        f"━━━━━━━━━━━━━━\n"
        f"💵 *What you stand to earn:*\n"
        f"Estimated first month: *~${estimated_earnings}*\n"
        f"_(Your rate of ${tutor['rate_min']}/hr × 4 sessions)_\n\n"
        f"🏦 *vs. going through an agency:*\n"
        f"Agency commission: *~${agency_commission}* taken upfront\n"
        f"Our fee: *${MATCH_FEE}* — one time, per match\n"
        f"*You save: ~${your_savings}*\n\n"
        f"━━━━━━━━━━━━━━\n"
        f"⏰ *This offer expires in 24 hours.*\n"
        f"The parent is still reviewing other tutors — confirm now to secure your spot.\n\n"
        f"Pay *${MATCH_FEE}* to unlock the parent's contact."
    )


# =============================================================================
# START + HOW IT WORKS
# =============================================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("👩‍🏫 Register as Tutor", callback_data="register_tutor")],
        [InlineKeyboardButton("👪 Post a Tuition Job", callback_data="post_job")],
        [InlineKeyboardButton("📋 Browse Jobs", callback_data="browse_jobs")],
        [InlineKeyboardButton("ℹ️ How It Works", callback_data="how_it_works")],
    ])
    await update.message.reply_text(
        f"Hi {update.effective_user.first_name}! 👋\n\n"
        "Welcome to *SG Tuition Match* — the fastest way to find or become a tutor in Singapore.\n\n"
        "What would you like to do?",
        reply_markup=keyboard,
        parse_mode="Markdown",
    )


async def how_it_works_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.message.reply_text(
        "ℹ️ *How It Works*\n\n"
        "*For Parents — completely free:*\n"
        "1. Post your tuition job\n"
        "2. Browse tutors who apply\n"
        "3. Shortlist the ones you like — they get notified instantly\n"
        "4. Your chosen tutor contacts you directly\n\n"
        "*For Tutors — free to apply:*\n"
        "1. Register your profile\n"
        "2. Browse and apply for matching jobs — free\n"
        "3. If a parent selects you, you'll be notified\n"
        f"4. Pay *${MATCH_FEE}* to unlock the parent's contact\n"
        f"5. No agency commission — you keep everything you earn\n\n"
        f"_Agencies typically take your entire first month's fee. Our flat "
        f"${MATCH_FEE} match fee saves you hundreds._",
        parse_mode="Markdown",
    )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "Cancelled. Type /start to begin again.",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ConversationHandler.END


# =============================================================================
# TUTOR REGISTRATION
# =============================================================================

async def tutor_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
        send = update.callback_query.message.reply_text
    else:
        send = update.message.reply_text

    context.user_data["tutor"] = {"subjects": [], "levels": [], "zones": []}
    await send(
        "Let's set up your tutor profile! 📝\n\n"
        "Type /cancel at any time to stop.\n\n"
        "What is your *full name*?",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove(),
    )
    return TUTOR_NAME


async def tutor_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["tutor"]["name"] = update.message.text.strip()
    await update.message.reply_text(
        "What type of tutor are you?",
        reply_markup=make_keyboard(TUTOR_TYPES, cols=1),
    )
    return TUTOR_TYPE


async def tutor_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text not in TUTOR_TYPES:
        await update.message.reply_text("Please choose one of the options shown.")
        return TUTOR_TYPE
    context.user_data["tutor"]["tutor_type"] = update.message.text
    await update.message.reply_text(
        "Which subjects do you teach?\n"
        "Select all that apply, then tap *✅ Done*.",
        parse_mode="Markdown",
        reply_markup=make_keyboard(SUBJECTS, cols=2, done_button=True),
    )
    return TUTOR_SUBJECTS


async def tutor_subjects(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "✅ Done":
        if not context.user_data["tutor"]["subjects"]:
            await update.message.reply_text("Please select at least one subject.")
            return TUTOR_SUBJECTS
        await update.message.reply_text(
            "Which levels do you teach?\n"
            "Select all that apply, then tap *✅ Done*.",
            parse_mode="Markdown",
            reply_markup=make_keyboard(LEVELS, cols=2, done_button=True),
        )
        return TUTOR_LEVELS
    if text in SUBJECTS and text not in context.user_data["tutor"]["subjects"]:
        context.user_data["tutor"]["subjects"].append(text)
        await update.message.reply_text(f"✓ {text} added. Select more or tap Done.")
    return TUTOR_SUBJECTS


async def tutor_levels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "✅ Done":
        if not context.user_data["tutor"]["levels"]:
            await update.message.reply_text("Please select at least one level.")
            return TUTOR_LEVELS
        await update.message.reply_text(
            "What is your *minimum hourly rate* in SGD?\n"
            "e.g. `25`",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardRemove(),
        )
        return TUTOR_RATE_MIN
    if text in LEVELS and text not in context.user_data["tutor"]["levels"]:
        context.user_data["tutor"]["levels"].append(text)
        await update.message.reply_text(f"✓ {text} added. Select more or tap Done.")
    return TUTOR_LEVELS


async def tutor_rate_min(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        rate = int(update.message.text.strip().replace("$", ""))
        assert 10 <= rate <= 300
        context.user_data["tutor"]["rate_min"] = rate
        await update.message.reply_text(
            "What is your *maximum hourly rate* in SGD?\n"
            "e.g. `60`",
            parse_mode="Markdown",
        )
        return TUTOR_RATE_MAX
    except (ValueError, AssertionError):
        await update.message.reply_text("Please enter a number between 10 and 300.")
        return TUTOR_RATE_MIN


async def tutor_rate_max(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        rate = int(update.message.text.strip().replace("$", ""))
        assert rate >= context.user_data["tutor"]["rate_min"]
        context.user_data["tutor"]["rate_max"] = rate
        await update.message.reply_text(
            "Which zones can you travel to?\n"
            "Select all that apply, then tap *✅ Done*.",
            parse_mode="Markdown",
            reply_markup=make_keyboard(ZONES, cols=1, done_button=True),
        )
        return TUTOR_ZONES
    except (ValueError, AssertionError):
        await update.message.reply_text("Please enter a number equal to or higher than your minimum.")
        return TUTOR_RATE_MAX


async def tutor_zones(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "✅ Done":
        if not context.user_data["tutor"]["zones"]:
            await update.message.reply_text("Please select at least one zone.")
            return TUTOR_ZONES
        await update.message.reply_text(
            "Briefly describe your qualifications.\n\n"
            "e.g. `NUS Year 3, 5 years tutoring, A for A-Level Maths`",
            reply_markup=ReplyKeyboardRemove(),
        )
        return TUTOR_QUALIFICATIONS
    if text in ZONES and text not in context.user_data["tutor"]["zones"]:
        context.user_data["tutor"]["zones"].append(text)
        await update.message.reply_text(f"✓ {text} added. Select more or tap Done.")
    return TUTOR_ZONES


async def tutor_qualifications(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["tutor"]["qualifications"] = update.message.text.strip()
    await update.message.reply_text(
        "What is your *contact number*?\n"
        "e.g. `91234567`\n\n"
        "Shared with parents when you confirm a match.",
        parse_mode="Markdown",
    )
    return TUTOR_PHONE


async def tutor_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text.strip().replace(" ", "")
    if not (phone.isdigit() and len(phone) == 8 and phone[0] in ("8", "9")):
        await update.message.reply_text(
            "Please enter a valid Singapore mobile number (8 digits, starting with 8 or 9)."
        )
        return TUTOR_PHONE
    context.user_data["tutor"]["phone"] = phone
    t = context.user_data["tutor"]
    await update.message.reply_text(
        "Please confirm your profile:\n\n" +
        tutor_summary({
            **t,
            "subjects": ", ".join(t["subjects"]),
            "levels":   ", ".join(t["levels"]),
            "zones":    ", ".join(t["zones"]),
        }) +
        f"📱 Phone: {t['phone']}\n\n"
        "Is this correct?",
        parse_mode="Markdown",
        reply_markup=make_keyboard(["✅ Confirm", "❌ Start Over"], cols=2),
    )
    return TUTOR_CONFIRM


async def tutor_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "✅ Confirm":
        t = context.user_data["tutor"]
        db.save_tutor(
            telegram_id=update.effective_user.id,
            name=t["name"],
            tutor_type=t["tutor_type"],
            subjects=", ".join(t["subjects"]),
            levels=", ".join(t["levels"]),
            rate_min=t["rate_min"],
            rate_max=t["rate_max"],
            zones=", ".join(t["zones"]),
            qualifications=t["qualifications"],
            phone=t["phone"],
        )
        await update.message.reply_text(
            "🎉 Profile saved!\n\n"
            "Use /browse to see open tuition jobs and apply for free.\n"
            "If a parent selects you, you'll be notified instantly.",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardRemove(),
        )
        context.user_data.clear()
        return ConversationHandler.END
    else:
        context.user_data["tutor"] = {"subjects": [], "levels": [], "zones": []}
        await update.message.reply_text(
            "OK, let's start over. What is your full name?",
            reply_markup=ReplyKeyboardRemove(),
        )
        return TUTOR_NAME


# =============================================================================
# BROWSE JOBS (free for all registered tutors)
# =============================================================================

async def browse_jobs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
        send = update.callback_query.message.reply_text
    else:
        send = update.message.reply_text

    tutor = db.get_tutor_by_telegram_id(update.effective_user.id)

    if not tutor:
        await send(
            "👤 *Register first to browse and apply for jobs.*\n\n"
            "Use /register to set up your tutor profile — it's free and takes a few minutes.",
            parse_mode="Markdown",
        )
        return

    jobs = db.get_open_jobs(limit=10)
    if not jobs:
        await send("No open jobs right now. Check back soon! 🙏")
        return

    await send(f"📋 *{len(jobs)} open job(s) — applying is free:*", parse_mode="Markdown")
    for job in jobs:
        already_applied = db.has_applied(tutor_id=tutor["id"], job_id=job["id"])
        if already_applied:
            button = InlineKeyboardButton("✅ Applied", callback_data="noop")
        else:
            button = InlineKeyboardButton("✋ Apply — Free", callback_data=f"apply_{job['id']}")

        await send(
            job_summary(job) + f"Job ID: #{job['id']}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[button]]),
        )


# =============================================================================
# TUTOR APPLIES (FREE)
# =============================================================================

async def apply_for_job(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Tutor taps Apply. Completely free — just records their application."""
    query = update.callback_query
    await query.answer()

    job_id = int(query.data.split("_")[1])
    tutor  = db.get_tutor_by_telegram_id(update.effective_user.id)

    if not tutor:
        await query.message.reply_text("You need to register first. Use /register.")
        return

    job = db.get_job_by_id(job_id)
    if not job:
        await query.message.reply_text("This job is no longer available.")
        return

    if db.has_applied(tutor_id=tutor["id"], job_id=job_id):
        await query.message.reply_text("You've already applied for this job. Sit tight!")
        return

    db.save_application(tutor_id=tutor["id"], job_id=job_id)

    await query.message.reply_text(
        f"✅ *Application sent!*\n\n"
        f"The parent will review your profile and shortlist who they'd like to hear from.\n\n"
        f"You'll be notified immediately if they select you. 🤞",
        parse_mode="Markdown",
    )

    # Notify parent that a new applicant has come in
    applicant_count = db.count_applications_for_job(job_id)
    try:
        view_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                f"👀 View {applicant_count} Applicant(s)",
                callback_data=f"view_applicants_{job_id}"
            )]
        ])
        await context.bot.send_message(
            chat_id=job["telegram_id"],
            text=(
                f"🔔 *New applicant for your tuition job!*\n\n"
                f"📚 {job['subject']} — {job['level']}\n\n"
                f"You now have *{applicant_count} applicant(s)*. "
                f"Tap below to review profiles and shortlist who you'd like to hear from."
            ),
            parse_mode="Markdown",
            reply_markup=view_keyboard,
        )
    except Exception as e:
        logger.warning(f"Could not notify parent for job {job_id}: {e}")


# =============================================================================
# PARENT VIEWS APPLICANTS + SHORTLISTS
# =============================================================================

async def view_applicants(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Parent taps View Applicants. Shows each tutor profile with a Shortlist button."""
    query = update.callback_query
    await query.answer()

    job_id = int(query.data.split("_")[2])
    job    = db.get_job_by_id(job_id)

    if not job:
        await query.message.reply_text("This job no longer exists.")
        return

    # Security: only the job poster can view applicants
    if update.effective_user.id != job["telegram_id"]:
        await query.message.reply_text("You can only view applicants for your own jobs.")
        return

    applications = db.get_applications_for_job(job_id)
    if not applications:
        await query.message.reply_text("No applicants yet. Check back soon!")
        return

    await query.message.reply_text(
        f"👥 *{len(applications)} applicant(s) for your job:*\n\n"
        f"Tap *Shortlist* on any tutor you'd like to contact you. "
        f"They'll be notified and prompted to confirm.",
        parse_mode="Markdown",
    )

    for app in applications:
        tutor = db.get_tutor_by_id(app["tutor_id"])
        if not tutor:
            continue

        if app["status"] == "shortlisted":
            button = InlineKeyboardButton("✅ Shortlisted", callback_data="noop")
        else:
            button = InlineKeyboardButton(
                "⭐ Shortlist",
                callback_data=f"shortlist_{tutor['id']}_{job_id}"
            )

        await query.message.reply_text(
            tutor_summary(tutor),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[button]]),
        )


async def shortlist_tutor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Parent taps Shortlist.
    Marks the application, then sends the tutor the emotional selection message
    with earnings projection and agency savings — BEFORE the payment wall.
    """
    query = update.callback_query
    await query.answer()

    parts    = query.data.split("_")
    tutor_id = int(parts[1])
    job_id   = int(parts[2])

    job   = db.get_job_by_id(job_id)
    tutor = db.get_tutor_by_id(tutor_id)

    if not job or not tutor:
        await query.message.reply_text("Something went wrong. Please try again.")
        return

    # Security: only the job poster can shortlist
    if update.effective_user.id != job["telegram_id"]:
        await query.message.reply_text("You can only shortlist for your own jobs.")
        return

    # Mark as shortlisted, create pending payment record
    db.shortlist_application(tutor_id=tutor_id, job_id=job_id)
    payment_id = db.create_match_payment(tutor_id=tutor_id, job_id=job_id, amount=MATCH_FEE)

    # Update the button on the parent's screen
    await query.edit_message_reply_markup(
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Shortlisted", callback_data="noop")]
        ])
    )
    await query.message.reply_text(
        f"✅ Shortlisted! {tutor['name']} has been notified and will confirm shortly."
    )

    # Count how many other applicants there were (social proof for tutor)
    applicant_count = db.count_applications_for_job(job_id)

    # Send the tutor the emotional selection notification + earnings numbers
    confirm_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"🔓 Confirm & Pay ${MATCH_FEE} to Unlock Contact",
            callback_data=f"confirmmatch_{payment_id}"
        )]
    ])

    try:
        await context.bot.send_message(
            chat_id=tutor["telegram_id"],
            text=selection_message(tutor, job, applicant_count, payment_id),
            parse_mode="Markdown",
            reply_markup=confirm_keyboard,
        )
    except Exception as e:
        logger.error(f"Could not send selection notification to tutor {tutor['telegram_id']}: {e}")


# =============================================================================
# MATCH PAYMENT FLOW (triggered when tutor taps Confirm & Pay)
# =============================================================================

async def confirm_match(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Tutor taps Confirm & Pay.
    Checks the 24h offer hasn't expired, then shows PayNow details.
    Tutor replies with their PayNow reference number — no photo needed.
    """
    query      = update.callback_query
    await query.answer()

    payment_id = int(query.data.split("_")[1])
    payment    = db.get_match_payment(payment_id)

    if not payment:
        await query.message.reply_text("This offer is no longer available.")
        return

    if payment["status"] == "approved":
        await query.message.reply_text("This match has already been confirmed. ✅")
        return

    # Check 24-hour expiry
    if db.is_match_payment_expired(payment_id):
        await query.message.reply_text(
            "⏰ *This offer has expired.*\n\n"
            "The 24-hour window has passed. "
            "Keep applying for jobs — the next match could come at any time.",
            parse_mode="Markdown",
        )
        return

    tutor = db.get_tutor_by_id(payment["tutor_id"])
    if not tutor or tutor["telegram_id"] != update.effective_user.id:
        await query.message.reply_text("This offer is not for your account.")
        return

    context.user_data["pending_payment_id"] = payment_id

    await query.message.reply_text(
        f"✅ *Almost there — make your PayNow payment to unlock the contact.*\n\n"
        f"PayNow to: 📱 *{PAYNOW_NUMBER}*\n"
        f"Amount: *${MATCH_FEE} SGD*\n"
        f"Reference: `MATCH-{payment_id}`\n\n"
        f"Once paid, reply here with your *PayNow transaction reference number*.\n"
        f"_(e.g. `PAY20240315123456` — found in your banking app after payment)_\n\n"
        f"We'll verify and release the parent's contact within a few hours.",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove(),
    )
    return MATCH_AWAIT_SCREENSHOT


async def receive_match_reference(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Tutor sends PayNow reference number as text. Forwards to admin — no photo storage."""
    payment_id = context.user_data.get("pending_payment_id")
    reference  = update.message.text.strip() if update.message.text else ""

    if not payment_id or not reference:
        await update.message.reply_text(
            "Please reply with your *PayNow transaction reference number*.\n\n"
            "You can find it in your banking app after completing the payment.\n\n"
            "Type /cancel to stop.",
            parse_mode="Markdown",
        )
        return MATCH_AWAIT_SCREENSHOT

    payment = db.get_match_payment(payment_id)
    tutor   = db.get_tutor_by_telegram_id(update.effective_user.id)
    job     = db.get_job_by_id(payment["job_id"])

    db.save_match_reference(payment_id=payment_id, reference=reference)

    if ADMIN_ID:
        admin_keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Approve", callback_data=f"match_approve_{payment_id}"),
                InlineKeyboardButton("❌ Reject",  callback_data=f"match_reject_{payment_id}"),
            ]
        ])
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=(
                f"💰 *Match Payment Received*\n\n"
                f"Payment ID: #{payment_id}\n"
                f"Amount: ${MATCH_FEE}\n"
                f"Reference: `MATCH-{payment_id}`\n"
                f"*Tutor's PayNow ref:* `{reference}`\n\n"
                f"*Tutor:*\n{tutor_summary(tutor)}"
                f"📱 Phone: {tutor['phone']}\n\n"
                f"*Job:*\n{job_summary(job)}"
            ),
            parse_mode="Markdown",
            reply_markup=admin_keyboard,
        )

    await update.message.reply_text(
        "✅ Reference number received! We'll verify your payment and send you the parent's contact shortly.\n\n"
        "This usually takes a few hours.",
        reply_markup=ReplyKeyboardRemove(),
    )
    context.user_data.clear()
    return ConversationHandler.END


# =============================================================================
# ADMIN: APPROVE / REJECT MATCH PAYMENT
# =============================================================================

async def approve_match(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin approves payment → releases contact to tutor, notifies parent."""
    query = update.callback_query
    await query.answer()

    if update.effective_user.id != ADMIN_ID:
        await query.message.reply_text("You are not authorised to do this.")
        return

    payment_id = int(query.data.split("_")[2])
    payment    = db.get_match_payment(payment_id)

    if not payment:
        await query.message.reply_text("Payment record not found.")
        return
    if payment["status"] == "approved":
        await query.message.reply_text("Already approved.")
        return

    db.approve_match_payment(payment_id)

    tutor = db.get_tutor_by_id(payment["tutor_id"])
    job   = db.get_job_by_id(payment["job_id"])

    # Record the confirmed match
    db.record_interest(tutor_id=tutor["id"], job_id=job["id"])

    try:
        # Send contact to tutor
        await context.bot.send_message(
            chat_id=tutor["telegram_id"],
            text=(
                f"✅ *Payment verified! Here is your match.*\n\n"
                f"*Job details:*\n{job_summary(job)}"
                f"\n📱 Contact the parent at: *{job['contact']}*\n\n"
                "Good luck! 🍀"
            ),
            parse_mode="Markdown",
        )

        # Notify parent that tutor is on the way
        report_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🚩 Report This Tutor", callback_data=f"report_{tutor['id']}_{job['id']}")]
        ])
        await context.bot.send_message(
            chat_id=job["telegram_id"],
            text=(
                f"👋 *Your tutor is confirmed!*\n\n"
                f"{tutor_summary(tutor)}"
                f"📱 They will reach out to you at: *{job['contact']}*\n\n"
                "Arrange a trial lesson and see if it's a good fit!\n\n"
                "_If this tutor behaves inappropriately, tap below to report them._"
            ),
            parse_mode="Markdown",
            reply_markup=report_keyboard,
        )

        await query.message.reply_text(
            f"✅ Payment #{payment_id} approved. {tutor['name']} has been given the parent's contact."
        )
    except Exception as e:
        logger.error(f"Error sending approval notifications: {e}")
        await query.message.reply_text(f"Approved but notification failed: {e}")


async def reject_match(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin rejects payment → notifies tutor to resubmit."""
    query = update.callback_query
    await query.answer()

    if update.effective_user.id != ADMIN_ID:
        await query.message.reply_text("You are not authorised to do this.")
        return

    payment_id = int(query.data.split("_")[2])
    payment    = db.get_match_payment(payment_id)

    if not payment:
        await query.message.reply_text("Payment record not found.")
        return

    db.reject_match_payment(payment_id)
    tutor = db.get_tutor_by_id(payment["tutor_id"])

    try:
        await context.bot.send_message(
            chat_id=tutor["telegram_id"],
            text=(
                "❌ *Payment could not be verified.*\n\n"
                "This could be because:\n"
                "• The reference number was missing\n"
                "• The amount was incorrect\n"
                "• The screenshot was unclear\n\n"
                f"Please PayNow *${MATCH_FEE}* to *{PAYNOW_NUMBER}* "
                f"with reference `MATCH-{payment_id}` and resubmit your screenshot."
            ),
            parse_mode="Markdown",
        )
        await query.message.reply_text(f"❌ Payment #{payment_id} rejected. Tutor notified.")
    except Exception as e:
        logger.error(f"Error sending rejection notification: {e}")
        await query.message.reply_text(f"Rejected but notification failed: {e}")


# =============================================================================
# JOB POSTING
# =============================================================================

async def job_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
        send = update.callback_query.message.reply_text
    else:
        send = update.message.reply_text

    context.user_data["job"] = {}
    await send(
        "Let's post your tuition job! 📢\n\n"
        "Type /cancel at any time to stop.\n\n"
        "What *subject* do you need help with?",
        parse_mode="Markdown",
        reply_markup=make_keyboard(SUBJECTS, cols=2),
    )
    return JOB_SUBJECT


async def job_subject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text not in SUBJECTS:
        await update.message.reply_text("Please choose from the options shown.")
        return JOB_SUBJECT
    context.user_data["job"]["subject"] = update.message.text
    await update.message.reply_text("What level?", reply_markup=make_keyboard(LEVELS, cols=2))
    return JOB_LEVEL


async def job_level(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text not in LEVELS:
        await update.message.reply_text("Please choose from the options shown.")
        return JOB_LEVEL
    context.user_data["job"]["level"] = update.message.text
    await update.message.reply_text("Which zone are you in?", reply_markup=make_keyboard(ZONES, cols=1))
    return JOB_ZONE


async def job_zone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text not in ZONES:
        await update.message.reply_text("Please choose from the options shown.")
        return JOB_ZONE
    context.user_data["job"]["zone"] = update.message.text
    await update.message.reply_text(
        "When do you need sessions?\n\ne.g. `Weekday evenings, 2x per week`",
        reply_markup=ReplyKeyboardRemove(),
    )
    return JOB_SCHEDULE


async def job_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["job"]["schedule"] = update.message.text.strip()
    await update.message.reply_text(
        "What is your *budget per hour* in SGD?\ne.g. `40`",
        parse_mode="Markdown",
    )
    return JOB_BUDGET


async def job_budget(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        budget = int(update.message.text.strip().replace("$", ""))
        assert budget >= 10
        context.user_data["job"]["budget"] = budget
        await update.message.reply_text(
            "Any preference for tutor type?",
            reply_markup=make_keyboard(["No Preference"] + TUTOR_TYPES, cols=1),
        )
        return JOB_TUTOR_TYPE_PREF
    except (ValueError, AssertionError):
        await update.message.reply_text("Please enter a valid amount, e.g. `40`")
        return JOB_BUDGET


async def job_tutor_type_pref(update: Update, context: ContextTypes.DEFAULT_TYPE):
    valid = ["No Preference"] + TUTOR_TYPES
    if update.message.text not in valid:
        await update.message.reply_text("Please choose from the options shown.")
        return JOB_TUTOR_TYPE_PREF
    context.user_data["job"]["tutor_type_pref"] = update.message.text
    await update.message.reply_text(
        "How should tutors contact you?\n\ne.g. `Telegram @username` or `WhatsApp 91234567`",
        reply_markup=ReplyKeyboardRemove(),
    )
    return JOB_CONTACT


async def job_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["job"]["contact"] = update.message.text.strip()
    j = context.user_data["job"]
    await update.message.reply_text(
        "Please confirm your job posting:\n\n" + job_summary(j) + "\nIs this correct?",
        parse_mode="Markdown",
        reply_markup=make_keyboard(["✅ Post Job", "❌ Start Over"], cols=2),
    )
    return JOB_CONFIRM


async def job_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "✅ Post Job":
        j = context.user_data["job"]
        job_id = db.save_job(
            telegram_id=update.effective_user.id,
            subject=j["subject"],
            level=j["level"],
            zone=j["zone"],
            schedule=j["schedule"],
            budget=j["budget"],
            tutor_type_pref=j["tutor_type_pref"],
            contact=j["contact"],
        )
        await update.message.reply_text(
            f"✅ Job posted! (Job ID: #{job_id})\n\n"
            "Matching tutors are being notified now.\n\n"
            "/myjobs — view your postings",
            reply_markup=ReplyKeyboardRemove(),
        )

        # Notify ALL matching active tutors (no subscription gate)
        matching_tutors = db.find_matching_tutors(
            subject=j["subject"],
            level=j["level"],
            zone=j["zone"],
            budget=j["budget"],
        )

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✋ Apply — Free", callback_data=f"apply_{job_id}")]
        ])

        for tutor in matching_tutors:
            try:
                await context.bot.send_message(
                    chat_id=tutor["telegram_id"],
                    text=(
                        "🔔 *New Matching Job!*\n\n"
                        + job_summary(j)
                        + f"\nJob ID: #{job_id}\n\n"
                        "Applying is free. If the parent shortlists you, you'll be notified."
                    ),
                    parse_mode="Markdown",
                    reply_markup=keyboard,
                )
            except Exception as e:
                logger.warning(f"Could not notify tutor {tutor['telegram_id']}: {e}")

        context.user_data.clear()
        return ConversationHandler.END
    else:
        context.user_data["job"] = {}
        await update.message.reply_text(
            "OK, let's start over. What subject do you need help with?",
            reply_markup=make_keyboard(SUBJECTS, cols=2),
        )
        return JOB_SUBJECT


# =============================================================================
# MY JOBS
# =============================================================================

async def my_jobs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    jobs = db.get_jobs_by_poster(update.effective_user.id)
    if not jobs:
        await update.message.reply_text("You haven't posted any jobs yet. Use /postjob.")
        return
    await update.message.reply_text("📋 *Your job postings:*", parse_mode="Markdown")
    for job in jobs:
        count = db.count_applications_for_job(job["id"])
        view_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"👀 View {count} Applicant(s)", callback_data=f"view_applicants_{job['id']}")]
        ]) if count > 0 else None
        await update.message.reply_text(
            job_summary(job) +
            f"Job ID: #{job['id']} | Status: *{job['status']}*\n"
            f"👥 Applicants: {count}",
            parse_mode="Markdown",
            reply_markup=view_keyboard,
        )


# =============================================================================
# REPORT FLOW
# =============================================================================

async def report_tutor_reasons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    parts    = query.data.split("_")
    tutor_id = int(parts[1])
    job_id   = int(parts[2])

    reason_buttons = [
        [InlineKeyboardButton(reason, callback_data=f"reportreason_{tutor_id}_{job_id}_{i}")]
        for i, reason in enumerate(REPORT_REASONS)
    ]
    reason_buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="admin_cancel")])

    await query.message.reply_text(
        "🚩 *Report Tutor*\n\nWhat is the reason for your report?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(reason_buttons),
    )


async def report_tutor_submit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    parts    = query.data.split("_")
    tutor_id = int(parts[1])
    job_id   = int(parts[2])
    reason   = REPORT_REASONS[int(parts[3])]

    tutor = db.get_tutor_by_id(tutor_id)
    job   = db.get_job_by_id(job_id)

    if not tutor:
        await query.message.reply_text("Could not find this tutor. They may have already been removed.")
        return

    report_id = db.save_report(
        reporter_telegram_id=update.effective_user.id,
        tutor_id=tutor_id,
        job_id=job_id,
        reason=reason,
    )

    await query.message.reply_text(
        "✅ *Report submitted. Thank you.*\n\n"
        "We take all reports seriously and will review this within 24 hours.\n\n"
        "_Your contact details are not shared with the tutor._",
        parse_mode="Markdown",
    )

    report_count = db.count_reports_for_tutor(tutor_id)
    auto_banned  = False

    if report_count >= AUTO_BAN_THRESHOLD and tutor["active"]:
        db.set_tutor_active(tutor_id, active=False)
        auto_banned = True
        try:
            await context.bot.send_message(
                chat_id=tutor["telegram_id"],
                text=(
                    "⚠️ *Your account has been suspended.*\n\n"
                    "Your profile has received multiple reports and has been "
                    "automatically suspended pending review.\n\n"
                    "If you believe this is a mistake, please contact us."
                ),
                parse_mode="Markdown",
            )
        except Exception:
            pass

    if ADMIN_ID:
        auto_ban_note = "\n\n⚠️ *TUTOR HAS BEEN AUTO-BANNED*" if auto_banned else ""
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=(
                f"🚩 *New Tutor Report*\n\n"
                f"Report #{report_id} | Total reports: {report_count}\n\n"
                f"*Tutor:*\n{tutor_summary(tutor)}"
                f"📱 {tutor['phone']} | 🆔 `{tutor['telegram_id']}`\n\n"
                f"*Reason:* {reason}\n\n"
                f"*Job:*\n{job_summary(job) if job else 'N/A'}"
                f"{auto_ban_note}"
            ),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🚫 Ban Tutor", callback_data=f"admin_ban_tutor_{tutor_id}"),
                    InlineKeyboardButton("✅ Dismiss",   callback_data=f"admin_dismiss_report_{report_id}"),
                ]
            ]),
        )


async def admin_dismiss_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if update.effective_user.id != ADMIN_ID:
        return
    report_id = int(query.data.split("_")[3])
    db.dismiss_report(report_id)
    await query.message.reply_text(f"✅ Report #{report_id} dismissed.")


# =============================================================================
# ADMIN: USER MANAGEMENT
# =============================================================================

async def list_tutors(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("This command is for admins only.")
        return

    tutors = db.get_all_tutors()
    if not tutors:
        await update.message.reply_text("No tutors registered yet.")
        return

    await update.message.reply_text(f"👩‍🏫 *{len(tutors)} registered tutor(s):*", parse_mode="Markdown")

    for t in tutors:
        report_count = db.count_reports_for_tutor(t["id"])
        report_line  = f"🚩 Reports: {report_count}\n" if report_count > 0 else ""
        status_line  = "🟢 Active" if t["active"] else "🔴 Banned"

        await update.message.reply_text(
            f"*#{t['id']} — {t['name']}*\n"
            f"🎓 {t['tutor_type']}\n"
            f"📚 {t['subjects']}\n"
            f"🏫 {t['levels']}\n"
            f"📍 {t['zones']}\n"
            f"💰 ${t['rate_min']}–${t['rate_max']}/hr\n"
            f"📱 {t['phone']}\n"
            f"🆔 TG ID: `{t['telegram_id']}`\n"
            f"📅 Joined: {t['created_at'][:10]}\n"
            f"Status: {status_line}\n"
            f"{report_line}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🗑 Delete", callback_data=f"admin_delete_tutor_{t['id']}"),
                    InlineKeyboardButton("🚫 Ban",    callback_data=f"admin_ban_tutor_{t['id']}"),
                ]
            ]),
        )


async def list_jobs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("This command is for admins only.")
        return

    jobs = db.get_all_jobs()
    if not jobs:
        await update.message.reply_text("No jobs posted yet.")
        return

    await update.message.reply_text(f"📋 *{len(jobs)} job(s):*", parse_mode="Markdown")
    for j in jobs:
        status_emoji = "🟢" if j["status"] == "open" else "⚫"
        count = db.count_applications_for_job(j["id"])
        await update.message.reply_text(
            f"*#{j['id']} — {j['subject']} ({j['level']})*\n"
            f"📍 {j['zone']} | 💰 ${j['budget']}/hr\n"
            f"🗓 {j['schedule']}\n"
            f"👩‍🏫 Pref: {j['tutor_type_pref']}\n"
            f"📱 Contact: {j['contact']}\n"
            f"📅 Posted: {j['created_at'][:10]}\n"
            f"👥 Applicants: {count}\n"
            f"{status_emoji} Status: {j['status']}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🗑 Delete Job", callback_data=f"admin_delete_job_{j['id']}")]
            ]),
        )


async def admin_delete_tutor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if update.effective_user.id != ADMIN_ID:
        return

    tutor_id = int(query.data.split("_")[3])
    tutor    = db.get_tutor_by_id(tutor_id)
    if not tutor:
        await query.message.reply_text("Tutor not found.")
        return

    await query.message.reply_text(
        f"⚠️ Delete *{tutor['name']}*? This cannot be undone.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Yes, delete", callback_data=f"admin_confirm_delete_tutor_{tutor_id}"),
                InlineKeyboardButton("❌ Cancel",      callback_data="admin_cancel"),
            ]
        ]),
    )


async def admin_confirm_delete_tutor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if update.effective_user.id != ADMIN_ID:
        return

    tutor_id = int(query.data.split("_")[4])
    tutor    = db.get_tutor_by_id(tutor_id)
    if not tutor:
        await query.message.reply_text("Tutor not found.")
        return

    db.delete_tutor(tutor_id)
    try:
        await context.bot.send_message(
            chat_id=tutor["telegram_id"],
            text="Your tutor profile has been removed from SG Tuition Match.\n\nIf you believe this is a mistake, please contact us.",
        )
    except Exception:
        pass
    await query.message.reply_text(f"✅ Tutor *{tutor['name']}* deleted.", parse_mode="Markdown")


async def admin_ban_tutor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if update.effective_user.id != ADMIN_ID:
        return

    tutor_id = int(query.data.split("_")[3])
    tutor    = db.get_tutor_by_id(tutor_id)
    if not tutor:
        await query.message.reply_text("Tutor not found.")
        return

    db.set_tutor_active(tutor_id, active=False)
    try:
        await context.bot.send_message(
            chat_id=tutor["telegram_id"],
            text="⚠️ Your tutor profile has been suspended from SG Tuition Match.\n\nIf you believe this is a mistake, please contact us.",
        )
    except Exception:
        pass
    await query.message.reply_text(f"🚫 *{tutor['name']}* banned.", parse_mode="Markdown")


async def admin_delete_job(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if update.effective_user.id != ADMIN_ID:
        return

    job_id = int(query.data.split("_")[3])
    await query.message.reply_text(
        f"⚠️ Delete job #{job_id}? This cannot be undone.",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Yes, delete", callback_data=f"admin_confirm_delete_job_{job_id}"),
                InlineKeyboardButton("❌ Cancel",      callback_data="admin_cancel"),
            ]
        ]),
    )


async def admin_confirm_delete_job(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if update.effective_user.id != ADMIN_ID:
        return
    job_id = int(query.data.split("_")[4])
    db.delete_job(job_id)
    await query.message.reply_text(f"✅ Job #{job_id} deleted.")


async def admin_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text("Cancelled.")


async def noop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles already-applied / already-shortlisted buttons gracefully."""
    await update.callback_query.answer()


# =============================================================================
# ADMIN: STATS
# =============================================================================

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("This command is for admins only.")
        return

    stats = db.get_stats()
    await update.message.reply_text(
        "📊 *Platform Stats*\n\n"
        f"👩‍🏫 Registered tutors: {stats['tutors']}\n"
        f"📋 Open jobs: {stats['open_jobs']}\n"
        f"📋 Total jobs: {stats['total_jobs']}\n"
        f"✋ Total applications: {stats['total_applications']}\n"
        f"⭐ Shortlisted: {stats['shortlisted']}\n"
        f"💰 Pending payments: {stats['pending_payments']}\n"
        f"✅ Confirmed matches: {stats['confirmed_matches']}\n"
        f"🚩 Pending reports: {stats['pending_reports']}\n"
        f"💵 Total earned: ${stats['total_earned']} SGD\n",
        parse_mode="Markdown",
    )


# =============================================================================
# MAIN
# =============================================================================

def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable is not set.")
    if ADMIN_ID == 0:
        logger.warning("ADMIN_TELEGRAM_ID not set — payment approvals will not work!")

    app = Application.builder().token(token).build()

    # --- Tutor registration ---
    tutor_conv = ConversationHandler(
        entry_points=[
            CommandHandler("register", tutor_start),
            CallbackQueryHandler(tutor_start, pattern="^register_tutor$"),
        ],
        states={
            TUTOR_NAME:           [MessageHandler(filters.TEXT & ~filters.COMMAND, tutor_name)],
            TUTOR_TYPE:           [MessageHandler(filters.TEXT & ~filters.COMMAND, tutor_type)],
            TUTOR_SUBJECTS:       [MessageHandler(filters.TEXT & ~filters.COMMAND, tutor_subjects)],
            TUTOR_LEVELS:         [MessageHandler(filters.TEXT & ~filters.COMMAND, tutor_levels)],
            TUTOR_RATE_MIN:       [MessageHandler(filters.TEXT & ~filters.COMMAND, tutor_rate_min)],
            TUTOR_RATE_MAX:       [MessageHandler(filters.TEXT & ~filters.COMMAND, tutor_rate_max)],
            TUTOR_ZONES:          [MessageHandler(filters.TEXT & ~filters.COMMAND, tutor_zones)],
            TUTOR_QUALIFICATIONS: [MessageHandler(filters.TEXT & ~filters.COMMAND, tutor_qualifications)],
            TUTOR_PHONE:          [MessageHandler(filters.TEXT & ~filters.COMMAND, tutor_phone)],
            TUTOR_CONFIRM:        [MessageHandler(filters.TEXT & ~filters.COMMAND, tutor_confirm)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # --- Job posting ---
    job_conv = ConversationHandler(
        entry_points=[
            CommandHandler("postjob", job_start),
            CallbackQueryHandler(job_start, pattern="^post_job$"),
        ],
        states={
            JOB_SUBJECT:         [MessageHandler(filters.TEXT & ~filters.COMMAND, job_subject)],
            JOB_LEVEL:           [MessageHandler(filters.TEXT & ~filters.COMMAND, job_level)],
            JOB_ZONE:            [MessageHandler(filters.TEXT & ~filters.COMMAND, job_zone)],
            JOB_SCHEDULE:        [MessageHandler(filters.TEXT & ~filters.COMMAND, job_schedule)],
            JOB_BUDGET:          [MessageHandler(filters.TEXT & ~filters.COMMAND, job_budget)],
            JOB_TUTOR_TYPE_PREF: [MessageHandler(filters.TEXT & ~filters.COMMAND, job_tutor_type_pref)],
            JOB_CONTACT:         [MessageHandler(filters.TEXT & ~filters.COMMAND, job_contact)],
            JOB_CONFIRM:         [MessageHandler(filters.TEXT & ~filters.COMMAND, job_confirm)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # --- Match payment ---
    match_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(confirm_match, pattern=r"^confirmmatch_\d+$"),
        ],
        states={
            MATCH_AWAIT_SCREENSHOT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_match_reference),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # --- Register handlers ---
    app.add_handler(tutor_conv)
    app.add_handler(job_conv)
    app.add_handler(match_conv)

    # Commands
    app.add_handler(CommandHandler("start",      start))
    app.add_handler(CommandHandler("browse",     browse_jobs))
    app.add_handler(CommandHandler("myjobs",     my_jobs))
    app.add_handler(CommandHandler("stats",      admin_stats))
    app.add_handler(CommandHandler("listtutors", list_tutors))
    app.add_handler(CommandHandler("listjobs",   list_jobs))

    # Callbacks
    app.add_handler(CallbackQueryHandler(browse_jobs,                pattern="^browse_jobs$"))
    app.add_handler(CallbackQueryHandler(how_it_works_cb,            pattern="^how_it_works$"))
    app.add_handler(CallbackQueryHandler(apply_for_job,              pattern=r"^apply_\d+$"))
    app.add_handler(CallbackQueryHandler(view_applicants,            pattern=r"^view_applicants_\d+$"))
    app.add_handler(CallbackQueryHandler(shortlist_tutor,            pattern=r"^shortlist_\d+_\d+$"))
    app.add_handler(CallbackQueryHandler(approve_match,              pattern=r"^match_approve_\d+$"))
    app.add_handler(CallbackQueryHandler(reject_match,               pattern=r"^match_reject_\d+$"))
    app.add_handler(CallbackQueryHandler(report_tutor_reasons,       pattern=r"^report_\d+_\d+$"))
    app.add_handler(CallbackQueryHandler(report_tutor_submit,        pattern=r"^reportreason_\d+_\d+_\d+$"))
    app.add_handler(CallbackQueryHandler(admin_dismiss_report,       pattern=r"^admin_dismiss_report_\d+$"))
    app.add_handler(CallbackQueryHandler(admin_delete_tutor,         pattern=r"^admin_delete_tutor_\d+$"))
    app.add_handler(CallbackQueryHandler(admin_confirm_delete_tutor, pattern=r"^admin_confirm_delete_tutor_\d+$"))
    app.add_handler(CallbackQueryHandler(admin_ban_tutor,            pattern=r"^admin_ban_tutor_\d+$"))
    app.add_handler(CallbackQueryHandler(admin_delete_job,           pattern=r"^admin_delete_job_\d+$"))
    app.add_handler(CallbackQueryHandler(admin_confirm_delete_job,   pattern=r"^admin_confirm_delete_job_\d+$"))
    app.add_handler(CallbackQueryHandler(admin_cancel,               pattern="^admin_cancel$"))
    app.add_handler(CallbackQueryHandler(noop,                       pattern="^noop$"))

    logger.info("Bot is running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
