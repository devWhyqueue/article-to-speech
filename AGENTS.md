- Make skill clean code with option --minimal pass without violations after implementation.

- You can take a look at the deployment with command:

Windows:

```
ssh ubuntu@89.168.90.195 -i <user_home>\.ssh\ssh-key-2023-09-20.key
```

User home depends on Windows or WSL.

- Note that on the server there is a pihole instance running and another Telegram bot service deployed, also using nginx. Do not interfere with them.

- Prefer deploying via image rebuild on server, instead of hot-deploying into container. As this uses more disk space, prune occasionally.