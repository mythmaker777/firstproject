"""
SG Tuition Match Bot v3 — with PayNow payment flow
====================================================
Payment flow:
  1. Tutor taps "Express Interest"
  2. Bot sends PayNow details + referral fee amount
  3. Tutor uploads payment screenshot
  4. Admin receives screenshot + Approve/Reject buttons
  5. On approval → parent's contact is sent to tutor automatically
"""

import logging
import os
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

db = Database("tuition.db")

# =============================================================================
# CONFIG — set these as Railway environment variables
# =============================================================================
# Your Telegram ID (get it from @userinfobot on Telegram)
ADMIN_ID = int(os.environ.get("ADMIN_TELEGRAM_ID", "0"))

# Your PayNow number (your Singapore mobile number linked to PayNow)
PAYNOW_NUMBER = os.environ.get("PAYNOW_NUMBER", "9XXXXXXX")

# How much you charge tutors per successful match (SGD)
REFERRAL_FEE = int(os.environ.get("REFERRAL_FEE", "50"))

# =============================================================================
# CONVERSATION STATES
# =============================================================================

# Tutor registration
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

# Job posting
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

# Payment flow
PAYMENT_AWAIT_SCREENSHOT = 18

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
        f"📱 Contact: {j['contact']}\n"
    )


# =============================================================================
# START + HELP
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
        "*For Parents:*\n"
        "1. Post your tuition job\n"
        "2. Matching tutors will contact you\n"
        "3. Arrange a trial lesson directly\n\n"
        "*For Tutors:*\n"
        "1. Register your profile\n"
        "2. Get notified of matching jobs\n"
        f"3. Pay a ${REFERRAL_FEE} referral fee via PayNow\n"
        "4. Receive parent's contact instantly\n\n"
        "*Free for parents. One-time referral fee for tutors.* 🎉",
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
        "Shared with parents only after a successful match.",
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
            "levels": ", ".join(t["levels"]),
            "zones": ", ".join(t["zones"]),
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
            "🎉 Profile saved! You'll be notified when a matching job is posted.\n\n"
            "/browse — see open jobs\n"
            "/register — update your profile",
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
        "When do you need sessions?\n\n"
        "e.g. `Weekday evenings, 2x per week`",
        reply_markup=ReplyKeyboardRemove(),
    )
    return JOB_SCHEDULE


async def job_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["job"]["schedule"] = update.message.text.strip()
    await update.message.reply_text(
        "What is your *budget per hour* in SGD?\n"
        "e.g. `40`",
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
        "How should tutors contact you?\n\n"
        "e.g. `Telegram @username` or `WhatsApp 91234567`",
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

        matching_tutors = db.find_matching_tutors(
            subject=j["subject"],
            level=j["level"],
            zone=j["zone"],
            budget=j["budget"],
        )

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✋ Express Interest", callback_data=f"interest_{job_id}")]
        ])

        for tutor in matching_tutors:
            try:
                await context.bot.send_message(
                    chat_id=tutor["telegram_id"],
                    text=(
                        "🔔 *New Matching Job!*\n\n"
                        + job_summary(j)
                        + f"\nJob ID: #{job_id}\n\n"
                        "Tap below to express interest."
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
# BROWSE
# =============================================================================

async def browse_jobs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
        send = update.callback_query.message.reply_text
    else:
        send = update.message.reply_text

    jobs = db.get_open_jobs(limit=10)
    if not jobs:
        await send("No open jobs right now. Check back soon! 🙏")
        return

    await send(f"📋 *{len(jobs)} open job(s):*", parse_mode="Markdown")
    for job in jobs:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✋ Express Interest", callback_data=f"interest_{job['id']}")]
        ])
        await send(
            job_summary(job) + f"Job ID: #{job['id']}",
            parse_mode="Markdown",
            reply_markup=keyboard,
        )


# =============================================================================
# PAYMENT FLOW
# =============================================================================

