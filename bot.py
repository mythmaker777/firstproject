"""
Tuition Matching Telegram Bot - Singapore
==========================================
Main entry point. Handles all conversation flows for tutors and parents.

Why python-telegram-bot v20+?
  - Fully async (asyncio-based), handles many concurrent users without threading issues
  - ConversationHandler makes multi-step forms clean and stateful
  - Best-maintained Python Telegram library with good docs
"""

import logging
import os
from dotenv import load_dotenv
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

load_dotenv()

# --- Logging ---
# Always set up logging early so you can debug issues in production
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# --- Database ---
db = Database("tuition.db")

# =============================================================================
# CONVERSATION STATES
# Using integers keeps things fast. Group them by flow for readability.
# =============================================================================

# Tutor registration states
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

# Parent job posting states
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

# =============================================================================
# CONSTANTS — Singapore-specific tuition data
# =============================================================================

SUBJECTS = [
    "English", "Mathematics", "Additional Mathematics",
    "Physics", "Chemistry", "Biology", "Combined Science",
    "History", "Geography", "Social Studies",
    "Chinese", "Malay", "Tamil",
    "Economics", "Literature", "Accounting",
    "GP (General Paper)", "Mother Tongue Literature",
]

LEVELS = [
    "Primary 1", "Primary 2", "Primary 3", "Primary 4",
    "Primary 5", "Primary 6 / PSLE",
    "Secondary 1", "Secondary 2", "Secondary 3", "Secondary 4 / O-Levels",
    "JC1", "JC2 / A-Levels",
    "IB / IGCSE", "Poly / ITE",
]

# Singapore postal districts grouped by area — crucial for tuition matching
# Parents strongly prefer tutors who live nearby or can travel easily
ZONES = [
    "Central (D1-D8, D9-D11)",
    "North (Woodlands, Yishun, Sembawang)",
    "North-East (Hougang, Sengkang, Punggol, AMK)",
    "East (Tampines, Pasir Ris, Bedok, Changi)",
    "West (Jurong, Clementi, Buona Vista)",
    "South (Queenstown, Tiong Bahru, Harbourfront)",
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
# HELPER FUNCTIONS
# =============================================================================

def build_keyboard(options: list, cols: int = 2, add_done: bool = False) -> ReplyKeyboardMarkup:
    """
    Builds a reply keyboard from a list of options.
    We use ReplyKeyboard (not InlineKeyboard) for multi-select flows because
    it keeps the chat clean — the keyboard disappears after submission.
    `cols` controls how many buttons per row.
    """
    rows = [options[i:i + cols] for i in range(0, len(options), cols)]
    if add_done:
        rows.append(["✅ Done"])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True, one_time_keyboard=False)


def format_tutor_profile(profile: dict) -> str:
    return (
        f"👤 *{profile['name']}*\n"
        f"🎓 Type: {profile['tutor_type']}\n"
        f"📚 Subjects: {profile['subjects']}\n"
        f"🏫 Levels: {profile['levels']}\n"
        f"💰 Rate: ${profile['rate_min']}–${profile['rate_max']}/hr\n"
        f"📍 Zones: {profile['zones']}\n"
        f"📋 Qualifications: {profile['qualifications']}\n"
    )


def format_job_post(job: dict) -> str:
    return (
        f"📢 *New Tuition Job*\n\n"
        f"📚 Subject: {job['subject']}\n"
        f"🏫 Level: {job['level']}\n"
        f"📍 Zone: {job['zone']}\n"
        f"🗓 Schedule: {job['schedule']}\n"
        f"💰 Budget: ${job['budget']}/hr\n"
        f"👩‍🏫 Preferred Tutor: {job['tutor_type_pref']}\n"
        f"📱 Contact: {job['contact']}\n"
    )


