module.exports = {
    apps: [
        {
            name: "xometry_scraper",
            script: "main.py",
            interpreter: "/home/saladin/xometry_bot/venv/bin/python",
            watch: false,
            autorestart: true,
            restart_delay: 10000
        },
        {
            name: "xometry_telegram",
            script: "bot_app.py",
            interpreter: "/home/saladin/xometry_bot/venv/bin/python",
            watch: false,
            autorestart: true,
            restart_delay: 5000
        }
    ]
}