async def express_interest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Step 1: Tutor taps Express Interest.
    Check they're registered, job exists, not already applied.
    Then ask for PayNow payment.
    """
    query = update.callback_query
    await query.answer()

    job_id = int(query.data.split("_")[1])
    tutor_tg_id = update.effective_user.id

    tutor = db.get_tutor_by_telegram_id(tutor_tg_id)
    if not tutor:
        await query.message.reply_text("You need to register first. Use /register.")
        return ConversationHandler.END

    job = db.get_job_by_id(job_id)
    if not job:
        await query.message.reply_text("This job is no longer available.")
        return ConversationHandler.END

    # Check for duplicate interest
    if db.has_expressed_interest(tutor_id=tutor["id"], job_id=job_id):
        await query.message.reply_text(
            "You've already expressed interest in this job.\n\n"
            "If you paid and are still waiting for approval, please be patient — "
            "it is reviewed within 24 hours."
        )
        return ConversationHandler.END

    # Create a pending payment record
    payment_id = db.create_payment(tutor_id=tutor["id"], job_id=job_id, amount=REFERRAL_FEE)

    # Store in user_data so the screenshot handler knows what to attach it to
    context.user_data["pending_payment_id"] = payment_id
    context.user_data["pending_job_id"] = job_id

    await query.message.reply_text(
        f"✋ *Great! One last step to get the parent's contact.*\n\n"
        f"A referral fee of *${REFERRAL_FEE} SGD* applies for successful matches.\n\n"
        f"Please PayNow to:\n"
        f"📱 *{PAYNOW_NUMBER}*\n"
        f"Reference: `TUITION-{payment_id}`\n\n"
        f"Once paid, send a *screenshot* of your payment confirmation here and "
        f"we will verify and release the parent's contact within a few hours.",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove(),
    )
    return PAYMENT_AWAIT_SCREENSHOT


async def receive_payment_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Step 2: Tutor sends screenshot.
    Forward it to admin with Approve/Reject buttons.
    """
    payment_id = context.user_data.get("pending_payment_id")
    job_id = context.user_data.get("pending_job_id")

    if not payment_id or not update.message.photo:
        await update.message.reply_text(
            "Please send a *screenshot image* of your PayNow payment confirmation.",
            parse_mode="Markdown",
        )
        return PAYMENT_AWAIT_SCREENSHOT

    tutor_tg_id = update.effective_user.id
    tutor = db.get_tutor_by_telegram_id(tutor_tg_id)
    job = db.get_job_by_id(job_id)

    # Store the file_id so admin can view the screenshot later if needed
    photo_file_id = update.message.photo[-1].file_id  # -1 = highest resolution
    db.attach_screenshot(payment_id=payment_id, photo_file_id=photo_file_id)

    # Notify admin
    if ADMIN_ID:
        admin_keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Approve", callback_data=f"approve_{payment_id}"),
                InlineKeyboardButton("❌ Reject", callback_data=f"reject_{payment_id}"),
            ]
        ])
        await context.bot.send_photo(
            chat_id=ADMIN_ID,
            photo=photo_file_id,
            caption=(
                f"💰 *Payment Screenshot Received*\n\n"
                f"Payment ID: #{payment_id}\n"
                f"Amount: ${REFERRAL_FEE}\n"
                f"Reference: TUITION-{payment_id}\n\n"
                f"*Tutor:*\n{tutor_summary(tutor)}"
                f"📱 Phone: {tutor['phone']}\n\n"
                f"*Job:*\n{job_summary(job)}"
            ),
            parse_mode="Markdown",
            reply_markup=admin_keyboard,
        )

    await update.message.reply_text(
        "✅ Screenshot received! We'll verify your payment and send you the parent's contact shortly.\n\n"
        "This usually takes a few hours.",
        reply_markup=ReplyKeyboardRemove(),
    )
    context.user_data.clear()
    return ConversationHandler.END


async def handle_non_photo_in_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Catches text messages sent during the payment screenshot step."""
    await update.message.reply_text(
        "Please send a *screenshot image* (photo) of your PayNow payment.\n\n"
        "If you want to cancel, type /cancel.",
        parse_mode="Markdown",
    )
    return PAYMENT_AWAIT_SCREENSHOT


# =============================================================================
# ADMIN: APPROVE / REJECT
# =============================================================================

async def approve_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Admin taps Approve.
    Marks payment as approved in DB, then sends parent's contact to tutor.
    """
    query = update.callback_query
    await query.answer()

    # Security: only admin can approve
    if update.effective_user.id != ADMIN_ID:
        await query.message.reply_text("You are not authorised to do this.")
        return

    payment_id = int(query.data.split("_")[1])
    payment = db.get_payment(payment_id)

    if not payment:
        await query.message.reply_text("Payment record not found.")
        return

    if payment["status"] == "approved":
        await query.message.reply_text("This payment was already approved.")
        return

    db.approve_payment(payment_id)

    tutor = db.get_tutor_by_id(payment["tutor_id"])
    job = db.get_job_by_id(payment["job_id"])

    # Record interest as confirmed
    db.record_interest(tutor_id=tutor["id"], job_id=job["id"])

    # Send parent contact to tutor
    try:
        await context.bot.send_message(
            chat_id=tutor["telegram_id"],
            text=(
                f"✅ *Payment verified! Here is your match.*\n\n"
                f"*Job Details:*\n{job_summary(job)}"
                f"\n📱 Contact the parent at: *{job['contact']}*\n\n"
                "Good luck! 🍀"
            ),
            parse_mode="Markdown",
        )

        # Also notify the parent that a tutor is coming
        await context.bot.send_message(
            chat_id=job["telegram_id"],
            text=(
                f"👋 *A tutor is on their way!*\n\n"
                f"{tutor_summary(tutor)}"
                f"📱 They will contact you at: *{job['contact']}*\n\n"
                "Arrange a trial lesson and see if it's a good fit!"
            ),
            parse_mode="Markdown",
        )

        # Confirm to admin
        await query.message.reply_text(
            f"✅ Payment #{payment_id} approved.\n"
            f"Tutor {tutor['name']} has been given the parent's contact."
        )

    except Exception as e:
        logger.error(f"Error sending approval notifications: {e}")
        await query.message.reply_text(f"Approval saved but notification failed: {e}")


