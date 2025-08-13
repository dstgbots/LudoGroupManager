# 🎮 Ludo Group Manager Bot

A comprehensive Telegram bot for managing Ludo group games, player balances, and automated payment tracking.

## Features

### 🔹 User Account Management
- Automatic user registration on first interaction
- Personal balance tracking with unique accounts per Telegram user ID
- `/balance` command to check current balance
- Transaction history tracking

### 🔹 Payment Processing
- Automatic detection of admin payment confirmations
- Pattern matching for messages like "3000 received @username"
- Instant balance updates and user notifications
- Transaction logging for audit trail

### 🔹 Game Management
- Automatic game table detection and processing
- Real-time balance deduction when games start
- Game duration tracking (max 1 hour)
- Support for multiple simultaneous games

### 🔹 Game Results & Payouts
- Winner detection via ✅ emoji reactions
- Automatic payout calculation with custom commission rates
- Balance distribution to winners
- Loser notifications with motivational messages

### 🔹 Admin Controls & Security
- **Admin-only group operations** - Only configured admins can use commands in group
- **Auto-delete responses** - Bot messages in group auto-delete after 5 seconds
- `/cancel` command to cancel games and refund players
- `/setcommission` to set custom commission rates per user
- `/addbalance` for manual balance adjustments
- Secure access control for all sensitive operations

### 🔹 Smart Notifications
- Game start notifications sent privately to players
- Winner congratulations with game link
- Loser encouragement messages
- Payment confirmation alerts

## Installation & Setup

### Prerequisites
- Python 3.8 or higher
- MongoDB database
- Telegram Bot Token (from @BotFather)

### Step 1: Clone and Install Dependencies
```bash
git clone <repository-url>
cd ludo-group-manager-bot
pip install -r requirements.txt
```

### Step 2: Database Setup
Make sure MongoDB is running on your system:
- **Windows**: Download from [MongoDB Community Server](https://www.mongodb.com/try/download/community)
- **Linux**: `sudo apt install mongodb` or `sudo yum install mongodb`
- **macOS**: `brew install mongodb-community`

### Step 3: Create Telegram Bot
1. Message @BotFather on Telegram
2. Use `/newbot` command
3. Follow instructions to get your bot token
4. Save the token for configuration

### Step 4: Get Group and Admin IDs
1. Add your bot to the Ludo group
2. **Give bot admin permissions** (required for deleting messages)
3. Send a message in the group
4. Visit `https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates`
5. Find your group chat ID (negative number like -1001234567890)
6. Get admin user IDs from the same API response (look for `from.id` values)

### Step 5: Configuration
Create a `.env` file in the project root:
```env
BOT_TOKEN=your_bot_token_here
MONGO_URI=mongodb://localhost:27017/
DATABASE_NAME=ludo_bot
GROUP_ID=-1001234567890
ADMIN_IDS=123456789,987654321
```

### Step 6: Run the Bot
```bash
python bot.py
```

## Usage Guide

### For Players
1. **Start the bot**: Send `/start` to the bot privately
2. **Check balance**: Use `/balance` command
3. **Join games**: Participate when admins post game tables
4. **Receive notifications**: Get updates about games and winnings

### For Admins
1. **Confirm payments**: Send messages like "3000 received @username"
2. **Start games**: Post game tables with player mentions and bet amounts
3. **End games**: React with ✅ emoji next to winner names
4. **Cancel games**: Reply to game table with `/cancel`
5. **Set commissions**: Use `/setcommission @username 5`
6. **Add balance**: Use `/addbalance @username 1000`

## Message Patterns

### Payment Confirmation
```
3000 received @username
5000 reviced @playername
```

### Game Table Format
```
@Sukha888

Sangram

500 f

@rohitman4513

devil

300 f

Singh

devil

200 f
```

### Game Results
```
Singh ✅

devil

300 f

@Sukha888

Ankita ✅✅

500 f

@rohitman4513 ✅

devil

300 f
```

## Commission System

- Each user has a customizable commission rate (default 5%)
- Winners pay commission on their winnings
- Losers pay the full bet amount
- Example: ₹300 bet with 5% commission = ₹285 to winner, ₹300 from loser

## Database Schema

### Users Collection
- `user_id`: Telegram user ID
- `username`: Telegram username
- `balance`: Current account balance
- `commission_rate`: Personal commission percentage
- `created_at`: Account creation timestamp

### Games Collection
- `game_id`: Unique game identifier
- `players`: Array of participating players
- `status`: active/completed/cancelled
- `total_pot`: Total bet amount
- `winners`: Array of winner usernames

### Transactions Collection
- `user_id`: User involved in transaction
- `type`: deposit/bet/win/refund/manual_add
- `amount`: Transaction amount
- `description`: Transaction details
- `timestamp`: When transaction occurred

## Error Handling

The bot includes comprehensive error handling for:
- Insufficient user balance
- Invalid message formats
- Database connection issues
- Telegram API errors
- Missing user accounts
- Invalid admin commands

## Security Features

### Admin-Only Access Control
- **Group commands restricted to admins only**
- Non-admin messages completely ignored in group
- Payment confirmations only from verified admins
- Game management restricted to admin users

### Auto-Delete Responses  
- **All bot responses in group auto-delete after 5 seconds**
- Keeps group chat clean and organized
- Prevents message clutter from bot operations

### Data Protection
- User ID-based authentication
- Transaction logging for audit trails
- Input validation and sanitization
- Rate limiting protection
- Secure balance and commission management

## Support

For issues, feature requests, or questions:
1. Check the logs for error messages
2. Verify your .env configuration
3. Ensure MongoDB is running
4. Check bot permissions in the group

## License

This project is licensed under the MIT License.
