from pyrogram import Client
from pyrogram.types import Message

app = Client(
    "ludo_bot",
    api_id=18274091,   
    api_hash="97afe4ab12cb99dab4bed25f768f5bbc",
    bot_token="5664706056:AAGweTBRqnaS1oQVEWkgxXl1WL9wUO_zuiA"
)

ALLOWED_GROUP = -1002504305026

@app.on_edited_message()
async def edited_message_handler(client: Client, message: Message):
    if message.chat.id != ALLOWED_GROUP:
        return  

    if message.text and "Full" in message.text:
        print("✏️ Edited Table Found in Group", message.chat.id)
        print("📝 Message Text:", message.text)

        # Detect winner if ✅ is present
        if "✅" in message.text:
            for line in message.text.split("\n"):
                if "✅" in line:
                    winner = line.replace("✅", "").strip()
                    print("🏆 Winner:", winner)

app.run()