async def reject_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Admin taps Reject.
    Marks payment as rejected and notifies the tutor.
    """
    query = update.callback_query
    await query.answer()

    if update.effective_user.id != ADMIN_ID:
        await query.message.reply_text("You are not authorised to do this.")
        return

    payment_id = int(query.data.split("_")[1])
    payment = db.get_payment(payment_id)

    if not payment:
        await query.message.reply_text("Payment record not found.")
        return

    db.reject_payment(payment_id)
    tutor = db.get_tutor_by_id(payment["tutor_id"])

    try:
        await context.bot.send_message(
            chat_id=tutor["telegram_id"],
            text=(
                "❌ *Payment could not be verified.*\n\n"
                "Your screenshot didn't match our records. This could be because:\n"
                "• The reference number was missing\n"
                "• The amount was incorrect\n"
                "• The screenshot was unclear\n\n"
                f"Please PayNow *${REFERRAL_FEE}* to *{PAYNOW_NUMBER}* with "
                f"reference `TUITION-{payment_id}` and resubmit.\n\n"
                "To resubmit, tap Express Interest on the job again."
            ),
            parse_mode="Markdown",
        )
        await query.message.reply_text(f"❌ Payment #{payment_id} rejected. Tutor has been notified.")
    except Exception as e:
        logger.error(f"Error sending rejection notification: {e}")
        await query.message.reply_text(f"Rejection saved but notification failed: {e}")


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
        await update.message.reply_text(
            job_summary(job) + f"Job ID: #{job['id']} | Status: *{job['status']}*",
            parse_mode="Markdown",
        )


# =============================================================================
# ADMIN: STATS
# =============================================================================

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Quick stats for you as the admin. Only accessible by your Telegram ID."""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("This command is for admins only.")
        return

    stats = db.get_stats()
    await update.message.reply_text(
        "📊 *Platform Stats*\n\n"
        f"👩‍🏫 Total tutors: {stats['tutors']}\n"
        f"📢 Open jobs: {stats['open_jobs']}\n"
        f"📋 Total jobs: {stats['total_jobs']}\n"
        f"💰 Pending payments: {stats['pending_payments']}\n"
        f"✅ Approved payments: {stats['approved_payments']}\n"
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

    # Tutor registration conversation
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

    # Job posting conversation
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

    # Payment conversation — triggered by the "Express Interest" button
    payment_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(express_interest, pattern=r"^interest_\d+$"),
        ],
        states={
            PAYMENT_AWAIT_SCREENSHOT: [
                MessageHandler(filters.PHOTO, receive_payment_screenshot),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_non_photo_in_payment),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(tutor_conv)
    app.add_handler(job_conv)
    app.add_handler(payment_conv)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("browse", browse_jobs))
    app.add_handler(CommandHandler("myjobs", my_jobs))
    app.add_handler(CommandHandler("stats", admin_stats))
    app.add_handler(CallbackQueryHandler(browse_jobs, pattern="^browse_jobs$"))
    app.add_handler(CallbackQueryHandler(how_it_works_cb, pattern="^how_it_works$"))
    app.add_handler(CallbackQueryHandler(approve_payment, pattern=r"^approve_\d+$"))
    app.add_handler(CallbackQueryHandler(reject_payment, pattern=r"^reject_\d+$"))

    logger.info("Bot is running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
