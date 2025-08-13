# 🔐 Admin-Only Features & Auto-Delete

## Overview
The Ludo Group Manager Bot now implements strict admin-only controls for group operations and auto-delete functionality for bot responses.

## 🚫 Admin-Only Restrictions

### Group Chat Behavior
- **Only admins can use commands** in the group chat
- **Only admins can send game-related messages** that the bot will process
- Non-admin messages are completely ignored by the bot

### Affected Commands (Group Only)
- `/start` - Only admins can initialize accounts in group
- `/balance` - Only admins can check balance in group  
- `/help` - Non-admins get limited help message
- `/cancel` - Admin-only game cancellation
- `/setcommission` - Admin-only commission management
- `/addbalance` - Admin-only balance management

### Game Management (Admin-Only)
- **Payment Confirmations**: Only admin messages like "3000 received @username"
- **Game Tables**: Only admins can post game tables to start games
- **Game Results**: Only admins can declare winners with ✅ emoji

## ⏰ Auto-Delete Feature

### Automatic Message Deletion
- **All bot responses in group chat are auto-deleted after 5 seconds**
- Keeps the group chat clean and focused
- Prevents clutter from bot confirmations

### Messages That Auto-Delete
- Payment confirmation messages
- Game start notifications  
- Game completion announcements
- Error messages and warnings
- Admin command responses
- Balance updates

### Private Chat Behavior
- **No auto-deletion in private chats**
- Users can view their balance and history normally
- Full conversation history preserved

## 🔧 Implementation Details

### Admin Check Logic
```python
# Group messages only processed if from admin
if update.effective_chat.id == int(self.group_id):
    if update.effective_user.id not in self.admin_ids:
        return  # Ignore non-admin messages
```

### Auto-Delete Mechanism
```python
async def send_auto_delete_message(self, context, chat_id, text, delete_after=5):
    message = await context.bot.send_message(chat_id=chat_id, text=text)
    
    # Schedule deletion after 5 seconds
    async def delete_message():
        await asyncio.sleep(delete_after)
        await context.bot.delete_message(chat_id=chat_id, message_id=message.message_id)
    
    asyncio.create_task(delete_message())
```

## 📋 Admin Setup Checklist

### Required Configuration
1. **Set admin user IDs** in `.env` file:
   ```env
   ADMIN_IDS=123456789,987654321
   ```

2. **Get admin Telegram IDs**:
   - Send message in group
   - Visit: `https://api.telegram.org/bot<BOT_TOKEN>/getUpdates`
   - Find `from.id` values for admin users

### Bot Permissions Required
- **Delete messages** - For auto-delete functionality
- **Send messages** - For bot responses
- **Read messages** - For processing commands

## 🎯 User Experience

### For Admins
- Full access to all bot features in group
- Commands work normally with auto-delete
- Can manage games, payments, and users

### For Regular Users
- **Private chat**: Full bot functionality available
- **Group chat**: Commands blocked with helpful message
- Encouraged to use private chat for account management

### Group Benefits
- Clean chat without bot clutter
- Admin-controlled game management
- Secure payment and balance operations

## 🚨 Important Notes

### Security Features
- Prevents unauthorized game manipulation
- Protects user balance information
- Ensures only trusted admins manage money

### Error Handling
- Graceful handling of non-admin attempts
- Clear error messages directing to private chat
- No bot crashes from unauthorized access

### Auto-Delete Timing
- **5 seconds** is the default delete time
- Can be modified in the `send_auto_delete_message` function
- Provides enough time to read but keeps chat clean

## 📖 Usage Examples

### ✅ Valid Admin Actions
```
Admin: 3000 received @player1
Bot: ✅ Balance updated! (deletes after 5s)

Admin: /setcommission @player1 7
Bot: ✅ Commission rate set to 7% (deletes after 5s)
```

### ❌ Blocked Non-Admin Actions  
```
User: 5000 received @someone
Bot: (no response - message ignored)

User: /balance
Bot: ❌ Only admins can use commands in group (deletes after 5s)
```

This implementation ensures your Ludo group remains secure, organized, and admin-controlled while providing full functionality to users in private chats.
