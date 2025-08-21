import logging
import re
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Store active games {chat_id: {message_id: game_data}}
active_games = {}

# Your admin IDs
ADMIN_IDS = [2109516065, 739290618]

# Allowed group IDs
GROUP_IDS = [-1002849354155, -1002504305026]


def parse_table(text: str):
    """Parse table message and extract usernames + bet amount."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    players = []
    bet_amount = None

    for line in lines:
        # detect bet like '500 Full'
        match = re.search(r"(\d+)\s*Full", line, re.IGNORECASE)
        if match:
            bet_amount = int(match.group(1))
        else:
            # possible username
            if line.startswith("@"):
                players.append(line.lstrip("@"))
            else:
                players.append(line)

    return players, bet_amount


async def handle_new_table(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle new game table sent by admin."""
    if update.effective_user.id not in ADMIN_IDS:
        return
    if update.effective_chat.id not in GROUP_IDS:
        return

    message = update.effective_message
    players, bet_amount = parse_table(message.text or "")

    if len(players) == 2 and bet_amount:
        active_games[(message.chat_id, message.message_id)] = {
            "players": players,
            "bet": bet_amount,
        }
        logger.info(f"🎮 New game stored: {players} | Bet: {bet_amount}")
        await message.reply_text(
            f"✅ Game created between {players[0]} and {players[1]} for ₹{bet_amount}"
        )


async def handle_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle edited game table and detect winner."""
    if update.effective_chat.id not in GROUP_IDS:
        return

    message = update.effective_message
    key = (message.chat_id, message.message_id)

    if key not in active_games:
        logger.info("⚠️ Edited message is not a tracked game.")
        return

    players, bet_amount = parse_table(message.text or "")
    winner = None

    for line in (message.text or "").splitlines():
        if "✅" in line:
            winner = re.sub(r"✅", "", line).strip().lstrip("@")
            break

    if not winner:
        logger.warning("❌ No winner found in edited message.")
        return

    game = active_games[key]
    loser = [p for p in game["players"] if p.lower() != winner.lower()]

    logger.info(f"🏆 Winner detected: {winner}")
    await message.reply_text(
        f"🏆 Winner: <b>{winner}</b>\n"
        f"😔 Loser: <b>{', '.join(loser)}</b>\n"
        f"💰 Bet: ₹{game['bet']}",
        parse_mode=ParseMode.HTML
    )

    # Clean up finished game
    del active_games[key]


def main():
    application = ApplicationBuilder().token("5664706056:AAGweTBRqnaS1oQVEWkgxXl1WL9wUO_zuiA").build()

    # New game tables
    application.add_handler(MessageHandler(filters.TEXT & ~filters.UpdateType.EDITED_MESSAGE, handle_new_table))

    # Edited tables (winner detection)
    application.add_handler(MessageHandler(filters.UpdateType.EDITED_MESSAGE, handle_edit))

    logger.info("🤖 Bot started...")
    application.run_polling()


if __name__ == "__main__":
    main()
