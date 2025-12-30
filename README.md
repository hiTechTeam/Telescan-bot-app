# Telescan_bot

Official Telegram bot for the [Telescan] application(https://github.com/hiTechTeam/Telescan-iOS).

The bot generates a unique 8-character authentication code, which is used to securely link a Telegram profile to the Telescan application.

Bot: [@tgtelescan_bot](https://t.me/tgtelescan_bot)

## Features

- Generate new code with the `/start` command or by pressing a button
- Automatic code update (old one becomes invalid)
- Secure server-side code hashing (SHA-256)
- The code is used only once to link a profile

## How to use

1. Open [@tgtelescan_bot](https://t.me/tgtelescan_bot) in Telegram
2. Click **Start** or send `/start`
3. The bot will send you an 8-character code
4. Enter this code in the Telescan application
5. Telegram profile will be successfully linked

If necessary, get a new code - just click `/update_code`

## Technical implementation

- The bot is written in [Python] using the aiogram library
- The code is stored on the server in hashed form (SHA-256)
- When a new code is generated, the previous one is automatically invalidated
- Communication with Telescan API backend for registration and updating of codes

## For developers

Running a bot locally in docker

```shell
git clone https://github.com/hiTechTeam/Telescan-bot-app.git
cd Telescan-bot-app/
make bot-up
```

## Development and contributions

The project is open for contributions. If you want to help:

- Fork the repository
- Create a thread describing the change
- Open Pull Request

Especially useful:

- Improved bot interface
- Adding localizations
- Testing and searching for bugs

## Contacts

- Developer: [r66cha](https://github.com/r66cha)
- Documentation and roadmap: https://github.com/hiTechTeam/Telescan-info
