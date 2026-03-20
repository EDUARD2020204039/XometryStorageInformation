module.exports = {
  apps: [{
    name: 'xometry-app',
    script: 'app.py',
    interpreter: 'python3',
    instances: 1,
    autorestart: true,
    watch: false,
    max_memory_restart: '1G',
    env: {
      NODE_ENV: 'production',
      APP_ENV: 'production',
      PORT: 10000,
      GLITCHTIP_DSN: process.env.GLITCHTIP_DSN,
      APP_RELEASE: process.env.APP_RELEASE
    },
    error_file: './logs/err.log',
    out_file: './logs/out.log',
    time: true
  }]
}