# =============================================================================
# COMMON HANDLERS
# =============================================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Entry point. Shows the main menu."""
    user = update.effective_user
    keyboard = [
        [InlineKeyboardButton("👩‍🏫 Register as Tutor", callback_data="register_tutor")],
        [InlineKeyboardButton("👪 Post a Tuition Job", callback_data="post_job")],
        [InlineKeyboardButton("📋 Browse Job Listings", callback_data="browse_jobs")],
        [InlineKeyboardButton("ℹ️ How It Works", callback_data="how_it_works")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        f"Hello {user.first_name}! 👋\n\n"
        "Welcome to *SG Tuition Match* — the fastest way to find or become a tutor in Singapore.\n\n"
        "What would you like to do?",
        reply_markup=reply_markup,
        parse_mode="Markdown",
    )


async def how_it_works(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await query.message.reply_text(
        "ℹ️ *How SG Tuition Match Works*\n\n"
        "*For Parents/Students:*\n"
        "1. Post your tuition job (subject, level, budget, zone)\n"
        "2. Interested tutors will contact you directly\n"
        "3. Trial lesson is between you and the tutor\n\n"
        "*For Tutors:*\n"
        "1. Register your profile\n"
        "2. Get notified of matching jobs instantly\n"
        "3. Express interest — the parent's contact is shared\n"
        "4. A small referral fee applies upon successful match\n\n"
        "*Completely free for parents/students.* 🎉",
        parse_mode="Markdown",
    )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Universal cancel — exits any conversation."""
    context.user_data.clear()
    await update.message.reply_text(
        "❌ Cancelled. Type /start to begin again.",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ConversationHandler.END


# =============================================================================
# TUTOR REGISTRATION FLOW
# =============================================================================

async def tutor_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Triggered by callback or /register command."""
    if update.callback_query:
        await update.callback_query.answer()
        msg = update.callback_query.message
    else:
        msg = update.message

    # Initialise fresh data store for this conversation
    context.user_data["tutor"] = {"subjects": [], "levels": [], "zones": []}

    await msg.reply_text(
        "Great! Let's set up your tutor profile. 📝\n\n"
        "You can type /cancel at any time to stop.\n\n"
        "First, what's your *full name*?",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove(),
    )
    return TUTOR_NAME


async def tutor_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["tutor"]["name"] = update.message.text.strip()
    await update.message.reply_text(
        "What type of tutor are you?",
        reply_markup=build_keyboard(TUTOR_TYPES, cols=1),
    )
    return TUTOR_TYPE


async def tutor_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.text not in TUTOR_TYPES:
        await update.message.reply_text("Please select one of the options below.")
        return TUTOR_TYPE
    context.user_data["tutor"]["tutor_type"] = update.message.text

    await update.message.reply_text(
        "Which subjects can you teach?\n"
        "Select all that apply, then tap *✅ Done*.",
        parse_mode="Markdown",
        reply_markup=build_keyboard(SUBJECTS, cols=2, add_done=True),
    )
    return TUTOR_SUBJECTS


async def tutor_subjects(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text
    if text == "✅ Done":
        if not context.user_data["tutor"]["subjects"]:
            await update.message.reply_text("Please select at least one subject.")
            return TUTOR_SUBJECTS
        await update.message.reply_text(
            "Which levels do you teach?\n"
            "Select all that apply, then tap *✅ Done*.",
            parse_mode="Markdown",
            reply_markup=build_keyboard(LEVELS, cols=2, add_done=True),
        )
        return TUTOR_LEVELS
    if text in SUBJECTS:
        subs = context.user_data["tutor"]["subjects"]
        if text not in subs:
            subs.append(text)
        await update.message.reply_text(f"✓ Added: {text}. Select more or tap Done.")
    return TUTOR_SUBJECTS


async def tutor_levels(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text
    if text == "✅ Done":
        if not context.user_data["tutor"]["levels"]:
            await update.message.reply_text("Please select at least one level.")
            return TUTOR_LEVELS
        await update.message.reply_text(
            "What's your *minimum hourly rate* (SGD)?\n"
            "e.g. type `25`",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardRemove(),
        )
        return TUTOR_RATE_MIN
    if text in LEVELS:
        lvls = context.user_data["tutor"]["levels"]
        if text not in lvls:
            lvls.append(text)
        await update.message.reply_text(f"✓ Added: {text}. Select more or tap Done.")
    return TUTOR_LEVELS


async def tutor_rate_min(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        rate = int(update.message.text.strip().replace("$", ""))
        if rate < 10 or rate > 300:
            raise ValueError
        context.user_data["tutor"]["rate_min"] = rate
        await update.message.reply_text(
            "What's your *maximum hourly rate* (SGD)?\n"
            "e.g. type `60`",
            parse_mode="Markdown",
        )
        return TUTOR_RATE_MAX
    except ValueError:
        await update.message.reply_text("Please enter a valid rate between $10 and $300.")
        return TUTOR_RATE_MIN


async def tutor_rate_max(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        rate = int(update.message.text.strip().replace("$", ""))
        if rate < context.user_data["tutor"]["rate_min"]:
            await update.message.reply_text("Max rate must be ≥ your minimum rate.")
            return TUTOR_RATE_MAX
        context.user_data["tutor"]["rate_max"] = rate
        await update.message.reply_text(
            "Which zones are you available to travel to?\n"
            "Select all that apply, then tap *✅ Done*.",
            parse_mode="Markdown",
            reply_markup=build_keyboard(ZONES, cols=1, add_done=True),
        )
        return TUTOR_ZONES
    except ValueError:
        await update.message.reply_text("Please enter a valid number.")
        return TUTOR_RATE_MAX


async def tutor_zones(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text
    if text == "✅ Done":
        if not context.user_data["tutor"]["zones"]:
            await update.message.reply_text("Please select at least one zone.")
            return TUTOR_ZONES
        await update.message.reply_text(
            "Briefly describe your qualifications.\n"
            "e.g. `NUS Computer Science Year 3, 8 years tutoring experience, top 10% at O-Levels`",
            reply_markup=ReplyKeyboardRemove(),
        )
        return TUTOR_QUALIFICATIONS
    if text in ZONES:
        zones = context.user_data["tutor"]["zones"]
        if text not in zones:
            zones.append(text)
        await update.message.reply_text(f"✓ Added: {text}. Select more or tap Done.")
    return TUTOR_ZONES


async def tutor_qualifications(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["tutor"]["qualifications"] = update.message.text.strip()
    await update.message.reply_text(
        "What's your *contact number* (shared only with interested parents)?\n"
        "e.g. `9123 4567`",
        parse_mode="Markdown",
    )
    return TUTOR_PHONE


async def tutor_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    phone = update.message.text.strip().replace(" ", "")
    # Basic SG phone validation: 8 digits starting with 8 or 9
    if not (phone.isdigit() and len(phone) == 8 and phone[0] in ("8", "9")):
        await update.message.reply_text(
            "Please enter a valid Singapore mobile number (8 digits starting with 8 or 9)."
        )
        return TUTOR_PHONE
    context.user_data["tutor"]["phone"] = phone

    tutor = context.user_data["tutor"]
    summary = (
        "Please confirm your profile:\n\n"
        f"{format_tutor_profile({**tutor, 'subjects': ', '.join(tutor['subjects']), 'levels': ', '.join(tutor['levels']), 'zones': ', '.join(tutor['zones'])})}"
        f"📱 Phone: {tutor['phone']}\n\n"
        "Is everything correct?"
    )
    await update.message.reply_text(
        summary,
        parse_mode="Markdown",
        reply_markup=build_keyboard(["✅ Confirm", "❌ Start Over"], cols=2),
    )
    return TUTOR_CONFIRM


async def tutor_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.text == "✅ Confirm":
        tutor = context.user_data["tutor"]
        telegram_id = update.effective_user.id
        db.save_tutor(
            telegram_id=telegram_id,
            name=tutor["name"],
            tutor_type=tutor["tutor_type"],
            subjects=", ".join(tutor["subjects"]),
            levels=", ".join(tutor["levels"]),
            rate_min=tutor["rate_min"],
            rate_max=tutor["rate_max"],
            zones=", ".join(tutor["zones"]),
            qualifications=tutor["qualifications"],
            phone=tutor["phone"],
        )
        await update.message.reply_text(
            "🎉 Profile saved! You'll be notified when a matching job is posted.\n\n"
            "Use /editprofile to update your details anytime.\n"
            "Use /myjobs to see jobs you've expressed interest in.",
            reply_markup=ReplyKeyboardRemove(),
        )
        context.user_data.clear()
        return ConversationHandler.END
    else:
        # Start over
        context.user_data["tutor"] = {"subjects": [], "levels": [], "zones": []}
        await update.message.reply_text(
            "OK, let's start again. What's your full name?",
            reply_markup=ReplyKeyboardRemove(),
        )
        return TUTOR_NAME


# =============================================================================
# PARENT JOB POSTING FLOW
# =============================================================================

async def job_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.callback_query:
        await update.callback_query.answer()
        msg = update.callback_query.message
    else:
        msg = update.message

    context.user_data["job"] = {}
    await msg.reply_text(
        "Let's post your tuition job! 📢\n\n"
        "Type /cancel at any time to stop.\n\n"
        "What *subject* do you need tutoring for?",
        parse_mode="Markdown",
        reply_markup=build_keyboard(SUBJECTS, cols=2),
    )
    return JOB_SUBJECT


async def job_subject(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.text not in SUBJECTS:
        await update.message.reply_text("Please select a subject from the list.")
        return JOB_SUBJECT
    context.user_data["job"]["subject"] = update.message.text
    await update.message.reply_text(
        "What level?",
        reply_markup=build_keyboard(LEVELS, cols=2),
    )
    return JOB_LEVEL


async def job_level(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.text not in LEVELS:
        await update.message.reply_text("Please select a level from the list.")
        return JOB_LEVEL
    context.user_data["job"]["level"] = update.message.text
    await update.message.reply_text(
        "Which zone are you located in?",
        reply_markup=build_keyboard(ZONES, cols=1),
    )
    return JOB_ZONE


async def job_zone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.text not in ZONES:
        await update.message.reply_text("Please select your zone.")
        return JOB_ZONE
    context.user_data["job"]["zone"] = update.message.text
    await update.message.reply_text(
        "When are sessions needed? Describe your preferred schedule.\n"
        "e.g. `Weekday evenings, 2x per week` or `Saturday mornings`",
        reply_markup=ReplyKeyboardRemove(),
    )
    return JOB_SCHEDULE


async def job_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["job"]["schedule"] = update.message.text.strip()
    await update.message.reply_text(
        "What's your *budget per hour* (SGD)?\n"
        "e.g. type `40`",
        parse_mode="Markdown",
    )
    return JOB_BUDGET


async def job_budget(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        budget = int(update.message.text.strip().replace("$", ""))
        if budget < 10:
            raise ValueError
        context.user_data["job"]["budget"] = budget
        await update.message.reply_text(
            "Any preference on tutor type?",
            reply_markup=build_keyboard(["No Preference"] + TUTOR_TYPES, cols=1),
        )
        return JOB_TUTOR_TYPE_PREF
    except ValueError:
        await update.message.reply_text("Please enter a valid budget (e.g. 40).")
        return JOB_BUDGET


async def job_tutor_type_pref(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    valid = ["No Preference"] + TUTOR_TYPES
    if update.message.text not in valid:
        await update.message.reply_text("Please select from the options.")
        return JOB_TUTOR_TYPE_PREF
    context.user_data["job"]["tutor_type_pref"] = update.message.text
    await update.message.reply_text(
        "What's the best way for tutors to reach you?\n"
        "e.g. `Telegram @username` or `WhatsApp 9123 4567`",
        reply_markup=ReplyKeyboardRemove(),
    )
    return JOB_CONTACT


async def job_contact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["job"]["contact"] = update.message.text.strip()
    job = context.user_data["job"]

    summary = "Please confirm your job posting:\n\n" + format_job_post(job)
    await update.message.reply_text(
        summary,
        parse_mode="Markdown",
        reply_markup=build_keyboard(["✅ Post Job", "❌ Start Over"], cols=2),
    )
    return JOB_CONFIRM


async def job_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE, application) -> int:
    """
    Why we pass `application` here: we need to notify matching tutors.
    We do this in-process for simplicity. In a larger system you'd use a job queue.
    """
    if update.message.text == "✅ Post Job":
        job = context.user_data["job"]
        poster_id = update.effective_user.id

        job_id = db.save_job(
            telegram_id=poster_id,
            subject=job["subject"],
            level=job["level"],
            zone=job["zone"],
            schedule=job["schedule"],
            budget=job["budget"],
            tutor_type_pref=job["tutor_type_pref"],
            contact=job["contact"],
        )

        await update.message.reply_text(
            f"✅ Job posted! (Job ID: #{job_id})\n\n"
            "Matching tutors will be notified. Expect responses within a few hours.\n\n"
            "Use /myjobs to manage your postings.",
            reply_markup=ReplyKeyboardRemove(),
        )

        # --- Notify matching tutors ---
        matching_tutors = db.find_matching_tutors(
            subject=job["subject"],
            level=job["level"],
            zone=job["zone"],
            budget=job["budget"],
        )

        notification = (
            "🔔 *New Matching Job Alert!*\n\n"
            + format_job_post(job)
            + f"\nJob ID: #{job_id}\n"
            "Reply with /interested_{job_id} to express interest."
        )

        notified = 0
        for tutor in matching_tutors:
            try:
                await application.bot.send_message(
                    chat_id=tutor["telegram_id"],
                    text=notification,
                    parse_mode="Markdown",
                )
                notified += 1
            except Exception as e:
                logger.warning(f"Could not notify tutor {tutor['telegram_id']}: {e}")

        logger.info(f"Job #{job_id}: notified {notified} tutors.")
        context.user_data.clear()
        return ConversationHandler.END
    else:
        context.user_data["job"] = {}
        await update.message.reply_text(
            "OK, let's start again. What subject do you need tutoring for?",
            reply_markup=build_keyboard(SUBJECTS, cols=2),
        )
        return JOB_SUBJECT


# =============================================================================
# BROWSE + INTEREST HANDLERS
# =============================================================================

async def browse_jobs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Shows open job listings to tutors."""
    if update.callback_query:
        await update.callback_query.answer()
        msg = update.callback_query.message
    else:
        msg = update.message

    jobs = db.get_open_jobs(limit=10)
    if not jobs:
        await msg.reply_text("No open jobs at the moment. Check back soon! 🙏")
        return

    for job in jobs:
        text = format_job_post(job) + f"\nJob ID: #{job['id']}"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "✋ Express Interest",
                callback_data=f"interest_{job['id']}"
            )]
        ])
        await msg.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)


async def express_interest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Called when a tutor taps 'Express Interest' on a job.
    Retrieves the tutor's stored phone from DB and sends it to the parent.
    """
    query = update.callback_query
    await query.answer()

    job_id = int(query.data.split("_")[1])
    tutor_tg_id = update.effective_user.id

    tutor = db.get_tutor_by_telegram_id(tutor_tg_id)
    if not tutor:
        await query.message.reply_text(
            "You need to register as a tutor first. Use /register."
        )
        return

    job = db.get_job_by_id(job_id)
    if not job:
        await query.message.reply_text("This job is no longer available.")
        return

    # Record the interest
    already = db.record_interest(tutor_id=tutor["id"], job_id=job_id)
    if already:
        await query.message.reply_text("You've already expressed interest in this job.")
        return

    # Notify the parent
    parent_notification = (
        f"👋 A tutor is interested in your job #{job_id}!\n\n"
        f"{format_tutor_profile(tutor)}"
        f"📱 Contact: {tutor['phone']}\n\n"
        "Reach out to them directly to arrange a trial lesson."
    )
    try:
        from telegram.ext import Application
        await context.bot.send_message(
            chat_id=job["telegram_id"],
            text=parent_notification,
            parse_mode="Markdown",
        )
        await query.message.reply_text(
            f"✅ Your interest has been sent! The parent's contact: *{job['contact']}*",
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.error(f"Failed to notify parent: {e}")
        await query.message.reply_text(
            "Something went wrong. Please try again later."
        )


async def my_jobs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Shows a user's own job postings (for parents) or interested jobs (for tutors)."""
    tg_id = update.effective_user.id
    jobs = db.get_jobs_by_poster(tg_id)
    if jobs:
        await update.message.reply_text("📋 *Your Job Postings:*", parse_mode="Markdown")
        for job in jobs:
            await update.message.reply_text(
                format_job_post(job) + f"Job ID: #{job['id']} | Status: {job['status']}",
                parse_mode="Markdown",
            )
    else:
        await update.message.reply_text("You haven't posted any jobs yet. Use /postjob to get started.")


# =============================================================================
# BOT SETUP
# =============================================================================

def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN not set in environment.")

    app = Application.builder().token(token).build()

    # --- Tutor registration conversation ---
    tutor_conv = ConversationHandler(
        entry_points=[
            CommandHandler("register", tutor_start),
            CallbackQueryHandler(tutor_start, pattern="^register_tutor$"),
        ],
        states={
            TUTOR_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, tutor_name)],
            TUTOR_TYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, tutor_type)],
            TUTOR_SUBJECTS: [MessageHandler(filters.TEXT & ~filters.COMMAND, tutor_subjects)],
            TUTOR_LEVELS: [MessageHandler(filters.TEXT & ~filters.COMMAND, tutor_levels)],
            TUTOR_RATE_MIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, tutor_rate_min)],
            TUTOR_RATE_MAX: [MessageHandler(filters.TEXT & ~filters.COMMAND, tutor_rate_max)],
            TUTOR_ZONES: [MessageHandler(filters.TEXT & ~filters.COMMAND, tutor_zones)],
            TUTOR_QUALIFICATIONS: [MessageHandler(filters.TEXT & ~filters.COMMAND, tutor_qualifications)],
            TUTOR_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, tutor_phone)],
            TUTOR_CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, tutor_confirm)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # --- Job posting conversation ---
    # We use a closure to pass `app` into job_confirm so it can notify tutors
    async def job_confirm_wrapper(update, context):
        return await job_confirm(update, context, app)

    job_conv = ConversationHandler(
        entry_points=[
            CommandHandler("postjob", job_start),
            CallbackQueryHandler(job_start, pattern="^post_job$"),
        ],
        states={
            JOB_SUBJECT: [MessageHandler(filters.TEXT & ~filters.COMMAND, job_subject)],
            JOB_LEVEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, job_level)],
            JOB_ZONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, job_zone)],
            JOB_SCHEDULE: [MessageHandler(filters.TEXT & ~filters.COMMAND, job_schedule)],
            JOB_BUDGET: [MessageHandler(filters.TEXT & ~filters.COMMAND, job_budget)],
            JOB_TUTOR_TYPE_PREF: [MessageHandler(filters.TEXT & ~filters.COMMAND, job_tutor_type_pref)],
            JOB_CONTACT: [MessageHandler(filters.TEXT & ~filters.COMMAND, job_contact)],
            JOB_CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, job_confirm_wrapper)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # Register handlers (order matters — conversations first)
    app.add_handler(tutor_conv)
    app.add_handler(job_conv)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("browse", browse_jobs))
    app.add_handler(CommandHandler("myjobs", my_jobs))
    app.add_handler(CallbackQueryHandler(browse_jobs, pattern="^browse_jobs$"))
    app.add_handler(CallbackQueryHandler(how_it_works, pattern="^how_it_works$"))
    app.add_handler(CallbackQueryHandler(express_interest, pattern=r"^interest_\d+$"))

    # --- Run ---
    # Polling is fine for development. Switch to webhook for production (see README).
    logger.info("Bot starting in polling mode...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
