# Features Package

This folder contains all the feature modules for the Ludo Bot Manager, organized by functionality for better maintainability and code organization.

## Module Structure

### 1. `database.py` - DatabaseManager
**Purpose**: Handles all MongoDB operations and database interactions.

**Key Features**:
- User management (CRUD operations)
- Game data storage and retrieval
- Transaction tracking
- Balance sheet data aggregation
- Statistics generation

**Usage**:
```python
from features import DatabaseManager

db = DatabaseManager(mongo_uri, database_name)
user = db.get_user(user_id)
games = db.get_active_games()
```

### 2. `pyrogram_client.py` - PyrogramManager
**Purpose**: Manages Pyrogram client for handling edited messages and admin message editing.

**Key Features**:
- Pyrogram client initialization and management
- Message handler setup for edited messages
- Game table detection from new messages
- Winner detection from edited messages
- Admin DM notifications

**Usage**:
```python
from features import PyrogramManager

pyro = PyrogramManager(api_id, api_hash, group_id, admin_ids)
pyro.set_dependencies(database, telegram_bot)
await pyro.start_client()
```

### 3. `game_manager.py` - GameManager
**Purpose**: Handles all game-related operations and logic.

**Key Features**:
- Game creation and management
- Game result processing
- Winner selection handling
- Game data extraction from messages
- Game validation and status updates

**Usage**:
```python
from features import GameManager

game_mgr = GameManager(database, telegram_bot)
game_data = game_mgr.extract_game_data_from_message(message_text, admin_id, msg_id, chat_id)
success = game_mgr.process_game_result(game_id, winner_username)
```

### 4. `user_manager.py` - UserManager
**Purpose**: Manages user accounts, balances, and transactions.

**Key Features**:
- User creation and retrieval
- Balance management (add/withdraw)
- Transaction history
- User statistics and summaries
- User search and ranking

**Usage**:
```python
from features import UserManager

user_mgr = UserManager(database, telegram_bot)
user = user_mgr.get_or_create_user(user_id, username, first_name)
balance = user_mgr.get_user_balance(user_id)
success = user_mgr.add_balance(user_id, amount, admin_id, reason)
```

### 5. `balance_sheet.py` - BalanceSheetManager
**Purpose**: Handles balance sheets, statistics, and financial reporting.

**Key Features**:
- Daily and monthly balance sheets
- Overall bot statistics
- User balance summaries
- Game statistics
- Pinned message management

**Usage**:
```python
from features import BalanceSheetManager

balance_mgr = BalanceSheetManager(database, telegram_bot)
daily_sheet = balance_mgr.get_daily_balance_sheet()
monthly_sheet = balance_mgr.get_monthly_balance_sheet(2024, 8)
stats = balance_mgr.get_overall_statistics(days=30)
```

## Integration

All modules are designed to work together through dependency injection. The main bot class should:

1. Initialize the `DatabaseManager` first
2. Create other managers with database dependency
3. Set up Pyrogram manager with all dependencies
4. Use managers for specific operations

## Benefits of This Structure

1. **Separation of Concerns**: Each module handles a specific aspect of the bot
2. **Maintainability**: Easy to find and modify specific functionality
3. **Testability**: Each module can be tested independently
4. **Reusability**: Modules can be reused in other projects
5. **Scalability**: Easy to add new features by creating new modules

## Adding New Features

To add a new feature:

1. Create a new Python file in the `features/` folder
2. Define a class with clear responsibilities
3. Add the class to `__init__.py`
4. Import and use in the main bot class

## Dependencies

Each module has minimal external dependencies and relies on:
- `database`: MongoDB operations
- `telegram_bot`: Bot instance for Telegram operations
- Standard Python libraries (datetime, logging, etc.)

## Error Handling

All modules include comprehensive error handling and logging to help with debugging and monitoring.
