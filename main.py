import asyncio

import bot

if __name__ == '__main__':
    asyncio.run(bot.setup_database())
    print(f'database created')
    bot.run_bot()