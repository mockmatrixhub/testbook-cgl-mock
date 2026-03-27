import re
import json
import io
import html
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
    CallbackQueryHandler
)

# ================= CONFIG =================
TOKEN = "8244382896:AAHRnS5akHfPzDK0TNaZlaYHhJXuyexacUM"

# ================= SESSION =================
user_sessions = {}

def reset_session(uid):
    user_sessions[uid] = {
        "step": "TITLE",
        "quiz_title": None,
        "quiz_id": None,
        "section_type": None,
        "manual_sections": None,
        "timer_min": 60
    }

# ================= HTML ESCAPE =================
def esc(txt):
    if not txt: return ""
    return (
        txt.replace("&", "&amp;")
           .replace("<", "&lt;")
           .replace(">", "&gt;")
           .replace("&lt;br&gt;", "<br>")
    )

def parse_html_questions(html_content):
    match = re.search(r'const\s+questions\s*=\s*(\[.*?\]);', html_content, re.DOTALL)
    if not match:
        raise ValueError("Could not find 'const questions' array in the HTML file.")
    return json.loads(match.group(1))

# ================= COMMANDS =================
async def quiz_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reset_session(update.effective_user.id)
    keyboard = [
        [InlineKeyboardButton("Default CGL (100Q)", callback_data="def_cgl")],
        [InlineKeyboardButton("Give Manually", callback_data="sec_manual")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("🚀 Starting JSON generation from HTML.\n\nSelect Exam Type:", reply_markup=reply_markup)

# ================= CALLBACK HANDLER =================
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    session = user_sessions.get(uid)
    if not session: return

    await query.answer()

    if query.data == "def_cgl":
        session["section_type"] = "default"
        session["manual_sections"] = (
            "1. REASONING(1-25)-2-0.5\n"
            "2. GK(26-50)-2-0.5\n"
            "3. MATH(51-75)-2-0.5\n"
            "4. ENGLISH(76-100)-2-0.5"
        )
        session["timer_min"] = 60
        session["step"] = "TITLE"
        await query.edit_message_text("✅ Default CGL Selected.\n\nPlease send the **Quiz Title**.")

    elif query.data == "sec_manual":
        session["section_type"] = "manual"
        session["step"] = "MANUAL_SEC_INPUT"
        await query.edit_message_text("Please provide sections manually:\nFormat: SECTION NAME(START-END)-POS-NEG\n\nExample:\n1. GK(1-50)-2-0.5")

# ================= TEXT & FILE HANDLER =================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    session = user_sessions.get(uid)
    if not session: return

    if session["step"] == "MANUAL_SEC_INPUT":
        session["manual_sections"] = update.message.text.strip()
        session["step"] = "TITLE"
        await update.message.reply_text("✅ Sections Saved. Please send the **Quiz Title**.")
        return

    if session["step"] == "TITLE":
        session["quiz_title"] = update.message.text.strip()
        session["step"] = "ID"
        await update.message.reply_text("✅ Title Saved. Please send the **Quiz ID**.")
        return

    if session["step"] == "ID":
        session["quiz_id"] = update.message.text.strip()
        session["step"] = "FILE"
        await update.message.reply_text("✅ ID Saved. Please upload the **HTML File**.")
        return

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    session = user_sessions.get(uid)
    if not session or session["step"] != "FILE": return

    doc = update.message.document
    if not doc.file_name.endswith(".html"):
        await update.message.reply_text("❌ Please upload a valid .html file.")
        return

    file = await context.bot.get_file(doc.file_id)
    content = await file.download_as_bytearray()
    html_text = content.decode("utf-8")

    try:
        raw_questions = parse_html_questions(html_text)
        
        # Structure the Output exactly like the provided JSON file
        sections_dict = {}
        
        sec_lines = session["manual_sections"].splitlines()
        sec_map = []
        for line in sec_lines:
            # Matches: 1. NAME(1-25)-2-0.5
            m = re.search(r'(?:[\d\.]+\s*)?(.*?)\((\d+)-(\d+)\)-([\d\.]+)-([\d\.]+)', line)
            if m:
                sec_name = m.group(1).strip()
                sec_map.append({
                    "name": sec_name,
                    "start": int(m.group(2)),
                    "end": int(m.group(3)),
                    "pos": m.group(4),
                    "neg": m.group(5)
                })
                sections_dict[sec_name] = []

        for i, q in enumerate(raw_questions):
            q_num = i + 1
            current_sec_name = "MISC"
            pos, neg = "2", "0.5"
            
            for s in sec_map:
                if s["start"] <= q_num <= s["end"]:
                    current_sec_name = s["name"]
                    pos, neg = s["pos"], s["neg"]
                    break

            if current_sec_name not in sections_dict:
                sections_dict[current_sec_name] = []

            item = {
                "answer": str(q.get("correct", 1)),
                "correct_score": pos,
                "id": str(50000 + q_num),
                "negative_score": neg,
                "option_1": {"en": esc(q["opts_en"][0]), "hi": esc(q["opts_hi"][0]) if q.get("opts_hi") else ""},
                "option_2": {"en": esc(q["opts_en"][1]), "hi": esc(q["opts_hi"][1]) if q.get("opts_hi") else ""},
                "option_3": {"en": esc(q["opts_en"][2]), "hi": esc(q["opts_hi"][2]) if q.get("opts_hi") else ""},
                "option_4": {"en": esc(q["opts_en"][3]), "hi": esc(q["opts_hi"][3]) if q.get("opts_hi") else ""},
                "option_5": "",
                "question": {"en": esc(q["q_en"]), "hi": esc(q.get("q_hi", ""))},
                "quiz_id": session["quiz_id"],
                "solution_text": {"en": esc(q.get("sol_en", "")), "hi": esc(q.get("sol_hi", ""))}
            }
            sections_dict[current_sec_name].append(item)

        # FINAL OUTPUT STRUCTURE (As per CHSL-2025.json)
        output_data = {
            "meta": {
                "title": session["quiz_title"],
                "id": session["quiz_id"],
                "total_questions": len(raw_questions),
                "correct_score": "2", # Master setting
                "negative_score": "0.5",
                "timer_minutes": str(session["timer_min"]),
                "timer_seconds": session["timer_min"] * 60
            },
            "sections": sections_dict
        }

        json_str = json.dumps(output_data, indent=4, ensure_ascii=False)
        file_name = f"{session['quiz_title'].replace(' ', '_')}.json"
        
        caption = (
            f"<b>✅ Quiz JSON Generated Successfully!</b>\n\n"
            f"<b>📌 Title:</b> {session['quiz_title']}\n"
            f"<b>🔑 ID:</b> <code>{session['quiz_id']}</code>\n"
            f"<b>⏱ Timer:</b> {session['timer_min']} Min\n"
            f"<b>📝 Total Questions:</b> {len(raw_questions)}\n\n"
            f"<b>📂 Sections:</b>\n{session['manual_sections']}"
        )

        await update.message.reply_document(
            document=io.BytesIO(json_str.encode("utf-8")),
            filename=file_name,
            caption=caption,
            parse_mode="HTML"
        )

        website_code = f'<div class="quiz" data-type="paid" data-id="{session["quiz_id"]}" data-title="{session["quiz_title"]}"></div>'
        await update.message.reply_text(
            f"📋 <b>Website Code Snippet:</b>\n\n<pre><code class='language-html'>{html.escape(website_code)}</code></pre>",
            parse_mode="HTML"
        )
        
        reset_session(uid)

    except Exception as e:
        await update.message.reply_text(f"❌ Error processing file: {str(e)}")

def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("quiz", quiz_cmd))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.run_polling()

if __name__ == "__main__":
    main()
